"""Store switch — service rules and route scope (no database)."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from main import app
from mtf.auth.api.session import get_session_service
from mtf.auth.services.session_service import SessionService
from mtf.shared.deps import CurrentUser, get_current_user
from mtf.tenant.models.business_unit import BU_TYPE_STORE, BusinessUnit
from mtf.tenant.services.business_unit_service import StoreAccessError

TENANT_ID = "01HZYJZGXM0KV0K4T8Y9ABCDE0"
USER_ID = "01HZYJZGXM0KV0K4T8Y9USER01"
MAIN_ID = "01HZYJZGXM0KV0K4T8Y9MAIN01"
MAYFAIR = BusinessUnit(
    id="01HZYJZGXM0KV0K4T8Y9MAYFR1", tenant_id=TENANT_ID, bu_type=BU_TYPE_STORE,
    code="MAYFAIR", name="Mayfair",
)
STAFF = CurrentUser(USER_ID, "app_user", "tenant", TENANT_ID, None, MAIN_ID)


@pytest.fixture
def service() -> Iterator[SessionService]:
    service = SessionService(MagicMock())
    session = MagicMock(id="sess", user_id=USER_ID, tenant_id=TENANT_ID,
                        business_unit_id=MAIN_ID, token_hash=b"old")
    app_user = MagicMock(id=USER_ID, user_scope="tenant", first_name="A", last_name="B")
    patch.object(service, "_get_session_by_access_hash", return_value=session).start()
    patch.object(service, "_get_active_user_by_id", return_value=app_user).start()
    patch.object(service, "_tenant_name", return_value="Acme").start()
    patch.object(service, "_units").start().is_multi_store.return_value = True
    yield service
    patch.stopall()


def _session(service: SessionService) -> MagicMock:
    return service._get_session_by_access_hash.return_value  # type: ignore[attr-defined]


def test_allowed_switch_moves_the_session_and_rotates_its_tokens(service) -> None:
    service._units.resolve_login_unit.return_value = MAYFAIR
    with patch("mtf.auth.services.session_service.append_audit_log") as audit:
        tokens = service.switch_business_unit("raw", STAFF, "mayfair")

    session = _session(service)
    assert session.business_unit_id == MAYFAIR.id
    assert session.token_hash != b"old"
    assert (tokens.business_unit_code, tokens.multi_store) == ("MAYFAIR", True)
    service._units.resolve_login_unit.assert_called_once_with(TENANT_ID, USER_ID, "mayfair")
    logged = audit.call_args.kwargs
    assert logged["action"] == "update"
    assert logged["old_values"] == {"business_unit_id": MAIN_ID}
    assert logged["new_values"] == {"event": "business_unit_switch", "business_unit_id": MAYFAIR.id}
    service._db.commit.assert_called_once()


def test_denied_switch_leaves_the_session_alone(service) -> None:
    service._units.resolve_login_unit.side_effect = StoreAccessError("store_denied")
    with pytest.raises(HTTPException) as raised:
        service.switch_business_unit("raw", STAFF, "MAYFAIR")
    assert raised.value.status_code == 401
    assert raised.value.detail["message"] == "You don't have access to this store"
    session = _session(service)
    assert (session.business_unit_id, session.token_hash) == (MAIN_ID, b"old")
    service._db.commit.assert_not_called()


@pytest.mark.parametrize(
    "user",
    [
        CurrentUser(USER_ID, "app_user", "tenant_account", TENANT_ID, "acct", "root"),
        CurrentUser(USER_ID, "app_user", "system", None),
    ],
    ids=["portal", "system"],
)
def test_only_staff_may_switch(user: CurrentUser) -> None:
    sessions = MagicMock()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session_service] = lambda: sessions
    try:
        r = TestClient(app).post(
            "/api/auth/session/business-unit",
            json={"business_unit_code": "MAIN"},
            headers={"Authorization": "Bearer token"},
        )
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "AUTH_FORBIDDEN"
    sessions.switch_business_unit.assert_not_called()
