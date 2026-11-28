"""Live SQL Server — switching the session's store (product decision 12, step 7).

The ``staff`` tenant gets MAYFAIR next to MAIN. Its admin (root role) may switch to any store;
a member with no roles may use only MAIN.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from main import app
from mtf.audit.models import AuditLog
from mtf.auth.models.session import AuthSession
from mtf.shared.config import get_settings
from mtf.shared.database import SessionLocal
from mtf.shared.security import decode_access_token
from tests.business_unit_fixtures import add_stores
from tests.cleanup import soft_delete_users
from tests.staff_login import PASSWORD, bearer, login_staff

pytestmark = pytest.mark.integration

SWITCH_URL = "/api/auth/session/business-unit"


@pytest.fixture
def mayfair(staff: dict) -> str:
    return add_stores(staff["tenant_id"], "MAYFAIR")["MAYFAIR"]


@pytest.fixture
def member(client: TestClient, staff: dict, system_auth_headers: dict[str, str]) -> Iterator[str]:
    email = f"member-{staff['email']}"
    r = client.post(
        f"/api/tenant/{staff['tenant_id']}/users",
        json={"email": email, "password": PASSWORD, "role": "member"},
        headers=system_auth_headers,
    )
    assert r.status_code == 201, r.text
    yield email
    soft_delete_users(r.json()["user_id"])


def _switch(client: TestClient, access_token: str, code: str):
    return client.post(SWITCH_URL, json={"business_unit_code": code}, headers=bearer(access_token))


def _me_store(client: TestClient, access_token: str) -> str:
    r = client.get("/api/auth/me", headers=bearer(access_token))
    assert r.status_code == 200, r.text
    return r.json()["business_unit"]["code"]


def _session_unit(access_token: str) -> str | None:
    with SessionLocal() as db:
        return db.get_one(AuthSession, decode_access_token(access_token)["sid"]).business_unit_id


def test_switch_moves_the_session_and_retires_the_old_token(
    client: TestClient, staff: dict, mayfair: str
) -> None:
    tokens = login_staff(client, staff["email"], staff["tenant_id"])
    r = _switch(client, tokens["access_token"], " mayfair ")
    assert r.status_code == 200, r.text
    switched = r.json()
    assert (switched["business_unit_id"], switched["business_unit_code"]) == (mayfair, "MAYFAIR")
    assert switched["multi_store"] is True
    assert decode_access_token(switched["access_token"])["business_unit_id"] == mayfair

    assert _session_unit(switched["access_token"]) == mayfair
    assert _me_store(client, switched["access_token"]) == "MAYFAIR"
    old = client.get("/api/auth/me", headers=bearer(tokens["access_token"]))
    assert old.status_code == 401
    assert old.json()["detail"]["message"] == "Session expired or revoked"

    refreshed = client.post("/api/auth/refresh", json={"refresh_token": switched["refresh_token"]})
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["business_unit_code"] == "MAYFAIR"

    with SessionLocal() as db:
        audit = db.scalars(
            select(AuditLog).where(
                AuditLog.action == "update",
                AuditLog.table_name == "session",
                AuditLog.record_id == decode_access_token(switched["access_token"])["sid"],
            )
        ).one()
    assert audit.business_unit_id == mayfair
    assert json.loads(audit.old_values) == {"business_unit_id": tokens["business_unit_id"]}
    assert json.loads(audit.new_values) == {
        "event": "business_unit_switch", "business_unit_id": mayfair,
    }


def test_denied_switch_keeps_the_session_and_its_token(
    client: TestClient, staff: dict, mayfair: str, member: str
) -> None:
    tokens = login_staff(client, member, staff["tenant_id"])
    for code in ("MAYFAIR", "COMPANY", "NOPE"):
        r = _switch(client, tokens["access_token"], code)
        assert r.status_code == 401, r.text
        assert r.json()["detail"] == {
            "code": "AUTH_UNAUTHORIZED", "message": "You don't have access to this store",
        }
    assert _session_unit(tokens["access_token"]) == tokens["business_unit_id"]
    assert _me_store(client, tokens["access_token"]) == "MAIN"


def test_browser_switch_sets_the_cookie_not_the_body(
    client: TestClient, staff: dict, mayfair: str
) -> None:
    tokens = login_staff(client, staff["email"], staff["tenant_id"])
    browser = TestClient(app, base_url="https://testserver")
    browser.headers["Origin"] = get_settings().allowed_origins[0]
    r = browser.post(
        "/api/auth/browser/session/business-unit",
        json={"business_unit_code": "MAYFAIR"},
        headers=bearer(tokens["access_token"]),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["business_unit_code"] == "MAYFAIR"
    assert "refresh_token" not in body
    assert body["session_id"] == decode_access_token(tokens["access_token"])["sid"]
    assert "__Host-deevoflow-refresh-" in r.headers["set-cookie"]
