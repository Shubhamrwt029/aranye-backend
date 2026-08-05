import base64
import hashlib

from cryptography.fernet import Fernet

from app.core.config import get_settings


def _fernet() -> Fernet:
    settings = get_settings()
    material = settings.encryption_key or settings.jwt_secret_key
    if settings.environment == "production" and not settings.encryption_key:
        raise RuntimeError("ENCRYPTION_KEY is required in production")
    key = base64.urlsafe_b64encode(hashlib.sha256(material.encode()).digest())
    return Fernet(key)


def encrypt_value(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_value(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()
