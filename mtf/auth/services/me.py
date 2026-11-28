"""Assemble RBAC and business unit fields for ``GET /api/auth/me`` (UI only)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from mtf.auth.schemas.user import MeBusinessUnitRead, MeReportGrantRead
from mtf.auth.services.permission_resolver import Actor, PermissionResolver
from mtf.rpt.models.report_definition import ReportDefinition
from mtf.tenant.models.business_unit import BusinessUnit
from mtf.tenant.services.business_unit_service import BusinessUnitService


def me_business_unit_fields(db: Session, user: Actor) -> dict[str, object]:
    """``business_unit``, ``multi_store`` and (staff only) ``business_units``."""
    if user.tenant_id is None or user.business_unit_id is None:
        return {}
    units = BusinessUnitService(db)
    current = db.get_one(BusinessUnit, user.business_unit_id)
    open_units = (
        units.list_open_to_staff(user.tenant_id, user.user_id)
        if user.user_scope == "tenant"
        else []
    )
    return {
        "business_unit": MeBusinessUnitRead.model_validate(current),
        "multi_store": units.is_multi_store(user.tenant_id),
        "business_units": [MeBusinessUnitRead.model_validate(unit) for unit in open_units],
    }


def me_rbac_fields(
    db: Session,
    resolver: PermissionResolver,
    user: Actor,
) -> tuple[list[str], list[MeReportGrantRead]]:
    """Sorted permission codes and viewable report grants with ``report_key``."""
    permissions = sorted(resolver.permission_codes(user))
    grants = resolver.report_grants(user)
    viewable = {
        report_id: grant
        for report_id, grant in grants.items()
        if grant.can_view
    }
    if not viewable:
        return permissions, []

    keys = {
        report_id: report_key
        for report_id, report_key in db.execute(
            select(ReportDefinition.id, ReportDefinition.report_key).where(
                ReportDefinition.id.in_(list(viewable)),
                ReportDefinition.is_active == True,  # noqa: E712
                ReportDefinition.is_deleted == False,  # noqa: E712
            )
        ).all()
    }
    reports = [
        MeReportGrantRead(
            report_key=keys[report_id],
            can_view=True,
            can_export=grant.can_export,
        )
        for report_id, grant in viewable.items()
        if report_id in keys
    ]
    reports.sort(key=lambda row: row.report_key)
    return permissions, reports
