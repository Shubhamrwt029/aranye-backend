import pytest
from pydantic import ValidationError

from app.schemas.auth import OTPResendRequest, OTPSendRequest, OTPVerifyRequest


def test_otp_phone_is_normalized_to_e164():
    request = OTPSendRequest(identifier="+91 89497 28448")
    assert request.identifier == "+918949728448"


def test_verify_and_resend_require_valid_phone_numbers():
    with pytest.raises(ValidationError):
        OTPVerifyRequest(identifier="8949728448", otp="123456")
    with pytest.raises(ValidationError):
        OTPResendRequest(identifier="not-a-phone")


def test_verify_requires_six_digit_otp():
    with pytest.raises(ValidationError):
        OTPVerifyRequest(identifier="+918949728448", otp="1234")
    with pytest.raises(ValidationError):
        OTPVerifyRequest(identifier="+918949728448", otp="12345a")

    request = OTPVerifyRequest(identifier="+918949728448", otp="123456")
    assert request.otp == "123456"
