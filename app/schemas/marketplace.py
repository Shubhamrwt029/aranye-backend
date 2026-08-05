from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class ORMModel(BaseModel):
    model_config = {"from_attributes": True}


class Page(BaseModel):
    items: list[Any]
    total: int
    page: int
    page_size: int


class AddressCreate(BaseModel):
    label: str = Field("Home", max_length=50)
    line1: str = Field(min_length=3, max_length=255)
    line2: str | None = Field(None, max_length=255)
    area: str = Field(min_length=2, max_length=120)
    city: str = Field(min_length=2, max_length=120)
    state: str = Field(min_length=2, max_length=120)
    postal_code: str = Field(pattern=r"^\d{6}$")
    latitude: Decimal = Field(ge=-90, le=90)
    longitude: Decimal = Field(ge=-180, le=180)
    is_default: bool = False


class AddressResponse(AddressCreate, ORMModel):
    id: UUID


class ShopCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    business_type: str = Field(min_length=2, max_length=60)
    description: str | None = Field(None, max_length=2000)
    phone: str = Field(pattern=r"^\+[1-9]\d{9,14}$")
    whatsapp_number: str | None = Field(None, pattern=r"^\+[1-9]\d{9,14}$")
    address_line: str = Field(min_length=3, max_length=255)
    area: str = Field(min_length=2, max_length=120)
    city: str = Field(min_length=2, max_length=120)
    postal_code: str = Field(pattern=r"^\d{6}$")
    latitude: Decimal = Field(ge=-90, le=90)
    longitude: Decimal = Field(ge=-180, le=180)
    service_radius_km: Decimal = Field(default=Decimal("5"), gt=0, le=50)
    delivery_fee_paise: int = Field(default=0, ge=0)
    minimum_order_paise: int = Field(default=0, ge=0)
    supports_delivery: bool = True
    supports_pickup: bool = True

    @model_validator(mode="after")
    def fulfillment_required(self):
        if not self.supports_delivery and not self.supports_pickup:
            raise ValueError("At least one fulfillment type is required")
        return self


class ShopResponse(ShopCreate, ORMModel):
    id: UUID
    owner_id: UUID
    status: str
    is_open: bool
    rejection_reason: str | None
    logo_url: str | None
    banner_url: str | None
    rating_average: Decimal
    rating_count: int
    created_at: datetime
    category_names: list[str] = Field(default_factory=list)
    offer_label: str | None = None


class ShopHourInput(BaseModel):
    weekday: int = Field(ge=0, le=6)
    opens_at: time | None = None
    closes_at: time | None = None
    is_closed: bool = False


class BankAccountInput(BaseModel):
    account_holder_name: str = Field(min_length=2, max_length=160)
    account_number: str = Field(pattern=r"^\d{8,20}$")
    ifsc: str = Field(pattern=r"^[A-Z]{4}0[A-Z0-9]{6}$")


class CategoryCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    parent_id: UUID | None = None
    image_url: str | None = None
    is_active: bool = True
    sort_order: int = Field(default=100, ge=0, le=10000)


class CategoryResponse(CategoryCreate, ORMModel):
    id: UUID


class ProductCreate(BaseModel):
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


class ProductResponse(ProductCreate, ORMModel):
    id: UUID
    shop_id: UUID
    rating_average: Decimal
    rating_count: int
    created_at: datetime


class ShopStorefrontResponse(BaseModel):
    shop: ShopResponse
    categories: list[CategoryResponse]
    products: list[ProductResponse]


class ShopProductSearchResult(BaseModel):
    shop: ShopResponse
    matched_product: ProductResponse


class CartItemInput(BaseModel):
    product_id: UUID
    quantity: int = Field(ge=1, le=99)


class CartItemUpdate(BaseModel):
    quantity: int = Field(ge=1, le=99)


class CartProductResponse(ORMModel):
    id: UUID
    name: str
    description: str | None
    price_paise: int
    image_urls: list[str]
    is_available: bool
    rating_average: Decimal
    rating_count: int


class CartItemResponse(ORMModel):
    id: UUID
    product_id: UUID
    quantity: int
    product: CartProductResponse


class CartResponse(BaseModel):
    id: UUID
    shop_id: UUID
    items: list[CartItemResponse]
    subtotal_paise: int
    delivery_fee_paise: int
    total_paise: int


class CheckoutRequest(BaseModel):
    cart_id: UUID
    fulfillment_type: Literal["delivery", "pickup"]
    address_id: UUID | None = None
    payment_method: Literal["cod", "online"]

    @model_validator(mode="after")
    def delivery_address(self):
        if self.fulfillment_type == "delivery" and not self.address_id:
            raise ValueError("Delivery address is required")
        return self


class OrderStatusUpdate(BaseModel):
    status: Literal["accepted", "rejected", "preparing", "ready", "out_for_delivery", "completed"]
    reason: str | None = Field(None, max_length=500)


class OrderResponse(ORMModel):
    id: UUID
    order_number: str
    customer_id: UUID
    shop_id: UUID
    status: str
    fulfillment_type: str
    payment_method: str
    subtotal_paise: int
    delivery_fee_paise: int
    total_paise: int
    snapshot: dict
    created_at: datetime


class CampaignCreate(BaseModel):
    title: str = Field(min_length=2, max_length=160)
    area: str = Field(min_length=2, max_length=120)
    city: str = Field(min_length=2, max_length=120)
    starts_at: datetime
    ends_at: datetime
    reward_valid_until: date
    total_inventory: int = Field(gt=0, le=100000)
    per_user_limit: int = Field(default=1, ge=1, le=10)
    prizes: list[dict] = Field(min_length=1, max_length=50)
    artwork_url: str | None = None

    @field_validator("prizes")
    @classmethod
    def valid_weights(cls, prizes: list[dict]):
        if any(int(p.get("weight", 0)) <= 0 or "label" not in p for p in prizes):
            raise ValueError("Each prize requires a label and positive integer weight")
        return prizes

    @model_validator(mode="after")
    def valid_dates(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        if self.reward_valid_until < self.ends_at.date():
            raise ValueError("reward validity must include the campaign end date")
        return self


class CampaignResponse(CampaignCreate, ORMModel):
    id: UUID
    shop_id: UUID
    claimed_count: int
    status: str


class RewardClaimResponse(ORMModel):
    id: UUID
    campaign_id: UUID
    user_id: UUID
    claim_sequence: int
    prize: dict
    status: str
    revealed_at: datetime | None
    redeemed_at: datetime | None
    created_at: datetime


class PromotionResponse(BaseModel):
    id: UUID
    title: str
    subtitle: str
    image_url: str
    action_type: Literal["shop", "product", "category", "reward", "external"]
    action_value: str
    placement: Literal["hero", "offer"]
    sort_order: int

    model_config = {"from_attributes": True}


class CustomerHomeResponse(BaseModel):
    promotions: list[PromotionResponse]
    offers: list[PromotionResponse]
    categories: list[CategoryResponse]
    shops: list[ShopResponse]
    featured_products: list[ProductResponse]


class PaymentCreate(BaseModel):
    purpose: Literal["order", "shop_activation"]
    order_id: UUID | None = None


class AdminDecision(BaseModel):
    approved: bool
    reason: str | None = Field(None, max_length=1000)


class NotificationCompose(BaseModel):
    title: str = Field(min_length=2, max_length=160)
    body: str = Field(min_length=2, max_length=1000)
    role: Literal["customer", "shopkeeper", "all"] = "all"
    data: dict = Field(default_factory=dict)
