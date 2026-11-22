"""Live SQL Server tests for rbac_fix_02 permission catalog columns.

Every write is rolled back. Skip if ``DEEVO_SKIP_DB_TESTS`` is set or if
the additive script has not been applied.
"""

from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from mtf.auth.models.permission import Permission
from mtf.shared.database import SessionLocal
from mtf.shared.security import generate_id

pytestmark = pytest.mark.integration


@pytest.fixture
def db() -> Generator[Session, None, None]:
    if os.environ.get("DEEVO_SKIP_DB_TESTS", "").lower() in ("1", "true", "yes"):
        pytest.skip("DEEVO_SKIP_DB_TESTS is set")
    session = SessionLocal()
    try:
        session.execute(select(1))
        present = session.execute(
            text(
                """
                SELECT 1
                FROM sys.columns
                WHERE object_id = OBJECT_ID('auth.permission')
                  AND name = 'is_tenant_grantable'
                """
            )
        ).scalar()
    except DBAPIError as exc:
        session.close()
        pytest.skip(f"database not available: {exc.__class__.__name__}")
    if present is None:
        session.close()
        pytest.skip("apply sql/rbac_fix_02_permission_catalog.sql first")
    yield session
    session.rollback()
    session.close()


def _orig(exc: BaseException) -> str:
    return str(getattr(exc, "orig", exc))


def _permission(*, user_scope: str, resource_code: str | None = None) -> Permission:
    token = generate_id()[:10].lower()
    code_part = resource_code or f"pytest_{token}"
    return Permission(
        id=generate_id(),
        code=f"screen.{code_part}.view",
        resource_type="screen",
        resource_code=code_part,
        action="view",
        user_scope=user_scope,
        module_code="GENERAL",
        resource_name=code_part,
        is_tenant_grantable=user_scope != "system",
    )


def test_catalog_columns_and_indexes_exist(db: Session) -> None:
    columns = {
        row[0]
        for row in db.execute(
            text(
                """
                SELECT name
                FROM sys.columns
                WHERE object_id = OBJECT_ID('auth.permission')
                  AND name IN ('module_code', 'resource_name', 'sort_order', 'is_tenant_grantable')
                """
            )
        )
    }
    assert columns == {
        "module_code",
        "resource_name",
        "sort_order",
        "is_tenant_grantable",
    }
    indexes = {
        row[0]
        for row in db.execute(
            text(
                """
                SELECT name
                FROM sys.indexes
                WHERE object_id = OBJECT_ID('auth.permission')
                  AND name IN ('UQ_permission_code', 'UQ_permission_scope_code',
                               'IX_permission_admin_grid')
                """
            )
        )
    }
    assert "UQ_permission_code" not in indexes
    assert "UQ_permission_scope_code" in indexes
    assert "IX_permission_admin_grid" in indexes


def test_system_permission_cannot_be_tenant_grantable(db: Session) -> None:
    row = _permission(user_scope="system")
    row.is_tenant_grantable = True
    db.add(row)
    with pytest.raises(IntegrityError) as exc_info:
        db.flush()
    assert "CK_permission_system_not_grantable" in _orig(exc_info.value)


def test_lowercase_module_code_is_rejected(db: Session) -> None:
    row = _permission(user_scope="tenant")
    row.module_code = "crm"
    db.add(row)
    with pytest.raises(IntegrityError) as exc_info:
        db.flush()
    assert "CK_permission_module_code_upper" in _orig(exc_info.value)


def test_same_code_different_scope_inserts(db: Session) -> None:
    token = generate_id()[:10].lower()
    tenant_row = _permission(user_scope="tenant", resource_code=token)
    portal_row = _permission(user_scope="tenant_account", resource_code=token)
    db.add(tenant_row)
    db.add(portal_row)
    db.flush()
    db.refresh(tenant_row)
    db.refresh(portal_row)
    assert tenant_row.code == portal_row.code
    assert tenant_row.user_scope != portal_row.user_scope


def test_duplicate_scope_and_code_is_rejected(db: Session) -> None:
    token = generate_id()[:10].lower()
    first = _permission(user_scope="tenant", resource_code=token)
    second = _permission(user_scope="tenant", resource_code=token)
    db.add(first)
    db.flush()
    db.add(second)
    with pytest.raises(IntegrityError) as exc_info:
        db.flush()
    assert "UQ_permission_scope_code" in _orig(exc_info.value)
