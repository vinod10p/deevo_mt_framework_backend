"""ReportSavedView ↔ live ``rpt.report_saved_view`` (every write is rolled back).

Confirms the model maps to the real table and that the DB constraints the saved-view
service will rely on fire as expected.
"""

from __future__ import annotations

import json
import os
from collections.abc import Generator

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from mtf.auth.models.tenant_user import TenantUser
from mtf.rpt.models import ReportColumn, ReportDefinition, ReportSavedView
from mtf.rpt.services import validate_report_layout
from mtf.shared.database import SessionLocal
from mtf.shared.db_integrity import is_unique_constraint_violation
from mtf.shared.security import generate_id

pytestmark = pytest.mark.integration


@pytest.fixture
def db() -> Generator[Session, None, None]:
    if os.environ.get("DEEVO_SKIP_DB_TESTS", "").lower() in ("1", "true", "yes"):
        pytest.skip("DEEVO_SKIP_DB_TESTS is set")
    session = SessionLocal()
    try:
        session.execute(select(1))
    except DBAPIError as exc:
        session.close()
        pytest.skip(f"database not available: {exc.__class__.__name__}")
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def context(db: Session) -> dict[str, object]:
    report = db.scalars(
        select(ReportDefinition).where(
            ReportDefinition.report_key == "tenant_account_list",
            ReportDefinition.scope_type == "system",
            ReportDefinition.is_deleted == False,  # noqa: E712
        )
    ).first()
    member = db.scalars(select(TenantUser).where(TenantUser.is_deleted == False)).first()  # noqa: E712
    if report is None or member is None:
        pytest.skip("rpt sample reports or tenant users not seeded")
    columns = db.scalars(
        select(ReportColumn).where(
            ReportColumn.report_id == report.id, ReportColumn.is_deleted == False  # noqa: E712
        )
    ).all()
    return {"report": report, "tenant_id": member.tenant_id, "user_id": member.user_id,
            "columns": columns}


def _view(context: dict[str, object], **overrides: object) -> ReportSavedView:
    layout = validate_report_layout(
        {"columns": [{"column_name": "name", "width": 240}],
         "sort": [{"column_name": "name"}], "group": ["account_type"]},
        context["columns"],  # type: ignore[arg-type]
    )
    values: dict[str, object] = {
        "id": generate_id(),
        "tenant_id": context["tenant_id"],
        "report_id": context["report"].id,  # type: ignore[attr-defined]
        "scope_type": "user",
        "user_id": context["user_id"],
        "view_name": f"pytest view {generate_id()}",
        "criteria_json": json.dumps({"version": 1, "status": "active"}),
        "layout_json": json.dumps({"version": 1, **layout}),
        "created_by": context["user_id"],
        "updated_by": context["user_id"],
    }
    values.update(overrides)
    return ReportSavedView(**values)


def test_insert_round_trips_with_server_defaults(db: Session, context: dict) -> None:
    view = _view(context)
    db.add(view)
    db.flush()
    db.refresh(view)

    assert view.row_version
    assert view.created_at is not None
    assert view.is_default is False and view.is_active is True and view.is_deleted is False
    assert json.loads(view.layout_json)["group"] == ["account_type"]


def test_scope_check_rejects_user_view_without_user(db: Session, context: dict) -> None:
    db.add(_view(context, user_id=None))
    with pytest.raises(IntegrityError):
        db.flush()


def test_version_check_rejects_unversioned_json(db: Session, context: dict) -> None:
    db.add(_view(context, criteria_json="{}"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_default_state_check_rejects_deleted_default(db: Session, context: dict) -> None:
    db.add(_view(context, is_default=True, is_deleted=True))
    with pytest.raises(IntegrityError):
        db.flush()


def test_duplicate_name_in_tier_is_unique_violation(db: Session, context: dict) -> None:
    first = _view(context)
    db.add(first)
    db.flush()
    db.add(_view(context, view_name=first.view_name))
    with pytest.raises(IntegrityError) as exc_info:
        db.flush()
    assert is_unique_constraint_violation(exc_info.value)
    assert "UQ_report_saved_view_user" in str(exc_info.value.orig)


def test_second_default_in_tier_is_unique_violation(db: Session, context: dict) -> None:
    db.add(_view(context, is_default=True))
    db.flush()
    db.add(_view(context, is_default=True))
    with pytest.raises(IntegrityError) as exc_info:
        db.flush()
    assert is_unique_constraint_violation(exc_info.value)
    assert "UQ_report_saved_view_user_default" in str(exc_info.value.orig)
