"""Tenant assignment helpers: assignable roles, escalation, last-admin."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import Select, and_, or_, select
from sqlalchemy.orm import Session

from mtf.auth.models.permission import Permission
from mtf.auth.models.role import Role
from mtf.auth.models.role_permission import RolePermission
from mtf.auth.models.tenant_user import TenantUser
from mtf.auth.models.user import User
from mtf.auth.models.user_role import UserRole
from mtf.auth.services.permission_resolver import Actor, PermissionResolver
from mtf.rpt.models.report_definition import ReportDefinition
from mtf.shared.exceptions import conflict, forbidden, not_found

#: Last-admin means at least one tenant staff user holds this catalog code.
ADMIN_PERMISSION_CODE = "api.auth.role.update"


def assignable_role_filter(tenant_id: str) -> object:
    """Tenant-owned custom roles plus platform tenant templates."""
    return or_(
        and_(Role.tenant_id == tenant_id, Role.is_system == False),  # noqa: E712
        and_(
            Role.tenant_id.is_(None),
            Role.is_system == True,  # noqa: E712
            Role.user_scope == "tenant",
        ),
    )


def require_assignable_role(db: Session, tenant_id: str, role_id: str) -> Role:
    row = db.scalars(
        select(Role).where(
            Role.id == role_id,
            Role.is_deleted == False,  # noqa: E712
            assignable_role_filter(tenant_id),
        )
    ).first()
    if row is None:
        not_found("AUTH_ROLE", "Role not found")
    return row


def require_tenant_owned_role(db: Session, tenant_id: str, role_id: str) -> Role:
    row = db.scalars(
        select(Role).where(
            Role.id == role_id,
            Role.is_deleted == False,  # noqa: E712
        )
    ).first()
    if row is None:
        not_found("AUTH_ROLE", "Role not found")
    if row.tenant_id is None or row.is_system:
        forbidden("AUTH_ROLE", "Cannot edit a platform role")
    if row.tenant_id != tenant_id:
        not_found("AUTH_ROLE", "Role not found")
    return row


def require_active_tenant_membership(db: Session, tenant_id: str, user_id: str) -> TenantUser:
    row = db.scalars(
        select(TenantUser).where(
            TenantUser.tenant_id == tenant_id,
            TenantUser.user_id == user_id,
            TenantUser.is_active == True,  # noqa: E712
            TenantUser.is_deleted == False,  # noqa: E712
        )
    ).first()
    if row is None:
        not_found("TENANT_USER", "Membership not found")
    return row


def require_tenant_staff_user(db: Session, user_id: str) -> User:
    user = db.scalars(
        select(User).where(
            User.id == user_id,
            User.is_deleted == False,  # noqa: E712
        )
    ).first()
    if user is None:
        not_found("USER", "User not found")
    if user.user_scope != "tenant":
        not_found("TENANT_USER", "Membership not found")
    return user


def require_tenant_report(db: Session, tenant_id: str, report_id: str) -> ReportDefinition:
    row = db.scalars(
        select(ReportDefinition).where(
            ReportDefinition.id == report_id,
            ReportDefinition.is_deleted == False,  # noqa: E712
        )
    ).first()
    if row is None:
        not_found("REPORT", "Report not found")
    platform = row.scope_type == "system" and row.tenant_id is None
    owned = row.tenant_id == tenant_id
    if not platform and not owned:
        not_found("REPORT", "Report not found")
    return row


def permission_codes_for_role(db: Session, role_id: str) -> list[str]:
    return list(
        db.scalars(
            select(Permission.code).join(
                RolePermission,
                RolePermission.permission_id == Permission.id,
            ).where(
                RolePermission.role_id == role_id,
                RolePermission.is_active == True,  # noqa: E712
                RolePermission.is_deleted == False,  # noqa: E712
                Permission.is_active == True,  # noqa: E712
                Permission.is_deleted == False,  # noqa: E712
            )
        ).all()
    )


def assert_no_escalation(
    resolver: PermissionResolver,
    actor: Actor,
    codes: Iterable[str],
) -> None:
    held = resolver.permission_codes(actor)
    missing = sorted({code for code in codes if code not in held})
    if missing:
        forbidden("AUTH_ROLE", "Cannot grant a permission you do not hold")


def assert_report_escalation(
    resolver: PermissionResolver,
    actor: Actor,
    report_id: str,
    *,
    can_view: bool,
    can_export: bool,
) -> None:
    grant = resolver.report_grants(actor).get(report_id)
    if can_view and (grant is None or not grant.can_view):
        forbidden("AUTH_ROLE", "Cannot grant report access you do not hold")
    if can_export and (grant is None or not grant.can_export):
        forbidden("AUTH_ROLE", "Cannot grant report access you do not hold")


def _admin_assignment_stmt(tenant_id: str) -> Select[tuple[str, str]]:
    """Lock live tenant-staff assignments that currently confer last-admin."""
    return (
        select(UserRole.user_id, UserRole.role_id)
        .join(Role, Role.id == UserRole.role_id)
        .join(RolePermission, RolePermission.role_id == Role.id)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .where(
            UserRole.tenant_id == tenant_id,
            UserRole.account_id.is_(None),
            UserRole.is_active == True,  # noqa: E712
            UserRole.is_deleted == False,  # noqa: E712
            Role.is_active == True,  # noqa: E712
            Role.is_deleted == False,  # noqa: E712
            RolePermission.is_active == True,  # noqa: E712
            RolePermission.is_deleted == False,  # noqa: E712
            Permission.is_active == True,  # noqa: E712
            Permission.is_deleted == False,  # noqa: E712
            Permission.code == ADMIN_PERMISSION_CODE,
        )
        .with_hint(UserRole, "WITH (UPDLOCK, HOLDLOCK)", dialect_name="mssql")
    )


def admin_assignment_pairs(db: Session, tenant_id: str) -> list[tuple[str, str]]:
    rows = db.execute(_admin_assignment_stmt(tenant_id)).all()
    return [(user_id, role_id) for user_id, role_id in rows]


def assert_not_last_admin(
    db: Session,
    tenant_id: str,
    *,
    drop_user_id: str | None = None,
    drop_role_id: str | None = None,
) -> None:
    """409 if the planned drop would leave the tenant with no ``api.auth.role.update`` holder.

    Locks matching ``user_role`` rows with ``UPDLOCK, HOLDLOCK`` in the same transaction.
    """
    remaining: set[str] = set()
    for user_id, role_id in admin_assignment_pairs(db, tenant_id):
        if drop_user_id is not None and drop_role_id is not None:
            if user_id == drop_user_id and role_id == drop_role_id:
                continue
        elif drop_role_id is not None:
            if role_id == drop_role_id:
                continue
        elif drop_user_id is not None:
            if user_id == drop_user_id:
                continue
        remaining.add(user_id)
    if not remaining:
        conflict("AUTH_ROLE", "Cannot remove the last admin from the tenant")
