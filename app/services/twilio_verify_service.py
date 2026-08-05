import logging
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.exceptions import AppException

settings = get_settings()
logger = logging.getLogger(__name__)


class TwilioVerifyService:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        if not settings.twilio_verify_service_sid:
            raise AppException("Twilio Verify is not configured", 503)
        if settings.twilio_api_key and settings.twilio_api_key_secret:
            username = settings.twilio_api_key
            password = settings.twilio_api_key_secret
        else:
            username = settings.twilio_account_sid
            password = settings.twilio_auth_token
        if not username or not password:
            raise AppException("Twilio credentials are not configured", 503)
        self.auth = httpx.BasicAuth(username, password)
        self.service_sid = settings.twilio_verify_service_sid
        self.transport = transport

    async def _post(self, resource: str, data: dict[str, str]) -> dict[str, Any]:
        url = f"https://verify.twilio.com/v2/Services/{self.service_sid}/{resource}"
        try:
            async with httpx.AsyncClient(
                timeout=settings.twilio_timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.post(url, data=data, auth=self.auth)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise AppException("Twilio Verify is temporarily unavailable", 503) from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise AppException("Twilio returned an invalid response", 502) from exc
        if response.status_code >= 400:
            logger.warning(
                "Twilio Verify rejected request: status=%s code=%s message=%s",
                response.status_code,
                payload.get("code"),
                payload.get("message"),
            )
        if response.status_code in {401, 403}:
            # This is a server/provider credential problem, not an Aranye client login failure.
            raise AppException(self._message(payload), 502)
        if response.status_code == 429:
            raise AppException(self._message(payload), 429)
        if response.status_code >= 500:
            raise AppException(self._message(payload), 503)
        if response.status_code >= 400:
            raise AppException(self._message(payload), 400)
        return payload

    @staticmethod
    def _message(payload: dict[str, Any]) -> str:
        message = str(payload.get("message") or "Twilio Verify request failed")
        code = payload.get("code")
        return f"{message} (Twilio error {code})" if code else message

    async def send(self, identifier: str) -> dict[str, Any]:
        payload = await self._post("Verifications", {"To": identifier, "Channel": "sms"})
        if payload.get("status") != "pending" or not payload.get("sid"):
            raise AppException(self._message(payload), 502)
        logger.info(
            "Twilio verification accepted: sid=%s status=%s channel=%s",
            payload.get("sid"),
            payload.get("status"),
            payload.get("channel"),
        )
        return payload

    async def verify(self, identifier: str, code: str) -> dict[str, Any]:
        try:
            payload = await self._post("VerificationCheck", {"To": identifier, "Code": code})
        except AppException as exc:
            # Twilio deletes a verification after expiry, approval, or max attempts and then
            # answers the check with 404. Present that as an invalid/expired code to clients.
            if exc.status_code == 400 and "20404" in str(exc.detail):
                raise AppException(
                    "Verification expired, was already used, or reached the maximum attempts. "
                    "Request a new OTP.",
                    400,
                ) from exc
            raise
        if payload.get("status") != "approved":
            status = payload.get("status", "unknown")
            raise AppException(f"Invalid or expired verification code (status: {status})", 400)
        logger.info(
            "Twilio verification approved: sid=%s status=%s",
            payload.get("sid"),
            payload.get("status"),
        )
        return payload
