"""HTTP routes — ``auth.tenant_user`` (tenant membership)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from mtf.auth.schemas import TenantMembershipCreate, TenantMembershipRead, TenantMembershipUpdate
from mtf.auth.services import TenantUserService
from mtf.shared.deps import CurrentUser, get_db, require_scope
from mtf.shared.exceptions import bad_request, raise_if_not_found

router = APIRouter()


def get_tenant_user_service(db: Session = Depends(get_db)) -> TenantUserService:
    return TenantUserService(db)


@router.get("/tenant-users", response_model=list[TenantMembershipRead])
def list_tenant_users(
    tenant_id: str | None = Query(
        default=None,
        description="Return memberships for this tenant (mutually exclusive with user_id).",
    ),
    user_id: str | None = Query(
        default=None,
        description="Return memberships for this app user (mutually exclusive with tenant_id).",
    ),
    skip: int = 0,
    limit: int = 100,
    _current_user: CurrentUser = Depends(require_scope("system")),
    service: TenantUserService = Depends(get_tenant_user_service),
) -> list[TenantUserRead]:
    if (tenant_id is None) == (user_id is None):
        bad_request("TENANT_USER", "Specify exactly one of tenant_id or user_id")
    if tenant_id is not None:
        return service.list_by_tenant(tenant_id, skip=skip, limit=limit)
    return service.list_by_user(user_id, skip=skip, limit=limit)


@router.get("/tenant-users/{tenant_user_id}", response_model=TenantMembershipRead)
def get_tenant_user(
    tenant_user_id: str,
    _current_user: CurrentUser = Depends(require_scope("system")),
    service: TenantUserService = Depends(get_tenant_user_service),
) -> TenantUserRead:
    row = service.get(tenant_user_id)
    raise_if_not_found(row, "TENANT_USER", "Membership not found")
    return row


@router.post("/tenant-users", response_model=TenantMembershipRead, status_code=status.HTTP_201_CREATED)
def create_tenant_user(
    payload: TenantMembershipCreate,
    _current_user: CurrentUser = Depends(require_scope("system")),
    service: TenantUserService = Depends(get_tenant_user_service),
) -> TenantUserRead:
    return service.create(payload)


@router.patch("/tenant-users/{tenant_user_id}", response_model=TenantMembershipRead)
def update_tenant_user(
    tenant_user_id: str,
    payload: TenantMembershipUpdate,
    _current_user: CurrentUser = Depends(require_scope("system")),
    service: TenantUserService = Depends(get_tenant_user_service),
) -> TenantUserRead:
    return service.update(tenant_user_id, payload)


@router.delete("/tenant-users/{tenant_user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tenant_user(
    tenant_user_id: str,
    _current_user: CurrentUser = Depends(require_scope("system")),
    service: TenantUserService = Depends(get_tenant_user_service),
) -> Response:
    service.soft_delete(tenant_user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
