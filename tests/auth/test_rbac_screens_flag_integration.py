"""Live SQL Server: apply rbac_fix_03_screens_flag.sql and prove the one-way flag."""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from mtf.shared.database import SessionLocal, engine
from mtf.shared.security import generate_id
from mtf.tenant.models.tenant import Tenant
from mtf.tenant.models.tenant_setting import TenantSetting
from mtf.tenant.services.rbac_screens import RBAC_SCREENS_KEY, RBAC_SCREENS_ON
from tests.auth.test_rbac_fix_03 import FIX_PATH

pytestmark = pytest.mark.integration


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


def _apply_fix() -> None:
    sql = Path(FIX_PATH).read_text(encoding="utf-8")
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        try:
            for batch in _batches(sql):
                if batch.lstrip().upper().startswith("USE "):
                    continue
                conn.execute(text(batch))
        finally:
            # Scripts set NOCOUNT ON; a pooled connection that keeps it makes
            # SQLAlchemy see rowcount -1 (StaleDataError) in later tests.
            conn.execute(text("SET NOCOUNT OFF; SET XACT_ABORT OFF"))


def _orig(exc: BaseException) -> str:
    return str(getattr(exc, "orig", exc))


@pytest.fixture(scope="module")
def applied() -> None:
    if os.environ.get("DEEVO_SKIP_DB_TESTS", "").lower() in ("1", "true", "yes"):
        pytest.skip("DEEVO_SKIP_DB_TESTS is set")
    try:
        with engine.connect() as conn:
            present = conn.execute(text("SELECT OBJECT_ID('tenant.tenant_setting', 'U')")).scalar()
    except DBAPIError as exc:
        pytest.skip(f"database not available: {exc.__class__.__name__}")
    if present is None:
        pytest.skip("tenant.tenant_setting is not present")
    _apply_fix()


@pytest.fixture
def db(applied: None) -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        try:
            session.execute(text("SET NOCOUNT OFF"))
            session.commit()
        except Exception:
            session.rollback()
        session.close()


def test_index_and_trigger_exist(applied: None) -> None:
    with SessionLocal() as db:
        index_name = db.execute(
            text(
                """
                SELECT name
                FROM sys.indexes
                WHERE object_id = OBJECT_ID('tenant.tenant_setting')
                  AND name IN ('UQ_tenant_setting_tenant_key', 'UX_tenant_setting_tenant_key')
                """
            )
        ).scalar()
        trigger_name = db.execute(
            text(
                """
                SELECT name
                FROM sys.triggers
                WHERE parent_id = OBJECT_ID('tenant.tenant_setting')
                  AND name = 'TR_tenant_setting_rbac_screens_one_way'
                """
            )
        ).scalar()
    assert index_name in {
        "UQ_tenant_setting_tenant_key",
        "UX_tenant_setting_tenant_key",
    }
    assert trigger_name == "TR_tenant_setting_rbac_screens_one_way"


def test_every_live_tenant_has_screens_flag(applied: None) -> None:
    with SessionLocal() as db:
        missing = db.execute(
            text(
                """
                SELECT t.id
                FROM tenant.tenant t
                WHERE t.is_deleted = 0
                  AND NOT EXISTS (
                        SELECT 1
                        FROM tenant.tenant_setting s
                        WHERE s.tenant_id = t.id
                          AND s.[key] = 'rbac.screens'
                          AND s.[value] = N'on'
                          AND s.is_active = 1
                          AND s.is_deleted = 0
                  )
                """
            )
        ).fetchall()
    assert missing == []


def test_duplicate_live_key_is_rejected(db: Session) -> None:
    row = db.scalars(
        select(TenantSetting).where(
            TenantSetting.key == RBAC_SCREENS_KEY,
            TenantSetting.is_deleted == False,  # noqa: E712
        )
    ).first()
    if row is None:
        pytest.skip("no live rbac.screens row")
    db.add(
        TenantSetting(
            id=generate_id(),
            tenant_id=row.tenant_id,
            key=RBAC_SCREENS_KEY,
            value=RBAC_SCREENS_ON,
        )
    )
    with pytest.raises(IntegrityError) as exc_info:
        db.flush()
    err = _orig(exc_info.value)
    assert "tenant_setting_tenant_key" in err


def test_cannot_turn_flag_off(db: Session) -> None:
    row = db.scalars(
        select(TenantSetting).where(
            TenantSetting.key == RBAC_SCREENS_KEY,
            TenantSetting.value == RBAC_SCREENS_ON,
            TenantSetting.is_deleted == False,  # noqa: E712
        )
    ).first()
    if row is None:
        pytest.skip("no live rbac.screens=on row")
    row.value = "off"
    db.add(row)
    with pytest.raises(DBAPIError) as exc_info:
        db.flush()
    assert "51032" in _orig(exc_info.value)


def test_cannot_soft_delete_flag(db: Session) -> None:
    row = db.scalars(
        select(TenantSetting).where(
            TenantSetting.key == RBAC_SCREENS_KEY,
            TenantSetting.value == RBAC_SCREENS_ON,
            TenantSetting.is_deleted == False,  # noqa: E712
        )
    ).first()
    if row is None:
        pytest.skip("no live rbac.screens=on row")
    row.is_deleted = True
    db.add(row)
    with pytest.raises(DBAPIError) as exc_info:
        db.flush()
    assert "51032" in _orig(exc_info.value)


def test_cannot_hard_delete_flag(db: Session) -> None:
    row = db.scalars(
        select(TenantSetting).where(
            TenantSetting.key == RBAC_SCREENS_KEY,
            TenantSetting.is_deleted == False,  # noqa: E712
        )
    ).first()
    if row is None:
        pytest.skip("no live rbac.screens row")
    db.delete(row)
    with pytest.raises(DBAPIError) as exc_info:
        db.flush()
    assert "51030" in _orig(exc_info.value)


def test_insert_must_be_on(db: Session) -> None:
    tenant = Tenant(
        id=generate_id(),
        name="RBAC screens flag pytest",
        subdomain=f"rbac-flag-{generate_id()[:10].lower()}",
    )
    db.add(tenant)
    db.flush()
    db.add(
        TenantSetting(
            id=generate_id(),
            tenant_id=tenant.id,
            key=RBAC_SCREENS_KEY,
            value="off",
        )
    )
    with pytest.raises(DBAPIError) as exc_info:
        db.flush()
    assert "51031" in _orig(exc_info.value)
