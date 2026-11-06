"""Unit tests — audit_insert / audit_update / audit_soft_delete helpers."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from mtf.audit.models import AuditLog
from mtf.audit.service import (
    AuditSource,
    audit_insert,
    audit_soft_delete,
    audit_update,
    row_snapshot,
)
from mtf.shared.deps import CurrentUser
from mtf.tenant.models import Tenant

ACTOR = CurrentUser(
    user_id="01JUSER0000000000000000001",
    user_type="app_user",
    user_scope="system",
    tenant_id=None,
)
SOURCE = AuditSource(request_id="01JREQ00000000000000000001", ip_address="10.0.0.1")


def _logs(db: MagicMock) -> list[AuditLog]:
    return [c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], AuditLog)]


def test_audit_insert_snapshots_row_and_does_not_commit() -> None:
    db = MagicMock()
    tenant = Tenant(id="01JTENANT0000000000000001", name="Acme", subdomain="acme")
    log = audit_insert(
        db,
        entity=tenant,
        schema_name="tenant",
        table_name="tenant",
        actor=ACTOR,
        source=SOURCE,
        tenant_id=tenant.id,
    )
    assert _logs(db) == [log]
    db.commit.assert_not_called()
    assert log.action == "insert"
    assert (log.schema_name, log.table_name, log.record_id) == (
        "tenant",
        "tenant",
        tenant.id,
    )
    assert log.tenant_id == tenant.id
    assert log.request_id == SOURCE.request_id
    body = json.loads(log.new_values)
    assert body["name"] == "Acme"
    assert "row_version" not in body
    assert log.old_values is None


def test_audit_update_skips_when_nothing_changed() -> None:
    db = MagicMock()
    tenant = Tenant(id="01JTENANT0000000000000001", name="Acme", subdomain="acme")
    before = row_snapshot(tenant)
    assert audit_update(
        db,
        entity=tenant,
        schema_name="tenant",
        table_name="tenant",
        before=before,
        actor=ACTOR,
        source=SOURCE,
        tenant_id=tenant.id,
    ) is None
    db.add.assert_not_called()


def test_audit_update_writes_changed_keys_only() -> None:
    db = MagicMock()
    tenant = Tenant(id="01JTENANT0000000000000001", name="Acme", subdomain="acme")
    before = row_snapshot(tenant)
    tenant.name = "Renamed"
    log = audit_update(
        db,
        entity=tenant,
        schema_name="tenant",
        table_name="tenant",
        before=before,
        actor=ACTOR,
        source=SOURCE,
        tenant_id=tenant.id,
    )
    assert log is not None
    assert json.loads(log.old_values) == {"name": "Acme"}
    assert json.loads(log.new_values) == {"name": "Renamed"}


def test_audit_soft_delete_keeps_before_and_after() -> None:
    db = MagicMock()
    tenant = Tenant(
        id="01JTENANT0000000000000001",
        name="Acme",
        subdomain="acme",
        is_deleted=False,
    )
    before = row_snapshot(tenant)
    tenant.is_deleted = True
    log = audit_soft_delete(
        db,
        entity=tenant,
        schema_name="tenant",
        table_name="tenant",
        before=before,
        actor=ACTOR,
        source=SOURCE,
        tenant_id=tenant.id,
    )
    assert log.action == "delete"
    assert json.loads(log.old_values)["is_deleted"] is False
    assert json.loads(log.new_values)["is_deleted"] is True
    db.commit.assert_not_called()
