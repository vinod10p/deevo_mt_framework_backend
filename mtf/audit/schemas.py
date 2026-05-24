"""Pydantic schemas — audit domain."""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

AuditAction = Literal["insert", "update", "delete", "login", "logout", "export", "import"]
AuditUserType = Literal["system", "tenant", "tenant_account"]


class AuditLogCreate(BaseModel):
    """Used internally by services to record an audit event."""

    id: str
    tenant_id: Optional[str] = None
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    user_type: Optional[AuditUserType] = None
    schema_name: str
    table_name: str
    record_id: str
    action: AuditAction
    old_values: Optional[str] = None
    new_values: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    reason: Optional[str] = None


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: Optional[str] = None
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    user_type: Optional[str] = None
    schema_name: str
    table_name: str
    record_id: str
    action: str
    old_values: Optional[str] = None
    new_values: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    reason: Optional[str] = None
    created_at: datetime
