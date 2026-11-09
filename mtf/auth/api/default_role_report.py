"""HTTP routes — ``auth.default_role_report`` catalog (system scope)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from mtf.audit.api.deps import get_audit_source
from mtf.audit.service import AuditSource
from mtf.auth.schemas.default_role_report import (
    DefaultRoleReportCreate,
    DefaultRoleReportRead,
    DefaultRoleReportUpdate,
)
from mtf.auth.services.default_role_report import DefaultRoleReportService
from mtf.shared.deps import CurrentUser, get_db, require_scope

router = APIRouter(prefix="/roles/{role_id}/default-reports", tags=["auth"])


def get_default_role_report_service(
    db: Session = Depends(get_db),
) -> DefaultRoleReportService:
    return DefaultRoleReportService(db)


@router.get("", response_model=list[DefaultRoleReportRead])
def list_default_role_reports(
    role_id: str,
    skip: int = 0,
    limit: int = 100,
    _current_user: CurrentUser = Depends(require_scope("system")),
    service: DefaultRoleReportService = Depends(get_default_role_report_service),
) -> list[DefaultRoleReportRead]:
    return service.list_for_role(role_id, skip=skip, limit=limit)


@router.post("", response_model=DefaultRoleReportRead, status_code=status.HTTP_201_CREATED)
def create_default_role_report(
    role_id: str,
    payload: DefaultRoleReportCreate,
    current_user: CurrentUser = Depends(require_scope("system")),
    source: AuditSource = Depends(get_audit_source),
    service: DefaultRoleReportService = Depends(get_default_role_report_service),
) -> DefaultRoleReportRead:
    return service.create(
        role_id,
        payload,
        created_by=current_user.user_id,
        actor=current_user,
        source=source,
    )


@router.get("/{report_id}", response_model=DefaultRoleReportRead)
def get_default_role_report(
    role_id: str,
    report_id: str,
    _current_user: CurrentUser = Depends(require_scope("system")),
    service: DefaultRoleReportService = Depends(get_default_role_report_service),
) -> DefaultRoleReportRead:
    return service.get(role_id, report_id)


@router.patch("/{report_id}", response_model=DefaultRoleReportRead)
def update_default_role_report(
    role_id: str,
    report_id: str,
    payload: DefaultRoleReportUpdate,
    current_user: CurrentUser = Depends(require_scope("system")),
    source: AuditSource = Depends(get_audit_source),
    service: DefaultRoleReportService = Depends(get_default_role_report_service),
) -> DefaultRoleReportRead:
    return service.update(
        role_id,
        report_id,
        payload,
        updated_by=current_user.user_id,
        actor=current_user,
        source=source,
    )


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_default_role_report(
    role_id: str,
    report_id: str,
    current_user: CurrentUser = Depends(require_scope("system")),
    source: AuditSource = Depends(get_audit_source),
    service: DefaultRoleReportService = Depends(get_default_role_report_service),
) -> Response:
    service.soft_delete(
        role_id,
        report_id,
        deleted_by=current_user.user_id,
        actor=current_user,
        source=source,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
