"""FastAPI tests — tenant accounts, addresses, and account users (mocked services)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from main import app
from mtf.shared.deps import CurrentUser, get_current_user
from mtf.tenant.api.tenant_account import (
    get_tenant_account_address_service,
    get_tenant_account_service,
    get_tenant_account_user_service,
)
from mtf.tenant.api.tenant_staff import require_owner_or_admin

from tests.tenant.conftest import (
    TEST_ACCOUNT_ID,
    TEST_ADDRESS_ID,
    TEST_TENANT_ID,
    TEST_USER_ID,
    minimal_tenant_account,
    minimal_tenant_account_address,
    minimal_tenant_account_user_detail,
)

_STUB_DENYLIST = frozenset({"test_account_routes_require_bearer"})


@pytest.fixture(autouse=True)
def stub_current_user_for_account_api_tests(
    request: pytest.FixtureRequest,
    clear_app_dependency_overrides: None,
) -> None:
    if request.function.__name__ in _STUB_DENYLIST:
        yield
        return
    owner = CurrentUser(
        user_id=TEST_USER_ID,
        user_type="app_user",
        user_scope="tenant",
        tenant_id=TEST_TENANT_ID,
    )
    app.dependency_overrides[get_current_user] = lambda: owner
    app.dependency_overrides[require_owner_or_admin] = lambda: owner
    yield
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(require_owner_or_admin, None)


def test_account_routes_require_bearer() -> None:
    client = TestClient(app)
    r = client.get("/api/tenant/accounts")
    assert r.status_code in (401, 403)


def test_openapi_registers_account_paths() -> None:
    client = TestClient(app)
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/tenant/accounts" in paths
    assert "/api/tenant/accounts/{account_id}" in paths
    assert "/api/tenant/accounts/{account_id}/addresses" in paths
    assert "/api/tenant/accounts/{account_id}/users" in paths


def test_create_account_201() -> None:
    svc = MagicMock()
    svc.create.return_value = minimal_tenant_account(account_code="NEW1", name="Neo Ltd")
    app.dependency_overrides[get_tenant_account_service] = lambda: svc

    client = TestClient(app)
    r = client.post(
        "/api/tenant/accounts",
        json={
            "account_code": "NEW1",
            "account_type": "customer",
            "name": "Neo Ltd",
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["account_code"] == "NEW1"
    assert body["tenant_id"] == TEST_TENANT_ID
    svc.create.assert_called_once()
    args, kwargs = svc.create.call_args
    assert args[1] == TEST_TENANT_ID
    assert kwargs.get("created_by") == TEST_USER_ID


def test_list_accounts_returns_page() -> None:
    svc = MagicMock()
    row = minimal_tenant_account()
    svc.list_accounts.return_value = {
        "items": [row],
        "total": 1,
        "skip": 0,
        "limit": 50,
    }
    app.dependency_overrides[get_tenant_account_service] = lambda: svc

    client = TestClient(app)
    r = client.get("/api/tenant/accounts", params={"skip": 0, "limit": 50})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == TEST_ACCOUNT_ID


def test_get_patch_delete_account() -> None:
    svc = MagicMock()
    svc.get_by_id.return_value = minimal_tenant_account()
    svc.update.return_value = minimal_tenant_account(name="Updated")
    svc.soft_delete.return_value = minimal_tenant_account()
    app.dependency_overrides[get_tenant_account_service] = lambda: svc

    client = TestClient(app)
    base = f"/api/tenant/accounts/{TEST_ACCOUNT_ID}"

    assert client.get(base).status_code == 200

    pr = client.patch(base, json={"row_version": "AAAAAAAAAAA=", "name": "Updated"})
    assert pr.status_code == 200
    assert pr.json()["name"] == "Updated"

    dr = client.delete(base)
    assert dr.status_code == 204
    svc.soft_delete.assert_called_once_with(
        TEST_ACCOUNT_ID,
        TEST_TENANT_ID,
        deleted_by=TEST_USER_ID,
    )


def test_account_user_routes() -> None:
    user_svc = MagicMock()
    user_svc.assert_can_manage_account_users = MagicMock()
    user_svc.list_details_by_account.return_value = [minimal_tenant_account_user_detail()]
    user_svc.get_detail_for_account.return_value = minimal_tenant_account_user_detail()
    user_svc.create_for_account.return_value = minimal_tenant_account_user_detail()
    user_svc.update_for_account.return_value = minimal_tenant_account_user_detail()
    app.dependency_overrides[get_tenant_account_user_service] = lambda: user_svc

    client = TestClient(app)
    base = f"/api/tenant/accounts/{TEST_ACCOUNT_ID}/users"

    assert client.get(base).status_code == 200
    assert len(client.get(base).json()) == 1

    assert client.get(f"{base}/{TEST_USER_ID}").status_code == 200

    cr = client.post(
        base,
        json={
            "email": "portal@example.com",
            "password": "password123",
            "role": "member",
        },
    )
    assert cr.status_code == 201
    user_svc.assert_can_manage_account_users.assert_called_once()

    pr = client.patch(
        f"{base}/{TEST_USER_ID}",
        json={"row_version": "AAAAAAAAAAA=", "first_name": "New"},
    )
    assert pr.status_code == 200

    dr = client.delete(f"{base}/{TEST_USER_ID}")
    assert dr.status_code == 204


def test_create_address_201() -> None:
    addr_svc = MagicMock()
    addr_svc.create.return_value = minimal_tenant_account_address()
    app.dependency_overrides[get_tenant_account_address_service] = lambda: addr_svc

    client = TestClient(app)
    r = client.post(
        f"/api/tenant/accounts/{TEST_ACCOUNT_ID}/addresses",
        json={
            "address_type": "billing",
            "address_line1": "100 Ship Rd",
            "is_default": False,
        },
    )
    assert r.status_code == 201
    addr_svc.create.assert_called_once()


def test_list_get_patch_delete_address() -> None:
    addr_svc = MagicMock()
    addr_svc.list_addresses.return_value = [minimal_tenant_account_address()]
    addr_svc.get_by_id.return_value = minimal_tenant_account_address()
    addr_svc.update.return_value = minimal_tenant_account_address(address_line1="Changed")
    addr_svc.soft_delete.return_value = minimal_tenant_account_address()
    app.dependency_overrides[get_tenant_account_address_service] = lambda: addr_svc

    client = TestClient(app)
    url = f"/api/tenant/accounts/{TEST_ACCOUNT_ID}/addresses/{TEST_ADDRESS_ID}"

    assert client.get(f"/api/tenant/accounts/{TEST_ACCOUNT_ID}/addresses").status_code == 200
    assert client.get(url).status_code == 200
    assert client.patch(url, json={"row_version": "AAAAAAAAAAA=", "address_line1": "Changed"}).status_code == 200
    assert client.delete(url).status_code == 204
