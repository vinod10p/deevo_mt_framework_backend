"""Platform role catalog service — ``auth.role`` where ``tenant_id`` is NULL."""

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
from mtf.auth.schemas.role import RoleCreate, RoleUpdate
from mtf.auth.services.rbac_catalog import (
    apply_soft_delete,
    commit_or_conflict,
    require_platform_role,
    utc_naive_now,
)
from mtf.shared.deps import CurrentUser
from mtf.shared.exceptions import conflict, row_version_conflict
from mtf.shared.security import generate_id


class RoleService:
    def __init__(self, session: Session) -> None:
        self._db = session

    def list_roles(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        user_scope: str | None = None,
    ) -> list[Role]:
        stmt = select(Role).where(
            Role.tenant_id.is_(None),
            Role.is_deleted == False,  # noqa: E712
        )
        if user_scope is not None:
            stmt = stmt.where(Role.user_scope == user_scope)
        stmt = stmt.order_by(Role.code).offset(skip).limit(limit)
        return list(self._db.scalars(stmt).all())

    def get(self, role_id: str) -> Role:
        return require_platform_role(self._db, role_id)

    def _live_platform_by_code(self, code: str) -> Role | None:
        return self._db.scalars(
            select(Role).where(
                Role.tenant_id.is_(None),
                Role.code == code,
                Role.is_deleted == False,  # noqa: E712
            )
        ).first()

    def create(
        self,
        data: RoleCreate,
        *,
        created_by: str | None = None,
        actor: CurrentUser | None = None,
        source: AuditSource | None = None,
    ) -> Role:
        if self._live_platform_by_code(data.code) is not None:
            conflict("AUTH_ROLE", "Platform role code already exists")

        row = Role(
            id=generate_id(),
            tenant_id=None,
            code=data.code,
            name=data.name,
            description=data.description,
            user_scope=data.user_scope,
            is_system=True,
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
        )
        commit_or_conflict(
            self._db,
            code_prefix="AUTH_ROLE",
            message="Platform role code already exists",
        )
        self._db.refresh(row)
        return row

    def update(
        self,
        role_id: str,
        data: RoleUpdate,
        *,
        updated_by: str | None = None,
        actor: CurrentUser | None = None,
        source: AuditSource | None = None,
    ) -> Role:
        row = self.get(role_id)
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
        )
        self._db.commit()
        self._db.refresh(row)
        return row

    def soft_delete(
        self,
        role_id: str,
        *,
        deleted_by: str,
        actor: CurrentUser | None = None,
        source: AuditSource | None = None,
    ) -> Role:
        row = self.get(role_id)
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
        )
        self._db.commit()
        self._db.refresh(row)
        return row
