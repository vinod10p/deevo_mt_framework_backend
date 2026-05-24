"""Tenant-scoped staff routes for deevo_crm (``user_scope=tenant``)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from mtf.auth.services import TenantUserService
from mtf.shared.deps import (
    CurrentUser,
    get_db,
    get_tenant_id,
    require_scope,
    require_tenant_role,
)
from mtf.tenant.schemas import TenantRead, TenantUserCreate, TenantUserRead, TenantUserUpdate
from mtf.tenant.services import TenantService

router = APIRouter(tags=["tenant-staff"])

# Module-level checker so tests can ``app.dependency_overrides[require_owner_or_admin]``.
require_owner_or_admin = require_tenant_role("owner", "admin")


def get_tenant_service(db: Session = Depends(get_db)) -> TenantService:
    return TenantService(db)


def get_tenant_user_service(db: Session = Depends(get_db)) -> TenantUserService:
    return TenantUserService(db)


@router.get("/me", response_model=TenantRead)
def get_current_tenant(
    tenant_id: str = Depends(get_tenant_id),
    _user: CurrentUser = Depends(require_scope("tenant")),
    service: TenantService = Depends(get_tenant_service),
) -> TenantRead:
    return service.require_tenant(tenant_id)


@router.get("/users", response_model=list[TenantUserRead])
def list_tenant_staff(
    skip: int = 0,
    limit: int = 100,
    tenant_id: str = Depends(get_tenant_id),
    _user: CurrentUser = Depends(require_scope("tenant")),
    service: TenantUserService = Depends(get_tenant_user_service),
) -> list[TenantUserRead]:
    return service.list_details_by_tenant(tenant_id, skip=skip, limit=limit)


@router.get("/users/{user_id}", response_model=TenantUserRead)
def get_tenant_staff(
    user_id: str,
    tenant_id: str = Depends(get_tenant_id),
    _user: CurrentUser = Depends(require_scope("tenant")),
    service: TenantUserService = Depends(get_tenant_user_service),
) -> TenantUserRead:
    return service.get_detail_for_tenant(tenant_id, user_id)


@router.post("/users", response_model=TenantUserRead, status_code=status.HTTP_201_CREATED)
def create_tenant_staff(
    payload: TenantUserCreate,
    tenant_id: str = Depends(get_tenant_id),
    current_user: CurrentUser = Depends(require_owner_or_admin),
    service: TenantUserService = Depends(get_tenant_user_service),
) -> TenantUserRead:
    service.assert_can_manage_users(tenant_id, current_user.user_id)
    return service.create_for_tenant(tenant_id, payload, created_by=current_user.user_id)


@router.patch("/users/{user_id}", response_model=TenantUserRead)
def update_tenant_staff(
    user_id: str,
    payload: TenantUserUpdate,
    tenant_id: str = Depends(get_tenant_id),
    current_user: CurrentUser = Depends(require_scope("tenant")),
    service: TenantUserService = Depends(get_tenant_user_service),
) -> TenantUserRead:
    actor = service.get_membership(tenant_id, current_user.user_id)
    if actor is None:
        from mtf.shared.exceptions import not_found

        not_found("TENANT_USER", "Membership not found")

    if current_user.user_id == user_id:
        return service.update_for_tenant(
            tenant_id,
            user_id,
            payload,
            updated_by=current_user.user_id,
            actor_membership=actor,
        )

    service.assert_can_manage_users(tenant_id, current_user.user_id)
    return service.update_for_tenant(
        tenant_id,
        user_id,
        payload,
        updated_by=current_user.user_id,
    )


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tenant_staff(
    user_id: str,
    tenant_id: str = Depends(get_tenant_id),
    current_user: CurrentUser = Depends(require_owner_or_admin),
    service: TenantUserService = Depends(get_tenant_user_service),
) -> Response:
    service.assert_can_manage_users(tenant_id, current_user.user_id)
    service.soft_delete_for_tenant(tenant_id, user_id, deleted_by=current_user.user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
