"""PostgreSQL-only integration tests for scratch-card distribution and redemption.

Run with:
TEST_DATABASE_URL=postgresql+asyncpg://127.0.0.1:55432/aranye_verify \
  pytest tests/test_scratch_card_postgres.py
"""

import asyncio
import os
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.exceptions import ConflictException
from app.models.marketplace import Address, AuditLog, Notification, Shop, ShopStatus
from app.models.scratch_card import (
    DistributionJobStatus,
    DistributionMethod,
    ScratchAssignmentStatus,
    ScratchCard,
    ScratchCardAssignment,
    ScratchCardDistributionJob,
    ScratchCardStatus,
    ScratchCardType,
)
from app.models.user import User, UserRole
from app.schemas.scratch_card import DistributionRequest
from app.services.scratch_card_service import ScratchCardService
from app.services.marketplace_service import MarketplaceService


DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="TEST_DATABASE_URL is required for PostgreSQL integration tests",
)


def make_user(role: UserRole, number: int, **values) -> User:
    defaults = {
        "id": uuid.uuid4(),
        "role": role,
        "phone": f"9000{number:06d}",
        "name": f"User {number}",
        "is_active": True,
        "is_profile_complete": True,
        "is_phone_verified": True,
    }
    defaults.update(values)
    return User(**defaults)


def make_card(admin: User, *, shop: Shop | None = None, **values) -> ScratchCard:
    now = datetime.now(UTC)
    defaults = {
        "id": uuid.uuid4(),
        "title": f"Integration card {uuid.uuid4().hex[:8]}",
        "reward_type": "coupon",
        "coupon_type": "unique",
        "starts_at": now - timedelta(minutes=5),
        "ends_at": now + timedelta(days=2),
        "expires_at": now + timedelta(days=3),
        "status": ScratchCardStatus.DRAFT,
        "priority": 100,
        "scratch_card_type": (
            ScratchCardType.SHOPKEEPER_PROMOTION
            if shop
            else ScratchCardType.ADMIN_REWARD
        ),
        "shop_id": shop.id if shop else None,
        "created_by": admin.id,
        "total_redeemed": 0,
    }
    defaults.update(values)
    return ScratchCard(**defaults)


@pytest.fixture
async def sessions():
    engine = create_async_engine(DATABASE_URL, pool_size=10, max_overflow=10)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE TABLE users CASCADE"))
    try:
        yield factory
    finally:
        await engine.dispose()


async def publish(factory, card, admin, request):
    async with factory() as session:
        db_card = await session.get(ScratchCard, card.id)
        db_admin = await session.get(User, admin.id)
        job = await ScratchCardService(session).enqueue_distribution(
            db_card, request, db_admin
        )
        job_id = job.id
        await session.commit()
    async with factory() as session:
        job = await session.get(ScratchCardDistributionJob, job_id)
        await ScratchCardService(session).process_job(job)
        await session.commit()
    return job_id


@pytest.mark.asyncio
async def test_all_distribution_methods_deduplicate_and_notify(sessions):
    factory = sessions
    today = date.today()
    admin = make_user(UserRole.ADMIN, 1, email="scratch-admin@example.test", phone=None)
    owner = make_user(UserRole.SHOPKEEPER, 2)
    customers = [
        make_user(
            UserRole.CUSTOMER,
            number,
            date_of_birth=today if number == 10 else date(1990, 1, 1),
        )
        for number in range(10, 16)
    ]
    inactive = make_user(UserRole.CUSTOMER, 20, is_active=False)
    shop = Shop(
        id=uuid.uuid4(),
        owner_id=owner.id,
        name="Scratch Integration Shop",
        business_type="grocery",
        phone="9111111111",
        address_line="Market Road",
        area="Central",
        city="Test City",
        postal_code="100001",
        latitude=Decimal("28.613900"),
        longitude=Decimal("77.209000"),
        status=ShopStatus.ACTIVE,
    )
    addresses = [
        Address(
            user_id=customers[0].id,
            label="Home",
            line1="One",
            area=" Central ",
            city=" TEST CITY ",
            state="Test",
            postal_code="100001",
            latitude=Decimal("28.614000"),
            longitude=Decimal("77.209100"),
        ),
        # A second matching address proves a customer is still assigned once.
        Address(
            user_id=customers[0].id,
            label="Work",
            line1="Two",
            area="Central",
            city="Test City",
            state="Test",
            postal_code="100001",
            latitude=Decimal("28.614100"),
            longitude=Decimal("77.209200"),
        ),
        Address(
            user_id=customers[1].id,
            label="Home",
            line1="Three",
            area="Central",
            city="Test City",
            state="Test",
            postal_code="100001",
            latitude=Decimal("28.620000"),
            longitude=Decimal("77.210000"),
        ),
        Address(
            user_id=customers[2].id,
            label="Home",
            line1="Far",
            area="Outer",
            city="Test City",
            state="Test",
            postal_code="100002",
            latitude=Decimal("29.500000"),
            longitude=Decimal("78.000000"),
        ),
    ]
    async with factory() as session:
        session.add_all([admin, owner, *customers, inactive])
        await session.flush()
        session.add(shop)
        await session.flush()
        session.add_all(addresses)
        cards = {
            method: make_card(
                admin,
                shop=shop
                if method in {DistributionMethod.NEARBY, DistributionMethod.NEARBY_QUANTITY}
                else None,
            )
            for method in DistributionMethod
        }
        session.add_all(cards.values())
        await session.commit()

    requests = {
        DistributionMethod.RANDOM: DistributionRequest(
            distribution_method=DistributionMethod.RANDOM, quantity=3
        ),
        DistributionMethod.NEARBY: DistributionRequest(
            distribution_method=DistributionMethod.NEARBY, radius_km=5
        ),
        DistributionMethod.NEARBY_QUANTITY: DistributionRequest(
            distribution_method=DistributionMethod.NEARBY_QUANTITY,
            radius_km=5,
            quantity=1,
        ),
        DistributionMethod.TARGETED: DistributionRequest(
            distribution_method=DistributionMethod.TARGETED,
            user_ids=[customers[3].id, customers[4].id],
        ),
        DistributionMethod.BIRTHDAY: DistributionRequest(
            distribution_method=DistributionMethod.BIRTHDAY, quantity=5
        ),
        DistributionMethod.AREA: DistributionRequest(
            distribution_method=DistributionMethod.AREA,
            area="central",
            city="test city",
        ),
    }
    job_ids = {}
    for method, request in requests.items():
        job_ids[method] = await publish(factory, cards[method], admin, request)

    async with factory() as session:
        jobs = {
            job.distribution_method: job
            for job in (
                await session.scalars(
                    select(ScratchCardDistributionJob).where(
                        ScratchCardDistributionJob.id.in_(job_ids.values())
                    )
                )
            )
        }
        assert jobs[DistributionMethod.RANDOM].assigned_count == 3
        assert jobs[DistributionMethod.NEARBY].assigned_count == 2
        assert jobs[DistributionMethod.NEARBY_QUANTITY].assigned_count == 1
        assert jobs[DistributionMethod.TARGETED].assigned_count == 2
        assert jobs[DistributionMethod.BIRTHDAY].assigned_count == 1
        assert jobs[DistributionMethod.AREA].assigned_count == 2
        assert all(job.status == DistributionJobStatus.COMPLETED for job in jobs.values())
        assignment_count = int(
            await session.scalar(select(func.count()).select_from(ScratchCardAssignment))
        )
        notification_count = int(
            await session.scalar(select(func.count()).select_from(Notification))
        )
        assert assignment_count == notification_count == 11
        assert int(
            await session.scalar(
                select(func.count(func.distinct(ScratchCardAssignment.redemption_code)))
            )
        ) == assignment_count

    # A repeated run permanently preserves the audience mapping and assigns nobody twice.
    rerun_id = await publish(
        factory,
        cards[DistributionMethod.AREA],
        admin,
        requests[DistributionMethod.AREA],
    )
    async with factory() as session:
        rerun = await session.get(ScratchCardDistributionJob, rerun_id)
        assert rerun.eligible_count == 0
        assert rerun.assigned_count == 0


@pytest.mark.asyncio
async def test_scratch_and_redemption_are_idempotent_and_limit_is_atomic(sessions):
    factory = sessions
    admin = make_user(UserRole.ADMIN, 1, email="redeem-admin@example.test", phone=None)
    owner = make_user(UserRole.SHOPKEEPER, 2)
    customers = [make_user(UserRole.CUSTOMER, number) for number in (10, 11)]
    shop = Shop(
        id=uuid.uuid4(),
        owner_id=owner.id,
        name="Atomic Redemption Shop",
        business_type="grocery",
        phone="9222222222",
        address_line="Market Road",
        area="Central",
        city="Test City",
        postal_code="100001",
        latitude=Decimal("28.613900"),
        longitude=Decimal("77.209000"),
        status=ShopStatus.ACTIVE,
    )
    card = make_card(
        admin,
        shop=shop,
        daily_redemption_limit=1,
        total_redemption_limit=2,
        redemption_code_prefix="SHOP26",
    )
    async with factory() as session:
        session.add_all([admin, owner, *customers])
        await session.flush()
        session.add(shop)
        await session.flush()
        session.add(card)
        await session.commit()
    await publish(
        factory,
        card,
        admin,
        DistributionRequest(
            distribution_method=DistributionMethod.TARGETED,
            user_ids=[customer.id for customer in customers],
        ),
    )
    async with factory() as session:
        assignments = list(
            await session.scalars(
                select(ScratchCardAssignment).order_by(ScratchCardAssignment.user_id)
            )
        )
        for assignment in assignments:
            customer = await session.get(User, assignment.user_id)
            first = await ScratchCardService(session).scratch(assignment.id, customer)
            second = await ScratchCardService(session).scratch(assignment.id, customer)
            assert first["redemption_code"] == second["redemption_code"]
        codes = [assignment.redemption_code for assignment in assignments]
        assert all(code.startswith("SHOP26-") and len(code) == 17 for code in codes)
        await session.commit()

    async def redeem(code):
        async with factory() as session:
            actor = await session.get(User, owner.id)
            try:
                assignment, _, _ = await ScratchCardService(session).redeem(code, actor)
                await session.commit()
                return assignment.id
            except ConflictException:
                await session.rollback()
                return None

    results = await asyncio.gather(*(redeem(code) for code in codes))
    assert sum(result is not None for result in results) == 1
    winning_code = codes[results.index(next(result for result in results if result is not None))]
    first_id = await redeem(winning_code)
    assert first_id is not None
    async with factory() as session:
        db_card = await session.get(ScratchCard, card.id)
        assert db_card.total_redeemed == 1
        assert int(
            await session.scalar(
                select(func.count())
                .select_from(ScratchCardAssignment)
                .where(ScratchCardAssignment.status == ScratchAssignmentStatus.REDEEMED)
            )
        ) == 1


@pytest.mark.asyncio
async def test_skip_locked_workers_claim_different_jobs_and_failures_retry(sessions):
    factory = sessions
    admin = make_user(UserRole.ADMIN, 1, email="worker-admin@example.test", phone=None)
    customers = [make_user(UserRole.CUSTOMER, number) for number in range(10, 14)]
    cards = [make_card(admin), make_card(admin)]
    bad_card = make_card(admin)
    async with factory() as session:
        session.add_all([admin, *customers])
        await session.flush()
        session.add_all([*cards, bad_card])
        await session.commit()
        for card in cards:
            await ScratchCardService(session).enqueue_distribution(
                card,
                DistributionRequest(
                    distribution_method=DistributionMethod.RANDOM, quantity=1
                ),
                admin,
            )
        bad_job = await ScratchCardService(session).enqueue_distribution(
            bad_card,
            DistributionRequest(
                distribution_method=DistributionMethod.NEARBY, radius_km=1
            ),
            admin,
        )
        bad_job_id = bad_job.id
        await session.commit()

    async def work_once():
        async with factory() as session:
            job_id = await ScratchCardService(session).process_next_job()
            await session.commit()
            return job_id

    first_claims = await asyncio.gather(work_once(), work_once())
    assert len(set(first_claims)) == 2
    # Consume the remaining failing job and retry it to its durable retry ceiling.
    for _ in range(4):
        await work_once()
    async with factory() as session:
        bad_job = await session.get(ScratchCardDistributionJob, bad_job_id)
        assert bad_job.status == DistributionJobStatus.FAILED
        assert bad_job.attempts == bad_job.max_attempts == 3
        assert "selected shop" in bad_job.error_message


@pytest.mark.asyncio
async def test_audit_snapshots_are_json_safe(sessions):
    factory = sessions
    admin = make_user(UserRole.ADMIN, 1, email="audit-admin@example.test", phone=None)
    async with factory() as session:
        session.add(admin)
        await session.commit()
        await MarketplaceService(session).audit(
            admin,
            "scratch_card.created",
            "scratch_card",
            uuid.uuid4(),
            after={
                "id": uuid.uuid4(),
                "created_at": datetime.now(UTC),
                "amount": Decimal("10.50"),
                "status": ScratchCardStatus.DRAFT,
            },
            reason="Regression test for create/publish 500",
        )
        await session.commit()
        audit = (await session.scalars(select(AuditLog))).one()
        assert isinstance(audit.after["id"], str)
        assert audit.after["status"] == "draft"
        assert audit.after["amount"] == 10.5


@pytest.mark.asyncio
async def test_large_random_audience(sessions):
    user_count = int(os.getenv("SCRATCH_LOAD_USERS", "0"))
    if user_count < 1:
        pytest.skip("Set SCRATCH_LOAD_USERS to run the PostgreSQL load scenario")
    factory = sessions
    admin = make_user(UserRole.ADMIN, 1, email="load-admin@example.test", phone=None)
    card = make_card(admin)
    async with factory() as session:
        session.add(admin)
        await session.flush()
        session.add(card)
        await session.commit()
        await session.execute(
            text(
                """
                INSERT INTO users (id, role, name, is_active)
                SELECT md5('scratch-load-' || value::text)::uuid,
                       'customer'::user_role,
                       'Load User ' || value::text,
                       true
                FROM generate_series(1, :user_count) AS value
                """
            ),
            {"user_count": user_count},
        )
        await session.commit()

    started = time.perf_counter()
    job_id = await publish(
        factory,
        card,
        admin,
        DistributionRequest(
            distribution_method=DistributionMethod.RANDOM,
            quantity=user_count,
        ),
    )
    elapsed = time.perf_counter() - started
    async with factory() as session:
        job = await session.get(ScratchCardDistributionJob, job_id)
        assert job.eligible_count == user_count
        assert job.assigned_count == user_count
        assert int(
            await session.scalar(select(func.count()).select_from(ScratchCardAssignment))
        ) == user_count
        assert int(
            await session.scalar(select(func.count()).select_from(Notification))
        ) == user_count
    print(f"distributed {user_count} assignments in {elapsed:.3f}s")
