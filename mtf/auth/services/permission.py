"""Permission catalog service — ``auth.permission`` (system scope)."""

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
from mtf.auth.models.permission import Permission
from mtf.auth.schemas.permission import PermissionCreate, PermissionUpdate
from mtf.auth.services.rbac_catalog import (
    apply_soft_delete,
    commit_or_conflict,
    compose_permission_code,
    require_live_permission,
    utc_naive_now,
)
from mtf.shared.deps import CurrentUser
from mtf.shared.exceptions import conflict, row_version_conflict
from mtf.shared.security import generate_id


class PermissionService:
    def __init__(self, session: Session) -> None:
        self._db = session

    def list_permissions(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        user_scope: str | None = None,
        resource_type: str | None = None,
    ) -> list[Permission]:
        stmt = select(Permission).where(Permission.is_deleted == False)  # noqa: E712
        if user_scope is not None:
            stmt = stmt.where(Permission.user_scope == user_scope)
        if resource_type is not None:
            stmt = stmt.where(Permission.resource_type == resource_type)
        stmt = stmt.order_by(Permission.code).offset(skip).limit(limit)
        return list(self._db.scalars(stmt).all())

    def get(self, permission_id: str) -> Permission:
        return require_live_permission(self._db, permission_id)

    def _live_by_code(self, code: str) -> Permission | None:
        return self._db.scalars(
            select(Permission).where(
                Permission.code == code,
                Permission.is_deleted == False,  # noqa: E712
            )
        ).first()

    def create(
        self,
        data: PermissionCreate,
        *,
        created_by: str | None = None,
        actor: CurrentUser | None = None,
        source: AuditSource | None = None,
    ) -> Permission:
        code = compose_permission_code(data.resource_type, data.resource_code, data.action)
        if self._live_by_code(code) is not None:
            conflict("AUTH_PERMISSION", "Permission code already exists")

        row = Permission(
            id=generate_id(),
            code=code,
            resource_type=data.resource_type,
            resource_code=data.resource_code,
            action=data.action,
            user_scope=data.user_scope,
            description=data.description,
            created_by=created_by,
            updated_by=created_by,
        )
        self._db.add(row)
        audit_insert(
            self._db,
            entity=row,
            schema_name="auth",
            table_name="permission",
            actor=actor,
            source=source,
        )
        commit_or_conflict(
            self._db,
            code_prefix="AUTH_PERMISSION",
            message="Permission code already exists",
        )
        self._db.refresh(row)
        return row

    def update(
        self,
        permission_id: str,
        data: PermissionUpdate,
        *,
        updated_by: str | None = None,
        actor: CurrentUser | None = None,
        source: AuditSource | None = None,
    ) -> Permission:
        row = self.get(permission_id)
        if row.row_version != data.row_version:
            row_version_conflict("AUTH_PERMISSION")

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
            table_name="permission",
            before=before,
            actor=actor,
            source=source,
        )
        self._db.commit()
        self._db.refresh(row)
        return row

    def soft_delete(
        self,
        permission_id: str,
        *,
        deleted_by: str,
        actor: CurrentUser | None = None,
        source: AuditSource | None = None,
    ) -> Permission:
        row = self.get(permission_id)
        before = row_snapshot(row)
        apply_soft_delete(row, deleted_by=deleted_by)
        self._db.add(row)
        audit_soft_delete(
            self._db,
            entity=row,
            schema_name="auth",
            table_name="permission",
            before=before,
            actor=actor,
            source=source,
        )
        self._db.commit()
        self._db.refresh(row)
        return row
