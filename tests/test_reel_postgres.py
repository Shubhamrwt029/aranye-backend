"""PostgreSQL integration tests for the reel feed, engagement, and publishing lifecycle.

Run with a database migrated through revision 010:
TEST_DATABASE_URL=postgresql+asyncpg://127.0.0.1:55432/aranye_verify pytest
"""

import os
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.v1.endpoints import customer_reels, shopkeeper_reels
from app.core.exceptions import ConflictException, NotFoundException
from app.models.marketplace import MediaAsset, Product, Shop, ShopStatus
from app.models.reel import Reel, ReelCTAType, ReelMediaType, ReelStatus, ReelView
from app.models.user import User, UserRole
from app.schemas.reel import ReelCreate, ReelShareInput, ReelUpdate, ReelViewInput

DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="TEST_DATABASE_URL is required for PostgreSQL integration tests",
)


def make_user(role: UserRole, number: int) -> User:
    return User(
        id=uuid.uuid4(),
        role=role,
        phone=f"9100{number:06d}",
        name=f"Reel User {number}",
        is_active=True,
        is_profile_complete=True,
        is_phone_verified=True,
    )


def make_shop(owner: User, number: int, *, active: bool = True) -> Shop:
    return Shop(
        id=uuid.uuid4(),
        owner_id=owner.id,
        name=f"Reel Shop {number}",
        business_type="grocery",
        phone=f"9200{number:06d}",
        address_line="Market Road",
        area="Central",
        city="Test City",
        postal_code="100001",
        latitude=Decimal("28.613900"),
        longitude=Decimal("77.209000"),
        status=ShopStatus.ACTIVE if active else ShopStatus.DRAFT,
    )


def make_reel(shop: Shop, title: str, **values) -> Reel:
    now = datetime.now(UTC)
    defaults = {
        "id": uuid.uuid4(),
        "shop_id": shop.id,
        "title": title,
        "category": "Food",
        "media_type": ReelMediaType.VIDEO,
        "media_url": f"https://media.example/{uuid.uuid4()}.mp4",
        "cta_type": ReelCTAType.SHOP,
        "status": ReelStatus.ACTIVE,
        "starts_at": now - timedelta(hours=1),
        "ends_at": now + timedelta(days=1),
        "published_at": now - timedelta(minutes=5),
    }
    defaults.update(values)
    return Reel(**defaults)


@pytest.fixture
async def session():
    engine = create_async_engine(DATABASE_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE TABLE users CASCADE"))
    async with factory() as db:
        yield db
        await db.rollback()
    await engine.dispose()


@pytest.mark.asyncio
async def test_feed_visibility_saved_filter_and_engagement_are_consistent(session):
    db = session
    owner = make_user(UserRole.SHOPKEEPER, 1)
    customer = make_user(UserRole.CUSTOMER, 2)
    other_customer = make_user(UserRole.CUSTOMER, 3)
    inactive_owner = make_user(UserRole.SHOPKEEPER, 4)
    shop = make_shop(owner, 1)
    inactive_shop = make_shop(inactive_owner, 2, active=False)
    now = datetime.now(UTC)
    visible = make_reel(shop, "Visible reel", category="Food", priority=1)
    same_category_case = make_reel(shop, "Second reel", category="food", priority=2)
    paused = make_reel(shop, "Paused reel", status=ReelStatus.PAUSED)
    expired = make_reel(shop, "Expired reel", ends_at=now - timedelta(minutes=1))
    inactive_shop_reel = make_reel(inactive_shop, "Inactive shop reel")
    db.add_all(
        [
            owner,
            customer,
            other_customer,
            inactive_owner,
            shop,
            inactive_shop,
            visible,
            same_category_case,
            paused,
            expired,
            inactive_shop_reel,
        ]
    )
    await db.commit()

    feed = await customer_reels.reel_feed(
        customer, db, category=None, saved_only=False, limit=20, offset=0
    )
    assert [item.id for item in feed.items] == [visible.id, same_category_case.id]
    assert feed.total == 2
    assert [item.lower() for item in await customer_reels.reel_categories(customer, db)] == ["food"]

    first_like = await customer_reels.like_reel(visible.id, customer, db)
    second_like = await customer_reels.like_reel(visible.id, customer, db)
    assert first_like.like_count == second_like.like_count == 1
    first_save = await customer_reels.save_reel(visible.id, customer, db)
    second_save = await customer_reels.save_reel(visible.id, customer, db)
    assert first_save.save_count == second_save.save_count == 1

    saved_feed = await customer_reels.reel_feed(
        customer, db, category=None, saved_only=True, limit=20, offset=0
    )
    assert [item.id for item in saved_feed.items] == [visible.id]
    assert saved_feed.items[0].is_liked is True
    assert saved_feed.items[0].is_saved is True

    await customer_reels.view_reel(visible.id, ReelViewInput(watched_ms=1_000), customer, db)
    repeated_view = await customer_reels.view_reel(
        visible.id,
        ReelViewInput(watched_ms=5_000, completed=True),
        customer,
        db,
    )
    second_viewer = await customer_reels.view_reel(
        visible.id, ReelViewInput(watched_ms=2_000), other_customer, db
    )
    assert repeated_view.view_count == 1
    assert second_viewer.view_count == 2
    view = await db.scalar(
        select(ReelView).where(ReelView.reel_id == visible.id, ReelView.user_id == customer.id)
    )
    assert view and view.watched_ms == 5_000 and view.completed is True

    share = await customer_reels.share_reel(
        visible.id, ReelShareInput(platform="whatsapp"), customer, db
    )
    click = await customer_reels.reel_cta_click(visible.id, customer, db)
    assert share.share_count == 1
    assert click.click_count == 1
    analytics = await shopkeeper_reels.reel_analytics(visible.id, owner, db)
    assert analytics.unique_views == 2
    assert analytics.completed_views == 1
    assert analytics.completion_rate == 0.5
    assert analytics.shares == analytics.cta_clicks == 1

    first_unlike = await customer_reels.unlike_reel(visible.id, customer, db)
    second_unlike = await customer_reels.unlike_reel(visible.id, customer, db)
    assert first_unlike.like_count == second_unlike.like_count == 0
    first_unsave = await customer_reels.unsave_reel(visible.id, customer, db)
    second_unsave = await customer_reels.unsave_reel(visible.id, customer, db)
    assert first_unsave.save_count == second_unsave.save_count == 0


@pytest.mark.asyncio
async def test_shopkeeper_media_ownership_product_ownership_and_lifecycle(session):
    db = session
    owner = make_user(UserRole.SHOPKEEPER, 10)
    foreign_owner = make_user(UserRole.SHOPKEEPER, 11)
    shop = make_shop(owner, 10)
    foreign_shop = make_shop(foreign_owner, 11)
    ready_media = MediaAsset(
        id=uuid.uuid4(),
        object_key="reels/ready.mp4",
        bucket="test",
        content_type="video/mp4",
        size_bytes=1_000,
        status="ready",
        public_url="https://media.example/ready.mp4",
        uploaded_by=owner.id,
    )
    pending_media = MediaAsset(
        id=uuid.uuid4(),
        object_key="reels/pending.mp4",
        bucket="test",
        content_type="video/mp4",
        size_bytes=1_000,
        status="pending",
        uploaded_by=owner.id,
    )
    foreign_product = Product(
        id=uuid.uuid4(),
        shop_id=foreign_shop.id,
        name="Foreign product",
        price_paise=100,
        is_available=True,
        is_deleted=False,
    )
    db.add_all(
        [
            owner,
            foreign_owner,
            shop,
            foreign_shop,
            ready_media,
            pending_media,
            foreign_product,
        ]
    )
    await db.commit()

    with pytest.raises(ConflictException, match="not complete"):
        await shopkeeper_reels.create_reel(
            ReelCreate(
                title="Pending media",
                category="Food",
                media_type="video",
                media_asset_id=pending_media.id,
            ),
            owner,
            db,
        )
    with pytest.raises(NotFoundException, match="Product"):
        await shopkeeper_reels.create_reel(
            ReelCreate(
                title="Foreign product",
                category="Food",
                media_type="video",
                media_asset_id=ready_media.id,
                cta_type="product",
                product_id=foreign_product.id,
            ),
            owner,
            db,
        )

    reel = await shopkeeper_reels.create_reel(
        ReelCreate(
            title="Owned reel",
            category="Food",
            media_type="video",
            media_asset_id=ready_media.id,
        ),
        owner,
        db,
    )
    assert reel.status == ReelStatus.DRAFT
    shop.status = ShopStatus.DRAFT
    with pytest.raises(ConflictException, match="Shop must be active"):
        await shopkeeper_reels.publish_reel(reel.id, owner, db)
    shop.status = ShopStatus.ACTIVE
    published = await shopkeeper_reels.publish_reel(reel.id, owner, db)
    assert published.status == ReelStatus.ACTIVE
    paused = await shopkeeper_reels.pause_reel(reel.id, owner, db)
    assert paused.status == ReelStatus.PAUSED
    await shopkeeper_reels.archive_reel(reel.id, owner, db)
    assert reel.status == ReelStatus.ARCHIVED
    with pytest.raises(ConflictException, match="cannot be edited"):
        await shopkeeper_reels.update_reel(reel.id, ReelUpdate(title="Edited archive"), owner, db)
    with pytest.raises(NotFoundException, match="Reel"):
        await shopkeeper_reels.my_reel(reel.id, foreign_owner, db)

    expired = await shopkeeper_reels.create_reel(
        ReelCreate(
            title="Expired draft",
            category="Food",
            media_type="video",
            media_asset_id=ready_media.id,
            starts_at=datetime.now(UTC) - timedelta(hours=2),
            ends_at=datetime.now(UTC) - timedelta(hours=1),
        ),
        owner,
        db,
    )
    with pytest.raises(ConflictException, match="end time has already passed"):
        await shopkeeper_reels.publish_reel(expired.id, owner, db)
