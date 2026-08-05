import httpx
import pytest

from app.core.exceptions import AppException
from app.services import twilio_verify_service as twilio_module
from app.services.twilio_verify_service import TwilioVerifyService


def test_twilio_error_message_includes_provider_code():
    assert (
        TwilioVerifyService._message({"message": "Recipient is not verified", "code": 21608})
        == "Recipient is not verified (Twilio error 21608)"
    )


def test_twilio_generic_error_message():
    assert TwilioVerifyService._message({}) == "Twilio Verify request failed"


@pytest.fixture
def twilio_settings(monkeypatch):
    monkeypatch.setattr(twilio_module.settings, "twilio_account_sid", "AC" + "a" * 32)
    monkeypatch.setattr(twilio_module.settings, "twilio_auth_token", "secret")
    monkeypatch.setattr(twilio_module.settings, "twilio_api_key", None)
    monkeypatch.setattr(twilio_module.settings, "twilio_api_key_secret", None)
    monkeypatch.setattr(twilio_module.settings, "twilio_verify_service_sid", "VA" + "b" * 32)


@pytest.mark.asyncio
async def test_send_verification_accepts_pending_response(twilio_settings):
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/Verifications")
        assert b"To=%2B918949728448" in request.content
        assert b"Channel=sms" in request.content
        return httpx.Response(
            201,
            json={"sid": "VE" + "c" * 32, "status": "pending", "channel": "sms"},
        )

    service = TwilioVerifyService(transport=httpx.MockTransport(handler))
    payload = await service.send("+918949728448")
    assert payload["status"] == "pending"


@pytest.mark.asyncio
async def test_verify_trusts_approved_status_without_legacy_valid_field(twilio_settings):
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"sid": "VE" + "d" * 32, "status": "approved"})

    service = TwilioVerifyService(transport=httpx.MockTransport(handler))
    payload = await service.verify("+918949728448", "123456")
    assert payload["status"] == "approved"


@pytest.mark.asyncio
async def test_verify_maps_deleted_verification_to_actionable_error(twilio_settings):
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={"code": 20404, "message": "The requested resource was not found"},
        )

    service = TwilioVerifyService(transport=httpx.MockTransport(handler))
    with pytest.raises(AppException) as exc_info:
        await service.verify("+918949728448", "123456")
    assert exc_info.value.status_code == 400
    assert "Request a new OTP" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_send_surfaces_twilio_provider_error(twilio_settings):
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"code": 60200, "message": "Invalid parameter To"},
        )

    service = TwilioVerifyService(transport=httpx.MockTransport(handler))
    with pytest.raises(AppException) as exc_info:
        await service.send("+918949728448")
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid parameter To (Twilio error 60200)"
