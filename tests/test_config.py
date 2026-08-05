import pytest

from app.core.config import get_settings


def test_production_rejects_demo_data(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("APP_DEBUG", "false")
    monkeypatch.setenv("DEMO_DATA_ENABLED", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:secret@db.example.com/aranye")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://api.example.com")
    monkeypatch.setenv("JWT_SECRET_KEY", "a" * 64)
    get_settings.cache_clear()
    try:
        with pytest.raises(ValueError, match="DEMO_DATA_ENABLED"):
            get_settings()
    finally:
        get_settings.cache_clear()
