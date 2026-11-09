"""Tenant-scoped RBAC assignment routes (JWT tenant + owner/admin membership)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from mtf.audit.api.deps import get_audit_source
from mtf.audit.service import AuditSource
from mtf.auth.schemas.role import RoleRead, RoleUpdate, TenantRoleCreate
from mtf.auth.schemas.role_permission import RolePermissionCreate, RolePermissionRead
from mtf.auth.schemas.role_report import RoleReportCreate, RoleReportRead, RoleReportUpdate
from mtf.auth.schemas.user_role import UserRoleCreate, UserRoleRead
from mtf.auth.services.permission_resolver import PermissionResolver
from mtf.auth.services.role_report import RoleReportService
from mtf.auth.services.tenant_role import TenantRoleService
from mtf.auth.services.user_role import UserRoleService
from mtf.shared.deps import CurrentUser, get_db, get_permission_resolver, get_tenant_id
from mtf.tenant.api.tenant_staff import require_owner_or_admin

router = APIRouter(tags=["tenant-rbac"])


def get_tenant_role_service(db: Session = Depends(get_db)) -> TenantRoleService:
    return TenantRoleService(db)


def get_user_role_service(db: Session = Depends(get_db)) -> UserRoleService:
    return UserRoleService(db)


def get_role_report_service(db: Session = Depends(get_db)) -> RoleReportService:
    return RoleReportService(db)


@router.get("/roles", response_model=list[RoleRead])
def list_tenant_roles(
    skip: int = 0,
    limit: int = 100,
    tenant_id: str = Depends(get_tenant_id),
    _current_user: CurrentUser = Depends(require_owner_or_admin),
    service: TenantRoleService = Depends(get_tenant_role_service),
) -> list[RoleRead]:
    return service.list_roles(tenant_id, skip=skip, limit=limit)


@router.post("/roles", response_model=RoleRead, status_code=status.HTTP_201_CREATED)
def create_tenant_role(
    payload: TenantRoleCreate,
    tenant_id: str = Depends(get_tenant_id),
    current_user: CurrentUser = Depends(require_owner_or_admin),
    source: AuditSource = Depends(get_audit_source),
    service: TenantRoleService = Depends(get_tenant_role_service),
) -> RoleRead:
    return service.create(
        tenant_id,
        payload,
        created_by=current_user.user_id,
        actor=current_user,
        source=source,
    )


@router.get("/roles/{role_id}", response_model=RoleRead)
def get_tenant_role(
    role_id: str,
    tenant_id: str = Depends(get_tenant_id),
    _current_user: CurrentUser = Depends(require_owner_or_admin),
    service: TenantRoleService = Depends(get_tenant_role_service),
) -> RoleRead:
    return service.get(tenant_id, role_id)


@router.patch("/roles/{role_id}", response_model=RoleRead)
def update_tenant_role(
    role_id: str,
    payload: RoleUpdate,
    tenant_id: str = Depends(get_tenant_id),
    current_user: CurrentUser = Depends(require_owner_or_admin),
    source: AuditSource = Depends(get_audit_source),
    service: TenantRoleService = Depends(get_tenant_role_service),
) -> RoleRead:
    return service.update(
        tenant_id,
        role_id,
        payload,
        updated_by=current_user.user_id,
        actor=current_user,
        source=source,
    )


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tenant_role(
    role_id: str,
    tenant_id: str = Depends(get_tenant_id),
    current_user: CurrentUser = Depends(require_owner_or_admin),
    source: AuditSource = Depends(get_audit_source),
    service: TenantRoleService = Depends(get_tenant_role_service),
) -> Response:
    service.soft_delete(
        tenant_id,
        role_id,
        deleted_by=current_user.user_id,
        actor=current_user,
        source=source,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/roles/{role_id}/permissions", response_model=list[RolePermissionRead])
def list_tenant_role_permissions(
    role_id: str,
    skip: int = 0,
    limit: int = 100,
    tenant_id: str = Depends(get_tenant_id),
    _current_user: CurrentUser = Depends(require_owner_or_admin),
    service: TenantRoleService = Depends(get_tenant_role_service),
) -> list[RolePermissionRead]:
    return service.list_permissions(tenant_id, role_id, skip=skip, limit=limit)


@router.post(
    "/roles/{role_id}/permissions",
    response_model=RolePermissionRead,
    status_code=status.HTTP_201_CREATED,
)
def grant_tenant_role_permission(
    role_id: str,
    payload: RolePermissionCreate,
    tenant_id: str = Depends(get_tenant_id),
    current_user: CurrentUser = Depends(require_owner_or_admin),
    source: AuditSource = Depends(get_audit_source),
    resolver: PermissionResolver = Depends(get_permission_resolver),
    service: TenantRoleService = Depends(get_tenant_role_service),
) -> RolePermissionRead:
    return service.grant_permission(
        tenant_id,
        role_id,
        payload,
        resolver=resolver,
        actor=current_user,
        created_by=current_user.user_id,
        source=source,
    )


@router.delete(
    "/roles/{role_id}/permissions/{permission_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_tenant_role_permission(
    role_id: str,
    permission_id: str,
    tenant_id: str = Depends(get_tenant_id),
    current_user: CurrentUser = Depends(require_owner_or_admin),
    source: AuditSource = Depends(get_audit_source),
    service: TenantRoleService = Depends(get_tenant_role_service),
) -> Response:
    service.revoke_permission(
        tenant_id,
        role_id,
        permission_id,
        deleted_by=current_user.user_id,
        actor=current_user,
        source=source,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/roles/{role_id}/reports", response_model=list[RoleReportRead])
def list_tenant_role_reports(
    role_id: str,
    skip: int = 0,
    limit: int = 100,
    tenant_id: str = Depends(get_tenant_id),
    _current_user: CurrentUser = Depends(require_owner_or_admin),
    service: RoleReportService = Depends(get_role_report_service),
) -> list[RoleReportRead]:
    return service.list_for_role(tenant_id, role_id, skip=skip, limit=limit)


@router.post(
    "/roles/{role_id}/reports",
    response_model=RoleReportRead,
    status_code=status.HTTP_201_CREATED,
)
def create_tenant_role_report(
    role_id: str,
    payload: RoleReportCreate,
    tenant_id: str = Depends(get_tenant_id),
    current_user: CurrentUser = Depends(require_owner_or_admin),
    source: AuditSource = Depends(get_audit_source),
    resolver: PermissionResolver = Depends(get_permission_resolver),
    service: RoleReportService = Depends(get_role_report_service),
) -> RoleReportRead:
    return service.create(
        tenant_id,
        role_id,
        payload,
        resolver=resolver,
        actor=current_user,
        created_by=current_user.user_id,
        source=source,
    )


@router.patch("/roles/{role_id}/reports/{report_id}", response_model=RoleReportRead)
def update_tenant_role_report(
    role_id: str,
    report_id: str,
    payload: RoleReportUpdate,
    tenant_id: str = Depends(get_tenant_id),
    current_user: CurrentUser = Depends(require_owner_or_admin),
    source: AuditSource = Depends(get_audit_source),
    resolver: PermissionResolver = Depends(get_permission_resolver),
    service: RoleReportService = Depends(get_role_report_service),
) -> RoleReportRead:
    return service.update(
        tenant_id,
        role_id,
        report_id,
        payload,
        resolver=resolver,
        actor=current_user,
        updated_by=current_user.user_id,
        source=source,
    )


@router.delete(
    "/roles/{role_id}/reports/{report_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_tenant_role_report(
    role_id: str,
    report_id: str,
    tenant_id: str = Depends(get_tenant_id),
    current_user: CurrentUser = Depends(require_owner_or_admin),
    source: AuditSource = Depends(get_audit_source),
    service: RoleReportService = Depends(get_role_report_service),
) -> Response:
    service.soft_delete(
        tenant_id,
        role_id,
        report_id,
        deleted_by=current_user.user_id,
        actor=current_user,
        source=source,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/users/{user_id}/roles", response_model=list[UserRoleRead])
def list_tenant_user_roles(
    user_id: str,
    skip: int = 0,
    limit: int = 100,
    tenant_id: str = Depends(get_tenant_id),
    _current_user: CurrentUser = Depends(require_owner_or_admin),
    service: UserRoleService = Depends(get_user_role_service),
) -> list[UserRoleRead]:
    return service.list_for_user(tenant_id, user_id, skip=skip, limit=limit)


@router.post(
    "/users/{user_id}/roles",
    response_model=UserRoleRead,
    status_code=status.HTTP_201_CREATED,
)
def assign_tenant_user_role(
    user_id: str,
    payload: UserRoleCreate,
    tenant_id: str = Depends(get_tenant_id),
    current_user: CurrentUser = Depends(require_owner_or_admin),
    source: AuditSource = Depends(get_audit_source),
    resolver: PermissionResolver = Depends(get_permission_resolver),
    service: UserRoleService = Depends(get_user_role_service),
) -> UserRoleRead:
    return service.create(
        tenant_id,
        user_id,
        payload,
        resolver=resolver,
        actor=current_user,
        created_by=current_user.user_id,
        source=source,
    )


@router.delete(
    "/users/{user_id}/roles/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_tenant_user_role(
    user_id: str,
    role_id: str,
    tenant_id: str = Depends(get_tenant_id),
    current_user: CurrentUser = Depends(require_owner_or_admin),
    source: AuditSource = Depends(get_audit_source),
    service: UserRoleService = Depends(get_user_role_service),
) -> Response:
    service.soft_delete(
        tenant_id,
        user_id,
        role_id,
        deleted_by=current_user.user_id,
        actor=current_user,
        source=source,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
