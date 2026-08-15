"""HTTP routes — ``tenant.tenant`` resource."""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from mtf.auth.services import TenantAccountUserService, TenantUserService
from mtf.shared.deps import CurrentUser, PaginationParams, get_db, get_pagination, require_scope
from mtf.shared.exceptions import raise_if_not_found
from mtf.tenant.schemas import (
    MailboxCreate,
    MailboxRead,
    MailboxUpdate,
    TenantAccountAddressCreate,
    TenantAccountAddressRead,
    TenantAccountAddressUpdate,
    TenantAccountCreate,
    TenantAccountListResponse,
    TenantAccountRead,
    TenantAccountUpdate,
    TenantAccountUserCreate,
    TenantAccountUserRead,
    TenantAccountUserUpdate,
    TenantCreate,
    TenantRead,
    TenantSubdomainRead,
    TenantUpdate,
    TenantUserCreate,
    TenantUserRead,
    TenantUserUpdate,
)
from mtf.tenant.services import (
    MailboxService,
    TenantAccountAddressService,
    TenantAccountService,
    TenantService,
)

router = APIRouter()


def get_mailbox_service(db: Session = Depends(get_db)) -> MailboxService:
    return MailboxService(db)


def get_tenant_service(db: Session = Depends(get_db)) -> TenantService:
    return TenantService(db)


def get_tenant_user_service(db: Session = Depends(get_db)) -> TenantUserService:
    return TenantUserService(db)


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


@router.get("/by-subdomain", response_model=TenantSubdomainRead)
def get_tenant_by_subdomain(
    subdomain: str = Query(..., description="Tenant subdomain slug"),
    service: TenantService = Depends(get_tenant_service),
) -> TenantSubdomainRead:
    tenant = service.get_by_subdomain(subdomain)
    raise_if_not_found(tenant, "TENANT_TENANT", "Tenant not found")

    if not tenant.is_active or tenant.status in (
        "suspended",
        "cancelled",
        "expired",
    ):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "TENANT_INACTIVE",
                "message": "This tenant is not available.",
            },
        )

    return TenantSubdomainRead(
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        subdomain=tenant.subdomain,
        is_active=tenant.is_active,
    )


@router.get("/by-id", response_model=TenantSubdomainRead)
def get_tenant_by_id(
    tenant_id: str = Query(..., description="Tenant primary key (ULID)"),
    service: TenantService = Depends(get_tenant_service),
) -> TenantSubdomainRead:
    """Public lookup for deevo_account login pages (tenant id in URL)."""
    tenant = service.get_tenant(tenant_id)
    raise_if_not_found(tenant, "TENANT_TENANT", "Tenant not found")

    if not tenant.is_active or tenant.status in (
        "suspended",
        "cancelled",
        "expired",
    ):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "TENANT_INACTIVE",
                "message": "This tenant is not available.",
            },
        )

    return TenantSubdomainRead(
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        subdomain=tenant.subdomain,
        is_active=tenant.is_active,
    )


@router.get("/", response_model=list[TenantRead])
def list_tenants(
    skip: int = 0,
    limit: int = 100,
    _current_user: CurrentUser = Depends(require_scope("system")),
    service: TenantService = Depends(get_tenant_service),
) -> list[TenantRead]:
    return service.list_tenants(skip=skip, limit=limit)


@router.get("/{tenant_id}", response_model=TenantRead)
def get_tenant(
    tenant_id: str,
    _current_user: CurrentUser = Depends(require_scope("system")),
    service: TenantService = Depends(get_tenant_service),
) -> TenantRead:
    return service.require_tenant(tenant_id)


@router.post("/", response_model=TenantRead, status_code=status.HTTP_201_CREATED)
def create_tenant(
    payload: TenantCreate,
    current_user: CurrentUser = Depends(require_scope("system")),
    service: TenantService = Depends(get_tenant_service),
) -> TenantRead:
    return service.create_tenant(payload, created_by=current_user.user_id)


@router.patch("/{tenant_id}", response_model=TenantRead)
def update_tenant(
    tenant_id: str,
    payload: TenantUpdate,
    current_user: CurrentUser = Depends(require_scope("system")),
    service: TenantService = Depends(get_tenant_service),
) -> TenantRead:
    return service.update_tenant(tenant_id, payload, updated_by=current_user.user_id)


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tenant(
    tenant_id: str,
    current_user: CurrentUser = Depends(require_scope("system")),
    service: TenantService = Depends(get_tenant_service),
) -> Response:
    service.soft_delete_tenant(tenant_id, deleted_by=current_user.user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{tenant_id}/users", response_model=list[TenantUserRead])
def list_tenant_users(
    tenant_id: str,
    skip: int = 0,
    limit: int = 100,
    _current_user: CurrentUser = Depends(require_scope("system")),
    service: TenantUserService = Depends(get_tenant_user_service),
) -> list[TenantUserRead]:
    return service.list_details_by_tenant(tenant_id, skip=skip, limit=limit)


@router.post("/{tenant_id}/users", response_model=TenantUserRead, status_code=status.HTTP_201_CREATED)
def create_tenant_user(
    tenant_id: str,
    payload: TenantUserCreate,
    current_user: CurrentUser = Depends(require_scope("system")),
    service: TenantUserService = Depends(get_tenant_user_service),
) -> TenantUserRead:
    return service.create_for_tenant(tenant_id, payload, created_by=current_user.user_id)


@router.patch("/{tenant_id}/users/{user_id}", response_model=TenantUserRead)
def update_tenant_user(
    tenant_id: str,
    user_id: str,
    payload: TenantUserUpdate,
    current_user: CurrentUser = Depends(require_scope("system")),
    service: TenantUserService = Depends(get_tenant_user_service),
) -> TenantUserRead:
    return service.update_for_tenant(
        tenant_id,
        user_id,
        payload,
        updated_by=current_user.user_id,
    )


@router.delete("/{tenant_id}/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tenant_user(
    tenant_id: str,
    user_id: str,
    current_user: CurrentUser = Depends(require_scope("system")),
    service: TenantUserService = Depends(get_tenant_user_service),
) -> Response:
    service.soft_delete_for_tenant(tenant_id, user_id, deleted_by=current_user.user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{tenant_id}/mailboxes", response_model=list[MailboxRead])
def list_tenant_mailboxes(
    tenant_id: str,
    skip: int = 0,
    limit: int = 100,
    _current_user: CurrentUser = Depends(require_scope("system")),
    service: MailboxService = Depends(get_mailbox_service),
) -> list[MailboxRead]:
    return service.list_by_tenant(tenant_id, skip=skip, limit=limit)


@router.post("/{tenant_id}/mailboxes", response_model=MailboxRead, status_code=status.HTTP_201_CREATED)
def create_tenant_mailbox(
    tenant_id: str,
    payload: MailboxCreate,
    current_user: CurrentUser = Depends(require_scope("system")),
    service: MailboxService = Depends(get_mailbox_service),
) -> MailboxRead:
    return service.create_for_tenant(tenant_id, payload, created_by=current_user.user_id)


@router.patch("/{tenant_id}/mailboxes/{mailbox_id}", response_model=MailboxRead)
def update_tenant_mailbox(
    tenant_id: str,
    mailbox_id: str,
    payload: MailboxUpdate,
    current_user: CurrentUser = Depends(require_scope("system")),
    service: MailboxService = Depends(get_mailbox_service),
) -> MailboxRead:
    mb = service.update_for_tenant(tenant_id, mailbox_id, payload, updated_by=current_user.user_id)
    if not mb:
        raise HTTPException(status_code=404, detail={"code": "MAILBOX_NOT_FOUND", "message": "Mailbox not found"})
    return mb


@router.delete("/{tenant_id}/mailboxes/{mailbox_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tenant_mailbox(
    tenant_id: str,
    mailbox_id: str,
    current_user: CurrentUser = Depends(require_scope("system")),
    service: MailboxService = Depends(get_mailbox_service),
) -> Response:
    success = service.delete_for_tenant(tenant_id, mailbox_id, deleted_by=current_user.user_id)
    if not success:
        raise HTTPException(status_code=404, detail={"code": "MAILBOX_NOT_FOUND", "message": "Mailbox not found"})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/mailboxes/callback")
def mailbox_oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
    service: MailboxService = Depends(get_mailbox_service),
) -> RedirectResponse:
    import base64
    import json

    try:
        state_decoded = base64.urlsafe_b64decode(state.encode()).decode()
        state_dict = json.loads(state_decoded)
        tenant_id = state_dict.get("tenant_id")
        mailbox_id = state_dict.get("mailbox_id")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid state parameter")

    if not tenant_id or not mailbox_id:
        raise HTTPException(status_code=400, detail="State missing required fields")

    cred = service.process_oauth_callback(tenant_id, mailbox_id, code)
    if not cred:
        raise HTTPException(status_code=400, detail="Failed to verify mailbox and exchange tokens")

    # Redirect to Streamlit frontend Verification page
    frontend_url = "http://localhost:8001/verification"
    return RedirectResponse(url=frontend_url)




@router.get("/{tenant_id}/mailboxes/{mailbox_id}/authorize")
def authorize_mailbox_oauth(
    tenant_id: str,
    mailbox_id: str,
    service: MailboxService = Depends(get_mailbox_service),
) -> RedirectResponse:
    mailbox = service.get_by_id(tenant_id, mailbox_id)
    if not mailbox:
        raise HTTPException(status_code=404, detail="Mailbox not found")

    auth_url = service.get_authorization_url(tenant_id, mailbox_id)
    return RedirectResponse(url=auth_url)


@router.post(
    "/{tenant_id}/accounts",
    response_model=TenantAccountRead,
    status_code=status.HTTP_201_CREATED,
)
def create_tenant_account(
    tenant_id: str,
    payload: TenantAccountCreate,
    current_user: CurrentUser = Depends(require_scope("system")),
    service: TenantAccountService = Depends(get_tenant_account_service),
) -> TenantAccountRead:
    return service.create(payload, tenant_id, created_by=current_user.user_id)


@router.get("/{tenant_id}/accounts", response_model=TenantAccountListResponse)
def list_tenant_accounts(
    tenant_id: str,
    pagination: PaginationParams = Depends(get_pagination),
    account_status: str | None = Query(None, alias="status"),
    account_type: str | None = Query(None),
    search: str | None = Query(None),
    _current_user: CurrentUser = Depends(require_scope("system")),
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


@router.get("/{tenant_id}/accounts/{account_id}", response_model=TenantAccountRead)
def get_tenant_account(
    tenant_id: str,
    account_id: str,
    _current_user: CurrentUser = Depends(require_scope("system")),
    service: TenantAccountService = Depends(get_tenant_account_service),
) -> TenantAccountRead:
    return service.get_by_id(account_id, tenant_id)


@router.patch("/{tenant_id}/accounts/{account_id}", response_model=TenantAccountRead)
def update_tenant_account(
    tenant_id: str,
    account_id: str,
    payload: TenantAccountUpdate,
    current_user: CurrentUser = Depends(require_scope("system")),
    service: TenantAccountService = Depends(get_tenant_account_service),
) -> TenantAccountRead:
    return service.update(account_id, tenant_id, payload, updated_by=current_user.user_id)


@router.delete("/{tenant_id}/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tenant_account(
    tenant_id: str,
    account_id: str,
    current_user: CurrentUser = Depends(require_scope("system")),
    service: TenantAccountService = Depends(get_tenant_account_service),
) -> Response:
    service.soft_delete(account_id, tenant_id, deleted_by=current_user.user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{tenant_id}/accounts/{account_id}/users", response_model=list[TenantAccountUserRead])
def list_tenant_account_users(
    tenant_id: str,
    account_id: str,
    skip: int = 0,
    limit: int = 100,
    _current_user: CurrentUser = Depends(require_scope("system")),
    service: TenantAccountUserService = Depends(get_tenant_account_user_service),
) -> list[TenantAccountUserRead]:
    return service.list_details_by_account(tenant_id, account_id, skip=skip, limit=limit)


@router.post(
    "/{tenant_id}/accounts/{account_id}/users",
    response_model=TenantAccountUserRead,
    status_code=status.HTTP_201_CREATED,
)
def create_tenant_account_user(
    tenant_id: str,
    account_id: str,
    payload: TenantAccountUserCreate,
    current_user: CurrentUser = Depends(require_scope("system")),
    service: TenantAccountUserService = Depends(get_tenant_account_user_service),
) -> TenantAccountUserRead:
    return service.create_for_account(
        tenant_id,
        account_id,
        payload,
        created_by=current_user.user_id,
    )


@router.patch(
    "/{tenant_id}/accounts/{account_id}/users/{user_id}",
    response_model=TenantAccountUserRead,
)
def update_tenant_account_user(
    tenant_id: str,
    account_id: str,
    user_id: str,
    payload: TenantAccountUserUpdate,
    current_user: CurrentUser = Depends(require_scope("system")),
    service: TenantAccountUserService = Depends(get_tenant_account_user_service),
) -> TenantAccountUserRead:
    return service.update_for_account(
        tenant_id,
        account_id,
        user_id,
        payload,
        updated_by=current_user.user_id,
    )


@router.delete(
    "/{tenant_id}/accounts/{account_id}/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_tenant_account_user(
    tenant_id: str,
    account_id: str,
    user_id: str,
    current_user: CurrentUser = Depends(require_scope("system")),
    service: TenantAccountUserService = Depends(get_tenant_account_user_service),
) -> Response:
    service.soft_delete_for_account(
        tenant_id,
        account_id,
        user_id,
        deleted_by=current_user.user_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{tenant_id}/accounts/{account_id}/addresses",
    response_model=TenantAccountAddressRead,
    status_code=status.HTTP_201_CREATED,
)
def create_tenant_account_address(
    tenant_id: str,
    account_id: str,
    payload: TenantAccountAddressCreate,
    current_user: CurrentUser = Depends(require_scope("system")),
    service: TenantAccountAddressService = Depends(get_tenant_account_address_service),
) -> TenantAccountAddressRead:
    return service.create(tenant_id, account_id, payload, created_by=current_user.user_id)


@router.get(
    "/{tenant_id}/accounts/{account_id}/addresses",
    response_model=list[TenantAccountAddressRead],
)
def list_tenant_account_addresses(
    tenant_id: str,
    account_id: str,
    pagination: PaginationParams = Depends(get_pagination),
    _current_user: CurrentUser = Depends(require_scope("system")),
    service: TenantAccountAddressService = Depends(get_tenant_account_address_service),
) -> list[TenantAccountAddressRead]:
    return service.list_addresses(
        tenant_id,
        account_id,
        skip=pagination.skip,
        limit=pagination.limit,
    )


@router.get(
    "/{tenant_id}/accounts/{account_id}/addresses/{address_id}",
    response_model=TenantAccountAddressRead,
)
def get_tenant_account_address(
    tenant_id: str,
    account_id: str,
    address_id: str,
    _current_user: CurrentUser = Depends(require_scope("system")),
    service: TenantAccountAddressService = Depends(get_tenant_account_address_service),
) -> TenantAccountAddressRead:
    return service.get_by_id(tenant_id, account_id, address_id)


@router.patch(
    "/{tenant_id}/accounts/{account_id}/addresses/{address_id}",
    response_model=TenantAccountAddressRead,
)
def update_tenant_account_address(
    tenant_id: str,
    account_id: str,
    address_id: str,
    payload: TenantAccountAddressUpdate,
    current_user: CurrentUser = Depends(require_scope("system")),
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
    "/{tenant_id}/accounts/{account_id}/addresses/{address_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_tenant_account_address(
    tenant_id: str,
    account_id: str,
    address_id: str,
    current_user: CurrentUser = Depends(require_scope("system")),
    service: TenantAccountAddressService = Depends(get_tenant_account_address_service),
) -> Response:
    service.soft_delete(
        tenant_id,
        account_id,
        address_id,
        deleted_by=current_user.user_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
