"""Apply sql/auth_rbac_seed_v3.sql on live SQL Server and prove it is idempotent."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from mtf.auth.models.default_role_report import DefaultRoleReport
from mtf.auth.models.permission import Permission
from mtf.auth.models.role import Role
from mtf.auth.models.role_permission import RolePermission
from mtf.rpt.models.report_definition import ReportDefinition
from mtf.shared.database import SessionLocal, engine
from tests.auth.test_rbac_seed import EXPECTED_PERMISSIONS, EXPECTED_ROLES, SEED_PATH

pytestmark = pytest.mark.integration

_MTF_REPORT = "tenant_account_list"


def _batches(sql: str) -> list[str]:
    batches: list[str] = []
    current: list[str] = []
    for line in sql.splitlines():
        if line.strip().upper() == "GO":
            batch = "\n".join(current).strip()
            if batch:
                batches.append(batch)
            current = []
        else:
            current.append(line)
    tail = "\n".join(current).strip()
    if tail:
        batches.append(tail)
    return batches


def _apply_seed() -> None:
    sql = Path(SEED_PATH).read_text(encoding="utf-8")
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        for batch in _batches(sql):
            stripped = batch.lstrip()
            if stripped.upper().startswith("USE "):
                continue
            conn.execute(text(batch))


@pytest.fixture(scope="module")
def seeded() -> None:
    if os.environ.get("DEEVO_SKIP_DB_TESTS", "").lower() in ("1", "true", "yes"):
        pytest.skip("DEEVO_SKIP_DB_TESTS is set")
    try:
        with engine.connect() as conn:
            present = conn.execute(text("SELECT OBJECT_ID('auth.permission', 'U')")).scalar()
    except DBAPIError as exc:
        pytest.skip(f"database not available: {exc.__class__.__name__}")
    if present is None:
        pytest.skip("auth.permission is not present; apply sql/auth_rbac_schema_v3.sql")
    _apply_seed()


def test_seed_inserts_platform_catalog(seeded: None) -> None:
    with SessionLocal() as db:
        codes = set(
            db.scalars(select(Permission.code).where(Permission.is_deleted == False)).all()  # noqa: E712
        )
        roles = set(
            db.scalars(
                select(Role.code).where(Role.tenant_id.is_(None), Role.is_deleted == False)  # noqa: E712
            ).all()
        )
    assert EXPECTED_PERMISSIONS <= codes
    assert EXPECTED_ROLES <= roles


def test_tenant_admin_holds_lead_and_role_update(seeded: None) -> None:
    with SessionLocal() as db:
        admin = db.scalars(
            select(Role).where(Role.tenant_id.is_(None), Role.code == "tenant_admin")
        ).first()
        assert admin is not None
        granted = set(
            db.scalars(
                select(Permission.code)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .where(
                    RolePermission.role_id == admin.id,
                    RolePermission.is_deleted == False,  # noqa: E712
                    Permission.is_deleted == False,  # noqa: E712
                )
            ).all()
        )
    assert "screen.lead.view" in granted
    assert "screen.lead.create" in granted
    assert "api.auth.role.update" in granted
    assert "api.system.role.update" not in granted


def test_default_report_grant_for_mtf_sample(seeded: None) -> None:
    with SessionLocal() as db:
        report = db.scalars(
            select(ReportDefinition).where(
                ReportDefinition.report_key == _MTF_REPORT,
                ReportDefinition.scope_type == "system",
                ReportDefinition.is_deleted == False,  # noqa: E712
            )
        ).first()
        if report is None:
            pytest.skip(f"{_MTF_REPORT} is not seeded")
        admin = db.scalars(
            select(Role).where(Role.tenant_id.is_(None), Role.code == "tenant_admin")
        ).one()
        grant = db.scalars(
            select(DefaultRoleReport).where(
                DefaultRoleReport.role_id == admin.id,
                DefaultRoleReport.report_id == report.id,
                DefaultRoleReport.is_deleted == False,  # noqa: E712
            )
        ).first()
    assert grant is not None
    assert grant.can_view is True
    assert grant.can_export is True


def _live_count(table: str) -> int:
    stmt = text(f"SELECT COUNT(*) FROM auth.{table} WHERE is_deleted = 0")
    with SessionLocal() as db:
        return db.execute(stmt).scalar_one()


def test_seed_is_idempotent(seeded: None) -> None:
    before = {
        "permission": _live_count("permission"),
        "role": _live_count("role"),
        "role_permission": _live_count("role_permission"),
        "default_role_report": _live_count("default_role_report"),
    }
    _apply_seed()
    assert _live_count("permission") == before["permission"]
    assert _live_count("role") == before["role"]
    assert _live_count("role_permission") == before["role_permission"]
    assert _live_count("default_role_report") == before["default_role_report"]
