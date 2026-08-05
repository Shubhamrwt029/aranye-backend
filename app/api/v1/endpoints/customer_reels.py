from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import delete, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentCustomer
from app.core.database import get_db
from app.core.exceptions import NotFoundException
from app.models.marketplace import Shop, ShopStatus
from app.models.reel import (
    Reel,
    ReelEvent,
    ReelEventType,
    ReelLike,
    ReelSave,
    ReelStatus,
    ReelView,
)
from app.schemas.reel import (
    ReelEngagementResponse,
    ReelFeedResponse,
    ReelResponse,
    ReelShareInput,
    ReelViewInput,
)

router = APIRouter()
DB = Annotated[AsyncSession, Depends(get_db)]


def visible_reels(now: datetime):
    return (
        select(Reel, Shop)
        .join(Shop, Shop.id == Reel.shop_id)
        .where(
            Reel.status == ReelStatus.ACTIVE,
            Shop.status == ShopStatus.ACTIVE,
            or_(Reel.starts_at.is_(None), Reel.starts_at <= now),
            or_(Reel.ends_at.is_(None), Reel.ends_at >= now),
        )
    )


def reel_response(reel: Reel, shop: Shop, *, is_liked: bool, is_saved: bool) -> ReelResponse:
    return ReelResponse.model_validate(
        {
            **{column.name: getattr(reel, column.name) for column in reel.__table__.columns},
            "advertiser": {
                "shop_id": shop.id,
                "name": shop.name,
                "phone": shop.phone,
                "whatsapp_number": shop.whatsapp_number,
                "logo_url": shop.logo_url,
            },
            "is_liked": is_liked,
            "is_saved": is_saved,
        }
    )


async def customer_reel(reel_id: UUID, db: AsyncSession) -> tuple[Reel, Shop]:
    row = (
        await db.execute(visible_reels(datetime.now(UTC)).where(Reel.id == reel_id))
    ).one_or_none()
    if not row:
        raise NotFoundException("Reel")
    return row[0], row[1]


async def flags(reel_id: UUID, user_id: UUID, db: AsyncSession) -> tuple[bool, bool]:
    liked, saved = (
        await db.execute(
            select(
                exists().where(ReelLike.reel_id == reel_id, ReelLike.user_id == user_id),
                exists().where(ReelSave.reel_id == reel_id, ReelSave.user_id == user_id),
            )
        )
    ).one()
    return bool(liked), bool(saved)


async def engagement(reel: Reel, user_id: UUID, db: AsyncSession) -> ReelEngagementResponse:
    liked, saved = await flags(reel.id, user_id, db)
    return ReelEngagementResponse(
        reel_id=reel.id,
        is_liked=liked,
        is_saved=saved,
        like_count=reel.like_count,
        save_count=reel.save_count,
        share_count=reel.share_count,
        view_count=reel.view_count,
        click_count=reel.click_count,
    )


@router.get("/reels/categories", response_model=list[str])
async def reel_categories(_: CurrentCustomer, db: DB):
    now = datetime.now(UTC)
    query = (
        visible_reels(now)
        .with_only_columns(func.min(Reel.category))
        .group_by(func.lower(Reel.category))
        .order_by(func.lower(Reel.category))
    )
    return list((await db.scalars(query)).all())


@router.get("/reels", response_model=ReelFeedResponse)
async def reel_feed(
    user: CurrentCustomer,
    db: DB,
    category: str | None = Query(None, min_length=1, max_length=80),
    saved_only: bool = False,
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
):
    query = visible_reels(datetime.now(UTC))
    if category:
        query = query.where(func.lower(Reel.category) == category.strip().lower())
    if saved_only:
        query = query.join(
            ReelSave,
            (ReelSave.reel_id == Reel.id) & (ReelSave.user_id == user.id),
        )
    total = int(
        (await db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))) or 0
    )
    rows = (
        await db.execute(
            query.order_by(Reel.priority, Reel.published_at.desc(), Reel.id)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    reel_ids = [reel.id for reel, _ in rows]
    liked_ids = (
        set(
            (
                await db.scalars(
                    select(ReelLike.reel_id).where(
                        ReelLike.user_id == user.id, ReelLike.reel_id.in_(reel_ids)
                    )
                )
            ).all()
        )
        if reel_ids
        else set()
    )
    saved_ids = (
        set(
            (
                await db.scalars(
                    select(ReelSave.reel_id).where(
                        ReelSave.user_id == user.id, ReelSave.reel_id.in_(reel_ids)
                    )
                )
            ).all()
        )
        if reel_ids
        else set()
    )
    return ReelFeedResponse(
        items=[
            reel_response(
                reel,
                shop,
                is_liked=reel.id in liked_ids,
                is_saved=reel.id in saved_ids,
            )
            for reel, shop in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/reels/{reel_id}", response_model=ReelResponse)
async def reel_detail(reel_id: UUID, user: CurrentCustomer, db: DB):
    reel, shop = await customer_reel(reel_id, db)
    liked, saved = await flags(reel.id, user.id, db)
    return reel_response(reel, shop, is_liked=liked, is_saved=saved)


async def set_unique_interaction(
    *, reel: Reel, user_id: UUID, db: AsyncSession, model, counter: str, enabled: bool
) -> None:
    if enabled:
        result = await db.execute(
            insert(model)
            .values(id=uuid4(), reel_id=reel.id, user_id=user_id)
            .on_conflict_do_nothing(index_elements=["reel_id", "user_id"])
        )
        if result.rowcount:
            await db.execute(
                update(Reel).where(Reel.id == reel.id).values({counter: getattr(Reel, counter) + 1})
            )
    else:
        result = await db.execute(
            delete(model).where(model.reel_id == reel.id, model.user_id == user_id)
        )
        if result.rowcount:
            await db.execute(
                update(Reel)
                .where(Reel.id == reel.id)
                .values({counter: func.greatest(getattr(Reel, counter) - 1, 0)})
            )
    await db.flush()
    await db.refresh(reel)


@router.put("/reels/{reel_id}/like", response_model=ReelEngagementResponse)
async def like_reel(reel_id: UUID, user: CurrentCustomer, db: DB):
    reel, _ = await customer_reel(reel_id, db)
    await set_unique_interaction(
        reel=reel, user_id=user.id, db=db, model=ReelLike, counter="like_count", enabled=True
    )
    return await engagement(reel, user.id, db)


@router.delete("/reels/{reel_id}/like", response_model=ReelEngagementResponse)
async def unlike_reel(reel_id: UUID, user: CurrentCustomer, db: DB):
    reel, _ = await customer_reel(reel_id, db)
    await set_unique_interaction(
        reel=reel, user_id=user.id, db=db, model=ReelLike, counter="like_count", enabled=False
    )
    return await engagement(reel, user.id, db)


@router.put("/reels/{reel_id}/save", response_model=ReelEngagementResponse)
async def save_reel(reel_id: UUID, user: CurrentCustomer, db: DB):
    reel, _ = await customer_reel(reel_id, db)
    await set_unique_interaction(
        reel=reel, user_id=user.id, db=db, model=ReelSave, counter="save_count", enabled=True
    )
    return await engagement(reel, user.id, db)


@router.delete("/reels/{reel_id}/save", response_model=ReelEngagementResponse)
async def unsave_reel(reel_id: UUID, user: CurrentCustomer, db: DB):
    reel, _ = await customer_reel(reel_id, db)
    await set_unique_interaction(
        reel=reel, user_id=user.id, db=db, model=ReelSave, counter="save_count", enabled=False
    )
    return await engagement(reel, user.id, db)


@router.post("/reels/{reel_id}/view", response_model=ReelEngagementResponse)
async def view_reel(reel_id: UUID, data: ReelViewInput, user: CurrentCustomer, db: DB):
    reel, _ = await customer_reel(reel_id, db)
    inserted_id = await db.scalar(
        insert(ReelView)
        .values(
            id=uuid4(),
            reel_id=reel.id,
            user_id=user.id,
            watched_ms=data.watched_ms,
            completed=data.completed,
        )
        .on_conflict_do_nothing(index_elements=["reel_id", "user_id"])
        .returning(ReelView.id)
    )
    if inserted_id:
        await db.execute(
            update(Reel).where(Reel.id == reel.id).values(view_count=Reel.view_count + 1)
        )
    else:
        await db.execute(
            update(ReelView)
            .where(ReelView.reel_id == reel.id, ReelView.user_id == user.id)
            .values(
                watched_ms=func.greatest(ReelView.watched_ms, data.watched_ms),
                completed=ReelView.completed | data.completed,
                updated_at=func.now(),
            )
        )
    await db.flush()
    await db.refresh(reel)
    return await engagement(reel, user.id, db)


@router.post(
    "/reels/{reel_id}/share",
    response_model=ReelEngagementResponse,
    status_code=status.HTTP_201_CREATED,
)
async def share_reel(reel_id: UUID, data: ReelShareInput, user: CurrentCustomer, db: DB):
    reel, _ = await customer_reel(reel_id, db)
    db.add(
        ReelEvent(
            reel_id=reel.id,
            user_id=user.id,
            event_type=ReelEventType.SHARE,
            platform=data.platform,
        )
    )
    await db.execute(
        update(Reel).where(Reel.id == reel.id).values(share_count=Reel.share_count + 1)
    )
    await db.flush()
    await db.refresh(reel)
    return await engagement(reel, user.id, db)


@router.post("/reels/{reel_id}/cta-click", response_model=ReelEngagementResponse)
async def reel_cta_click(reel_id: UUID, user: CurrentCustomer, db: DB):
    reel, _ = await customer_reel(reel_id, db)
    db.add(ReelEvent(reel_id=reel.id, user_id=user.id, event_type=ReelEventType.CTA_CLICK))
    await db.execute(
        update(Reel).where(Reel.id == reel.id).values(click_count=Reel.click_count + 1)
    )
    await db.flush()
    await db.refresh(reel)
    return await engagement(reel, user.id, db)
