from datetime import date

import pytest
from pydantic import ValidationError

from app.schemas.user import ProfileCompleteRequest, ProfileUpdateRequest


def test_profile_completion_normalizes_whatsapp_number():
    request = ProfileCompleteRequest(
        gender="female",
        date_of_birth=date(2000, 1, 1),
        whatsapp_number="+91 89497 28448",
    )
    assert request.whatsapp_number == "+918949728448"


def test_profile_image_requires_http_url():
    with pytest.raises(ValidationError):
        ProfileUpdateRequest(profile_image_url="javascript:alert(1)")

    request = ProfileUpdateRequest(profile_image_url="https://cdn.example.com/profile.jpg")
    assert request.profile_image_url == "https://cdn.example.com/profile.jpg"
