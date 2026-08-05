import json
import secrets
import time
from datetime import UTC, datetime

import redis.asyncio as redis

from app.core.config import get_settings
from app.core.exceptions import AppException, TooManyRequestsException
from app.services.twilio_verify_service import TwilioVerifyService

settings = get_settings()


class OTPService:
    """
    Handles OTP generation, storage, and verification.
    Uses Redis because OTPs are temporary — Redis auto-expires keys.
    In dev without Redis, falls back to in-memory storage.
    """

    def __init__(self):
        self._redis: redis.Redis | None = None
        self._memory_store: dict[str, tuple[str, float]] = {}

    async def _get_redis(self) -> redis.Redis | None:
        if self._redis is not None:
            return self._redis
        try:
            client = redis.from_url(settings.redis_url, decode_responses=True)
            await client.ping()
            self._redis = client
            return client
        except Exception:
            if settings.environment != "development":
                raise AppException("OTP service is temporarily unavailable", 503)
            return None

    def _otp_key(self, identifier: str, role: str) -> str:
        return f"otp:{role}:{identifier}"

    def _cooldown_key(self, identifier: str, _role: str) -> str:
        # A phone-global cooldown prevents customer and shopkeeper routes being alternated
        # to send multiple billable messages to the same number.
        return f"otp_cooldown:{identifier}"

    def _attempts_key(self, identifier: str, role: str) -> str:
        return f"otp_attempts:{role}:{identifier}"

    def _generate_otp(self) -> str:
        upper = 10**settings.otp_length
        return f"{secrets.randbelow(upper):0{settings.otp_length}d}"

    async def _set_value(self, key: str, value: str, ttl_seconds: int) -> None:
        client = await self._get_redis()
        if client:
            await client.setex(key, ttl_seconds, value)
        else:
            self._memory_store[key] = (value, time.monotonic() + ttl_seconds)

    async def _get_value(self, key: str) -> str | None:
        client = await self._get_redis()
        if client:
            return await client.get(key)
        stored = self._memory_store.get(key)
        if not stored:
            return None
        value, expires_at = stored
        if expires_at <= time.monotonic():
            self._memory_store.pop(key, None)
            return None
        return value

    async def _delete_value(self, key: str) -> None:
        client = await self._get_redis()
        if client:
            await client.delete(key)
        else:
            self._memory_store.pop(key, None)

    async def send_otp(self, identifier: str, role: str) -> tuple[str, int, int, str | None]:
        cooldown_key = self._cooldown_key(identifier, role)
        if await self._get_value(cooldown_key):
            raise TooManyRequestsException(
                f"Please wait {settings.otp_resend_cooldown_seconds} seconds before requesting a new OTP"
            )

        if settings.sms_provider == "twilio":
            payload = await TwilioVerifyService().send(identifier)
            request_id = str(payload["sid"])
            await self._set_value(cooldown_key, "1", settings.otp_resend_cooldown_seconds)
            return (
                "",
                settings.otp_expire_minutes * 60,
                settings.otp_resend_cooldown_seconds,
                request_id,
            )

        otp = self._generate_otp()
        otp_key = self._otp_key(identifier, role)
        otp_data = json.dumps(
            {
                "otp": otp,
                "attempts": 0,
                "created_at": datetime.now(UTC).isoformat(),
            }
        )

        await self._set_value(otp_key, otp_data, settings.otp_expire_minutes * 60)
        await self._set_value(cooldown_key, "1", settings.otp_resend_cooldown_seconds)

        return otp, settings.otp_expire_minutes * 60, settings.otp_resend_cooldown_seconds, None

    async def verify_otp(self, identifier: str, role: str, otp: str) -> bool:
        if settings.sms_provider == "twilio":
            await TwilioVerifyService().verify(identifier, otp)
            return True

        otp_key = self._otp_key(identifier, role)
        stored = await self._get_value(otp_key)

        if not stored:
            raise AppException("OTP expired or not found. Please request a new one.")

        data = json.loads(stored)
        attempts = data.get("attempts", 0)

        if attempts >= settings.otp_max_attempts:
            await self._delete_value(otp_key)
            raise AppException("Too many failed attempts. Please request a new OTP.")

        if data["otp"] != otp:
            data["attempts"] = attempts + 1
            remaining_ttl = settings.otp_expire_minutes * 60
            await self._set_value(otp_key, json.dumps(data), remaining_ttl)
            raise AppException(
                f"Invalid OTP. {settings.otp_max_attempts - data['attempts']} attempts remaining."
            )

        await self._delete_value(otp_key)
        return True

    async def resend_otp(self, identifier: str, role: str) -> tuple[str, int, int, str | None]:
        cooldown_key = self._cooldown_key(identifier, role)
        if await self._get_value(cooldown_key):
            raise TooManyRequestsException(
                f"Please wait {settings.otp_resend_cooldown_seconds} seconds before requesting a new OTP"
            )
        if settings.sms_provider == "twilio":
            payload = await TwilioVerifyService().send(identifier)
            request_id = payload.get("sid")
            await self._set_value(cooldown_key, "1", settings.otp_resend_cooldown_seconds)
            return (
                "",
                settings.otp_expire_minutes * 60,
                settings.otp_resend_cooldown_seconds,
                str(request_id) if request_id else None,
            )
        return await self.send_otp(identifier, role)
