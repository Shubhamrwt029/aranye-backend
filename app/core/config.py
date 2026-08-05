import os
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Central configuration loaded from environment variables.
    MNCs use this pattern so secrets never live in code.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_name: str = "Aranye API"
    app_version: str = "0.1.0"
    environment: Literal["development", "preview", "staging", "production"] = "development"
    app_debug: bool = True
    public_base_url: str = "http://127.0.0.1:8000"
    demo_data_enabled: bool = False

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/aranye_db",
        description="Async PostgreSQL connection string",
    )

    # JWT
    jwt_secret_key: str = Field(
        default="CHANGE-ME-in-production-use-openssl-rand-hex-32",
        description="Secret key for signing JWT tokens",
    )
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    jwt_issuer: str = "aranye-api"
    jwt_audience: str = "aranye-clients"

    # OTP
    otp_length: int = 6
    otp_expire_minutes: int = 10
    otp_resend_cooldown_seconds: int = 60
    otp_max_attempts: int = 5

    # Redis (stores OTP temporarily — fast & auto-expiring)
    redis_url: str = "redis://localhost:6379/0"

    # Integrations
    sms_provider: Literal["console", "twilio"] = "console"
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_verify_service_sid: str | None = None
    twilio_api_key: str | None = None
    twilio_api_key_secret: str | None = None
    twilio_timeout_seconds: float = 10.0
    razorpay_key_id: str | None = None
    razorpay_key_secret: str | None = None
    razorpay_webhook_secret: str | None = None
    s3_endpoint_url: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_bucket: str = "aranye-media"
    s3_region: str = "ap-south-1"
    s3_public_base_url: str | None = None
    media_max_upload_bytes: int = 10_485_760
    media_max_video_upload_bytes: int = 104_857_600
    media_presign_expire_seconds: int = 900
    encryption_key: str | None = None
    launch_city: str = ""
    default_delivery_fee_paise: int = 0
    shop_activation_fee_paise: int = 49900

    # CORS
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:8080"]


@lru_cache
def get_settings() -> Settings:
    settings = Settings(_env_file=os.getenv("ARANYE_ENV_FILE", ".env"))
    if settings.sms_provider == "twilio":
        has_account_credentials = bool(settings.twilio_account_sid and settings.twilio_auth_token)
        has_api_key_credentials = bool(settings.twilio_api_key and settings.twilio_api_key_secret)
        if not settings.twilio_verify_service_sid:
            raise ValueError("TWILIO_VERIFY_SERVICE_SID is required when SMS_PROVIDER=twilio")
        if not (has_account_credentials or has_api_key_credentials):
            raise ValueError(
                "Provide TWILIO_ACCOUNT_SID + TWILIO_AUTH_TOKEN or "
                "TWILIO_API_KEY + TWILIO_API_KEY_SECRET when SMS_PROVIDER=twilio"
            )
        if not has_account_credentials and (
            bool(settings.twilio_api_key) != bool(settings.twilio_api_key_secret)
        ):
            raise ValueError("TWILIO_API_KEY and TWILIO_API_KEY_SECRET must be provided together")
        if not settings.twilio_verify_service_sid.startswith("VA"):
            raise ValueError("TWILIO_VERIFY_SERVICE_SID must be a Verify SID starting with VA")
        if has_account_credentials and not settings.twilio_account_sid.startswith("AC"):
            raise ValueError("TWILIO_ACCOUNT_SID must start with AC")
        if has_api_key_credentials and not settings.twilio_api_key.startswith("SK"):
            raise ValueError("TWILIO_API_KEY must be an API key SID starting with SK")
    if settings.environment == "production":
        if settings.demo_data_enabled:
            raise ValueError("DEMO_DATA_ENABLED must be false in production")
        if settings.sms_provider != "twilio":
            raise ValueError("SMS_PROVIDER must be twilio in production")
        if not settings.public_base_url.startswith("https://"):
            raise ValueError("PUBLIC_BASE_URL must use https in production")
        if "localhost" in settings.database_url or "postgres:postgres" in settings.database_url:
            raise ValueError("Production must use a dedicated database with secure credentials")
        insecure = (
            settings.jwt_secret_key.startswith("CHANGE-ME") or len(settings.jwt_secret_key) < 32
        )
        if insecure:
            raise ValueError("JWT_SECRET_KEY must be a strong secret in production")
        if settings.app_debug:
            raise ValueError("APP_DEBUG must be false in production")
        if not settings.cors_origins or "*" in settings.cors_origins:
            raise ValueError("Explicit CORS_ORIGINS are required in production")
    return settings
