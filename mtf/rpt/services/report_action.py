"""Resolve a report action into trusted screen or report navigation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy.orm import Session

from mtf.rpt.models import ReportAction, ReportActionParam
from mtf.rpt.schemas import ReportNavigationRead, ScreenNavigationRead
from mtf.rpt.services.criteria_validation import CriteriaSpec, validate_report_criteria
from mtf.rpt.services.report_catalog import ReportCatalogService
from mtf.shared.exceptions import forbidden, not_found, validation_error
from mtf.txn.services.screen_permission import ScreenOperation, ScreenPermissionService

_SCREEN_MODE_OPERATION: dict[str, ScreenOperation] = {"add": "add", "view": "view"}


def map_action_sources(
    params: list[ReportActionParam],
    row: Mapping[str, Any],
    criteria: Mapping[str, Any],
) -> dict[str, Any]:
    """Copy declared sources only. Extra client keys are ignored."""
    fields: dict[str, str] = {}
    mapped: dict[str, Any] = {}
    for param in params:
        if param.source_type == "column":
            source = row
        elif param.source_type == "criteria":
            source = criteria
        else:
            fields[param.source_key] = "Invalid source"
            continue
        if param.source_key not in source:
            fields[param.source_key] = "Required"
            continue
        value = source[param.source_key]
        if value is None or (isinstance(value, str) and value == ""):
            fields[param.source_key] = "Required"
            continue
        mapped[param.target_key] = value
    if fields:
        validation_error("REPORT_ACTION", "Action could not be resolved", fields)
    return mapped


def adapt_mapped_criteria(
    mapped: Mapping[str, Any],
    specs: Iterable[CriteriaSpec],
) -> dict[str, Any]:
    """Align copied source values with the target report's V1 criterion shapes.

    Grouped-report rows often store a single value (``status: "new"``) while the
    target list report filters with ``multiselect``. Wrap a non-list, non-dict
    scalar in a one-item list in that case. Lists, daterange objects, and scalar
    targets are left unchanged for ``validate_report_criteria``.
    """
    by_key = {spec.criteria_key: spec for spec in specs}
    adapted: dict[str, Any] = {}
    for key, value in mapped.items():
        spec = by_key.get(key)
        if (
            spec is not None
            and spec.control_type == "multiselect"
            and not isinstance(value, (list, dict))
        ):
            adapted[key] = [value]
        else:
            adapted[key] = value
    return adapted


class ReportActionService:
    """Turn a report action + current row/criteria into navigation the client can trust."""

    def __init__(
        self,
        db: Session,
        catalog: ReportCatalogService | None = None,
        screens: ScreenPermissionService | None = None,
    ) -> None:
        self._db = db
        self._catalog = catalog or ReportCatalogService(db)
        self._screens = screens or ScreenPermissionService(db)

    def resolve(
        self,
        tenant_id: str,
        user_id: str,
        report_key: str,
        action_key: str,
        row: Mapping[str, Any] | None = None,
        criteria: Mapping[str, Any] | None = None,
    ) -> ScreenNavigationRead | ReportNavigationRead:
        source = self._catalog.resolve_definition(tenant_id, report_key)
        action = self._catalog.get_live_action(source.id, action_key)
        mapped = map_action_sources(
            self._catalog.list_live_action_params(action.id),
            row or {},
            criteria or {},
        )
        if action.action_type == "screen":
            return self._resolve_screen(tenant_id, user_id, action, mapped)
        if action.action_type == "report":
            return self._resolve_report(tenant_id, action, mapped)
        not_found("REPORT_ACTION", "Action not found")

    def _resolve_screen(
        self,
        tenant_id: str,
        user_id: str,
        action: ReportAction,
        params: dict[str, Any],
    ) -> ScreenNavigationRead:
        if action.target_screen_id is None or action.screen_mode is None:
            not_found("REPORT_ACTION", "Action not found")
        screen = self._catalog.live_screen(action.target_screen_id)
        if screen is None:
            not_found("REPORT_ACTION", "Action not found")
        operation = _SCREEN_MODE_OPERATION.get(action.screen_mode)
        if operation is None:
            not_found("REPORT_ACTION", "Action not found")
        if not self._screens.resolve_for_screen(tenant_id, user_id, screen).allows(operation):
            forbidden("SCREEN", "Insufficient permissions")
        return ScreenNavigationRead(
            screen_key=screen.screen_key,
            mode=action.screen_mode,  # type: ignore[arg-type]
            params=params,
        )

    def _resolve_report(
        self,
        tenant_id: str,
        action: ReportAction,
        mapped: dict[str, Any],
    ) -> ReportNavigationRead:
        if action.target_report_id is None:
            not_found("REPORT_ACTION", "Action not found")
        target_key = self._catalog.visible_target_report_key(
            tenant_id, action.target_report_id
        )
        if target_key is None:
            not_found("REPORT", "Report not found")
        resolved = self._catalog.resolve(tenant_id, target_key)
        return ReportNavigationRead(
            report_key=target_key,
            criteria=validate_report_criteria(
                adapt_mapped_criteria(mapped, resolved.criteria),
                resolved.criteria,
            ),
        )
