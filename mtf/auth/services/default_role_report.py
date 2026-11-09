"""Platform default report grants — ``auth.default_role_report``."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from mtf.audit.service import (
    AuditSource,
    audit_insert,
    audit_soft_delete,
    audit_update,
    row_snapshot,
)
from mtf.auth.models.default_role_report import DefaultRoleReport
from mtf.auth.schemas.default_role_report import (
    DefaultRoleReportCreate,
    DefaultRoleReportUpdate,
)
from mtf.auth.services.rbac_catalog import (
    apply_soft_delete,
    commit_or_conflict,
    require_export_needs_view,
    require_platform_report,
    require_template_role,
    utc_naive_now,
)
from mtf.shared.deps import CurrentUser
from mtf.shared.exceptions import conflict, not_found, row_version_conflict
from mtf.shared.security import generate_id


class DefaultRoleReportService:
    def __init__(self, session: Session) -> None:
        self._db = session

    def list_for_role(
        self,
        role_id: str,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> list[DefaultRoleReport]:
        require_template_role(self._db, role_id)
        stmt = (
            select(DefaultRoleReport)
            .where(
                DefaultRoleReport.role_id == role_id,
                DefaultRoleReport.is_deleted == False,  # noqa: E712
            )
            .order_by(DefaultRoleReport.created_at, DefaultRoleReport.id)
            .offset(skip)
            .limit(limit)
        )
        return list(self._db.scalars(stmt).all())

    def _live_grant(self, role_id: str, report_id: str) -> DefaultRoleReport | None:
        return self._db.scalars(
            select(DefaultRoleReport).where(
                DefaultRoleReport.role_id == role_id,
                DefaultRoleReport.report_id == report_id,
                DefaultRoleReport.is_deleted == False,  # noqa: E712
            )
        ).first()

    def get(self, role_id: str, report_id: str) -> DefaultRoleReport:
        require_template_role(self._db, role_id)
        row = self._live_grant(role_id, report_id)
        if row is None:
            not_found("AUTH_DEFAULT_ROLE_REPORT", "Default report grant not found")
        return row

    def create(
        self,
        role_id: str,
        data: DefaultRoleReportCreate,
        *,
        created_by: str | None = None,
        actor: CurrentUser | None = None,
        source: AuditSource | None = None,
    ) -> DefaultRoleReport:
        role = require_template_role(self._db, role_id)
        require_platform_report(self._db, data.report_id)
        require_export_needs_view(can_view=data.can_view, can_export=data.can_export)
        if self._live_grant(role_id, data.report_id) is not None:
            conflict(
                "AUTH_DEFAULT_ROLE_REPORT",
                "Default report grant already exists for this role",
            )

        row = DefaultRoleReport(
            id=generate_id(),
            role_id=role.id,
            report_id=data.report_id,
            can_view=data.can_view,
            can_export=data.can_export,
            created_by=created_by,
            updated_by=created_by,
        )
        self._db.add(row)
        audit_insert(
            self._db,
            entity=row,
            schema_name="auth",
            table_name="default_role_report",
            actor=actor,
            source=source,
        )
        commit_or_conflict(
            self._db,
            code_prefix="AUTH_DEFAULT_ROLE_REPORT",
            message="Default report grant already exists for this role",
        )
        self._db.refresh(row)
        return row

    def update(
        self,
        role_id: str,
        report_id: str,
        data: DefaultRoleReportUpdate,
        *,
        updated_by: str | None = None,
        actor: CurrentUser | None = None,
        source: AuditSource | None = None,
    ) -> DefaultRoleReport:
        row = self.get(role_id, report_id)
        if row.row_version != data.row_version:
            row_version_conflict("AUTH_DEFAULT_ROLE_REPORT")

        can_view = row.can_view if data.can_view is None else data.can_view
        can_export = row.can_export if data.can_export is None else data.can_export
        require_export_needs_view(can_view=can_view, can_export=can_export)

        before = row_snapshot(row)
        updates = data.model_dump(exclude_none=True, exclude={"row_version"})
        for key, value in updates.items():
            setattr(row, key, value)
        row.updated_at = utc_naive_now()
        if updated_by is not None:
            row.updated_by = updated_by

        self._db.add(row)
        audit_update(
            self._db,
            entity=row,
            schema_name="auth",
            table_name="default_role_report",
            before=before,
            actor=actor,
            source=source,
        )
        self._db.commit()
        self._db.refresh(row)
        return row

    def soft_delete(
        self,
        role_id: str,
        report_id: str,
        *,
        deleted_by: str,
        actor: CurrentUser | None = None,
        source: AuditSource | None = None,
    ) -> DefaultRoleReport:
        row = self.get(role_id, report_id)
        before = row_snapshot(row)
        apply_soft_delete(row, deleted_by=deleted_by)
        self._db.add(row)
        audit_soft_delete(
            self._db,
            entity=row,
            schema_name="auth",
            table_name="default_role_report",
            before=before,
            actor=actor,
            source=source,
        )
        self._db.commit()
        self._db.refresh(row)
        return row
