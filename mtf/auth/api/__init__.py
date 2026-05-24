"""HTTP API — auth domain (mount in `app.main`).

Aggregate one ``APIRouter`` per entity module (e.g. ``app_user.py``). For a single
router, re-export it here; for multiple entities, compose with ``include_router``.
"""

from fastapi import APIRouter

from mtf.auth.api.app_user import router as app_user_router
from mtf.auth.api.session import router as session_router
from mtf.auth.api.tenant_user import router as tenant_user_router

router = APIRouter()
router.include_router(session_router)
router.include_router(app_user_router)
router.include_router(tenant_user_router)

__all__ = ["router"]
