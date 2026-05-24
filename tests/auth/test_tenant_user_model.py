"""Tests for ``TenantUser`` ORM model (`auth.tenant_user`).

These tests do not require a database connection. They assert table mapping,
columns, foreign keys (after related models are registered on the same
metadata), and ``__repr__`` output.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import configure_mappers

from mtf.auth.models.tenant_user import TenantUser


@pytest.fixture(scope="module", autouse=True)
def _configure_mappers_for_fk_resolution() -> None:
    """``TenantUser`` references ``tenant.tenant``; load related models so FK targets resolve."""
    from mtf.auth.models.user import User  # noqa: F401
    from mtf.tenant.models.tenant import Tenant  # noqa: F401

    _ = User.__table__, Tenant.__table__
    configure_mappers()


def test_tenant_user_table_location() -> None:
    assert TenantUser.__table__.schema == "auth"
    assert TenantUser.__tablename__ == "tenant_user"


def test_tenant_user_column_mapping() -> None:
    names = set(TenantUser.__mapper__.columns.keys())
    assert names == {
        "id",
        "tenant_id",
        "user_id",
        "role",
        "invited_at",
        "invited_by",
        "invite_token",
        "joined_at",
        "is_active",
        "is_deleted",
        "row_version",
        "created_at",
        "updated_at",
        "created_by",
        "updated_by",
        "deleted_by",
    }


def test_tenant_user_foreign_key_targets() -> None:
    targets = {(fk.column.table.fullname, fk.column.key) for fk in TenantUser.__table__.foreign_keys}
    assert ("tenant.tenant", "id") in targets
    assert ("auth.app_user", "id") in targets
    # All app_user FKs should point at auth.app_user.id
    assert all(fk.column.table.fullname == "auth.app_user" for fk in TenantUser.__table__.foreign_keys if fk.parent.key != "tenant_id")


def test_tenant_user_repr_includes_core_fields() -> None:
    row = TenantUser(
        id="01HZYJZGXM0KV0K4T8Y9ABCDEF",
        tenant_id="01HZYJZGXM0KV0K4T8Y9ABCDE0",
        user_id="01HZYJZGXM0KV0K4T8Y9ABCDE1",
        role="member",
    )
    out = repr(row)
    assert "TenantUser" in out
    assert "01HZYJZGXM0KV0K4T8Y9ABCDEF" in out
    assert "01HZYJZGXM0KV0K4T8Y9ABCDE0" in out
    assert "01HZYJZGXM0KV0K4T8Y9ABCDE1" in out
    assert "member" in out
