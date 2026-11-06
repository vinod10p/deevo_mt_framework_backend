"""FastAPI dependencies — audit request origin and read access."""

from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from mtf.audit.middleware import AUDIT_REQUEST_ID_STATE
from mtf.audit.service import AuditLogService, AuditSource
from mtf.shared.deps import get_db, require_any_scope

require_audit_reader = require_any_scope("system", "tenant", "tenant_account")


def get_audit_service(db: Session = Depends(get_db)) -> AuditLogService:
    return AuditLogService(db)


def get_audit_source(request: Request) -> AuditSource:
    """IP, user-agent, and the middleware-assigned ``request_id`` ULID."""
    request_id = getattr(request.state, AUDIT_REQUEST_ID_STATE, None)
    if not isinstance(request_id, str):
        request_id = None
    return AuditSource(
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        request_id=request_id,
    )
