"""FastAPI dependencies for transaction screens."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from mtf.auth.services.permission_resolver import PermissionResolver
from mtf.shared.deps import CurrentUser, get_current_user, get_db, get_permission_resolver
from mtf.shared.exceptions import forbidden
from mtf.txn.services.screen_access import ScreenAccessService
from mtf.txn.services.screen_permission import (
    ScreenEffectivePermissions,
    ScreenOperation,
    ScreenPermissionService,
)

#: ``request.state`` attribute for the per-request :class:`ScreenAccessService`.
SCREEN_ACCESS_STATE = "screen_access"

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


def get_screen_access_service(
    request: Request,
    db: Session = Depends(get_db),
    resolver: PermissionResolver = Depends(get_permission_resolver),
    legacy: ScreenPermissionService = Depends(get_screen_permission_service),
) -> ScreenAccessService:
    """One access service per request so RBAC detection is queried once."""
    existing = getattr(request.state, SCREEN_ACCESS_STATE, None)
    if isinstance(existing, ScreenAccessService):
        return existing
    service = ScreenAccessService(db, resolver=resolver, legacy=legacy)
    setattr(request.state, SCREEN_ACCESS_STATE, service)
    return service


def require_screen_permission(
    screen_key: str,
    operation: ScreenOperation,
) -> Callable[..., ScreenEffectivePermissions]:
    """Enforce one screen operation. ``screen_key`` is a product constant (e.g. ``"lead"``).

    If the tenant has RBAC grants for this screen, check ``screen.{key}.{action}``
    only (``403 AUTH_FORBIDDEN``). Otherwise fall back to ``txn.screen_permission``
    (``403 SCREEN_FORBIDDEN``). Not both-must-pass.

    Does not check ``user_scope`` — the product route adds ``require_scope`` if needed.
    Tenant comes from the JWT; a missing tenant is ``AUTH_FORBIDDEN``.
    """
    cached = _screen_permission_checkers.get((screen_key, operation))
    if cached is not None:
        return cached

    def checker(
        user: CurrentUser = Depends(get_screen_caller),
        access: ScreenAccessService = Depends(get_screen_access_service),
    ) -> ScreenEffectivePermissions:
        return access.require(user, screen_key, operation)

    _screen_permission_checkers[(screen_key, operation)] = checker
    return checker
