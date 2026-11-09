"""Dual-write membership.role → auth.user_role, and copy default report grants.

``tenant_user.role`` / ``tenant_account_user.role`` stay master until RBAC owns
the gates. Every membership write must call these helpers in the same
transaction. Missing platform template roles fail the write.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from mtf.audit.service import (
    AuditSource,
    audit_insert,
    audit_soft_delete,
    audit_update,
    row_snapshot,
)
from mtf.auth.models.default_role_report import DefaultRoleReport
from mtf.auth.models.role import Role
from mtf.auth.models.role_report import RoleReport
from mtf.auth.models.user_role import UserRole
from mtf.shared.deps import CurrentUser
from mtf.shared.exceptions import bad_request, conflict
from mtf.shared.security import generate_id

T = TypeVar("T")

#: Membership string → platform ``auth.role.code`` (tenant_id NULL).
TENANT_MEMBERSHIP_ROLE_MAP: dict[str, str] = {
    "owner": "tenant_admin",
    "admin": "tenant_admin",
    "member": "tenant_member",
    "viewer": "tenant_member",
}
ACCOUNT_MEMBERSHIP_ROLE_MAP: dict[str, str] = {
    "admin": "account_admin",
    "member": "account_member",
}


def _utc_naive_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _orm_rows(result: object, model: type[T]) -> list[T]:
    raw = result.all()
    try:
        iterator = iter(raw)
    except TypeError:
        return []
    return [row for row in iterator if isinstance(row, model)]


def _first_orm(result: object, model: type[T]) -> T | None:
    row = result.first()
    return row if isinstance(row, model) else None


def template_role_code(*, user_scope: str, membership_role: str) -> str:
    if user_scope == "tenant":
        mapped = TENANT_MEMBERSHIP_ROLE_MAP.get(membership_role)
    elif user_scope == "tenant_account":
        mapped = ACCOUNT_MEMBERSHIP_ROLE_MAP.get(membership_role)
    else:
        bad_request("AUTH_ROLE", f"Unsupported user_scope {user_scope!r}")
    if mapped is None:
        bad_request(
            "AUTH_ROLE",
            f"Unknown membership role {membership_role!r}",
        )
    return mapped


def require_platform_role(db: Session, *, code: str, user_scope: str) -> Role:
    role = _first_orm(
        db.scalars(
            select(Role).where(
                Role.tenant_id.is_(None),
                Role.code == code,
                Role.user_scope == user_scope,
                Role.is_active == True,  # noqa: E712
                Role.is_deleted == False,  # noqa: E712
            )
        ),
        Role,
    )
    if role is None:
        conflict("AUTH_ROLE", f"Platform role {code} is missing")
    return role


def copy_default_role_reports(
    db: Session,
    *,
    tenant_id: str,
    created_by: str | None = None,
    actor: CurrentUser | None = None,
    source: AuditSource | None = None,
) -> int:
    """Copy live ``default_role_report`` rows into ``role_report`` for a tenant.

    Inserts only missing ``(role_id, report_id)`` pairs. Empty catalog is a
    no-op — membership writes still fail if a template role is missing.
    """
    defaults = _orm_rows(
        db.scalars(
            select(DefaultRoleReport).where(
                DefaultRoleReport.is_active == True,  # noqa: E712
                DefaultRoleReport.is_deleted == False,  # noqa: E712
            )
        ),
        DefaultRoleReport,
    )
    if not defaults:
        return 0

    existing = {
        (row.role_id, row.report_id)
        for row in _orm_rows(
            db.scalars(
                select(RoleReport).where(
                    RoleReport.tenant_id == tenant_id,
                    RoleReport.is_deleted == False,  # noqa: E712
                )
            ),
            RoleReport,
        )
    }

    inserted = 0
    for default in defaults:
        pair = (default.role_id, default.report_id)
        if pair in existing:
            continue
        row = RoleReport(
            id=generate_id(),
            tenant_id=tenant_id,
            role_id=default.role_id,
            report_id=default.report_id,
            can_view=default.can_view,
            can_export=default.can_export,
            created_by=created_by,
            updated_by=created_by,
        )
        db.add(row)
        audit_insert(
            db,
            entity=row,
            schema_name="auth",
            table_name="role_report",
            actor=actor,
            source=source,
            tenant_id=tenant_id,
        )
        existing.add(pair)
        inserted += 1
    return inserted


def sync_tenant_user_role(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    membership_role: str,
    is_active: bool = True,
    actor_id: str | None = None,
    actor: CurrentUser | None = None,
    source: AuditSource | None = None,
) -> None:
    _sync_assignment(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        account_id=None,
        user_scope="tenant",
        membership_role=membership_role,
        is_active=is_active,
        actor_id=actor_id,
        actor=actor,
        source=source,
    )


def sync_account_user_role(
    db: Session,
    *,
    tenant_id: str,
    account_id: str,
    user_id: str,
    membership_role: str,
    is_active: bool = True,
    actor_id: str | None = None,
    actor: CurrentUser | None = None,
    source: AuditSource | None = None,
) -> None:
    _sync_assignment(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        account_id=account_id,
        user_scope="tenant_account",
        membership_role=membership_role,
        is_active=is_active,
        actor_id=actor_id,
        actor=actor,
        source=source,
    )


def revoke_tenant_user_roles(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    actor_id: str | None = None,
    actor: CurrentUser | None = None,
    source: AuditSource | None = None,
) -> None:
    _revoke_assignments(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        account_id=None,
        actor_id=actor_id,
        actor=actor,
        source=source,
    )


def revoke_account_user_roles(
    db: Session,
    *,
    tenant_id: str,
    account_id: str,
    user_id: str,
    actor_id: str | None = None,
    actor: CurrentUser | None = None,
    source: AuditSource | None = None,
) -> None:
    _revoke_assignments(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        account_id=account_id,
        actor_id=actor_id,
        actor=actor,
        source=source,
    )


def _place_filters(
    *,
    tenant_id: str,
    user_id: str,
    account_id: str | None,
) -> list[object]:
    filters: list[object] = [
        UserRole.tenant_id == tenant_id,
        UserRole.user_id == user_id,
    ]
    if account_id is None:
        filters.append(UserRole.account_id.is_(None))
    else:
        filters.append(UserRole.account_id == account_id)
    return filters


def _live_assignments(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    account_id: str | None,
) -> list[UserRole]:
    return _orm_rows(
        db.scalars(
            select(UserRole).where(
                *_place_filters(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    account_id=account_id,
                ),
                UserRole.is_deleted == False,  # noqa: E712
            )
        ),
        UserRole,
    )


def _sync_assignment(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    account_id: str | None,
    user_scope: str,
    membership_role: str,
    is_active: bool,
    actor_id: str | None,
    actor: CurrentUser | None,
    source: AuditSource | None,
) -> None:
    code = template_role_code(user_scope=user_scope, membership_role=membership_role)
    role = require_platform_role(db, code=code, user_scope=user_scope)
    live = _live_assignments(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        account_id=account_id,
    )
    keep: UserRole | None = None
    for row in live:
        if row.role_id == role.id:
            keep = row
            continue
        _soft_delete_assignment(
            db,
            row,
            actor_id=actor_id,
            actor=actor,
            source=source,
        )
    if keep is None:
        assignment = UserRole(
            id=generate_id(),
            tenant_id=tenant_id,
            user_id=user_id,
            account_id=account_id,
            role_id=role.id,
            user_scope=user_scope,
            is_active=is_active,
            created_by=actor_id,
            updated_by=actor_id,
        )
        db.add(assignment)
        audit_insert(
            db,
            entity=assignment,
            schema_name="auth",
            table_name="user_role",
            actor=actor,
            source=source,
            tenant_id=tenant_id,
            account_id=account_id,
        )
        return

    before = row_snapshot(keep)
    keep.is_active = is_active
    keep.updated_by = actor_id
    keep.updated_at = _utc_naive_now()
    db.add(keep)
    audit_update(
        db,
        entity=keep,
        schema_name="auth",
        table_name="user_role",
        before=before,
        actor=actor,
        source=source,
        tenant_id=tenant_id,
        account_id=account_id,
    )


def _revoke_assignments(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    account_id: str | None,
    actor_id: str | None,
    actor: CurrentUser | None,
    source: AuditSource | None,
) -> None:
    for row in _live_assignments(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        account_id=account_id,
    ):
        _soft_delete_assignment(
            db,
            row,
            actor_id=actor_id,
            actor=actor,
            source=source,
        )


def _soft_delete_assignment(
    db: Session,
    row: UserRole,
    *,
    actor_id: str | None,
    actor: CurrentUser | None,
    source: AuditSource | None,
) -> None:
    deleted_by = actor_id or row.created_by
    if deleted_by is None:
        conflict("AUTH_ROLE", "Cannot revoke a role assignment without deleted_by")
    before = row_snapshot(row)
    now = _utc_naive_now()
    row.is_active = False
    row.is_deleted = True
    row.deleted_at = now
    row.deleted_by = deleted_by
    row.updated_at = now
    row.updated_by = deleted_by
    db.add(row)
    audit_soft_delete(
        db,
        entity=row,
        schema_name="auth",
        table_name="user_role",
        before=before,
        actor=actor,
        source=source,
        tenant_id=row.tenant_id,
        account_id=row.account_id,
    )
