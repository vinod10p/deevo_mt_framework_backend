"""Each wired mutation adds audit.audit_log in the same transaction (mocked DB)."""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

from mtf.audit.models import AuditLog
from mtf.audit.service import AuditSource
from mtf.auth.models import TenantUser, User
from mtf.auth.models.tenant_account_user import TenantAccountUser
from mtf.auth.schemas import UserUpdate
from mtf.auth.services.tenant_account_user import TenantAccountUserService
from mtf.auth.services.tenant_user import TenantUserService
from mtf.auth.services.user import UserService
from mtf.shared.deps import CurrentUser
from mtf.tenant.models.mailbox import Mailbox
from mtf.tenant.schemas import TenantUserCreate, TenantUserUpdate
from mtf.tenant.schemas.mailbox import MailboxUpdate
from mtf.tenant.schemas.tenant_account import TenantAccountCreate, TenantAccountUpdate
from mtf.tenant.schemas.tenant_account_address import TenantAccountAddressUpdate
from mtf.tenant.schemas.tenant_account_user import (
    TenantAccountUserCreate,
    TenantAccountUserUpdate,
)
from mtf.tenant.services.mailbox_service import MailboxService
from mtf.tenant.services.tenant_account_address_service import TenantAccountAddressService
from mtf.tenant.services.tenant_account_service import TenantAccountService
from tests.tenant.conftest import (
    TEST_ACCOUNT_ID,
    TEST_TENANT_ID,
    TEST_USER_ID,
    minimal_tenant_account,
    minimal_tenant_account_address,
)

_NOW = datetime(2026, 5, 9, 12, 0, 0)
_ROW_VER = bytes(range(8))
ACTOR = CurrentUser(
    user_id=TEST_USER_ID,
    user_type="app_user",
    user_scope="tenant",
    tenant_id=TEST_TENANT_ID,
)
SOURCE = AuditSource(request_id="01JREQ00000000000000000001", ip_address="10.0.0.1")


def _logs(db: MagicMock) -> list[AuditLog]:
    return [c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], AuditLog)]


def _commit_after_adds(db: MagicMock) -> None:
    names = [call[0] for call in db.method_calls]
    add_indexes = [i for i, name in enumerate(names) if name == "add"]
    assert add_indexes, "expected db.add"
    assert "commit" in names
    assert names.index("commit") > add_indexes[-1]


def _user(**overrides: object) -> User:
    values: dict[str, object] = {
        "id": TEST_USER_ID,
        "email": "member@example.com",
        "first_name": "Member",
        "last_name": "User",
        "phone": None,
        "avatar_url": None,
        "password_hash": "x",
        "auth_provider": "local",
        "is_active": True,
        "is_deleted": False,
        "failed_login_count": 0,
        "mfa_enabled": False,
        "row_version": _ROW_VER,
        "created_at": _NOW,
        "updated_at": _NOW,
        "user_scope": "tenant",
    }
    values.update(overrides)
    return User(**values)  # type: ignore[arg-type]


def _membership(**overrides: object) -> TenantUser:
    values: dict[str, object] = {
        "id": "01HZYJZGXM0KV0K4T8Y9ABCDE5",
        "tenant_id": TEST_TENANT_ID,
        "user_id": TEST_USER_ID,
        "role": "member",
        "is_active": True,
        "is_deleted": False,
        "row_version": _ROW_VER,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    values.update(overrides)
    return TenantUser(**values)  # type: ignore[arg-type]


def _account_membership(**overrides: object) -> TenantAccountUser:
    values: dict[str, object] = {
        "id": "01HZYJZGXM0KV0K4T8Y9ABCDE6",
        "tenant_id": TEST_TENANT_ID,
        "account_id": TEST_ACCOUNT_ID,
        "user_id": TEST_USER_ID,
        "role": "member",
        "is_active": True,
        "is_deleted": False,
        "row_version": _ROW_VER,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    values.update(overrides)
    return TenantAccountUser(**values)  # type: ignore[arg-type]


def test_update_user_writes_changed_fields() -> None:
    db = MagicMock()
    user = _user(user_scope="system")
    svc = UserService(db)
    with patch.object(svc, "get_user", return_value=user):
        svc.update_user(
            user.id,
            UserUpdate(row_version=_ROW_VER, first_name="Patched"),
            updated_by=ACTOR.user_id,
            actor=ACTOR,
            source=SOURCE,
        )
    [log] = _logs(db)
    assert log.action == "update"
    assert (log.schema_name, log.table_name, log.record_id) == ("auth", "app_user", user.id)
    assert json.loads(log.old_values)["first_name"] == "Member"
    assert json.loads(log.new_values)["first_name"] == "Patched"
    _commit_after_adds(db)


def test_create_for_tenant_writes_user_and_membership() -> None:
    db = MagicMock()
    svc = TenantUserService(db)
    payload = TenantUserCreate(
        email="new@example.com",
        password="password123",
        role="member",
        first_name="New",
    )
    with (
        patch.object(svc, "_require_tenant"),
        patch.object(svc, "_get_active_user_by_email", return_value=None),
        patch("mtf.auth.services.tenant_user.hash_password", return_value="hashed"),
    ):
        svc.create_for_tenant(
            TEST_TENANT_ID,
            payload,
            created_by=ACTOR.user_id,
            actor=ACTOR,
            source=SOURCE,
        )
    logs = _logs(db)
    kinds = {(log.schema_name, log.table_name, log.action) for log in logs}
    assert kinds == {("auth", "app_user", "insert"), ("auth", "tenant_user", "insert")}
    assert all(log.tenant_id == TEST_TENANT_ID for log in logs)
    assert all(log.request_id == SOURCE.request_id for log in logs)
    user_log = next(log for log in logs if log.table_name == "app_user")
    body = json.loads(user_log.new_values)
    assert body["email"] == "new@example.com"
    assert "password" not in body and "password_hash" not in body
    _commit_after_adds(db)


def test_update_for_tenant_writes_membership_and_user() -> None:
    db = MagicMock()
    row = _membership()
    user = _user()
    svc = TenantUserService(db)
    with (
        patch.object(svc, "_membership_by_tenant_and_user", return_value=row),
        patch.object(svc, "_get_user_any", return_value=user),
    ):
        svc.update_for_tenant(
            TEST_TENANT_ID,
            TEST_USER_ID,
            TenantUserUpdate(row_version=_ROW_VER, role="admin", first_name="Renamed"),
            updated_by=ACTOR.user_id,
            actor=ACTOR,
            source=SOURCE,
        )
    logs = _logs(db)
    kinds = {(log.schema_name, log.table_name, log.action) for log in logs}
    assert kinds == {("auth", "tenant_user", "update"), ("auth", "app_user", "update")}
    membership_log = next(log for log in logs if log.table_name == "tenant_user")
    assert json.loads(membership_log.old_values)["role"] == "member"
    assert json.loads(membership_log.new_values)["role"] == "admin"
    _commit_after_adds(db)


def test_soft_delete_for_tenant_writes_delete() -> None:
    db = MagicMock()
    row = _membership()
    svc = TenantUserService(db)
    with patch.object(svc, "_membership_by_tenant_and_user", return_value=row):
        svc.soft_delete_for_tenant(
            TEST_TENANT_ID,
            TEST_USER_ID,
            deleted_by=ACTOR.user_id,
            actor=ACTOR,
            source=SOURCE,
        )
    [log] = _logs(db)
    assert log.action == "delete"
    assert (log.schema_name, log.table_name) == ("auth", "tenant_user")
    assert json.loads(log.old_values)["is_deleted"] is False
    assert json.loads(log.new_values)["is_deleted"] is True
    _commit_after_adds(db)


def test_create_for_account_writes_user_and_membership() -> None:
    db = MagicMock()
    svc = TenantAccountUserService(db)
    payload = TenantAccountUserCreate(
        email="portal@example.com",
        password="password123",
        role="member",
    )
    with (
        patch.object(svc, "_require_account"),
        patch.object(svc, "_get_active_user_by_email", return_value=None),
        patch("mtf.auth.services.tenant_account_user.hash_password", return_value="hashed"),
    ):
        svc.create_for_account(
            TEST_TENANT_ID,
            TEST_ACCOUNT_ID,
            payload,
            created_by=ACTOR.user_id,
            actor=ACTOR,
            source=SOURCE,
        )
    logs = _logs(db)
    kinds = {(log.schema_name, log.table_name, log.action) for log in logs}
    assert kinds == {
        ("auth", "app_user", "insert"),
        ("auth", "tenant_account_user", "insert"),
    }
    assert all(log.tenant_id == TEST_TENANT_ID for log in logs)
    assert all(log.account_id == TEST_ACCOUNT_ID for log in logs)
    _commit_after_adds(db)


def test_update_for_account_writes_membership_and_user() -> None:
    db = MagicMock()
    row = _account_membership()
    user = _user(user_scope="tenant_account")
    svc = TenantAccountUserService(db)
    with (
        patch.object(svc, "_membership", return_value=row),
        patch.object(svc, "_get_user_any", return_value=user),
    ):
        svc.update_for_account(
            TEST_TENANT_ID,
            TEST_ACCOUNT_ID,
            TEST_USER_ID,
            TenantAccountUserUpdate(row_version=_ROW_VER, first_name="Portal"),
            updated_by=ACTOR.user_id,
            actor=ACTOR,
            source=SOURCE,
        )
    logs = _logs(db)
    user_log = next(log for log in logs if log.table_name == "app_user")
    assert user_log.action == "update"
    assert json.loads(user_log.new_values)["first_name"] == "Portal"
    _commit_after_adds(db)


def test_soft_delete_for_account_writes_delete() -> None:
    db = MagicMock()
    row = _account_membership()
    svc = TenantAccountUserService(db)
    with patch.object(svc, "_membership", return_value=row):
        svc.soft_delete_for_account(
            TEST_TENANT_ID,
            TEST_ACCOUNT_ID,
            TEST_USER_ID,
            deleted_by=ACTOR.user_id,
            actor=ACTOR,
            source=SOURCE,
        )
    [log] = _logs(db)
    assert log.action == "delete"
    assert (log.schema_name, log.table_name) == ("auth", "tenant_account_user")
    assert log.account_id == TEST_ACCOUNT_ID
    _commit_after_adds(db)


def test_account_create_update_delete() -> None:
    db = MagicMock()
    db.scalars.return_value.first.side_effect = [MagicMock(), None]
    created = TenantAccountService(db).create(
        TenantAccountCreate(account_code="NEW1", account_type="customer", name="Neo"),
        TEST_TENANT_ID,
        created_by=ACTOR.user_id,
        actor=ACTOR,
        source=SOURCE,
    )
    [insert] = _logs(db)
    assert insert.action == "insert"
    assert (insert.schema_name, insert.table_name) == ("tenant", "tenant_account")
    assert insert.tenant_id == TEST_TENANT_ID
    assert insert.account_id == created.id
    _commit_after_adds(db)

    row = minimal_tenant_account()
    db2 = MagicMock()
    db2.scalars.return_value.first.return_value = row
    TenantAccountService(db2).update(
        TEST_ACCOUNT_ID,
        TEST_TENANT_ID,
        TenantAccountUpdate(row_version=_ROW_VER, name="Updated"),
        updated_by=ACTOR.user_id,
        actor=ACTOR,
        source=SOURCE,
    )
    [update] = _logs(db2)
    assert update.action == "update"
    assert json.loads(update.new_values)["name"] == "Updated"

    row2 = minimal_tenant_account()
    db3 = MagicMock()
    db3.scalars.return_value.first.return_value = row2
    TenantAccountService(db3).soft_delete(
        TEST_ACCOUNT_ID,
        TEST_TENANT_ID,
        deleted_by=ACTOR.user_id,
        actor=ACTOR,
        source=SOURCE,
    )
    [delete] = _logs(db3)
    assert delete.action == "delete"
    assert json.loads(delete.new_values)["is_deleted"] is True


def test_address_update_and_soft_delete() -> None:
    row = minimal_tenant_account_address()
    db = MagicMock()
    db.scalars.return_value.first.side_effect = [minimal_tenant_account(), row]
    TenantAccountAddressService(db).update(
        TEST_TENANT_ID,
        TEST_ACCOUNT_ID,
        row.id,
        TenantAccountAddressUpdate(row_version=_ROW_VER, address_line1="Changed"),
        updated_by=ACTOR.user_id,
        actor=ACTOR,
        source=SOURCE,
    )
    [update] = _logs(db)
    assert update.action == "update"
    assert (update.schema_name, update.table_name) == ("tenant", "tenant_account_address")
    assert json.loads(update.new_values)["address_line1"] == "Changed"

    row2 = minimal_tenant_account_address()
    db2 = MagicMock()
    db2.scalars.return_value.first.side_effect = [minimal_tenant_account(), row2]
    TenantAccountAddressService(db2).soft_delete(
        TEST_TENANT_ID,
        TEST_ACCOUNT_ID,
        row2.id,
        deleted_by=ACTOR.user_id,
        actor=ACTOR,
        source=SOURCE,
    )
    [delete] = _logs(db2)
    assert delete.action == "delete"
    assert json.loads(delete.old_values)["is_deleted"] is False
    assert json.loads(delete.new_values)["is_deleted"] is True


@patch("mtf.tenant.services.mailbox_service.get_settings")
def test_mailbox_update_and_delete(_settings: MagicMock) -> None:
    mailbox = Mailbox(
        id="01JMAILBOX0000000000000001",
        tenant_id=TEST_TENANT_ID,
        email_address="box@example.com",
        display_name="Old",
        provider="microsoft_graph",
        mailbox_type="user",
        is_deleted=False,
    )
    db = MagicMock()
    svc = MailboxService(db)
    with patch.object(svc, "get_by_id", return_value=mailbox):
        svc.update_for_tenant(
            TEST_TENANT_ID,
            mailbox.id,
            MailboxUpdate(display_name="Inbox"),
            updated_by=ACTOR.user_id,
            actor=ACTOR,
            source=SOURCE,
        )
    [update] = _logs(db)
    assert update.action == "update"
    assert (update.schema_name, update.table_name) == ("email", "mailbox")
    assert json.loads(update.new_values)["display_name"] == "Inbox"
    assert "access_token" not in json.loads(update.new_values)

    mailbox2 = Mailbox(
        id="01JMAILBOX0000000000000002",
        tenant_id=TEST_TENANT_ID,
        email_address="box2@example.com",
        is_deleted=False,
    )
    db2 = MagicMock()
    svc2 = MailboxService(db2)
    with patch.object(svc2, "get_by_id", return_value=mailbox2):
        assert svc2.delete_for_tenant(
            TEST_TENANT_ID,
            mailbox2.id,
            deleted_by=ACTOR.user_id,
            actor=ACTOR,
            source=SOURCE,
        )
    [delete] = _logs(db2)
    assert delete.action == "delete"
    assert json.loads(delete.new_values)["is_deleted"] is True
    _commit_after_adds(db2)
