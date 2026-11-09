"""PermissionResolver — mocked session, no live database."""

from __future__ import annotations

from unittest.mock import MagicMock

from sqlalchemy.dialects import mssql

from mtf.auth.services.permission_resolver import PermissionResolver, ReportGrant
from mtf.shared.deps import CurrentUser

TEST_TENANT_ID = "01HZYJZGXM0KV0K4T8Y9ABCDE0"
TEST_USER_ID = "01HZYJZGXM0KV0K4T8Y9ABCDE3"
TEST_ACCOUNT_ID = "01HZYJZGXM0KV0K4T8Y9ABCDE1"


def tenant_user(tenant_id: str | None = TEST_TENANT_ID) -> CurrentUser:
    return CurrentUser(
        user_id=TEST_USER_ID,
        user_type="app_user",
        user_scope="tenant",
        tenant_id=tenant_id,
    )


def portal_user() -> CurrentUser:
    return CurrentUser(
        user_id=TEST_USER_ID,
        user_type="app_user",
        user_scope="tenant_account",
        tenant_id=TEST_TENANT_ID,
        account_id=TEST_ACCOUNT_ID,
    )


def system_user() -> CurrentUser:
    return CurrentUser(
        user_id=TEST_USER_ID,
        user_type="app_user",
        user_scope="system",
        tenant_id=None,
    )


def _stmt_sql(stmt: object) -> str:
    return str(stmt.compile(dialect=mssql.dialect())).lower()


def test_tenant_missing_tenant_id_is_empty_without_query() -> None:
    db = MagicMock()
    codes = PermissionResolver(db).permission_codes(tenant_user(tenant_id=None))
    assert codes == frozenset()
    db.scalars.assert_not_called()


def test_portal_missing_account_is_empty_without_query() -> None:
    db = MagicMock()
    user = CurrentUser(
        user_id=TEST_USER_ID,
        user_type="app_user",
        user_scope="tenant_account",
        tenant_id=TEST_TENANT_ID,
        account_id=None,
    )
    assert PermissionResolver(db).permission_codes(user) == frozenset()
    db.scalars.assert_not_called()


def test_tenant_sql_requires_membership_and_null_account() -> None:
    db = MagicMock()
    result = MagicMock()
    result.all.return_value = ["screen.lead.view"]
    db.scalars.return_value = result

    codes = PermissionResolver(db).permission_codes(tenant_user())

    assert codes == frozenset({"screen.lead.view"})
    sql = _stmt_sql(db.scalars.call_args.args[0])
    assert "tenant_user" in sql
    assert "account_id" in sql
    assert "is_deleted" in sql
    assert "is_active" in sql


def test_portal_sql_joins_account_membership() -> None:
    db = MagicMock()
    result = MagicMock()
    result.all.return_value = ["screen.lead.view"]
    db.scalars.return_value = result

    PermissionResolver(db).permission_codes(portal_user())

    sql = _stmt_sql(db.scalars.call_args.args[0])
    assert "tenant_account_user" in sql
    assert "tenant_user" not in sql


def test_system_sql_has_no_membership_join() -> None:
    db = MagicMock()
    result = MagicMock()
    result.all.return_value = ["api.auth.role.manage"]
    db.scalars.return_value = result

    codes = PermissionResolver(db).permission_codes(system_user())

    assert "api.auth.role.manage" in codes
    sql = _stmt_sql(db.scalars.call_args.args[0])
    assert "tenant_user" not in sql
    assert "tenant_account_user" not in sql


def test_permission_codes_are_memoized_on_the_resolver() -> None:
    db = MagicMock()
    result = MagicMock()
    result.all.return_value = ["screen.lead.view", "screen.lead.create"]
    db.scalars.return_value = result
    resolver = PermissionResolver(db)
    user = tenant_user()

    first = resolver.permission_codes(user)
    second = resolver.permission_codes(user)

    assert first is second
    assert resolver.has_permission(user, "screen.lead.view") is True
    assert resolver.has_permission(user, "screen.lead.delete") is False
    assert db.scalars.call_count == 1


def test_system_report_grants_are_empty_without_query() -> None:
    db = MagicMock()
    assert PermissionResolver(db).report_grants(system_user()) == {}
    db.execute.assert_not_called()
    db.scalars.assert_not_called()


def test_report_grants_or_across_roles_and_memoize() -> None:
    db = MagicMock()
    db.execute.return_value.all.return_value = [
        ("report-a", True, False),
        ("report-a", True, True),
        ("report-b", True, False),
    ]
    resolver = PermissionResolver(db)
    grants = resolver.report_grants(tenant_user())

    assert grants["report-a"] == ReportGrant("report-a", can_view=True, can_export=True)
    assert grants["report-b"] == ReportGrant("report-b", can_view=True, can_export=False)
    assert resolver.report_grants(tenant_user()) is grants
    assert db.execute.call_count == 1
