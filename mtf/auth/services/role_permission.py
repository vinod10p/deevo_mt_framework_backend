"""Role-permission catalog grants — ``auth.role_permission`` for platform roles."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from mtf.audit.service import (
    AuditSource,
    audit_insert,
    audit_soft_delete,
    row_snapshot,
)
from mtf.auth.models.role_permission import RolePermission
from mtf.auth.schemas.role_permission import RolePermissionCreate
from mtf.auth.services.rbac_catalog import (
    apply_soft_delete,
    commit_or_conflict,
    require_live_permission,
    require_platform_role,
)
from mtf.shared.deps import CurrentUser
from mtf.shared.exceptions import bad_request, conflict, not_found
from mtf.shared.security import generate_id


class RolePermissionService:
    def __init__(self, session: Session) -> None:
        self._db = session

    def list_for_role(
        self,
        role_id: str,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> list[RolePermission]:
        require_platform_role(self._db, role_id)
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

    def create(
        self,
        role_id: str,
        data: RolePermissionCreate,
        *,
        created_by: str | None = None,
        actor: CurrentUser | None = None,
        source: AuditSource | None = None,
    ) -> RolePermission:
        role = require_platform_role(self._db, role_id)
        permission = require_live_permission(self._db, data.permission_id)
        if permission.user_scope != role.user_scope:
            bad_request(
                "AUTH_ROLE_PERMISSION",
                "Permission user_scope must match the role user_scope",
            )
        if self._live_grant(role_id, data.permission_id) is not None:
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
            actor=actor,
            source=source,
        )
        commit_or_conflict(
            self._db,
            code_prefix="AUTH_ROLE_PERMISSION",
            message="Permission is already granted to this role",
        )
        self._db.refresh(row)
        return row

    def soft_delete(
        self,
        role_id: str,
        permission_id: str,
        *,
        deleted_by: str,
        actor: CurrentUser | None = None,
        source: AuditSource | None = None,
    ) -> RolePermission:
        require_platform_role(self._db, role_id)
        row = self._live_grant(role_id, permission_id)
        if row is None:
            not_found("AUTH_ROLE_PERMISSION", "Role permission not found")
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
        )
        self._db.commit()
        self._db.refresh(row)
        return row
