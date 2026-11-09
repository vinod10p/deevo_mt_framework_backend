"""HTTP routes — ``auth.permission`` catalog (system scope)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from mtf.audit.api.deps import get_audit_source
from mtf.audit.service import AuditSource
from mtf.auth.schemas.permission import PermissionCreate, PermissionRead, PermissionUpdate
from mtf.auth.services.permission import PermissionService
from mtf.shared.deps import CurrentUser, get_db, require_scope

router = APIRouter(tags=["auth"])


def get_permission_service(db: Session = Depends(get_db)) -> PermissionService:
    return PermissionService(db)


@router.get("/permissions", response_model=list[PermissionRead])
def list_permissions(
    skip: int = 0,
    limit: int = 100,
    user_scope: str | None = Query(default=None),
    resource_type: str | None = Query(default=None),
    _current_user: CurrentUser = Depends(require_scope("system")),
    service: PermissionService = Depends(get_permission_service),
) -> list[PermissionRead]:
    return service.list_permissions(
        skip=skip,
        limit=limit,
        user_scope=user_scope,
        resource_type=resource_type,
    )


@router.post("/permissions", response_model=PermissionRead, status_code=status.HTTP_201_CREATED)
def create_permission(
    payload: PermissionCreate,
    current_user: CurrentUser = Depends(require_scope("system")),
    source: AuditSource = Depends(get_audit_source),
    service: PermissionService = Depends(get_permission_service),
) -> PermissionRead:
    return service.create(
        payload,
        created_by=current_user.user_id,
        actor=current_user,
        source=source,
    )


@router.get("/permissions/{permission_id}", response_model=PermissionRead)
def get_permission(
    permission_id: str,
    _current_user: CurrentUser = Depends(require_scope("system")),
    service: PermissionService = Depends(get_permission_service),
) -> PermissionRead:
    return service.get(permission_id)


@router.patch("/permissions/{permission_id}", response_model=PermissionRead)
def update_permission(
    permission_id: str,
    payload: PermissionUpdate,
    current_user: CurrentUser = Depends(require_scope("system")),
    source: AuditSource = Depends(get_audit_source),
    service: PermissionService = Depends(get_permission_service),
) -> PermissionRead:
    return service.update(
        permission_id,
        payload,
        updated_by=current_user.user_id,
        actor=current_user,
        source=source,
    )


@router.delete("/permissions/{permission_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_permission(
    permission_id: str,
    current_user: CurrentUser = Depends(require_scope("system")),
    source: AuditSource = Depends(get_audit_source),
    service: PermissionService = Depends(get_permission_service),
) -> Response:
    service.soft_delete(
        permission_id,
        deleted_by=current_user.user_id,
        actor=current_user,
        source=source,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
