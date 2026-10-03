"""HTTP API — rpt domain (mounted at ``/api`` in ``main``).

Aggregate one ``APIRouter`` per entity module. Entity routers carry their own prefix
(e.g. ``/reports``) because FastAPI rejects an empty prefix plus an empty route path.
"""

from fastapi import APIRouter

from mtf.rpt.api.report import router as report_router

router = APIRouter()
router.include_router(report_router)

__all__ = ["router"]
