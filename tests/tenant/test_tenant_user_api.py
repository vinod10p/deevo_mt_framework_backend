"""FastAPI tests — nested tenant user routes under ``tenant.tenant``."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from main import app
from mtf.shared.deps import CurrentUser, get_current_user
from mtf.tenant.api.tenant import get_tenant_user_service
from mtf.tenant.schemas import TenantUserCreate, TenantUserUpdate

from tests.tenant.conftest import (
    TEST_SYSTEM_USER_ID,
    TEST_TENANT_ID,
    TEST_USER_ID,
    minimal_tenant_user_detail,
)

_DENYLIST = frozenset({"test_tenant_user_routes_require_bearer"})


@pytest.fixture(autouse=True)
def stub_current_user_for_tenant_user_api_tests(
    request: pytest.FixtureRequest,
    clear_app_dependency_overrides: None,
) -> None:
    if request.function.__name__ in _DENYLIST:
        yield
        return
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id=TEST_SYSTEM_USER_ID,
        user_type="app_user",
        user_scope="system",
        tenant_id=None,
    )
    yield
    app.dependency_overrides.pop(get_current_user, None)


def test_tenant_user_routes_require_bearer() -> None:
    client = TestClient(app)
    r = client.get(f"/api/tenant/{TEST_TENANT_ID}/users")
    assert r.status_code in (401, 403)


def test_openapi_registers_tenant_user_paths() -> None:
    client = TestClient(app)
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/tenant/{tenant_id}/users" in paths
    assert "/api/tenant/{tenant_id}/users/{user_id}" in paths


def test_list_tenant_users() -> None:
    svc = MagicMock()
    svc.list_details_by_tenant.return_value = [minimal_tenant_user_detail()]
    app.dependency_overrides[get_tenant_user_service] = lambda: svc

    client = TestClient(app)
    r = client.get(f"/api/tenant/{TEST_TENANT_ID}/users", params={"skip": 0, "limit": 50})
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["tenant_id"] == TEST_TENANT_ID
    assert body[0]["user_id"] == TEST_USER_ID
    svc.list_details_by_tenant.assert_called_once_with(TEST_TENANT_ID, skip=0, limit=50)


def test_create_tenant_user_creates_user_and_membership() -> None:
    svc = MagicMock()
    svc.create_for_tenant.return_value = minimal_tenant_user_detail(email="new.member@example.com")
    app.dependency_overrides[get_tenant_user_service] = lambda: svc

    client = TestClient(app)
    payload = {
        "email": "new.member@example.com",
        "password": "secret123",
        "role": "member",
        "first_name": "New",
        "last_name": "Member",
    }
    r = client.post(f"/api/tenant/{TEST_TENANT_ID}/users", json=payload)
    assert r.status_code == 201
    assert r.json()["email"] == "new.member@example.com"
    args, kwargs = svc.create_for_tenant.call_args
    assert args[0] == TEST_TENANT_ID
    assert isinstance(args[1], TenantUserCreate)
    assert args[1].role == "member"
    assert kwargs["created_by"] == TEST_SYSTEM_USER_ID


def test_update_tenant_user_updates_membership() -> None:
    svc = MagicMock()
    svc.update_for_tenant.return_value = minimal_tenant_user_detail(role="admin", is_active=False)
    app.dependency_overrides[get_tenant_user_service] = lambda: svc

    client = TestClient(app)
    rv_b64 = "AAAAAAAAAAA="
    r = client.patch(
        f"/api/tenant/{TEST_TENANT_ID}/users/{TEST_USER_ID}",
        json={"row_version": rv_b64, "role": "admin", "is_active": False},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "admin"
    assert body["is_active"] is False
    args, kwargs = svc.update_for_tenant.call_args
    assert args[0] == TEST_TENANT_ID
    assert args[1] == TEST_USER_ID
    assert isinstance(args[2], TenantUserUpdate)
    assert kwargs["updated_by"] == TEST_SYSTEM_USER_ID


def test_delete_tenant_user_soft_deletes_membership_only() -> None:
    svc = MagicMock()
    app.dependency_overrides[get_tenant_user_service] = lambda: svc

    client = TestClient(app)
    r = client.delete(f"/api/tenant/{TEST_TENANT_ID}/users/{TEST_USER_ID}")
    assert r.status_code == 204
    args, kwargs = svc.soft_delete_for_tenant.call_args
    assert args == (TEST_TENANT_ID, TEST_USER_ID)
    assert kwargs["deleted_by"] == TEST_SYSTEM_USER_ID
    assert kwargs["actor"].user_id == TEST_SYSTEM_USER_ID
    assert kwargs["source"].request_id is not None
