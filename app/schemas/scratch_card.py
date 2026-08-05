from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.scratch_card import (
    DistributionJobStatus,
    DistributionMethod,
    ScratchAssignmentStatus,
    ScratchCardStatus,
    ScratchCardType,
)


class ORMModel(BaseModel):
    model_config = {"from_attributes": True}


class ScratchCardFields(BaseModel):
    title: str = Field(min_length=2, max_length=160)
    subtitle: str | None = Field(None, max_length=240)
    description: str | None = Field(None, max_length=5000)
    image_url: str | None = Field(None, max_length=800)
    banner_url: str | None = Field(None, max_length=800)
    reward_type: str = Field(min_length=2, max_length=50)
    offer_type: str | None = Field(None, max_length=50)
    terms_and_conditions: str | None = Field(None, max_length=10000)
    coupon_code: str | None = Field(None, min_length=2, max_length=80)
    coupon_type: Literal["unique", "shared"] = "unique"
    redemption_code_prefix: str | None = Field(None, min_length=3, max_length=12)
    shop_id: UUID | None = None
    starts_at: datetime
    ends_at: datetime
    expires_at: datetime
    priority: int = Field(default=100, ge=0, le=10000)
    daily_redemption_limit: int | None = Field(None, gt=0, le=10_000_000)
    total_redemption_limit: int | None = Field(None, gt=0, le=100_000_000)
    scratch_card_type: ScratchCardType

    @field_validator("redemption_code_prefix", mode="before")
    @classmethod
    def normalize_redemption_code_prefix(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = "".join(character for character in value.upper() if character.isalnum())
        if len(normalized) < 3:
            raise ValueError("redemption_code_prefix must contain at least 3 letters or numbers")
        return normalized

    @model_validator(mode="after")
    def validate_business_rules(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        if self.expires_at < self.ends_at:
            raise ValueError("expires_at must be on or after ends_at")
        if self.scratch_card_type == ScratchCardType.SHOPKEEPER_PROMOTION and not self.shop_id:
            raise ValueError("shop_id is required for a shopkeeper promotion")
        if self.reward_type.strip().lower().replace(" ", "_") == "free_product" and not self.shop_id:
            raise ValueError("shop_id is required for a physical free-product reward")
        if self.coupon_type == "shared" and not self.coupon_code:
            raise ValueError("coupon_code is required when coupon_type is shared")
        if (
            self.daily_redemption_limit
            and self.total_redemption_limit
            and self.daily_redemption_limit > self.total_redemption_limit
        ):
            raise ValueError("daily redemption limit cannot exceed total redemption limit")
        return self


class ScratchCardCreate(ScratchCardFields):
    pass


class ScratchCardUpdate(BaseModel):
    title: str | None = Field(None, min_length=2, max_length=160)
    subtitle: str | None = Field(None, max_length=240)
    description: str | None = Field(None, max_length=5000)
    image_url: str | None = Field(None, max_length=800)
    banner_url: str | None = Field(None, max_length=800)
    reward_type: str | None = Field(None, min_length=2, max_length=50)
    offer_type: str | None = Field(None, max_length=50)
    terms_and_conditions: str | None = Field(None, max_length=10000)
    coupon_code: str | None = Field(None, min_length=2, max_length=80)
    coupon_type: Literal["unique", "shared"] | None = None
    redemption_code_prefix: str | None = Field(None, min_length=3, max_length=12)
    shop_id: UUID | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    expires_at: datetime | None = None
    priority: int | None = Field(None, ge=0, le=10000)
    daily_redemption_limit: int | None = Field(None, gt=0, le=10_000_000)
    total_redemption_limit: int | None = Field(None, gt=0, le=100_000_000)
    scratch_card_type: ScratchCardType | None = None
    expected_updated_at: datetime | None = None
    reason: str = Field(default="Scratch card updated", min_length=3, max_length=500)

    @field_validator("redemption_code_prefix", mode="before")
    @classmethod
    def normalize_redemption_code_prefix(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = "".join(character for character in value.upper() if character.isalnum())
        if len(normalized) < 3:
            raise ValueError("redemption_code_prefix must contain at least 3 letters or numbers")
        return normalized


class ScratchCardResponse(ScratchCardFields, ORMModel):
    id: UUID
    status: ScratchCardStatus
    created_by: UUID
    approved_by: UUID | None
    approved_at: datetime | None
    published_at: datetime | None
    total_redeemed: int
    created_at: datetime
    updated_at: datetime


class DistributionRequest(BaseModel):
    distribution_method: DistributionMethod
    quantity: int | None = Field(None, gt=0, le=10_000_000)
    radius_km: float | None = Field(None, gt=0, le=100)
    user_ids: list[UUID] = Field(default_factory=list, max_length=10000)
    area: str | None = Field(None, min_length=2, max_length=120)
    city: str | None = Field(None, min_length=2, max_length=120)

    @model_validator(mode="after")
    def validate_method_filters(self):
        method = self.distribution_method
        if method in {
            DistributionMethod.RANDOM,
            DistributionMethod.NEARBY_QUANTITY,
            DistributionMethod.BIRTHDAY,
        } and not self.quantity:
            raise ValueError("quantity is required for this distribution method")
        if method in {DistributionMethod.NEARBY, DistributionMethod.NEARBY_QUANTITY}:
            if self.radius_km is None:
                raise ValueError("radius_km is required for nearby distribution")
        if method == DistributionMethod.TARGETED and not self.user_ids:
            raise ValueError("user_ids is required for targeted distribution")
        if method == DistributionMethod.AREA and (not self.area or not self.city):
            raise ValueError("area and city are required for area distribution")
        return self

    def job_filters(self) -> dict:
        return {
            key: value
            for key, value in {
                "radius_km": self.radius_km,
                "user_ids": [str(item) for item in self.user_ids] if self.user_ids else None,
                "area": self.area.strip() if self.area else None,
                "city": self.city.strip() if self.city else None,
            }.items()
            if value is not None
        }


class DistributionEstimate(BaseModel):
    eligible_count: int
    already_assigned_count: int
    assignable_count: int
    requested_quantity: int | None


class DistributionJobResponse(ORMModel):
    id: UUID
    scratch_card_id: UUID
    distribution_method: DistributionMethod
    filters: dict
    requested_quantity: int | None
    status: DistributionJobStatus
    eligible_count: int
    assigned_count: int
    skipped_count: int
    failed_count: int
    attempts: int
    max_attempts: int
    error_message: str | None
    created_by: UUID
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AssignmentResponse(ORMModel):
    id: UUID
    scratch_card_id: UUID
    user_id: UUID
    distribution_job_id: UUID | None
    distribution_method: DistributionMethod
    assigned_by: UUID
    assigned_at: datetime
    status: ScratchAssignmentStatus
    redemption_code: str
    viewed_at: datetime | None
    scratched_at: datetime | None
    redeemed_at: datetime | None
    expired_at: datetime | None


class ScratchCardListItem(BaseModel):
    assignment_id: UUID
    scratch_card_id: UUID
    title: str
    subtitle: str | None
    image_url: str | None
    banner_url: str | None
    reward_type: str
    offer_type: str | None
    expires_at: datetime
    priority: int
    status: ScratchAssignmentStatus
    scratched: bool
    redeemed: bool
    shop_id: UUID | None
    shop_name: str | None


class ScratchCardReveal(ScratchCardListItem):
    description: str | None
    terms_and_conditions: str | None
    coupon_code: str | None
    redemption_code: str
    coupon_type: str


class RedemptionCodeRequest(BaseModel):
    redemption_code: str = Field(min_length=6, max_length=24)


class RedemptionPreview(BaseModel):
    assignment_id: UUID
    scratch_card_id: UUID
    title: str
    customer_name: str | None
    customer_phone: str | None
    expires_at: datetime
    status: ScratchAssignmentStatus
    redeemed_at: datetime | None


class ShopScratchCampaign(ORMModel):
    id: UUID
    title: str
    subtitle: str | None
    description: str | None
    image_url: str | None
    banner_url: str | None
    reward_type: str
    offer_type: str | None
    terms_and_conditions: str | None
    redemption_code_prefix: str | None
    starts_at: datetime
    ends_at: datetime
    expires_at: datetime
    status: ScratchCardStatus
    total_redeemed: int


class ScratchAnalytics(BaseModel):
    total_assigned: int
    total_viewed: int
    total_scratched: int
    total_redeemed: int
    expired: int
    unused: int
    ctr: float
    scratch_conversion: float
    redemption_rate: float
    distribution_reach: dict[str, int]
    nearby_reach: int
    random_reach: int
    daily_stats: list[dict]
