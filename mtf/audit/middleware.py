"""Per-request ULID for ``audit.audit_log.request_id``."""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send

from mtf.shared.security import generate_id

#: ``request.state`` attribute — never copy inbound X-Request-ID / trace headers.
AUDIT_REQUEST_ID_STATE = "audit_request_id"


class AuditRequestIdMiddleware:
    """Assign a backend-generated ULID to every HTTP request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            state = scope.setdefault("state", {})
            state[AUDIT_REQUEST_ID_STATE] = generate_id()
        await self.app(scope, receive, send)
