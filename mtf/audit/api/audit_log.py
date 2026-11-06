"""HTTP routes — ``audit.audit_log`` resource (read-only)."""

from typing import Optional

from fastapi import APIRouter, Depends, Query

from mtf.audit.api.deps import get_audit_service, require_audit_reader
from mtf.audit.schemas import AuditLogRead
from mtf.audit.service import AuditLogService
from mtf.shared.deps import CurrentUser, PaginationParams, get_pagination
from mtf.shared.exceptions import not_found

router = APIRouter(tags=["audit"])


@router.get("/logs", response_model=list[AuditLogRead])
def list_logs(
    user: CurrentUser = Depends(require_audit_reader),
    tenant_id: Optional[str] = Query(
        None,
        description="System-only filter. Tenant and portal callers are scoped from the JWT.",
    ),
    account_id: Optional[str] = Query(
        None,
        description="Filter for system and tenant staff. Portal uses the JWT account.",
    ),
    user_id: Optional[str] = None,
    action: Optional[str] = None,
    schema_name: Optional[str] = None,
    table_name: Optional[str] = None,
    record_id: Optional[str] = None,
    request_id: Optional[str] = None,
    pagination: PaginationParams = Depends(get_pagination),
    service: AuditLogService = Depends(get_audit_service),
) -> list[AuditLogRead]:
    return service.list_logs(
        user,
        tenant_id=tenant_id,
        account_id=account_id,
        user_id=user_id,
        action=action,
        schema_name=schema_name,
        table_name=table_name,
        record_id=record_id,
        request_id=request_id,
        skip=pagination.skip,
        limit=pagination.limit,
    )


@router.get("/logs/{log_id}", response_model=AuditLogRead)
def get_log(
    log_id: str,
    user: CurrentUser = Depends(require_audit_reader),
    service: AuditLogService = Depends(get_audit_service),
) -> AuditLogRead:
    log = service.get_log(user, log_id)
    if not log:
        not_found("AUDIT_LOG", "Audit log entry not found")
    return log
