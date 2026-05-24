"""HTTP routes — tenant accounts, addresses, and account users (JWT tenant scope)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from mtf.auth.services.tenant_account_user import TenantAccountUserService
from mtf.shared.deps import (
    CurrentUser,
    PaginationParams,
    get_db,
    get_pagination,
    get_tenant_id,
    require_scope,
)
from mtf.tenant.api.tenant_staff import require_owner_or_admin
from mtf.tenant.schemas.tenant_account import (
    TenantAccountCreate,
    TenantAccountListResponse,
    TenantAccountRead,
    TenantAccountUpdate,
)
from mtf.tenant.schemas.tenant_account_address import (
    TenantAccountAddressCreate,
    TenantAccountAddressRead,
    TenantAccountAddressUpdate,
)
from mtf.tenant.schemas.tenant_account_user import (
    TenantAccountUserCreate,
    TenantAccountUserRead,
    TenantAccountUserUpdate,
)
from mtf.tenant.services.tenant_account_address_service import TenantAccountAddressService
from mtf.tenant.services.tenant_account_service import TenantAccountService

router = APIRouter(prefix="/accounts", tags=["accounts"])


def get_tenant_account_service(db: Session = Depends(get_db)) -> TenantAccountService:
    return TenantAccountService(db)


def get_tenant_account_address_service(
    db: Session = Depends(get_db),
) -> TenantAccountAddressService:
    return TenantAccountAddressService(db)


def get_tenant_account_user_service(
    db: Session = Depends(get_db),
) -> TenantAccountUserService:
    return TenantAccountUserService(db)


@router.post("", response_model=TenantAccountRead, status_code=status.HTTP_201_CREATED)
def create_account(
    payload: TenantAccountCreate,
    tenant_id: str = Depends(get_tenant_id),
    current_user: CurrentUser = Depends(require_owner_or_admin),
    service: TenantAccountService = Depends(get_tenant_account_service),
) -> TenantAccountRead:
    return service.create(payload, tenant_id, created_by=current_user.user_id)


@router.get("", response_model=TenantAccountListResponse)
def list_accounts(
    pagination: PaginationParams = Depends(get_pagination),
    account_status: str | None = Query(None, alias="status"),
    account_type: str | None = Query(None),
    search: str | None = Query(None),
    tenant_id: str = Depends(get_tenant_id),
    _scope: CurrentUser = Depends(require_scope("tenant")),
    service: TenantAccountService = Depends(get_tenant_account_service),
) -> TenantAccountListResponse:
    page = service.list_accounts(
        tenant_id,
        skip=pagination.skip,
        limit=pagination.limit,
        status=account_status,
        account_type=account_type,
        search=search,
    )
    return TenantAccountListResponse(
        items=[TenantAccountRead.model_validate(r) for r in page["items"]],
        total=page["total"],
        skip=page["skip"],
        limit=page["limit"],
    )


@router.get("/{account_id}", response_model=TenantAccountRead)
def get_account(
    account_id: str,
    tenant_id: str = Depends(get_tenant_id),
    _scope: CurrentUser = Depends(require_scope("tenant")),
    service: TenantAccountService = Depends(get_tenant_account_service),
) -> TenantAccountRead:
    return service.get_by_id(account_id, tenant_id)


@router.patch("/{account_id}", response_model=TenantAccountRead)
def update_account(
    account_id: str,
    payload: TenantAccountUpdate,
    tenant_id: str = Depends(get_tenant_id),
    current_user: CurrentUser = Depends(require_owner_or_admin),
    service: TenantAccountService = Depends(get_tenant_account_service),
) -> TenantAccountRead:
    return service.update(account_id, tenant_id, payload, updated_by=current_user.user_id)


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    account_id: str,
    tenant_id: str = Depends(get_tenant_id),
    current_user: CurrentUser = Depends(require_owner_or_admin),
    service: TenantAccountService = Depends(get_tenant_account_service),
) -> Response:
    service.soft_delete(account_id, tenant_id, deleted_by=current_user.user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{account_id}/users", response_model=list[TenantAccountUserRead])
def list_account_users(
    account_id: str,
    skip: int = 0,
    limit: int = 100,
    tenant_id: str = Depends(get_tenant_id),
    _scope: CurrentUser = Depends(require_scope("tenant")),
    service: TenantAccountUserService = Depends(get_tenant_account_user_service),
) -> list[TenantAccountUserRead]:
    return service.list_details_by_account(tenant_id, account_id, skip=skip, limit=limit)


@router.get("/{account_id}/users/{user_id}", response_model=TenantAccountUserRead)
def get_account_user(
    account_id: str,
    user_id: str,
    tenant_id: str = Depends(get_tenant_id),
    _scope: CurrentUser = Depends(require_scope("tenant")),
    service: TenantAccountUserService = Depends(get_tenant_account_user_service),
) -> TenantAccountUserRead:
    return service.get_detail_for_account(tenant_id, account_id, user_id)


@router.post(
    "/{account_id}/users",
    response_model=TenantAccountUserRead,
    status_code=status.HTTP_201_CREATED,
)
def create_account_user(
    account_id: str,
    payload: TenantAccountUserCreate,
    tenant_id: str = Depends(get_tenant_id),
    current_user: CurrentUser = Depends(require_owner_or_admin),
    service: TenantAccountUserService = Depends(get_tenant_account_user_service),
) -> TenantAccountUserRead:
    service.assert_can_manage_account_users(tenant_id, account_id, current_user.user_id)
    return service.create_for_account(
        tenant_id,
        account_id,
        payload,
        created_by=current_user.user_id,
    )


@router.patch("/{account_id}/users/{user_id}", response_model=TenantAccountUserRead)
def update_account_user(
    account_id: str,
    user_id: str,
    payload: TenantAccountUserUpdate,
    tenant_id: str = Depends(get_tenant_id),
    current_user: CurrentUser = Depends(require_owner_or_admin),
    service: TenantAccountUserService = Depends(get_tenant_account_user_service),
) -> TenantAccountUserRead:
    service.assert_can_manage_account_users(tenant_id, account_id, current_user.user_id)
    return service.update_for_account(
        tenant_id,
        account_id,
        user_id,
        payload,
        updated_by=current_user.user_id,
    )


@router.delete("/{account_id}/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account_user(
    account_id: str,
    user_id: str,
    tenant_id: str = Depends(get_tenant_id),
    current_user: CurrentUser = Depends(require_owner_or_admin),
    service: TenantAccountUserService = Depends(get_tenant_account_user_service),
) -> Response:
    service.assert_can_manage_account_users(tenant_id, account_id, current_user.user_id)
    service.soft_delete_for_account(
        tenant_id,
        account_id,
        user_id,
        deleted_by=current_user.user_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{account_id}/addresses",
    response_model=TenantAccountAddressRead,
    status_code=status.HTTP_201_CREATED,
)
def create_account_address(
    account_id: str,
    payload: TenantAccountAddressCreate,
    tenant_id: str = Depends(get_tenant_id),
    current_user: CurrentUser = Depends(require_owner_or_admin),
    service: TenantAccountAddressService = Depends(get_tenant_account_address_service),
) -> TenantAccountAddressRead:
    return service.create(tenant_id, account_id, payload, created_by=current_user.user_id)


@router.get("/{account_id}/addresses", response_model=list[TenantAccountAddressRead])
def list_account_addresses(
    account_id: str,
    pagination: PaginationParams = Depends(get_pagination),
    tenant_id: str = Depends(get_tenant_id),
    _scope: CurrentUser = Depends(require_scope("tenant")),
    service: TenantAccountAddressService = Depends(get_tenant_account_address_service),
) -> list[TenantAccountAddressRead]:
    return service.list_addresses(
        tenant_id,
        account_id,
        skip=pagination.skip,
        limit=pagination.limit,
    )


@router.get("/{account_id}/addresses/{address_id}", response_model=TenantAccountAddressRead)
def get_account_address(
    account_id: str,
    address_id: str,
    tenant_id: str = Depends(get_tenant_id),
    _scope: CurrentUser = Depends(require_scope("tenant")),
    service: TenantAccountAddressService = Depends(get_tenant_account_address_service),
) -> TenantAccountAddressRead:
    return service.get_by_id(tenant_id, account_id, address_id)


@router.patch("/{account_id}/addresses/{address_id}", response_model=TenantAccountAddressRead)
def update_account_address(
    account_id: str,
    address_id: str,
    payload: TenantAccountAddressUpdate,
    tenant_id: str = Depends(get_tenant_id),
    current_user: CurrentUser = Depends(require_owner_or_admin),
    service: TenantAccountAddressService = Depends(get_tenant_account_address_service),
) -> TenantAccountAddressRead:
    return service.update(
        tenant_id,
        account_id,
        address_id,
        payload,
        updated_by=current_user.user_id,
    )


@router.delete(
    "/{account_id}/addresses/{address_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_account_address(
    account_id: str,
    address_id: str,
    tenant_id: str = Depends(get_tenant_id),
    current_user: CurrentUser = Depends(require_owner_or_admin),
    service: TenantAccountAddressService = Depends(get_tenant_account_address_service),
) -> Response:
    service.soft_delete(
        tenant_id,
        account_id,
        address_id,
        deleted_by=current_user.user_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
