"""ORM mapping tests for ``tenant.tenant_account`` and ``tenant.tenant_account_address``."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import configure_mappers

from mtf.tenant.models.tenant_account import TenantAccount
from mtf.tenant.models.tenant_account_address import TenantAccountAddress

from tests.tenant.conftest import minimal_tenant_account, minimal_tenant_account_address


@pytest.fixture(scope="module", autouse=True)
def _configure_mappers_for_fk_resolution() -> None:
    from mtf.auth.models.user import User  # noqa: F401
    from mtf.tenant.models.tenant import Tenant  # noqa: F401

    _ = User.__table__, Tenant.__table__, TenantAccount.__table__, TenantAccountAddress.__table__
    configure_mappers()


def test_tenant_account_table_location() -> None:
    assert TenantAccount.__table__.schema == "tenant"
    assert TenantAccount.__tablename__ == "tenant_account"


def test_tenant_account_columns() -> None:
    names = set(TenantAccount.__mapper__.columns.keys())
    assert names == {
        "id",
        "tenant_id",
        "account_code",
        "account_type",
        "name",
        "email",
        "phone",
        "website",
        "custom_fields",
        "status",
        "is_active",
        "is_deleted",
        "row_version",
        "created_at",
        "updated_at",
        "created_by",
        "updated_by",
        "deleted_by",
    }


def test_tenant_account_foreign_keys() -> None:
    targets = {(fk.parent.key, fk.column.table.fullname, fk.column.key) for fk in TenantAccount.__table__.foreign_keys}
    assert ("tenant_id", "tenant.tenant", "id") in targets
    audit = {fk.parent.key for fk in TenantAccount.__table__.foreign_keys if fk.column.table.fullname == "auth.app_user"}
    assert audit == {"created_by", "updated_by", "deleted_by"}


def test_tenant_account_repr() -> None:
    row = minimal_tenant_account(name="Globex")
    assert "TenantAccount" in repr(row)


def test_tenant_account_address_table_location() -> None:
    assert TenantAccountAddress.__table__.schema == "tenant"
    assert TenantAccountAddress.__tablename__ == "tenant_account_address"


def test_tenant_account_address_columns() -> None:
    names = set(TenantAccountAddress.__mapper__.columns.keys())
    assert "tenant_id" in names
    assert "account_id" in names
    assert "address_type" in names
    assert "is_default" in names


def test_tenant_account_address_foreign_keys() -> None:
    for fk in TenantAccountAddress.__table__.foreign_keys:
        if fk.parent.key == "account_id":
            assert fk.column.table.fullname == "tenant.tenant_account"
        elif fk.parent.key == "tenant_id":
            assert fk.column.table.fullname == "tenant.tenant"
        else:
            assert fk.column.table.fullname == "auth.app_user"


def test_tenant_account_address_repr() -> None:
    row = minimal_tenant_account_address(address_type="shipping")
    assert "TenantAccountAddress" in repr(row)
