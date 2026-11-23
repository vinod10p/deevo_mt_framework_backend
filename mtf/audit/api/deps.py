"""FastAPI dependencies — audit request origin and read access."""

from __future__ import annotations

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from mtf.audit.middleware import AUDIT_REQUEST_ID_STATE
from mtf.audit.service import AuditLogService, AuditSource
from mtf.auth.models.session import AuthSession
from mtf.shared.client_ip import client_ip
from mtf.shared.deps import (
    CurrentUser,
    account_membership_role,
    get_db,
    require_any_scope,
    tenant_membership_role,
)
from mtf.shared.exceptions import forbidden
from mtf.shared.security import hash_token


def require_audit_reader(
    user: CurrentUser = Depends(require_any_scope("system", "tenant", "tenant_account")),
    db: Session = Depends(get_db),
) -> CurrentUser:
    """Who may read the audit trail.

    * ``system`` — everything (optionally filtered).
    * ``tenant`` — tenant **admins** only; members get 403. Rows are still limited to the
      JWT tenant by :func:`resolve_audit_read_scope`.
    * ``tenant_account`` — account **admins** only; rows limited to the JWT account.

    The trail holds staff emails (``login_failed``), role changes and before/after
    snapshots, so ordinary members must not see it.
    """
    if user.user_scope == "system":
        return user
    if user.user_scope == "tenant":
        if user.tenant_id is None:
            forbidden("AUTH", "Tenant context required")
        role = tenant_membership_role(db, user)
    else:
        if user.tenant_id is None or user.account_id is None:
            forbidden("AUTH", "Account context required")
        role = account_membership_role(db, user)
    if role != "admin":
        forbidden("AUTH", "Insufficient permissions")
    return user

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
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
        request_id=request_id,
        session_id=session_id,
    )
