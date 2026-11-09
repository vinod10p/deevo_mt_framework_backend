"""Tenant-owned roles and their permission grants."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from mtf.audit.service import (
    AuditSource,
    audit_insert,
    audit_soft_delete,
    audit_update,
    row_snapshot,
)
from mtf.auth.models.role import Role
from mtf.auth.models.role_permission import RolePermission
from mtf.auth.schemas.role import RoleUpdate, TenantRoleCreate
from mtf.auth.schemas.role_permission import RolePermissionCreate
from mtf.auth.services.permission_resolver import Actor, PermissionResolver
from mtf.auth.services.rbac_assignment import (
    ADMIN_PERMISSION_CODE,
    assert_no_escalation,
    assert_not_last_admin,
    assignable_role_filter,
    permission_codes_for_role,
    require_assignable_role,
    require_tenant_owned_role,
)
from mtf.auth.services.rbac_catalog import (
    apply_soft_delete,
    commit_or_conflict,
    require_live_permission,
    utc_naive_now,
)
from mtf.shared.deps import CurrentUser
from mtf.shared.exceptions import bad_request, conflict, not_found, row_version_conflict
from mtf.shared.security import generate_id


class TenantRoleService:
    def __init__(self, session: Session) -> None:
        self._db = session

    def list_roles(
        self,
        tenant_id: str,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Role]:
        stmt = (
            select(Role)
            .where(
                Role.is_deleted == False,  # noqa: E712
                assignable_role_filter(tenant_id),
            )
            .order_by(Role.is_system.desc(), Role.code)
            .offset(skip)
            .limit(limit)
        )
        return list(self._db.scalars(stmt).all())

    def get(self, tenant_id: str, role_id: str) -> Role:
        return require_assignable_role(self._db, tenant_id, role_id)

    def _live_by_code(self, tenant_id: str, code: str) -> Role | None:
        return self._db.scalars(
            select(Role).where(
                Role.tenant_id == tenant_id,
                Role.code == code,
                Role.is_deleted == False,  # noqa: E712
            )
        ).first()

    def create(
        self,
        tenant_id: str,
        data: TenantRoleCreate,
        *,
        created_by: str | None = None,
        actor: CurrentUser | None = None,
        source: AuditSource | None = None,
    ) -> Role:
        if self._live_by_code(tenant_id, data.code) is not None:
            conflict("AUTH_ROLE", "Role code already exists in this tenant")

        row = Role(
            id=generate_id(),
            tenant_id=tenant_id,
            code=data.code,
            name=data.name,
            description=data.description,
            user_scope="tenant",
            is_system=False,
            created_by=created_by,
            updated_by=created_by,
        )
        self._db.add(row)
        audit_insert(
            self._db,
            entity=row,
            schema_name="auth",
            table_name="role",
            actor=actor,
            source=source,
            tenant_id=tenant_id,
        )
        commit_or_conflict(
            self._db,
            code_prefix="AUTH_ROLE",
            message="Role code already exists in this tenant",
        )
        self._db.refresh(row)
        return row

    def update(
        self,
        tenant_id: str,
        role_id: str,
        data: RoleUpdate,
        *,
        updated_by: str | None = None,
        actor: CurrentUser | None = None,
        source: AuditSource | None = None,
    ) -> Role:
        row = require_tenant_owned_role(self._db, tenant_id, role_id)
        if row.row_version != data.row_version:
            row_version_conflict("AUTH_ROLE")

        before = row_snapshot(row)
        updates = data.model_dump(exclude_none=True, exclude={"row_version"})
        for key, value in updates.items():
            setattr(row, key, value)
        row.updated_at = utc_naive_now()
        if updated_by is not None:
            row.updated_by = updated_by

        self._db.add(row)
        audit_update(
            self._db,
            entity=row,
            schema_name="auth",
            table_name="role",
            before=before,
            actor=actor,
            source=source,
            tenant_id=tenant_id,
        )
        self._db.commit()
        self._db.refresh(row)
        return row

    def soft_delete(
        self,
        tenant_id: str,
        role_id: str,
        *,
        deleted_by: str,
        actor: CurrentUser | None = None,
        source: AuditSource | None = None,
    ) -> Role:
        row = require_tenant_owned_role(self._db, tenant_id, role_id)
        if ADMIN_PERMISSION_CODE in permission_codes_for_role(self._db, row.id):
            assert_not_last_admin(self._db, tenant_id, drop_role_id=row.id)
        before = row_snapshot(row)
        apply_soft_delete(row, deleted_by=deleted_by)
        self._db.add(row)
        audit_soft_delete(
            self._db,
            entity=row,
            schema_name="auth",
            table_name="role",
            before=before,
            actor=actor,
            source=source,
            tenant_id=tenant_id,
        )
        self._db.commit()
        self._db.refresh(row)
        return row

    def list_permissions(
        self,
        tenant_id: str,
        role_id: str,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> list[RolePermission]:
        require_assignable_role(self._db, tenant_id, role_id)
        stmt = (
            select(RolePermission)
            .where(
                RolePermission.role_id == role_id,
                RolePermission.is_deleted == False,  # noqa: E712
            )
            .order_by(RolePermission.created_at, RolePermission.id)
            .offset(skip)
            .limit(limit)
        )
        return list(self._db.scalars(stmt).all())

    def _live_grant(self, role_id: str, permission_id: str) -> RolePermission | None:
        return self._db.scalars(
            select(RolePermission).where(
                RolePermission.role_id == role_id,
                RolePermission.permission_id == permission_id,
                RolePermission.is_deleted == False,  # noqa: E712
            )
        ).first()

    def grant_permission(
        self,
        tenant_id: str,
        role_id: str,
        data: RolePermissionCreate,
        *,
        resolver: PermissionResolver,
        actor: Actor,
        created_by: str | None = None,
        source: AuditSource | None = None,
    ) -> RolePermission:
        role = require_tenant_owned_role(self._db, tenant_id, role_id)
        permission = require_live_permission(self._db, data.permission_id)
        if permission.user_scope != role.user_scope:
            bad_request(
                "AUTH_ROLE_PERMISSION",
                "Permission user_scope must match the role user_scope",
            )
        assert_no_escalation(resolver, actor, [permission.code])
        if self._live_grant(role.id, permission.id) is not None:
            conflict("AUTH_ROLE_PERMISSION", "Permission is already granted to this role")

        row = RolePermission(
            id=generate_id(),
            role_id=role.id,
            permission_id=permission.id,
            user_scope=role.user_scope,
            created_by=created_by,
            updated_by=created_by,
        )
        self._db.add(row)
        audit_insert(
            self._db,
            entity=row,
            schema_name="auth",
            table_name="role_permission",
            actor=actor if isinstance(actor, CurrentUser) else None,
            source=source,
            tenant_id=tenant_id,
        )
        commit_or_conflict(
            self._db,
            code_prefix="AUTH_ROLE_PERMISSION",
            message="Permission is already granted to this role",
        )
        self._db.refresh(row)
        return row

    def revoke_permission(
        self,
        tenant_id: str,
        role_id: str,
        permission_id: str,
        *,
        deleted_by: str,
        actor: CurrentUser | None = None,
        source: AuditSource | None = None,
    ) -> RolePermission:
        require_tenant_owned_role(self._db, tenant_id, role_id)
        row = self._live_grant(role_id, permission_id)
        if row is None:
            not_found("AUTH_ROLE_PERMISSION", "Role permission not found")
        permission = require_live_permission(self._db, permission_id)
        if permission.code == ADMIN_PERMISSION_CODE:
            assert_not_last_admin(self._db, tenant_id, drop_role_id=role_id)
        before = row_snapshot(row)
        apply_soft_delete(row, deleted_by=deleted_by)
        self._db.add(row)
        audit_soft_delete(
            self._db,
            entity=row,
            schema_name="auth",
            table_name="role_permission",
            before=before,
            actor=actor,
            source=source,
            tenant_id=tenant_id,
        )
        self._db.commit()
        self._db.refresh(row)
        return row
