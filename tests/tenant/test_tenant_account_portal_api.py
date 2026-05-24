"""FastAPI tests — account portal users (``/api/account/users``, mocked services)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from main import app
from mtf.auth.models.tenant_account_user import TenantAccountUser
from mtf.shared.deps import CurrentUser, get_current_user
from mtf.tenant.api.tenant_account_portal import (
    get_tenant_account_user_service,
    require_account_admin,
)

from tests.tenant.conftest import (
    TEST_ACCOUNT_ID,
    TEST_TENANT_ID,
    TEST_USER_ID,
    _NOW,
    _ROW_VER,
    minimal_tenant_account_user_detail,
)

OTHER_USER_ID = "01HZYJZGXM0KV0K4T8Y9ABCDE7"

_STUB_DENYLIST = frozenset({"test_portal_routes_require_bearer"})


def _active_membership(*, role: str = "member", user_id: str = TEST_USER_ID) -> TenantAccountUser:
    return TenantAccountUser(
        id="01HZYJZGXM0KV0K4T8Y9ABCDE8",
        tenant_id=TEST_TENANT_ID,
        account_id=TEST_ACCOUNT_ID,
        user_id=user_id,
        role=role,
        is_active=True,
        is_deleted=False,
        joined_at=_NOW,
        row_version=_ROW_VER,
        created_at=_NOW,
        updated_at=_NOW,
    )


@pytest.fixture(autouse=True)
def stub_portal_current_user(
    request: pytest.FixtureRequest,
    clear_app_dependency_overrides: None,
) -> None:
    if request.function.__name__ in _STUB_DENYLIST:
        yield
        return
    portal_user = CurrentUser(
        user_id=TEST_USER_ID,
        user_type="app_user",
        user_scope="tenant_account",
        tenant_id=TEST_TENANT_ID,
        account_id=TEST_ACCOUNT_ID,
    )
    app.dependency_overrides[get_current_user] = lambda: portal_user
    app.dependency_overrides[require_account_admin] = lambda: portal_user
    yield
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(require_account_admin, None)


def test_portal_routes_require_bearer() -> None:
    client = TestClient(app)
    r = client.get("/api/account/users")
    assert r.status_code in (401, 403)


def test_openapi_registers_portal_paths() -> None:
    client = TestClient(app)
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/account/users" in paths
    assert "/api/account/users/{user_id}" in paths


def test_list_account_portal_users() -> None:
    user_svc = MagicMock()
    user_svc.get_membership.return_value = _active_membership()
    user_svc.list_details_by_account.return_value = [minimal_tenant_account_user_detail()]
    app.dependency_overrides[get_tenant_account_user_service] = lambda: user_svc

    client = TestClient(app)
    r = client.get("/api/account/users", params={"skip": 0, "limit": 50})
    assert r.status_code == 200
    assert len(r.json()) == 1
    user_svc.list_details_by_account.assert_called_once_with(
        TEST_TENANT_ID,
        TEST_ACCOUNT_ID,
        skip=0,
        limit=50,
    )


def test_get_account_portal_user() -> None:
    user_svc = MagicMock()
    user_svc.get_membership.return_value = _active_membership()
    user_svc.get_detail_for_account.return_value = minimal_tenant_account_user_detail()
    app.dependency_overrides[get_tenant_account_user_service] = lambda: user_svc

    client = TestClient(app)
    r = client.get(f"/api/account/users/{TEST_USER_ID}")
    assert r.status_code == 200
    assert r.json()["user_id"] == TEST_USER_ID
    user_svc.get_detail_for_account.assert_called_once_with(
        TEST_TENANT_ID,
        TEST_ACCOUNT_ID,
        TEST_USER_ID,
    )


def test_create_account_portal_user_admin() -> None:
    admin = CurrentUser(
        user_id=TEST_USER_ID,
        user_type="app_user",
        user_scope="tenant_account",
        tenant_id=TEST_TENANT_ID,
        account_id=TEST_ACCOUNT_ID,
    )
    app.dependency_overrides[get_current_user] = lambda: admin
    app.dependency_overrides[require_account_admin] = lambda: admin

    user_svc = MagicMock()
    user_svc.create_for_account.return_value = minimal_tenant_account_user_detail(role="member")
    app.dependency_overrides[get_tenant_account_user_service] = lambda: user_svc

    client = TestClient(app)
    r = client.post(
        "/api/account/users",
        json={
            "email": "newportal@example.com",
            "password": "password123",
            "role": "member",
        },
    )
    assert r.status_code == 201
    user_svc.create_for_account.assert_called_once()
    args, kwargs = user_svc.create_for_account.call_args
    assert args[0] == TEST_TENANT_ID
    assert args[1] == TEST_ACCOUNT_ID
    assert kwargs.get("created_by") == TEST_USER_ID


def test_patch_self_as_member() -> None:
    user_svc = MagicMock()
    user_svc.get_membership.return_value = _active_membership(role="member")
    user_svc.update_for_account.return_value = minimal_tenant_account_user_detail(first_name="Updated")
    app.dependency_overrides[get_tenant_account_user_service] = lambda: user_svc

    client = TestClient(app)
    r = client.patch(
        f"/api/account/users/{TEST_USER_ID}",
        json={"row_version": "AAAAAAAAAAA=", "first_name": "Updated"},
    )
    assert r.status_code == 200
    assert r.json()["first_name"] == "Updated"
    user_svc.update_for_account.assert_called_once()
    _, kwargs = user_svc.update_for_account.call_args
    assert kwargs.get("actor_membership") is not None


def test_patch_other_user_forbidden_for_member() -> None:
    user_svc = MagicMock()
    user_svc.get_membership.return_value = _active_membership(role="member")
    app.dependency_overrides[get_tenant_account_user_service] = lambda: user_svc

    client = TestClient(app)
    r = client.patch(
        f"/api/account/users/{OTHER_USER_ID}",
        json={"row_version": "AAAAAAAAAAA=", "first_name": "Nope"},
    )
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "AUTH_FORBIDDEN"
    user_svc.update_for_account.assert_not_called()


def test_delete_account_portal_user_admin() -> None:
    admin = CurrentUser(
        user_id=TEST_USER_ID,
        user_type="app_user",
        user_scope="tenant_account",
        tenant_id=TEST_TENANT_ID,
        account_id=TEST_ACCOUNT_ID,
    )
    app.dependency_overrides[get_current_user] = lambda: admin
    app.dependency_overrides[require_account_admin] = lambda: admin

    user_svc = MagicMock()
    app.dependency_overrides[get_tenant_account_user_service] = lambda: user_svc

    client = TestClient(app)
    r = client.delete(f"/api/account/users/{OTHER_USER_ID}")
    assert r.status_code == 204
    user_svc.soft_delete_for_account.assert_called_once_with(
        TEST_TENANT_ID,
        TEST_ACCOUNT_ID,
        OTHER_USER_ID,
        deleted_by=TEST_USER_ID,
    )
