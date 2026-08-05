from pydantic import BaseModel, Field, field_validator

from app.schemas.user import UserResponse
from app.schemas.validators import normalize_phone


class OTPSendRequest(BaseModel):
    """
    Matches Figma 'Welcome Back' screen:
    user enters a mobile number, then taps 'Send OTP'.
    Role is determined by the endpoint (/customer/ or /shopkeeper/).
    """

    identifier: str = Field(
        ...,
        min_length=5,
        max_length=255,
        description="Phone number in international format (+91XXXXXXXXXX)",
        examples=["+918219862104"],
    )

    @field_validator("identifier")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        return normalize_phone(value)


class OTPSendResponse(BaseModel):
    message: str = "OTP request accepted"
    identifier: str
    provider: str
    sms_sent: bool
    otp_expires_in_seconds: int
    resend_available_in_seconds: int
    provider_status: str = "accepted"
    provider_request_id: str | None = None
    # Only returned in development — remove in production
    debug_otp: str | None = None


class OTPVerifyRequest(BaseModel):
    """Verification code; Twilio Verify is configured for six digits."""

    identifier: str
    otp: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")

    @field_validator("identifier")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        return normalize_phone(value)


class OTPResendRequest(BaseModel):
    identifier: str

    @field_validator("identifier")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        return normalize_phone(value)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse
    is_new_user: bool = False


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class AdminLoginRequest(BaseModel):
    """Admin panel uses email + password (not OTP)."""

    email: str
    password: str = Field(..., min_length=8)


class AdminLoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse
