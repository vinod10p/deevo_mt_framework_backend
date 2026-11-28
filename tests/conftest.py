"""Shared pytest fixtures."""

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture(scope="session")
def client() -> TestClient:
    """FastAPI test client — reused across the whole test session."""
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def reset_login_throttle() -> None:
    """The login throttle is process-wide and every TestClient request comes from
    ``testclient`` — reset it so deliberate failed logins in one test can't 429 another."""
    from mtf.auth.services.login_throttle import login_throttle

    login_throttle.clear()
    yield
    login_throttle.clear()


#: Business unit id returned for every unit lookup made through a mocked DB session.
TEST_BUSINESS_UNIT_ID = "01HZYJZGXM0KV0K4T8Y9ABCDEB"


@pytest.fixture(autouse=True)
def business_units_for_mock_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests run services on mock sessions; answer business-unit lookups for them.

    A real ``Session`` (integration tests) still queries ``tenant.business_unit``.
    """
    from sqlalchemy.orm import Session

    from mtf.tenant import business_units

    real_lookup = business_units._required_unit_id

    def lookup(db: object, tenant_id: str, *conditions: object) -> str:
        if isinstance(db, Session):
            return real_lookup(db, tenant_id, *conditions)
        return TEST_BUSINESS_UNIT_ID

    monkeypatch.setattr(business_units, "_root_ids", {})
    monkeypatch.setattr(business_units, "_required_unit_id", lookup)
