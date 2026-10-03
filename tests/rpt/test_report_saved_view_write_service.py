"""ReportSavedViewService write side — validation, tiers, default clearing, audit, conflicts."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from mtf.audit.models import AuditLog
from mtf.rpt.models import ReportSavedView
from mtf.rpt.schemas import ReportSavedViewCreate, ReportSavedViewUpdate
from mtf.rpt.services import AuditSource, ReportSavedViewService, ResolvedReport
from mtf.shared.exceptions import forbidden
from tests.rpt.conftest import (
    TENANT_REPORT_ID,
    TEST_TENANT_ID,
    TEST_USER_ID,
    minimal_column,
    minimal_criteria,
    minimal_report,
    minimal_saved_view,
    portal_user,
    tenant_user,
)

NEW_ROW_VERSION = b"\x00\x00\x00\x00\x00\x00\x00\x09"
SOURCE = AuditSource(ip_address="10.0.0.1", user_agent="pytest")


def _resolved(report=None) -> ResolvedReport:
    return ResolvedReport(
        definition=report or minimal_report(),
        columns=[
            minimal_column(),
            minimal_column(
                id="01JRPT0CM00000000000000002", column_name="account_type",
                is_groupable=True, is_aggregatable=True,
            ),
        ],
        criteria=[
            minimal_criteria(),
            minimal_criteria(
                id="01JRPT0CR00000000000000002", criteria_key="status",
                control_type="dropdown",
            ),
        ],
    )


def _refresh(view: ReportSavedView) -> None:
    view.row_version = NEW_ROW_VERSION
    view.updated_at = view.updated_at or minimal_saved_view().updated_at


def _service(
    *, existing=None, previous_defaults=(), report=None
) -> tuple[ReportSavedViewService, MagicMock]:
    db = MagicMock()
    db.scalars.return_value.first.return_value = existing
    db.scalars.return_value.all.return_value = list(previous_defaults)
    db.refresh.side_effect = _refresh
    service = ReportSavedViewService(db)
    service._catalog = MagicMock()
    service._catalog.resolve.return_value = _resolved(report)
    service._catalog.resolve_definition.return_value = report or minimal_report()
    service._authorizer = MagicMock()
    service._authorizer.can_edit.return_value = True
    return service, db


def _added(db: MagicMock, kind: type) -> list:
    return [c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], kind)]


def _create(**overrides: object) -> ReportSavedViewCreate:
    body: dict[str, object] = {"view_name": "Q3 Review", "scope_type": "user"}
    body.update(overrides)
    return ReportSavedViewCreate(**body)  # type: ignore[arg-type]


def _code(exc: pytest.ExceptionInfo[HTTPException]) -> str:
    return exc.value.detail["code"]  # type: ignore[index]


# ------------------------------------------------------------------ create


def test_create_user_view_stores_versioned_json_and_audits() -> None:
    service, db = _service()
    data = _create(
        criteria={"account_type": ["customer", "customer"], "status": ""},
        layout={"sort": [{"column_name": "name"}], "group": ["account_type"]},
    )

    result = service.create_view(tenant_user(), "tenant_account_list", data, source=SOURCE)

    service._authorizer.authorize.assert_called_once_with(
        tenant_user(), "report.view.manage_user"
    )
    [view] = _added(db, ReportSavedView)
    assert (view.scope_type, view.tenant_id, view.user_id) == ("user", TEST_TENANT_ID, TEST_USER_ID)
    assert json.loads(view.criteria_json) == {"version": 1, "account_type": ["customer"]}
    assert json.loads(view.layout_json) == {
        "version": 1,
        "columns": [],
        "sort": [{"column_name": "name", "direction": "asc"}],
        "group": ["account_type"],
        "aggregates": [],
    }
    assert view.created_by == view.updated_by == TEST_USER_ID

    [audit] = _added(db, AuditLog)
    assert (audit.action, audit.record_id, audit.schema_name, audit.table_name) == (
        "insert", view.id, "rpt", "report_saved_view"
    )
    assert (audit.ip_address, audit.user_agent, audit.user_type) == ("10.0.0.1", "pytest", "tenant")
    assert json.loads(audit.new_values)["view_name"] == "Q3 Review"
    db.commit.assert_called_once()

    assert result.criteria == {"account_type": ["customer"]}
    assert result.row_version == NEW_ROW_VERSION


def test_create_empty_criteria_stored_as_version_only() -> None:
    service, db = _service()
    service.create_view(tenant_user(), "r", _create())
    [view] = _added(db, ReportSavedView)
    assert json.loads(view.criteria_json) == {"version": 1}


def test_create_tenant_view_has_no_user_id() -> None:
    service, db = _service()
    service.create_view(tenant_user(), "r", _create(scope_type="tenant"))
    service._authorizer.authorize.assert_called_once_with(
        tenant_user(), "report.view.manage_tenant"
    )
    [view] = _added(db, ReportSavedView)
    assert (view.tenant_id, view.user_id) == (TEST_TENANT_ID, None)


def test_create_forbidden_writes_nothing() -> None:
    service, db = _service()
    service._authorizer.authorize.side_effect = lambda *_: forbidden("AUTH", "no")
    with pytest.raises(HTTPException) as exc:
        service.create_view(portal_user(), "r", _create(scope_type="tenant"))
    assert exc.value.status_code == 403
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_create_system_view_on_tenant_report_rejected_even_if_authorized() -> None:
    tenant_report = minimal_report(
        id=TENANT_REPORT_ID, scope_type="tenant", tenant_id=TEST_TENANT_ID
    )
    service, db = _service(report=tenant_report)
    with pytest.raises(HTTPException) as exc:
        service.create_view(tenant_user(), "r", _create(scope_type="system"))
    assert _code(exc) == "AUTH_FORBIDDEN"
    db.add.assert_not_called()


@pytest.mark.parametrize(
    ("overrides", "code", "field"),
    [
        ({"criteria": {"version": 1}}, "REPORT_CRITERIA_INVALID", "version"),
        ({"criteria": {"status": ["a"]}}, "REPORT_CRITERIA_INVALID", "status"),
        ({"layout": {"group": ["name"]}}, "REPORT_LAYOUT_INVALID", "group[0]"),
        ({"layout": {"version": 1}}, "REPORT_LAYOUT_INVALID", "version"),
    ],
)
def test_create_validation_errors(overrides: dict, code: str, field: str) -> None:
    service, db = _service()
    with pytest.raises(HTTPException) as exc:
        service.create_view(tenant_user(), "r", _create(**overrides))
    assert exc.value.status_code == 422
    assert _code(exc) == code
    assert field in exc.value.detail["fields"]  # type: ignore[index]
    db.add.assert_not_called()


def test_create_default_clears_previous_default_first() -> None:
    previous = minimal_saved_view(id="01JRPT0SV00000000000000009", is_default=True)
    service, db = _service(previous_defaults=[previous])

    service.create_view(tenant_user(), "r", _create(is_default=True), source=SOURCE)

    assert previous.is_default is False
    assert previous.updated_by == TEST_USER_ID
    calls = db.method_calls
    flush_at = next(i for i, c in enumerate(calls) if c[0] == "flush")
    view_add_at = next(
        i for i, c in enumerate(calls) if c[0] == "add" and isinstance(c.args[0], ReportSavedView)
    )
    assert flush_at < view_add_at
    audits = _added(db, AuditLog)
    assert [(a.action, a.record_id) for a in audits][0] == ("update", previous.id)
    assert json.loads(audits[0].new_values) == {"is_default": False}


def test_create_without_default_does_not_touch_other_views() -> None:
    service, db = _service()
    service.create_view(tenant_user(), "r", _create())
    db.flush.assert_not_called()


# ------------------------------------------------------------------ update


def _update(**overrides: object) -> ReportSavedViewUpdate:
    body: dict[str, object] = {"row_version": minimal_saved_view().row_version}
    body.update(overrides)
    return ReportSavedViewUpdate(**body)  # type: ignore[arg-type]


def test_update_view_not_visible_404() -> None:
    service, db = _service(existing=None)
    with pytest.raises(HTTPException) as exc:
        service.update_view(tenant_user(), "r", "missing", _update(view_name="x"))
    assert exc.value.status_code == 404
    assert _code(exc) == "REPORT_VIEW_NOT_FOUND"
    db.commit.assert_not_called()


def test_update_not_editable_403() -> None:
    view = minimal_saved_view(scope_type="tenant", user_id=None)
    service, db = _service(existing=view)
    service._authorizer.authorize_edit.side_effect = lambda *_: forbidden("AUTH", "no")
    with pytest.raises(HTTPException) as exc:
        service.update_view(tenant_user(), "r", view.id, _update(view_name="x"))
    assert exc.value.status_code == 403
    db.commit.assert_not_called()


def test_update_row_version_mismatch_409() -> None:
    service, db = _service(existing=minimal_saved_view())
    with pytest.raises(HTTPException) as exc:
        service.update_view(
            tenant_user(), "r", "v", _update(row_version=b"\xff" * 8, view_name="x")
        )
    assert exc.value.status_code == 409
    assert _code(exc) == "REPORT_VIEW_CONFLICT"
    db.commit.assert_not_called()


def test_update_applies_changes_and_audits_old_and_new() -> None:
    view = minimal_saved_view()
    service, db = _service(existing=view)

    result = service.update_view(
        tenant_user(), "r", view.id,
        _update(view_name="Renamed", criteria={}, layout={"columns": [{"column_name": "name"}]}),
        source=SOURCE,
    )

    assert view.view_name == "Renamed"
    assert json.loads(view.criteria_json) == {"version": 1}
    assert json.loads(view.layout_json)["columns"] == [
        {"column_name": "name", "visible": True, "width": None}
    ]
    assert view.updated_by == TEST_USER_ID
    [audit] = _added(db, AuditLog)
    assert audit.action == "update"
    assert json.loads(audit.old_values)["view_name"] == "My view"
    assert json.loads(audit.new_values)["view_name"] == "Renamed"
    db.commit.assert_called_once()
    assert result.view_name == "Renamed"


def test_update_set_default_clears_tier() -> None:
    view = minimal_saved_view()
    previous = minimal_saved_view(id="01JRPT0SV00000000000000009", is_default=True)
    service, db = _service(existing=view, previous_defaults=[previous])

    service.update_view(tenant_user(), "r", view.id, _update(is_default=True))

    assert view.is_default is True and previous.is_default is False
    db.flush.assert_called_once()


def test_update_already_default_does_not_reclear() -> None:
    view = minimal_saved_view(is_default=True)
    service, db = _service(existing=view)
    service.update_view(tenant_user(), "r", view.id, _update(is_default=True))
    db.flush.assert_not_called()


def test_update_without_changes_writes_nothing() -> None:
    service, db = _service(existing=minimal_saved_view())
    result = service.update_view(tenant_user(), "r", "v", _update())
    db.commit.assert_not_called()
    assert result.view_name == "My view"


def test_update_validates_criteria() -> None:
    service, db = _service(existing=minimal_saved_view())
    with pytest.raises(HTTPException) as exc:
        service.update_view(tenant_user(), "r", "v", _update(criteria={"nope": 1}))
    assert _code(exc) == "REPORT_CRITERIA_INVALID"
    db.commit.assert_not_called()


# ------------------------------------------------------------------ delete


def test_delete_soft_deletes_clears_default_and_audits() -> None:
    view = minimal_saved_view(is_default=True)
    service, db = _service(existing=view)

    service.delete_view(tenant_user(), "r", view.id, source=SOURCE)

    assert view.is_deleted is True and view.is_default is False
    assert view.deleted_by == view.updated_by == TEST_USER_ID
    [audit] = _added(db, AuditLog)
    assert audit.action == "delete" and audit.new_values is None
    assert json.loads(audit.old_values)["is_default"] is True
    db.commit.assert_called_once()
    db.flush.assert_not_called()


def test_delete_not_visible_404() -> None:
    service, db = _service(existing=None)
    with pytest.raises(HTTPException) as exc:
        service.delete_view(tenant_user(), "r", "missing")
    assert _code(exc) == "REPORT_VIEW_NOT_FOUND"
    db.commit.assert_not_called()


# --------------------------------------------------------------- conflicts


def _integrity(message: str) -> IntegrityError:
    return IntegrityError("INSERT ...", {}, Exception(message))


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            "Cannot insert duplicate key row in object 'rpt.report_saved_view' with unique "
            "index 'UQ_report_saved_view_tenant'. The duplicate key value is (x, my_default).",
            "name already exists",
        ),
        (
            "Cannot insert duplicate key row in object 'rpt.report_saved_view' with unique "
            "index 'UQ_report_saved_view_user_default'.",
            "default view",
        ),
    ],
)
def test_unique_violation_translated_to_conflict(message: str, expected: str) -> None:
    service, db = _service()
    db.commit.side_effect = _integrity(message)
    with pytest.raises(HTTPException) as exc:
        service.create_view(tenant_user(), "r", _create())
    assert exc.value.status_code == 409
    assert _code(exc) == "REPORT_VIEW_CONFLICT"
    assert expected in exc.value.detail["message"]  # type: ignore[index]
    db.rollback.assert_called_once()


def test_other_integrity_errors_propagate() -> None:
    service, db = _service()
    db.commit.side_effect = _integrity("The INSERT statement conflicted with the FOREIGN KEY")
    with pytest.raises(IntegrityError):
        service.create_view(tenant_user(), "r", _create())
    db.rollback.assert_called_once()


def test_stale_row_on_write_is_row_version_conflict() -> None:
    service, db = _service(existing=minimal_saved_view())
    db.commit.side_effect = StaleDataError("0 rows matched")
    with pytest.raises(HTTPException) as exc:
        service.delete_view(tenant_user(), "r", "v")
    assert exc.value.status_code == 409
    assert _code(exc) == "REPORT_VIEW_CONFLICT"
    db.rollback.assert_called_once()
