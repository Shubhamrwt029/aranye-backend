import hashlib
import hmac
import random
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import (
    AppException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.models.marketplace import (
    Address,
    AuditLog,
    Cart,
    CartItem,
    FulfillmentType,
    Order,
    OrderItem,
    OrderStatus,
    Product,
    RewardCampaign,
    RewardClaim,
    Shop,
    ShopStatus,
)
from app.models.user import User
from app.schemas.marketplace import CheckoutRequest

settings = get_settings()


class MarketplaceService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_owned_shop(self, user: User, lock: bool = False) -> Shop:
        query = select(Shop).where(Shop.owner_id == user.id)
        if lock:
            query = query.with_for_update()
        shop = (await self.db.execute(query)).scalar_one_or_none()
        if not shop:
            raise NotFoundException("Shop")
        return shop

    async def checkout(self, user: User, request: CheckoutRequest, idempotency_key: str) -> Order:
        existing = (
            await self.db.execute(
                select(Order).where(
                    Order.customer_id == user.id, Order.idempotency_key == idempotency_key
                )
            )
        ).scalar_one_or_none()
        if existing:
            return existing

        cart = (
            await self.db.execute(
                select(Cart)
                .where(Cart.id == request.cart_id, Cart.user_id == user.id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if not cart:
            raise NotFoundException("Cart")
        shop = await self.db.get(Shop, cart.shop_id)
        if not shop or shop.status != ShopStatus.ACTIVE or not shop.is_open:
            raise AppException("Shop is not currently accepting orders")
        if request.fulfillment_type == "delivery" and not shop.supports_delivery:
            raise AppException("Shop does not support delivery")
        if request.fulfillment_type == "pickup" and not shop.supports_pickup:
            raise AppException("Shop does not support pickup")
        if request.address_id:
            address = await self.db.get(Address, request.address_id)
            if not address or address.user_id != user.id:
                raise ForbiddenException("Invalid delivery address")

        rows = (
            await self.db.execute(
                select(CartItem, Product)
                .join(Product, Product.id == CartItem.product_id)
                .where(CartItem.cart_id == cart.id)
                .with_for_update(of=Product)
            )
        ).all()
        if not rows:
            raise AppException("Cart is empty")
        subtotal = 0
        snapshot_items = []
        for item, product in rows:
            if product.is_deleted or not product.is_available:
                raise ConflictException(f"{product.name} is unavailable")
            if product.stock_quantity is not None and product.stock_quantity < item.quantity:
                raise ConflictException(f"Insufficient stock for {product.name}")
            line_total = product.price_paise * item.quantity
            subtotal += line_total
            snapshot_items.append(
                {
                    "product_id": str(product.id),
                    "name": product.name,
                    "unit_price_paise": product.price_paise,
                    "quantity": item.quantity,
                    "total_paise": line_total,
                }
            )
        if subtotal < shop.minimum_order_paise:
            raise AppException("Minimum order value has not been reached")
        delivery_fee = shop.delivery_fee_paise if request.fulfillment_type == "delivery" else 0
        order = Order(
            order_number=f"AR-{datetime.now(UTC):%y%m%d}-{uuid4().hex[:8].upper()}",
            customer_id=user.id,
            shop_id=shop.id,
            address_id=request.address_id,
            fulfillment_type=FulfillmentType(request.fulfillment_type),
            payment_method=request.payment_method,
            subtotal_paise=subtotal,
            delivery_fee_paise=delivery_fee,
            total_paise=subtotal + delivery_fee,
            idempotency_key=idempotency_key,
            snapshot={"shop": {"id": str(shop.id), "name": shop.name}, "items": snapshot_items},
        )
        self.db.add(order)
        await self.db.flush()
        for row, snap in zip(rows, snapshot_items, strict=True):
            item, product = row
            self.db.add(
                OrderItem(
                    order_id=order.id,
                    product_id=product.id,
                    product_name=product.name,
                    unit_price_paise=product.price_paise,
                    quantity=item.quantity,
                    total_paise=snap["total_paise"],
                )
            )
            if product.stock_quantity is not None:
                product.stock_quantity -= item.quantity
        await self.db.delete(cart)
        return order

    async def transition_order(
        self, actor: User, order_id: UUID, target: OrderStatus, reason: str | None
    ) -> Order:
        order = (
            await self.db.execute(select(Order).where(Order.id == order_id).with_for_update())
        ).scalar_one_or_none()
        if not order:
            raise NotFoundException("Order")
        shop = await self.get_owned_shop(actor)
        if order.shop_id != shop.id:
            raise ForbiddenException()
        allowed = {
            OrderStatus.PENDING: {OrderStatus.ACCEPTED, OrderStatus.REJECTED},
            OrderStatus.ACCEPTED: {OrderStatus.PREPARING},
            OrderStatus.PREPARING: {OrderStatus.READY},
            OrderStatus.READY: {OrderStatus.OUT_FOR_DELIVERY, OrderStatus.COMPLETED},
            OrderStatus.OUT_FOR_DELIVERY: {OrderStatus.COMPLETED},
        }
        if target not in allowed.get(order.status, set()):
            raise ConflictException(
                f"Cannot move order from {order.status.value} to {target.value}"
            )
        if (
            target == OrderStatus.OUT_FOR_DELIVERY
            and order.fulfillment_type != FulfillmentType.DELIVERY
        ):
            raise ConflictException("Pickup orders cannot be out for delivery")
        order.status = target
        if target == OrderStatus.REJECTED:
            order.cancellation_reason = reason
        if target == OrderStatus.COMPLETED:
            order.completed_at = datetime.now(UTC)
        return order

    async def claim_reward(self, user: User, campaign_id: UUID) -> RewardClaim:
        campaign = (
            await self.db.execute(
                select(RewardCampaign).where(RewardCampaign.id == campaign_id).with_for_update()
            )
        ).scalar_one_or_none()
        now = datetime.now(UTC)
        if (
            not campaign
            or campaign.status != "active"
            or not (campaign.starts_at <= now <= campaign.ends_at)
        ):
            raise NotFoundException("Active campaign")
        count = (
            await self.db.execute(
                select(func.count())
                .select_from(RewardClaim)
                .where(RewardClaim.campaign_id == campaign.id, RewardClaim.user_id == user.id)
            )
        ).scalar_one()
        if count >= campaign.per_user_limit:
            raise ConflictException("Campaign claim limit reached")
        if campaign.claimed_count >= campaign.total_inventory:
            raise ConflictException("Campaign is fully claimed")
        prizes = campaign.prizes
        prize = random.SystemRandom().choices(
            prizes, weights=[int(p["weight"]) for p in prizes], k=1
        )[0]
        claim = RewardClaim(
            campaign_id=campaign.id, user_id=user.id, claim_sequence=count + 1, prize=prize
        )
        campaign.claimed_count += 1
        self.db.add(claim)
        await self.db.flush()
        return claim

    async def audit(
        self,
        actor: User,
        action: str,
        resource_type: str,
        resource_id: UUID | str | None,
        before=None,
        after=None,
        reason: str | None = None,
        request_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        self.db.add(
            AuditLog(
                actor_id=actor.id,
                action=action,
                resource_type=resource_type,
                resource_id=str(resource_id) if resource_id else None,
                before=jsonable_encoder(before) if before is not None else None,
                after=jsonable_encoder(after) if after is not None else None,
                reason=reason,
                request_id=request_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )


def verify_razorpay_signature(body: bytes, signature: str) -> bool:
    if not settings.razorpay_webhook_secret:
        return settings.environment == "development"
    expected = hmac.new(settings.razorpay_webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
