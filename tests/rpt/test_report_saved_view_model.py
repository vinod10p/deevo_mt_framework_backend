"""ORM mapping tests for ``rpt.report_saved_view``."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import configure_mappers

from mtf.rpt.models import ReportSavedView


@pytest.fixture(scope="module", autouse=True)
def _configure_mappers_for_fk_resolution() -> None:
    from mtf.auth.models.user import User  # noqa: F401
    from mtf.rpt.models import ReportDefinition  # noqa: F401
    from mtf.tenant.models.tenant import Tenant  # noqa: F401

    configure_mappers()


def test_table_location() -> None:
    assert ReportSavedView.__table__.schema == "rpt"
    assert ReportSavedView.__tablename__ == "report_saved_view"


def test_columns_match_ddl() -> None:
    assert set(ReportSavedView.__mapper__.columns.keys()) == {
        "id",
        "tenant_id",
        "report_id",
        "scope_type",
        "user_id",
        "view_name",
        "criteria_json",
        "layout_json",
        "is_default",
        "is_active",
        "is_deleted",
        "row_version",
        "created_at",
        "updated_at",
        "created_by",
        "updated_by",
        "deleted_by",
    }


def test_nullability() -> None:
    cols = ReportSavedView.__table__.columns
    assert cols["tenant_id"].nullable is True
    assert cols["user_id"].nullable is True
    for name in ("report_id", "scope_type", "view_name", "criteria_json", "layout_json"):
        assert cols[name].nullable is False, name


def test_foreign_keys() -> None:
    targets = {
        (fk.parent.key, fk.column.table.fullname)
        for fk in ReportSavedView.__table__.foreign_keys
    }
    assert targets == {
        ("tenant_id", "tenant.tenant"),
        ("report_id", "rpt.report_definition"),
        ("user_id", "auth.app_user"),
        ("created_by", "auth.app_user"),
        ("updated_by", "auth.app_user"),
        ("deleted_by", "auth.app_user"),
    }
