"""Report saved views — visibility, User → Tenant → System default resolution, and writes."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, case, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from mtf.audit.schemas import AuditAction
from mtf.audit.service import AuditSource, append_audit_log
from mtf.rpt.models import ReportDefinition, ReportSavedView
from mtf.rpt.schemas import ReportSavedViewCreate, ReportSavedViewRead, ReportSavedViewUpdate
from mtf.rpt.services.criteria_validation import criteria_to_json, validate_report_criteria
from mtf.rpt.services.layout_validation import LAYOUT_SECTIONS, validate_report_layout
from mtf.rpt.services.report_catalog import ReportCatalogService, ResolvedReport
from mtf.rpt.services.view_authorization import MANAGE_ACTION_BY_SCOPE, ReportViewAuthorizer
from mtf.shared.db_integrity import is_unique_constraint_violation
from mtf.shared.deps import CurrentUser
from mtf.shared.exceptions import conflict, forbidden, not_found, row_version_conflict
from mtf.shared.security import generate_id

#: Default precedence and list order: the caller's own views first, system views last.
_TIER_ORDER = {"user": 0, "tenant": 1, "system": 2}

#: Top-level ``version`` written into ``criteria_json`` / ``layout_json``.
STORED_JSON_VERSION = 1

_DOMAIN = "REPORT_VIEW"

#: UQ_report_saved_view_{system,tenant,user}_default — one default per tier.
_DEFAULT_INDEX = re.compile(r"UQ_report_saved_view_\w+_default", re.IGNORECASE)


def _stored_object(raw: str) -> dict[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, dict):
        return {}
    value.pop("version", None)
    return value


def _utc_naive_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _snapshot(view: ReportSavedView) -> dict[str, Any]:
    return {
        "report_id": view.report_id,
        "scope_type": view.scope_type,
        "tenant_id": view.tenant_id,
        "user_id": view.user_id,
        "view_name": view.view_name,
        "is_default": view.is_default,
        "is_deleted": view.is_deleted,
        "criteria": json.loads(view.criteria_json),
        "layout": json.loads(view.layout_json),
    }


class ReportSavedViewService:
    def __init__(self, db: Session, *, catalog: ReportCatalogService | None = None) -> None:
        self._db = db
        self._catalog = catalog or ReportCatalogService(db)
        self._authorizer = ReportViewAuthorizer(db)

    # ------------------------------------------------------------------ reads

    def list_views(self, user: CurrentUser, report_key: str) -> list[ReportSavedViewRead]:
        """Active views visible to ``user``: system, their tenant's, and their own user views."""
        report = self._catalog.resolve_definition(self._tenant_id(user), report_key)
        tier = case(_TIER_ORDER, value=ReportSavedView.scope_type, else_=len(_TIER_ORDER))
        stmt = (
            select(ReportSavedView)
            .where(self._visible(report, user))
            .order_by(tier, ReportSavedView.view_name, ReportSavedView.id)
        )
        return [self._to_read(user, view) for view in self._db.scalars(stmt).all()]

    def get_default_view(self, user: CurrentUser, report_key: str) -> ReportSavedViewRead | None:
        """First default in User → Tenant → System order, or ``None`` (frontend then falls
        back to ``report_column`` / ``report_criteria`` base defaults)."""
        report = self._catalog.resolve_definition(self._tenant_id(user), report_key)
        stmt = select(ReportSavedView).where(
            self._visible(report, user),
            ReportSavedView.is_default == True,  # noqa: E712
        )
        defaults = sorted(
            self._db.scalars(stmt).all(), key=lambda view: _TIER_ORDER[view.scope_type]
        )
        return self._to_read(user, defaults[0]) if defaults else None

    # ----------------------------------------------------------------- writes

    def create_view(
        self,
        user: CurrentUser,
        report_key: str,
        data: ReportSavedViewCreate,
        *,
        source: AuditSource | None = None,
    ) -> ReportSavedViewRead:
        tenant_id = self._tenant_id(user)
        resolved = self._catalog.resolve(tenant_id, report_key)
        report = resolved.definition
        self._authorizer.authorize(user, MANAGE_ACTION_BY_SCOPE[data.scope_type])
        self._check_report_scope(report, data.scope_type, tenant_id)
        criteria_json = self._criteria_json(data.criteria, resolved)
        layout_json = self._layout_json(data.layout, resolved)

        view = ReportSavedView(
            id=generate_id(),
            tenant_id=None if data.scope_type == "system" else tenant_id,
            report_id=report.id,
            scope_type=data.scope_type,
            user_id=user.user_id if data.scope_type == "user" else None,
            view_name=data.view_name,
            criteria_json=criteria_json,
            layout_json=layout_json,
            is_default=data.is_default,
            is_active=True,
            is_deleted=False,
            created_by=user.user_id,
            updated_by=user.user_id,
        )
        with self._write_errors():
            if data.is_default:
                self._clear_tier_default(user, view, source)
            self._db.add(view)
            self._audit(user, source, "insert", view.id, new_values=_snapshot(view))
            self._db.commit()
        self._db.refresh(view)
        return self._to_read(user, view)

    def update_view(
        self,
        user: CurrentUser,
        report_key: str,
        view_id: str,
        data: ReportSavedViewUpdate,
        *,
        source: AuditSource | None = None,
    ) -> ReportSavedViewRead:
        tenant_id = self._tenant_id(user)
        resolved = self._catalog.resolve(tenant_id, report_key)
        view = self._require_editable(user, resolved.definition, view_id)
        if view.row_version != data.row_version:
            row_version_conflict(_DOMAIN)

        changes: dict[str, Any] = {}
        if data.view_name is not None:
            changes["view_name"] = data.view_name
        if data.criteria is not None:
            changes["criteria_json"] = self._criteria_json(data.criteria, resolved)
        if data.layout is not None:
            changes["layout_json"] = self._layout_json(data.layout, resolved)
        if data.is_default is not None:
            changes["is_default"] = data.is_default
        if not changes:
            return self._to_read(user, view)

        old_values = _snapshot(view)
        with self._write_errors():
            if changes.get("is_default") and not view.is_default:
                self._clear_tier_default(user, view, source)
            for key, value in changes.items():
                setattr(view, key, value)
            view.updated_at = _utc_naive_now()
            view.updated_by = user.user_id
            self._audit(
                user, source, "update", view.id,
                old_values=old_values, new_values=_snapshot(view),
            )
            self._db.commit()
        self._db.refresh(view)
        return self._to_read(user, view)

    def delete_view(
        self,
        user: CurrentUser,
        report_key: str,
        view_id: str,
        *,
        source: AuditSource | None = None,
    ) -> None:
        """Soft delete. Never promotes another view to default — #6 falls back at read time."""
        report = self._catalog.resolve_definition(self._tenant_id(user), report_key)
        view = self._require_editable(user, report, view_id)

        old_values = _snapshot(view)
        with self._write_errors():
            view.is_deleted = True
            view.is_default = False
            view.deleted_by = user.user_id
            view.updated_by = user.user_id
            view.updated_at = _utc_naive_now()
            self._audit(
                user,
                source,
                "delete",
                view.id,
                old_values=old_values,
                new_values=_snapshot(view),
            )
            self._db.commit()

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _tenant_id(user: CurrentUser) -> str:
        if user.tenant_id is None:
            forbidden("AUTH", "Tenant context required")
        return user.tenant_id

    @staticmethod
    def _check_report_scope(report: ReportDefinition, scope_type: str, tenant_id: str) -> None:
        """App-layer rule 6: views under a tenant report stay in that tenant, never system."""
        if report.scope_type == "tenant" and (
            scope_type == "system" or report.tenant_id != tenant_id
        ):
            forbidden("AUTH", "Not allowed to manage these saved views")

    @staticmethod
    def _criteria_json(criteria: dict[str, Any], resolved: ResolvedReport) -> str:
        normalized = validate_report_criteria(criteria, resolved.criteria)
        return criteria_to_json({"version": STORED_JSON_VERSION, **normalized})

    @staticmethod
    def _layout_json(layout: dict[str, Any], resolved: ResolvedReport) -> str:
        normalized = validate_report_layout(layout, resolved.columns)
        return json.dumps({"version": STORED_JSON_VERSION, **normalized}, ensure_ascii=False)

    @staticmethod
    def _visible(report: ReportDefinition, user: CurrentUser):
        tiers = [
            and_(
                ReportSavedView.scope_type == "tenant",
                ReportSavedView.tenant_id == user.tenant_id,
            ),
            and_(
                ReportSavedView.scope_type == "user",
                ReportSavedView.tenant_id == user.tenant_id,
                ReportSavedView.user_id == user.user_id,
            ),
        ]
        if report.scope_type == "system":
            tiers.append(
                and_(ReportSavedView.scope_type == "system", ReportSavedView.tenant_id.is_(None))
            )
        return and_(
            ReportSavedView.report_id == report.id,
            ReportSavedView.is_deleted == False,  # noqa: E712
            ReportSavedView.is_active == True,  # noqa: E712
            or_(*tiers),
        )

    def _require_editable(
        self, user: CurrentUser, report: ReportDefinition, view_id: str
    ) -> ReportSavedView:
        """404 when the view isn't visible (no leaking other tenants' / users' views),
        403 when it's visible but the caller can't manage its tier."""
        stmt = select(ReportSavedView).where(
            self._visible(report, user), ReportSavedView.id == view_id
        )
        view = self._db.scalars(stmt).first()
        if view is None:
            not_found(_DOMAIN, "Saved view not found")
        self._authorizer.authorize_edit(user, view)
        return view

    def _clear_tier_default(
        self, user: CurrentUser, view: ReportSavedView, source: AuditSource | None
    ) -> None:
        """Unset the current default in ``view``'s tier and flush, so the filtered unique
        index never sees two defaults. A concurrent winner still surfaces as a conflict."""
        stmt = select(ReportSavedView).where(
            ReportSavedView.report_id == view.report_id,
            ReportSavedView.scope_type == view.scope_type,
            ReportSavedView.is_default == True,  # noqa: E712
            ReportSavedView.is_deleted == False,  # noqa: E712
            ReportSavedView.id != view.id,
        )
        if view.scope_type == "system":
            stmt = stmt.where(ReportSavedView.tenant_id.is_(None))
        else:
            stmt = stmt.where(ReportSavedView.tenant_id == view.tenant_id)
        if view.scope_type == "user":
            stmt = stmt.where(ReportSavedView.user_id == view.user_id)

        now = _utc_naive_now()
        for previous in self._db.scalars(stmt).all():
            previous.is_default = False
            previous.updated_at = now
            previous.updated_by = user.user_id
            self._audit(
                user, source, "update", previous.id,
                old_values={"is_default": True}, new_values={"is_default": False},
            )
        self._db.flush()

    def _audit(
        self,
        user: CurrentUser,
        source: AuditSource | None,
        action: AuditAction,
        record_id: str,
        *,
        old_values: dict[str, Any] | None = None,
        new_values: dict[str, Any] | None = None,
    ) -> None:
        append_audit_log(
            self._db,
            action=action,
            actor=user,
            source=source,
            schema_name="rpt",
            table_name="report_saved_view",
            record_id=record_id,
            old_values=old_values,
            new_values=new_values,
        )

    @contextmanager
    def _write_errors(self) -> Iterator[None]:
        """Roll back and translate races the unique indexes / ``row_version`` caught."""
        try:
            yield
        except StaleDataError:
            self._db.rollback()
            row_version_conflict(_DOMAIN)
        except IntegrityError as exc:
            self._db.rollback()
            if not is_unique_constraint_violation(exc):
                raise
            if _DEFAULT_INDEX.search(str(exc.orig or exc)):
                conflict(_DOMAIN, "Another default view was saved at the same time; retry")
            conflict(_DOMAIN, "A saved view with this name already exists")

    def _to_read(self, user: CurrentUser, view: ReportSavedView) -> ReportSavedViewRead:
        layout = _stored_object(view.layout_json)
        return ReportSavedViewRead(
            id=view.id,
            view_name=view.view_name,
            scope_type=view.scope_type,
            is_default=view.is_default,
            can_edit=self._authorizer.can_edit(user, view),
            criteria=_stored_object(view.criteria_json),
            layout={key: layout.get(key) or [] for key in LAYOUT_SECTIONS},
            row_version=view.row_version,
            updated_at=view.updated_at,
        )
