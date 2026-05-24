"""Auth test fixtures — system login for integration tests."""

from __future__ import annotations

import os
from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def system_auth_headers(client: TestClient) -> dict[str, str]:
    """Bearer token for bootstrap system user (integration tests only)."""
    if os.environ.get("DEEVO_SKIP_DB_TESTS", "").lower() in ("1", "true", "yes"):
        pytest.skip("DEEVO_SKIP_DB_TESTS is set")

    email = os.environ.get("DEEVO_TEST_SYSTEM_EMAIL", "vinod@deevolight.com")
    password = os.environ.get("DEEVO_TEST_SYSTEM_PASSWORD", "vinod123")
    r = client.post(
        "/api/auth/login",
        json={"email": email, "password": password, "created_from": "web"},
    )
    if r.status_code != 200:
        pytest.skip(f"system login failed: {r.status_code} {r.text}")
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def clear_app_dependency_overrides() -> Generator[None, None, None]:
    from main import app

    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()
