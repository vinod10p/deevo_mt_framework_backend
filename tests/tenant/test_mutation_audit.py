"""Mutation services write audit.audit_log in the same transaction."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from mtf.audit.models import AuditLog
from mtf.audit.service import AuditSource
from mtf.auth.schemas import UserCreate
from mtf.auth.services.user import UserService
from mtf.shared.deps import CurrentUser
from mtf.tenant.schemas import TenantCreate, TenantUpdate
from mtf.tenant.schemas.mailbox import MailboxCreate
from mtf.tenant.schemas.tenant_account_address import TenantAccountAddressCreate
from mtf.tenant.services.mailbox_service import MailboxService
from mtf.tenant.services.tenant_account_address_service import TenantAccountAddressService
from mtf.tenant.services.tenant_service import TenantService
from tests.tenant.conftest import (
    TEST_ACCOUNT_ID,
    TEST_ADDRESS_ID,
    TEST_TENANT_ID,
    TEST_USER_ID,
    minimal_tenant,
    minimal_tenant_account,
    minimal_tenant_account_address,
)

ACTOR = CurrentUser(
    user_id=TEST_USER_ID,
    user_type="app_user",
    user_scope="system",
    tenant_id=None,
)
SOURCE = AuditSource(request_id="01JREQ00000000000000000001", ip_address="10.0.0.1")


def _logs(db: MagicMock) -> list[AuditLog]:
    return [c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], AuditLog)]


def test_create_tenant_writes_insert_with_new_tenant_id() -> None:
    db = MagicMock()
    tenant = TenantService(db).create_tenant(
        TenantCreate(name="Co", subdomain="co"),
        created_by=ACTOR.user_id,
        actor=ACTOR,
        source=SOURCE,
    )
    [log] = _logs(db)
    assert log.action == "insert"
    assert (log.schema_name, log.table_name, log.record_id) == ("tenant", "tenant", tenant.id)
    assert log.tenant_id == tenant.id
    assert log.request_id == SOURCE.request_id
    assert json.loads(log.new_values)["subdomain"] == "co"
    db.commit.assert_called_once()


def test_update_tenant_writes_changed_fields() -> None:
    row = minimal_tenant(id=TEST_TENANT_ID)
    db = MagicMock()
    db.scalars.return_value.first.return_value = row
    TenantService(db).update_tenant(
        TEST_TENANT_ID,
        TenantUpdate(row_version=row.row_version, name="Renamed"),
        updated_by=ACTOR.user_id,
        actor=ACTOR,
        source=SOURCE,
    )
    [log] = _logs(db)
    assert log.action == "update"
    assert json.loads(log.old_values)["name"] == "Test Tenant Org"
    assert json.loads(log.new_values)["name"] == "Renamed"


def test_soft_delete_tenant_writes_delete_action() -> None:
    row = minimal_tenant(id=TEST_TENANT_ID)
    db = MagicMock()
    db.scalars.return_value.first.return_value = row
    TenantService(db).soft_delete_tenant(
        TEST_TENANT_ID,
        deleted_by=ACTOR.user_id,
        actor=ACTOR,
        source=SOURCE,
    )
    [log] = _logs(db)
    assert log.action == "delete"
    assert json.loads(log.old_values)["is_deleted"] is False
    assert json.loads(log.new_values)["is_deleted"] is True


def test_create_user_strips_password_from_audit() -> None:
    db = MagicMock()
    svc = UserService(db)
    with (
        patch.object(svc, "get_by_email", return_value=None),
        patch("mtf.auth.services.user.hash_password", return_value="hashed"),
    ):
        user = svc.create_user(
            UserCreate(email="a@b.com", password="secret", first_name="Ann"),
            actor=ACTOR,
            source=SOURCE,
        )
    [log] = _logs(db)
    body = json.loads(log.new_values)
    assert log.action == "insert"
    assert (log.schema_name, log.table_name) == ("auth", "app_user")
    assert log.record_id == user.id
    assert body["email"] == "a@b.com"
    assert "password" not in body
    assert "password_hash" not in body


def test_clear_default_address_writes_update_audit() -> None:
    prev = minimal_tenant_account_address(id=TEST_ADDRESS_ID, is_default=True)
    db = MagicMock()
    db.scalars.return_value = [prev]
    TenantAccountAddressService(db)._clear_default_flags(
        TEST_TENANT_ID,
        TEST_ACCOUNT_ID,
        keep_address_id="01KEEP00000000000000000001",
        actor=ACTOR,
        source=SOURCE,
    )
    assert prev.is_default is False
    logs = _logs(db)
    assert logs[0].action == "update"
    assert (logs[0].schema_name, logs[0].table_name) == ("tenant", "tenant_account_address")
    assert json.loads(logs[0].old_values)["is_default"] is True
    assert json.loads(logs[0].new_values)["is_default"] is False


def test_create_address_writes_insert_with_account_id() -> None:
    db = MagicMock()
    db.scalars.return_value.first.return_value = minimal_tenant_account()
    row = TenantAccountAddressService(db).create(
        TEST_TENANT_ID,
        TEST_ACCOUNT_ID,
        TenantAccountAddressCreate(address_type="billing", address_line1="1 Main"),
        created_by=ACTOR.user_id,
        actor=ACTOR,
        source=SOURCE,
    )
    [log] = _logs(db)
    assert log.action == "insert"
    assert (log.schema_name, log.table_name) == ("tenant", "tenant_account_address")
    assert log.tenant_id == TEST_TENANT_ID
    assert log.account_id == TEST_ACCOUNT_ID
    assert log.record_id == row.id


@patch("mtf.tenant.services.mailbox_service.get_settings")
def test_create_mailbox_audits_email_mailbox(_settings: MagicMock) -> None:
    db = MagicMock()
    mailbox = MailboxService(db).create_for_tenant(
        TEST_TENANT_ID,
        MailboxCreate(email_address="box@example.com"),
        created_by=ACTOR.user_id,
        actor=ACTOR,
        source=SOURCE,
    )
    [log] = _logs(db)
    assert log.action == "insert"
    assert (log.schema_name, log.table_name) == ("email", "mailbox")
    assert log.tenant_id == TEST_TENANT_ID
    assert log.record_id == mailbox.id
    body = json.loads(log.new_values)
    assert body["email_address"] == "box@example.com"
    assert "access_token" not in body
    assert "refresh_token" not in body
