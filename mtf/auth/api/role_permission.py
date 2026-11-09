"""HTTP routes — platform ``auth.role_permission`` catalog (system scope)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from mtf.audit.api.deps import get_audit_source
from mtf.audit.service import AuditSource
from mtf.auth.schemas.role_permission import RolePermissionCreate, RolePermissionRead
from mtf.auth.services.role_permission import RolePermissionService
from mtf.shared.deps import CurrentUser, get_db, require_scope

router = APIRouter(prefix="/roles/{role_id}/permissions", tags=["auth"])


def get_role_permission_service(db: Session = Depends(get_db)) -> RolePermissionService:
    return RolePermissionService(db)


@router.get("", response_model=list[RolePermissionRead])
def list_role_permissions(
    role_id: str,
    skip: int = 0,
    limit: int = 100,
    _current_user: CurrentUser = Depends(require_scope("system")),
    service: RolePermissionService = Depends(get_role_permission_service),
) -> list[RolePermissionRead]:
    return service.list_for_role(role_id, skip=skip, limit=limit)


@router.post("", response_model=RolePermissionRead, status_code=status.HTTP_201_CREATED)
def create_role_permission(
    role_id: str,
    payload: RolePermissionCreate,
    current_user: CurrentUser = Depends(require_scope("system")),
    source: AuditSource = Depends(get_audit_source),
    service: RolePermissionService = Depends(get_role_permission_service),
) -> RolePermissionRead:
    return service.create(
        role_id,
        payload,
        created_by=current_user.user_id,
        actor=current_user,
        source=source,
    )


@router.delete("/{permission_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_role_permission(
    role_id: str,
    permission_id: str,
    current_user: CurrentUser = Depends(require_scope("system")),
    source: AuditSource = Depends(get_audit_source),
    service: RolePermissionService = Depends(get_role_permission_service),
) -> Response:
    service.soft_delete(
        role_id,
        permission_id,
        deleted_by=current_user.user_id,
        actor=current_user,
        source=source,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
