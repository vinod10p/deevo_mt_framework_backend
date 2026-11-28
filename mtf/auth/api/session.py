"""HTTP routes — login, refresh, logout (JWT auth flows).

``app.main`` mounts the auth router at ``/api/auth``. This module adds routes
``/login``, ``/refresh``, etc., so full URLs are ``/api/auth/login``,
``/api/auth/refresh``, …

Do **not** set ``prefix="/auth"`` on this router — that would duplicate the
segment already applied in ``main`` (``/api/auth/auth/login``).
"""

from __future__ import annotations

from hashlib import sha256

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from mtf.audit.api.deps import get_audit_source
from mtf.audit.service import AuditSource
from mtf.auth.schemas import UserMeRead
from mtf.auth.schemas.session import (
    BrowserLogoutRequest,
    BrowserRefreshRequest,
    BrowserTokenResponse,
    BusinessUnitSwitchRequest,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
)
from mtf.auth.services import TenantAccountUserService, TenantUserService, UserService
from mtf.auth.services.me import me_business_unit_fields, me_rbac_fields
from mtf.auth.services.permission_resolver import PermissionResolver
from mtf.auth.services.session_service import SessionService
from mtf.shared.config import get_settings
from mtf.shared.deps import (
    CurrentUser,
    get_current_user,
    get_db,
    get_permission_resolver,
    require_tenant_scope,
)
from mtf.shared.exceptions import forbidden, unauthorized
from mtf.shared.security import decode_access_token, decode_refresh_token

router = APIRouter(tags=["auth"])


def get_session_service(db: Session = Depends(get_db)) -> SessionService:
    """Instantiate ``SessionService`` with the request DB session."""
    return SessionService(db)


def get_user_service(db: Session = Depends(get_db)) -> UserService:
    return UserService(db)


def get_tenant_user_service(db: Session = Depends(get_db)) -> TenantUserService:
    return TenantUserService(db)


def get_tenant_account_user_service(
    db: Session = Depends(get_db),
) -> TenantAccountUserService:
    return TenantAccountUserService(db)


def get_tenant_account_service_for_me(db: Session = Depends(get_db)):
    from mtf.tenant.services import TenantAccountService

    return TenantAccountService(db)


def _raw_access_token_from_request(request: Request) -> str:
    """Parse Bearer credential from ``Authorization`` (case-insensitive scheme).

    ``get_current_user`` already validated the header + JWT; this recovers the
    exact raw token string needed for session hash lookup.
    """
    header = request.headers.get("Authorization")
    if not header:
        unauthorized("AUTH", "Invalid token")
    parts = header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        unauthorized("AUTH", "Invalid token")
    raw = parts[1].strip()
    if not raw:
        unauthorized("AUTH", "Invalid token")
    return raw


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    source: AuditSource = Depends(get_audit_source),
    service: SessionService = Depends(get_session_service),
) -> TokenResponse:
    return service.login(payload, source=source)


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(
    payload: RefreshRequest,
    source: AuditSource = Depends(get_audit_source),
    service: SessionService = Depends(get_session_service),
) -> TokenResponse:
    return service.refresh(payload, source=source)


def _browser_cookie(request: Request) -> str:
    # The API host is shared by tenant frontends. Each allowed origin gets its
    # own cookie name so an adjacent frontend cannot exchange this credential.
    origin_hash = sha256(request.headers["Origin"].encode()).hexdigest()[:32]
    return f"__Host-deevoflow-refresh-{origin_hash}"


def _require_browser_origin(request: Request) -> None:
    # Cookie-authenticated writes require an exact allowlist match, even when
    # a request could reach the server without a CORS preflight.
    if request.headers.get("Origin") not in get_settings().allowed_origins:
        forbidden("AUTH", "Untrusted browser origin")


def _browser_tokens(
    request: Request, response: Response, tokens: TokenResponse
) -> BrowserTokenResponse:
    if tokens.user_scope not in {"tenant", "tenant_account"}:
        forbidden("AUTH", "This account cannot sign in to the tenant application")
    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(
        _browser_cookie(request),
        tokens.refresh_token,
        max_age=get_settings().jwt_refresh_token_expire_days * 86400,
        path="/",
        secure=True,
        httponly=True,
        samesite="strict",
    )
    return BrowserTokenResponse.model_validate({
        **tokens.model_dump(),
        "session_id": decode_access_token(tokens.access_token)["sid"],
    })


@router.post(
    "/browser/login",
    response_model=BrowserTokenResponse,
    dependencies=[Depends(_require_browser_origin)],
)
def browser_login(
    request: Request,
    payload: LoginRequest,
    response: Response,
    source: AuditSource = Depends(get_audit_source),
    service: SessionService = Depends(get_session_service),
) -> BrowserTokenResponse:
    return _browser_tokens(request, response, service.login(payload, source=source))


@router.post(
    "/browser/refresh",
    response_model=BrowserTokenResponse,
    dependencies=[Depends(_require_browser_origin)],
)
def browser_refresh(
    request: Request,
    response: Response,
    payload: BrowserRefreshRequest | None = None,
    source: AuditSource = Depends(get_audit_source),
    service: SessionService = Depends(get_session_service),
) -> BrowserTokenResponse:
    if payload is None:
        unauthorized("AUTH", "Invalid refresh token")
    if payload.session_id is None:
        # One-time exchange for a legacy browser with its own token in storage.
        token = payload.refresh_token
    else:
        token = request.cookies.get(_browser_cookie(request))
        if token:
            try:
                session_id = decode_refresh_token(token).get("session_id")
            except ValueError:
                unauthorized("AUTH", "Invalid refresh token")
            if session_id != payload.session_id:
                unauthorized("AUTH", "Browser session changed")
    if not token:
        unauthorized("AUTH", "Invalid refresh token")
    tokens = service.refresh(RefreshRequest(refresh_token=token), source=source)
    return _browser_tokens(request, response, tokens)


@router.post(
    "/browser/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(_require_browser_origin)],
)
def browser_logout(
    request: Request,
    response: Response,
    payload: BrowserLogoutRequest,
    source: AuditSource = Depends(get_audit_source),
    service: SessionService = Depends(get_session_service),
) -> None:
    cookie = _browser_cookie(request)
    token = request.cookies.get(cookie)
    if token and not service.logout_by_refresh(token, payload.session_id, source=source):
        forbidden("AUTH", "Browser session changed")
    response.delete_cookie(cookie, path="/", secure=True, httponly=True, samesite="strict")


@router.get("/me", response_model=UserMeRead)
def get_me(
    current_user: CurrentUser = Depends(get_current_user),
    user_service: UserService = Depends(get_user_service),
    tenant_user_service: TenantUserService = Depends(get_tenant_user_service),
    tenant_account_user_service: TenantAccountUserService = Depends(
        get_tenant_account_user_service
    ),
    tenant_account_service=Depends(get_tenant_account_service_for_me),
    resolver: PermissionResolver = Depends(get_permission_resolver),
    db: Session = Depends(get_db),
) -> UserMeRead:
    """Current user profile — system, tenant staff, or portal account user."""
    if current_user.user_scope not in ("system", "tenant", "tenant_account"):
        forbidden("AUTH", "Insufficient permissions")

    if current_user.user_scope == "tenant_account":
        if current_user.tenant_id is None or current_user.account_id is None:
            forbidden("AUTH", "Account context required")

    user = user_service.get_user(current_user.user_id)
    if user is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "USER_NOT_FOUND", "message": "User not found"},
        )

    role: str | None = None
    tenant_id = current_user.tenant_id
    account_id: str | None = None
    account_name: str | None = None
    account_code: str | None = None
    account_type: str | None = None

    if current_user.user_scope == "tenant":
        if tenant_id is None:
            forbidden("AUTH", "Tenant context required")
        membership = tenant_user_service.get_membership(tenant_id, current_user.user_id)
        if membership is None or not membership.is_active:
            forbidden("AUTH", "Tenant membership not found")
        role = membership.role
    elif current_user.user_scope == "tenant_account":
        account_id = current_user.account_id
        assert account_id is not None
        membership = tenant_account_user_service.get_membership(
            tenant_id,
            account_id,
            current_user.user_id,
        )
        if membership is None or not membership.is_active:
            forbidden("AUTH", "Account membership not found")
        role = membership.role

        account = tenant_account_service.get_by_id(account_id, tenant_id)
        account_name = account.name
        account_code = account.account_code
        account_type = account.account_type

    permissions, reports = me_rbac_fields(db, resolver, current_user)

    return UserMeRead(
        id=user.id,
        email=user.email,
        email_normalized=user.email_normalized,
        first_name=user.first_name,
        last_name=user.last_name,
        phone=user.phone,
        avatar_url=user.avatar_url,
        password_changed_at=user.password_changed_at,
        auth_provider=user.auth_provider,
        external_id=user.external_id,
        email_verified_at=user.email_verified_at,
        last_login_at=user.last_login_at,
        is_active=user.is_active,
        is_deleted=user.is_deleted,
        failed_login_count=user.failed_login_count,
        locked_until=user.locked_until,
        mfa_enabled=user.mfa_enabled,
        mfa_confirmed_at=user.mfa_confirmed_at,
        user_scope=user.user_scope,
        row_version=user.row_version,
        created_at=user.created_at,
        updated_at=user.updated_at,
        created_by=user.created_by,
        updated_by=user.updated_by,
        deleted_by=user.deleted_by,
        tenant_id=tenant_id,
        role=role,
        account_id=account_id,
        account_name=account_name,
        account_code=account_code,
        account_type=account_type,
        permissions=permissions,
        reports=reports,
        **me_business_unit_fields(db, current_user),
    )


def _switch_business_unit(
    request: Request,
    payload: BusinessUnitSwitchRequest,
    user: CurrentUser,
    source: AuditSource,
    service: SessionService,
) -> TokenResponse:
    raw_token = _raw_access_token_from_request(request)
    return service.switch_business_unit(
        raw_token, user, payload.business_unit_code, source=source
    )


@router.post("/session/business-unit", response_model=TokenResponse)
def switch_business_unit(
    request: Request,
    payload: BusinessUnitSwitchRequest,
    user: CurrentUser = Depends(require_tenant_scope),
    source: AuditSource = Depends(get_audit_source),
    service: SessionService = Depends(get_session_service),
) -> TokenResponse:
    """Move this session to another store; returns a new token pair (staff only)."""
    return _switch_business_unit(request, payload, user, source, service)


@router.post(
    "/browser/session/business-unit",
    response_model=BrowserTokenResponse,
    dependencies=[Depends(_require_browser_origin)],
)
def browser_switch_business_unit(
    request: Request,
    response: Response,
    payload: BusinessUnitSwitchRequest,
    user: CurrentUser = Depends(require_tenant_scope),
    source: AuditSource = Depends(get_audit_source),
    service: SessionService = Depends(get_session_service),
) -> BrowserTokenResponse:
    """Browser variant: the new refresh token goes into the cookie, not the body."""
    tokens = _switch_business_unit(request, payload, user, source, service)
    return _browser_tokens(request, response, tokens)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    source: AuditSource = Depends(get_audit_source),
    service: SessionService = Depends(get_session_service),
) -> None:
    raw_token = _raw_access_token_from_request(request)
    service.logout(
        raw_token,
        current_user.user_id,
        source=source,
    )


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
def logout_all(
    current_user: CurrentUser = Depends(get_current_user),
    source: AuditSource = Depends(get_audit_source),
    service: SessionService = Depends(get_session_service),
) -> None:
    service.logout_all(
        user_id=current_user.user_id,
        current_user_id=current_user.user_id,
        source=source,
    )
