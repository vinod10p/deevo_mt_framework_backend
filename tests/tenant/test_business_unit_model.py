"""ORM mapping tests for ``tenant.business_unit`` and the shared column helpers — no database."""

from __future__ import annotations

import pytest
from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import configure_mappers

from mtf.shared.model_columns import RecordStateMixin, StandardColumnsMixin
from mtf.tenant.models.business_unit import BU_TYPE_ROOT, BU_TYPE_STORE, BU_TYPES, BusinessUnit

_STANDARD = {
    "is_active",
    "is_deleted",
    "row_version",
    "created_at",
    "updated_at",
    "created_by",
    "updated_by",
    "deleted_at",
    "deleted_by",
}


@pytest.fixture(scope="module", autouse=True)
def _configure_mappers_for_fk_resolution() -> None:
    from mtf.auth.models.user import User  # noqa: F401
    from mtf.tenant.models.tenant import Tenant  # noqa: F401

    configure_mappers()


def test_table_location() -> None:
    assert BusinessUnit.__table__.schema == "tenant"
    assert BusinessUnit.__tablename__ == "business_unit"


def test_columns_match_ddl() -> None:
    assert set(BusinessUnit.__mapper__.columns.keys()) == _STANDARD | {
        "id",
        "tenant_id",
        "parent_id",
        "bu_type",
        "code",
        "name",
        "address_line1",
        "address_line2",
        "city",
        "state",
        "postal_code",
        "country",
        "timezone",
        "currency",
        "sort_order",
    }


def test_nullability() -> None:
    cols = BusinessUnit.__table__.columns
    for name in ("tenant_id", "bu_type", "code", "name", "sort_order"):
        assert cols[name].nullable is False, name
    for name in ("parent_id", "timezone", "currency"):
        assert cols[name].nullable is True, name


def test_id_tenant_unique_is_the_composite_fk_target() -> None:
    uniques = {
        (constraint.name, tuple(col.name for col in constraint.columns))
        for constraint in BusinessUnit.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("UQ_business_unit_id_tenant", ("id", "tenant_id")) in uniques


def test_parent_must_be_in_same_tenant() -> None:
    parent_fk = next(
        constraint
        for constraint in BusinessUnit.__table__.foreign_key_constraints
        if constraint.name == "FK_business_unit_parent"
    )
    assert parent_fk.column_keys == ["parent_id", "tenant_id"]
    assert [element.target_fullname for element in parent_fk.elements] == [
        "tenant.business_unit.id",
        "tenant.business_unit.tenant_id",
    ]


def test_bu_types_match_check_constraint() -> None:
    assert BU_TYPES == {"root", "store", "warehouse", "workshop", "online"}
    assert {BU_TYPE_ROOT, BU_TYPE_STORE} <= BU_TYPES


def test_is_root() -> None:
    assert BusinessUnit(bu_type="root").is_root is True
    assert BusinessUnit(bu_type="store").is_root is False


def test_repr_includes_identity() -> None:
    row = BusinessUnit(
        id="01JBXM0000000000000000000A", tenant_id="t1", bu_type="store", code="MAIN"
    )
    assert "BusinessUnit" in repr(row)
    assert "MAIN" in repr(row)


def test_standard_columns_mixin_adds_created_and_updated_by() -> None:
    record_state = set(RecordStateMixin.__annotations__)
    standard = record_state | set(StandardColumnsMixin.__annotations__)
    assert "created_by" not in record_state
    assert standard == _STANDARD
