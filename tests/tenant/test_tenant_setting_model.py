"""ORM mapping tests for ``tenant.tenant_setting`` — no database."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import configure_mappers

from mtf.tenant.models.tenant import Tenant
from mtf.tenant.models.tenant_setting import TenantSetting


@pytest.fixture(scope="module", autouse=True)
def _configure_mappers_for_fk_resolution() -> None:
    from mtf.auth.models.user import User  # noqa: F401

    _ = User.__table__, Tenant.__table__, TenantSetting.__table__
    configure_mappers()


def test_tenant_setting_table_location() -> None:
    assert TenantSetting.__table__.schema == "tenant"
    assert TenantSetting.__tablename__ == "tenant_setting"
    assert TenantSetting.__table__.implicit_returning is False


def test_tenant_setting_column_mapping() -> None:
    names = set(TenantSetting.__mapper__.columns.keys())
    assert {"id", "tenant_id", "key", "value", "is_active", "is_deleted", "row_version"}.issubset(
        names
    )


def test_tenant_setting_repr() -> None:
    row = TenantSetting(
        id="01HZYJZGXM0KV0K4T8Y9SETTNG",
        tenant_id="01HZYJZGXM0KV0K4T8Y9ABCDE0",
        key="rbac.screens",
        value="on",
    )
    assert "rbac.screens" in repr(row)
    assert "TenantSetting" in repr(row)
