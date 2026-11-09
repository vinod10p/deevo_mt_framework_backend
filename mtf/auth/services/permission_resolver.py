"""Load effective permission codes and report grants for one caller.

Permission codes are not in the JWT. This service runs one query per kind
(codes, report grants) and memoizes the result on the instance — FastAPI
reuses one instance per request via ``get_permission_resolver``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import Select, and_, select
from sqlalchemy.orm import Session

from mtf.auth.models.permission import Permission
from mtf.auth.models.role import Role
from mtf.auth.models.role_permission import RolePermission
from mtf.auth.models.role_report import RoleReport
from mtf.auth.models.tenant_account_user import TenantAccountUser
from mtf.auth.models.tenant_user import TenantUser
from mtf.auth.models.user_role import UserRole


class Actor(Protocol):
    """``CurrentUser`` (and test doubles) — identity only, no JWT claims for grants."""

    user_id: str
    user_scope: str
    tenant_id: str | None
    account_id: str | None


@dataclass(frozen=True)
class ReportGrant:
    """Combined ``can_view`` / ``can_export`` for one report after OR-ing roles."""

    report_id: str
    can_view: bool
    can_export: bool


_ActorKey = tuple[str, str, str | None, str | None]


def _actor_key(user: Actor) -> _ActorKey:
    return (user.user_scope, user.user_id, user.tenant_id, user.account_id)


class PermissionResolver:
    """Effective grants for one database session (one HTTP request)."""

    def __init__(self, db: Session) -> None:
        self._db = db
        self._codes: dict[_ActorKey, frozenset[str]] = {}
        self._reports: dict[_ActorKey, dict[str, ReportGrant]] = {}

    def permission_codes(self, user: Actor) -> frozenset[str]:
        key = _actor_key(user)
        cached = self._codes.get(key)
        if cached is not None:
            return cached
        codes = self._load_codes(user)
        self._codes[key] = codes
        return codes

    def has_permission(self, user: Actor, code: str) -> bool:
        return code in self.permission_codes(user)

    def report_grants(self, user: Actor) -> dict[str, ReportGrant]:
        key = _actor_key(user)
        cached = self._reports.get(key)
        if cached is not None:
            return cached
        grants = self._load_report_grants(user)
        self._reports[key] = grants
        return grants

    def _load_codes(self, user: Actor) -> frozenset[str]:
        role_ids = self._role_ids_stmt(user)
        if role_ids is None:
            return frozenset()
        stmt = (
            select(Permission.code)
            .distinct()
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(
                RolePermission.role_id.in_(role_ids),
                RolePermission.is_active == True,  # noqa: E712
                RolePermission.is_deleted == False,  # noqa: E712
                Permission.is_active == True,  # noqa: E712
                Permission.is_deleted == False,  # noqa: E712
            )
        )
        return frozenset(self._db.scalars(stmt).all())

    def _load_report_grants(self, user: Actor) -> dict[str, ReportGrant]:
        if user.user_scope == "system" or user.tenant_id is None:
            return {}
        role_ids = self._role_ids_stmt(user)
        if role_ids is None:
            return {}
        stmt = select(RoleReport.report_id, RoleReport.can_view, RoleReport.can_export).where(
            RoleReport.role_id.in_(role_ids),
            RoleReport.tenant_id == user.tenant_id,
            RoleReport.is_active == True,  # noqa: E712
            RoleReport.is_deleted == False,  # noqa: E712
        )
        merged: dict[str, ReportGrant] = {}
        for report_id, can_view, can_export in self._db.execute(stmt).all():
            previous = merged.get(report_id)
            view = bool(can_view) or (previous.can_view if previous else False)
            export = bool(can_export) or (previous.can_export if previous else False)
            merged[report_id] = ReportGrant(
                report_id=report_id,
                can_view=view,
                can_export=export and view,
            )
        return merged

    def _role_ids_stmt(self, user: Actor) -> Select[tuple[str]] | None:
        if user.user_scope == "system":
            return (
                select(UserRole.role_id)
                .join(Role, Role.id == UserRole.role_id)
                .where(
                    UserRole.user_id == user.user_id,
                    UserRole.tenant_id.is_(None),
                    UserRole.account_id.is_(None),
                    UserRole.is_active == True,  # noqa: E712
                    UserRole.is_deleted == False,  # noqa: E712
                    Role.is_active == True,  # noqa: E712
                    Role.is_deleted == False,  # noqa: E712
                )
            )
        if user.user_scope == "tenant":
            if user.tenant_id is None:
                return None
            return (
                select(UserRole.role_id)
                .join(
                    TenantUser,
                    and_(
                        TenantUser.user_id == UserRole.user_id,
                        TenantUser.tenant_id == UserRole.tenant_id,
                        TenantUser.is_active == True,  # noqa: E712
                        TenantUser.is_deleted == False,  # noqa: E712
                    ),
                )
                .join(Role, Role.id == UserRole.role_id)
                .where(
                    UserRole.user_id == user.user_id,
                    UserRole.tenant_id == user.tenant_id,
                    UserRole.account_id.is_(None),
                    UserRole.is_active == True,  # noqa: E712
                    UserRole.is_deleted == False,  # noqa: E712
                    Role.is_active == True,  # noqa: E712
                    Role.is_deleted == False,  # noqa: E712
                )
            )
        if user.user_scope == "tenant_account":
            if user.tenant_id is None or user.account_id is None:
                return None
            return (
                select(UserRole.role_id)
                .join(
                    TenantAccountUser,
                    and_(
                        TenantAccountUser.user_id == UserRole.user_id,
                        TenantAccountUser.tenant_id == UserRole.tenant_id,
                        TenantAccountUser.account_id == UserRole.account_id,
                        TenantAccountUser.is_active == True,  # noqa: E712
                        TenantAccountUser.is_deleted == False,  # noqa: E712
                    ),
                )
                .join(Role, Role.id == UserRole.role_id)
                .where(
                    UserRole.user_id == user.user_id,
                    UserRole.tenant_id == user.tenant_id,
                    UserRole.account_id == user.account_id,
                    UserRole.is_active == True,  # noqa: E712
                    UserRole.is_deleted == False,  # noqa: E712
                    Role.is_active == True,  # noqa: E712
                    Role.is_deleted == False,  # noqa: E712
                )
            )
        return None
