"""Unit tests for ``app.shared.security`` (no DB, no FastAPI)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest

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


# ---------------------------------------------------------------------------
# Mailbox OAuth ``state`` (signed, short-lived, purpose-bound)
# ---------------------------------------------------------------------------


def _state_key() -> str:
    return security._purpose_key(security.MAILBOX_OAUTH_STATE_TYPE)


def test_mailbox_oauth_state_roundtrip() -> None:
    state = security.create_mailbox_oauth_state("ten-1", "mbx-1", "admin-1")
    assert security.decode_mailbox_oauth_state(state) == {
        "tenant_id": "ten-1",
        "mailbox_id": "mbx-1",
        "initiated_by": "admin-1",
    }


def test_mailbox_oauth_state_expires_after_ttl() -> None:
    assert security.MAILBOX_OAUTH_STATE_TTL <= timedelta(minutes=15)
    state = security.create_mailbox_oauth_state("ten-1", "mbx-1", "admin-1")
    exp = jwt.decode(state, options={"verify_signature": False})["exp"]
    remaining = exp - datetime.now(timezone.utc).timestamp()
    assert 0 < remaining <= security.MAILBOX_OAUTH_STATE_TTL.total_seconds() + 5


def test_mailbox_oauth_state_expired_rejected() -> None:
    expired = jwt.encode(
        {
            "typ": security.MAILBOX_OAUTH_STATE_TYPE,
            "tid": "ten-1",
            "mbx": "mbx-1",
            "by": "admin-1",
            "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
        },
        _state_key(),
        algorithm=get_settings().jwt_algorithm,
    )
    with pytest.raises(ValueError, match="STATE_EXPIRED"):
        security.decode_mailbox_oauth_state(expired)


def test_mailbox_oauth_state_legacy_unsigned_base64_rejected() -> None:
    """The old forgeable format (base64 JSON) must no longer be accepted."""
    import base64
    import json

    legacy = base64.urlsafe_b64encode(
        json.dumps({"tenant_id": "ten-1", "mailbox_id": "mbx-1"}).encode()
    ).decode()
    with pytest.raises(ValueError, match="STATE_INVALID"):
        security.decode_mailbox_oauth_state(legacy)


def test_mailbox_oauth_state_tampered_payload_rejected() -> None:
    state = security.create_mailbox_oauth_state("ten-1", "mbx-1", "admin-1")
    header, payload, sig = state.split(".")
    claims = jwt.decode(state, options={"verify_signature": False})
    forged_claims = claims | {"tid": "victim-tenant"}
    forged_payload = jwt.encode(forged_claims, "x", algorithm="HS256").split(".")[1]
    with pytest.raises(ValueError, match="STATE_INVALID"):
        security.decode_mailbox_oauth_state(f"{header}.{forged_payload}.{sig}")


def test_mailbox_oauth_state_signed_with_jwt_secret_rejected() -> None:
    """A state signed with the plain JWT secret (not the derived key) is not trusted."""
    forged = jwt.encode(
        {
            "typ": security.MAILBOX_OAUTH_STATE_TYPE,
            "tid": "ten-1",
            "mbx": "mbx-1",
            "by": "admin-1",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        get_settings().jwt_secret_key.get_secret_value(),
        algorithm=get_settings().jwt_algorithm,
    )
    with pytest.raises(ValueError, match="STATE_INVALID"):
        security.decode_mailbox_oauth_state(forged)


def test_mailbox_oauth_state_wrong_typ_rejected() -> None:
    other = jwt.encode(
        {
            "typ": "something_else",
            "tid": "ten-1",
            "mbx": "mbx-1",
            "by": "admin-1",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        _state_key(),
        algorithm=get_settings().jwt_algorithm,
    )
    with pytest.raises(ValueError, match="STATE_INVALID"):
        security.decode_mailbox_oauth_state(other)


@pytest.mark.parametrize("missing", ["tid", "mbx", "by"])
def test_mailbox_oauth_state_missing_claim_rejected(missing: str) -> None:
    claims = {
        "typ": security.MAILBOX_OAUTH_STATE_TYPE,
        "tid": "ten-1",
        "mbx": "mbx-1",
        "by": "admin-1",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    del claims[missing]
    token = jwt.encode(claims, _state_key(), algorithm=get_settings().jwt_algorithm)
    with pytest.raises(ValueError, match="STATE_INVALID"):
        security.decode_mailbox_oauth_state(token)


def test_access_token_is_not_a_valid_mailbox_oauth_state() -> None:
    access = security.create_access_token("u", "app_user", "system", None)
    with pytest.raises(ValueError, match="STATE_INVALID"):
        security.decode_mailbox_oauth_state(access)


def test_mailbox_oauth_state_is_not_a_valid_access_token() -> None:
    """State travels in URLs and logs — it must never work as a Bearer token."""
    state = security.create_mailbox_oauth_state("ten-1", "mbx-1", "admin-1")
    with pytest.raises(ValueError, match="TOKEN_INVALID"):
        security.decode_token(state)
    assert "user_id" not in jwt.decode(state, options={"verify_signature": False})


def test_mailbox_oauth_state_unique_per_call() -> None:
    a = security.create_mailbox_oauth_state("ten-1", "mbx-1", "admin-1")
    b = security.create_mailbox_oauth_state("ten-1", "mbx-1", "admin-1")
    assert a != b


def test_access_token_carries_session_id_when_given() -> None:
    token = security.create_access_token(
        "u", "app_user", "tenant", "ten-1", session_id="sess-1"
    )
    assert security.decode_token(token)["sid"] == "sess-1"
    bare = security.create_access_token("u", "app_user", "tenant", "ten-1")
    assert "sid" not in security.decode_token(bare)


# ---------------------------------------------------------------------------
# PyJWT migration — algorithm confusion and unsigned tokens are rejected
# ---------------------------------------------------------------------------


def _claims(**extra: object) -> dict:
    return {
        "user_id": "evil",
        "user_scope": "system",
        "sid": "s",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        **extra,
    }


def test_decode_token_rejects_alg_none() -> None:
    unsigned = jwt.encode(_claims(), key=None, algorithm="none")
    with pytest.raises(ValueError, match="TOKEN_INVALID"):
        security.decode_token(unsigned)


def test_decode_token_rejects_other_hmac_algorithm() -> None:
    """Same secret, different algorithm than configured → not accepted."""
    settings = get_settings()
    other = "HS512" if settings.jwt_algorithm != "HS512" else "HS384"
    token = jwt.encode(
        _claims(), settings.jwt_secret_key.get_secret_value(), algorithm=other
    )
    with pytest.raises(ValueError, match="TOKEN_INVALID"):
        security.decode_token(token)


def test_decode_token_rejects_truncated_signature() -> None:
    token = security.create_access_token("u", "app_user", "system", None, session_id="s")
    with pytest.raises(ValueError, match="TOKEN_INVALID"):
        security.decode_token(token[:-4])


def test_decode_mailbox_state_rejects_alg_none() -> None:
    unsigned = jwt.encode(
        {
            "typ": security.MAILBOX_OAUTH_STATE_TYPE,
            "tid": "t",
            "mbx": "m",
            "by": "b",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        key=None,
        algorithm="none",
    )
    with pytest.raises(ValueError, match="STATE_INVALID"):
        security.decode_mailbox_oauth_state(unsigned)


def test_tokens_issued_are_compact_strings() -> None:
    """PyJWT returns ``str`` (jose did too) — callers put it straight into JSON/headers."""
    token = security.create_access_token("u", "app_user", "system", None, session_id="s")
    assert isinstance(token, str) and token.count(".") == 2
    assert jwt.get_unverified_header(token)["alg"] == get_settings().jwt_algorithm


# ---------------------------------------------------------------------------
# Token ``typ`` (finding #6)
# ---------------------------------------------------------------------------


def _unsigned_claims(token: str) -> dict:
    return jwt.decode(token, options={"verify_signature": False})


def test_access_and_refresh_tokens_carry_typ() -> None:
    access = security.create_access_token("u", "app_user", "system", None, session_id="s")
    refresh = security.create_refresh_token("u", "s")
    assert _unsigned_claims(access)["typ"] == security.ACCESS_TOKEN_TYPE == "access"
    assert _unsigned_claims(refresh)["typ"] == security.REFRESH_TOKEN_TYPE == "refresh"


def test_decode_access_token_accepts_access_only() -> None:
    access = security.create_access_token("u", "app_user", "system", None, session_id="s")
    assert security.decode_access_token(access)["user_id"] == "u"
    with pytest.raises(ValueError, match="TOKEN_INVALID"):
        security.decode_access_token(security.create_refresh_token("u", "s"))


def test_decode_refresh_token_rejects_access_token() -> None:
    access = security.create_access_token("u", "app_user", "system", None, session_id="s")
    with pytest.raises(ValueError, match="TOKEN_INVALID"):
        security.decode_refresh_token(access)
    assert security.decode_refresh_token(security.create_refresh_token("u", "s"))[
        "session_id"
    ] == "s"


def _legacy(claims: dict) -> str:
    settings = get_settings()
    return jwt.encode(
        {**claims, "exp": datetime.now(timezone.utc) + timedelta(days=1)},
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def test_legacy_refresh_token_without_typ_still_accepted() -> None:
    """Refresh tokens issued before ``typ`` must keep working (users stay signed in)."""
    legacy = _legacy({"user_id": "u", "session_id": "s"})
    assert security.decode_refresh_token(legacy)["session_id"] == "s"


def test_legacy_access_token_without_typ_rejected() -> None:
    legacy = _legacy({"user_id": "u", "user_scope": "system", "sid": "s"})
    with pytest.raises(ValueError, match="TOKEN_INVALID"):
        security.decode_access_token(legacy)


@pytest.mark.parametrize("typ", ["access", "mailbox_oauth_state", "", "REFRESH"])
def test_decode_refresh_token_rejects_other_typ(typ: str) -> None:
    with pytest.raises(ValueError, match="TOKEN_INVALID"):
        security.decode_refresh_token(_legacy({"typ": typ, "user_id": "u", "session_id": "s"}))


def test_expired_refresh_token_reports_expired() -> None:
    settings = get_settings()
    expired = jwt.encode(
        {"typ": "refresh", "user_id": "u", "session_id": "s",
         "exp": datetime.now(timezone.utc) - timedelta(seconds=1)},
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(ValueError, match="TOKEN_EXPIRED"):
        security.decode_refresh_token(expired)
