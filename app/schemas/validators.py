import re

import phonenumbers

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


def normalize_phone(value: str) -> str:
    """Validate and normalize a phone number to E.164."""
    value = value.strip()
    try:
        parsed = phonenumbers.parse(value, None)
    except phonenumbers.NumberParseException as exc:
        raise ValueError("Enter a valid phone number with country code") from exc
    if not phonenumbers.is_valid_number(parsed):
        raise ValueError("Enter a valid phone number with country code")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
