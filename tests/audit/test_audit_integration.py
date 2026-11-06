"""Live SQL Server tests for ``audit.audit_log`` on ``deevo_app_dev2``.

Writes go through the HTTP API as ``deevo_app`` (SELECT/INSERT only). Audit rows
are append-only and are left in place; tenants created here are soft-deleted.
"""

from __future__ import annotations

import json
import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from mtf.audit.models import AuditLog
from mtf.auth.models.user import User
from mtf.shared.database import SessionLocal, engine
from tests.tenant.conftest import SEEDED_SYSTEM_USER_ID

pytestmark = pytest.mark.integration

LOGS_URL = "/api/audit/logs"
TARGET_DATABASE = "deevo_app_dev2"


def _skip_if_disabled() -> None:
    if os.environ.get("DEEVO_SKIP_DB_TESTS", "").lower() in ("1", "true", "yes"):
        pytest.skip("DEEVO_SKIP_DB_TESTS is set")


@pytest.fixture(scope="module", autouse=True)
def require_dev2_database() -> None:
    _skip_if_disabled()
    try:
        with engine.connect() as conn:
            name = conn.execute(text("SELECT DB_NAME() AS n")).scalar_one()
            table = conn.execute(
                text(
                    "SELECT 1 FROM sys.tables t "
                    "JOIN sys.schemas s ON s.schema_id = t.schema_id "
                    "WHERE s.name = 'audit' AND t.name = 'audit_log'"
                )
            ).first()
    except DBAPIError as exc:
        pytest.skip(f"database not available: {exc.__class__.__name__}")
    if str(name).lower() != TARGET_DATABASE:
        pytest.skip(
            f"audit integration targets {TARGET_DATABASE}, connected to {name}"
        )
    if table is None:
        pytest.skip("audit.audit_log is not present")


@pytest.fixture
def system_headers(client: TestClient) -> dict[str, str]:
    email = os.environ.get("DEEVO_TEST_SYSTEM_EMAIL", "vinod@deevolight.com")
    password = os.environ.get("DEEVO_TEST_SYSTEM_PASSWORD", "vinod123")
    r = client.post(
        "/api/auth/login",
        json={"email": email, "password": password, "created_from": "web"},
        headers={"User-Agent": "pytest-audit-int"},
    )
    if r.status_code != 200:
        pytest.skip(f"system login failed: {r.status_code} {r.text}")
    return {
        "Authorization": f"Bearer {r.json()['access_token']}",
        "User-Agent": "pytest-audit-int",
    }


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _json_object(raw: str | None) -> dict:
    assert raw is not None
    value = json.loads(raw)
    assert isinstance(value, dict)
    return value


def _list_logs(
    client: TestClient, headers: dict[str, str], **params: object
) -> list[dict]:
    r = client.get(LOGS_URL, params=params, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, list)
    return body


def _find_login_failed(email: str) -> AuditLog | None:
    with SessionLocal() as db:
        return db.scalars(
            select(AuditLog)
            .where(
                AuditLog.action == "login_failed",
                AuditLog.new_values.like(f"%{email}%"),
            )
            .order_by(AuditLog.created_at.desc())
        ).first()


def _cleanup_user(user_id: str) -> None:
    with SessionLocal() as db:
        user = db.scalars(select(User).where(User.id == user_id)).first()
        if user is None:
            return
        user.is_active = False
        user.is_deleted = True
        user.updated_by = SEEDED_SYSTEM_USER_ID
        user.deleted_by = SEEDED_SYSTEM_USER_ID
        db.add(user)
        db.commit()


def test_tenant_mutations_round_trip_audit_log(
    client: TestClient, system_headers: dict[str, str]
) -> None:
    subdomain = _unique("audit-int")
    create = client.post(
        "/api/tenant/",
        json={"name": "Audit Integration Tenant", "subdomain": subdomain},
        headers={**system_headers, "X-Request-ID": "client-trace"},
    )
    assert create.status_code == 201, create.text
    tenant = create.json()
    tenant_id = tenant["id"]
    row_version = tenant["row_version"]

    try:
        rows = _list_logs(
            client,
            system_headers,
            schema_name="tenant",
            table_name="tenant",
            record_id=tenant_id,
        )
        inserts = [row for row in rows if row["action"] == "insert"]
        assert len(inserts) == 1
        insert = inserts[0]
        assert insert["tenant_id"] == tenant_id
        assert insert["user_type"] == "system"
        assert insert["request_id"] not in (None, "client-trace")
        assert len(insert["request_id"]) == 26
        new_values = _json_object(insert["new_values"])
        assert insert["old_values"] is None
        assert new_values["name"] == "Audit Integration Tenant"
        assert new_values["subdomain"] == subdomain
        assert "password" not in new_values
        assert "row_version" not in new_values

        with SessionLocal() as db:
            db_row = db.scalars(select(AuditLog).where(AuditLog.id == insert["id"])).first()
        assert db_row is not None
        assert db_row.action == "insert"
        assert db_row.record_id == tenant_id

        patch = client.patch(
            f"/api/tenant/{tenant_id}",
            json={
                "row_version": row_version,
                "name": "Audit Integration Tenant Updated",
            },
            headers=system_headers,
        )
        assert patch.status_code == 200, patch.text

        rows = _list_logs(
            client,
            system_headers,
            schema_name="tenant",
            table_name="tenant",
            record_id=tenant_id,
        )
        updates = [row for row in rows if row["action"] == "update"]
        assert updates
        update = updates[0]
        assert _json_object(update["old_values"])["name"] == "Audit Integration Tenant"
        assert _json_object(update["new_values"])["name"] == "Audit Integration Tenant Updated"
        assert update["request_id"] != insert["request_id"]

        got = client.get(f"{LOGS_URL}/{insert['id']}", headers=system_headers)
        assert got.status_code == 200, got.text
        assert got.json()["id"] == insert["id"]
    finally:
        deleted = client.delete(f"/api/tenant/{tenant_id}", headers=system_headers)
        assert deleted.status_code == 204, deleted.text

    rows = _list_logs(
        client,
        system_headers,
        schema_name="tenant",
        table_name="tenant",
        record_id=tenant_id,
        action="delete",
    )
    assert rows
    delete_row = rows[0]
    assert delete_row["action"] == "delete"
    assert _json_object(delete_row["old_values"])["is_deleted"] is False
    assert _json_object(delete_row["new_values"])["is_deleted"] is True


def test_login_failed_persists_email_never_password(
    client: TestClient, system_headers: dict[str, str]
) -> None:
    email = f"audit-fail-{uuid.uuid4().hex[:12]}@example.com"
    failed = client.post(
        "/api/auth/login",
        json={"email": email, "password": "not-the-password", "created_from": "web"},
        headers={"User-Agent": "pytest-audit-int"},
    )
    assert failed.status_code == 401, failed.text

    stored = _find_login_failed(email)
    assert stored is not None
    assert stored.schema_name is None
    assert stored.table_name is None
    assert stored.record_id is None
    body = _json_object(stored.new_values)
    assert body["email"] == email
    assert "password" not in body
    assert "password_hash" not in body

    got = client.get(f"{LOGS_URL}/{stored.id}", headers=system_headers)
    assert got.status_code == 200, got.text
    assert got.json()["id"] == stored.id


def test_post_logs_is_gone_on_live_api(
    client: TestClient, system_headers: dict[str, str]
) -> None:
    r = client.post(
        LOGS_URL,
        json={"action": "login", "new_values": "{\"event\":\"nope\"}"},
        headers=system_headers,
    )
    assert r.status_code == 405


def test_tenant_jwt_cannot_read_unscoped_log(
    client: TestClient, system_headers: dict[str, str]
) -> None:
    subdomain = _unique("audit-scope")
    email = _unique("audit-staff") + "@example.com"
    password = "Secret123!"
    tenant_id: str | None = None
    user_id: str | None = None

    create = client.post(
        "/api/tenant/",
        json={"name": "Audit Scope Tenant", "subdomain": subdomain},
        headers=system_headers,
    )
    assert create.status_code == 201, create.text
    tenant_id = create.json()["id"]

    try:
        staff = client.post(
            f"/api/tenant/{tenant_id}/users",
            json={
                "email": email,
                "password": password,
                "role": "owner",
                "first_name": "Audit",
            },
            headers=system_headers,
        )
        assert staff.status_code == 201, staff.text
        user_id = staff.json()["user_id"]

        login = client.post(
            "/api/auth/login",
            json={
                "email": email,
                "password": password,
                "created_from": "web",
                "tenant_id": tenant_id,
            },
        )
        assert login.status_code == 200, login.text
        tenant_headers = {
            "Authorization": f"Bearer {login.json()['access_token']}",
        }

        own = _list_logs(client, tenant_headers, limit=50)
        assert own
        assert all(row["tenant_id"] == tenant_id for row in own)
        assert any(
            row["action"] == "insert" and row["record_id"] == tenant_id for row in own
        )

        other = _list_logs(
            client,
            tenant_headers,
            tenant_id="01HZYJZGXM0KV0K4T8Y9ABCDE9",
            limit=50,
        )
        assert all(row["tenant_id"] == tenant_id for row in other)

        unknown = f"audit-hidden-{uuid.uuid4().hex[:12]}@example.com"
        hidden_login = client.post(
            "/api/auth/login",
            json={
                "email": unknown,
                "password": "not-the-password",
                "created_from": "web",
            },
        )
        assert hidden_login.status_code == 401, hidden_login.text
        hidden = _find_login_failed(unknown)
        assert hidden is not None
        assert hidden.tenant_id is None
        blocked = client.get(f"{LOGS_URL}/{hidden.id}", headers=tenant_headers)
        assert blocked.status_code == 404, blocked.text
        assert blocked.json()["detail"]["code"] == "AUDIT_LOG_NOT_FOUND"
    finally:
        if user_id is not None:
            if tenant_id is not None:
                client.delete(
                    f"/api/tenant/{tenant_id}/users/{user_id}",
                    headers=system_headers,
                )
            _cleanup_user(user_id)
        if tenant_id is not None:
            client.delete(f"/api/tenant/{tenant_id}", headers=system_headers)


def _execute_as_deevo_app(sql: str, **params: object) -> None:
    """Run ``sql`` as ``deevo_app`` and always roll back.

    Local ``.env`` may connect as a ``db_owner`` login (``deevo``), which bypasses
    object DENY. Impersonation checks the GRANT/DENY that production uses.
    """
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(text("EXECUTE AS USER = 'deevo_app'"))
            conn.execute(text(sql), params)
        finally:
            trans.rollback()


def test_app_role_cannot_update_or_delete_audit_log(
    client: TestClient, system_headers: dict[str, str]
) -> None:
    with engine.connect() as conn:
        principal = conn.execute(text("SELECT DATABASE_PRINCIPAL_ID('deevo_app')")).scalar()
    if principal is None:
        pytest.skip("database user deevo_app is not present")

    rows = _list_logs(client, system_headers, action="login", limit=1)
    if not rows:
        pytest.skip("no audit rows to prove append-only DENY")
    log_id = rows[0]["id"]

    with pytest.raises(DBAPIError):
        _execute_as_deevo_app(
            "DELETE FROM audit.audit_log WHERE id = :id",
            id=log_id,
        )
    with pytest.raises(DBAPIError):
        _execute_as_deevo_app(
            "UPDATE audit.audit_log SET reason = N'should-not-stick' WHERE id = :id",
            id=log_id,
        )

    with SessionLocal() as db:
        assert db.scalars(select(AuditLog).where(AuditLog.id == log_id)).first() is not None
