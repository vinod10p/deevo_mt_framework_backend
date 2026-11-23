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
