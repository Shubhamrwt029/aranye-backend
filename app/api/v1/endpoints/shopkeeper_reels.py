from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentShopkeeper
from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import AppException, ConflictException, NotFoundException
from app.models.marketplace import MediaAsset, Product, Shop, ShopStatus
from app.models.reel import Reel, ReelEvent, ReelEventType, ReelStatus, ReelView
from app.models.user import User
from app.schemas.reel import (
    ReelAnalyticsResponse,
    ReelCreate,
    ReelManageResponse,
    ReelMediaCompleteRequest,
    ReelMediaPresignRequest,
    ReelUpdate,
)
from app.services.marketplace_service import MarketplaceService
from app.services.media_service import MediaService

router = APIRouter()
DB = Annotated[AsyncSession, Depends(get_db)]
settings = get_settings()


async def owned_reel(reel_id: UUID, shop: Shop, db: AsyncSession) -> Reel:
    reel = await db.get(Reel, reel_id)
    if not reel or reel.shop_id != shop.id:
        raise NotFoundException("Reel")
    return reel


async def owned_ready_asset(
    asset_id: UUID, user: User, db: AsyncSession, *, expected_kind: str | None = None
) -> MediaAsset:
    asset = await db.get(MediaAsset, asset_id)
    if not asset or asset.uploaded_by != user.id:
        raise NotFoundException("Media asset")
    if asset.status != "ready" or not asset.public_url:
        raise ConflictException("Media upload is not complete")
    if expected_kind and not asset.content_type.startswith(f"{expected_kind}/"):
        raise AppException(f"Expected a {expected_kind} media asset")
    return asset


async def validate_product(product_id: UUID | None, shop: Shop, db: AsyncSession) -> None:
    if not product_id:
        return
    product = await db.get(Product, product_id)
    if not product or product.shop_id != shop.id or product.is_deleted:
        raise NotFoundException("Product")


@router.post("/reels/media/presign", status_code=status.HTTP_201_CREATED)
async def reel_media_presign(data: ReelMediaPresignRequest, user: CurrentShopkeeper, db: DB):
    service = MediaService()
    service.validate_reel_size(data.size_bytes, data.content_type)
    key = service.object_key("reels", data.filename)
    asset = MediaAsset(
        object_key=key,
        bucket=settings.s3_bucket,
        content_type=data.content_type,
        size_bytes=data.size_bytes,
        status="pending",
        uploaded_by=user.id,
    )
    db.add(asset)
    await db.flush()
    return {
        "asset_id": asset.id,
        "upload_url": service.presign(key, data.content_type),
        "object_key": key,
        "expires_in": settings.media_presign_expire_seconds,
    }


@router.post("/reels/media/{asset_id}/complete")
async def reel_media_complete(
    asset_id: UUID,
    data: ReelMediaCompleteRequest,
    user: CurrentShopkeeper,
    db: DB,
):
    asset = await db.get(MediaAsset, asset_id)
    if not asset or asset.uploaded_by != user.id:
        raise NotFoundException("Media asset")
    if asset.status == "ready":
        return asset
    MediaService().validate_reel_size(data.size_bytes, asset.content_type)
    if data.size_bytes != asset.size_bytes:
        raise ConflictException("Uploaded size does not match the presigned request")
    asset.status = "ready"
    asset.public_url = MediaService().public_url(asset.object_key)
    return asset


@router.post("/reels", response_model=ReelManageResponse, status_code=status.HTTP_201_CREATED)
async def create_reel(data: ReelCreate, user: CurrentShopkeeper, db: DB):
    shop = await MarketplaceService(db).get_owned_shop(user)
    media = await owned_ready_asset(data.media_asset_id, user, db, expected_kind=data.media_type)
    poster = (
        await owned_ready_asset(data.poster_asset_id, user, db, expected_kind="image")
        if data.poster_asset_id
        else None
    )
    await validate_product(data.product_id, shop, db)
    values = data.model_dump(exclude={"media_asset_id", "poster_asset_id"})
    reel = Reel(
        shop_id=shop.id,
        media_url=media.public_url,
        poster_url=poster.public_url if poster else None,
        **values,
    )
    db.add(reel)
    await db.flush()
    return reel


@router.get("/reels", response_model=list[ReelManageResponse])
async def my_reels(
    user: CurrentShopkeeper,
    db: DB,
    reel_status: ReelStatus | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    shop = await MarketplaceService(db).get_owned_shop(user)
    query = select(Reel).where(Reel.shop_id == shop.id)
    if reel_status:
        query = query.where(Reel.status == reel_status)
    return list(
        (await db.scalars(query.order_by(Reel.created_at.desc()).limit(limit).offset(offset))).all()
    )


@router.get("/reels/{reel_id}", response_model=ReelManageResponse)
async def my_reel(reel_id: UUID, user: CurrentShopkeeper, db: DB):
    shop = await MarketplaceService(db).get_owned_shop(user)
    return await owned_reel(reel_id, shop, db)


@router.patch("/reels/{reel_id}", response_model=ReelManageResponse)
async def update_reel(reel_id: UUID, data: ReelUpdate, user: CurrentShopkeeper, db: DB):
    shop = await MarketplaceService(db).get_owned_shop(user)
    reel = await owned_reel(reel_id, shop, db)
    if reel.status == ReelStatus.ARCHIVED:
        raise ConflictException("Archived reels cannot be edited")
    values = data.model_dump(exclude_unset=True)
    media_asset_id = values.pop("media_asset_id", None)
    poster_asset_id = values.pop("poster_asset_id", None)
    if media_asset_id:
        media = await owned_ready_asset(
            media_asset_id, user, db, expected_kind=values["media_type"]
        )
        reel.media_url = media.public_url
    if poster_asset_id:
        poster = await owned_ready_asset(poster_asset_id, user, db, expected_kind="image")
        reel.poster_url = poster.public_url
    elif "poster_asset_id" in data.model_fields_set:
        reel.poster_url = None
    product_id = values.get("product_id", reel.product_id)
    await validate_product(product_id, shop, db)
    next_start = values.get("starts_at", reel.starts_at)
    next_end = values.get("ends_at", reel.ends_at)
    if next_start and next_end and next_end <= next_start:
        raise AppException("ends_at must be after starts_at")
    next_cta = values.get("cta_type", reel.cta_type)
    next_cta_value = values.get("cta_value", reel.cta_value)
    next_cta_value_key = getattr(next_cta, "value", next_cta)
    if next_cta_value_key == "product" and not product_id:
        raise AppException("product_id is required for a product CTA")
    if next_cta_value_key == "external" and not next_cta_value:
        raise AppException("cta_value is required for an external CTA")
    for key, value in values.items():
        setattr(reel, key, value)
    return reel


@router.post("/reels/{reel_id}/publish", response_model=ReelManageResponse)
async def publish_reel(reel_id: UUID, user: CurrentShopkeeper, db: DB):
    shop = await MarketplaceService(db).get_owned_shop(user)
    reel = await owned_reel(reel_id, shop, db)
    if shop.status != ShopStatus.ACTIVE:
        raise ConflictException("Shop must be active before publishing reels")
    if reel.status == ReelStatus.ARCHIVED:
        raise ConflictException("Archived reels cannot be published")
    if reel.ends_at and reel.ends_at <= datetime.now(UTC):
        raise ConflictException("Reel end time has already passed")
    reel.status = ReelStatus.ACTIVE
    reel.published_at = reel.published_at or datetime.now(UTC)
    return reel


@router.post("/reels/{reel_id}/pause", response_model=ReelManageResponse)
async def pause_reel(reel_id: UUID, user: CurrentShopkeeper, db: DB):
    shop = await MarketplaceService(db).get_owned_shop(user)
    reel = await owned_reel(reel_id, shop, db)
    if reel.status != ReelStatus.ACTIVE:
        raise ConflictException("Only active reels can be paused")
    reel.status = ReelStatus.PAUSED
    return reel


@router.delete("/reels/{reel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_reel(reel_id: UUID, user: CurrentShopkeeper, db: DB):
    shop = await MarketplaceService(db).get_owned_shop(user)
    reel = await owned_reel(reel_id, shop, db)
    reel.status = ReelStatus.ARCHIVED


@router.get("/reels/{reel_id}/analytics", response_model=ReelAnalyticsResponse)
async def reel_analytics(reel_id: UUID, user: CurrentShopkeeper, db: DB):
    shop = await MarketplaceService(db).get_owned_shop(user)
    reel = await owned_reel(reel_id, shop, db)
    completed_views = int(
        (
            await db.scalar(
                select(func.count(ReelView.id)).where(
                    ReelView.reel_id == reel.id, ReelView.completed.is_(True)
                )
            )
        )
        or 0
    )
    shares, clicks = (
        await db.execute(
            select(
                func.count(ReelEvent.id).filter(ReelEvent.event_type == ReelEventType.SHARE),
                func.count(ReelEvent.id).filter(ReelEvent.event_type == ReelEventType.CTA_CLICK),
            ).where(ReelEvent.reel_id == reel.id)
        )
    ).one()
    return ReelAnalyticsResponse(
        reel_id=reel.id,
        likes=reel.like_count,
        saves=reel.save_count,
        unique_views=reel.view_count,
        completed_views=completed_views,
        shares=int(shares or 0),
        cta_clicks=int(clicks or 0),
        completion_rate=round(completed_views / reel.view_count, 4) if reel.view_count else 0,
    )
