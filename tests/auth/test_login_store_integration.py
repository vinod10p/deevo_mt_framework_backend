"""Live SQL Server — the session's store: typed at login, kept and re-checked on refresh.

Product decisions 3–8 and 13 (steps 4 and 5). Uses the ``staff`` fixture (a fresh tenant
with COMPANY + MAIN and one admin) and adds a member with no roles. Store failures are
audited, never throttled, and all look the same.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from main import app
from mtf.auth.models.session import AuthSession
from mtf.auth.models.user_role import UserRole
from mtf.shared.config import get_settings
from mtf.shared.database import SessionLocal
from mtf.shared.security import decode_access_token
from mtf.tenant.business_units import FIRST_STORE_CODE, ROOT_UNIT_CODE
from mtf.tenant.models.business_unit import BusinessUnit
from tests.audit.test_audit_integration import _find_login_failed
from tests.business_unit_fixtures import add_stores, grant_store_role
from tests.cleanup import SEEDED_SYSTEM_USER_ID, soft_delete_users
from tests.staff_login import PASSWORD, login_staff

pytestmark = pytest.mark.integration

_REQUIRED = "Store is required"
_DENIED = "You don't have access to this store"


@pytest.fixture
def member(client: TestClient, staff: dict, system_auth_headers: dict[str, str]) -> Iterator[dict]:
    """A member of the ``staff`` tenant with no roles (default store: MAIN)."""
    email = f"member-{staff['email']}"
    r = client.post(
        f"/api/tenant/{staff['tenant_id']}/users",
        json={"email": email, "password": PASSWORD, "role": "member"},
        headers=system_auth_headers,
    )
    assert r.status_code == 201, r.text
    user_id = r.json()["user_id"]
    yield {"email": email, "user_id": user_id}
    soft_delete_users(user_id)


def _login(client: TestClient, email: str, tenant_id: str, store: str | None, **extra) -> dict:
    body = {"email": email, "password": PASSWORD, "tenant_id": tenant_id, "created_from": "web"}
    if store is not None:
        body["business_unit_code"] = store
    return client.post("/api/auth/login", json=body | extra)


def _rejected_with(response, message: str, email: str, reason: str) -> None:
    assert response.status_code == 401, response.text
    assert response.json()["detail"] == {"code": "AUTH_UNAUTHORIZED", "message": message}
    failed = _find_login_failed(email)
    assert failed is not None
    assert json.loads(failed.new_values)["reason"] == reason


def test_store_is_required_for_staff(client: TestClient, staff: dict) -> None:
    for blank in (None, "", "   "):
        r = _login(client, staff["email"], staff["tenant_id"], blank)
        _rejected_with(r, _REQUIRED, staff["email"], "store_required")


@pytest.mark.parametrize("store", ["NOPE", "COMPANYX", "MAIN2"])
def test_unknown_store_is_denied(client: TestClient, staff: dict, store: str) -> None:
    r = _login(client, staff["email"], staff["tenant_id"], store)
    _rejected_with(r, _DENIED, staff["email"], "store_denied")


def test_admin_logs_in_to_a_store_trimmed_and_case_insensitive(
    client: TestClient, staff: dict
) -> None:
    body = login_staff(client, staff["email"], staff["tenant_id"], store="  main ")
    assert body["business_unit_code"] == FIRST_STORE_CODE
    assert body["business_unit_type"] == "store"
    assert body["business_unit_name"] == "Main Store"
    assert body["multi_store"] is False

    claims = decode_access_token(body["access_token"])
    assert claims["business_unit_id"] == body["business_unit_id"]
    with SessionLocal() as db:
        session = db.get_one(AuthSession, claims["sid"])
        assert session.business_unit_id == body["business_unit_id"]


def test_admin_may_use_all_stores_mode(client: TestClient, staff: dict) -> None:
    body = login_staff(client, staff["email"], staff["tenant_id"], store=ROOT_UNIT_CODE.lower())
    assert body["business_unit_code"] == ROOT_UNIT_CODE
    assert body["business_unit_type"] == "root"


def test_member_without_roles_only_gets_the_default_store(
    client: TestClient, staff: dict, member: dict
) -> None:
    body = login_staff(client, member["email"], staff["tenant_id"])
    assert body["business_unit_code"] == FIRST_STORE_CODE

    r = _login(client, member["email"], staff["tenant_id"], ROOT_UNIT_CODE)
    _rejected_with(r, _DENIED, member["email"], "store_denied")


def test_store_failures_do_not_count_as_password_guesses(client: TestClient, staff: dict) -> None:
    attempts = get_settings().login_max_failures_per_account_ip + 3
    for _ in range(attempts):
        assert _login(client, staff["email"], staff["tenant_id"], "NOPE").status_code == 401
    login_staff(client, staff["email"], staff["tenant_id"])


def test_wrong_password_with_a_wrong_store_is_a_password_failure(
    client: TestClient, staff: dict
) -> None:
    r = _login(client, staff["email"], staff["tenant_id"], "NOPE", password="wrong")
    assert r.status_code == 401
    assert r.json()["detail"]["message"] == "Invalid email or password"


def test_browser_login_returns_the_store(client: TestClient, staff: dict) -> None:
    browser = TestClient(app, base_url="https://testserver")
    browser.headers["Origin"] = get_settings().allowed_origins[0]
    body = {
        "email": staff["email"],
        "password": PASSWORD,
        "tenant_id": staff["tenant_id"],
        "created_from": "web",
    }
    missing = browser.post("/api/auth/browser/login", json=body)
    assert missing.status_code == 401
    assert missing.json()["detail"]["message"] == _REQUIRED

    r = browser.post(
        "/api/auth/browser/login", json=body | {"business_unit_code": FIRST_STORE_CODE}
    )
    assert r.status_code == 200, r.text
    assert r.json()["business_unit_code"] == FIRST_STORE_CODE
    assert "refresh_token" not in r.json()


# --- refresh (step 5) ------------------------------------------------------------------


def _refresh(client: TestClient, tokens: dict):
    return client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})


def _assert_refresh_ends_session(client: TestClient, tokens: dict) -> None:
    r = _refresh(client, tokens)
    assert r.status_code == 401, r.text
    assert r.json()["detail"] == {"code": "AUTH_UNAUTHORIZED", "message": "Invalid refresh token"}
    with SessionLocal() as db:
        session = db.get_one(AuthSession, decode_access_token(tokens["access_token"])["sid"])
        assert (session.is_active, session.revoke_reason) == (False, "store_access_removed")


def test_refresh_keeps_the_store(client: TestClient, staff: dict) -> None:
    tokens = login_staff(client, staff["email"], staff["tenant_id"])
    r = _refresh(client, tokens)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["business_unit_id"] == tokens["business_unit_id"]
    assert body["business_unit_code"] == FIRST_STORE_CODE
    claims = decode_access_token(body["access_token"])
    assert claims["business_unit_id"] == tokens["business_unit_id"]


def test_refresh_ends_the_session_when_the_store_is_deactivated(
    client: TestClient, staff: dict
) -> None:
    tokens = login_staff(client, staff["email"], staff["tenant_id"])
    with SessionLocal() as db:
        db.get_one(BusinessUnit, tokens["business_unit_id"]).is_active = False
        db.commit()
    _assert_refresh_ends_session(client, tokens)


def test_refresh_ends_the_session_when_the_store_role_is_removed(
    client: TestClient, staff: dict, member: dict
) -> None:
    mayfair = add_stores(staff["tenant_id"], "MAYFAIR")["MAYFAIR"]
    assignment_id = grant_store_role(staff["tenant_id"], member["user_id"], mayfair)
    tokens = login_staff(client, member["email"], staff["tenant_id"], store="MAYFAIR")
    with SessionLocal() as db:
        db.get_one(UserRole, assignment_id).mark_deleted(SEEDED_SYSTEM_USER_ID)
        db.commit()
    _assert_refresh_ends_session(client, tokens)
