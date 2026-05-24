"""HTTP routes — ``audit.audit_log`` resource."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from mtf.audit.schemas import AuditLogCreate, AuditLogRead
from mtf.audit.service import AuditLogService
from mtf.shared.deps import get_db

router = APIRouter()


def get_audit_service(db: Session = Depends(get_db)) -> AuditLogService:
    return AuditLogService(db)


@router.get("/logs", response_model=list[AuditLogRead])
def list_logs(
    tenant_id: Optional[str] = None,
    user_id: Optional[str] = None,
    action: Optional[str] = None,
    schema_name: Optional[str] = None,
    table_name: Optional[str] = None,
    record_id: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    service: AuditLogService = Depends(get_audit_service),
) -> list[AuditLogRead]:
    return service.list_logs(
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        schema_name=schema_name,
        table_name=table_name,
        record_id=record_id,
        skip=skip,
        limit=limit,
    )


@router.get("/logs/{log_id}", response_model=AuditLogRead)
def get_log(
    log_id: str,
    service: AuditLogService = Depends(get_audit_service),
) -> AuditLogRead:
    log = service.get_log(log_id)
    if not log:
        raise HTTPException(
            status_code=404,
            detail={"code": "AUDIT_LOG_NOT_FOUND", "message": "Audit log entry not found"},
        )
    return log


@router.post("/logs", response_model=AuditLogRead, status_code=201)
def create_log(
    payload: AuditLogCreate,
    service: AuditLogService = Depends(get_audit_service),
) -> AuditLogRead:
    return service.create_log(payload)
