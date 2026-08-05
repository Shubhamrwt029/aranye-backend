from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.models.marketplace import OrderStatus, PaymentStatus, ShopStatus


class PageResponse(BaseModel):
    items: list[Any]
    total: int
    limit: int
    offset: int


class UserAdminUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=100)
    email: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, pattern=r"^\+[1-9]\d{9,14}$")
    profile_image_url: str | None = Field(None, max_length=500)
    is_active: bool | None = None
    expected_updated_at: datetime | None = None
    reason: str = Field(min_length=3, max_length=500)


class ShopAdminUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=160)
    business_type: str | None = Field(None, min_length=2, max_length=60)
    description: str | None = Field(None, max_length=2000)
    phone: str | None = Field(None, pattern=r"^\+[1-9]\d{9,14}$")
    whatsapp_number: str | None = Field(None, pattern=r"^\+[1-9]\d{9,14}$")
    address_line: str | None = Field(None, min_length=3, max_length=255)
    area: str | None = Field(None, min_length=2, max_length=120)
    city: str | None = Field(None, min_length=2, max_length=120)
    postal_code: str | None = Field(None, pattern=r"^\d{6}$")
    service_radius_km: Decimal | None = Field(None, gt=0, le=50)
    delivery_fee_paise: int | None = Field(None, ge=0)
    minimum_order_paise: int | None = Field(None, ge=0)
    supports_delivery: bool | None = None
    supports_pickup: bool | None = None
    is_open: bool | None = None
    logo_url: str | None = Field(None, max_length=500)
    banner_url: str | None = Field(None, max_length=500)
    expected_updated_at: datetime | None = None
    reason: str = Field(min_length=3, max_length=500)


class LifecycleAction(BaseModel):
    status: ShopStatus
    reason: str = Field(min_length=3, max_length=500)


class AdminStatusAction(BaseModel):
    is_active: bool
    reason: str = Field(min_length=3, max_length=500)


class CategoryAdminUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=100)
    slug: str | None = Field(None, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    parent_id: UUID | None = None
    image_url: str | None = Field(None, max_length=500)
    is_active: bool | None = None
    sort_order: int | None = Field(None, ge=0, le=10000)
    expected_updated_at: datetime | None = None
    reason: str = Field(min_length=3, max_length=500)


class ProductAdminCreate(BaseModel):
    shop_id: UUID
    name: str = Field(min_length=2, max_length=180)
    category_id: UUID | None = None
    description: str | None = Field(None, max_length=5000)
    ingredients: str | None = Field(None, max_length=3000)
    price_paise: int = Field(gt=0)
    compare_at_price_paise: int | None = Field(None, gt=0)
    stock_quantity: int | None = Field(None, ge=0)
    is_available: bool = True
    is_featured: bool = False
    image_urls: list[str] = Field(default_factory=list, max_length=8)


class ProductAdminUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=180)
    category_id: UUID | None = None
    description: str | None = Field(None, max_length=5000)
    ingredients: str | None = Field(None, max_length=3000)
    price_paise: int | None = Field(None, gt=0)
    compare_at_price_paise: int | None = Field(None, gt=0)
    stock_quantity: int | None = Field(None, ge=0)
    is_available: bool | None = None
    is_featured: bool | None = None
    image_urls: list[str] | None = Field(None, max_length=8)
    expected_updated_at: datetime | None = None
    reason: str = Field(min_length=3, max_length=500)


class PromotionCreate(BaseModel):
    title: str = Field(min_length=2, max_length=160)
    subtitle: str = Field(min_length=2, max_length=240)
    image_url: str = Field(min_length=5, max_length=500)
    action_type: Literal["shop", "product", "category", "reward", "external"]
    action_value: str = Field(min_length=1, max_length=500)
    placement: Literal["hero", "offer"] = "hero"
    sort_order: int = Field(0, ge=0)
    target_city: str | None = Field(None, max_length=120)
    target_area: str | None = Field(None, max_length=120)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    is_active: bool = True

    @model_validator(mode="after")
    def valid_window(self):
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class PromotionUpdate(BaseModel):
    title: str | None = Field(None, min_length=2, max_length=160)
    subtitle: str | None = Field(None, min_length=2, max_length=240)
    image_url: str | None = Field(None, min_length=5, max_length=500)
    action_type: Literal["shop", "product", "category", "reward", "external"] | None = None
    action_value: str | None = Field(None, min_length=1, max_length=500)
    placement: Literal["hero", "offer"] | None = None
    sort_order: int | None = Field(None, ge=0)
    target_city: str | None = Field(None, max_length=120)
    target_area: str | None = Field(None, max_length=120)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    is_active: bool | None = None
    expected_updated_at: datetime | None = None
    reason: str = Field(min_length=3, max_length=500)


class CampaignAdminUpdate(BaseModel):
    title: str | None = Field(None, min_length=2, max_length=160)
    area: str | None = Field(None, min_length=2, max_length=120)
    city: str | None = Field(None, min_length=2, max_length=120)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    total_inventory: int | None = Field(None, gt=0, le=100000)
    per_user_limit: int | None = Field(None, ge=1, le=10)
    artwork_url: str | None = Field(None, max_length=500)
    status: Literal["draft", "active", "suspended", "completed"] | None = None
    expected_updated_at: datetime | None = None
    reason: str = Field(min_length=3, max_length=500)


class CampaignAdminCreate(BaseModel):
    shop_id: UUID
    title: str = Field(min_length=2, max_length=160)
    area: str = Field(min_length=2, max_length=120)
    city: str = Field(min_length=2, max_length=120)
    starts_at: datetime
    ends_at: datetime
    reward_valid_until: date
    total_inventory: int = Field(gt=0, le=100000)
    per_user_limit: int = Field(default=1, ge=1, le=10)
    prizes: list[dict] = Field(min_length=1, max_length=50)
    artwork_url: str | None = Field(None, max_length=500)
    status: Literal["draft", "active"] = "draft"

    @model_validator(mode="after")
    def valid_campaign(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        if self.reward_valid_until < self.ends_at.date():
            raise ValueError("reward validity must include the campaign end date")
        if any(int(prize.get("weight", 0)) <= 0 or "label" not in prize for prize in self.prizes):
            raise ValueError("Each prize requires a label and positive integer weight")
        return self


class ClaimAction(BaseModel):
    status: Literal["claimed", "redeemed", "revoked"]
    reason: str = Field(min_length=3, max_length=500)


class OrderAdminAction(BaseModel):
    status: OrderStatus
    reason: str = Field(min_length=3, max_length=500)


class PaymentAdminAction(BaseModel):
    action: Literal["refund", "reconcile"]
    reason: str = Field(min_length=3, max_length=500)
    expected_status: PaymentStatus | None = None


class DeleteConfirmation(BaseModel):
    password: str = Field(min_length=8)
    confirmation: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=3, max_length=500)


class AdminCreate(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=12, max_length=128)
    name: str = Field(min_length=2, max_length=100)


class AdminPasswordChange(BaseModel):
    current_password: str = Field(min_length=8)
    new_password: str = Field(min_length=12, max_length=128)


class AdminPasswordReset(BaseModel):
    admin_password: str = Field(min_length=8)
    new_password: str = Field(min_length=12, max_length=128)
    reason: str = Field(min_length=3, max_length=500)


class MarketplaceSettings(BaseModel):
    launch_city: str = Field(max_length=120)
    default_delivery_fee_paise: int = Field(ge=0, le=100000)
    shop_activation_fee_paise: int = Field(ge=0, le=10_000_000)
    cancellation_window_minutes: int = Field(ge=0, le=1440)
    support_email: str | None = Field(None, max_length=255)
    support_phone: str | None = Field(None, pattern=r"^\+[1-9]\d{9,14}$")


class MediaPresignRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: Literal["image/jpeg", "image/png", "image/webp"]
    size_bytes: int = Field(gt=0)
    kind: Literal["shop", "product", "category", "promotion", "reward", "profile"]


class MediaCompleteRequest(BaseModel):
    size_bytes: int = Field(gt=0)
