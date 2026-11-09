"""HTTP API — txn domain (mounted at ``/api`` in ``main``).

Product backends import ``require_screen_permission`` from ``mtf.txn.api.deps``.
When the tenant has RBAC grants for the screen, that helper checks
``screen.{key}.{action}`` only; otherwise it falls back to ``txn.screen_permission``.
"""

from fastapi import APIRouter

from mtf.txn.api.deps import require_screen_permission
from mtf.txn.api.screen import router as screen_router

router = APIRouter()
router.include_router(screen_router)

__all__ = ["require_screen_permission", "router"]
