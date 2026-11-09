"""Report catalog — read-only metadata from ``rpt.report_definition``, ``report_column``,
and ``report_criteria``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session, aliased

from mtf.auth.services.permission_resolver import PermissionResolver
from mtf.rpt.models import (
    ReportAction,
    ReportActionParam,
    ReportColumn,
    ReportCriteria,
    ReportDefinition,
)
from mtf.rpt.schemas import (
    ReportActionParamRead,
    ReportActionRead,
    ReportColumnRead,
    ReportCriteriaRead,
    ReportDetailRead,
    ReportSummaryRead,
)
from mtf.shared.deps import CurrentUser
from mtf.shared.exceptions import not_found
from mtf.txn.models import Screen
from mtf.txn.services.screen_permission import ScreenOperation, ScreenPermissionService

_LOOKUP_CONTROL_TYPES = frozenset({"dropdown", "multiselect"})
_SCREEN_MODE_OPERATION: dict[str, ScreenOperation] = {"add": "add", "view": "view"}


@dataclass(frozen=True)
class ResolvedReport:
    definition: ReportDefinition
    columns: list[ReportColumn]
    criteria: list[ReportCriteria]


def _is_live(model: type[Any]):
    return and_(model.is_deleted == False, model.is_active == True)  # noqa: E712


_UNSET = object()


class ReportCatalogService:
    """Resolves which reports a tenant can see and serves their metadata.

    ``_resolve_report`` is the single place that maps ``report_key`` to a report for a
    tenant; the execution engine and saved-view services must reuse it.

    Tenant and portal callers are filtered by ``auth.role_report`` (``can_view``).
    Hidden reports are omitted from the list and look like unknown keys (404).
    System users keep the unfiltered catalog rules; they do not read tenant grants.
    """

    def __init__(
        self,
        db: Session,
        *,
        user: CurrentUser | None = None,
        resolver: PermissionResolver | None = None,
    ) -> None:
        self._db = db
        self._user = user
        self._resolver = resolver
        self._viewable_ids: object = _UNSET

    def list_reports(self, tenant_id: str) -> list[ReportSummaryRead]:
        """All system reports plus the tenant's own — not paginated.

        A tenant report hides a system report with the same ``report_key``.
        Tenant/portal callers only see reports with ``role_report.can_view``.
        """
        viewable = self._viewable_report_ids()
        if viewable is not None and not viewable:
            return []
        override = aliased(ReportDefinition)
        has_tenant_override = exists().where(
            override.scope_type == "tenant",
            override.tenant_id == tenant_id,
            override.report_key == ReportDefinition.report_key,
            _is_live(override),
        )
        filters = [
            _is_live(ReportDefinition),
            or_(
                and_(
                    ReportDefinition.scope_type == "tenant",
                    ReportDefinition.tenant_id == tenant_id,
                ),
                and_(
                    ReportDefinition.scope_type == "system",
                    ~has_tenant_override,
                ),
            ),
        ]
        if viewable is not None:
            filters.append(ReportDefinition.id.in_(viewable))
        stmt = (
            select(ReportDefinition)
            .where(*filters)
            .order_by(ReportDefinition.display_name, ReportDefinition.report_key)
        )
        return [ReportSummaryRead.model_validate(r) for r in self._db.scalars(stmt).all()]

    def resolve_definition(self, tenant_id: str, report_key: str) -> ReportDefinition:
        """Visible report definition only (no columns/criteria); otherwise 404."""
        return self._resolve_report(tenant_id, report_key)

    def resolve(self, tenant_id: str, report_key: str) -> ResolvedReport:
        """Visible report plus its live columns and criteria, each in ``display_order``."""
        report = self._resolve_report(tenant_id, report_key)
        return ResolvedReport(
            definition=report,
            columns=self._list_columns(report.id),
            criteria=self._list_criteria(report.id),
        )

    def get_report(self, tenant_id: str, report_key: str, user_id: str) -> ReportDetailRead:
        resolved = self.resolve(tenant_id, report_key)
        report, columns, criteria = resolved.definition, resolved.columns, resolved.criteria
        return ReportDetailRead(
            report_key=report.report_key,
            display_name=report.display_name,
            description=report.description,
            scope_type=report.scope_type,
            default_max_rows=report.default_max_rows,
            columns=[ReportColumnRead.model_validate(c) for c in columns],
            criteria=[
                ReportCriteriaRead(
                    criteria_key=c.criteria_key,
                    display_name=c.display_name,
                    data_type=c.data_type,
                    control_type=c.control_type,
                    has_lookup=bool(c.lookup_proc),
                    default_value=c.default_value,
                    is_required=c.is_required,
                    display_order=c.display_order,
                )
                for c in criteria
            ],
            actions=self._actions_for(report.id, tenant_id, user_id),
        )

    def get_lookup_criteria(
        self, tenant_id: str, report_key: str, criteria_key: str
    ) -> ReportCriteria:
        """Live dropdown/multiselect criterion with a ``lookup_proc``; otherwise 404."""
        report = self._resolve_report(tenant_id, report_key)
        stmt = (
            select(ReportCriteria)
            .where(
                ReportCriteria.report_id == report.id,
                ReportCriteria.criteria_key == criteria_key,
                _is_live(ReportCriteria),
            )
            .limit(1)
        )
        criteria = self._db.scalars(stmt).first()
        if (
            criteria is None
            or criteria.control_type not in _LOOKUP_CONTROL_TYPES
            or not criteria.lookup_proc
        ):
            not_found("REPORT_LOOKUP", "Lookup not found")
        return criteria

    def _viewable_report_ids(self) -> frozenset[str] | None:
        """Report ids the caller may view, or ``None`` to skip RBAC filtering."""
        if self._viewable_ids is not _UNSET:
            return self._viewable_ids  # type: ignore[return-value]
        if self._user is None or self._user.user_scope == "system":
            self._viewable_ids = None
            return None
        resolver = self._resolver or PermissionResolver(self._db)
        self._resolver = resolver
        self._viewable_ids = frozenset(
            grant.report_id
            for grant in resolver.report_grants(self._user).values()
            if grant.can_view
        )
        return self._viewable_ids

    def _hide_unauthorized(self, report: ReportDefinition) -> ReportDefinition:
        viewable = self._viewable_report_ids()
        if viewable is not None and report.id not in viewable:
            not_found("REPORT", "Report not found")
        return report

    def _resolve_report(self, tenant_id: str, report_key: str) -> ReportDefinition:
        """Tenant-owned report wins over a system report with the same key; otherwise 404.

        Unauthorized (no ``can_view`` grant) is the same 404 as unknown.
        """
        viewable = self._viewable_report_ids()
        if viewable is not None and not viewable:
            not_found("REPORT", "Report not found")
        tenant_stmt = (
            select(ReportDefinition)
            .where(
                ReportDefinition.scope_type == "tenant",
                ReportDefinition.tenant_id == tenant_id,
                ReportDefinition.report_key == report_key,
                _is_live(ReportDefinition),
            )
            .limit(1)
        )
        report = self._db.scalars(tenant_stmt).first()
        if report is not None:
            return self._hide_unauthorized(report)

        system_stmt = (
            select(ReportDefinition)
            .where(
                ReportDefinition.scope_type == "system",
                ReportDefinition.report_key == report_key,
                _is_live(ReportDefinition),
            )
            .limit(1)
        )
        report = self._db.scalars(system_stmt).first()
        if report is None:
            not_found("REPORT", "Report not found")
        return self._hide_unauthorized(report)

    def _list_columns(self, report_id: str) -> list[ReportColumn]:
        stmt = (
            select(ReportColumn)
            .where(ReportColumn.report_id == report_id, _is_live(ReportColumn))
            .order_by(ReportColumn.display_order, ReportColumn.column_name)
        )
        return list(self._db.scalars(stmt).all())

    def _list_criteria(self, report_id: str) -> list[ReportCriteria]:
        stmt = (
            select(ReportCriteria)
            .where(ReportCriteria.report_id == report_id, _is_live(ReportCriteria))
            .order_by(ReportCriteria.display_order, ReportCriteria.criteria_key)
        )
        return list(self._db.scalars(stmt).all())

    def _actions_for(
        self, report_id: str, tenant_id: str, user_id: str
    ) -> list[ReportActionRead]:
        actions = self._list_actions(report_id)
        if not actions:
            return []
        params_by_action = self._list_action_params([a.id for a in actions])
        screens = self._live_screens_by_id(
            [a.target_screen_id for a in actions if a.target_screen_id]
        )
        perm_svc = ScreenPermissionService(self._db)
        visible: list[ReportActionRead] = []
        for action in actions:
            read = self._to_action_read(
                action,
                params_by_action.get(action.id, []),
                tenant_id,
                user_id,
                screens,
                perm_svc,
            )
            if read is not None:
                visible.append(read)
        return visible

    def _list_actions(self, report_id: str) -> list[ReportAction]:
        stmt = (
            select(ReportAction)
            .where(ReportAction.report_id == report_id, _is_live(ReportAction))
            .order_by(ReportAction.display_order, ReportAction.action_key)
        )
        return list(self._db.scalars(stmt).all())

    def _list_action_params(self, action_ids: list[str]) -> dict[str, list[ReportActionParam]]:
        if not action_ids:
            return {}
        stmt = (
            select(ReportActionParam)
            .where(ReportActionParam.action_id.in_(action_ids), _is_live(ReportActionParam))
            .order_by(ReportActionParam.target_key)
        )
        grouped: dict[str, list[ReportActionParam]] = {aid: [] for aid in action_ids}
        for param in self._db.scalars(stmt).all():
            grouped.setdefault(param.action_id, []).append(param)
        return grouped

    def _live_screens_by_id(self, screen_ids: list[str | None]) -> dict[str, Screen]:
        ids = list(dict.fromkeys(sid for sid in screen_ids if sid))
        if not ids:
            return {}
        stmt = select(Screen).where(Screen.id.in_(ids), _is_live(Screen))
        return {row.id: row for row in self._db.scalars(stmt).all()}

    def _to_action_read(
        self,
        action: ReportAction,
        params: list[ReportActionParam],
        tenant_id: str,
        user_id: str,
        screens: dict[str, Screen],
        perm_svc: ScreenPermissionService,
    ) -> ReportActionRead | None:
        screen_key: str | None = None
        screen_mode: str | None = None
        report_key: str | None = None
        if action.action_type == "screen":
            if action.target_screen_id is None or action.screen_mode is None:
                return None
            screen = screens.get(action.target_screen_id)
            if screen is None:
                return None
            perms = perm_svc.resolve_for_screen(tenant_id, user_id, screen)
            operation = _SCREEN_MODE_OPERATION.get(action.screen_mode)
            if operation is None or not perms.allows(operation):
                return None
            screen_key = screen.screen_key
            screen_mode = action.screen_mode
        elif action.action_type == "report":
            if action.target_report_id is None:
                return None
            report_key = self.visible_target_report_key(tenant_id, action.target_report_id)
            if report_key is None:
                return None
        else:
            return None
        return ReportActionRead(
            action_key=action.action_key,
            display_name=action.display_name,
            action_type=action.action_type,  # type: ignore[arg-type]
            display_location=action.display_location,  # type: ignore[arg-type]
            trigger_column_key=action.trigger_column_key,
            display_order=action.display_order,
            screen_key=screen_key,
            screen_mode=screen_mode,  # type: ignore[arg-type]
            report_key=report_key,
            params=[
                ReportActionParamRead(
                    source_type=p.source_type,  # type: ignore[arg-type]
                    source_key=p.source_key,
                    target_key=p.target_key,
                )
                for p in params
            ],
        )

    def get_live_action(self, report_id: str, action_key: str) -> ReportAction:
        """Live action on this report; otherwise 404 ``REPORT_ACTION_NOT_FOUND``."""
        stmt = (
            select(ReportAction)
            .where(
                ReportAction.report_id == report_id,
                ReportAction.action_key == action_key,
                _is_live(ReportAction),
            )
            .limit(1)
        )
        action = self._db.scalars(stmt).first()
        if action is None:
            not_found("REPORT_ACTION", "Action not found")
        return action

    def list_live_action_params(self, action_id: str) -> list[ReportActionParam]:
        return self._list_action_params([action_id]).get(action_id, [])

    def live_screen(self, screen_id: str) -> Screen | None:
        return self._live_screens_by_id([screen_id]).get(screen_id)

    def visible_target_report_key(self, tenant_id: str, report_id: str) -> str | None:
        """Return the target's ``report_key`` only if this tenant can see that key."""
        stmt = select(ReportDefinition).where(
            ReportDefinition.id == report_id,
            _is_live(ReportDefinition),
        )
        target = self._db.scalars(stmt).first()
        if target is None:
            return None
        try:
            self._resolve_report(tenant_id, target.report_key)
        except HTTPException:
            return None
        return target.report_key
