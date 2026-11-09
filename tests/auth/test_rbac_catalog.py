"""Unit tests — system catalog CRUD (permissions, platform roles, grants)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from mtf.audit.models import AuditLog
from mtf.audit.service import AuditSource
from mtf.auth.models.default_role_report import DefaultRoleReport
from mtf.auth.models.permission import Permission
from mtf.auth.models.role import Role
from mtf.auth.models.role_permission import RolePermission
from mtf.auth.schemas.default_role_report import (
    DefaultRoleReportCreate,
    DefaultRoleReportUpdate,
)
from mtf.auth.schemas.permission import PermissionCreate, PermissionUpdate
from mtf.auth.schemas.role import RoleCreate, RoleUpdate
from mtf.auth.schemas.role_permission import RolePermissionCreate
from mtf.auth.services.default_role_report import DefaultRoleReportService
from mtf.auth.services.permission import PermissionService
from mtf.auth.services.rbac_catalog import compose_permission_code
from mtf.auth.services.role import RoleService
from mtf.auth.services.role_permission import RolePermissionService
from mtf.rpt.models.report_definition import ReportDefinition
from mtf.shared.deps import CurrentUser
from tests.tenant.conftest import TEST_TENANT_ID, TEST_USER_ID

_NOW = datetime(2026, 5, 9, 12, 0, 0)
_ROW_VER = bytes(range(8))
_PERM_ID = "01JRACMTFPMTEST00000000001"
_ROLE_ID = "01JRACMTFR1TEST00000000001"
_REPORT_ID = "01JRACMTFREPORT00000000001"
ACTOR = CurrentUser(
    user_id=TEST_USER_ID,
    user_type="app_user",
    user_scope="system",
    tenant_id=None,
)
SOURCE = AuditSource(request_id="01JREQ00000000000000000001")


def _first(value: object) -> MagicMock:
    result = MagicMock()
    result.first.return_value = value
    result.all.return_value = [] if value is None else [value]
    return result


def _added(db: MagicMock, model: type) -> list:
    return [call.args[0] for call in db.add.call_args_list if isinstance(call.args[0], model)]


def _permission(**overrides: object) -> Permission:
    values: dict[str, object] = {
        "id": _PERM_ID,
        "code": "screen.step8.view",
        "resource_type": "screen",
        "resource_code": "step8",
        "action": "view",
        "user_scope": "tenant",
        "description": "Step 8",
        "is_active": True,
        "is_deleted": False,
        "row_version": _ROW_VER,
        "created_at": _NOW,
        "updated_at": _NOW,
        "created_by": TEST_USER_ID,
        "updated_by": TEST_USER_ID,
        "deleted_at": None,
        "deleted_by": None,
    }
    values.update(overrides)
    return Permission(**values)  # type: ignore[arg-type]


def _role(**overrides: object) -> Role:
    values: dict[str, object] = {
        "id": _ROLE_ID,
        "tenant_id": None,
        "code": "step8_role",
        "name": "Step 8 Role",
        "description": None,
        "user_scope": "tenant",
        "is_system": True,
        "is_active": True,
        "is_deleted": False,
        "row_version": _ROW_VER,
        "created_at": _NOW,
        "updated_at": _NOW,
        "created_by": TEST_USER_ID,
        "updated_by": TEST_USER_ID,
        "deleted_at": None,
        "deleted_by": None,
    }
    values.update(overrides)
    return Role(**values)  # type: ignore[arg-type]


def _report(**overrides: object) -> ReportDefinition:
    values: dict[str, object] = {
        "id": _REPORT_ID,
        "tenant_id": None,
        "scope_type": "system",
        "report_key": "tenant_account_list",
        "display_name": "Accounts",
        "proc_name": "rpt.tenant_account_list",
        "is_active": True,
        "is_deleted": False,
    }
    values.update(overrides)
    return ReportDefinition(**values)  # type: ignore[arg-type]


def test_compose_permission_code_keeps_dots_in_resource_code() -> None:
    assert compose_permission_code("api", "auth.role", "update") == "api.auth.role.update"
    assert compose_permission_code("screen", "lead", "view") == "screen.lead.view"


def test_create_permission_composes_code_and_audits() -> None:
    db = MagicMock()
    db.scalars.return_value = _first(None)
    svc = PermissionService(db)
    row = svc.create(
        PermissionCreate(
            resource_type="screen",
            resource_code="step8",
            action="view",
            user_scope="tenant",
            description="Step 8",
        ),
        created_by=TEST_USER_ID,
        actor=ACTOR,
        source=SOURCE,
    )
    assert row.code == "screen.step8.view"
    [perm] = _added(db, Permission)
    assert perm.code == "screen.step8.view"
    assert perm.resource_type == "screen"
    [log] = _added(db, AuditLog)
    assert (log.action, log.schema_name, log.table_name) == ("insert", "auth", "permission")
    db.commit.assert_called_once()


def test_duplicate_permission_code_is_409() -> None:
    db = MagicMock()
    db.scalars.return_value = _first(_permission())
    svc = PermissionService(db)
    with pytest.raises(HTTPException) as exc_info:
        svc.create(
            PermissionCreate(
                resource_type="screen",
                resource_code="step8",
                action="view",
                user_scope="tenant",
            ),
            created_by=TEST_USER_ID,
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "AUTH_PERMISSION_CONFLICT"


def test_update_permission_does_not_change_code() -> None:
    db = MagicMock()
    existing = _permission()
    db.scalars.return_value = _first(existing)
    svc = PermissionService(db)
    updated = svc.update(
        existing.id,
        PermissionUpdate(row_version=_ROW_VER, description="Renamed", is_active=False),
        updated_by=TEST_USER_ID,
        actor=ACTOR,
        source=SOURCE,
    )
    assert updated.code == "screen.step8.view"
    assert updated.description == "Renamed"
    assert updated.is_active is False
    [log] = _added(db, AuditLog)
    assert log.action == "update"


def test_soft_delete_permission_sets_deleted_at() -> None:
    db = MagicMock()
    existing = _permission()
    db.scalars.return_value = _first(existing)
    svc = PermissionService(db)
    deleted = svc.soft_delete(existing.id, deleted_by=TEST_USER_ID, actor=ACTOR, source=SOURCE)
    assert deleted.is_deleted is True
    assert deleted.deleted_by == TEST_USER_ID
    assert deleted.deleted_at is not None
    [log] = _added(db, AuditLog)
    assert log.action == "delete"


def test_create_platform_role_forces_system_flag() -> None:
    db = MagicMock()
    db.scalars.return_value = _first(None)
    svc = RoleService(db)
    row = svc.create(
        RoleCreate(code="step8_role", name="Step 8", user_scope="tenant"),
        created_by=TEST_USER_ID,
        actor=ACTOR,
        source=SOURCE,
    )
    assert row.tenant_id is None
    assert row.is_system is True
    [role] = _added(db, Role)
    assert role.tenant_id is None
    assert role.is_system is True
    [log] = _added(db, AuditLog)
    assert (log.action, log.table_name) == ("insert", "role")


def test_duplicate_platform_role_code_is_409() -> None:
    db = MagicMock()
    db.scalars.return_value = _first(_role())
    svc = RoleService(db)
    with pytest.raises(HTTPException) as exc_info:
        svc.create(
            RoleCreate(code="step8_role", name="Step 8", user_scope="tenant"),
            created_by=TEST_USER_ID,
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "AUTH_ROLE_CONFLICT"


def test_get_tenant_owned_role_is_404() -> None:
    db = MagicMock()
    db.scalars.return_value = _first(None)
    svc = RoleService(db)
    with pytest.raises(HTTPException) as exc_info:
        svc.get("01TENANTROLE00000000000001")
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["code"] == "AUTH_ROLE_NOT_FOUND"


def test_update_role_name_audits() -> None:
    db = MagicMock()
    existing = _role()
    db.scalars.return_value = _first(existing)
    svc = RoleService(db)
    updated = svc.update(
        existing.id,
        RoleUpdate(row_version=_ROW_VER, name="Renamed"),
        updated_by=TEST_USER_ID,
        actor=ACTOR,
        source=SOURCE,
    )
    assert updated.name == "Renamed"
    [log] = _added(db, AuditLog)
    assert log.action == "update"


def test_grant_permission_copies_role_scope() -> None:
    db = MagicMock()
    role = _role()
    permission = _permission()
    db.scalars.side_effect = [_first(role), _first(permission), _first(None)]
    svc = RolePermissionService(db)
    row = svc.create(
        role.id,
        RolePermissionCreate(permission_id=permission.id),
        created_by=TEST_USER_ID,
        actor=ACTOR,
        source=SOURCE,
    )
    assert row.user_scope == "tenant"
    assert row.role_id == role.id
    assert row.permission_id == permission.id
    [log] = _added(db, AuditLog)
    assert (log.action, log.table_name) == ("insert", "role_permission")


def test_grant_rejects_scope_mismatch() -> None:
    db = MagicMock()
    role = _role(user_scope="tenant")
    permission = _permission(user_scope="system", code="api.system.role.update")
    db.scalars.side_effect = [_first(role), _first(permission)]
    svc = RolePermissionService(db)
    with pytest.raises(HTTPException) as exc_info:
        svc.create(role.id, RolePermissionCreate(permission_id=permission.id))
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["code"] == "AUTH_ROLE_PERMISSION_BAD_REQUEST"


def test_duplicate_grant_is_409() -> None:
    db = MagicMock()
    role = _role()
    permission = _permission()
    existing = RolePermission(
        id="01JRACMTFGPTEST00000000001",
        role_id=role.id,
        permission_id=permission.id,
        user_scope="tenant",
        is_active=True,
        is_deleted=False,
    )
    db.scalars.side_effect = [_first(role), _first(permission), _first(existing)]
    svc = RolePermissionService(db)
    with pytest.raises(HTTPException) as exc_info:
        svc.create(role.id, RolePermissionCreate(permission_id=permission.id))
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "AUTH_ROLE_PERMISSION_CONFLICT"


def test_create_default_report_rejects_tenant_report() -> None:
    db = MagicMock()
    role = _role()
    report = _report(scope_type="tenant", tenant_id=TEST_TENANT_ID)
    db.scalars.side_effect = [_first(role), _first(report)]
    svc = DefaultRoleReportService(db)
    with pytest.raises(HTTPException) as exc_info:
        svc.create(role.id, DefaultRoleReportCreate(report_id=report.id, can_view=True))
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["code"] == "AUTH_DEFAULT_ROLE_REPORT_BAD_REQUEST"


def test_create_default_report_rejects_system_admin_role() -> None:
    db = MagicMock()
    db.scalars.return_value = _first(_role(user_scope="system", code="system_admin"))
    svc = DefaultRoleReportService(db)
    with pytest.raises(HTTPException) as exc_info:
        svc.create(_ROLE_ID, DefaultRoleReportCreate(report_id=_REPORT_ID))
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["code"] == "AUTH_DEFAULT_ROLE_REPORT_BAD_REQUEST"


def test_create_default_report_requires_view_for_export() -> None:
    db = MagicMock()
    db.scalars.side_effect = [_first(_role()), _first(_report())]
    svc = DefaultRoleReportService(db)
    with pytest.raises(HTTPException) as exc_info:
        svc.create(
            _ROLE_ID,
            DefaultRoleReportCreate(report_id=_REPORT_ID, can_view=False, can_export=True),
        )
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["code"] == "AUTH_DEFAULT_ROLE_REPORT_BAD_REQUEST"


def test_create_default_report_audits() -> None:
    db = MagicMock()
    db.scalars.side_effect = [_first(_role()), _first(_report()), _first(None)]
    svc = DefaultRoleReportService(db)
    row = svc.create(
        _ROLE_ID,
        DefaultRoleReportCreate(report_id=_REPORT_ID, can_view=True, can_export=True),
        created_by=TEST_USER_ID,
        actor=ACTOR,
        source=SOURCE,
    )
    assert row.can_export is True
    [log] = _added(db, AuditLog)
    assert (log.action, log.table_name) == ("insert", "default_role_report")


def test_update_default_report_export_needs_view() -> None:
    db = MagicMock()
    grant = DefaultRoleReport(
        id="01JRACMTFDRTEST00000000001",
        role_id=_ROLE_ID,
        report_id=_REPORT_ID,
        can_view=True,
        can_export=True,
        is_active=True,
        is_deleted=False,
        row_version=_ROW_VER,
        created_at=_NOW,
        updated_at=_NOW,
    )
    db.scalars.side_effect = [_first(_role()), _first(grant)]
    svc = DefaultRoleReportService(db)
    with pytest.raises(HTTPException) as exc_info:
        svc.update(
            _ROLE_ID,
            _REPORT_ID,
            DefaultRoleReportUpdate(row_version=_ROW_VER, can_view=False),
        )
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["code"] == "AUTH_DEFAULT_ROLE_REPORT_BAD_REQUEST"
