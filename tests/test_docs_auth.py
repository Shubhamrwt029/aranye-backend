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
