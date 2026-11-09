"""auth_rbac_seed_v3.sql — fixed ULIDs, expected codes, no runtime ID generation."""

from __future__ import annotations

import re
from pathlib import Path

SEED_PATH = Path(__file__).resolve().parents[2] / "sql" / "auth_rbac_seed_v3.sql"
CROCKFORD = set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")
ULID_RE = re.compile(r"'([0-9A-Z]{26})'")

EXPECTED_PERMISSIONS = {
    "screen.lead.view",
    "screen.lead.create",
    "screen.lead.update",
    "screen.lead.delete",
    "screen.lead.export",
    "api.auth.role.update",
    "api.system.role.update",
}
EXPECTED_ROLES = {
    "tenant_admin",
    "tenant_member",
    "account_admin",
    "account_member",
    "system_admin",
}


def _sql() -> str:
    return SEED_PATH.read_text(encoding="utf-8")


def test_seed_file_exists() -> None:
    assert SEED_PATH.is_file()


def test_seed_is_idempotent_and_does_not_generate_ids() -> None:
    sql = _sql()
    assert "IF NOT EXISTS" in sql
    assert "NEWID()" not in sql.upper()
    assert "NEWSEQUENTIALID" not in sql.upper()


def test_seed_permission_and_role_codes() -> None:
    sql = _sql()
    for code in EXPECTED_PERMISSIONS:
        assert f"'{code}'" in sql
    for code in EXPECTED_ROLES:
        assert f"'{code}'" in sql
    assert "'api.auth.role.manage'" not in sql
    assert "'manage'" not in sql


def test_seed_ids_are_fixed_crockford_ulids() -> None:
    ids = ULID_RE.findall(_sql())
    seed_ids = [value for value in ids if value.startswith("01JRACMTF")]
    assert seed_ids, "expected literal 01JRACMTF… ULIDs"
    assert len(set(seed_ids)) == len(seed_ids)
    for value in seed_ids:
        assert len(value) == 26
        assert set(value) <= CROCKFORD, value


def test_seed_looks_up_reports_by_key() -> None:
    sql = _sql()
    assert "tenant_account_list" in sql
    assert "crm_lead_list" in sql
    assert "rpt.report_definition" in sql
