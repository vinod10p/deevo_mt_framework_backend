"""Unit tests — append_audit_log add-only writer and secret stripping."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from mtf.audit.models import AuditLog
from mtf.audit.service import (
    AuditSource,
    append_audit_log,
    sanitize_audit_values,
)
from mtf.shared.deps import CurrentUser

ACTOR = CurrentUser(
    user_id="01JUSER0000000000000000001",
    user_type="app_user",
    user_scope="tenant",
    tenant_id="01JTENANT0000000000000001",
    account_id="01JACCOUNT000000000000001",
)
SOURCE = AuditSource(
    ip_address="10.0.0.1",
    user_agent="pytest",
    request_id="01JREQ00000000000000000001",
    session_id="01JSESS0000000000000000001",
)


def test_sanitize_strips_secrets_and_row_version() -> None:
    cleaned = sanitize_audit_values(
        {
            "email": "a@b.com",
            "password": "secret",
            "password_hash": "hash",
            "access_token": "tok",
            "mfa_secret_enc": "enc",
            "nested": {"refresh_token": "r", "role": "admin"},
            "row_version": b"\x00\x01",
        }
    )
    assert cleaned == {
        "email": "a@b.com",
        "nested": {"role": "admin"},
    }


def test_append_does_not_commit_and_fills_actor_source() -> None:
    db = MagicMock()
    log = append_audit_log(
        db,
        action="insert",
        actor=ACTOR,
        source=SOURCE,
        schema_name="tenant",
        table_name="tenant",
        record_id="01JREC00000000000000000001",
        new_values={"name": "Acme", "password": "nope"},
    )
    db.add.assert_called_once_with(log)
    db.commit.assert_not_called()
    assert isinstance(log, AuditLog)
    assert len(log.id) == 26
    assert (
        log.tenant_id,
        log.account_id,
        log.user_id,
        log.user_type,
    ) == (ACTOR.tenant_id, ACTOR.account_id, ACTOR.user_id, "tenant")
    assert (log.session_id, log.request_id) == (SOURCE.session_id, SOURCE.request_id)
    assert (log.ip_address, log.user_agent) == ("10.0.0.1", "pytest")
    assert log.old_values is None
    assert json.loads(log.new_values) == {"name": "Acme"}


def test_append_login_failed_allows_null_target() -> None:
    db = MagicMock()
    log = append_audit_log(
        db,
        action="login_failed",
        new_values={"email": "a@b.com", "password": "secret"},
    )
    assert log.schema_name is None and log.table_name is None and log.record_id is None
    assert json.loads(log.new_values) == {"email": "a@b.com"}
    db.commit.assert_not_called()


def test_append_insert_requires_target_and_new_values() -> None:
    db = MagicMock()
    with pytest.raises(ValueError, match="schema_name"):
        append_audit_log(db, action="insert", new_values={"a": 1})
    with pytest.raises(ValueError, match="new_values"):
        append_audit_log(
            db,
            action="insert",
            schema_name="auth",
            table_name="app_user",
            record_id="01JREC00000000000000000001",
        )


def test_append_rejects_non_object_values() -> None:
    db = MagicMock()
    with pytest.raises(ValueError, match="JSON object"):
        append_audit_log(
            db,
            action="login",
            new_values=["not", "an", "object"],  # type: ignore[arg-type]
        )


def test_append_delete_requires_old_values() -> None:
    db = MagicMock()
    with pytest.raises(ValueError, match="old_values"):
        append_audit_log(
            db,
            action="delete",
            schema_name="auth",
            table_name="app_user",
            record_id="01JREC00000000000000000001",
        )


def test_append_restore_requires_both_value_objects() -> None:
    db = MagicMock()
    with pytest.raises(ValueError, match="restore"):
        append_audit_log(
            db,
            action="restore",
            schema_name="auth",
            table_name="app_user",
            record_id="01JREC00000000000000000001",
            old_values={"is_deleted": True},
        )


def test_append_update_requires_both_value_objects() -> None:
    db = MagicMock()
    with pytest.raises(ValueError, match="old_values"):
        append_audit_log(
            db,
            action="update",
            schema_name="auth",
            table_name="app_user",
            record_id="01JREC00000000000000000001",
            new_values={"email": "a@b.com"},
        )


def test_append_encodes_datetime() -> None:
    db = MagicMock()
    stamp = datetime(2026, 11, 5, 12, 0, 0)
    log = append_audit_log(
        db,
        action="login",
        new_values={"at": stamp},
    )
    assert json.loads(log.new_values) == {"at": stamp.isoformat()}


def test_sanitize_encodes_decimal_as_string() -> None:
    cleaned = sanitize_audit_values({"revenue": Decimal("1500.50"), "employees": 12})
    assert cleaned == {"revenue": "1500.50", "employees": 12}


def test_append_encodes_decimal_without_typeerror() -> None:
    db = MagicMock()
    log = append_audit_log(
        db,
        action="insert",
        schema_name="crm",
        table_name="lead",
        record_id="01JREC00000000000000000001",
        new_values={"first_name": "Sam", "revenue": Decimal("1500.50")},
    )
    assert json.loads(log.new_values) == {"first_name": "Sam", "revenue": "1500.50"}


def test_explicit_none_clears_actor_tenant() -> None:
    db = MagicMock()
    log = append_audit_log(
        db,
        action="login",
        actor=ACTOR,
        tenant_id=None,
        new_values={"event": "login"},
    )
    assert log.tenant_id is None
    assert log.user_id == ACTOR.user_id
