"""Unit tests — tenant assignment helpers, last-admin, escalation."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from mtf.audit.models import AuditLog
from mtf.auth.models.permission import Permission
from mtf.auth.models.role import Role
from mtf.auth.models.tenant_user import TenantUser
from mtf.auth.models.user import User
from mtf.auth.models.user_role import UserRole
from mtf.auth.schemas.role import RoleUpdate, TenantRoleCreate
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
from mtf.tenant.services.business_unit_service import BusinessUnitService
from tests.conftest import TEST_BUSINESS_UNIT_ID as ROOT_ID
from tests.tenant.conftest import TEST_TENANT_ID, TEST_USER_ID

STORE_ID = "01HZYJZGXM0KV0K4T8Y9STORE1"

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
        "module_code": "GENERAL",
        "resource_name": "Lead",
        "sort_order": 0,
        "is_tenant_grantable": True,
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


def test_role_admin_may_grant_tenant_grantable_permissions() -> None:
    resolver = MagicMock()
    resolver.permission_codes.return_value = frozenset({ADMIN_PERMISSION_CODE})
    db = MagicMock()
    db.scalars.return_value.all.return_value = ["screen.lead.view", "menu.wf_inbox.view"]
    assert_no_escalation(
        resolver,
        ACTOR,
        ["screen.lead.view", "menu.wf_inbox.view"],
        db=db,
    )


def test_role_admin_still_blocked_from_non_grantable() -> None:
    resolver = MagicMock()
    resolver.permission_codes.return_value = frozenset({ADMIN_PERMISSION_CODE})
    db = MagicMock()
    db.scalars.return_value.all.return_value = []
    with pytest.raises(HTTPException) as exc_info:
        assert_no_escalation(resolver, ACTOR, ["system.secret"], db=db)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "AUTH_ROLE_FORBIDDEN"


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


def _codes(*codes: str) -> MagicMock:
    result = MagicMock()
    result.all.return_value = list(codes)
    return result


def test_deactivate_last_admin_role_is_409() -> None:
    db = MagicMock()
    db.scalars.side_effect = [_first(_role()), _codes(ADMIN_PERMISSION_CODE)]
    db.execute.return_value.all.return_value = [(TEST_USER_ID, _ROLE_ID)]
    svc = TenantRoleService(db)
    with pytest.raises(HTTPException) as exc_info:
        svc.update(
            TEST_TENANT_ID,
            _ROLE_ID,
            RoleUpdate(row_version=_ROW_VER, is_active=False),
            updated_by=TEST_USER_ID,
            actor=ACTOR,
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "AUTH_ROLE_CONFLICT"
    db.commit.assert_not_called()


def test_deactivate_admin_role_allowed_when_other_admin_remains() -> None:
    db = MagicMock()
    db.scalars.side_effect = [_first(_role()), _codes(ADMIN_PERMISSION_CODE)]
    db.execute.return_value.all.return_value = [
        (TEST_USER_ID, _ROLE_ID),
        ("01OTHER000000000000000000", _ADMIN_ROLE_ID),
    ]
    row = TenantRoleService(db).update(
        TEST_TENANT_ID,
        _ROLE_ID,
        RoleUpdate(row_version=_ROW_VER, is_active=False),
        updated_by=TEST_USER_ID,
        actor=ACTOR,
    )
    assert row.is_active is False
    db.commit.assert_called_once()


def test_rename_admin_role_skips_last_admin_check() -> None:
    db = MagicMock()
    db.scalars.side_effect = [_first(_role())]
    TenantRoleService(db).update(
        TEST_TENANT_ID,
        _ROLE_ID,
        RoleUpdate(row_version=_ROW_VER, name="Renamed"),
        updated_by=TEST_USER_ID,
        actor=ACTOR,
    )
    db.execute.assert_not_called()


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
    with patch.object(BusinessUnitService, "default_store_id", return_value=STORE_ID):
        row = svc.create(
            TEST_TENANT_ID,
            TEST_USER_ID,
            UserRoleCreate(role_id=role.id),
            resolver=resolver,
            actor=ACTOR,
            created_by=TEST_USER_ID,
        )
    assert row.business_unit_id == STORE_ID  # a custom role lands at the default store
    assert row.account_id is None
    assert row.user_scope == "tenant"
    [log] = _added(db, AuditLog)
    assert (log.action, log.table_name) == ("insert", "user_role")
    assert isinstance(_added(db, UserRole)[0], UserRole)


# --- where an assignment is held (decision 10, step 8) ----------------------------------


def _unit_for(
    role: Role,
    requested_id: str | None,
    *,
    default_store: str | None = STORE_ID,
    known_units: frozenset[str] = frozenset({ROOT_ID, STORE_ID}),
) -> str:
    with (
        patch.object(BusinessUnitService, "default_store_id", return_value=default_store),
        patch.object(
            BusinessUnitService,
            "get_active",
            side_effect=lambda _tenant, unit_id: unit_id if unit_id in known_units else None,
        ),
    ):
        return UserRoleService(MagicMock())._assignment_unit(
            TEST_TENANT_ID, TEST_USER_ID, role, requested_id
        )


@pytest.mark.parametrize(
    ("tenant_wide", "requested", "expected"),
    [
        (True, None, ROOT_ID),  # tenant-wide roles default to every store
        (False, None, STORE_ID),  # custom roles default to the user's default store
        (False, STORE_ID, STORE_ID),
        (True, STORE_ID, STORE_ID),
        (True, ROOT_ID, ROOT_ID),
    ],
)
def test_assignment_unit(tenant_wide: bool, requested: str | None, expected: str) -> None:
    assert _unit_for(_role(is_tenant_wide=tenant_wide), requested) == expected


@pytest.mark.parametrize(
    ("requested", "default_store"),
    [(ROOT_ID, STORE_ID), (None, None)],
    ids=["root-named", "no-default-store"],
)
def test_custom_role_at_root_is_refused(requested: str | None, default_store: str | None) -> None:
    with pytest.raises(HTTPException) as exc_info:
        _unit_for(_role(is_tenant_wide=False), requested, default_store=default_store)
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == {
        "code": "AUTH_ROLE_CONFLICT", "message": "This role can only be assigned to a store",
    }


def test_unit_of_another_tenant_is_not_found() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _unit_for(_role(), "01HZYJZGXM0KV0K4T8Y9OTHER1")
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["code"] == "TENANT_BUSINESS_UNIT_NOT_FOUND"
