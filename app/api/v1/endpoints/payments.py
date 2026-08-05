import json
from typing import Annotated
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, Header, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import (
    AppException,
    NotFoundException,
    UnauthorizedException,
)
from app.models.marketplace import Order, Payment, PaymentStatus, Shop, ShopStatus
from app.schemas.marketplace import PaymentCreate
from app.services.marketplace_service import verify_razorpay_signature

router = APIRouter()
settings = get_settings()
DB = Annotated[AsyncSession, Depends(get_db)]


@router.post("/orders", status_code=status.HTTP_201_CREATED)
async def create_payment(data: PaymentCreate, user: CurrentUser, db: DB):
    if data.purpose == "order":
        order = await db.get(Order, data.order_id) if data.order_id else None
        if not order or order.customer_id != user.id:
            raise NotFoundException("Order")
        amount, shop_id = order.total_paise, order.shop_id
    else:
        shop = (await db.execute(select(Shop).where(Shop.owner_id == user.id))).scalar_one_or_none()
        if not shop:
            raise NotFoundException("Shop")
        amount, shop_id = settings.shop_activation_fee_paise, shop.id
    payment = Payment(
        id=uuid4(),
        user_id=user.id,
        order_id=data.order_id,
        shop_id=shop_id,
        purpose=data.purpose,
        amount_paise=amount,
    )
    if settings.razorpay_key_id and settings.razorpay_key_secret:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                "https://api.razorpay.com/v1/orders",
                auth=(settings.razorpay_key_id, settings.razorpay_key_secret),
                json={"amount": amount, "currency": "INR", "receipt": str(payment.id)},
            )
            response.raise_for_status()
            payment.provider_order_id = response.json()["id"]
    elif settings.environment == "development":
        payment.provider_order_id = f"order_dev_{payment.id}"
    else:
        raise AppException("Payment provider is unavailable", 503)
    db.add(payment)
    await db.flush()
    return {
        "payment_id": payment.id,
        "provider_order_id": payment.provider_order_id,
        "amount_paise": amount,
        "currency": "INR",
        "key_id": settings.razorpay_key_id,
    }


@router.post("/webhooks/razorpay", include_in_schema=False)
async def razorpay_webhook(
    request: Request, db: DB, signature: Annotated[str, Header(alias="X-Razorpay-Signature")]
):
    body = await request.body()
    if not verify_razorpay_signature(body, signature):
        raise UnauthorizedException("Invalid webhook signature")
    event = json.loads(body)
    entity = event.get("payload", {}).get("payment", {}).get("entity", {})
    provider_order_id = entity.get("order_id")
    payment = (
        await db.execute(
            select(Payment).where(Payment.provider_order_id == provider_order_id).with_for_update()
        )
    ).scalar_one_or_none()
    if not payment:
        return {"received": True}
    if event.get("event") == "payment.captured":
        payment.status = PaymentStatus.CAPTURED
        payment.provider_payment_id = entity.get("id")
        if payment.purpose == "shop_activation":
            shop = await db.get(Shop, payment.shop_id)
            shop.status = ShopStatus.PENDING_REVIEW
    elif event.get("event") == "payment.failed":
        payment.status = PaymentStatus.FAILED
    return {"received": True}
