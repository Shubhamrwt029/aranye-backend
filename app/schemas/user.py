from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.schemas.validators import normalize_phone


class ProfileCompleteRequest(BaseModel):
    """
    Matches Figma 'Add Your Detail' screen:
    gender, date of birth, WhatsApp number.
    """

    gender: Literal["male", "female", "other"]
    date_of_birth: date
    whatsapp_number: str = Field(..., min_length=10, max_length=18)
    name: str | None = Field(None, min_length=2, max_length=100)

    @field_validator("date_of_birth")
    @classmethod
    def validate_dob(cls, value: date) -> date:
        today = date.today()
        if value >= today:
            raise ValueError("Date of birth must be in the past")
        age = today.year - value.year - ((today.month, today.day) < (value.month, value.day))
        if age < 13:
            raise ValueError("You must be at least 13 years old")
        return value

    @field_validator("whatsapp_number")
    @classmethod
    def validate_whatsapp_number(cls, value: str) -> str:
        return normalize_phone(value)


class ProfileUpdateRequest(BaseModel):
    """Fields editable from the customer Profile screen."""

    name: str | None = Field(None, min_length=2, max_length=100)
    profile_image_url: str | None = Field(None, max_length=500)

    @field_validator("profile_image_url")
    @classmethod
    def validate_profile_image_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value.startswith(("https://", "http://")):
            raise ValueError("Profile image URL must use http or https")
        return value


class UserResponse(BaseModel):
    id: UUID
    phone: str | None
    email: str | None
    role: str
    name: str | None
    gender: str | None
    date_of_birth: date | None
    whatsapp_number: str | None
    profile_image_url: str | None
    is_profile_complete: bool
    is_phone_verified: bool
    created_at: datetime

    model_config = {"from_attributes": True}
