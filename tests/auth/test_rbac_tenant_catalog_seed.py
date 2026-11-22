"""sql/auth_rbac_seed_tenant_catalog_v1.sql — static checks (no database)."""

from __future__ import annotations

import re
from pathlib import Path

SEED_PATH = (
    Path(__file__).resolve().parents[2] / "sql" / "auth_rbac_seed_tenant_catalog_v1.sql"
)
CROCKFORD = set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")
ULID_RE = re.compile(r"'([0-9A-Z]{26})'")

CRM_RESOURCES = ("lead", "account", "contact", "opportunity", "task", "note")
CRM_ACTIONS = ("view", "create", "update", "delete", "export")
WF_CODES = ("wf_inbox", "wf_mine", "wf_all", "wf_templates")

EXPECTED_PERMISSIONS = {
    *(f"screen.{resource}.{action}" for resource in CRM_RESOURCES for action in CRM_ACTIONS),
    *(f"menu.{code}.view" for code in WF_CODES),
    "api.auth.role.update",
    "api.system.role.update",
}


def _sql() -> str:
    return SEED_PATH.read_text(encoding="utf-8")


def test_seed_file_exists() -> None:
    assert SEED_PATH.is_file()


def test_seed_is_idempotent_and_does_not_generate_ids() -> None:
    sql = _sql()
    assert "NOT EXISTS" in sql
    assert "NEWID()" not in sql.upper()
    assert "NEWSEQUENTIALID" not in sql.upper()
    assert "THROW 51020" in sql


def test_seed_permission_codes_and_modules() -> None:
    sql = _sql()
    for code in EXPECTED_PERMISSIONS:
        assert f"'{code}'" in sql
    assert "'CRM'" in sql
    assert "'WF'" in sql
    assert "'GENERAL'" in sql
    assert "'menu.wf_inbox.view'" in sql
    assert "'api.auth.role.manage'" not in sql
    assert sql.count("'system'") >= 1
    assert "is_tenant_grantable" in sql


def test_wf_rows_are_menu_view_only() -> None:
    sql = _sql()
    for code in WF_CODES:
        assert f"'menu.{code}.view'" in sql
        assert f"'screen.{code}." not in sql
        assert f"'menu.{code}.create'" not in sql


def test_seed_ids_are_fixed_crockford_ulids() -> None:
    ids = ULID_RE.findall(_sql())
    seed_ids = [value for value in ids if value.startswith("01JRACMTF")]
    assert seed_ids, "expected literal 01JRACMTF… ULIDs"
    assert len(set(seed_ids)) == len(seed_ids)
    for value in seed_ids:
        assert len(value) == 26
        assert set(value) <= CROCKFORD, value
