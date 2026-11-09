"""HTTP routes — login, refresh, logout (JWT auth flows).

``app.main`` mounts the auth router at ``/api/auth``. This module adds routes
``/login``, ``/refresh``, etc., so full URLs are ``/api/auth/login``,
``/api/auth/refresh``, …

Do **not** set ``prefix="/auth"`` on this router — that would duplicate the
segment already applied in ``main`` (``/api/auth/auth/login``).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from mtf.audit.api.deps import get_audit_source
from mtf.audit.service import AuditSource
from mtf.auth.schemas import UserMeRead
from mtf.auth.schemas.session import LoginRequest, RefreshRequest, TokenResponse
from mtf.auth.services import TenantAccountUserService, TenantUserService, UserService
from mtf.auth.services.me import me_rbac_fields
from mtf.auth.services.permission_resolver import PermissionResolver
from mtf.auth.services.session_service import SessionService
from mtf.shared.deps import (
    CurrentUser,
    get_current_user,
    get_db,
    get_permission_resolver,
)
from mtf.shared.exceptions import forbidden, unauthorized

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
    )


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
