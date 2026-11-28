"""Unit tests — membership → template dual-write (admin thin / member empty)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from mtf.auth.models.role import Role
from mtf.auth.models.user_role import UserRole
from mtf.auth.services.membership_rbac import (
    ADMIN_TEMPLATE_CODE,
    MEMBER_TEMPLATE_CODE,
    TENANT_MEMBERSHIP_ROLE_MAP,
    require_platform_role,
    sync_tenant_user_role,
    template_role_code,
)
from tests.conftest import TEST_BUSINESS_UNIT_ID

_MOD = "mtf.auth.services.membership_rbac"


def test_tenant_map_is_admin_only() -> None:
    assert TENANT_MEMBERSHIP_ROLE_MAP == {"admin": "tenant_admin"}
    assert template_role_code(user_scope="tenant", membership_role="admin") == "tenant_admin"
    assert template_role_code(user_scope="tenant", membership_role="member") is None
    with pytest.raises(HTTPException) as exc:
        template_role_code(user_scope="tenant", membership_role="owner")
    assert exc.value.status_code == 400


def test_sync_admin_assigns_tenant_admin() -> None:
    db = MagicMock()
    admin = Role(
        id="01JRACMTFR1000000000000001",
        tenant_id=None,
        code=ADMIN_TEMPLATE_CODE,
        name="Tenant Admin",
        user_scope="tenant",
        is_system=True,
        is_active=True,
        is_deleted=False,
    )
    with (
        patch(f"{_MOD}.require_platform_role", return_value=admin) as require,
        patch(f"{_MOD}._live_assignments", return_value=[]),
        patch(f"{_MOD}.audit_insert"),
    ):
        sync_tenant_user_role(
            db,
            tenant_id="t1",
            user_id="u1",
            membership_role="admin",
            actor_id="actor",
        )
    require.assert_called_once_with(db, code="tenant_admin", user_scope="tenant")
    (assignment,) = db.add.call_args.args
    assert assignment.role_id == admin.id
    # Membership templates apply in every store, so they are written at the root unit.
    assert assignment.business_unit_id == TEST_BUSINESS_UNIT_ID


def test_sync_member_revokes_templates_and_assigns_nothing() -> None:
    db = MagicMock()
    leftover = UserRole(
        id="01JOLD0000000000000000001",
        tenant_id="t1",
        user_id="u1",
        account_id=None,
        role_id="01JRACMTFR1000000000000002",
        user_scope="tenant",
        is_active=True,
        is_deleted=False,
    )
    with (
        patch(f"{_MOD}.require_platform_role") as require,
        patch(f"{_MOD}._live_assignments", return_value=[leftover]),
        patch(f"{_MOD}._soft_delete_assignment") as soft,
        patch(f"{_MOD}.audit_insert") as insert,
    ):
        sync_tenant_user_role(
            db,
            tenant_id="t1",
            user_id="u1",
            membership_role="member",
            actor_id="actor",
        )
    require.assert_not_called()
    soft.assert_called_once()
    insert.assert_not_called()


def test_require_platform_role_missing_is_409() -> None:
    db = MagicMock()
    db.scalars.return_value.first.return_value = None
    with pytest.raises(HTTPException) as exc:
        require_platform_role(db, code=MEMBER_TEMPLATE_CODE, user_scope="tenant")
    assert exc.value.status_code == 409
