"""NavMenuService — tree nesting, scope filter, 404 (mocked session)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import mssql

from mtf.nav.services import (
    ItemRow,
    NavMenuService,
    build_menu_tree,
    filter_visible_rows,
    version_iso,
)
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


def _unfiltered(service: NavMenuService) -> NavMenuService:
    """Service with the per-user filter switched off (scope / tree tests)."""
    service._allowed = lambda: None  # type: ignore[method-assign]
    return service


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
    assert tree[1].screen_code is None


def test_build_menu_tree_drops_dead_screens() -> None:
    rows = [
        ItemRow(
            id=REPORT_ITEM_ID,
            parent_id=None,
            code="CRM.BOARD",
            item_type="screen",
            label="Board",
            icon="crm",
            report_key=None,
            sort_order=10,
            updated_at=_NOW,
            report_updated_at=None,
            screen_code=None,
        ),
        ItemRow(
            id=GROUP_ID,
            parent_id=None,
            code="CRM.DASH",
            item_type="screen",
            label="Dashboard",
            icon="crm",
            report_key=None,
            sort_order=20,
            updated_at=_NOW,
            report_updated_at=None,
            screen_code="crm_dashboard",
        ),
    ]
    tree = build_menu_tree(rows)
    assert [row.code for row in tree] == ["CRM.DASH"]
    assert tree[0].screen_code == "crm_dashboard"
    assert tree[0].report_key is None


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

    body = _unfiltered(NavMenuService(db, tenant_user())).list_modules()

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

    body = _unfiltered(NavMenuService(db, portal_user())).list_modules()

    assert body.modules == []
    assert body.version == "1970-01-01T00:00:00.000Z"
    assert "tenant_account" in _params(db.scalars.call_args.args[0]).values()


def test_get_module_items_uppercases_code_and_404s_other_scope() -> None:
    db = MagicMock()
    missing = MagicMock()
    missing.first.return_value = None
    db.scalars.return_value = missing

    with pytest.raises(HTTPException) as exc_info:
        _unfiltered(NavMenuService(db, tenant_user())).get_module_items("crm")

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
        (group, None, None, None, None, None),
        (child, "crm_account_list", _CHILD_NOW, None, None, None),
    ]

    body = _unfiltered(NavMenuService(db, tenant_user())).get_module_items("crm")

    assert body.module.code == "CRM"
    assert body.version == "2026-11-16T09:00:00.123Z"
    assert body.items[0].code == "CRM.SALES"
    assert body.items[0].children[0].report_key == "crm_account_list"
    join_sql = _stmt_sql(db.execute.call_args.args[0])
    assert "nav.menu_item" in join_sql
    assert [MODULE_ID] in _params(db.execute.call_args.args[0]).values()


# --- per-user filtering ------------------------------------------------------


def _row(
    code: str,
    item_type: str,
    *,
    parent_id: str | None = None,
    report_key: str | None = None,
    screen_code: str | None = None,
    permission_code: str | None = None,
    module_id: str = MODULE_ID,
) -> ItemRow:
    return ItemRow(
        id=f"id-{code}",
        parent_id=parent_id,
        code=code,
        item_type=item_type,
        label=code,
        icon=None,
        report_key=report_key,
        sort_order=10,
        updated_at=_NOW,
        report_updated_at=_NOW if report_key else None,
        screen_code=screen_code,
        screen_updated_at=_NOW if screen_code else None,
        permission_code=permission_code,
        module_id=module_id,
    )


def _catalog_rows() -> list[ItemRow]:
    return [
        _row("CRM.LEADS", "report", report_key="crm_lead_list"),
        _row("CRM.ACCOUNTS", "report", report_key="crm_account_list"),
        _row(
            "CRM.NOTES",
            "screen",
            screen_code="crm_notes",
            permission_code="screen.note.view",
        ),
        _row("CRM.NOPERM", "screen", screen_code="crm_orphan_screen"),
        _row("CRM.GROUP", "group"),
        _row("CRM.IN_GROUP", "report", parent_id="id-CRM.GROUP", report_key="crm_task_list"),
        _row("CRM.EMPTY_GROUP", "group"),
    ]


def _codes(rows: list[ItemRow]) -> list[str]:
    return [row.code for row in rows]


def test_filter_none_means_no_filtering() -> None:
    rows = _catalog_rows()
    assert filter_visible_rows(rows, report_keys=None, permission_codes=None) == rows


def test_filter_nothing_granted_hides_everything() -> None:
    rows = _catalog_rows()
    kept = filter_visible_rows(rows, report_keys=frozenset(), permission_codes=frozenset())
    assert kept == []


def test_filter_report_needs_report_grant_not_permission() -> None:
    kept = filter_visible_rows(
        _catalog_rows(),
        report_keys=frozenset({"crm_lead_list"}),
        permission_codes=frozenset({"crm_account_list", "screen.lead.view"}),
    )
    assert _codes(kept) == ["CRM.LEADS"]


def test_filter_screen_needs_its_permission_code() -> None:
    kept = filter_visible_rows(
        _catalog_rows(),
        report_keys=frozenset(),
        permission_codes=frozenset({"screen.note.view"}),
    )
    assert _codes(kept) == ["CRM.NOTES"]


def test_filter_screen_without_permission_code_is_always_hidden() -> None:
    kept = filter_visible_rows(
        _catalog_rows(),
        report_keys=frozenset({"crm_lead_list"}),
        permission_codes=frozenset({"", "crm_orphan_screen", "screen.note.view"}),
    )
    assert "CRM.NOPERM" not in _codes(kept)


def test_filter_group_shows_only_with_a_visible_child() -> None:
    allowed = filter_visible_rows(
        _catalog_rows(),
        report_keys=frozenset({"crm_task_list"}),
        permission_codes=frozenset(),
    )
    assert _codes(allowed) == ["CRM.GROUP", "CRM.IN_GROUP"]
    tree = build_menu_tree(allowed)
    assert [row.code for row in tree] == ["CRM.GROUP"]
    assert [child.code for child in tree[0].children] == ["CRM.IN_GROUP"]


def test_filter_group_cycle_is_hidden_not_infinite() -> None:
    a = _row("A", "group", parent_id="id-B")
    b = _row("B", "group", parent_id="id-A")
    assert filter_visible_rows([a, b], report_keys=frozenset(), permission_codes=frozenset()) == []


class _FakeResolver:
    def __init__(self, codes: set[str]) -> None:
        self._codes = frozenset(codes)

    def permission_codes(self, _user: object) -> frozenset[str]:
        return self._codes


class _FakeCatalog:
    keys: set[str] = set()
    seen_tenant: list[str] = []

    def __init__(self, _db: object, *, user: object, resolver: object) -> None:
        pass

    def list_reports(self, tenant_id: str) -> list[object]:
        type(self).seen_tenant.append(tenant_id)
        return [MagicMock(report_key=key) for key in sorted(type(self).keys)]


def _filtered_service(
    monkeypatch: pytest.MonkeyPatch,
    db: MagicMock,
    user: object,
    *,
    codes: set[str],
    report_keys: set[str],
) -> NavMenuService:
    _FakeCatalog.keys = set(report_keys)
    _FakeCatalog.seen_tenant = []
    monkeypatch.setattr("mtf.nav.services.menu.ReportCatalogService", _FakeCatalog)
    return NavMenuService(db, user, resolver=_FakeResolver(codes))  # type: ignore[arg-type]


def _two_module_db() -> MagicMock:
    crm = minimal_module()
    wf = minimal_module(
        id="01JNAVMTFMD000000000000002",
        code="WF",
        name="Workflow",
        icon="workflow",
        sort_order=20,
    )
    db = MagicMock()
    modules = MagicMock()
    modules.all.return_value = [crm, wf]
    db.scalars.return_value = modules
    lead = minimal_item()
    inbox = minimal_item(
        id="01JNAVMTFME000000000000010",
        module_id="01JNAVMTFMD000000000000002",
        code="WF.INBOX",
        item_type="screen",
        report_id=None,
        screen_id="01JNAVMTFSC000000000000001",
    )
    db.execute.return_value.all.return_value = [
        (lead, "crm_lead_list", _NOW, None, None, None),
        (inbox, None, None, "wf_inbox", _NOW, "menu.wf_inbox.view"),
    ]
    return db


def test_list_modules_hides_modules_with_nothing_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _filtered_service(
        monkeypatch,
        _two_module_db(),
        tenant_user(),
        codes={"menu.wf_inbox.view"},
        report_keys=set(),
    )
    assert [row.code for row in service.list_modules().modules] == ["WF"]
    assert _FakeCatalog.seen_tenant == ["01HZYJZGXM0KV0K4T8Y9ABCDE0"]


def test_list_modules_shows_modules_with_a_visible_report(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _filtered_service(
        monkeypatch,
        _two_module_db(),
        tenant_user(),
        codes=set(),
        report_keys={"crm_lead_list"},
    )
    assert [row.code for row in service.list_modules().modules] == ["CRM"]


def test_list_modules_empty_when_nothing_granted(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _filtered_service(
        monkeypatch, _two_module_db(), tenant_user(), codes=set(), report_keys=set()
    )
    body = service.list_modules()
    assert body.modules == []
    assert body.version == "1970-01-01T00:00:00.000Z"


def test_module_items_only_visible_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _two_module_db()
    found = MagicMock()
    found.first.return_value = minimal_module()
    db.scalars.return_value = found
    service = _filtered_service(
        monkeypatch, db, tenant_user(), codes={"menu.wf_inbox.view"}, report_keys={"crm_lead_list"}
    )
    body = service.get_module_items("crm")
    assert [row.code for row in body.items] == ["CRM.LEADS"]


def test_module_items_404_when_nothing_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _two_module_db()
    found = MagicMock()
    found.first.return_value = minimal_module()
    db.scalars.return_value = found
    service = _filtered_service(monkeypatch, db, tenant_user(), codes=set(), report_keys=set())
    with pytest.raises(HTTPException) as exc_info:
        service.get_module_items("crm")
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["code"] == "NAV_MODULE_NOT_FOUND"


def test_system_caller_is_not_filtered(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.nav.conftest import system_user

    db = _two_module_db()
    service = _filtered_service(monkeypatch, db, system_user(), codes=set(), report_keys=set())
    assert [row.code for row in service.list_modules().modules] == ["CRM", "WF"]
    assert _FakeCatalog.seen_tenant == []
    db.execute.assert_not_called()


def test_tenant_caller_without_tenant_id_sees_no_reports(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _filtered_service(
        monkeypatch,
        _two_module_db(),
        tenant_user(tenant_id=None),
        codes=set(),
        report_keys={"crm_lead_list"},
    )
    assert service.list_modules().modules == []
    assert _FakeCatalog.seen_tenant == []
