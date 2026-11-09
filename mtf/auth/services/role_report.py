"""Per-tenant ``auth.role_report`` grants."""

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
from mtf.auth.models.role_report import RoleReport
from mtf.auth.schemas.role_report import RoleReportCreate, RoleReportUpdate
from mtf.auth.services.permission_resolver import Actor, PermissionResolver
from mtf.auth.services.rbac_assignment import (
    assert_report_escalation,
    require_assignable_role,
    require_tenant_report,
)
from mtf.auth.services.rbac_catalog import (
    apply_soft_delete,
    commit_or_conflict,
    require_export_needs_view,
    utc_naive_now,
)
from mtf.shared.deps import CurrentUser
from mtf.shared.exceptions import conflict, not_found, row_version_conflict
from mtf.shared.security import generate_id


class RoleReportService:
    def __init__(self, session: Session) -> None:
        self._db = session

    def list_for_role(
        self,
        tenant_id: str,
        role_id: str,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> list[RoleReport]:
        require_assignable_role(self._db, tenant_id, role_id)
        stmt = (
            select(RoleReport)
            .where(
                RoleReport.tenant_id == tenant_id,
                RoleReport.role_id == role_id,
                RoleReport.is_deleted == False,  # noqa: E712
            )
            .order_by(RoleReport.created_at, RoleReport.id)
            .offset(skip)
            .limit(limit)
        )
        return list(self._db.scalars(stmt).all())

    def _live_grant(self, tenant_id: str, role_id: str, report_id: str) -> RoleReport | None:
        return self._db.scalars(
            select(RoleReport).where(
                RoleReport.tenant_id == tenant_id,
                RoleReport.role_id == role_id,
                RoleReport.report_id == report_id,
                RoleReport.is_deleted == False,  # noqa: E712
            )
        ).first()

    def get(self, tenant_id: str, role_id: str, report_id: str) -> RoleReport:
        require_assignable_role(self._db, tenant_id, role_id)
        row = self._live_grant(tenant_id, role_id, report_id)
        if row is None:
            not_found("AUTH_ROLE_REPORT", "Role report grant not found")
        return row

    def create(
        self,
        tenant_id: str,
        role_id: str,
        data: RoleReportCreate,
        *,
        resolver: PermissionResolver,
        actor: Actor,
        created_by: str | None = None,
        source: AuditSource | None = None,
    ) -> RoleReport:
        role = require_assignable_role(self._db, tenant_id, role_id)
        if role.tenant_id is not None and role.tenant_id != tenant_id:
            not_found("AUTH_ROLE", "Role not found")
        require_tenant_report(self._db, tenant_id, data.report_id)
        require_export_needs_view(
            can_view=data.can_view,
            can_export=data.can_export,
            code_prefix="AUTH_ROLE_REPORT",
        )
        assert_report_escalation(
            resolver,
            actor,
            data.report_id,
            can_view=data.can_view,
            can_export=data.can_export,
        )
        if self._live_grant(tenant_id, role.id, data.report_id) is not None:
            conflict("AUTH_ROLE_REPORT", "Report grant already exists for this role")

        row = RoleReport(
            id=generate_id(),
            tenant_id=tenant_id,
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
            table_name="role_report",
            actor=actor if isinstance(actor, CurrentUser) else None,
            source=source,
            tenant_id=tenant_id,
        )
        commit_or_conflict(
            self._db,
            code_prefix="AUTH_ROLE_REPORT",
            message="Report grant already exists for this role",
        )
        self._db.refresh(row)
        return row

    def update(
        self,
        tenant_id: str,
        role_id: str,
        report_id: str,
        data: RoleReportUpdate,
        *,
        resolver: PermissionResolver,
        actor: Actor,
        updated_by: str | None = None,
        source: AuditSource | None = None,
    ) -> RoleReport:
        row = self.get(tenant_id, role_id, report_id)
        if row.row_version != data.row_version:
            row_version_conflict("AUTH_ROLE_REPORT")

        can_view = row.can_view if data.can_view is None else data.can_view
        can_export = row.can_export if data.can_export is None else data.can_export
        require_export_needs_view(
            can_view=can_view,
            can_export=can_export,
            code_prefix="AUTH_ROLE_REPORT",
        )
        assert_report_escalation(
            resolver,
            actor,
            report_id,
            can_view=can_view,
            can_export=can_export,
        )

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
            table_name="role_report",
            before=before,
            actor=actor if isinstance(actor, CurrentUser) else None,
            source=source,
            tenant_id=tenant_id,
        )
        self._db.commit()
        self._db.refresh(row)
        return row

    def soft_delete(
        self,
        tenant_id: str,
        role_id: str,
        report_id: str,
        *,
        deleted_by: str,
        actor: CurrentUser | None = None,
        source: AuditSource | None = None,
    ) -> RoleReport:
        row = self.get(tenant_id, role_id, report_id)
        before = row_snapshot(row)
        apply_soft_delete(row, deleted_by=deleted_by)
        self._db.add(row)
        audit_soft_delete(
            self._db,
            entity=row,
            schema_name="auth",
            table_name="role_report",
            before=before,
            actor=actor,
            source=source,
            tenant_id=tenant_id,
        )
        self._db.commit()
        self._db.refresh(row)
        return row
