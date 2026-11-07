"""get_audit_source fills session_id from auth.session when a Bearer token is present."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from mtf.audit.api.deps import active_session_id_for_access_token, get_audit_source
from mtf.audit.service import AuditSource
from mtf.shared.deps import get_db

SESSION_ID = "01JSESS0000000000000000001"
ACCESS_TOKEN = "test-access-token"


def _probe_app(db: MagicMock) -> FastAPI:
    app = FastAPI()
    app.dependency_overrides[get_db] = lambda: db

    @app.get("/probe")
    def probe(source: AuditSource = Depends(get_audit_source)) -> dict[str, str | None]:
        return {"session_id": source.session_id, "request_id": source.request_id}

    return app


def test_lookup_returns_active_session_id() -> None:
    db = MagicMock()
    db.scalars.return_value.first.return_value = SESSION_ID
    assert active_session_id_for_access_token(db, ACCESS_TOKEN) == SESSION_ID
    db.scalars.assert_called_once()


def test_lookup_returns_none_when_no_row() -> None:
    db = MagicMock()
    db.scalars.return_value.first.return_value = None
    assert active_session_id_for_access_token(db, ACCESS_TOKEN) is None


def test_probe_without_bearer_leaves_session_null() -> None:
    db = MagicMock()
    client = TestClient(_probe_app(db))
    body = client.get("/probe").json()
    assert body["session_id"] is None
    db.scalars.assert_not_called()


def test_probe_with_bearer_sets_session_id() -> None:
    db = MagicMock()
    db.scalars.return_value.first.return_value = SESSION_ID
    client = TestClient(_probe_app(db))
    body = client.get("/probe", headers={"Authorization": f"Bearer {ACCESS_TOKEN}"}).json()
    assert body["session_id"] == SESSION_ID
    db.scalars.assert_called_once()


def test_probe_unknown_token_leaves_session_null() -> None:
    db = MagicMock()
    db.scalars.return_value.first.return_value = None
    client = TestClient(_probe_app(db))
    body = client.get(
        "/probe", headers={"Authorization": "Bearer not-a-session"}
    ).json()
    assert body["session_id"] is None
    db.scalars.assert_called_once()
