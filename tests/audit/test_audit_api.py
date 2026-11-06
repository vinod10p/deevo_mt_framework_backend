"""FastAPI tests — audit log read routes (mocked service)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from main import app
from mtf.audit.api.deps import get_audit_service
from mtf.audit.models import AuditLog
from mtf.shared.deps import get_current_user
from tests.audit.conftest import (
    LOG_ID,
    OTHER_TENANT_ID,
    TEST_ACCOUNT_ID,
    TEST_TENANT_ID,
    portal_user,
    system_user,
    tenant_user,
)

LOGS_URL = "/api/audit/logs"
LOG_URL = f"{LOGS_URL}/{LOG_ID}"


def _log(**overrides: object) -> AuditLog:
    values: dict[str, object] = {
        "id": LOG_ID,
        "action": "update",
        "tenant_id": TEST_TENANT_ID,
        "account_id": TEST_ACCOUNT_ID,
        "schema_name": "tenant",
        "table_name": "tenant",
        "record_id": "01JREC00000000000000000001",
        "created_at": datetime(2026, 11, 5, 12, 0, 0),
    }
    values.update(overrides)
    return AuditLog(**values)  # type: ignore[arg-type]


def _with_user(user, svc: MagicMock | None = None) -> MagicMock:
    if svc is None:
        svc = MagicMock()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_audit_service] = lambda: svc
    return svc


def test_openapi_has_get_logs_and_no_post() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    assert "get" in paths[LOGS_URL]
    assert "post" not in paths[LOGS_URL]
    assert "get" in paths["/api/audit/logs/{log_id}"]


def test_list_requires_bearer() -> None:
    r = TestClient(app).get(LOGS_URL)
    assert r.status_code in (401, 403)


def test_post_logs_gone() -> None:
    svc = _with_user(system_user())
    r = TestClient(app).post(LOGS_URL, json={"action": "login"})
    assert r.status_code == 405
    svc.create_log.assert_not_called()
    svc.append.assert_not_called()


def test_list_passes_user_and_filters_not_query_tenant_for_staff() -> None:
    user = tenant_user()
    svc = _with_user(user)
    svc.list_logs.return_value = []
    r = TestClient(app).get(
        LOGS_URL,
        params={
            "tenant_id": OTHER_TENANT_ID,
            "action": "update",
            "request_id": "01JREQ00000000000000000001",
            "skip": 5,
            "limit": 10,
        },
    )
    assert r.status_code == 200, r.text
    kwargs = svc.list_logs.call_args.kwargs
    assert svc.list_logs.call_args.args[0] == user
    assert kwargs["tenant_id"] == OTHER_TENANT_ID
    assert kwargs["action"] == "update"
    assert kwargs["request_id"] == "01JREQ00000000000000000001"
    assert kwargs["skip"] == 5 and kwargs["limit"] == 10
    # Service, not the query string, enforces JWT tenant.


def test_get_log_200() -> None:
    svc = _with_user(system_user())
    svc.get_log.return_value = _log()
    r = TestClient(app).get(LOG_URL)
    assert r.status_code == 200, r.text
    assert r.json()["id"] == LOG_ID
    assert r.json()["account_id"] == TEST_ACCOUNT_ID
    args, _kwargs = svc.get_log.call_args
    assert args[0].user_scope == "system"
    assert args[1] == LOG_ID


def test_get_log_404() -> None:
    svc = _with_user(tenant_user())
    svc.get_log.return_value = None
    r = TestClient(app).get(LOG_URL)
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "AUDIT_LOG_NOT_FOUND"


def test_portal_list_calls_service_with_portal_user() -> None:
    user = portal_user()
    svc = _with_user(user)
    svc.list_logs.return_value = []
    r = TestClient(app).get(LOGS_URL)
    assert r.status_code == 200
    assert svc.list_logs.call_args.args[0] == user
