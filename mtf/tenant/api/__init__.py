"""HTTP API — tenant domain (mount in `app.main`).

Aggregate one ``APIRouter`` per entity module (e.g. ``tenant.py``).
"""

from fastapi import APIRouter

from mtf.tenant.api.tenant import router as tenant_entity_router
from mtf.tenant.api.tenant_account import router as tenant_account_router
from mtf.tenant.api.tenant_rbac import router as tenant_rbac_router
from mtf.tenant.api.tenant_staff import router as tenant_staff_router

router = APIRouter()
# Static paths before ``/{tenant_id}`` and ``/accounts``.
router.include_router(tenant_staff_router)
router.include_router(tenant_rbac_router)
router.include_router(tenant_account_router)
router.include_router(tenant_entity_router)

__all__ = ["router"]
