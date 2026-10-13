"""ORM mapping tests for ``txn`` metadata tables — no database."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import configure_mappers

from mtf.txn.models import (
    Lookup,
    LookupColumn,
    Screen,
    ScreenField,
    ScreenFieldConfig,
    ScreenPermission,
    ScreenSection,
)


@pytest.fixture(scope="module", autouse=True)
def _configure_mappers_for_fk_resolution() -> None:
    from mtf.auth.models.user import User  # noqa: F401
    from mtf.tenant.models.tenant import Tenant  # noqa: F401

    _ = User.__table__, Tenant.__table__, Screen.__table__
    configure_mappers()


def test_screen_table_location() -> None:
    assert Screen.__table__.schema == "txn"
    assert Screen.__tablename__ == "screen"


def test_screen_column_mapping() -> None:
    names = set(Screen.__mapper__.columns.keys())
    assert {
        "id",
        "screen_key",
        "display_name",
        "api_base_path",
        "layout_type",
        "permission_mode",
        "allow_view",
        "allow_add",
        "allow_edit",
        "allow_delete",
        "row_version",
        "deleted_at",
    }.issubset(names)


def test_screen_audit_foreign_keys_point_at_app_user() -> None:
    targets = {(fk.parent.key, fk.column.table.fullname) for fk in Screen.__table__.foreign_keys}
    assert targets >= {
        ("created_by", "auth.app_user"),
        ("updated_by", "auth.app_user"),
        ("deleted_by", "auth.app_user"),
    }


def test_lookup_includes_display_field_key() -> None:
    names = set(Lookup.__mapper__.columns.keys())
    assert "return_field_key" in names
    assert "display_field_key" in names
    assert Lookup.__table__.c.display_field_key.nullable is True


def _fk_targets(model: type) -> set[tuple[str, str]]:
    return {(fk.parent.key, fk.column.table.fullname) for fk in model.__table__.foreign_keys}


def test_child_table_locations_and_parents() -> None:
    assert ScreenSection.__table__.schema == "txn"
    assert ScreenField.__table__.schema == "txn"
    assert ScreenFieldConfig.__table__.schema == "txn"
    assert ScreenPermission.__table__.schema == "txn"
    assert LookupColumn.__table__.schema == "txn"

    assert ("screen_id", "txn.screen") in _fk_targets(ScreenSection)
    assert {
        ("screen_id", "txn.screen"),
        ("section_id", "txn.screen_section"),
        ("lookup_id", "txn.lookup"),
    } <= _fk_targets(ScreenField)
    assert {("tenant_id", "tenant.tenant"), ("field_id", "txn.screen_field")} <= _fk_targets(
        ScreenFieldConfig
    )
    assert {
        ("tenant_id", "tenant.tenant"),
        ("user_id", "auth.app_user"),
        ("screen_id", "txn.screen"),
    } <= _fk_targets(ScreenPermission)


def test_screen_field_numeric_bounds() -> None:
    assert str(ScreenField.__table__.c.min_value.type) == "NUMERIC(38, 10)"
    assert str(ScreenField.__table__.c.max_value.type) == "NUMERIC(38, 10)"
