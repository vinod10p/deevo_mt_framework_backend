"""sql/nav_menu_fix_01_permissions.sql — static checks (no database)."""

from __future__ import annotations

from pathlib import Path

FIX_PATH = Path(__file__).resolve().parents[2] / "sql" / "nav_menu_fix_01_permissions.sql"


def _sql() -> str:
    return FIX_PATH.read_text(encoding="utf-8")


def test_fix_file_exists() -> None:
    assert FIX_PATH.is_file()


def test_adds_nullable_permission_code_idempotently() -> None:
    sql = _sql()
    assert "COL_LENGTH('nav.screen', 'permission_code') IS NULL" in sql
    assert "ADD permission_code varchar(150) NULL" in sql


def test_maps_every_known_tenant_screen() -> None:
    sql = _sql()
    for screen, permission in {
        "wf_inbox": "menu.wf_inbox.view",
        "wf_mine": "menu.wf_mine.view",
        "wf_all": "menu.wf_all.view",
        "wf_templates": "menu.wf_templates.view",
        "crm_notes": "screen.note.view",
        "crm_lookups": "menu.crm_lookups.view",
        "admin_users": "menu.admin_users.view",
        "admin_portal_accounts": "menu.admin_portal_accounts.view",
    }.items():
        assert f"('{screen}'" in sql
        assert f"'{permission}')" in sql


def test_admin_screens_are_admin_only_and_lookups_are_not_templated() -> None:
    sql = _sql()
    lookups = next(line for line in sql.splitlines() if "'menu.crm_lookups.view'," in line)
    assert "NULL, NULL)," in lookups or lookups.rstrip().endswith("NULL),")
    for code in ("menu.admin_users.view", "menu.admin_portal_accounts.view"):
        line = next(line for line in sql.splitlines() if f"'{code}'," in line)
        assert "'01JRACNAVGM" not in line
        assert line.rstrip().rstrip(",;").endswith("NULL)")


def test_new_ids_are_26_chars_and_unique() -> None:
    import re

    ids = re.findall(r"'(01JRACNAV[A-Z]{2}[0-9A-Z]{15})'", _sql())
    assert ids
    assert all(len(value) == 26 for value in ids)
    assert len(set(ids)) == len(ids)


def test_does_not_touch_assignments_or_custom_roles() -> None:
    sql = _sql()
    assert "auth.user_role" not in sql
    assert "tenant_id IS NULL AND code = 'tenant_admin'" in sql


def test_header_has_no_nested_comment_openers() -> None:
    # SQL Server nests block comments; a stray slash-star in the header breaks the batch.
    header = _sql().split("*/", 1)[0]
    assert header.count("/*") == 1
