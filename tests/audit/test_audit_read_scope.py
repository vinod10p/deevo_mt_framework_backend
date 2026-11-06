"""Unit tests — JWT-scoped audit reads (no database)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from mtf.audit.models import AuditLog
from mtf.audit.service import (
    AuditLogService,
    audit_log_visible,
    resolve_audit_read_scope,
)
from tests.audit.conftest import (
    LOG_ID,
    OTHER_ACCOUNT_ID,
    OTHER_TENANT_ID,
    TEST_ACCOUNT_ID,
    TEST_TENANT_ID,
    portal_user,
    system_user,
    tenant_user,
)


def _log(**overrides: object) -> AuditLog:
    values: dict[str, object] = {
        "id": LOG_ID,
        "action": "update",
        "tenant_id": TEST_TENANT_ID,
        "account_id": None,
        "created_at": datetime(2026, 11, 5, 12, 0, 0),
    }
    values.update(overrides)
    return AuditLog(**values)  # type: ignore[arg-type]


def test_system_scope_uses_optional_filters() -> None:
    assert resolve_audit_read_scope(system_user()) == (None, None)
    assert resolve_audit_read_scope(
        system_user(), tenant_id=TEST_TENANT_ID, account_id=TEST_ACCOUNT_ID
    ) == (TEST_TENANT_ID, TEST_ACCOUNT_ID)


def test_tenant_scope_ignores_query_tenant_id() -> None:
    assert resolve_audit_read_scope(
        tenant_user(), tenant_id=OTHER_TENANT_ID, account_id=TEST_ACCOUNT_ID
    ) == (TEST_TENANT_ID, TEST_ACCOUNT_ID)


def test_portal_scope_ignores_query_tenant_and_account() -> None:
    assert resolve_audit_read_scope(
        portal_user(), tenant_id=OTHER_TENANT_ID, account_id=OTHER_ACCOUNT_ID
    ) == (TEST_TENANT_ID, TEST_ACCOUNT_ID)


def test_tenant_without_tenant_id_is_forbidden() -> None:
    with pytest.raises(HTTPException) as exc:
        resolve_audit_read_scope(tenant_user(tenant_id=None))
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "AUTH_FORBIDDEN"


def test_visibility_hides_other_tenant_from_staff() -> None:
    own = _log()
    other = _log(tenant_id=OTHER_TENANT_ID)
    assert audit_log_visible(tenant_user(), own) is True
    assert audit_log_visible(tenant_user(), other) is False
    assert audit_log_visible(system_user(), other) is True


def test_portal_sees_only_own_account() -> None:
    own = _log(account_id=TEST_ACCOUNT_ID)
    other_account = _log(account_id=OTHER_ACCOUNT_ID)
    tenant_level = _log(account_id=None)
    assert audit_log_visible(portal_user(), own) is True
    assert audit_log_visible(portal_user(), other_account) is False
    assert audit_log_visible(portal_user(), tenant_level) is False
    assert audit_log_visible(tenant_user(), tenant_level) is True


def test_list_logs_applies_forced_tenant_not_query_tenant() -> None:
    db = MagicMock()
    db.scalars.return_value.all.return_value = []
    AuditLogService(db).list_logs(tenant_user(), tenant_id=OTHER_TENANT_ID)
    stmt = db.scalars.call_args.args[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert TEST_TENANT_ID in sql
    assert OTHER_TENANT_ID not in sql


def test_get_log_returns_none_when_out_of_scope() -> None:
    db = MagicMock()
    db.scalars.return_value.first.return_value = _log(tenant_id=OTHER_TENANT_ID)
    assert AuditLogService(db).get_log(tenant_user(), LOG_ID) is None
