"""Live SQL Server: GET /api/tenant/permissions returns grantable tenant catalog."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from main import app
from mtf.shared.deps import CurrentUser, get_current_user
from mtf.tenant.api.tenant_rbac import require_role_admin
from tests.tenant.conftest import TEST_TENANT_ID, TEST_USER_ID

pytestmark = pytest.mark.integration

_GRID_KEYS = {
    "id",
    "code",
    "resource_type",
    "resource_code",
    "action",
    "module_code",
    "resource_name",
    "sort_order",
}


def _skip_if_disabled() -> None:
    if os.environ.get("DEEVO_SKIP_DB_TESTS", "").lower() in ("1", "true", "yes"):
        pytest.skip("DEEVO_SKIP_DB_TESTS is set")


@pytest.fixture(autouse=True)
def stub_tenant_admin(clear_app_dependency_overrides: None) -> None:
    _skip_if_disabled()
    user = CurrentUser(
        user_id=TEST_USER_ID,
        user_type="app_user",
        user_scope="tenant",
        tenant_id=TEST_TENANT_ID,
    )
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[require_role_admin] = lambda: user
    yield
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(require_role_admin, None)


def test_tenant_permission_catalog_is_grantable_only(client: TestClient) -> None:
    response = client.get("/api/tenant/permissions")
    assert response.status_code == 200, response.text
    rows = response.json()
    assert rows, "apply sql/auth_rbac_seed_tenant_catalog_v1.sql first"
    codes = [row["code"] for row in rows]
    assert "screen.lead.view" in codes
    assert "screen.account.create" in codes
    assert "menu.wf_inbox.view" in codes
    assert "api.auth.role.update" in codes
    assert "api.system.role.update" not in codes
    for row in rows:
        assert set(row) == _GRID_KEYS
        assert row["code"] != "api.system.role.update"
    by_code = {row["code"]: row for row in rows}
    assert by_code["screen.lead.view"]["module_code"] == "CRM"
    assert by_code["menu.wf_inbox.view"]["module_code"] == "WF"
    assert by_code["menu.wf_inbox.view"]["resource_type"] == "menu"
    assert by_code["api.auth.role.update"]["module_code"] == "GENERAL"
    module_order = [row["module_code"] for row in rows]
    assert module_order == sorted(module_order)
