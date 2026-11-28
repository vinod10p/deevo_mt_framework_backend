"""FastAPI tests — tenant assignment routes (mocked services, no database)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from main import app
from mtf.auth.models.permission import Permission
from mtf.auth.models.role import Role
from mtf.auth.models.user_role import UserRole
from mtf.shared.deps import CurrentUser, get_current_user, get_permission_resolver
from mtf.tenant.api.tenant_rbac import (
    get_permission_service,
    get_role_report_service,
    get_tenant_role_service,
    get_user_role_service,
    require_role_admin,
)
from tests.tenant.conftest import TEST_ROOT_BU_ID, TEST_TENANT_ID, TEST_USER_ID

_NOW = datetime(2026, 5, 9, 12, 0, 0)
_ROW_VER = bytes(range(8))
_ROLE_ID = "01JRACMTFR1TEST00000000009"
OWNER = CurrentUser(
    user_id=TEST_USER_ID,
    user_type="app_user",
    user_scope="tenant",
    tenant_id=TEST_TENANT_ID,
)


def _role() -> Role:
    return Role(
        id=_ROLE_ID,
        tenant_id=TEST_TENANT_ID,
        business_unit_id=TEST_ROOT_BU_ID,
        code="support_lead",
        name="Support Lead",
        description=None,
        user_scope="tenant",
        is_system=False,
        is_tenant_wide=False,
        is_active=True,
        is_deleted=False,
        row_version=_ROW_VER,
        created_at=_NOW,
        updated_at=_NOW,
        created_by=TEST_USER_ID,
        updated_by=TEST_USER_ID,
        deleted_at=None,
        deleted_by=None,
    )


def _stub_owner() -> None:
    resolver = MagicMock()
    resolver.has_permission.return_value = True
    app.dependency_overrides[get_current_user] = lambda: OWNER
    app.dependency_overrides[require_role_admin] = lambda: OWNER
    app.dependency_overrides[get_permission_resolver] = lambda: resolver


def _permission() -> Permission:
    return Permission(
        id="01JRACMTFPMTEST00000000009",
        code="screen.lead.view",
        resource_type="screen",
        resource_code="lead",
        action="view",
        user_scope="tenant",
        description="Lead",
        module_code="CRM",
        resource_name="Lead",
        sort_order=10,
        is_tenant_grantable=True,
        is_active=True,
        is_deleted=False,
        row_version=_ROW_VER,
        created_at=_NOW,
        updated_at=_NOW,
        created_by=TEST_USER_ID,
        updated_by=TEST_USER_ID,
        deleted_at=None,
        deleted_by=None,
    )


def test_assignment_routes_require_bearer() -> None:
    client = TestClient(app)
    assert client.get("/api/tenant/roles").status_code in (401, 403)
    assert client.get("/api/tenant/permissions").status_code in (401, 403)


def test_missing_role_admin_permission_is_403() -> None:
    resolver = MagicMock()
    resolver.has_permission.return_value = False
    app.dependency_overrides[get_current_user] = lambda: OWNER
    app.dependency_overrides[get_permission_resolver] = lambda: resolver
    client = TestClient(app)
    roles = client.get("/api/tenant/roles")
    assert roles.status_code == 403
    assert roles.json()["detail"]["code"] == "AUTH_FORBIDDEN"
    catalog = client.get("/api/tenant/permissions")
    assert catalog.status_code == 403
    assert catalog.json()["detail"]["code"] == "AUTH_FORBIDDEN"


def test_list_tenant_permissions_calls_service() -> None:
    _stub_owner()
    svc = MagicMock()
    perm = _permission()
    svc.list_tenant_grantable.return_value = [perm]
    app.dependency_overrides[get_permission_service] = lambda: svc
    client = TestClient(app)

    listed = client.get("/api/tenant/permissions")
    assert listed.status_code == 200
    body = listed.json()
    assert body[0]["code"] == "screen.lead.view"
    assert body[0]["module_code"] == "CRM"
    assert body[0]["resource_name"] == "Lead"
    assert "is_tenant_grantable" not in body[0]
    assert "row_version" not in body[0]
    svc.list_tenant_grantable.assert_called_once_with()
    assert client.post("/api/tenant/permissions", json={}).status_code == 405


def test_list_tenant_reports_calls_service() -> None:
    _stub_owner()
    svc = MagicMock()
    row = MagicMock(
        id="01JRPT0DF00000000000000001",
        report_key="crm_lead_list",
        display_name="Leads",
        description=None,
        scope_type="system",
    )
    svc.list_grantable_reports.return_value = [row]
    app.dependency_overrides[get_role_report_service] = lambda: svc
    client = TestClient(app)

    listed = client.get("/api/tenant/reports")
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body[0]["report_key"] == "crm_lead_list"
    assert body[0]["id"] == "01JRPT0DF00000000000000001"
    svc.list_grantable_reports.assert_called_once_with(TEST_TENANT_ID, skip=0, limit=200)


def test_list_and_create_tenant_role_call_service() -> None:
    _stub_owner()
    svc = MagicMock()
    role = _role()
    svc.list_roles.return_value = [role]
    svc.create.return_value = role
    app.dependency_overrides[get_tenant_role_service] = lambda: svc
    client = TestClient(app)

    listed = client.get("/api/tenant/roles")
    assert listed.status_code == 200
    assert listed.json()[0]["is_system"] is False
    svc.list_roles.assert_called_once_with(TEST_TENANT_ID, skip=0, limit=100)

    created = client.post(
        "/api/tenant/roles",
        json={"code": "support_lead", "name": "Support Lead"},
    )
    assert created.status_code == 201
    svc.create.assert_called_once()


def test_assign_user_role_calls_service() -> None:
    _stub_owner()
    svc = MagicMock()
    svc.create.return_value = UserRole(
        id="01JRACUSRROLE0000000000009",
        tenant_id=TEST_TENANT_ID,
        business_unit_id=TEST_ROOT_BU_ID,
        user_id=TEST_USER_ID,
        account_id=None,
        role_id=_ROLE_ID,
        user_scope="tenant",
        is_active=True,
        is_deleted=False,
        row_version=_ROW_VER,
        created_at=_NOW,
        updated_at=_NOW,
        created_by=TEST_USER_ID,
        updated_by=TEST_USER_ID,
        deleted_at=None,
        deleted_by=None,
    )
    app.dependency_overrides[get_user_role_service] = lambda: svc
    client = TestClient(app)
    created = client.post(
        f"/api/tenant/users/{TEST_USER_ID}/roles",
        json={"role_id": _ROLE_ID},
    )
    assert created.status_code == 201
    svc.create.assert_called_once()
