"""``get_current_user`` — access tokens die with their session and membership (no DB)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from mtf.shared import security
from mtf.shared.config import get_settings
from mtf.shared.deps import CurrentUser, get_business_unit_id, get_current_user

USER_ID = "01HZYJZGXM0KV0K4T8Y9USER01"
SESSION_ID = "01HZYJZGXM0KV0K4T8Y9SESS01"
TENANT_ID = "01HZYJZGXM0KV0K4T8Y9ABCDE0"
ACCOUNT_ID = "01HZYJZGXM0KV0K4T8Y9ABCDE1"
BUSINESS_UNIT_ID = "01HZYJZGXM0KV0K4T8Y9ABCDEB"


def _token(scope: str = "system", **kwargs: object) -> str:
    tenant_id = kwargs.pop("tenant_id", TENANT_ID if scope != "system" else None)
    account_id = kwargs.pop("account_id", ACCOUNT_ID if scope == "tenant_account" else None)
    session_id = kwargs.pop("session_id", SESSION_ID)
    return security.create_access_token(
        USER_ID, "app_user", scope, tenant_id, account_id, session_id=session_id
    )


def _db(session_hash: bytes | None = None, *roles: str | None) -> MagicMock:
    """The session lookup finds ``session_hash`` at BUSINESS_UNIT_ID (``None``: no live
    session); membership lookups then return ``roles`` in order."""
    db = MagicMock()
    row = MagicMock(token_hash=session_hash, business_unit_id=BUSINESS_UNIT_ID)
    db.execute.return_value.first.return_value = row if session_hash is not None else None
    db.scalars.return_value.first.side_effect = list(roles)
    return db


def _call(token: str, db: MagicMock):
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    return get_current_user(credentials=creds, db=db)


def _assert_401(token: str, db: MagicMock, message: str) -> None:
    with pytest.raises(HTTPException) as exc_info:
        _call(token, db)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail["message"] == message


def _assert_no_db(db: MagicMock) -> None:
    db.execute.assert_not_called()
    db.scalars.assert_not_called()


def _sql(db: MagicMock, call: int = 0) -> str:
    """SQL of query ``call``: 0 is the session lookup, then the membership lookups."""
    stmt = (db.execute.call_args_list + db.scalars.call_args_list)[call].args[0]
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


# ---------------------------------------------------------------------------
# Session must be live and this must be its current token
# ---------------------------------------------------------------------------


def test_live_session_system_user_ok() -> None:
    token = _token("system")
    db = _db(security.hash_token(token))
    user = _call(token, db)
    assert (user.user_id, user.user_scope, user.tenant_id) == (USER_ID, "system", None)
    db.scalars.assert_not_called()  # system users need no membership lookup


def test_session_lookup_is_by_pk_and_checks_revocation_and_user() -> None:
    token = _token("system")
    db = _db(security.hash_token(token))
    _call(token, db)
    sql = _sql(db)
    assert f"auth.session.id = '{SESSION_ID}'" in sql
    assert f"auth.session.user_id = '{USER_ID}'" in sql
    assert "auth.session.is_active = true" in sql
    assert "auth.session.is_deleted = false" in sql
    assert "auth.session.revoked_at IS NULL" in sql
    assert "auth.app_user.is_active = true" in sql
    assert "auth.app_user.is_deleted = false" in sql


def test_logged_out_or_revoked_session_rejected() -> None:
    """Logout / logout-all set is_active=0 → the row no longer matches → 401."""
    _assert_401(_token("system"), _db(None), "Session expired or revoked")


def test_superseded_token_after_refresh_rejected() -> None:
    """Refresh rotates ``token_hash``; the previous access token must stop working."""
    old = _token("system")
    newer = _token("system")
    _assert_401(old, _db(security.hash_token(newer)), "Session expired or revoked")


def test_token_without_sid_rejected_before_db() -> None:
    token = security.create_access_token(USER_ID, "app_user", "system", None)
    db = _db()
    _assert_401(token, db, "Invalid token")
    _assert_no_db(db)


@pytest.mark.parametrize("sid", ["", 123], ids=["empty", "not-a-string"])
def test_malformed_sid_rejected(sid: object) -> None:
    settings = get_settings()
    token = jwt.encode(
        {
            "typ": "access",
            "user_id": USER_ID,
            "user_scope": "system",
            "sid": sid,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    db = _db()
    _assert_401(token, db, "Invalid token")
    _assert_no_db(db)


def test_refresh_token_cannot_be_used_as_bearer() -> None:
    refresh = security.create_refresh_token(USER_ID, SESSION_ID)
    db = _db(security.hash_token(refresh))
    _assert_401(refresh, db, "Invalid token")
    _assert_no_db(db)


def test_expired_token_rejected_before_db() -> None:
    settings = get_settings()
    token = jwt.encode(
        {
            "typ": "access",
            "user_id": USER_ID,
            "sid": SESSION_ID,
            "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
        },
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    db = _db()
    _assert_401(token, db, "Token expired")
    _assert_no_db(db)


def test_token_for_another_session_rejected() -> None:
    """A valid token whose ``sid`` points at someone else's session finds no row."""
    token = _token("system", session_id="01HZYJZGXM0KV0K4T8Y9SESS99")
    db = _db(None)
    _assert_401(token, db, "Session expired or revoked")
    assert "01HZYJZGXM0KV0K4T8Y9SESS99" in _sql(db)


# ---------------------------------------------------------------------------
# Tenant / portal membership must still be active
# ---------------------------------------------------------------------------


def test_tenant_member_with_active_membership_ok() -> None:
    token = _token("tenant")
    db = _db(security.hash_token(token), "member")
    user = _call(token, db)
    assert (user.user_scope, user.tenant_id) == ("tenant", TENANT_ID)
    sql = _sql(db, 1)
    assert "tenant_user" in sql and TENANT_ID in sql and USER_ID in sql
    assert "is_active = true" in sql


def test_tenant_member_removed_or_deactivated_rejected() -> None:
    token = _token("tenant")
    _assert_401(token, _db(security.hash_token(token), None), "Membership inactive")


def test_portal_user_with_active_account_membership_ok() -> None:
    token = _token("tenant_account")
    db = _db(security.hash_token(token), "member")
    user = _call(token, db)
    assert (user.tenant_id, user.account_id) == (TENANT_ID, ACCOUNT_ID)
    sql = _sql(db, 1)
    assert "tenant_account_user" in sql and ACCOUNT_ID in sql


def test_portal_user_removed_from_account_rejected() -> None:
    token = _token("tenant_account")
    _assert_401(token, _db(security.hash_token(token), None), "Membership inactive")


def test_tenant_scope_without_tenant_skips_lookup() -> None:
    """No tenant in the JWT: route guards (``get_tenant_id`` etc.) already return 403."""
    token = _token("tenant", tenant_id=None)
    db = _db(security.hash_token(token))
    user = _call(token, db)
    assert user.tenant_id is None
    db.scalars.assert_not_called()


# ---------------------------------------------------------------------------
# Token type and claim values (finding #6)
# ---------------------------------------------------------------------------


def _signed(**claims: object) -> str:
    settings = get_settings()
    base: dict[str, object] = {
        "typ": "access",
        "user_id": USER_ID,
        "user_type": "app_user",
        "user_scope": "system",
        "tenant_id": None,
        "sid": SESSION_ID,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    base.update(claims)
    base = {k: v for k, v in base.items() if v is not _DROP}
    return jwt.encode(
        base, settings.jwt_secret_key.get_secret_value(), algorithm=settings.jwt_algorithm
    )


_DROP = object()


def test_well_formed_signed_token_accepted() -> None:
    """Control for the cases below: the hand-built token itself is valid."""
    token = _signed()
    user = _call(token, _db(security.hash_token(token)))
    assert user.user_scope == "system"


@pytest.mark.parametrize(
    "typ", [_DROP, "refresh", "mailbox_oauth_state", "ACCESS", ""],
    ids=["missing", "refresh", "state", "wrong-case", "empty"],
)
def test_non_access_typ_rejected_before_db(typ: object) -> None:
    token = _signed(typ=typ)
    db = _db(security.hash_token(token))
    _assert_401(token, db, "Invalid token")
    _assert_no_db(db)


@pytest.mark.parametrize(
    "scope", [_DROP, None, "", "admin", "TENANT", "superuser"],
    ids=["missing", "null", "empty", "admin", "wrong-case", "superuser"],
)
def test_unknown_user_scope_rejected_not_defaulted(scope: object) -> None:
    """Previously an unknown scope silently became ``tenant``."""
    token = _signed(user_scope=scope)
    db = _db(security.hash_token(token))
    _assert_401(token, db, "Invalid token")
    _assert_no_db(db)


@pytest.mark.parametrize(
    "user_type", [_DROP, None, "", "root", "APP_USER"],
    ids=["missing", "null", "empty", "root", "wrong-case"],
)
def test_unknown_user_type_rejected_not_defaulted(user_type: object) -> None:
    """Previously an unknown type silently became ``app_user``."""
    token = _signed(user_type=user_type)
    db = _db(security.hash_token(token))
    _assert_401(token, db, "Invalid token")
    _assert_no_db(db)


@pytest.mark.parametrize("user_type", ["app_user", "customer_user"])
@pytest.mark.parametrize("scope", ["system", "tenant", "tenant_account"])
def test_every_known_scope_and_type_accepted(scope: str, user_type: str) -> None:
    token = _signed(
        user_scope=scope,
        user_type=user_type,
        tenant_id=None if scope == "system" else TENANT_ID,
        account_id=ACCOUNT_ID if scope == "tenant_account" else _DROP,
    )
    results: list[object] = [security.hash_token(token)]
    if scope != "system":
        results.append("member")
    user = _call(token, _db(*results))
    assert (user.user_scope, user.user_type) == (scope, user_type)


# ---------------------------------------------------------------------------
# Business unit: from the session row, never from the token
# ---------------------------------------------------------------------------


def test_business_unit_comes_from_the_session_row() -> None:
    token = security.create_access_token(
        USER_ID, "app_user", "tenant", TENANT_ID,
        session_id=SESSION_ID, business_unit_id="01HZYJZGXM0KV0K4T8Y9FORGED",
    )
    db = _db(security.hash_token(token), "member")
    user = _call(token, db)
    assert user.business_unit_id == BUSINESS_UNIT_ID
    assert "auth.session.business_unit_id" in _sql(db)


def _staff(business_unit_id: str | None) -> CurrentUser:
    return CurrentUser(USER_ID, "app_user", "tenant", TENANT_ID, None, business_unit_id)


def test_get_business_unit_id_returns_the_session_unit() -> None:
    assert get_business_unit_id(_staff(BUSINESS_UNIT_ID)) == BUSINESS_UNIT_ID


def test_get_business_unit_id_without_a_unit_is_401() -> None:
    with pytest.raises(HTTPException) as exc_info:
        get_business_unit_id(_staff(None))
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail["message"] == "Store context required"
