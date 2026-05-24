"""FastAPI tests — tenant-scoped staff routes (``/api/tenant/me``, ``/api/tenant/users``)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from main import app
from mtf.shared.deps import CurrentUser, get_current_user
from mtf.tenant.api.tenant_staff import (
    get_tenant_service,
    get_tenant_user_service,
    require_owner_or_admin,
)
from mtf.tenant.schemas import TenantUserCreate

from tests.tenant.conftest import (
    TEST_TENANT_ID,
    TEST_USER_ID,
    minimal_tenant,
    minimal_tenant_user_detail,
)

_DENYLIST = frozenset({"test_tenant_staff_routes_require_bearer"})


@pytest.fixture(autouse=True)
def stub_tenant_user_for_staff_api(
    request: pytest.FixtureRequest,
    clear_app_dependency_overrides: None,
) -> None:
    if request.function.__name__ in _DENYLIST:
        yield
        return
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id=TEST_USER_ID,
        user_type="app_user",
        user_scope="tenant",
        tenant_id=TEST_TENANT_ID,
    )
    yield
    app.dependency_overrides.pop(get_current_user, None)


def test_tenant_staff_routes_require_bearer() -> None:
    client = TestClient(app)
    r = client.get("/api/tenant/me")
    assert r.status_code in (401, 403)


def test_get_tenant_me() -> None:
    svc = MagicMock()
    svc.require_tenant.return_value = minimal_tenant()
    app.dependency_overrides[get_tenant_service] = lambda: svc

    client = TestClient(app)
    r = client.get("/api/tenant/me")
    assert r.status_code == 200
    assert r.json()["id"] == TEST_TENANT_ID


def test_list_tenant_staff() -> None:
    svc = MagicMock()
    svc.list_details_by_tenant.return_value = [minimal_tenant_user_detail()]
    app.dependency_overrides[get_tenant_user_service] = lambda: svc

    client = TestClient(app)
    r = client.get("/api/tenant/users")
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_member_cannot_create_staff() -> None:
    from mtf.shared.exceptions import forbidden

    def deny_owner_admin() -> CurrentUser:
        forbidden("AUTH", "Insufficient permissions")
        raise AssertionError("unreachable")

    app.dependency_overrides[require_owner_or_admin] = deny_owner_admin
    app.dependency_overrides[get_tenant_user_service] = lambda: MagicMock()

    client = TestClient(app)
    r = client.post(
        "/api/tenant/users",
        json={
            "email": "x@example.com",
            "password": "password123",
            "role": "member",
        },
    )
    assert r.status_code == 403


def test_get_tenant_staff_by_user_id() -> None:
    detail = minimal_tenant_user_detail()
    svc = MagicMock()
    svc.get_detail_for_tenant.return_value = detail
    app.dependency_overrides[get_tenant_user_service] = lambda: svc

    client = TestClient(app)
    r = client.get(f"/api/tenant/users/{TEST_USER_ID}")
    assert r.status_code == 200
    assert r.json()["user_id"] == TEST_USER_ID
    svc.get_detail_for_tenant.assert_called_once_with(TEST_TENANT_ID, TEST_USER_ID)


def test_owner_can_update_other_staff() -> None:
    owner = CurrentUser(
        user_id="01OWNER000000000000000000",
        user_type="app_user",
        user_scope="tenant",
        tenant_id=TEST_TENANT_ID,
    )
    app.dependency_overrides[get_current_user] = lambda: owner
    svc = MagicMock(spec=["get_membership", "assert_can_manage_users", "update_for_tenant"])
    svc.get_membership.return_value = MagicMock(role="owner")
    svc.update_for_tenant.return_value = minimal_tenant_user_detail(role="admin")
    app.dependency_overrides[get_tenant_user_service] = lambda: svc

    client = TestClient(app)
    r = client.patch(
        "/api/tenant/users/01OTHER00000000000000000",
        json={"row_version": "AAAAAAAAAAA=", "role": "admin"},
    )
    assert r.status_code == 200
    svc.assert_can_manage_users.assert_called_once()
    svc.update_for_tenant.assert_called_once()


def test_owner_can_create_staff() -> None:
    owner = CurrentUser(
        user_id="01OWNER000000000000000000",
        user_type="app_user",
        user_scope="tenant",
        tenant_id=TEST_TENANT_ID,
    )
    app.dependency_overrides[get_current_user] = lambda: owner
    svc = MagicMock(spec=["assert_can_manage_users", "create_for_tenant"])
    svc.assert_can_manage_users.return_value = MagicMock(role="owner")
    svc.create_for_tenant.return_value = minimal_tenant_user_detail()
    app.dependency_overrides[get_tenant_user_service] = lambda: svc

    app.dependency_overrides[require_owner_or_admin] = lambda: owner

    client = TestClient(app)
    payload = TenantUserCreate(
        email="new@example.com",
        password="password123",
        role="member",
    )
    r = client.post("/api/tenant/users", json=payload.model_dump())
    assert r.status_code == 201
    svc.create_for_tenant.assert_called_once()
