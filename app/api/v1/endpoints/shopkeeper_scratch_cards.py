from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentShopkeeper
from app.core.database import get_db
from app.core.exceptions import NotFoundException
from app.models.scratch_card import ScratchCard, ScratchCardAssignment, ScratchCardStatus
from app.models.user import User
from app.schemas.scratch_card import (
    RedemptionCodeRequest,
    RedemptionPreview,
    ShopScratchCampaign,
)
from app.services.marketplace_service import MarketplaceService
from app.services.scratch_card_service import ScratchCardService

router = APIRouter()
DB = Annotated[AsyncSession, Depends(get_db)]


def preview_payload(assignment, card, customer) -> dict:
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


@router.get("/scratch-card-campaigns")
async def linked_campaigns(
    user: CurrentShopkeeper,
    db: DB,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    shop = await MarketplaceService(db).get_owned_shop(user)
    query = select(ScratchCard).where(
        ScratchCard.shop_id == shop.id,
        ScratchCard.status != ScratchCardStatus.DRAFT,
        ScratchCard.status != ScratchCardStatus.ARCHIVED,
    )
    total = int(
        (
            await db.scalar(
                select(func.count()).select_from(query.order_by(None).subquery())
            )
        )
        or 0
    )
    items = list(
        (
            await db.scalars(
                query.order_by(ScratchCard.created_at.desc()).limit(limit).offset(offset)
            )
        ).all()
    )
    return {
        "items": [ShopScratchCampaign.model_validate(item) for item in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get(
    "/scratch-card-campaigns/{card_id}",
    response_model=ShopScratchCampaign,
)
async def linked_campaign_detail(
    card_id: UUID,
    user: CurrentShopkeeper,
    db: DB,
):
    shop = await MarketplaceService(db).get_owned_shop(user)
    card = await db.get(ScratchCard, card_id)
    if (
        not card
        or card.shop_id != shop.id
        or card.status in {ScratchCardStatus.DRAFT, ScratchCardStatus.ARCHIVED}
    ):
        raise NotFoundException("Scratch card campaign")
    return card


@router.post("/scratch-card-redemptions/preview", response_model=RedemptionPreview)
async def preview_redemption(
    data: RedemptionCodeRequest, user: CurrentShopkeeper, db: DB
):
    return preview_payload(
        *(await ScratchCardService(db).redemption_preview(data.redemption_code, user))
    )


@router.post("/scratch-card-redemptions/redeem", response_model=RedemptionPreview)
async def redeem_scratch_card(
    data: RedemptionCodeRequest, user: CurrentShopkeeper, db: DB
):
    return preview_payload(
        *(await ScratchCardService(db).redeem(data.redemption_code, user))
    )


@router.get("/scratch-card-redemptions")
async def redemption_history(
    user: CurrentShopkeeper,
    db: DB,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    shop = await MarketplaceService(db).get_owned_shop(user)
    rows = (
        await db.execute(
            select(ScratchCardAssignment, ScratchCard, User)
            .join(ScratchCard, ScratchCard.id == ScratchCardAssignment.scratch_card_id)
            .join(User, User.id == ScratchCardAssignment.user_id)
            .where(
                ScratchCard.shop_id == shop.id,
                ScratchCardAssignment.redeemed_at.is_not(None),
            )
            .order_by(ScratchCardAssignment.redeemed_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    total = int(
        (
            await db.scalar(
                select(func.count())
                .select_from(ScratchCardAssignment)
                .join(ScratchCard, ScratchCard.id == ScratchCardAssignment.scratch_card_id)
                .where(
                    ScratchCard.shop_id == shop.id,
                    ScratchCardAssignment.redeemed_at.is_not(None),
                )
            )
        )
        or 0
    )
    return {
        "items": [preview_payload(*row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }
