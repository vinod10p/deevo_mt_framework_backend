"""HTTP API — txn domain (mounted at ``/api`` in ``main``).

Product backends import ``require_screen_permission`` from ``mtf.txn.api.deps``.
"""

from fastapi import APIRouter

from mtf.txn.api.deps import require_screen_permission
from mtf.txn.api.screen import router as screen_router

router = APIRouter()
router.include_router(screen_router)

__all__ = ["require_screen_permission", "router"]
