"""Unit tests — backend-generated audit request_id ULID."""

from __future__ import annotations

from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from main import app as framework_app
from mtf.audit.api.deps import get_audit_source
from mtf.audit.middleware import AUDIT_REQUEST_ID_STATE, AuditRequestIdMiddleware


async def _probe(request: Request) -> JSONResponse:
    source = get_audit_source(request)
    return JSONResponse(
        {
            "state": getattr(request.state, AUDIT_REQUEST_ID_STATE, None),
            "source": source.request_id,
            "user_agent": source.user_agent,
        }
    )


def _probe_app() -> Starlette:
    return Starlette(
        routes=[Route("/probe", _probe)],
        middleware=[Middleware(AuditRequestIdMiddleware)],
    )


def test_middleware_assigns_ulid_and_get_audit_source_reads_it() -> None:
    client = TestClient(_probe_app())
    first = client.get("/probe", headers={"user-agent": "pytest-agent"}).json()
    second = client.get("/probe").json()
    assert first["state"] == first["source"]
    assert first["user_agent"] == "pytest-agent"
    assert isinstance(first["state"], str) and len(first["state"]) == 26
    assert first["state"] != second["state"]


def test_inbound_x_request_id_is_ignored() -> None:
    client = TestClient(_probe_app())
    body = client.get("/probe", headers={"X-Request-ID": "client-trace"}).json()
    assert body["state"] != "client-trace"
    assert body["state"] == body["source"]
    assert isinstance(body["state"], str) and len(body["state"]) == 26


def test_framework_health_runs_with_request_id_middleware() -> None:
    r = TestClient(framework_app).get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
