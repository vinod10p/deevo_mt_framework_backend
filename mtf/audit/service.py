"""Audit domain services."""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session
from ulid import ULID

from mtf.audit.models import AuditLog
from mtf.audit.schemas import AuditLogCreate


class AuditLogService:
    def __init__(self, session: Session) -> None:
        self._db = session

    def list_logs(
        self,
        *,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
        schema_name: Optional[str] = None,
        table_name: Optional[str] = None,
        record_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[AuditLog]:
        stmt = select(AuditLog).order_by(AuditLog.created_at.desc())

        if tenant_id is not None:
            stmt = stmt.where(AuditLog.tenant_id == tenant_id)
        if user_id is not None:
            stmt = stmt.where(AuditLog.user_id == user_id)
        if action is not None:
            stmt = stmt.where(AuditLog.action == action)
        if schema_name is not None:
            stmt = stmt.where(AuditLog.schema_name == schema_name)
        if table_name is not None:
            stmt = stmt.where(AuditLog.table_name == table_name)
        if record_id is not None:
            stmt = stmt.where(AuditLog.record_id == record_id)

        stmt = stmt.offset(skip).limit(limit)
        return list(self._db.scalars(stmt).all())

    def get_log(self, log_id: str) -> AuditLog | None:
        stmt = select(AuditLog).where(AuditLog.id == log_id)
        return self._db.scalars(stmt).first()

    def create_log(self, data: AuditLogCreate) -> AuditLog:
        log = AuditLog(
            id=data.id or str(ULID()),
            tenant_id=data.tenant_id,
            session_id=data.session_id,
            user_id=data.user_id,
            user_type=data.user_type,
            schema_name=data.schema_name,
            table_name=data.table_name,
            record_id=data.record_id,
            action=data.action,
            old_values=data.old_values,
            new_values=data.new_values,
            ip_address=data.ip_address,
            user_agent=data.user_agent,
            reason=data.reason,
        )
        self._db.add(log)
        self._db.commit()
        self._db.refresh(log)
        return log
