"""Screen gates: RBAC when ``rbac.screens=on``, else ``txn.screen_permission``.

Not both-must-pass. Product routes keep calling ``require_screen_permission``.
The per-tenant flag is one-way (backfill / onboarding). Empty grants deny.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from mtf.auth.services.permission_resolver import Actor, PermissionResolver
from mtf.shared.exceptions import forbidden
from mtf.tenant.services.rbac_screens import tenant_has_screen_rbac
from mtf.txn.models.screen import Screen
from mtf.txn.services.screen_permission import (
    ScreenEffectivePermissions,
    ScreenOperation,
    ScreenPermissionService,
)

#: ``txn.screen_permission`` operation → ``auth.permission.action``.
SCREEN_OPERATION_ACTIONS: dict[ScreenOperation, str] = {
    "view": "view",
    "add": "create",
    "edit": "update",
    "delete": "delete",
}


def screen_permission_code(screen_key: str, operation: ScreenOperation) -> str:
    return f"screen.{screen_key}.{SCREEN_OPERATION_ACTIONS[operation]}"


def tenant_uses_screen_rbac(
    db: Session,
    tenant_id: str,
    screen_key: str | None = None,
) -> bool:
    """True when this tenant has live ``rbac.screens = on``.

    ``screen_key`` is ignored: the switch is tenant-wide, not per screen.
    """
    del screen_key
    return tenant_has_screen_rbac(db, tenant_id)


class ScreenAccessService:
    """One instance per request — memoizes the RBAC-vs-legacy choice per tenant."""

    def __init__(
        self,
        db: Session,
        *,
        resolver: PermissionResolver | None = None,
        legacy: ScreenPermissionService | None = None,
    ) -> None:
        self._db = db
        self._resolver = resolver or PermissionResolver(db)
        self._legacy = legacy or ScreenPermissionService(db)
        self._uses_rbac: dict[str, bool] = {}

    def uses_rbac(self, tenant_id: str, screen_key: str | None = None) -> bool:
        del screen_key
        cached = self._uses_rbac.get(tenant_id)
        if cached is not None:
            return cached
        flag = tenant_uses_screen_rbac(self._db, tenant_id)
        self._uses_rbac[tenant_id] = flag
        return flag

    def _rbac_permissions(self, user: Actor, screen_key: str) -> ScreenEffectivePermissions:
        codes = self._resolver.permission_codes(user)
        return ScreenEffectivePermissions(
            can_view=f"screen.{screen_key}.view" in codes,
            can_add=f"screen.{screen_key}.create" in codes,
            can_edit=f"screen.{screen_key}.update" in codes,
            can_delete=f"screen.{screen_key}.delete" in codes,
        )

    def resolve(self, user: Actor, screen_key: str) -> ScreenEffectivePermissions:
        tenant_id = user.tenant_id
        if tenant_id is None:
            forbidden("AUTH", "Tenant context required")
        if self.uses_rbac(tenant_id, screen_key):
            return self._rbac_permissions(user, screen_key)
        return self._legacy.resolve(tenant_id, user.user_id, screen_key)

    def resolve_with_screen(
        self,
        user: Actor,
        screen_key: str,
    ) -> tuple[Screen, ScreenEffectivePermissions]:
        tenant_id = user.tenant_id
        if tenant_id is None:
            forbidden("AUTH", "Tenant context required")
        screen = self._legacy.get_live_screen(screen_key)
        if self.uses_rbac(tenant_id, screen_key):
            return screen, self._rbac_permissions(user, screen_key)
        return screen, self._legacy.resolve_for_screen(tenant_id, user.user_id, screen)

    def require(
        self,
        user: Actor,
        screen_key: str,
        operation: ScreenOperation,
    ) -> ScreenEffectivePermissions:
        perms = self.resolve(user, screen_key)
        if perms.allows(operation):
            return perms
        tenant_id = user.tenant_id
        if tenant_id is not None and self.uses_rbac(tenant_id, screen_key):
            forbidden("AUTH", "Insufficient permissions")
        forbidden("SCREEN", "Insufficient permissions")
