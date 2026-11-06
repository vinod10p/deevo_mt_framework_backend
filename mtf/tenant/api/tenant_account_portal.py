"""Account portal routes for deevo_account (``user_scope=tenant_account``)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from mtf.audit.api.deps import get_audit_source
from mtf.audit.service import AuditSource
from mtf.auth.models.tenant_account_user import TenantAccountUser
from mtf.auth.services.tenant_account_user import TenantAccountUserService
from mtf.shared.deps import (
    CurrentUser,
    get_account_id,
    get_db,
    get_tenant_id_portal,
    require_portal_account_admin,
    require_scope,
)
from mtf.shared.exceptions import forbidden, not_found
from mtf.tenant.schemas import (
    TenantAccountUserCreate,
    TenantAccountUserRead,
    TenantAccountUserUpdate,
)

router = APIRouter(tags=["account-portal"])

# Module-level checker so tests can ``app.dependency_overrides[require_account_admin]``.
require_account_admin = require_portal_account_admin()


def get_tenant_account_user_service(db: Session = Depends(get_db)) -> TenantAccountUserService:
    return TenantAccountUserService(db)


def _require_active_membership(
    service: TenantAccountUserService,
    tenant_id: str,
    account_id: str,
    user_id: str,
) -> TenantAccountUser:
    membership = service.get_membership(tenant_id, account_id, user_id)
    if membership is None or not membership.is_active:
        not_found("TENANT_ACCOUNT_USER", "Membership not found")
    return membership


@router.get("/users", response_model=list[TenantAccountUserRead])
def list_account_portal_users(
    skip: int = 0,
    limit: int = 100,
    tenant_id: str = Depends(get_tenant_id_portal),
    account_id: str = Depends(get_account_id),
    current_user: CurrentUser = Depends(require_scope("tenant_account")),
    service: TenantAccountUserService = Depends(get_tenant_account_user_service),
) -> list[TenantAccountUserRead]:
    _require_active_membership(service, tenant_id, account_id, current_user.user_id)
    return service.list_details_by_account(tenant_id, account_id, skip=skip, limit=limit)


@router.get("/users/{user_id}", response_model=TenantAccountUserRead)
def get_account_portal_user(
    user_id: str,
    tenant_id: str = Depends(get_tenant_id_portal),
    account_id: str = Depends(get_account_id),
    current_user: CurrentUser = Depends(require_scope("tenant_account")),
    service: TenantAccountUserService = Depends(get_tenant_account_user_service),
) -> TenantAccountUserRead:
    _require_active_membership(service, tenant_id, account_id, current_user.user_id)
    return service.get_detail_for_account(tenant_id, account_id, user_id)


@router.post("/users", response_model=TenantAccountUserRead, status_code=status.HTTP_201_CREATED)
def create_account_portal_user(
    payload: TenantAccountUserCreate,
    tenant_id: str = Depends(get_tenant_id_portal),
    account_id: str = Depends(get_account_id),
    current_user: CurrentUser = Depends(require_account_admin),
    source: AuditSource = Depends(get_audit_source),
    service: TenantAccountUserService = Depends(get_tenant_account_user_service),
) -> TenantAccountUserRead:
    return service.create_for_account(
        tenant_id,
        account_id,
        payload,
        created_by=current_user.user_id,
        actor=current_user,
        source=source,
    )


@router.patch("/users/{user_id}", response_model=TenantAccountUserRead)
def update_account_portal_user(
    user_id: str,
    payload: TenantAccountUserUpdate,
    tenant_id: str = Depends(get_tenant_id_portal),
    account_id: str = Depends(get_account_id),
    current_user: CurrentUser = Depends(require_scope("tenant_account")),
    source: AuditSource = Depends(get_audit_source),
    service: TenantAccountUserService = Depends(get_tenant_account_user_service),
) -> TenantAccountUserRead:
    membership = service.get_membership(tenant_id, account_id, current_user.user_id)
    if membership is None:
        not_found("TENANT_ACCOUNT_USER", "Membership not found")
    if membership.role != "admin" and current_user.user_id != user_id:
        forbidden("AUTH", "Insufficient permissions")
    return service.update_for_account(
        tenant_id,
        account_id,
        user_id,
        payload,
        updated_by=current_user.user_id,
        actor_membership=membership if current_user.user_id == user_id else None,
        actor=current_user,
        source=source,
    )


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account_portal_user(
    user_id: str,
    tenant_id: str = Depends(get_tenant_id_portal),
    account_id: str = Depends(get_account_id),
    current_user: CurrentUser = Depends(require_account_admin),
    source: AuditSource = Depends(get_audit_source),
    service: TenantAccountUserService = Depends(get_tenant_account_user_service),
) -> Response:
    service.soft_delete_for_account(
        tenant_id,
        account_id,
        user_id,
        deleted_by=current_user.user_id,
        actor=current_user,
        source=source,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
