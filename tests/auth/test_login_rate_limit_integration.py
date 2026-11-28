"""Live SQL Server — the lockout-DoS fix (finding #8) through the real login route."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from main import app
from mtf.shared.config import get_settings
from mtf.tenant.business_units import FIRST_STORE_CODE
from tests.auth.conftest import PASSWORD
from tests.auth.test_session_revocation_integration import _me

pytestmark = pytest.mark.integration


def _from(ip: str) -> TestClient:
    return TestClient(app, client=(ip, 50_000))


def test_attacker_cannot_lock_out_real_user(staff: dict) -> None:
    attacker, victim = _from("203.0.113.66"), _from("198.51.100.10")
    body = {
        "email": staff["email"],
        "password": "definitely-wrong",
        "created_from": "web",
        "tenant_id": staff["tenant_id"],
        "business_unit_code": FIRST_STORE_CODE,
    }
    limit = get_settings().login_max_failures_per_account_ip

    statuses = [attacker.post("/api/auth/login", json=body).status_code for _ in range(limit + 3)]
    assert statuses == [401] * limit + [429] * 3

    blocked = attacker.post("/api/auth/login", json=body | {"password": PASSWORD})
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) > 0

    ok = victim.post("/api/auth/login", json=body | {"password": PASSWORD})
    assert ok.status_code == 200, ok.text
    assert _me(victim, ok.json()["access_token"]) == 200
