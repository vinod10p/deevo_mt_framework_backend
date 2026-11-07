"""FastAPI dependencies — audit request origin and read access."""

from __future__ import annotations

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from mtf.audit.middleware import AUDIT_REQUEST_ID_STATE
from mtf.audit.service import AuditLogService, AuditSource
from mtf.auth.models.session import AuthSession
from mtf.shared.deps import get_db, require_any_scope
from mtf.shared.security import hash_token

require_audit_reader = require_any_scope("system", "tenant", "tenant_account")

#: Login / refresh have no access JWT; do not 401 from ``get_audit_source``.
_optional_bearer = HTTPBearer(auto_error=False)


def get_audit_service(db: Session = Depends(get_db)) -> AuditLogService:
    return AuditLogService(db)


def active_session_id_for_access_token(db: Session, raw_access_token: str) -> str | None:
    """``auth.session.id`` for the current access JWT, or None if none is active."""
    stmt = (
        select(AuthSession.id)
        .where(
            AuthSession.token_hash == hash_token(raw_access_token),
            AuthSession.is_active == True,  # noqa: E712
            AuthSession.is_deleted == False,  # noqa: E712
        )
        .limit(1)
    )
    row = db.scalars(stmt).first()
    return row if isinstance(row, str) else None


def get_audit_source(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
    db: Session | None = Depends(get_db),
) -> AuditSource:
    """IP, user-agent, request ULID, and ``session_id`` when a Bearer token matches."""
    request_id = getattr(request.state, AUDIT_REQUEST_ID_STATE, None)
    if not isinstance(request_id, str):
        request_id = None
    session_id = None
    if (
        isinstance(credentials, HTTPAuthorizationCredentials)
        and credentials.credentials
        and db is not None
        and hasattr(db, "scalars")
    ):
        session_id = active_session_id_for_access_token(db, credentials.credentials)
    return AuditSource(
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        request_id=request_id,
        session_id=session_id,
    )
