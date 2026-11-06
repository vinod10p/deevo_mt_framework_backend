"""HTTP routes — ``auth.app_user`` (User) resource."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from mtf.audit.api.deps import get_audit_source
from mtf.audit.service import AuditSource
from mtf.auth.schemas import UserCreate, UserRead, UserUpdate
from mtf.auth.services import UserService
from mtf.shared.deps import CurrentUser, get_db, require_scope

router = APIRouter()


def get_user_service(db: Session = Depends(get_db)) -> UserService:
    return UserService(db)


@router.get("/users", response_model=list[UserRead])
def list_users(
    skip: int = 0,
    limit: int = 100,
    _current_user: CurrentUser = Depends(require_scope("system")),
    service: UserService = Depends(get_user_service),
) -> list[UserRead]:
    return service.list_users(skip=skip, limit=limit)


@router.post("/users", response_model=UserRead, status_code=201)
def create_user(
    payload: UserCreate,
    current_user: CurrentUser = Depends(require_scope("system")),
    source: AuditSource = Depends(get_audit_source),
    service: UserService = Depends(get_user_service),
) -> UserRead:
    return service.create_user(payload, actor=current_user, source=source)


@router.get("/users/{user_id}", response_model=UserRead)
def get_user(
    user_id: str,
    _current_user: CurrentUser = Depends(require_scope("system")),
    service: UserService = Depends(get_user_service),
) -> UserRead:
    user = service.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail={"code": "USER_NOT_FOUND", "message": "User not found"})
    return user


@router.patch("/users/{user_id}", response_model=UserRead)
def update_user(
    user_id: str,
    payload: UserUpdate,
    current_user: CurrentUser = Depends(require_scope("system")),
    source: AuditSource = Depends(get_audit_source),
    service: UserService = Depends(get_user_service),
) -> UserRead:
    return service.update_user(
        user_id,
        payload,
        updated_by=current_user.user_id,
        actor=current_user,
        source=source,
    )
