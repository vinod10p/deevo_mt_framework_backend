"""HTTP API — auth domain (mount in `app.main`).

Aggregate one ``APIRouter`` per entity module (e.g. ``app_user.py``). For a single
router, re-export it here; for multiple entities, compose with ``include_router``.
"""

from fastapi import APIRouter

from mtf.auth.api.app_user import router as app_user_router
from mtf.auth.api.default_role_report import router as default_role_report_router
from mtf.auth.api.permission import router as permission_router
from mtf.auth.api.role import router as role_router
from mtf.auth.api.role_permission import router as role_permission_router
from mtf.auth.api.session import router as session_router
from mtf.auth.api.tenant_user import router as tenant_user_router

router = APIRouter()
router.include_router(session_router)
router.include_router(app_user_router)
router.include_router(tenant_user_router)
router.include_router(permission_router)
router.include_router(role_permission_router)
router.include_router(default_role_report_router)
router.include_router(role_router)

__all__ = ["router"]
