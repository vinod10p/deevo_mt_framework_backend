"""Unit tests for ``app.shared.security`` (no DB, no FastAPI)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt

from mtf.shared import security
from mtf.shared.config import get_settings


def test_hash_and_verify_password_roundtrip() -> None:
    h = security.hash_password("correct horse battery staple")
    assert security.verify_password("correct horse battery staple", h) is True
    assert security.verify_password("wrong", h) is False


def test_verify_password_never_raises_on_bad_hash() -> None:
    assert security.verify_password("x", "not-a-valid-hash") is False


def test_hash_token_is_sha256_digest() -> None:
    a = security.hash_token("same")
    b = security.hash_token("same")
    assert len(a) == 32 and a == b
    assert security.hash_token("other") != a


def test_generate_id_ulid_length() -> None:
    assert len(security.generate_id()) == 26


def test_access_token_roundtrip_payload() -> None:
    token = security.create_access_token(
        "user-1",
        "app_user",
        "tenant",
        tenant_id="ten-1",
    )
    claims = security.decode_token(token)
    assert claims["user_id"] == "user-1"
    assert claims["user_type"] == "app_user"
    assert claims["user_scope"] == "tenant"
    assert claims["tenant_id"] == "ten-1"
    assert isinstance(claims["exp"], int)
    assert len(claims["jti"]) == 26

    token_portal = security.create_access_token(
        "user-2",
        "app_user",
        "tenant_account",
        tenant_id="ten-1",
        account_id="acc-1",
    )
    portal_claims = security.decode_token(token_portal)
    assert portal_claims["tenant_id"] == "ten-1"
    assert portal_claims["account_id"] == "acc-1"


def test_refresh_token_roundtrip_payload() -> None:
    token = security.create_refresh_token("user-1", "session-1")
    claims = security.decode_token(token)
    assert claims["user_id"] == "user-1"
    assert claims["session_id"] == "session-1"
    assert isinstance(claims["exp"], int)
    assert len(claims["jti"]) == 26


def test_decode_token_invalid() -> None:
    with pytest.raises(ValueError, match="TOKEN_INVALID"):
        security.decode_token("not.a.jwt")


def test_decode_token_expired() -> None:
    settings = get_settings()
    exp = datetime.now(timezone.utc) - timedelta(minutes=5)
    bad = jwt.encode(
        {"sub": "x", "exp": exp},
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(ValueError, match="TOKEN_EXPIRED"):
        security.decode_token(bad)


def test_decode_token_wrong_signature_invalid() -> None:
    """Token signed with a different secret must not verify."""
    settings = get_settings()
    exp = datetime.now(timezone.utc) + timedelta(hours=1)
    forged = jwt.encode(
        {"user_id": "evil", "exp": exp},
        "totally-different-secret-key",
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(ValueError, match="TOKEN_INVALID"):
        security.decode_token(forged)


def test_access_token_jti_unique_per_token() -> None:
    t1 = security.create_access_token("u", "app_user", "tenant", None)
    t2 = security.create_access_token("u", "app_user", "tenant", None)
    assert security.decode_token(t1)["jti"] != security.decode_token(t2)["jti"]


def test_generate_id_distinct_under_burst() -> None:
    """Many sequential ULIDs should be unique (collision astronomically unlikely)."""
    ids = {security.generate_id() for _ in range(50)}
    assert len(ids) == 50
