"""HTTP routes — platform ``auth.role`` catalog (system scope)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from mtf.audit.api.deps import get_audit_source
from mtf.audit.service import AuditSource
from mtf.auth.schemas.role import RoleCreate, RoleRead, RoleUpdate
from mtf.auth.services.role import RoleService
from mtf.shared.deps import CurrentUser, get_db, require_scope

router = APIRouter(tags=["auth"])


def get_role_service(db: Session = Depends(get_db)) -> RoleService:
    return RoleService(db)


@router.get("/roles", response_model=list[RoleRead])
def list_roles(
    skip: int = 0,
    limit: int = 100,
    user_scope: str | None = Query(default=None),
    _current_user: CurrentUser = Depends(require_scope("system")),
    service: RoleService = Depends(get_role_service),
) -> list[RoleRead]:
    return service.list_roles(skip=skip, limit=limit, user_scope=user_scope)


@router.post("/roles", response_model=RoleRead, status_code=status.HTTP_201_CREATED)
def create_role(
    payload: RoleCreate,
    current_user: CurrentUser = Depends(require_scope("system")),
    source: AuditSource = Depends(get_audit_source),
    service: RoleService = Depends(get_role_service),
) -> RoleRead:
    return service.create(
        payload,
        created_by=current_user.user_id,
        actor=current_user,
        source=source,
    )


@router.get("/roles/{role_id}", response_model=RoleRead)
def get_role(
    role_id: str,
    _current_user: CurrentUser = Depends(require_scope("system")),
    service: RoleService = Depends(get_role_service),
) -> RoleRead:
    return service.get(role_id)


@router.patch("/roles/{role_id}", response_model=RoleRead)
def update_role(
    role_id: str,
    payload: RoleUpdate,
    current_user: CurrentUser = Depends(require_scope("system")),
    source: AuditSource = Depends(get_audit_source),
    service: RoleService = Depends(get_role_service),
) -> RoleRead:
    return service.update(
        role_id,
        payload,
        updated_by=current_user.user_id,
        actor=current_user,
        source=source,
    )


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_role(
    role_id: str,
    current_user: CurrentUser = Depends(require_scope("system")),
    source: AuditSource = Depends(get_audit_source),
    service: RoleService = Depends(get_role_service),
) -> Response:
    service.soft_delete(
        role_id,
        deleted_by=current_user.user_id,
        actor=current_user,
        source=source,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
