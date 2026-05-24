"""Shared pytest fixtures."""

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture(scope="session")
def client() -> TestClient:
    """FastAPI test client — reused across the whole test session."""
    return TestClient(app, raise_server_exceptions=True)
