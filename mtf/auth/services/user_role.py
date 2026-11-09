"""Tenant staff ``auth.user_role`` assignments."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from mtf.audit.service import (
    AuditSource,
    audit_insert,
    audit_soft_delete,
    row_snapshot,
)
from mtf.auth.models.user_role import UserRole
from mtf.auth.schemas.user_role import UserRoleCreate
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
from mtf.shared.security import generate_id


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

    def _live_assignment(self, tenant_id: str, user_id: str, role_id: str) -> UserRole | None:
        return self._db.scalars(
            select(UserRole).where(
                UserRole.tenant_id == tenant_id,
                UserRole.user_id == user_id,
                UserRole.account_id.is_(None),
                UserRole.role_id == role_id,
                UserRole.is_deleted == False,  # noqa: E712
            )
        ).first()

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
        assert_no_escalation(resolver, actor, permission_codes_for_role(self._db, role.id))
        if self._live_assignment(tenant_id, user_id, role.id) is not None:
            conflict("AUTH_USER_ROLE", "User already holds this role")

        row = UserRole(
            id=generate_id(),
            tenant_id=tenant_id,
            user_id=user_id,
            account_id=None,
            role_id=role.id,
            user_scope="tenant",
            created_by=created_by,
            updated_by=created_by,
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
        deleted_by: str,
        actor: CurrentUser | None = None,
        source: AuditSource | None = None,
    ) -> UserRole:
        require_active_tenant_membership(self._db, tenant_id, user_id)
        row = self._live_assignment(tenant_id, user_id, role_id)
        if row is None:
            not_found("AUTH_USER_ROLE", "Role assignment not found")
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
