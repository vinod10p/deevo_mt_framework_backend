"""FastAPI tests — system-scoped auth routes (mocked services, no database)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from mtf.auth.api.app_user import get_user_service
from mtf.auth.api.session import get_user_service as get_me_user_service
from mtf.auth.models.user import User
from main import app
from mtf.shared.deps import CurrentUser, get_current_user, get_permission_resolver

from tests.tenant.conftest import TEST_SYSTEM_USER_ID

_DENYLIST = frozenset(
    {
        "test_users_routes_require_bearer",
        "test_me_routes_require_bearer",
        "test_users_forbidden_for_tenant_scope",
        "test_me_tenant_account_requires_membership",
    }
)

_NOW = datetime(2026, 5, 9, 12, 0, 0)
_ROW_VER = bytes(range(8))


def _minimal_user(**kwargs: object) -> User:
    base: dict[str, object] = {
        "id": TEST_SYSTEM_USER_ID,
        "email": "admin@example.com",
        "email_normalized": "admin@example.com",
        "first_name": "Admin",
        "last_name": "User",
        "phone": None,
        "avatar_url": None,
        "password_hash": "x",
        "password_changed_at": None,
        "auth_provider": "local",
        "external_id": None,
        "email_verified_at": None,
        "last_login_at": None,
        "is_active": True,
        "is_deleted": False,
        "failed_login_count": 0,
        "locked_until": None,
        "mfa_enabled": False,
        "mfa_secret_enc": None,
        "mfa_confirmed_at": None,
        "row_version": _ROW_VER,
        "created_at": _NOW,
        "updated_at": _NOW,
        "created_by": None,
        "updated_by": None,
        "user_scope": "system",
        "deleted_by": None,
    }
    base.update(kwargs)
    return User(**base)  # type: ignore[arg-type]


def _empty_permission_resolver() -> MagicMock:
    resolver = MagicMock()
    resolver.permission_codes.return_value = frozenset()
    resolver.report_grants.return_value = {}
    return resolver


@pytest.fixture(autouse=True)
def stub_system_user_for_auth_api_tests(
    request: pytest.FixtureRequest,
) -> None:
    app.dependency_overrides[get_permission_resolver] = _empty_permission_resolver
    if request.function.__name__ in _DENYLIST:
        yield
        app.dependency_overrides.pop(get_permission_resolver, None)
        return
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id=TEST_SYSTEM_USER_ID,
        user_type="app_user",
        user_scope="system",
        tenant_id=None,
    )
    yield
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_permission_resolver, None)


def test_users_routes_require_bearer() -> None:
    client = TestClient(app)
    r = client.get("/api/auth/users")
    assert r.status_code in (401, 403)


def test_me_routes_require_bearer() -> None:
    client = TestClient(app)
    r = client.get("/api/auth/me")
    assert r.status_code in (401, 403)


def test_users_forbidden_for_tenant_scope() -> None:
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id=TEST_SYSTEM_USER_ID,
        user_type="app_user",
        user_scope="tenant",
        tenant_id="01HZYJZGXM0KV0K4T8Y9ABCDE0",
    )
    client = TestClient(app)
    r = client.get("/api/auth/users")
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "AUTH_FORBIDDEN"


def test_me_tenant_account_requires_membership() -> None:
    """Portal token without account_id in JWT is rejected at /me."""
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id=TEST_SYSTEM_USER_ID,
        user_type="app_user",
        user_scope="tenant_account",
        tenant_id="01HZYJZGXM0KV0K4T8Y9ABCDE0",
        account_id=None,
    )
    client = TestClient(app)
    r = client.get("/api/auth/me")
    assert r.status_code == 403


def test_list_users_calls_service() -> None:
    svc = MagicMock()
    svc.list_users.return_value = []
    app.dependency_overrides[get_user_service] = lambda: svc

    client = TestClient(app)
    r = client.get("/api/auth/users", params={"skip": 0, "limit": 10})
    assert r.status_code == 200
    svc.list_users.assert_called_once_with(skip=0, limit=10)


def test_patch_user_calls_service() -> None:
    user = _minimal_user()
    svc = MagicMock()
    svc.update_user.return_value = user
    app.dependency_overrides[get_user_service] = lambda: svc

    client = TestClient(app)
    r = client.patch(
        f"/api/auth/users/{TEST_SYSTEM_USER_ID}",
        json={"row_version": "AAAAAA==", "first_name": "Patched"},
    )
    assert r.status_code == 200
    svc.update_user.assert_called_once()
    call_args = svc.update_user.call_args
    assert call_args[0][0] == TEST_SYSTEM_USER_ID


def test_get_me_returns_user() -> None:
    user = _minimal_user()
    svc = MagicMock()
    svc.get_user.return_value = user
    app.dependency_overrides[get_me_user_service] = lambda: svc

    client = TestClient(app)
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == TEST_SYSTEM_USER_ID
    assert body["user_scope"] == "system"
    assert body["permissions"] == []
    assert body["reports"] == []
    svc.get_user.assert_called_once_with(TEST_SYSTEM_USER_ID)


def test_system_token_cannot_access_tenant_accounts() -> None:
    """CRM account routes require tenant scope — system gets 403."""
    client = TestClient(app)
    r = client.get("/api/tenant/accounts")
    assert r.status_code == 403
