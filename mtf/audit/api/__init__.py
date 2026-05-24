"""HTTP API — audit domain (mount in `app.main`).

Aggregate one ``APIRouter`` per entity module (e.g. ``audit_log.py``).
"""

from mtf.audit.api.audit_log import router

__all__ = ["router"]
