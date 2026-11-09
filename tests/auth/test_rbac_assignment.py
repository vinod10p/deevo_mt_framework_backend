"""Unit tests — tenant assignment helpers, last-admin, escalation."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from mtf.audit.models import AuditLog
from mtf.auth.models.permission import Permission
from mtf.auth.models.role import Role
from mtf.auth.models.tenant_user import TenantUser
from mtf.auth.models.user import User
from mtf.auth.models.user_role import UserRole
from mtf.auth.schemas.role import TenantRoleCreate
from mtf.auth.schemas.role_permission import RolePermissionCreate
from mtf.auth.schemas.user_role import UserRoleCreate
from mtf.auth.services.rbac_assignment import (
    ADMIN_PERMISSION_CODE,
    assert_no_escalation,
    assert_not_last_admin,
    require_tenant_owned_role,
)
from mtf.auth.services.tenant_role import TenantRoleService
from mtf.auth.services.user_role import UserRoleService
from mtf.shared.deps import CurrentUser
from tests.tenant.conftest import TEST_TENANT_ID, TEST_USER_ID

_NOW = datetime(2026, 5, 9, 12, 0, 0)
_ROW_VER = bytes(range(8))
_ROLE_ID = "01JRACMTFR1TEST00000000009"
_PERM_ID = "01JRACMTFPMTEST00000000009"
_ADMIN_ROLE_ID = "01JRACMTFR1000000000000001"
ACTOR = CurrentUser(
    user_id=TEST_USER_ID,
    user_type="app_user",
    user_scope="tenant",
    tenant_id=TEST_TENANT_ID,
)


def _first(value: object) -> MagicMock:
    result = MagicMock()
    result.first.return_value = value
    result.all.return_value = [] if value is None else [value]
    return result


def _added(db: MagicMock, model: type) -> list:
    return [call.args[0] for call in db.add.call_args_list if isinstance(call.args[0], model)]


def _role(**overrides: object) -> Role:
    values: dict[str, object] = {
        "id": _ROLE_ID,
        "tenant_id": TEST_TENANT_ID,
        "code": "support_lead",
        "name": "Support Lead",
        "description": None,
        "user_scope": "tenant",
        "is_system": False,
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


def _permission(**overrides: object) -> Permission:
    values: dict[str, object] = {
        "id": _PERM_ID,
        "code": "screen.lead.view",
        "resource_type": "screen",
        "resource_code": "lead",
        "action": "view",
        "user_scope": "tenant",
        "description": None,
        "is_active": True,
        "is_deleted": False,
    }
    values.update(overrides)
    return Permission(**values)  # type: ignore[arg-type]


def test_last_admin_revoke_is_409() -> None:
    db = MagicMock()
    db.execute.return_value.all.return_value = [(TEST_USER_ID, _ADMIN_ROLE_ID)]
    with pytest.raises(HTTPException) as exc_info:
        assert_not_last_admin(
            db,
            TEST_TENANT_ID,
            drop_user_id=TEST_USER_ID,
            drop_role_id=_ADMIN_ROLE_ID,
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "AUTH_ROLE_CONFLICT"
    db.execute.assert_called_once()


def test_last_admin_allows_when_another_holder_remains() -> None:
    db = MagicMock()
    db.execute.return_value.all.return_value = [
        (TEST_USER_ID, _ADMIN_ROLE_ID),
        ("01OTHER000000000000000000", _ADMIN_ROLE_ID),
    ]
    assert_not_last_admin(
        db,
        TEST_TENANT_ID,
        drop_user_id=TEST_USER_ID,
        drop_role_id=_ADMIN_ROLE_ID,
    )


def test_last_admin_drop_role_keeps_other_admin_role() -> None:
    db = MagicMock()
    db.execute.return_value.all.return_value = [
        (TEST_USER_ID, _ADMIN_ROLE_ID),
        (TEST_USER_ID, _ROLE_ID),
    ]
    assert_not_last_admin(db, TEST_TENANT_ID, drop_role_id=_ROLE_ID)


def test_escalation_rejects_ungranted_permission() -> None:
    resolver = MagicMock()
    resolver.permission_codes.return_value = frozenset({"screen.lead.view"})
    with pytest.raises(HTTPException) as exc_info:
        assert_no_escalation(resolver, ACTOR, [ADMIN_PERMISSION_CODE])
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "AUTH_ROLE_FORBIDDEN"


def test_escalation_allows_held_permission() -> None:
    resolver = MagicMock()
    resolver.permission_codes.return_value = frozenset(
        {"screen.lead.view", ADMIN_PERMISSION_CODE}
    )
    assert_no_escalation(resolver, ACTOR, ["screen.lead.view"])


def test_cannot_edit_platform_role() -> None:
    db = MagicMock()
    db.scalars.return_value = _first(_role(tenant_id=None, is_system=True, code="tenant_admin"))
    with pytest.raises(HTTPException) as exc_info:
        require_tenant_owned_role(db, TEST_TENANT_ID, _ADMIN_ROLE_ID)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "AUTH_ROLE_FORBIDDEN"


def test_create_tenant_role_is_not_system() -> None:
    db = MagicMock()
    db.scalars.return_value = _first(None)
    svc = TenantRoleService(db)
    row = svc.create(
        TEST_TENANT_ID,
        TenantRoleCreate(code="support_lead", name="Support Lead"),
        created_by=TEST_USER_ID,
        actor=ACTOR,
    )
    assert row.tenant_id == TEST_TENANT_ID
    assert row.is_system is False
    assert row.user_scope == "tenant"
    [role] = _added(db, Role)
    assert role.is_system is False
    [log] = _added(db, AuditLog)
    assert (log.action, log.table_name, log.tenant_id) == ("insert", "role", TEST_TENANT_ID)


def test_grant_permission_escalation() -> None:
    db = MagicMock()
    role = _role()
    permission = _permission(code=ADMIN_PERMISSION_CODE)
    db.scalars.side_effect = [_first(role), _first(permission)]
    resolver = MagicMock()
    resolver.permission_codes.return_value = frozenset({"screen.lead.view"})
    svc = TenantRoleService(db)
    with pytest.raises(HTTPException) as exc_info:
        svc.grant_permission(
            TEST_TENANT_ID,
            role.id,
            RolePermissionCreate(permission_id=permission.id),
            resolver=resolver,
            actor=ACTOR,
            created_by=TEST_USER_ID,
        )
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "AUTH_ROLE_FORBIDDEN"


def test_grant_permission_success_audits() -> None:
    db = MagicMock()
    role = _role()
    permission = _permission()
    db.scalars.side_effect = [_first(role), _first(permission), _first(None)]
    resolver = MagicMock()
    resolver.permission_codes.return_value = frozenset({"screen.lead.view"})
    svc = TenantRoleService(db)
    row = svc.grant_permission(
        TEST_TENANT_ID,
        role.id,
        RolePermissionCreate(permission_id=permission.id),
        resolver=resolver,
        actor=ACTOR,
        created_by=TEST_USER_ID,
    )
    assert row.user_scope == "tenant"
    [log] = _added(db, AuditLog)
    assert (log.action, log.table_name) == ("insert", "role_permission")


def test_assign_role_requires_membership() -> None:
    db = MagicMock()
    db.scalars.side_effect = [
        _first(
            User(
                id=TEST_USER_ID,
                email="a@example.com",
                user_scope="tenant",
                is_deleted=False,
            )
        ),
        _first(None),
    ]
    svc = UserRoleService(db)
    resolver = MagicMock()
    with pytest.raises(HTTPException) as exc_info:
        svc.create(
            TEST_TENANT_ID,
            TEST_USER_ID,
            UserRoleCreate(role_id=_ROLE_ID),
            resolver=resolver,
            actor=ACTOR,
            created_by=TEST_USER_ID,
        )
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["code"] == "TENANT_USER_NOT_FOUND"


def test_assign_role_audits() -> None:
    db = MagicMock()
    user = User(
        id=TEST_USER_ID,
        email="a@example.com",
        user_scope="tenant",
        is_deleted=False,
    )
    membership = TenantUser(
        id="01MEMBERSHIP00000000000001",
        tenant_id=TEST_TENANT_ID,
        user_id=TEST_USER_ID,
        role="member",
        is_active=True,
        is_deleted=False,
    )
    role = _role()
    codes = MagicMock()
    codes.all.return_value = []
    db.scalars.side_effect = [
        _first(user),
        _first(membership),
        _first(role),
        codes,
        _first(None),
    ]
    resolver = MagicMock()
    resolver.permission_codes.return_value = frozenset({"screen.lead.view"})
    svc = UserRoleService(db)
    row = svc.create(
        TEST_TENANT_ID,
        TEST_USER_ID,
        UserRoleCreate(role_id=role.id),
        resolver=resolver,
        actor=ACTOR,
        created_by=TEST_USER_ID,
    )
    assert row.account_id is None
    assert row.user_scope == "tenant"
    [log] = _added(db, AuditLog)
    assert (log.action, log.table_name) == ("insert", "user_role")
    assert isinstance(_added(db, UserRole)[0], UserRole)
