"""SessionService audit writes — login, login_failed, logout; refresh is not audited."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from mtf.audit.models import AuditLog
from mtf.audit.service import AuditSource
from mtf.auth.models.session import AuthSession
from mtf.auth.schemas.session import LoginRequest, RefreshRequest
from mtf.auth.services.session_service import SessionService

SOURCE = AuditSource(
    ip_address="10.0.0.1",
    user_agent="pytest",
    request_id="01JREQ00000000000000000001",
)


def _added(db: MagicMock, kind: type) -> list:
    return [c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], kind)]


def test_unknown_email_writes_login_failed_without_password() -> None:
    db = MagicMock()
    service = SessionService(db)
    with patch.object(service, "_get_active_user_by_email", return_value=None):
        with pytest.raises(HTTPException) as exc:
            service.login(
                LoginRequest(email="nobody@example.com", password="secret", created_from="web"),
                source=SOURCE,
            )
    assert exc.value.status_code == 401
    [log] = _added(db, AuditLog)
    assert log.action == "login_failed"
    assert log.request_id == SOURCE.request_id
    body = json.loads(log.new_values)
    assert body["email"] == "nobody@example.com"
    assert "password" not in body
    db.commit.assert_called()


def test_wrong_password_writes_login_failed_with_user_id() -> None:
    db = MagicMock()
    user = MagicMock()
    user.id = "01JUSER0000000000000000001"
    user.user_scope = "tenant"
    user.password_hash = "hash"
    user.locked_until = None
    user.failed_login_count = 0
    service = SessionService(db)
    with (
        patch.object(service, "_get_active_user_by_email", return_value=user),
        patch("mtf.auth.services.session_service.verify_password", return_value=False),
    ):
        with pytest.raises(HTTPException):
            service.login(
                LoginRequest(email="a@b.com", password="nope", created_from="web"),
                source=SOURCE,
            )
    [log] = _added(db, AuditLog)
    assert log.action == "login_failed"
    assert log.user_id == user.id
    assert json.loads(log.new_values) == {"email": "a@b.com"}
    db.commit.assert_called()


def test_successful_login_writes_login_on_session() -> None:
    db = MagicMock()
    user = MagicMock()
    user.id = "01JUSER0000000000000000001"
    user.user_scope = "system"
    user.password_hash = "hash"
    user.locked_until = None
    user.failed_login_count = 1
    user.first_name = "A"
    user.last_name = "B"
    service = SessionService(db)
    with (
        patch.object(service, "_get_active_user_by_email", return_value=user),
        patch("mtf.auth.services.session_service.verify_password", return_value=True),
        patch("mtf.auth.services.session_service.create_access_token", return_value="access"),
        patch("mtf.auth.services.session_service.create_refresh_token", return_value="refresh"),
        patch("mtf.auth.services.session_service.hash_token", return_value=b"x" * 32),
        patch.object(service, "_tenant_name", return_value=None),
    ):
        service.login(
            LoginRequest(email="sys@example.com", password="ok", created_from="web"),
            source=SOURCE,
        )
    logs = _added(db, AuditLog)
    assert [log.action for log in logs] == ["login"]
    log = logs[0]
    assert (log.schema_name, log.table_name) == ("auth", "session")
    assert log.record_id == log.session_id
    assert log.request_id == SOURCE.request_id
    assert json.loads(log.new_values) == {"event": "login"}
    sessions = _added(db, AuthSession)
    assert sessions[0].ip_address == "10.0.0.1"


def test_logout_writes_logout_on_session() -> None:
    db = MagicMock()
    session = MagicMock()
    session.id = "01JSESS0000000000000000001"
    session.user_id = "01JUSER0000000000000000001"
    session.tenant_id = None
    service = SessionService(db)
    with (
        patch.object(service, "_get_session_by_access_hash", return_value=session),
        patch("mtf.auth.services.session_service.hash_token", return_value=b"x" * 32),
        patch.object(service, "_user_scope_for_audit", return_value="system"),
    ):
        service.logout("access-token", session.user_id, source=SOURCE)
    [log] = _added(db, AuditLog)
    assert log.action == "logout"
    assert (log.schema_name, log.table_name, log.record_id) == (
        "auth",
        "session",
        session.id,
    )
    assert log.request_id == SOURCE.request_id
    assert json.loads(log.new_values) == {"event": "logout"}
    db.commit.assert_called()


def test_refresh_does_not_write_audit() -> None:
    db = MagicMock()
    session = MagicMock()
    session.id = "01JSESS0000000000000000001"
    session.user_id = "01JUSER0000000000000000001"
    session.tenant_id = None
    session.refresh_expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=1)
    user = MagicMock()
    user.user_scope = "system"
    user.first_name = "A"
    user.last_name = "B"
    service = SessionService(db)
    with (
        patch.object(service, "_get_session_by_refresh_hash", return_value=session),
        patch("mtf.auth.services.session_service.decode_token", return_value={
            "session_id": session.id, "user_id": session.user_id,
        }),
        patch.object(service, "_get_active_user_by_id", return_value=user),
        patch("mtf.auth.services.session_service.create_access_token", return_value="a"),
        patch("mtf.auth.services.session_service.create_refresh_token", return_value="r"),
        patch("mtf.auth.services.session_service.hash_token", return_value=b"x" * 32),
        patch.object(service, "_tenant_name", return_value=None),
    ):
        service.refresh(RefreshRequest(refresh_token="tok"), source=SOURCE)
    assert _added(db, AuditLog) == []
    db.commit.assert_called()
