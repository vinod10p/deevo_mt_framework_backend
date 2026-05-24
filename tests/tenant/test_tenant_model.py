"""ORM mapping tests for ``tenant.tenant`` — no database."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import configure_mappers

from mtf.tenant.models.tenant import Tenant

from tests.tenant.conftest import minimal_tenant


@pytest.fixture(scope="module", autouse=True)
def _configure_mappers_for_fk_resolution() -> None:
    from mtf.auth.models.user import User  # noqa: F401

    _ = User.__table__, Tenant.__table__
    configure_mappers()


def test_tenant_table_location() -> None:
    assert Tenant.__table__.schema == "tenant"
    assert Tenant.__tablename__ == "tenant"


def test_tenant_column_mapping() -> None:
    names = set(Tenant.__mapper__.columns.keys())
    assert {"id", "name", "status", "plan_type", "row_version", "features_enabled", "country"}.issubset(names)


def test_tenant_audit_foreign_keys_point_at_app_user() -> None:
    targets = {(fk.parent.key, fk.column.table.fullname) for fk in Tenant.__table__.foreign_keys}
    assert targets >= {
        ("created_by", "auth.app_user"),
        ("updated_by", "auth.app_user"),
        ("deleted_by", "auth.app_user"),
    }


def test_tenant_repr() -> None:
    row = minimal_tenant(name="Contoso")
    assert "Contoso" in repr(row)
    assert "Tenant" in repr(row)
