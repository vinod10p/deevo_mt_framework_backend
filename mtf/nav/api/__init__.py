"""HTTP API — nav domain (mounted at ``/api`` in ``main``)."""

from fastapi import APIRouter

from mtf.nav.api.menu import router as menu_router

router = APIRouter()
router.include_router(menu_router)

__all__ = ["router"]
