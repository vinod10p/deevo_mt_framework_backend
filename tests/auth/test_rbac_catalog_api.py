"""FastAPI tests — system catalog routes (mocked services, no database)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from main import app
from mtf.auth.api.default_role_report import get_default_role_report_service
from mtf.auth.api.permission import get_permission_service
from mtf.auth.api.role import get_role_service
from mtf.auth.api.role_permission import get_role_permission_service
from mtf.auth.models.permission import Permission
from mtf.auth.models.role import Role
from mtf.auth.models.role_permission import RolePermission
from mtf.shared.deps import CurrentUser, get_current_user
from tests.tenant.conftest import TEST_SYSTEM_USER_ID, TEST_TENANT_ID

_NOW = datetime(2026, 5, 9, 12, 0, 0)
_ROW_VER = bytes(range(8))
_PERM_ID = "01JRACMTFPMTEST00000000001"
_ROLE_ID = "01JRACMTFR1TEST00000000001"


def _system_user() -> None:
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id=TEST_SYSTEM_USER_ID,
        user_type="app_user",
        user_scope="system",
        tenant_id=None,
    )


def _permission() -> Permission:
    return Permission(
        id=_PERM_ID,
        code="screen.step8.view",
        resource_type="screen",
        resource_code="step8",
        action="view",
        user_scope="tenant",
        description="Step 8",
        is_active=True,
        is_deleted=False,
        row_version=_ROW_VER,
        created_at=_NOW,
        updated_at=_NOW,
        created_by=TEST_SYSTEM_USER_ID,
        updated_by=TEST_SYSTEM_USER_ID,
        deleted_at=None,
        deleted_by=None,
    )


def _role() -> Role:
    return Role(
        id=_ROLE_ID,
        tenant_id=None,
        code="step8_role",
        name="Step 8 Role",
        description=None,
        user_scope="tenant",
        is_system=True,
        is_active=True,
        is_deleted=False,
        row_version=_ROW_VER,
        created_at=_NOW,
        updated_at=_NOW,
        created_by=TEST_SYSTEM_USER_ID,
        updated_by=TEST_SYSTEM_USER_ID,
        deleted_at=None,
        deleted_by=None,
    )


def test_catalog_routes_require_bearer() -> None:
    client = TestClient(app)
    assert client.get("/api/auth/permissions").status_code in (401, 403)
    assert client.get("/api/auth/roles").status_code in (401, 403)


def test_catalog_forbidden_for_tenant_scope() -> None:
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id=TEST_SYSTEM_USER_ID,
        user_type="app_user",
        user_scope="tenant",
        tenant_id=TEST_TENANT_ID,
    )
    client = TestClient(app)
    r = client.get("/api/auth/permissions")
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "AUTH_FORBIDDEN"


def test_list_and_create_permission_call_service() -> None:
    _system_user()
    svc = MagicMock()
    perm = _permission()
    svc.list_permissions.return_value = [perm]
    svc.create.return_value = perm
    app.dependency_overrides[get_permission_service] = lambda: svc
    client = TestClient(app)

    listed = client.get("/api/auth/permissions", params={"skip": 0, "limit": 10})
    assert listed.status_code == 200
    assert listed.json()[0]["code"] == "screen.step8.view"
    svc.list_permissions.assert_called_once_with(
        skip=0,
        limit=10,
        user_scope=None,
        resource_type=None,
    )

    created = client.post(
        "/api/auth/permissions",
        json={
            "resource_type": "screen",
            "resource_code": "step8",
            "action": "view",
            "user_scope": "tenant",
        },
    )
    assert created.status_code == 201
    svc.create.assert_called_once()


def test_list_and_create_role_call_service() -> None:
    _system_user()
    svc = MagicMock()
    role = _role()
    svc.list_roles.return_value = [role]
    svc.create.return_value = role
    app.dependency_overrides[get_role_service] = lambda: svc
    client = TestClient(app)

    listed = client.get("/api/auth/roles")
    assert listed.status_code == 200
    assert listed.json()[0]["is_system"] is True
    assert listed.json()[0]["tenant_id"] is None

    created = client.post(
        "/api/auth/roles",
        json={"code": "step8_role", "name": "Step 8 Role", "user_scope": "tenant"},
    )
    assert created.status_code == 201
    svc.create.assert_called_once()


def test_role_permission_and_default_report_routes_call_service() -> None:
    _system_user()
    grant_svc = MagicMock()
    default_svc = MagicMock()
    grant = RolePermission(
        id="01JRACMTFGPTEST00000000001",
        role_id=_ROLE_ID,
        permission_id=_PERM_ID,
        user_scope="tenant",
        is_active=True,
        is_deleted=False,
        row_version=_ROW_VER,
        created_at=_NOW,
        updated_at=_NOW,
        created_by=TEST_SYSTEM_USER_ID,
        updated_by=TEST_SYSTEM_USER_ID,
        deleted_at=None,
        deleted_by=None,
    )
    grant_svc.create.return_value = grant
    grant_svc.list_for_role.return_value = [grant]
    app.dependency_overrides[get_role_permission_service] = lambda: grant_svc
    app.dependency_overrides[get_default_role_report_service] = lambda: default_svc
    client = TestClient(app)

    listed = client.get(f"/api/auth/roles/{_ROLE_ID}/permissions")
    assert listed.status_code == 200
    grant_svc.list_for_role.assert_called_once()

    created = client.post(
        f"/api/auth/roles/{_ROLE_ID}/permissions",
        json={"permission_id": _PERM_ID},
    )
    assert created.status_code == 201
    grant_svc.create.assert_called_once()

    deleted = client.delete(f"/api/auth/roles/{_ROLE_ID}/permissions/{_PERM_ID}")
    assert deleted.status_code == 204
    grant_svc.soft_delete.assert_called_once()
