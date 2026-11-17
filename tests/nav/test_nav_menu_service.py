"""NavMenuService — tree nesting, scope filter, 404 (mocked session)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import mssql

from mtf.nav.services import ItemRow, NavMenuService, build_menu_tree, version_iso
from tests.nav.conftest import (
    _NOW,
    CHILD_ITEM_ID,
    GROUP_ID,
    MODULE_ID,
    REPORT_ITEM_ID,
    minimal_item,
    minimal_module,
    portal_user,
    tenant_user,
)

_CHILD_NOW = datetime(2026, 11, 16, 9, 0, 0, 123000)


def _params(stmt: object) -> dict[str, object]:
    return stmt.compile(dialect=mssql.dialect()).params  # type: ignore[attr-defined]


def _stmt_sql(stmt: object) -> str:
    return str(stmt.compile(dialect=mssql.dialect()))  # type: ignore[attr-defined]


def test_version_iso_naive_utc_milliseconds() -> None:
    assert version_iso(_NOW) == "2026-11-16T08:12:34.567Z"
    assert version_iso(None) == "1970-01-01T00:00:00.000Z"
    aware = datetime(2026, 11, 16, 8, 12, 34, 567000, tzinfo=timezone.utc)
    assert version_iso(aware) == "2026-11-16T08:12:34.567Z"


def test_build_menu_tree_nests_and_sorts() -> None:
    rows = [
        ItemRow(
            id=REPORT_ITEM_ID,
            parent_id=None,
            code="CRM.LEADS",
            item_type="report",
            label="Leads",
            icon="users",
            report_key="crm_lead_list",
            sort_order=20,
            updated_at=_NOW,
            report_updated_at=_NOW,
        ),
        ItemRow(
            id=GROUP_ID,
            parent_id=None,
            code="CRM.SALES",
            item_type="group",
            label="Sales",
            icon="folder",
            report_key=None,
            sort_order=10,
            updated_at=_NOW,
            report_updated_at=None,
        ),
        ItemRow(
            id=CHILD_ITEM_ID,
            parent_id=GROUP_ID,
            code="CRM.ACCOUNTS",
            item_type="report",
            label="Accounts",
            icon="building",
            report_key="crm_account_list",
            sort_order=10,
            updated_at=_NOW,
            report_updated_at=_NOW,
        ),
        ItemRow(
            id="01JNAVMTFME000000000000099",
            parent_id=GROUP_ID,
            code="CRM.ZZZ",
            item_type="report",
            label="Zed",
            icon=None,
            report_key="crm_zzz",
            sort_order=10,
            updated_at=_NOW,
            report_updated_at=_NOW,
        ),
    ]
    tree = build_menu_tree(rows)
    assert [row.code for row in tree] == ["CRM.SALES", "CRM.LEADS"]
    assert tree[0].item_type == "group"
    assert tree[0].report_key is None
    assert [child.code for child in tree[0].children] == ["CRM.ACCOUNTS", "CRM.ZZZ"]
    assert tree[1].children == []
    assert tree[1].report_key == "crm_lead_list"


def test_build_menu_tree_drops_dead_reports_and_orphan_children() -> None:
    rows = [
        ItemRow(
            id=GROUP_ID,
            parent_id=None,
            code="CRM.SALES",
            item_type="group",
            label="Sales",
            icon="folder",
            report_key=None,
            sort_order=10,
            updated_at=_NOW,
            report_updated_at=None,
        ),
        ItemRow(
            id=REPORT_ITEM_ID,
            parent_id=None,
            code="CRM.LEADS",
            item_type="report",
            label="Leads",
            icon="users",
            report_key=None,
            sort_order=20,
            updated_at=_NOW,
            report_updated_at=None,
        ),
        ItemRow(
            id=CHILD_ITEM_ID,
            parent_id="01JNAVMTFMEDEADPARENT00001",
            code="CRM.ORPHAN",
            item_type="report",
            label="Orphan",
            icon=None,
            report_key="crm_orphan",
            sort_order=10,
            updated_at=_NOW,
            report_updated_at=_NOW,
        ),
    ]
    tree = build_menu_tree(rows)
    assert [row.code for row in tree] == ["CRM.SALES"]
    assert tree[0].children == []


def test_list_modules_filters_jwt_scope() -> None:
    crm = minimal_module()
    wf = minimal_module(
        id="01JNAVMTFMD000000000000002",
        code="WF",
        name="Workflow",
        icon="workflow",
        sort_order=20,
        updated_at=_CHILD_NOW,
    )
    db = MagicMock()
    result = MagicMock()
    result.all.return_value = [crm, wf]
    db.scalars.return_value = result

    body = NavMenuService(db, tenant_user()).list_modules()

    assert [row.code for row in body.modules] == ["CRM", "WF"]
    assert body.version == "2026-11-16T09:00:00.123Z"
    stmt = db.scalars.call_args.args[0]
    params = _params(stmt)
    assert "tenant" in params.values()
    assert "tenant_account" not in params.values()
    sql = _stmt_sql(stmt)
    assert "nav.menu_module" in sql


def test_list_modules_empty_uses_epoch_version() -> None:
    db = MagicMock()
    result = MagicMock()
    result.all.return_value = []
    db.scalars.return_value = result

    body = NavMenuService(db, portal_user()).list_modules()

    assert body.modules == []
    assert body.version == "1970-01-01T00:00:00.000Z"
    assert "tenant_account" in _params(db.scalars.call_args.args[0]).values()


def test_get_module_items_uppercases_code_and_404s_other_scope() -> None:
    db = MagicMock()
    missing = MagicMock()
    missing.first.return_value = None
    db.scalars.return_value = missing

    with pytest.raises(HTTPException) as exc_info:
        NavMenuService(db, tenant_user()).get_module_items("crm")

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["code"] == "NAV_MODULE_NOT_FOUND"
    params = _params(db.scalars.call_args.args[0])
    assert "CRM" in params.values()
    assert "tenant" in params.values()


def test_get_module_items_builds_tree_and_version() -> None:
    module = minimal_module()
    group = minimal_item(
        id=GROUP_ID,
        code="CRM.SALES",
        item_type="group",
        label="Sales",
        icon="folder",
        report_id=None,
        sort_order=10,
    )
    child = minimal_item(
        id=CHILD_ITEM_ID,
        parent_id=GROUP_ID,
        code="CRM.ACCOUNTS",
        item_type="report",
        label="Accounts",
        icon="building",
        sort_order=10,
        updated_at=_CHILD_NOW,
    )
    db = MagicMock()
    found = MagicMock()
    found.first.return_value = module
    db.scalars.return_value = found
    db.execute.return_value.all.return_value = [
        (group, None, None),
        (child, "crm_account_list", _CHILD_NOW),
    ]

    body = NavMenuService(db, tenant_user()).get_module_items("crm")

    assert body.module.code == "CRM"
    assert body.version == "2026-11-16T09:00:00.123Z"
    assert body.items[0].code == "CRM.SALES"
    assert body.items[0].children[0].report_key == "crm_account_list"
    join_sql = _stmt_sql(db.execute.call_args.args[0])
    assert "nav.menu_item" in join_sql
    assert MODULE_ID in _params(db.execute.call_args.args[0]).values()
