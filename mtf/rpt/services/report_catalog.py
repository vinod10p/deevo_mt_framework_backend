"""Report catalog — read-only metadata from ``rpt.report_definition``, ``report_column``,
and ``report_criteria``."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session, aliased

from mtf.rpt.models import ReportColumn, ReportCriteria, ReportDefinition
from mtf.rpt.schemas import (
    ReportColumnRead,
    ReportCriteriaRead,
    ReportDetailRead,
    ReportSummaryRead,
)
from mtf.shared.exceptions import not_found

_LOOKUP_CONTROL_TYPES = frozenset({"dropdown", "multiselect"})


@dataclass(frozen=True)
class ResolvedReport:
    definition: ReportDefinition
    columns: list[ReportColumn]
    criteria: list[ReportCriteria]


def _is_live(model: type[ReportDefinition] | type[ReportColumn] | type[ReportCriteria]):
    return and_(model.is_deleted == False, model.is_active == True)  # noqa: E712


class ReportCatalogService:
    """Resolves which reports a tenant can see and serves their metadata.

    ``_resolve_report`` is the single place that maps ``report_key`` to a report for a
    tenant; the execution engine and saved-view services must reuse it.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    def list_reports(self, tenant_id: str) -> list[ReportSummaryRead]:
        """All system reports plus the tenant's own — not paginated.

        A tenant report hides a system report with the same ``report_key``.
        """
        override = aliased(ReportDefinition)
        has_tenant_override = exists().where(
            override.scope_type == "tenant",
            override.tenant_id == tenant_id,
            override.report_key == ReportDefinition.report_key,
            _is_live(override),
        )
        stmt = (
            select(ReportDefinition)
            .where(
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
            )
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

    def get_report(self, tenant_id: str, report_key: str) -> ReportDetailRead:
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

    def _resolve_report(self, tenant_id: str, report_key: str) -> ReportDefinition:
        """Tenant-owned report wins over a system report with the same key; otherwise 404."""
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
            return report

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
        return report

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
