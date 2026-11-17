"""nav_menu_seed_v1.sql — fixed ULIDs, expected codes, lookup by report_key."""

from __future__ import annotations

import re
from pathlib import Path

SEED_PATH = Path(__file__).resolve().parents[2] / "sql" / "nav_menu_seed_v1.sql"
CROCKFORD = set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")
ULID_RE = re.compile(r"'([0-9A-Z]{26})'")

EXPECTED_MODULES = ("CRM", "WF", "EMAIL")
EXPECTED_ITEMS = (
    "CRM.LEADS",
    "CRM.ACCOUNTS",
    "CRM.CONTACTS",
    "CRM.OPPORTUNITIES",
    "CRM.TASKS",
    "WF.TASKS",
    "WF.TASKS.MINE",
    "WF.TASKS.ALL",
    "EMAIL.INBOX",
    "EMAIL.SENT",
)
EXPECTED_REPORTS = (
    "crm_lead_list",
    "crm_account_list",
    "crm_contact_list",
    "crm_opportunity_list",
    "crm_task_list",
    "tenant_user_list",
    "tenant_account_list",
    "portal_user_list",
)


def _sql() -> str:
    return SEED_PATH.read_text(encoding="utf-8")


def test_seed_file_exists() -> None:
    assert SEED_PATH.is_file()


def test_seed_is_idempotent_and_does_not_generate_ids() -> None:
    sql = _sql()
    assert "IF NOT EXISTS" in sql
    assert "NEWID()" not in sql.upper()
    assert "NEWSEQUENTIALID" not in sql.upper()
    assert "user_scope = 'tenant'" in sql
    assert "user_scope = 'tenant_account'" not in sql
    assert "user_scope = 'system'" not in sql


def test_seed_module_and_item_codes() -> None:
    sql = _sql()
    for code in EXPECTED_MODULES:
        assert f"'{code}'" in sql
    for code in EXPECTED_ITEMS:
        assert f"'{code}'" in sql
    for key in EXPECTED_REPORTS:
        assert f"'{key}'" in sql
    assert "rpt.report_definition" in sql


def test_seed_ids_are_fixed_crockford_ulids() -> None:
    ids = ULID_RE.findall(_sql())
    seed_ids = [value for value in ids if value.startswith("01JNAVMTF")]
    assert seed_ids, "expected literal 01JNAVMTF… ULIDs"
    assert len(set(seed_ids)) == len(seed_ids)
    for value in seed_ids:
        assert len(value) == 26
        assert set(value) <= CROCKFORD, value
