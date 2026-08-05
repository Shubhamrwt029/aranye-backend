import pytest
from fastapi import HTTPException
from fastapi.security import HTTPBasicCredentials
from pydantic import SecretStr

from app import main


def test_docs_auth_accepts_configured_credentials(monkeypatch):
    monkeypatch.setattr(main.settings, "api_docs_username", "docs-user")
    monkeypatch.setattr(main.settings, "api_docs_password", SecretStr("strong-docs-password"))

    authenticated_user = main.require_docs_auth(
        HTTPBasicCredentials(username="docs-user", password="strong-docs-password")
    )

    assert authenticated_user == "docs-user"


@pytest.mark.parametrize(
    "credentials",
    [
        None,
        HTTPBasicCredentials(username="wrong-user", password="strong-docs-password"),
        HTTPBasicCredentials(username="docs-user", password="wrong-password"),
    ],
)
def test_docs_auth_rejects_missing_or_invalid_credentials(monkeypatch, credentials):
    monkeypatch.setattr(main.settings, "api_docs_username", "docs-user")
    monkeypatch.setattr(main.settings, "api_docs_password", SecretStr("strong-docs-password"))

    with pytest.raises(HTTPException) as error:
        main.require_docs_auth(credentials)

    assert error.value.status_code == 401
    assert error.value.headers == {"WWW-Authenticate": 'Basic realm="Aranye API documentation"'}


def test_public_docs_schema_uses_deployed_paths_and_email_password_auth():
    schema = main.build_public_docs_openapi()

    assert schema["servers"] == [
        {
            "url": main.settings.public_base_url.rstrip("/"),
            "description": f"{main.settings.environment.title()} API",
        }
    ]
    assert "/admin/auth/login" in schema["paths"]
    assert not any(path.startswith("/api/v1") for path in schema["paths"])

    security_schemes = schema["components"]["securitySchemes"]
    assert security_schemes["AdminEmailPassword"]["type"] == "oauth2"
    password_flow = security_schemes["AdminEmailPassword"]["flows"]["password"]
    assert password_flow["tokenUrl"].endswith("/docs/token")
    assert security_schemes["HTTPBearer"]["scheme"] == "bearer"
