"""Saved-view role rules — the single hook to swap for real RBAC later.

* ``user`` views: any ``tenant`` or ``tenant_account`` user, on their own views only.
* ``tenant`` views: tenant staff (``user_scope = tenant``) whose ``auth.tenant_user.role``
  is ``owner`` or ``admin``.
* ``system`` views: never through the API in V1 — authored by SQL script.
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from mtf.auth.models.tenant_user import TenantUser
from mtf.rpt.models import ReportSavedView
from mtf.shared.deps import CurrentUser
from mtf.shared.exceptions import forbidden

ViewAction = Literal[
    "report.view.manage_user",
    "report.view.manage_tenant",
    "report.view.manage_system",
]

MANAGE_ACTION_BY_SCOPE: dict[str, ViewAction] = {
    "user": "report.view.manage_user",
    "tenant": "report.view.manage_tenant",
    "system": "report.view.manage_system",
}

_TENANT_VIEW_ROLES = frozenset({"owner", "admin"})


class ReportViewAuthorizer:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._tenant_roles: dict[tuple[str, str], str | None] = {}

    def is_allowed(self, user: CurrentUser, action: ViewAction) -> bool:
        if user.tenant_id is None:
            return False
        if action == "report.view.manage_user":
            return user.user_scope in ("tenant", "tenant_account")
        if action == "report.view.manage_tenant":
            return (
                user.user_scope == "tenant"
                and self._tenant_role(user.tenant_id, user.user_id) in _TENANT_VIEW_ROLES
            )
        return False

    def authorize(self, user: CurrentUser, action: ViewAction) -> None:
        """Raise ``403 AUTH_FORBIDDEN`` unless ``user`` may perform ``action``."""
        if not self.is_allowed(user, action):
            forbidden("AUTH", "Not allowed to manage these saved views")

    def authorize_edit(self, user: CurrentUser, view: ReportSavedView) -> None:
        """Raise ``403 AUTH_FORBIDDEN`` unless ``user`` may update or delete ``view``."""
        if not self.can_edit(user, view):
            forbidden("AUTH", "Not allowed to manage these saved views")

    def can_edit(self, user: CurrentUser, view: ReportSavedView) -> bool:
        """Whether ``user`` may update or delete this (already visible) view."""
        if view.scope_type == "user" and view.user_id != user.user_id:
            return False
        if view.scope_type != "system" and view.tenant_id != user.tenant_id:
            return False
        action = MANAGE_ACTION_BY_SCOPE.get(view.scope_type)
        return action is not None and self.is_allowed(user, action)

    def _tenant_role(self, tenant_id: str, user_id: str) -> str | None:
        key = (tenant_id, user_id)
        if key not in self._tenant_roles:
            stmt = (
                select(TenantUser.role)
                .where(
                    TenantUser.tenant_id == tenant_id,
                    TenantUser.user_id == user_id,
                    TenantUser.is_deleted == False,  # noqa: E712
                    TenantUser.is_active == True,  # noqa: E712
                )
                .limit(1)
            )
            self._tenant_roles[key] = self._db.scalars(stmt).first()
        return self._tenant_roles[key]
