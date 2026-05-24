"""Smoke tests — no database required."""

from fastapi.testclient import TestClient

from main import app


def test_health() -> None:
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_openapi_lists_auth_user_routes() -> None:
    client = TestClient(app)
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]
    assert "/api/auth/login" in paths
    assert "/api/auth/refresh" in paths
    assert "/api/auth/logout" in paths
    assert "/api/auth/logout-all" in paths
    assert "/api/auth/me" in paths
    assert "/api/tenant/me" in paths
    assert "/api/tenant/users" in paths
    assert "/api/tenant/users/{user_id}" in paths
    assert "/api/auth/users" in paths
    assert "/api/auth/users/{user_id}" in paths
    assert "patch" in paths["/api/auth/users/{user_id}"]


def test_auth_operations_tagged() -> None:
    client = TestClient(app)
    schema = client.get("/openapi.json").json()
    tags_by_op: set[str] = set()
    for path_item in schema["paths"].values():
        for method in path_item.values():
            if isinstance(method, dict) and "tags" in method:
                tags_by_op.update(method["tags"])
    assert "auth" in tags_by_op


def test_openapi_registers_tenant_by_subdomain() -> None:
    client = TestClient(app)
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/tenant/by-subdomain" in paths
