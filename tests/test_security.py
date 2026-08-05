from uuid import uuid4

from app.core.security import create_access_token, create_refresh_token, decode_token


def test_access_token_has_production_claims():
    user_id = uuid4()
    payload = decode_token(create_access_token(user_id, "customer"))
    assert payload is not None
    assert payload["sub"] == str(user_id)
    assert payload["type"] == "access"
    assert payload["iss"] and payload["aud"] and payload["jti"]


def test_refresh_token_is_bound_to_session():
    session_id = uuid4()
    payload = decode_token(create_refresh_token(uuid4(), "shopkeeper", session_id))
    assert payload is not None
    assert payload["sid"] == str(session_id)
    assert payload["type"] == "refresh"
