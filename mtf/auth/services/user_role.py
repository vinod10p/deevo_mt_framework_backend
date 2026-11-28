"""Tenant staff ``auth.user_role`` assignments — a role is held at the root or at one store."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from mtf.audit.service import (
    AuditSource,
    audit_insert,
    audit_soft_delete,
    row_snapshot,
)
from mtf.auth.models.role import Role
from mtf.auth.models.user_role import UserRole
from mtf.auth.schemas.user_role import UserRoleCreate
from mtf.auth.services.membership_rbac import ADMIN_TEMPLATE_CODE, MEMBER_TEMPLATE_CODE
from mtf.auth.services.permission_resolver import Actor, PermissionResolver
from mtf.auth.services.rbac_assignment import (
    assert_no_escalation,
    assert_not_last_admin,
    permission_codes_for_role,
    require_active_tenant_membership,
    require_assignable_role,
    require_tenant_staff_user,
)
from mtf.auth.services.rbac_catalog import apply_soft_delete, commit_or_conflict
from mtf.shared.deps import CurrentUser
from mtf.shared.exceptions import conflict, not_found
from mtf.tenant.business_units import root_unit_id
from mtf.tenant.services.business_unit_service import BusinessUnitService

_STORE_ONLY = "This role can only be assigned to a store"


def _reject_membership_template(role: Role) -> None:
    """Platform tenant_admin / tenant_member follow membership dual-write, not Role Admin."""
    if (
        role.tenant_id is None
        and role.user_scope == "tenant"
        and role.code in {ADMIN_TEMPLATE_CODE, MEMBER_TEMPLATE_CODE}
    ):
        conflict(
            "AUTH_USER_ROLE",
            f"{role.code} is managed by tenant membership (admin/member); "
            "change the user's membership role or assign a custom role",
        )


class UserRoleService:
    def __init__(self, session: Session) -> None:
        self._db = session

    def list_for_user(
        self,
        tenant_id: str,
        user_id: str,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> list[UserRole]:
        require_active_tenant_membership(self._db, tenant_id, user_id)
        stmt = (
            select(UserRole)
            .where(
                UserRole.tenant_id == tenant_id,
                UserRole.user_id == user_id,
                UserRole.account_id.is_(None),
                UserRole.is_deleted == False,  # noqa: E712
            )
            .order_by(UserRole.created_at, UserRole.id)
            .offset(skip)
            .limit(limit)
        )
        return list(self._db.scalars(stmt).all())

    def _live_assignments(
        self, tenant_id: str, user_id: str, role_id: str, business_unit_id: str | None = None
    ) -> list[UserRole]:
        """The user's live rows for ``role_id`` — at one unit, or at every unit."""
        stmt = select(UserRole).where(
            UserRole.tenant_id == tenant_id,
            UserRole.user_id == user_id,
            UserRole.account_id.is_(None),
            UserRole.role_id == role_id,
            UserRole.is_deleted == False,  # noqa: E712
        )
        if business_unit_id is not None:
            stmt = stmt.where(UserRole.business_unit_id == business_unit_id)
        return list(self._db.scalars(stmt))

    def _assignment_unit(
        self, tenant_id: str, user_id: str, role: Role, requested_id: str | None
    ) -> str:
        """Where the new assignment is held (decision 10: root only for tenant-wide roles)."""
        root_id = root_unit_id(self._db, tenant_id)
        if requested_id is None:
            if role.is_tenant_wide:
                return root_id
            requested_id = BusinessUnitService(self._db).default_store_id(tenant_id, user_id)
            if requested_id is None:
                conflict("AUTH_ROLE", _STORE_ONLY)
        elif BusinessUnitService(self._db).get_active(tenant_id, requested_id) is None:
            not_found("TENANT_BUSINESS_UNIT", "Business unit not found")
        if requested_id == root_id and not role.is_tenant_wide:
            conflict("AUTH_ROLE", _STORE_ONLY)
        return requested_id

    def create(
        self,
        tenant_id: str,
        user_id: str,
        data: UserRoleCreate,
        *,
        resolver: PermissionResolver,
        actor: Actor,
        created_by: str | None = None,
        source: AuditSource | None = None,
    ) -> UserRole:
        require_tenant_staff_user(self._db, user_id)
        require_active_tenant_membership(self._db, tenant_id, user_id)
        role = require_assignable_role(self._db, tenant_id, data.role_id)
        if role.user_scope != "tenant":
            not_found("AUTH_ROLE", "Role not found")
        _reject_membership_template(role)
        assert_no_escalation(
            resolver,
            actor,
            permission_codes_for_role(self._db, role.id),
            db=self._db,
        )
        unit_id = self._assignment_unit(tenant_id, user_id, role, data.business_unit_id)
        if self._live_assignments(tenant_id, user_id, role.id, unit_id):
            conflict("AUTH_USER_ROLE", "User already holds this role")

        row = UserRole.new(
            by=created_by,
            tenant_id=tenant_id,
            business_unit_id=unit_id,
            user_id=user_id,
            account_id=None,
            role_id=role.id,
            user_scope="tenant",
        )
        self._db.add(row)
        audit_insert(
            self._db,
            entity=row,
            schema_name="auth",
            table_name="user_role",
            actor=actor if isinstance(actor, CurrentUser) else None,
            source=source,
            tenant_id=tenant_id,
        )
        commit_or_conflict(
            self._db,
            code_prefix="AUTH_USER_ROLE",
            message="User already holds this role",
        )
        self._db.refresh(row)
        return row

    def soft_delete(
        self,
        tenant_id: str,
        user_id: str,
        role_id: str,
        *,
        business_unit_id: str | None = None,
        deleted_by: str,
        actor: CurrentUser | None = None,
        source: AuditSource | None = None,
    ) -> UserRole:
        """Revoke the role at ``business_unit_id`` (may be omitted if held at one unit only)."""
        require_active_tenant_membership(self._db, tenant_id, user_id)
        rows = self._live_assignments(tenant_id, user_id, role_id, business_unit_id)
        if not rows:
            not_found("AUTH_USER_ROLE", "Role assignment not found")
        if len(rows) > 1:
            conflict(
                "AUTH_USER_ROLE",
                "The user holds this role at more than one store; name the business unit",
            )
        row = rows[0]
        role = self._db.get(Role, role_id)
        if role is not None:
            _reject_membership_template(role)
        assert_not_last_admin(
            self._db,
            tenant_id,
            drop_user_id=user_id,
            drop_role_id=role_id,
        )
        before = row_snapshot(row)
        apply_soft_delete(row, deleted_by=deleted_by)
        self._db.add(row)
        audit_soft_delete(
            self._db,
            entity=row,
            schema_name="auth",
            table_name="user_role",
            before=before,
            actor=actor,
            source=source,
            tenant_id=tenant_id,
        )
        self._db.commit()
        self._db.refresh(row)
        return row
