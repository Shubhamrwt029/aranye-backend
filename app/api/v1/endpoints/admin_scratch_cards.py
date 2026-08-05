import csv
import io
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentAdmin
from app.core.database import get_db
from app.core.exceptions import ConflictException, NotFoundException, UnauthorizedException
from app.core.security import verify_password
from app.models.marketplace import Shop
from app.models.scratch_card import (
    DistributionJobStatus,
    DistributionMethod,
    ScratchAssignmentStatus,
    ScratchCard,
    ScratchCardAssignment,
    ScratchCardDistributionJob,
    ScratchCardStatus,
)
from app.models.user import User
from app.schemas.admin import DeleteConfirmation
from app.schemas.scratch_card import (
    DistributionEstimate,
    DistributionJobResponse,
    DistributionRequest,
    RedemptionCodeRequest,
    ScratchAnalytics,
    ScratchCardCreate,
    ScratchCardResponse,
    ScratchCardUpdate,
)
from app.services.marketplace_service import MarketplaceService
from app.services.scratch_card_service import ScratchCardService, utcnow

router = APIRouter()
DB = Annotated[AsyncSession, Depends(get_db)]


class LifecycleRequest(BaseModel):
    reason: str = Field(default="Scratch card lifecycle action", min_length=3, max_length=500)


async def audit(
    db: AsyncSession,
    admin: User,
    request: Request,
    action: str,
    resource_id: UUID,
    *,
    before: dict | None = None,
    after: dict | None = None,
    reason: str,
) -> None:
    await MarketplaceService(db).audit(
        admin,
        action,
        "scratch_card",
        resource_id,
        before,
        after,
        reason=reason,
        request_id=request.headers.get("X-Request-ID"),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent", "")[:500] or None,
    )


def snapshot(item: ScratchCard) -> dict:
    return {column.name: getattr(item, column.name) for column in item.__table__.columns}


@router.get("/scratch-cards")
async def list_scratch_cards(
    _: CurrentAdmin,
    db: DB,
    q: str | None = None,
    status_filter: ScratchCardStatus | None = Query(None, alias="status"),
    card_type: str | None = None,
    shop_id: UUID | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    query = select(ScratchCard)
    if q:
        query = query.where(
            or_(
                ScratchCard.title.ilike(f"%{q}%"),
                ScratchCard.subtitle.ilike(f"%{q}%"),
                ScratchCard.coupon_code.ilike(f"%{q}%"),
            )
        )
    if status_filter:
        query = query.where(ScratchCard.status == status_filter)
    if card_type:
        query = query.where(ScratchCard.scratch_card_type == card_type)
    if shop_id:
        query = query.where(ScratchCard.shop_id == shop_id)
    total = int(
        (await db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))) or 0
    )
    items = list(
        (
            await db.scalars(
                query.order_by(ScratchCard.created_at.desc()).limit(limit).offset(offset)
            )
        ).all()
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.post(
    "/scratch-cards",
    response_model=ScratchCardResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_scratch_card(
    data: ScratchCardCreate, admin: CurrentAdmin, request: Request, db: DB
):
    if data.shop_id and not await db.get(Shop, data.shop_id):
        raise NotFoundException("Shop")
    card = ScratchCard(
        **data.model_dump(),
        status=ScratchCardStatus.DRAFT,
        created_by=admin.id,
    )
    db.add(card)
    await db.flush()
    await audit(
        db,
        admin,
        request,
        "scratch_card.created",
        card.id,
        after=snapshot(card),
        reason="Scratch card created",
    )
    return card


@router.get("/scratch-cards/{card_id}", response_model=ScratchCardResponse)
async def get_scratch_card(card_id: UUID, _: CurrentAdmin, db: DB):
    return await ScratchCardService(db).get_card(card_id)


@router.get("/scratch-cards/{card_id}/preview")
async def preview_scratch_card(card_id: UUID, _: CurrentAdmin, db: DB):
    card = await ScratchCardService(db).get_card(card_id)
    shop = await db.get(Shop, card.shop_id) if card.shop_id else None
    return {"scratch_card": card, "shop": shop}


@router.put("/scratch-cards/{card_id}", response_model=ScratchCardResponse)
@router.patch("/scratch-cards/{card_id}", response_model=ScratchCardResponse)
async def update_scratch_card(
    card_id: UUID,
    data: ScratchCardUpdate,
    admin: CurrentAdmin,
    request: Request,
    db: DB,
):
    service = ScratchCardService(db)
    card = await service.get_card(card_id, lock=True)
    if data.expected_updated_at and card.updated_at != data.expected_updated_at:
        raise ConflictException("Scratch card changed since it was loaded")
    if card.status in {ScratchCardStatus.EXPIRED, ScratchCardStatus.ARCHIVED}:
        raise ConflictException("Expired or archived cards cannot be edited")
    before = snapshot(card)
    values = data.model_dump(
        exclude={"expected_updated_at", "reason"}, exclude_unset=True
    )
    for key, value in values.items():
        setattr(card, key, value)
    await service.validate_card(card)
    await audit(
        db,
        admin,
        request,
        "scratch_card.updated",
        card.id,
        before=before,
        after=snapshot(card),
        reason=data.reason,
    )
    return card


@router.delete("/scratch-cards/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scratch_card(
    card_id: UUID,
    data: DeleteConfirmation,
    admin: CurrentAdmin,
    request: Request,
    db: DB,
):
    card = await ScratchCardService(db).get_card(card_id, lock=True)
    if not admin.hashed_password or not verify_password(data.password, admin.hashed_password):
        raise UnauthorizedException("Administrator password is incorrect")
    if data.confirmation.strip() != card.title:
        raise ConflictException(f'Type "{card.title}" exactly to confirm deletion')
    assignments = int(
        (
            await db.scalar(
                select(func.count())
                .select_from(ScratchCardAssignment)
                .where(ScratchCardAssignment.scratch_card_id == card.id)
            )
        )
        or 0
    )
    if card.status != ScratchCardStatus.DRAFT or assignments:
        raise ConflictException("Only unassigned draft scratch cards can be permanently deleted")
    await audit(
        db,
        admin,
        request,
        "scratch_card.permanently_deleted",
        card.id,
        before=snapshot(card),
        reason=data.reason,
    )
    await db.delete(card)


@router.post(
    "/scratch-cards/{card_id}/duplicate",
    response_model=ScratchCardResponse,
    status_code=status.HTTP_201_CREATED,
)
async def duplicate_scratch_card(
    card_id: UUID, admin: CurrentAdmin, request: Request, db: DB
):
    source = await ScratchCardService(db).get_card(card_id)
    excluded = {
        "id",
        "status",
        "created_by",
        "approved_by",
        "approved_at",
        "published_at",
        "total_redeemed",
        "created_at",
        "updated_at",
        "title",
    }
    values = {
        column.name: getattr(source, column.name)
        for column in source.__table__.columns
        if column.name not in excluded
    }
    duplicate = ScratchCard(
        **values,
        title=f"{source.title} (Copy)"[:160],
        status=ScratchCardStatus.DRAFT,
        created_by=admin.id,
    )
    db.add(duplicate)
    await db.flush()
    await audit(
        db,
        admin,
        request,
        "scratch_card.duplicated",
        duplicate.id,
        after=snapshot(duplicate),
        reason=f"Duplicated from {source.id}",
    )
    return duplicate


async def lifecycle_action(
    card_id: UUID,
    target: ScratchCardStatus,
    data: LifecycleRequest,
    admin: User,
    request: Request,
    db: AsyncSession,
) -> ScratchCard:
    card = await ScratchCardService(db).get_card(card_id, lock=True)
    before = snapshot(card)
    now = utcnow()
    if target == ScratchCardStatus.PAUSED and card.status not in {
        ScratchCardStatus.ACTIVE,
        ScratchCardStatus.SCHEDULED,
    }:
        raise ConflictException("Only active or scheduled cards can be paused")
    if target == ScratchCardStatus.ACTIVE:
        if card.status != ScratchCardStatus.PAUSED:
            raise ConflictException("Only paused cards can be resumed")
        target = ScratchCardStatus.SCHEDULED if card.starts_at > now else ScratchCardStatus.ACTIVE
    if target == ScratchCardStatus.EXPIRED:
        if card.status in {ScratchCardStatus.EXPIRED, ScratchCardStatus.ARCHIVED}:
            raise ConflictException("Scratch card is already expired or archived")
        await db.execute(
            ScratchCardAssignment.__table__.update()
            .where(
                ScratchCardAssignment.scratch_card_id == card.id,
                ScratchCardAssignment.status != ScratchAssignmentStatus.REDEEMED,
            )
            .values(status=ScratchAssignmentStatus.EXPIRED, expired_at=now)
        )
    card.status = target
    await audit(
        db,
        admin,
        request,
        f"scratch_card.{target.value}",
        card.id,
        before=before,
        after=snapshot(card),
        reason=data.reason,
    )
    return card


@router.post("/scratch-cards/{card_id}/pause", response_model=ScratchCardResponse)
async def pause_scratch_card(
    card_id: UUID, data: LifecycleRequest, admin: CurrentAdmin, request: Request, db: DB
):
    return await lifecycle_action(
        card_id, ScratchCardStatus.PAUSED, data, admin, request, db
    )


@router.post("/scratch-cards/{card_id}/resume", response_model=ScratchCardResponse)
async def resume_scratch_card(
    card_id: UUID, data: LifecycleRequest, admin: CurrentAdmin, request: Request, db: DB
):
    return await lifecycle_action(
        card_id, ScratchCardStatus.ACTIVE, data, admin, request, db
    )


@router.post("/scratch-cards/{card_id}/expire", response_model=ScratchCardResponse)
async def expire_scratch_card(
    card_id: UUID, data: LifecycleRequest, admin: CurrentAdmin, request: Request, db: DB
):
    return await lifecycle_action(
        card_id, ScratchCardStatus.EXPIRED, data, admin, request, db
    )


@router.post(
    "/scratch-cards/{card_id}/audience-estimate",
    response_model=DistributionEstimate,
)
async def audience_estimate(
    card_id: UUID, data: DistributionRequest, _: CurrentAdmin, db: DB
):
    service = ScratchCardService(db)
    card = await service.get_card(card_id)
    await service.validate_card(card)
    return await service.estimate(card, data)


@router.post(
    "/scratch-cards/{card_id}/assign",
    response_model=DistributionJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def assign_scratch_card(
    card_id: UUID,
    data: DistributionRequest,
    admin: CurrentAdmin,
    request: Request,
    db: DB,
):
    service = ScratchCardService(db)
    card = await service.get_card(card_id, lock=True)
    job = await service.enqueue_distribution(card, data, admin)
    await audit(
        db,
        admin,
        request,
        "scratch_card.distribution_queued",
        card.id,
        after={"job_id": str(job.id), **data.model_dump(mode="json")},
        reason="Audience distribution queued",
    )
    return job


@router.get(
    "/scratch-cards/{card_id}/distribution-jobs",
    response_model=list[DistributionJobResponse],
)
async def distribution_jobs(card_id: UUID, _: CurrentAdmin, db: DB):
    await ScratchCardService(db).get_card(card_id)
    return list(
        (
            await db.scalars(
                select(ScratchCardDistributionJob)
                .where(ScratchCardDistributionJob.scratch_card_id == card_id)
                .order_by(ScratchCardDistributionJob.created_at.desc())
            )
        ).all()
    )


@router.get(
    "/scratch-cards/{card_id}/distribution-jobs/{job_id}",
    response_model=DistributionJobResponse,
)
async def distribution_job(card_id: UUID, job_id: UUID, _: CurrentAdmin, db: DB):
    job = await db.get(ScratchCardDistributionJob, job_id)
    if not job or job.scratch_card_id != card_id:
        raise NotFoundException("Distribution job")
    return job


@router.post(
    "/scratch-cards/{card_id}/distribution-jobs/{job_id}/retry",
    response_model=DistributionJobResponse,
)
async def retry_distribution_job(
    card_id: UUID,
    job_id: UUID,
    admin: CurrentAdmin,
    request: Request,
    db: DB,
):
    job = (
        await db.scalars(
            select(ScratchCardDistributionJob)
            .where(
                ScratchCardDistributionJob.id == job_id,
                ScratchCardDistributionJob.scratch_card_id == card_id,
            )
            .with_for_update()
        )
    ).one_or_none()
    if not job:
        raise NotFoundException("Distribution job")
    if job.status != DistributionJobStatus.FAILED:
        raise ConflictException("Only failed distribution jobs can be retried")
    job.status = DistributionJobStatus.PENDING
    job.error_message = None
    card = await ScratchCardService(db).get_card(card_id)
    card.status = ScratchCardStatus.PUBLISHING
    await audit(
        db,
        admin,
        request,
        "scratch_card.distribution_retried",
        card_id,
        after={"job_id": str(job.id)},
        reason="Distribution retry requested",
    )
    return job


async def assignment_query(card_id: UUID, q: str | None, status_filter: str | None):
    query = (
        select(ScratchCardAssignment, User)
        .join(User, User.id == ScratchCardAssignment.user_id)
        .where(ScratchCardAssignment.scratch_card_id == card_id)
    )
    if q:
        query = query.where(
            or_(
                User.name.ilike(f"%{q}%"),
                User.phone.ilike(f"%{q}%"),
                User.email.ilike(f"%{q}%"),
                ScratchCardAssignment.redemption_code.ilike(f"%{q}%"),
            )
        )
    if status_filter:
        query = query.where(ScratchCardAssignment.status == status_filter)
    return query


@router.get("/scratch-cards/{card_id}/assignments")
async def assignments(
    card_id: UUID,
    _: CurrentAdmin,
    db: DB,
    q: str | None = None,
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    await ScratchCardService(db).get_card(card_id)
    query = await assignment_query(card_id, q, status_filter)
    total = int(
        (await db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))) or 0
    )
    rows = (
        await db.execute(
            query.order_by(ScratchCardAssignment.assigned_at.desc()).limit(limit).offset(offset)
        )
    ).all()
    return {
        "items": [
            {
                **{
                    column.name: getattr(assignment, column.name)
                    for column in assignment.__table__.columns
                },
                "user": {
                    "id": user.id,
                    "name": user.name,
                    "phone": user.phone,
                    "email": user.email,
                },
            }
            for assignment, user in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/scratch-cards/{card_id}/assignments.csv")
async def assignments_csv(card_id: UUID, _: CurrentAdmin, db: DB):
    card = await ScratchCardService(db).get_card(card_id)
    rows = (
        await db.execute(
            (await assignment_query(card_id, None, None)).order_by(
                ScratchCardAssignment.assigned_at
            )
        )
    ).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "assignment_id",
            "user_id",
            "name",
            "phone",
            "email",
            "method",
            "status",
            "assigned_at",
            "viewed_at",
            "scratched_at",
            "redeemed_at",
        ]
    )
    for assignment, user in rows:
        writer.writerow(
            [
                assignment.id,
                user.id,
                user.name,
                user.phone,
                user.email,
                assignment.distribution_method.value,
                assignment.status.value,
                assignment.assigned_at,
                assignment.viewed_at,
                assignment.scratched_at,
                assignment.redeemed_at,
            ]
        )
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="scratch-{card.title}-assignments.csv"'
        },
    )


@router.get("/scratch-cards/{card_id}/analytics", response_model=ScratchAnalytics)
async def analytics(card_id: UUID, _: CurrentAdmin, db: DB):
    await ScratchCardService(db).get_card(card_id)
    assignments_table = ScratchCardAssignment
    totals = (
        await db.execute(
            select(
                func.count(assignments_table.id),
                func.count(assignments_table.viewed_at),
                func.count(assignments_table.scratched_at),
                func.count(assignments_table.redeemed_at),
                func.count(assignments_table.expired_at),
            ).where(assignments_table.scratch_card_id == card_id)
        )
    ).one()
    assigned, viewed, scratched, redeemed, expired = map(int, totals)
    reach_rows = (
        await db.execute(
            select(assignments_table.distribution_method, func.count())
            .where(assignments_table.scratch_card_id == card_id)
            .group_by(assignments_table.distribution_method)
        )
    ).all()
    reach = {method.value: int(count) for method, count in reach_rows}
    daily_rows = (
        await db.execute(
            select(
                func.date(assignments_table.assigned_at).label("day"),
                func.count(assignments_table.id).label("assigned"),
                func.count(assignments_table.viewed_at).label("viewed"),
                func.count(assignments_table.scratched_at).label("scratched"),
                func.count(assignments_table.redeemed_at).label("redeemed"),
            )
            .where(assignments_table.scratch_card_id == card_id)
            .group_by(func.date(assignments_table.assigned_at))
            .order_by(func.date(assignments_table.assigned_at))
        )
    ).all()
    return {
        "total_assigned": assigned,
        "total_viewed": viewed,
        "total_scratched": scratched,
        "total_redeemed": redeemed,
        "expired": expired,
        "unused": max(0, assigned - scratched - expired),
        "ctr": round(viewed * 100 / assigned, 2) if assigned else 0,
        "scratch_conversion": round(scratched * 100 / viewed, 2) if viewed else 0,
        "redemption_rate": round(redeemed * 100 / scratched, 2) if scratched else 0,
        "distribution_reach": reach,
        "nearby_reach": reach.get(DistributionMethod.NEARBY.value, 0)
        + reach.get(DistributionMethod.NEARBY_QUANTITY.value, 0),
        "random_reach": reach.get(DistributionMethod.RANDOM.value, 0),
        "daily_stats": [
            {
                "date": row.day.isoformat(),
                "assigned": int(row.assigned),
                "viewed": int(row.viewed),
                "scratched": int(row.scratched),
                "redeemed": int(row.redeemed),
            }
            for row in daily_rows
        ],
    }


@router.post("/scratch-cards/redemptions/preview")
async def admin_redemption_preview(
    data: RedemptionCodeRequest, admin: CurrentAdmin, db: DB
):
    assignment, card, customer = await ScratchCardService(db).redemption_preview(
        data.redemption_code, admin
    )
    return {
        "assignment_id": assignment.id,
        "scratch_card_id": card.id,
        "title": card.title,
        "customer_name": customer.name,
        "customer_phone": customer.phone,
        "expires_at": card.expires_at,
        "status": assignment.status,
        "redeemed_at": assignment.redeemed_at,
    }


@router.post("/scratch-cards/redemptions/redeem")
async def admin_redeem(data: RedemptionCodeRequest, admin: CurrentAdmin, db: DB):
    assignment, card, customer = await ScratchCardService(db).redeem(
        data.redemption_code, admin
    )
    return {
        "assignment_id": assignment.id,
        "scratch_card_id": card.id,
        "title": card.title,
        "customer_name": customer.name,
        "customer_phone": customer.phone,
        "expires_at": card.expires_at,
        "status": assignment.status,
        "redeemed_at": assignment.redeemed_at,
    }
