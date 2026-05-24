"""User API integration tests (requires live SQL Server)."""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


def _skip_if_disabled() -> None:
    if os.environ.get("DEEVO_SKIP_DB_TESTS", "").lower() in ("1", "true", "yes"):
        pytest.skip("DEEVO_SKIP_DB_TESTS is set")


def _unique_email() -> str:
    return f"user-api-test-{uuid.uuid4().hex}@example.com"


def test_create_user_minimal_201(
    client: TestClient, system_auth_headers: dict[str, str]
) -> None:
    _skip_if_disabled()

    email = _unique_email()
    r = client.post("/api/auth/users", json={"email": email}, headers=system_auth_headers)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email"] == email.strip().lower()
    assert body["email_normalized"] == email.strip().lower()
    assert body["user_scope"] == "tenant"
    assert body["is_active"] is True
    assert body["is_deleted"] is False
    assert body["auth_provider"] == "local"
    assert isinstance(body["id"], str) and len(body["id"]) == 26
    assert isinstance(body["row_version"], str) and len(body["row_version"]) > 0


def test_create_user_with_scope_and_profile(
    client: TestClient, system_auth_headers: dict[str, str]
) -> None:
    _skip_if_disabled()

    email = _unique_email()
    r = client.post(
        "/api/auth/users",
        json={
            "email": email,
            "user_scope": "system",
            "first_name": "Test",
            "last_name": "User",
            "phone": "+15555550100",
        },
        headers=system_auth_headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email"] == email.strip().lower()
    assert body["user_scope"] == "system"
    assert body["first_name"] == "Test"
    assert body["last_name"] == "User"
    assert body["phone"] == "+15555550100"


def test_create_duplicate_email_409(
    client: TestClient, system_auth_headers: dict[str, str]
) -> None:
    _skip_if_disabled()

    email = _unique_email()
    r1 = client.post("/api/auth/users", json={"email": email}, headers=system_auth_headers)
    assert r1.status_code == 201, r1.text

    r2 = client.post("/api/auth/users", json={"email": email}, headers=system_auth_headers)
    assert r2.status_code == 409, r2.text
    assert r2.json()["detail"]["code"] == "EMAIL_IN_USE"


def test_get_user_by_id_and_list_contains_user(
    client: TestClient, system_auth_headers: dict[str, str]
) -> None:
    _skip_if_disabled()

    email = _unique_email()
    r = client.post("/api/auth/users", json={"email": email}, headers=system_auth_headers)
    assert r.status_code == 201, r.text
    user_id = r.json()["id"]

    r = client.get(f"/api/auth/users/{user_id}", headers=system_auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["id"] == user_id
    assert r.json()["email"] == email.strip().lower()

    r = client.get("/api/auth/users?skip=0&limit=500", headers=system_auth_headers)
    assert r.status_code == 200, r.text
    ids = {u["id"] for u in r.json()}
    assert user_id in ids


def test_get_user_unknown_404(
    client: TestClient, system_auth_headers: dict[str, str]
) -> None:
    _skip_if_disabled()

    r = client.get(
        "/api/auth/users/01HZ9999999999999999999999",
        headers=system_auth_headers,
    )
    assert r.status_code == 404, r.text
    assert r.json()["detail"]["code"] == "USER_NOT_FOUND"
