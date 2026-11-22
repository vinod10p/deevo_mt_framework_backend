"""Nav catalog routes — ``GET /api/nav/modules`` and module items."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from mtf.auth.services.permission_resolver import PermissionResolver
from mtf.nav.schemas import NavModuleItemsRead, NavModuleListRead
from mtf.nav.services import NavMenuService
from mtf.shared.deps import CurrentUser, get_current_user, get_db, get_permission_resolver

router = APIRouter(prefix="/nav", tags=["nav"])


def get_nav_menu_service(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
    resolver: PermissionResolver = Depends(get_permission_resolver),
) -> NavMenuService:
    return NavMenuService(db, user, resolver=resolver)


@router.get("/modules", response_model=NavModuleListRead)
def list_modules(
    service: NavMenuService = Depends(get_nav_menu_service),
) -> NavModuleListRead:
    return service.list_modules()


@router.get("/modules/{module_code}/items", response_model=NavModuleItemsRead)
def get_module_items(
    module_code: str,
    service: NavMenuService = Depends(get_nav_menu_service),
) -> NavModuleItemsRead:
    return service.get_module_items(module_code)
