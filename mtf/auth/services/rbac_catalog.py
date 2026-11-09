"""Shared helpers for system catalog CRUD (step 8)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mtf.auth.models.permission import Permission
from mtf.auth.models.role import Role
from mtf.rpt.models.report_definition import ReportDefinition
from mtf.shared.db_integrity import is_unique_constraint_violation
from mtf.shared.exceptions import bad_request, conflict, not_found


def utc_naive_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def compose_permission_code(resource_type: str, resource_code: str, action: str) -> str:
    """``<resource_type>.<resource_code>.<action>`` — ``resource_code`` may contain dots."""
    return f"{resource_type}.{resource_code}.{action}"


def require_live_permission(db: Session, permission_id: str) -> Permission:
    row = db.scalars(
        select(Permission).where(
            Permission.id == permission_id,
            Permission.is_deleted == False,  # noqa: E712
        )
    ).first()
    if row is None:
        not_found("AUTH_PERMISSION", "Permission not found")
    return row


def require_platform_role(db: Session, role_id: str) -> Role:
    """Live platform role (``tenant_id`` NULL). Tenant-owned roles 404 here — step 9."""
    row = db.scalars(
        select(Role).where(
            Role.id == role_id,
            Role.tenant_id.is_(None),
            Role.is_deleted == False,  # noqa: E712
        )
    ).first()
    if row is None:
        not_found("AUTH_ROLE", "Platform role not found")
    return row


def require_template_role(db: Session, role_id: str) -> Role:
    """Platform role whose defaults are copied into tenants (not ``system_admin``)."""
    role = require_platform_role(db, role_id)
    if role.user_scope not in ("tenant", "tenant_account"):
        bad_request(
            "AUTH_DEFAULT_ROLE_REPORT",
            "Default report grants apply only to tenant or account template roles",
        )
    return role


def require_platform_report(db: Session, report_id: str) -> ReportDefinition:
    row = db.scalars(
        select(ReportDefinition).where(
            ReportDefinition.id == report_id,
            ReportDefinition.is_deleted == False,  # noqa: E712
        )
    ).first()
    if row is None:
        not_found("REPORT", "Report not found")
    if row.scope_type != "system" or row.tenant_id is not None:
        bad_request(
            "AUTH_DEFAULT_ROLE_REPORT",
            "Default report grants require a platform-wide report",
        )
    return row


def require_export_needs_view(
    *,
    can_view: bool,
    can_export: bool,
    code_prefix: str = "AUTH_DEFAULT_ROLE_REPORT",
) -> None:
    if can_export and not can_view:
        bad_request(code_prefix, "can_export requires can_view")


def apply_soft_delete(row: object, *, deleted_by: str) -> datetime:
    now = utc_naive_now()
    row.is_active = False  # type: ignore[attr-defined]
    row.is_deleted = True  # type: ignore[attr-defined]
    row.deleted_at = now  # type: ignore[attr-defined]
    row.deleted_by = deleted_by  # type: ignore[attr-defined]
    row.updated_at = now  # type: ignore[attr-defined]
    row.updated_by = deleted_by  # type: ignore[attr-defined]
    return now


def commit_or_conflict(db: Session, *, code_prefix: str, message: str) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if is_unique_constraint_violation(exc):
            conflict(code_prefix, message)
        raise
