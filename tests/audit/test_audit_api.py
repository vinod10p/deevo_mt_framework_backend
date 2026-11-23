"""FastAPI tests — audit log read routes (mocked service)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from main import app
from mtf.audit.api.deps import get_audit_service
from mtf.audit.models import AuditLog
from mtf.shared.deps import get_current_user, get_db
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


def _membership_db(role: str | None) -> MagicMock:
    """Fake ``get_db`` whose membership lookup returns ``role``."""
    db = MagicMock()
    db.scalars.return_value.first.return_value = role
    return db


def _with_user(
    user, svc: MagicMock | None = None, *, role: str | None = "admin"
) -> MagicMock:
    """Override the caller; tenant/portal callers are admins unless ``role`` says otherwise."""
    if svc is None:
        svc = MagicMock()
    db = _membership_db(role)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_audit_service] = lambda: svc
    app.dependency_overrides[get_db] = lambda: db
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


# ---------------------------------------------------------------------------
# Who may read: system, tenant admins, account admins — not ordinary members
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["member", None], ids=["member", "no-membership"])
@pytest.mark.parametrize("url", [LOGS_URL, LOG_URL], ids=["list", "get"])
def test_tenant_non_admin_forbidden(role: str | None, url: str) -> None:
    svc = _with_user(tenant_user(), role=role)
    r = TestClient(app).get(url)
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "AUTH_FORBIDDEN"
    svc.list_logs.assert_not_called()
    svc.get_log.assert_not_called()


@pytest.mark.parametrize("role", ["member", "viewer", None], ids=["member", "viewer", "none"])
@pytest.mark.parametrize("url", [LOGS_URL, LOG_URL], ids=["list", "get"])
def test_portal_non_admin_forbidden(role: str | None, url: str) -> None:
    svc = _with_user(portal_user(), role=role)
    r = TestClient(app).get(url)
    assert r.status_code == 403, r.text
    svc.list_logs.assert_not_called()
    svc.get_log.assert_not_called()


def test_tenant_admin_can_list() -> None:
    svc = _with_user(tenant_user(), role="admin")
    svc.list_logs.return_value = [_log()]
    r = TestClient(app).get(LOGS_URL)
    assert r.status_code == 200, r.text
    assert [row["id"] for row in r.json()] == [LOG_ID]


def test_portal_admin_can_get() -> None:
    svc = _with_user(portal_user(), role="admin")
    svc.get_log.return_value = _log()
    r = TestClient(app).get(LOG_URL)
    assert r.status_code == 200, r.text


def test_system_needs_no_membership_lookup() -> None:
    svc = _with_user(system_user(), role=None)
    db = app.dependency_overrides[get_db]()
    svc.list_logs.return_value = []
    r = TestClient(app).get(LOGS_URL)
    assert r.status_code == 200, r.text
    db.scalars.assert_not_called()


def test_tenant_without_tenant_id_forbidden_before_lookup() -> None:
    svc = _with_user(tenant_user(tenant_id=None), role="admin")
    db = app.dependency_overrides[get_db]()
    r = TestClient(app).get(LOGS_URL)
    assert r.status_code == 403
    db.scalars.assert_not_called()
    svc.list_logs.assert_not_called()


def test_membership_lookup_uses_jwt_identity() -> None:
    """The role check queries the JWT tenant/user, not anything from the request."""
    _with_user(tenant_user(), role="admin")
    db = app.dependency_overrides[get_db]()
    TestClient(app).get(LOGS_URL, params={"tenant_id": OTHER_TENANT_ID})
    sql = str(db.scalars.call_args.args[0].compile(compile_kwargs={"literal_binds": True}))
    assert TEST_TENANT_ID in sql and OTHER_TENANT_ID not in sql
    assert "tenant_user" in sql
