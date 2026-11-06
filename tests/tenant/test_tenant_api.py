"""FastAPI tests — ``tenant.tenant`` routes with mocked ``TenantService`` (no database)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from main import app
from mtf.shared.deps import CurrentUser, get_current_user
from mtf.tenant.api.tenant import get_tenant_service
from mtf.tenant.schemas import TenantCreate

from tests.tenant.conftest import TEST_SYSTEM_USER_ID, TEST_TENANT_ID, minimal_tenant

_DENYLIST = frozenset({"test_tenant_routes_require_bearer"})


def test_get_tenant_by_subdomain_public_200() -> None:
    svc = MagicMock()
    row = minimal_tenant()
    svc.get_by_subdomain.return_value = row
    app.dependency_overrides[get_tenant_service] = lambda: svc

    client = TestClient(app)
    r = client.get("/api/tenant/by-subdomain", params={"subdomain": "test-tenant-org"})
    assert r.status_code == 200
    body = r.json()
    assert body["tenant_id"] == TEST_TENANT_ID
    assert body["tenant_name"] == row.name
    assert body["subdomain"] == row.subdomain
    assert body["is_active"] is True
    svc.get_by_subdomain.assert_called_once_with("test-tenant-org")


def test_get_tenant_by_subdomain_404() -> None:
    svc = MagicMock()
    svc.get_by_subdomain.return_value = None
    app.dependency_overrides[get_tenant_service] = lambda: svc

    client = TestClient(app)
    r = client.get("/api/tenant/by-subdomain", params={"subdomain": "missing"})
    assert r.status_code == 404


def test_get_tenant_by_subdomain_inactive_403() -> None:
    svc = MagicMock()
    row = minimal_tenant(is_active=False)
    svc.get_by_subdomain.return_value = row
    app.dependency_overrides[get_tenant_service] = lambda: svc

    client = TestClient(app)
    r = client.get("/api/tenant/by-subdomain", params={"subdomain": row.subdomain})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "TENANT_INACTIVE"


def test_get_tenant_by_subdomain_status_blocked_403() -> None:
    svc = MagicMock()
    row = minimal_tenant(status="suspended")
    svc.get_by_subdomain.return_value = row
    app.dependency_overrides[get_tenant_service] = lambda: svc

    client = TestClient(app)
    r = client.get("/api/tenant/by-subdomain", params={"subdomain": row.subdomain})
    assert r.status_code == 403


@pytest.fixture(autouse=True)
def stub_current_user_for_tenant_api_tests(
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


def test_tenant_routes_require_bearer() -> None:
    client = TestClient(app)
    r = client.get("/api/tenant/")
    assert r.status_code in (401, 403)


def test_list_tenants_calls_service() -> None:
    svc = MagicMock()
    svc.list_tenants.return_value = []
    app.dependency_overrides[get_tenant_service] = lambda: svc

    client = TestClient(app)
    r = client.get("/api/tenant/", params={"skip": 5, "limit": 10})
    assert r.status_code == 200
    assert r.json() == []
    svc.list_tenants.assert_called_once_with(skip=5, limit=10)


def test_get_tenant_calls_require_tenant() -> None:
    svc = MagicMock()
    row = minimal_tenant(id=TEST_TENANT_ID)
    svc.require_tenant.return_value = row
    app.dependency_overrides[get_tenant_service] = lambda: svc

    client = TestClient(app)
    r = client.get(f"/api/tenant/{TEST_TENANT_ID}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == TEST_TENANT_ID
    assert body["name"] == "Test Tenant Org"
    svc.require_tenant.assert_called_once_with(TEST_TENANT_ID)


def test_create_tenant_returns_201() -> None:
    svc = MagicMock()
    created = minimal_tenant(id=TEST_TENANT_ID, name="NewCo", subdomain="newco")
    svc.create_tenant.return_value = created
    app.dependency_overrides[get_tenant_service] = lambda: svc

    client = TestClient(app)
    payload = {"name": "NewCo", "subdomain": "newco"}
    r = client.post("/api/tenant/", json=payload)
    assert r.status_code == 201
    assert r.json()["name"] == "NewCo"
    assert r.json()["subdomain"] == "newco"
    svc.create_tenant.assert_called_once()
    args, kwargs = svc.create_tenant.call_args
    assert isinstance(args[0], TenantCreate)
    assert args[0].subdomain == "newco"
    assert kwargs["created_by"] == TEST_SYSTEM_USER_ID


def test_create_tenant_requires_subdomain() -> None:
    svc = MagicMock()
    app.dependency_overrides[get_tenant_service] = lambda: svc

    client = TestClient(app)
    r = client.post("/api/tenant/", json={"name": "NewCo"})
    assert r.status_code == 422
    svc.create_tenant.assert_not_called()


def test_update_tenant_calls_service() -> None:
    svc = MagicMock()
    updated = minimal_tenant(id=TEST_TENANT_ID, name="Renamed")
    svc.update_tenant.return_value = updated
    app.dependency_overrides[get_tenant_service] = lambda: svc

    client = TestClient(app)
    rv_b64 = "AAAAAAAAAAA="
    r = client.patch(
        f"/api/tenant/{TEST_TENANT_ID}",
        json={"row_version": rv_b64, "name": "Renamed"},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Renamed"
    svc.update_tenant.assert_called_once()
    args, kwargs = svc.update_tenant.call_args
    assert args[0] == TEST_TENANT_ID
    assert kwargs["updated_by"] == TEST_SYSTEM_USER_ID


def test_update_tenant_rejects_null_subdomain() -> None:
    svc = MagicMock()
    app.dependency_overrides[get_tenant_service] = lambda: svc

    client = TestClient(app)
    rv_b64 = "AAAAAAAAAAA="
    r = client.patch(
        f"/api/tenant/{TEST_TENANT_ID}",
        json={"row_version": rv_b64, "subdomain": None},
    )
    assert r.status_code == 422
    svc.update_tenant.assert_not_called()


def test_delete_tenant_returns_204() -> None:
    svc = MagicMock()
    svc.soft_delete_tenant.return_value = minimal_tenant()
    app.dependency_overrides[get_tenant_service] = lambda: svc

    client = TestClient(app)
    r = client.delete(f"/api/tenant/{TEST_TENANT_ID}")
    assert r.status_code == 204
    _, kwargs = svc.soft_delete_tenant.call_args
    assert kwargs["deleted_by"] == TEST_SYSTEM_USER_ID
    assert kwargs["actor"].user_id == TEST_SYSTEM_USER_ID
    assert kwargs["source"].request_id is not None
