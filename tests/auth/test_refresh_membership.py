"""``/refresh`` re-checks tenant status and staff membership (gap in finding #4, no DB)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from mtf.auth.schemas.session import RefreshRequest
from mtf.auth.services.session_service import SessionService
from mtf.shared import security

USER_ID = "01JUSER0000000000000000001"
SESSION_ID = "01JSESS0000000000000000001"
TENANT_ID = "01HZYJZGXM0KV0K4T8Y9ABCDE0"
ACCOUNT_ID = "01HZYJZGXM0KV0K4T8Y9ABCDE1"


def _tenant(**kwargs: object) -> MagicMock:
    tenant = MagicMock(is_active=True, status="active")
    tenant.name = "Acme"
    for k, v in kwargs.items():
        setattr(tenant, k, v)
    return tenant


def _setup(
    scope: str,
    *,
    tenant: MagicMock | None,
    membership: object | None = "membership",
    session_tenant: str | None = TENANT_ID,
) -> tuple[SessionService, MagicMock, MagicMock]:
    db = MagicMock()
    db.scalars.return_value.first.return_value = tenant  # read by _usable_tenant
    session = MagicMock()
    session.id, session.user_id, session.tenant_id = SESSION_ID, USER_ID, session_tenant
    session.is_active = True
    session.refresh_expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(
        days=1
    )
    user = MagicMock(id=USER_ID, user_scope=scope, first_name="A", last_name="B")
    service = SessionService(db)
    patch.object(service, "_get_session_by_refresh_hash", return_value=session).start()
    patch.object(service, "_get_active_user_by_id", return_value=user).start()
    patch.object(service, "_get_active_tenant_membership", return_value=membership).start()
    patch.object(service, "_require_single_account_membership", return_value=ACCOUNT_ID).start()
    patch.object(service, "_account_name", return_value="Acct").start()
    patch.object(service, "_tenant_name", return_value="Acme").start()
    return service, db, session


@pytest.fixture(autouse=True)
def _stop_patches():
    yield
    patch.stopall()


def _refresh(service: SessionService):
    return service.refresh(
        RefreshRequest(refresh_token=security.create_refresh_token(USER_ID, SESSION_ID))
    )


def _assert_rejected_and_revoked(service, db, session, reason: str) -> None:
    with pytest.raises(HTTPException) as exc_info:
        _refresh(service)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail["message"] == "Invalid refresh token"
    assert session.is_active is False
    assert session.revoke_reason == reason
    assert session.revoked_at is not None
    db.commit.assert_called_once()  # the revocation is persisted, nothing else


# --- tenant staff ------------------------------------------------------------------


def test_active_staff_member_can_refresh() -> None:
    service, db, session = _setup("tenant", tenant=_tenant())
    out = _refresh(service)
    assert security.decode_access_token(out.access_token)["tenant_id"] == TENANT_ID
    assert session.is_active is True
    service._get_active_tenant_membership.assert_called_once_with(USER_ID, TENANT_ID)


def test_removed_staff_member_cannot_refresh_and_session_ends() -> None:
    service, db, session = _setup("tenant", tenant=_tenant(), membership=None)
    _assert_rejected_and_revoked(service, db, session, "membership_inactive")


@pytest.mark.parametrize(
    "tenant",
    [
        None,
        _tenant(is_active=False),
        _tenant(status="suspended"),
        _tenant(status="cancelled"),
        _tenant(status="expired"),
    ],
    ids=["missing-or-deleted", "inactive", "suspended", "cancelled", "expired"],
)
@pytest.mark.parametrize("scope", ["tenant", "tenant_account"])
def test_unusable_tenant_blocks_refresh(scope: str, tenant: MagicMock | None) -> None:
    service, db, session = _setup(scope, tenant=tenant)
    _assert_rejected_and_revoked(service, db, session, "tenant_inactive")
    service._get_active_tenant_membership.assert_not_called()


@pytest.mark.parametrize("scope", ["tenant", "tenant_account"])
def test_session_without_tenant_cannot_refresh(scope: str) -> None:
    service, db, session = _setup(scope, tenant=_tenant(), session_tenant=None)
    _assert_rejected_and_revoked(service, db, session, "tenant_inactive")


# --- portal and system ---------------------------------------------------------------


def test_portal_user_with_active_tenant_can_refresh() -> None:
    service, db, session = _setup("tenant_account", tenant=_tenant())
    out = _refresh(service)
    assert security.decode_access_token(out.access_token)["account_id"] == ACCOUNT_ID
    service._get_active_tenant_membership.assert_not_called()  # portal uses account check


def test_system_user_skips_tenant_checks() -> None:
    service, db, session = _setup("system", tenant=None, session_tenant=None)
    out = _refresh(service)
    assert security.decode_access_token(out.access_token)["user_scope"] == "system"
    service._get_active_tenant_membership.assert_not_called()
    assert session.is_active is True


# --- the helper itself ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("tenant", "usable"),
    [
        (_tenant(), True),
        (_tenant(status="trial"), True),
        (None, False),
        (_tenant(is_active=False), False),
        (_tenant(status="suspended"), False),
    ],
)
def test_usable_tenant(tenant: MagicMock | None, usable: bool) -> None:
    db = MagicMock()
    db.scalars.return_value.first.return_value = tenant
    assert (SessionService(db)._usable_tenant(TENANT_ID) is not None) is usable
