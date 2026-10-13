"""FastAPI dependencies for transaction screens."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends
from sqlalchemy.orm import Session

from mtf.shared.deps import CurrentUser, get_current_user, get_db
from mtf.shared.exceptions import forbidden
from mtf.txn.services.screen_permission import (
    ScreenEffectivePermissions,
    ScreenOperation,
    ScreenPermissionService,
)

_screen_permission_checkers: dict[
    tuple[str, ScreenOperation],
    Callable[..., ScreenEffectivePermissions],
] = {}


def get_screen_caller(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Authenticated caller with a tenant in the JWT. Scope is not restricted here."""
    if user.tenant_id is None:
        forbidden("AUTH", "Tenant context required")
    return user


def get_screen_permission_service(
    db: Session = Depends(get_db),
) -> ScreenPermissionService:
    return ScreenPermissionService(db)


def require_screen_permission(
    screen_key: str,
    operation: ScreenOperation,
) -> Callable[..., ScreenEffectivePermissions]:
    """Enforce one screen operation. ``screen_key`` is a product constant (e.g. ``"lead"``).

    Does not check ``user_scope`` — the product route adds ``require_scope`` if needed.
    Tenant comes from the JWT; a missing tenant is ``AUTH_FORBIDDEN``.
    """
    cached = _screen_permission_checkers.get((screen_key, operation))
    if cached is not None:
        return cached

    def checker(
        user: CurrentUser = Depends(get_screen_caller),
        service: ScreenPermissionService = Depends(get_screen_permission_service),
    ) -> ScreenEffectivePermissions:
        tenant_id = user.tenant_id
        if tenant_id is None:
            forbidden("AUTH", "Tenant context required")
        perms = service.resolve(tenant_id, user.user_id, screen_key)
        if not perms.allows(operation):
            forbidden("SCREEN", "Insufficient permissions")
        return perms

    _screen_permission_checkers[(screen_key, operation)] = checker
    return checker
