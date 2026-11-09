"""ORM mapping tests for V2 report permission/action tables — no database."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import configure_mappers

from mtf.rpt.models import ReportAction, ReportActionParam, ReportDefinition


@pytest.fixture(scope="module", autouse=True)
def _configure_mappers_for_fk_resolution() -> None:
    from mtf.auth.models.user import User  # noqa: F401
    from mtf.tenant.models.tenant import Tenant  # noqa: F401
    from mtf.txn.models.screen import Screen  # noqa: F401

    _ = User.__table__, Tenant.__table__, Screen.__table__, ReportDefinition.__table__
    configure_mappers()


def test_report_definition_has_permission_mode() -> None:
    col = ReportDefinition.__table__.c.permission_mode
    assert col.nullable is False
    assert col.server_default is not None


def _fk_targets(model: type) -> set[tuple[str, str]]:
    return {(fk.parent.key, fk.column.table.fullname) for fk in model.__table__.foreign_keys}


def test_report_action_targets_report_or_screen() -> None:
    assert ReportAction.__table__.schema == "rpt"
    fks = _fk_targets(ReportAction)
    assert ("report_id", "rpt.report_definition") in fks
    assert ("target_report_id", "rpt.report_definition") in fks
    assert ("target_screen_id", "txn.screen") in fks


def test_report_action_param_parent() -> None:
    assert ReportActionParam.__table__.schema == "rpt"
    assert ("action_id", "rpt.report_action") in _fk_targets(ReportActionParam)
