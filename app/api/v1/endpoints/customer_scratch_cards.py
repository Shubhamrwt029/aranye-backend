from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentCustomer
from app.core.database import get_db
from app.models.marketplace import Shop
from app.models.scratch_card import (
    ScratchAssignmentStatus,
    ScratchCard,
    ScratchCardAssignment,
    ScratchCardStatus,
)
from app.schemas.scratch_card import ScratchCardListItem, ScratchCardReveal
from app.services.scratch_card_service import ScratchCardService

router = APIRouter()
DB = Annotated[AsyncSession, Depends(get_db)]


@router.get("/scratch-cards")
async def scratch_cards(
    user: CurrentCustomer,
    db: DB,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    now = datetime.now(UTC)
    query = (
        select(ScratchCardAssignment, ScratchCard, Shop)
        .join(ScratchCard, ScratchCard.id == ScratchCardAssignment.scratch_card_id)
        .outerjoin(Shop, Shop.id == ScratchCard.shop_id)
        .where(
            ScratchCardAssignment.user_id == user.id,
            ScratchCardAssignment.status != ScratchAssignmentStatus.EXPIRED,
            ScratchCard.status == ScratchCardStatus.ACTIVE,
            ScratchCard.starts_at <= now,
            ScratchCard.expires_at >= now,
            or_(
                ScratchCard.ends_at >= now,
                ScratchCardAssignment.scratched_at.is_not(None),
            ),
        )
    )
    total = int(
        (await db.scalar(select(func.count()).select_from(query.order_by(None).subquery())))
        or 0
    )
    rows = (
        await db.execute(
            query.order_by(ScratchCard.priority, ScratchCardAssignment.assigned_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    service = ScratchCardService(db)
    return {
        "items": [
            ScratchCardListItem.model_validate(service.list_item(assignment, card, shop))
            for assignment, card, shop in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/scratch-cards/{assignment_id}")
async def scratch_card_detail(
    assignment_id: UUID, user: CurrentCustomer, db: DB
):
    service = ScratchCardService(db)
    assignment, card, shop = await service.customer_assignment(assignment_id, user)
    service.ensure_customer_visible(card, assignment)
    if assignment.scratched_at:
        return ScratchCardReveal.model_validate(
            service.reveal_item(assignment, card, shop)
        )
    return {
        **service.list_item(assignment, card, shop),
        "description": card.description,
        "terms_and_conditions": card.terms_and_conditions,
    }


@router.post(
    "/scratch-cards/{assignment_id}/view", response_model=ScratchCardListItem
)
async def view_scratch_card(
    assignment_id: UUID, user: CurrentCustomer, db: DB
):
    return await ScratchCardService(db).mark_viewed(assignment_id, user)


@router.post(
    "/scratch-cards/{assignment_id}/scratch", response_model=ScratchCardReveal
)
async def scratch_scratch_card(
    assignment_id: UUID, user: CurrentCustomer, db: DB
):
    return await ScratchCardService(db).scratch(assignment_id, user)
