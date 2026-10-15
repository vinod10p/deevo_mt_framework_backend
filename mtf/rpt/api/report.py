"""Report routes (``user_scope`` tenant or tenant_account): catalog, lookups, run, views."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from mtf.rpt.api.deps import (
    get_audit_source,
    get_report_connection,
    get_report_tenant_id,
    get_report_user,
)
from mtf.rpt.schemas import (
    ReportActionResolveRead,
    ReportActionResolveRequest,
    ReportDetailRead,
    ReportLookupRead,
    ReportRunRead,
    ReportRunRequest,
    ReportSavedViewCreate,
    ReportSavedViewRead,
    ReportSavedViewUpdate,
    ReportSummaryRead,
)
from mtf.rpt.services import (
    AuditSource,
    ReportActionService,
    ReportCatalogService,
    ReportLookupService,
    ReportRunService,
    ReportSavedViewService,
)
from mtf.shared.deps import CurrentUser, get_db

router = APIRouter(prefix="/reports", tags=["reports"])


def get_report_catalog_service(db: Session = Depends(get_db)) -> ReportCatalogService:
    return ReportCatalogService(db)


def get_report_lookup_service(db: Session = Depends(get_db)) -> ReportLookupService:
    return ReportLookupService(db)


def get_report_run_service(db: Session = Depends(get_db)) -> ReportRunService:
    return ReportRunService(db)


def get_report_saved_view_service(db: Session = Depends(get_db)) -> ReportSavedViewService:
    return ReportSavedViewService(db)


def get_report_action_service(db: Session = Depends(get_db)) -> ReportActionService:
    return ReportActionService(db)


@router.get("", response_model=list[ReportSummaryRead])
def list_reports(
    tenant_id: str = Depends(get_report_tenant_id),
    service: ReportCatalogService = Depends(get_report_catalog_service),
) -> list[ReportSummaryRead]:
    return service.list_reports(tenant_id)


@router.get("/{report_key}", response_model=ReportDetailRead)
def get_report(
    report_key: str,
    user: CurrentUser = Depends(get_report_user),
    service: ReportCatalogService = Depends(get_report_catalog_service),
) -> ReportDetailRead:
    return service.get_report(get_report_tenant_id(user), report_key, user.user_id)


@router.get("/{report_key}/lookups/{criteria_key}", response_model=ReportLookupRead)
def get_report_lookup(
    report_key: str,
    criteria_key: str,
    q: str | None = Query(None, max_length=200, description="Search text (labels)"),
    values: list[str] | None = Query(
        None, description="Resolve labels for these values (repeat the parameter)"
    ),
    limit: int | None = Query(None, description="Max options; default 50, capped at 200"),
    tenant_id: str = Depends(get_report_tenant_id),
    conn: Any = Depends(get_report_connection),
    service: ReportLookupService = Depends(get_report_lookup_service),
) -> ReportLookupRead:
    return service.get_options(
        conn, tenant_id, report_key, criteria_key, q=q, values=values, limit=limit
    )


@router.post(
    "/{report_key}/actions/{action_key}/resolve",
    response_model=ReportActionResolveRead,
)
def resolve_report_action(
    report_key: str,
    action_key: str,
    payload: ReportActionResolveRequest,
    user: CurrentUser = Depends(get_report_user),
    service: ReportActionService = Depends(get_report_action_service),
) -> ReportActionResolveRead:
    return service.resolve(
        get_report_tenant_id(user),
        user.user_id,
        report_key,
        action_key,
        row=payload.row,
        criteria=payload.criteria,
    )


@router.post("/{report_key}/run", response_model=ReportRunRead)
def run_report(
    report_key: str,
    payload: ReportRunRequest,
    tenant_id: str = Depends(get_report_tenant_id),
    conn: Any = Depends(get_report_connection),
    service: ReportRunService = Depends(get_report_run_service),
) -> ReportRunRead:
    return service.run(
        conn, tenant_id, report_key, criteria=payload.criteria, max_rows=payload.max_rows
    )


@router.get("/{report_key}/views", response_model=list[ReportSavedViewRead])
def list_report_views(
    report_key: str,
    user: CurrentUser = Depends(get_report_user),
    service: ReportSavedViewService = Depends(get_report_saved_view_service),
) -> list[ReportSavedViewRead]:
    return service.list_views(user, report_key)


@router.get(
    "/{report_key}/views/default",
    response_model=ReportSavedViewRead,
    responses={status.HTTP_204_NO_CONTENT: {"description": "No default view in any tier"}},
)
def get_default_report_view(
    report_key: str,
    user: CurrentUser = Depends(get_report_user),
    service: ReportSavedViewService = Depends(get_report_saved_view_service),
) -> ReportSavedViewRead | Response:
    view = service.get_default_view(user, report_key)
    if view is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return view


@router.post(
    "/{report_key}/views",
    response_model=ReportSavedViewRead,
    status_code=status.HTTP_201_CREATED,
)
def create_report_view(
    report_key: str,
    payload: ReportSavedViewCreate,
    user: CurrentUser = Depends(get_report_user),
    source: AuditSource = Depends(get_audit_source),
    service: ReportSavedViewService = Depends(get_report_saved_view_service),
) -> ReportSavedViewRead:
    return service.create_view(user, report_key, payload, source=source)


@router.patch("/{report_key}/views/{view_id}", response_model=ReportSavedViewRead)
def update_report_view(
    report_key: str,
    view_id: str,
    payload: ReportSavedViewUpdate,
    user: CurrentUser = Depends(get_report_user),
    source: AuditSource = Depends(get_audit_source),
    service: ReportSavedViewService = Depends(get_report_saved_view_service),
) -> ReportSavedViewRead:
    return service.update_view(user, report_key, view_id, payload, source=source)


@router.delete("/{report_key}/views/{view_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_report_view(
    report_key: str,
    view_id: str,
    user: CurrentUser = Depends(get_report_user),
    source: AuditSource = Depends(get_audit_source),
    service: ReportSavedViewService = Depends(get_report_saved_view_service),
) -> None:
    service.delete_view(user, report_key, view_id, source=source)
