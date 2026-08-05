import math
import json
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import String, and_, cast, func, literal, not_, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException, ForbiddenException, NotFoundException
from app.models.marketplace import Address, Notification, Shop
from app.models.scratch_card import (
    DistributionJobStatus,
    DistributionMethod,
    ScratchAssignmentStatus,
    ScratchCard,
    ScratchCardAssignment,
    ScratchCardDistributionJob,
    ScratchCardStatus,
)
from app.models.user import User, UserRole
from app.schemas.scratch_card import DistributionEstimate, DistributionRequest


VISIBLE_CARD_STATUSES = {ScratchCardStatus.ACTIVE}
REDEEMABLE_ASSIGNMENT_STATUSES = {
    ScratchAssignmentStatus.SCRATCHED,
}


def utcnow() -> datetime:
    return datetime.now(UTC)


class ScratchCardService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_card(self, card_id: UUID, *, lock: bool = False) -> ScratchCard:
        query = select(ScratchCard).where(ScratchCard.id == card_id)
        if lock:
            query = query.with_for_update()
        card = (await self.db.scalars(query)).one_or_none()
        if not card:
            raise NotFoundException("Scratch card")
        return card

    async def validate_card(self, card: ScratchCard) -> None:
        if card.ends_at <= card.starts_at:
            raise ConflictException("Scratch card end date must be after its start date")
        if card.expires_at < card.ends_at:
            raise ConflictException("Scratch card expiry must include the campaign end date")
        if card.scratch_card_type.value == "shopkeeper_promotion" and not card.shop_id:
            raise ConflictException("Shopkeeper promotions require a shop")
        if card.reward_type.strip().lower().replace(" ", "_") == "free_product" and not card.shop_id:
            raise ConflictException("Physical free-product rewards require a fulfillment shop")
        if card.shop_id and not await self.db.get(Shop, card.shop_id):
            raise NotFoundException("Shop")
        if card.coupon_type == "shared" and not card.coupon_code:
            raise ConflictException("Shared coupons require a coupon code")

    def _base_candidate_query(
        self,
        card: ScratchCard,
        request: DistributionRequest,
        *,
        exclude_assigned: bool,
    ):
        query = select(User.id).where(
            User.role == UserRole.CUSTOMER,
            User.is_active.is_(True),
        )
        method = request.distribution_method

        if method in {DistributionMethod.NEARBY, DistributionMethod.NEARBY_QUANTITY}:
            query = query.join(Address, Address.user_id == User.id)
        elif method == DistributionMethod.AREA:
            query = query.join(Address, Address.user_id == User.id).where(
                func.lower(func.trim(Address.area)) == request.area.strip().lower(),
                func.lower(func.trim(Address.city)) == request.city.strip().lower(),
            )
        elif method == DistributionMethod.TARGETED:
            query = query.where(User.id.in_(request.user_ids))
        elif method == DistributionMethod.BIRTHDAY:
            today = date.today()
            query = query.where(
                func.extract("month", User.date_of_birth) == today.month,
                func.extract("day", User.date_of_birth) == today.day,
            )

        if exclude_assigned:
            assigned = select(ScratchCardAssignment.id).where(
                ScratchCardAssignment.scratch_card_id == card.id,
                ScratchCardAssignment.user_id == User.id,
            )
            query = query.where(not_(assigned.exists()))
        return query.distinct()

    async def _nearby_query(self, card: ScratchCard, request: DistributionRequest, query):
        if not card.shop_id:
            raise ConflictException("Nearby distribution requires a selected shop")
        shop = await self.db.get(Shop, card.shop_id)
        if not shop:
            raise NotFoundException("Shop")
        radius = float(request.radius_km or 0)
        latitude = float(shop.latitude)
        longitude = float(shop.longitude)
        latitude_delta = radius / 111.0
        longitude_scale = max(0.1, math.cos(math.radians(latitude)))
        longitude_delta = radius / (111.0 * longitude_scale)

        lat = Address.latitude
        lon = Address.longitude
        distance = 6371.0 * 2.0 * func.asin(
            func.sqrt(
                func.power(func.sin(func.radians(lat - latitude) / 2.0), 2)
                + func.cos(func.radians(latitude))
                * func.cos(func.radians(lat))
                * func.power(func.sin(func.radians(lon - longitude) / 2.0), 2)
            )
        )
        return query.where(
            Address.latitude.between(latitude - latitude_delta, latitude + latitude_delta),
            Address.longitude.between(longitude - longitude_delta, longitude + longitude_delta),
            distance <= radius,
        )

    async def candidate_query(
        self,
        card: ScratchCard,
        request: DistributionRequest,
        *,
        exclude_assigned: bool,
    ):
        query = self._base_candidate_query(card, request, exclude_assigned=exclude_assigned)
        if request.distribution_method in {
            DistributionMethod.NEARBY,
            DistributionMethod.NEARBY_QUANTITY,
        }:
            query = await self._nearby_query(card, request, query)
        return query

    async def estimate(
        self, card: ScratchCard, request: DistributionRequest
    ) -> DistributionEstimate:
        eligible_query = await self.candidate_query(card, request, exclude_assigned=False)
        assignable_query = await self.candidate_query(card, request, exclude_assigned=True)
        eligible = int(
            (await self.db.scalar(select(func.count()).select_from(eligible_query.subquery()))) or 0
        )
        assignable = int(
            (await self.db.scalar(select(func.count()).select_from(assignable_query.subquery()))) or 0
        )
        return DistributionEstimate(
            eligible_count=eligible,
            already_assigned_count=eligible - assignable,
            assignable_count=assignable,
            requested_quantity=request.quantity,
        )

    async def enqueue_distribution(
        self, card: ScratchCard, request: DistributionRequest, admin: User
    ) -> ScratchCardDistributionJob:
        await self.validate_card(card)
        if card.status in {
            ScratchCardStatus.PAUSED,
            ScratchCardStatus.EXPIRED,
            ScratchCardStatus.ARCHIVED,
        }:
            raise ConflictException("Paused, expired, or archived scratch cards cannot be distributed")
        if card.expires_at <= utcnow():
            raise ConflictException("Scratch card has already expired")
        running = await self.db.scalar(
            select(func.count())
            .select_from(ScratchCardDistributionJob)
            .where(
                ScratchCardDistributionJob.scratch_card_id == card.id,
                ScratchCardDistributionJob.status.in_(
                    [DistributionJobStatus.PENDING, DistributionJobStatus.RUNNING]
                ),
            )
        )
        if running:
            raise ConflictException("A distribution job is already pending for this scratch card")

        job = ScratchCardDistributionJob(
            scratch_card_id=card.id,
            distribution_method=request.distribution_method,
            filters=request.job_filters(),
            requested_quantity=request.quantity,
            created_by=admin.id,
        )
        if card.status in {
            ScratchCardStatus.DRAFT,
            ScratchCardStatus.FAILED,
        }:
            card.status = ScratchCardStatus.PUBLISHING
        card.approved_by = admin.id
        card.approved_at = utcnow()
        self.db.add(job)
        await self.db.flush()
        return job

    @staticmethod
    def request_from_job(job: ScratchCardDistributionJob) -> DistributionRequest:
        return DistributionRequest(
            distribution_method=job.distribution_method,
            quantity=job.requested_quantity,
            **job.filters,
        )

    async def process_job(self, job: ScratchCardDistributionJob) -> None:
        now = utcnow()
        card = await self.get_card(job.scratch_card_id, lock=True)
        request = self.request_from_job(job)
        candidate_query = await self.candidate_query(card, request, exclude_assigned=True)
        candidate_subquery = candidate_query.subquery()
        job.eligible_count = int(
            (await self.db.scalar(select(func.count()).select_from(candidate_subquery))) or 0
        )

        deterministic_order = func.md5(
            cast(candidate_subquery.c.id, String) + literal(str(job.id))
        )
        selection_query = select(candidate_subquery.c.id).order_by(deterministic_order)
        if request.quantity:
            selection_query = selection_query.limit(request.quantity)
        selected = selection_query.subquery()
        assignment_id = cast(
            func.md5(cast(selected.c.id, String) + literal(str(job.id))),
            PG_UUID(as_uuid=True),
        )
        code_entropy = (
            cast(selected.c.id, String)
            + literal(str(job.id))
            + cast(func.random(), String)
            + cast(func.clock_timestamp(), String)
        )
        generated_code = func.upper(func.substr(func.md5(code_entropy), 1, 16))
        if card.redemption_code_prefix:
            generated_code = (
                literal(f"{card.redemption_code_prefix}-")
                + func.upper(func.substr(func.md5(code_entropy), 1, 10))
            )
        assignment_select = select(
            assignment_id,
            literal(card.id),
            selected.c.id,
            literal(job.id),
            cast(
                literal(job.distribution_method.value),
                ScratchCardAssignment.__table__.c.distribution_method.type,
            ),
            literal(job.created_by),
            cast(
                literal(ScratchAssignmentStatus.ASSIGNED.value),
                ScratchCardAssignment.__table__.c.status.type,
            ),
            generated_code,
        )
        insert_assignments = (
            pg_insert(ScratchCardAssignment)
            .from_select(
                [
                    "id",
                    "scratch_card_id",
                    "user_id",
                    "distribution_job_id",
                    "distribution_method",
                    "assigned_by",
                    "status",
                    "redemption_code",
                ],
                assignment_select,
            )
            .on_conflict_do_nothing()
        )
        assignment_result = await self.db.execute(insert_assignments)
        job.assigned_count = max(0, assignment_result.rowcount or 0)

        if job.assigned_count:
            assigned_to_job = select(
                cast(
                    func.md5(
                        cast(ScratchCardAssignment.id, String)
                        + literal("notification")
                    ),
                    PG_UUID(as_uuid=True),
                ),
                ScratchCardAssignment.user_id,
                literal("You have a new scratch card"),
                literal(card.title),
                cast(
                    literal(
                        json.dumps(
                            {
                                "action": "scratch_card",
                                "scratch_card_id": str(card.id),
                            }
                        )
                    ),
                    JSONB,
                ),
            ).where(ScratchCardAssignment.distribution_job_id == job.id)
            await self.db.execute(
                pg_insert(Notification).from_select(
                    ["id", "user_id", "title", "body", "data"],
                    assigned_to_job,
                )
            )

        selected_count = (
            min(job.eligible_count, request.quantity)
            if request.quantity
            else job.eligible_count
        )
        job.skipped_count = max(0, selected_count - job.assigned_count)
        job.status = DistributionJobStatus.COMPLETED
        job.completed_at = now
        card.published_at = card.published_at or now
        card.status = (
            ScratchCardStatus.SCHEDULED
            if card.starts_at > now
            else ScratchCardStatus.ACTIVE
        )

    async def process_next_job(self) -> UUID | None:
        job = (
            await self.db.scalars(
                select(ScratchCardDistributionJob)
                .where(
                    or_(
                        ScratchCardDistributionJob.status == DistributionJobStatus.PENDING,
                        and_(
                            ScratchCardDistributionJob.status == DistributionJobStatus.FAILED,
                            ScratchCardDistributionJob.attempts
                            < ScratchCardDistributionJob.max_attempts,
                        ),
                    )
                )
                .order_by(ScratchCardDistributionJob.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
        ).one_or_none()
        if not job:
            return None
        job.status = DistributionJobStatus.RUNNING
        job.started_at = utcnow()
        job.attempts += 1
        job.error_message = None
        await self.db.flush()
        try:
            # A statement-level PostgreSQL error aborts its transaction. Keep each
            # attempt in a savepoint so retry state can still be persisted.
            async with self.db.begin_nested():
                await self.process_job(job)
        except Exception as exc:
            await self.db.refresh(job)
            job.status = DistributionJobStatus.FAILED
            job.error_message = str(exc)[:4000]
            job.failed_count += 1
            card = await self.db.get(ScratchCard, job.scratch_card_id)
            if card and card.status == ScratchCardStatus.PUBLISHING:
                card.status = ScratchCardStatus.FAILED
            await self.db.flush()
        return job.id

    async def maintain_lifecycle(self) -> dict[str, int]:
        now = utcnow()
        activated = await self.db.execute(
            ScratchCard.__table__.update()
            .where(
                ScratchCard.status == ScratchCardStatus.SCHEDULED,
                ScratchCard.starts_at <= now,
            )
            .values(status=ScratchCardStatus.ACTIVE)
        )
        expired_cards = await self.db.execute(
            ScratchCard.__table__.update()
            .where(
                ScratchCard.status.in_(
                    [
                        ScratchCardStatus.ACTIVE,
                        ScratchCardStatus.SCHEDULED,
                        ScratchCardStatus.PAUSED,
                    ]
                ),
                ScratchCard.expires_at < now,
            )
            .values(status=ScratchCardStatus.EXPIRED)
            .returning(ScratchCard.id)
        )
        expired_ids = list(expired_cards.scalars())
        expired_assignments = 0
        if expired_ids:
            result = await self.db.execute(
                ScratchCardAssignment.__table__.update()
                .where(
                    ScratchCardAssignment.scratch_card_id.in_(expired_ids),
                    ScratchCardAssignment.status != ScratchAssignmentStatus.REDEEMED,
                )
                .values(status=ScratchAssignmentStatus.EXPIRED, expired_at=now)
            )
            expired_assignments = result.rowcount or 0
        return {
            "activated": activated.rowcount or 0,
            "expired_cards": len(expired_ids),
            "expired_assignments": expired_assignments,
        }

    async def customer_assignment(
        self, assignment_id: UUID, user: User, *, lock: bool = False
    ) -> tuple[ScratchCardAssignment, ScratchCard, Shop | None]:
        query = (
            select(ScratchCardAssignment, ScratchCard, Shop)
            .join(ScratchCard, ScratchCard.id == ScratchCardAssignment.scratch_card_id)
            .outerjoin(Shop, Shop.id == ScratchCard.shop_id)
            .where(
                ScratchCardAssignment.id == assignment_id,
                ScratchCardAssignment.user_id == user.id,
            )
        )
        if lock:
            query = query.with_for_update(of=ScratchCardAssignment)
        row = (await self.db.execute(query)).one_or_none()
        if not row:
            raise NotFoundException("Scratch card assignment")
        return row

    @staticmethod
    def list_item(
        assignment: ScratchCardAssignment, card: ScratchCard, shop: Shop | None
    ) -> dict[str, Any]:
        return {
            "assignment_id": assignment.id,
            "scratch_card_id": card.id,
            "title": card.title,
            "subtitle": card.subtitle,
            "image_url": card.image_url,
            "banner_url": card.banner_url,
            "reward_type": card.reward_type,
            "offer_type": card.offer_type,
            "expires_at": card.expires_at,
            "priority": card.priority,
            "status": assignment.status,
            "scratched": assignment.scratched_at is not None,
            "redeemed": assignment.redeemed_at is not None,
            "shop_id": card.shop_id,
            "shop_name": shop.name if shop else None,
        }

    @classmethod
    def reveal_item(
        cls, assignment: ScratchCardAssignment, card: ScratchCard, shop: Shop | None
    ) -> dict[str, Any]:
        return {
            **cls.list_item(assignment, card, shop),
            "description": card.description,
            "terms_and_conditions": card.terms_and_conditions,
            "coupon_code": card.coupon_code,
            "coupon_type": card.coupon_type,
            "redemption_code": assignment.redemption_code,
        }

    async def mark_viewed(self, assignment_id: UUID, user: User) -> dict[str, Any]:
        assignment, card, shop = await self.customer_assignment(assignment_id, user, lock=True)
        self.ensure_customer_visible(card, assignment)
        if assignment.viewed_at is None:
            assignment.viewed_at = utcnow()
            if assignment.status == ScratchAssignmentStatus.ASSIGNED:
                assignment.status = ScratchAssignmentStatus.VIEWED
        return self.list_item(assignment, card, shop)

    async def scratch(self, assignment_id: UUID, user: User) -> dict[str, Any]:
        assignment, card, shop = await self.customer_assignment(assignment_id, user, lock=True)
        self.ensure_customer_visible(card, assignment)
        now = utcnow()
        if assignment.viewed_at is None:
            assignment.viewed_at = now
        if assignment.scratched_at is None:
            assignment.scratched_at = now
            assignment.status = ScratchAssignmentStatus.SCRATCHED
        return self.reveal_item(assignment, card, shop)

    @staticmethod
    def ensure_customer_visible(
        card: ScratchCard, assignment: ScratchCardAssignment
    ) -> None:
        now = utcnow()
        if card.status not in VISIBLE_CARD_STATUSES or not (
            card.starts_at <= now <= card.expires_at
        ):
            raise ConflictException("Scratch card is not currently available")
        if assignment.scratched_at is None and now > card.ends_at:
            raise ConflictException("Scratch card campaign has ended")
        if assignment.status == ScratchAssignmentStatus.EXPIRED:
            raise ConflictException("Scratch card assignment has expired")

    async def redemption_preview(
        self, redemption_code: str, actor: User
    ) -> tuple[ScratchCardAssignment, ScratchCard, User]:
        row = (
            await self.db.execute(
                select(ScratchCardAssignment, ScratchCard, User)
                .join(ScratchCard, ScratchCard.id == ScratchCardAssignment.scratch_card_id)
                .join(User, User.id == ScratchCardAssignment.user_id)
                .where(
                    ScratchCardAssignment.redemption_code == redemption_code.strip().upper()
                )
            )
        ).one_or_none()
        if not row:
            raise NotFoundException("Redemption code")
        assignment, card, customer = row
        if actor.role == UserRole.SHOPKEEPER:
            shop = (
                await self.db.scalars(select(Shop).where(Shop.owner_id == actor.id))
            ).one_or_none()
            if not shop or card.shop_id != shop.id:
                raise ForbiddenException("This code does not belong to your shop")
        elif actor.role == UserRole.ADMIN:
            if card.shop_id:
                raise ForbiddenException("Shop-linked rewards must be redeemed by that shop")
        else:
            raise ForbiddenException("Only shopkeepers or administrators can redeem codes")
        return assignment, card, customer

    async def redeem(self, redemption_code: str, actor: User) -> tuple:
        preview_assignment, _, _ = await self.redemption_preview(redemption_code, actor)
        assignment = (
            await self.db.scalars(
                select(ScratchCardAssignment)
                .where(ScratchCardAssignment.id == preview_assignment.id)
                .with_for_update()
            )
        ).one()
        card = await self.get_card(assignment.scratch_card_id, lock=True)
        customer = await self.db.get(User, assignment.user_id)
        now = utcnow()
        if assignment.redeemed_at:
            return assignment, card, customer
        if assignment.status not in REDEEMABLE_ASSIGNMENT_STATUSES:
            raise ConflictException("Scratch card must be revealed before redemption")
        if card.status != ScratchCardStatus.ACTIVE or not (
            card.starts_at <= now <= card.expires_at
        ):
            raise ConflictException("Scratch card is not redeemable")
        if card.total_redemption_limit and card.total_redeemed >= card.total_redemption_limit:
            raise ConflictException("Total redemption limit has been reached")
        if card.daily_redemption_limit:
            today_count = int(
                (
                    await self.db.scalar(
                        select(func.count())
                        .select_from(ScratchCardAssignment)
                        .where(
                            ScratchCardAssignment.scratch_card_id == card.id,
                            func.date(ScratchCardAssignment.redeemed_at) == now.date(),
                        )
                    )
                )
                or 0
            )
            if today_count >= card.daily_redemption_limit:
                raise ConflictException("Daily redemption limit has been reached")
        assignment.status = ScratchAssignmentStatus.REDEEMED
        assignment.redeemed_at = now
        card.total_redeemed += 1
        return assignment, card, customer
