"""FastAPI dependencies — DB session and authentication."""

from __future__ import annotations

import hmac
from collections.abc import Callable, Generator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from fastapi import Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from mtf.auth.models.session import AuthSession
from mtf.auth.models.tenant_account_user import TenantAccountUser
from mtf.auth.models.tenant_user import TenantUser
from mtf.auth.models.user import User
from mtf.shared.database import SessionLocal
from mtf.shared.exceptions import forbidden, unauthorized
from mtf.shared.security import decode_access_token, hash_token

if TYPE_CHECKING:
    from mtf.auth.services.permission_resolver import PermissionResolver

#: ``request.state`` attribute for the per-request :class:`PermissionResolver`.
PERMISSION_RESOLVER_STATE = "permission_resolver"


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Authentication identity context
# ---------------------------------------------------------------------------

UserType = Literal["app_user", "customer_user"]
UserScope = Literal["system", "tenant", "tenant_account"]


@dataclass(frozen=True)
class CurrentUser:
    """Decoded JWT identity — passed into every protected service call."""

    user_id: str
    user_type: UserType
    user_scope: UserScope
    tenant_id: str | None
    account_id: str | None = None


http_bearer = HTTPBearer(auto_error=True)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(http_bearer),
    db: Session = Depends(get_db),
) -> CurrentUser:
    """Validate the Bearer access token against its live session and membership.

    401 unless: signature/expiry valid, ``typ="access"``, known ``user_type`` /
    ``user_scope``, ``sid`` names an active session whose current token this is, the
    user is active, and (tenant / portal scope) the membership is still active.
    """
    token = credentials.credentials
    try:
        claims = decode_access_token(token)
    except ValueError as exc:
        msg = str(exc)
        if msg == "TOKEN_EXPIRED":
            unauthorized("AUTH", "Token expired")
        unauthorized("AUTH", "Invalid token")

    user_id = claims.get("user_id")
    if not user_id or not isinstance(user_id, str):
        unauthorized("AUTH", "Invalid token")
    session_id = claims.get("sid")
    if not session_id or not isinstance(session_id, str):
        # Tokens issued before ``sid`` existed (or not by login/refresh) — client refreshes.
        unauthorized("AUTH", "Invalid token")

    # Unknown values are a malformed token — never guess a scope or type.
    user_type = claims.get("user_type")
    if user_type not in ("app_user", "customer_user"):
        unauthorized("AUTH", "Invalid token")
    user_scope = claims.get("user_scope")
    if user_scope not in ("system", "tenant", "tenant_account"):
        unauthorized("AUTH", "Invalid token")

    # One PK lookup: the session is live, this is its *current* access token (refresh
    # rotation and logout both invalidate older ones), and the user is still active.
    stmt = (
        select(AuthSession.token_hash)
        .join(User, User.id == AuthSession.user_id)
        .where(
            AuthSession.id == session_id,
            AuthSession.user_id == user_id,
            AuthSession.is_active == True,  # noqa: E712
            AuthSession.is_deleted == False,  # noqa: E712
            AuthSession.revoked_at.is_(None),
            User.is_deleted == False,  # noqa: E712
            User.is_active == True,  # noqa: E712
        )
        .limit(1)
    )
    current_hash = db.scalars(stmt).first()
    if current_hash is None or not hmac.compare_digest(current_hash, hash_token(token)):
        unauthorized("AUTH", "Session expired or revoked")

    tenant_raw = claims.get("tenant_id")
    tenant_id: str | None = tenant_raw if isinstance(tenant_raw, str) else None

    account_raw = claims.get("account_id")
    account_id: str | None = account_raw if isinstance(account_raw, str) else None

    current = CurrentUser(
        user_id=user_id,
        user_type=user_type,
        user_scope=user_scope,
        tenant_id=tenant_id,
        account_id=account_id,
    )

    # Removed / deactivated members lose access immediately, not when the JWT expires.
    if user_scope == "tenant" and tenant_id is not None:
        if tenant_membership_role(db, current) is None:
            unauthorized("AUTH", "Membership inactive")
    elif user_scope == "tenant_account" and tenant_id is not None and account_id is not None:
        if account_membership_role(db, current) is None:
            unauthorized("AUTH", "Membership inactive")

    return current


_scope_checkers: dict[UserScope, Callable[..., CurrentUser]] = {}


def require_scope(required_scope: UserScope) -> Callable[..., CurrentUser]:
    """Return a cached dependency so FastAPI reuses one JWT decode per request."""

    cached = _scope_checkers.get(required_scope)
    if cached is not None:
        return cached

    def checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.user_scope != required_scope:
            forbidden("AUTH", "Insufficient permissions")
        return user

    _scope_checkers[required_scope] = checker
    return checker


_any_scope_checkers: dict[tuple[UserScope, ...], Callable[..., CurrentUser]] = {}


def require_any_scope(*scopes: UserScope) -> Callable[..., CurrentUser]:
    """Like :func:`require_scope`, but accepts any one of ``scopes``."""
    key = tuple(sorted(set(scopes)))
    cached = _any_scope_checkers.get(key)
    if cached is not None:
        return cached

    allowed = set(key)

    def checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.user_scope not in allowed:
            forbidden("AUTH", "Insufficient permissions")
        return user

    _any_scope_checkers[key] = checker
    return checker


require_tenant_scope = require_scope("tenant")
require_system_scope = require_scope("system")


def get_tenant_id(user: CurrentUser = Depends(require_scope("tenant"))) -> str:
    """Tenant id from JWT — must not be taken from request body."""
    if user.tenant_id is None:
        forbidden("AUTH", "Tenant context required")
    return user.tenant_id


def get_tenant_id_portal(
    user: CurrentUser = Depends(require_scope("tenant_account")),
) -> str:
    """Tenant id from JWT for portal users."""
    if user.tenant_id is None:
        forbidden("AUTH", "Tenant context required")
    return user.tenant_id


def get_account_id(
    user: CurrentUser = Depends(require_scope("tenant_account")),
) -> str:
    """Account id from JWT for portal users."""
    if user.account_id is None:
        forbidden("AUTH", "Account context required")
    return user.account_id


def tenant_membership_role(db: Session, user: CurrentUser) -> str | None:
    """Role of the caller's active ``auth.tenant_user`` row for the JWT tenant, or None."""
    if user.tenant_id is None:
        return None
    stmt = (
        select(TenantUser.role)
        .where(
            TenantUser.tenant_id == user.tenant_id,
            TenantUser.user_id == user.user_id,
            TenantUser.is_deleted == False,  # noqa: E712
            TenantUser.is_active == True,  # noqa: E712
        )
        .limit(1)
    )
    return db.scalars(stmt).first()


def account_membership_role(db: Session, user: CurrentUser) -> str | None:
    """Role of the caller's active ``tenant_account_user`` row for the JWT account, or None."""
    if user.tenant_id is None or user.account_id is None:
        return None
    stmt = (
        select(TenantAccountUser.role)
        .where(
            TenantAccountUser.tenant_id == user.tenant_id,
            TenantAccountUser.account_id == user.account_id,
            TenantAccountUser.user_id == user.user_id,
            TenantAccountUser.is_deleted == False,  # noqa: E712
            TenantAccountUser.is_active == True,  # noqa: E712
        )
        .limit(1)
    )
    return db.scalars(stmt).first()


_tenant_role_checkers: dict[tuple[str, ...], Callable[..., CurrentUser]] = {}


def require_tenant_role(*roles: str) -> Callable[..., CurrentUser]:
    """Require ``user_scope=tenant`` and an active membership with one of ``roles``."""
    key = tuple(sorted(roles))
    cached = _tenant_role_checkers.get(key)
    if cached is not None:
        return cached

    allowed = set(roles)

    def checker(
        user: CurrentUser = Depends(require_scope("tenant")),
        db: Session = Depends(get_db),
    ) -> CurrentUser:
        if user.tenant_id is None:
            forbidden("AUTH", "Tenant context required")
        role = tenant_membership_role(db, user)
        if role is None or role not in allowed:
            forbidden("AUTH", "Insufficient permissions")
        return user

    _tenant_role_checkers[key] = checker
    return checker


def get_permission_resolver(
    request: Request,
    db: Session = Depends(get_db),
) -> PermissionResolver:
    """One resolver per request: stored on ``request.state`` and memoized internally."""
    from mtf.auth.services.permission_resolver import PermissionResolver

    existing = getattr(request.state, PERMISSION_RESOLVER_STATE, None)
    if isinstance(existing, PermissionResolver):
        return existing
    resolver = PermissionResolver(db)
    setattr(request.state, PERMISSION_RESOLVER_STATE, resolver)
    return resolver


_permission_checkers: dict[str, Callable[..., CurrentUser]] = {}


def require_permission(code: str) -> Callable[..., CurrentUser]:
    """Require ``code`` in the caller's request-scoped permission set.

    Does not check JWT scope — the route still adds ``require_scope`` when needed.
    Missing grant → ``403 AUTH_FORBIDDEN``.
    """
    cached = _permission_checkers.get(code)
    if cached is not None:
        return cached

    def checker(
        user: CurrentUser = Depends(get_current_user),
        resolver: PermissionResolver = Depends(get_permission_resolver),
    ) -> CurrentUser:
        if not resolver.has_permission(user, code):
            forbidden("AUTH", "Insufficient permissions")
        return user

    _permission_checkers[code] = checker
    return checker


def require_portal_account_admin() -> Callable[..., CurrentUser]:
    """Require ``user_scope=tenant_account`` and account membership ``role=admin``."""
    def checker(
        user: CurrentUser = Depends(require_scope("tenant_account")),
        db: Session = Depends(get_db),
    ) -> CurrentUser:
        if user.tenant_id is None or user.account_id is None:
            forbidden("AUTH", "Account context required")
        if account_membership_role(db, user) != "admin":
            forbidden("AUTH", "Insufficient permissions")
        return user

    return checker


# ---------------------------------------------------------------------------
# Pagination (list endpoints)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PaginationParams:
    """Offset pagination for ``.offset(skip).limit(limit)`` — see CONVENTIONS.md."""

    skip: int
    limit: int


def get_pagination(
    skip: int = Query(0, ge=0, description="Rows to skip (offset)."),
    limit: int = Query(
        100,
        ge=1,
        le=200,
        description="Max rows to return (capped at 200 per CONVENTIONS).",
    ),
) -> PaginationParams:
    """Dependency: validated ``skip`` / ``limit`` for list routes.

    Use as ``pagination: PaginationParams = Depends(get_pagination)``. FastAPI
    applies ``Query`` bounds; values are safe for SQLAlchemy ``offset`` / ``limit``.
    """
    return PaginationParams(skip=skip, limit=limit)

