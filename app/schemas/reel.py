from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class ORMModel(BaseModel):
    model_config = {"from_attributes": True}


class ReelMediaPresignRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: Literal[
        "image/jpeg",
        "image/png",
        "image/webp",
        "video/mp4",
        "video/quicktime",
        "video/webm",
    ]
    size_bytes: int = Field(gt=0)


class ReelMediaCompleteRequest(BaseModel):
    size_bytes: int = Field(gt=0)


class ReelCreate(BaseModel):
    title: str = Field(min_length=2, max_length=160)
    caption: str | None = Field(None, max_length=3000)
    category: str = Field(min_length=2, max_length=80)
    media_type: Literal["image", "video"]
    media_asset_id: UUID
    poster_asset_id: UUID | None = None
    cta_type: Literal["none", "shop", "product", "external", "call"] = "shop"
    cta_value: str | None = Field(None, max_length=1000)
    product_id: UUID | None = None
    priority: int = Field(100, ge=0, le=10000)
    starts_at: datetime | None = None
    ends_at: datetime | None = None

    @field_validator("title", "category")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        if not (cleaned := " ".join(value.split())):
            raise ValueError("Value cannot be blank")
        return cleaned

    @model_validator(mode="after")
    def validate_reel(self):
        if self.ends_at and self.starts_at and self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        if self.cta_type == "product" and not self.product_id:
            raise ValueError("product_id is required for a product CTA")
        if self.cta_type == "external" and not self.cta_value:
            raise ValueError("cta_value is required for an external CTA")
        return self


class ReelUpdate(BaseModel):
    title: str | None = Field(None, min_length=2, max_length=160)
    caption: str | None = Field(None, max_length=3000)
    category: str | None = Field(None, min_length=2, max_length=80)
    media_type: Literal["image", "video"] | None = None
    media_asset_id: UUID | None = None
    poster_asset_id: UUID | None = None
    cta_type: Literal["none", "shop", "product", "external", "call"] | None = None
    cta_value: str | None = Field(None, max_length=1000)
    product_id: UUID | None = None
    priority: int | None = Field(None, ge=0, le=10000)
    starts_at: datetime | None = None
    ends_at: datetime | None = None

    @field_validator("title", "category")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not (cleaned := " ".join(value.split())):
            raise ValueError("Value cannot be blank")
        return cleaned

    @model_validator(mode="after")
    def validate_update(self):
        non_nullable = ("title", "category", "cta_type", "priority")
        if any(
            field in self.model_fields_set and getattr(self, field) is None
            for field in non_nullable
        ):
            raise ValueError("title, category, cta_type, and priority cannot be null")
        media_change_requested = bool({"media_type", "media_asset_id"} & self.model_fields_set)
        if media_change_requested and (not self.media_type or not self.media_asset_id):
            raise ValueError("media_type and media_asset_id must be supplied together")
        if self.ends_at and self.starts_at and self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class ReelAdvertiser(BaseModel):
    shop_id: UUID
    name: str
    phone: str
    whatsapp_number: str | None
    logo_url: str | None


class ReelResponse(ORMModel):
    id: UUID
    title: str
    caption: str | None
    category: str
    media_type: str
    media_url: str
    poster_url: str | None
    cta_type: str
    cta_value: str | None
    product_id: UUID | None
    advertiser: ReelAdvertiser
    like_count: int
    save_count: int
    share_count: int
    view_count: int
    is_liked: bool
    is_saved: bool
    published_at: datetime | None


class ReelFeedResponse(BaseModel):
    items: list[ReelResponse]
    total: int
    limit: int
    offset: int


class ReelManageResponse(ORMModel):
    id: UUID
    shop_id: UUID
    product_id: UUID | None
    title: str
    caption: str | None
    category: str
    media_type: str
    media_url: str
    poster_url: str | None
    cta_type: str
    cta_value: str | None
    status: str
    priority: int
    starts_at: datetime | None
    ends_at: datetime | None
    published_at: datetime | None
    like_count: int
    save_count: int
    share_count: int
    view_count: int
    click_count: int
    created_at: datetime
    updated_at: datetime


class ReelEngagementResponse(BaseModel):
    reel_id: UUID
    is_liked: bool
    is_saved: bool
    like_count: int
    save_count: int
    share_count: int
    view_count: int
    click_count: int


class ReelViewInput(BaseModel):
    watched_ms: int = Field(0, ge=0, le=86_400_000)
    completed: bool = False


class ReelShareInput(BaseModel):
    platform: Literal["whatsapp", "facebook", "instagram", "system", "copy", "other"]


class ReelAnalyticsResponse(BaseModel):
    reel_id: UUID
    likes: int
    saves: int
    unique_views: int
    completed_views: int
    shares: int
    cta_clicks: int
    completion_rate: float
