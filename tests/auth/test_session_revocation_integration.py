"""Live SQL Server — access tokens stop working on logout, refresh, and removal.

Uses the real login / refresh / logout routes; tenants and users created here are
soft-deleted afterwards.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from mtf.auth.models.user import User
from mtf.shared.database import SessionLocal
from tests.auth.conftest import PASSWORD, _soft_delete_user
from tests.tenant.conftest import SEEDED_SYSTEM_USER_ID

pytestmark = pytest.mark.integration



def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _login(client: TestClient, email: str, tenant_id: str) -> dict:
    r = client.post(
        "/api/auth/login",
        json={
            "email": email,
            "password": PASSWORD,
            "created_from": "web",
            "tenant_id": tenant_id,
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


def _me(client: TestClient, access_token: str) -> int:
    return client.get("/api/auth/me", headers=_bearer(access_token)).status_code


def test_logout_revokes_access_token(client: TestClient, staff: dict) -> None:
    tokens = _login(client, staff["email"], staff["tenant_id"])
    assert _me(client, tokens["access_token"]) == 200

    r = client.post("/api/auth/logout", headers=_bearer(tokens["access_token"]))
    assert r.status_code == 204, r.text

    assert _me(client, tokens["access_token"]) == 401
    refresh = client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refresh.status_code == 401


def test_refresh_supersedes_previous_access_token(client: TestClient, staff: dict) -> None:
    first = _login(client, staff["email"], staff["tenant_id"])
    r = client.post("/api/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert r.status_code == 200, r.text
    second = r.json()

    assert _me(client, second["access_token"]) == 200
    assert _me(client, first["access_token"]) == 401


def test_logout_only_affects_that_session(client: TestClient, staff: dict) -> None:
    laptop = _login(client, staff["email"], staff["tenant_id"])
    phone = _login(client, staff["email"], staff["tenant_id"])

    client.post("/api/auth/logout", headers=_bearer(laptop["access_token"]))

    assert _me(client, laptop["access_token"]) == 401
    assert _me(client, phone["access_token"]) == 200


def test_removed_staff_loses_access_immediately(
    client: TestClient, system_auth_headers: dict[str, str], staff: dict
) -> None:
    """Remove a member (the fixture's admin stays — the last admin can't be removed)."""
    tenant_id = staff["tenant_id"]
    email = f"sess-rev-member-{uuid.uuid4().hex[:12]}@example.com"
    member = client.post(
        f"/api/tenant/{tenant_id}/users",
        json={"email": email, "password": PASSWORD, "role": "member", "first_name": "M"},
        headers=system_auth_headers,
    )
    assert member.status_code == 201, member.text
    member_id = member.json()["user_id"]
    try:
        tokens = _login(client, email, tenant_id)
        assert _me(client, tokens["access_token"]) == 200

        removed = client.delete(
            f"/api/tenant/{tenant_id}/users/{member_id}", headers=system_auth_headers
        )
        assert removed.status_code == 204, removed.text

        assert _me(client, tokens["access_token"]) == 401
    finally:
        _soft_delete_user(member_id)


def test_deactivated_user_loses_access_immediately(client: TestClient, staff: dict) -> None:
    tokens = _login(client, staff["email"], staff["tenant_id"])
    assert _me(client, tokens["access_token"]) == 200

    with SessionLocal() as db:
        user = db.scalars(select(User).where(User.id == staff["user_id"])).one()
        user.is_active = False
        user.updated_by = SEEDED_SYSTEM_USER_ID
        db.commit()

    assert _me(client, tokens["access_token"]) == 401


def test_access_token_cannot_be_used_to_refresh(client: TestClient, staff: dict) -> None:
    """Finding #6: tokens are typed; ``/refresh`` refuses an access token."""
    tokens = _login(client, staff["email"], staff["tenant_id"])

    r = client.post("/api/auth/refresh", json={"refresh_token": tokens["access_token"]})
    assert r.status_code == 401, r.text

    # The session was not touched: the original pair still works.
    assert _me(client, tokens["access_token"]) == 200
    ok = client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert ok.status_code == 200, ok.text


def test_refresh_token_cannot_be_used_as_bearer(client: TestClient, staff: dict) -> None:
    tokens = _login(client, staff["email"], staff["tenant_id"])
    assert _me(client, tokens["refresh_token"]) == 401
    assert _me(client, tokens["access_token"]) == 200


def test_removed_staff_cannot_refresh(
    client: TestClient, system_auth_headers: dict[str, str], staff: dict
) -> None:
    """Gap in #4: removal must also stop new tokens being minted via /refresh."""
    tenant_id = staff["tenant_id"]
    email = f"sess-rev-refresh-{uuid.uuid4().hex[:12]}@example.com"
    member = client.post(
        f"/api/tenant/{tenant_id}/users",
        json={"email": email, "password": PASSWORD, "role": "member", "first_name": "R"},
        headers=system_auth_headers,
    )
    assert member.status_code == 201, member.text
    member_id = member.json()["user_id"]
    try:
        tokens = _login(client, email, tenant_id)
        removed = client.delete(
            f"/api/tenant/{tenant_id}/users/{member_id}", headers=system_auth_headers
        )
        assert removed.status_code == 204, removed.text

        r = client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert r.status_code == 401, r.text
        assert _me(client, tokens["access_token"]) == 401
    finally:
        _soft_delete_user(member_id)


def test_suspended_tenant_cannot_refresh(client: TestClient, staff: dict) -> None:
    from mtf.tenant.models import Tenant

    tokens = _login(client, staff["email"], staff["tenant_id"])
    with SessionLocal() as db:
        tenant = db.scalars(select(Tenant).where(Tenant.id == staff["tenant_id"])).one()
        original_status = tenant.status
        tenant.status = "suspended"
        tenant.updated_by = SEEDED_SYSTEM_USER_ID
        db.commit()
    try:
        r = client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert r.status_code == 401, r.text
    finally:
        with SessionLocal() as db:
            tenant = db.scalars(select(Tenant).where(Tenant.id == staff["tenant_id"])).one()
            tenant.status = original_status
            tenant.updated_by = SEEDED_SYSTEM_USER_ID
            db.commit()
