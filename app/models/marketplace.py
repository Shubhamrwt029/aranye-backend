import enum
import uuid
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ShopStatus(str, enum.Enum):
    DRAFT = "draft"
    PAYMENT_PENDING = "payment_pending"
    PENDING_REVIEW = "pending_review"
    ACTIVE = "active"
    REJECTED = "rejected"
    SUSPENDED = "suspended"


class OrderStatus(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    PREPARING = "preparing"
    READY = "ready"
    OUT_FOR_DELIVERY = "out_for_delivery"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class FulfillmentType(str, enum.Enum):
    DELIVERY = "delivery"
    PICKUP = "pickup"


class PaymentStatus(str, enum.Enum):
    CREATED = "created"
    AUTHORIZED = "authorized"
    CAPTURED = "captured"
    FAILED = "failed"
    REFUNDED = "refunded"


class Address(Base, TimestampMixin):
    __tablename__ = "addresses"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(50), default="Home")
    line1: Mapped[str] = mapped_column(String(255))
    line2: Mapped[str | None] = mapped_column(String(255))
    area: Mapped[str] = mapped_column(String(120), index=True)
    city: Mapped[str] = mapped_column(String(120), index=True)
    state: Mapped[str] = mapped_column(String(120))
    postal_code: Mapped[str] = mapped_column(String(12))
    latitude: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class Shop(Base, TimestampMixin):
    __tablename__ = "shops"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), unique=True, index=True
    )
    name: Mapped[str] = mapped_column(String(160), index=True)
    business_type: Mapped[str] = mapped_column(String(60), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str] = mapped_column(String(15))
    whatsapp_number: Mapped[str | None] = mapped_column(String(15))
    address_line: Mapped[str] = mapped_column(String(255))
    area: Mapped[str] = mapped_column(String(120), index=True)
    city: Mapped[str] = mapped_column(String(120), index=True)
    postal_code: Mapped[str] = mapped_column(String(12))
    latitude: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    service_radius_km: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("5"))
    delivery_fee_paise: Mapped[int] = mapped_column(Integer, default=0)
    minimum_order_paise: Mapped[int] = mapped_column(Integer, default=0)
    supports_delivery: Mapped[bool] = mapped_column(Boolean, default=True)
    supports_pickup: Mapped[bool] = mapped_column(Boolean, default=True)
    is_open: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[ShopStatus] = mapped_column(
        Enum(ShopStatus, name="shop_status"), default=ShopStatus.DRAFT, index=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    logo_url: Mapped[str | None] = mapped_column(String(500))
    banner_url: Mapped[str | None] = mapped_column(String(500))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rating_average: Mapped[Decimal] = mapped_column(Numeric(3, 2), default=Decimal("0"))
    rating_count: Mapped[int] = mapped_column(Integer, default=0)


class ShopHour(Base):
    __tablename__ = "shop_hours"
    __table_args__ = (UniqueConstraint("shop_id", "weekday"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), index=True
    )
    weekday: Mapped[int] = mapped_column(Integer)
    opens_at: Mapped[time | None] = mapped_column(Time)
    closes_at: Mapped[time | None] = mapped_column(Time)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)


class BankAccount(Base, TimestampMixin):
    __tablename__ = "bank_accounts"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), unique=True
    )
    account_holder_name: Mapped[str] = mapped_column(String(160))
    account_number_encrypted: Mapped[str] = mapped_column(Text)
    account_number_last4: Mapped[str] = mapped_column(String(4))
    ifsc_encrypted: Mapped[str] = mapped_column(Text)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)


class Category(Base, TimestampMixin):
    __tablename__ = "categories"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id")
    )
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True)
    image_url: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=100, index=True)


class Product(Base, TimestampMixin):
    __tablename__ = "products"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), index=True
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(180), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    ingredients: Mapped[str | None] = mapped_column(Text)
    price_paise: Mapped[int] = mapped_column(Integer)
    compare_at_price_paise: Mapped[int | None] = mapped_column(Integer)
    stock_quantity: Mapped[int | None] = mapped_column(Integer)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    image_urls: Mapped[list] = mapped_column(JSONB, default=list)
    rating_average: Mapped[Decimal] = mapped_column(Numeric(3, 2), default=Decimal("0"))
    rating_count: Mapped[int] = mapped_column(Integer, default=0)


class Favorite(Base):
    __tablename__ = "favorites"
    __table_args__ = (UniqueConstraint("user_id", "shop_id"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Cart(Base, TimestampMixin):
    __tablename__ = "carts"
    __table_args__ = (UniqueConstraint("user_id", "shop_id"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id"), index=True
    )


class CartItem(Base, TimestampMixin):
    __tablename__ = "cart_items"
    __table_args__ = (UniqueConstraint("cart_id", "product_id"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cart_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("carts.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer)


class Order(Base, TimestampMixin):
    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("customer_id", "idempotency_key"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_number: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id"), index=True
    )
    address_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("addresses.id")
    )
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, name="order_status"), default=OrderStatus.PENDING, index=True
    )
    fulfillment_type: Mapped[FulfillmentType] = mapped_column(
        Enum(FulfillmentType, name="fulfillment_type")
    )
    payment_method: Mapped[str] = mapped_column(String(20))
    subtotal_paise: Mapped[int] = mapped_column(Integer)
    delivery_fee_paise: Mapped[int] = mapped_column(Integer, default=0)
    total_paise: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(100))
    snapshot: Mapped[dict] = mapped_column(JSONB)
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrderItem(Base):
    __tablename__ = "order_items"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id")
    )
    product_name: Mapped[str] = mapped_column(String(180))
    unit_price_paise: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer)
    total_paise: Mapped[int] = mapped_column(Integer)


class Payment(Base, TimestampMixin):
    __tablename__ = "payments"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), index=True
    )
    shop_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("shops.id"))
    purpose: Mapped[str] = mapped_column(String(30), index=True)
    provider: Mapped[str] = mapped_column(String(30), default="razorpay")
    provider_order_id: Mapped[str | None] = mapped_column(String(120), unique=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String(120), unique=True)
    amount_paise: Mapped[int] = mapped_column(Integer)
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, name="payment_status"), default=PaymentStatus.CREATED
    )
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict)


class RewardCampaign(Base, TimestampMixin):
    __tablename__ = "reward_campaigns"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(160))
    area: Mapped[str] = mapped_column(String(120), index=True)
    city: Mapped[str] = mapped_column(String(120), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reward_valid_until: Mapped[date] = mapped_column(Date)
    total_inventory: Mapped[int] = mapped_column(Integer)
    claimed_count: Mapped[int] = mapped_column(Integer, default=0)
    per_user_limit: Mapped[int] = mapped_column(Integer, default=1)
    prizes: Mapped[list] = mapped_column(JSONB)
    artwork_url: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)


class RewardClaim(Base, TimestampMixin):
    __tablename__ = "reward_claims"
    __table_args__ = (UniqueConstraint("campaign_id", "user_id", "claim_sequence"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reward_campaigns.id"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    claim_sequence: Mapped[int] = mapped_column(Integer, default=1)
    prize: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), default="claimed")
    revealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Notification(Base, TimestampMixin):
    __tablename__ = "notifications"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NotificationBroadcast(Base, TimestampMixin):
    __tablename__ = "notification_broadcasts"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text)
    audience: Mapped[str] = mapped_column(String(20), index=True)
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    recipient_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="sent", index=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Promotion(Base, TimestampMixin):
    __tablename__ = "promotions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(160))
    subtitle: Mapped[str] = mapped_column(String(240))
    image_url: Mapped[str] = mapped_column(String(500))
    action_type: Mapped[str] = mapped_column(String(30))
    action_value: Mapped[str] = mapped_column(String(500))
    placement: Mapped[str] = mapped_column(String(20), default="hero", index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    target_city: Mapped[str | None] = mapped_column(String(120), index=True)
    target_area: Mapped[str | None] = mapped_column(String(120), index=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class MediaAsset(Base, TimestampMixin):
    __tablename__ = "media_assets"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    object_key: Mapped[str] = mapped_column(String(500), unique=True, index=True)
    bucket: Mapped[str] = mapped_column(String(120))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    public_url: Mapped[str | None] = mapped_column(String(800))
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class OTPDeliveryEvent(Base, TimestampMixin):
    __tablename__ = "otp_delivery_events"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider_request_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    failure_reason: Mapped[str | None] = mapped_column(String(500))
    phone_last4: Mapped[str | None] = mapped_column(String(4))
    sender_id: Mapped[str | None] = mapped_column(String(30))
    template_id: Mapped[str | None] = mapped_column(String(120))
    dlt_template_id: Mapped[str | None] = mapped_column(String(120))
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    provider_payload: Mapped[dict] = mapped_column(JSONB, default=dict)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    action: Mapped[str] = mapped_column(String(120), index=True)
    resource_type: Mapped[str] = mapped_column(String(80), index=True)
    resource_id: Mapped[str | None] = mapped_column(String(80))
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)
    request_id: Mapped[str | None] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(String(500))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class AppSetting(Base, TimestampMixin):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB)
    description: Mapped[str | None] = mapped_column(Text)
