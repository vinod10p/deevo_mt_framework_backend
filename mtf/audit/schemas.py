"""Pydantic schemas — audit domain (v2)."""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

AuditAction = Literal[
    "insert",
    "update",
    "delete",
    "restore",
    "login",
    "login_failed",
    "logout",
    "access_denied",
    "export",
    "import",
]
AuditUserType = Literal["system", "tenant", "tenant_account"]

DATA_CHANGE_ACTIONS: frozenset[str] = frozenset({"insert", "update", "delete", "restore"})


class AuditLogCreate(BaseModel):
    """Internal write payload. Prefer ``append_audit_log`` from services."""

    id: Optional[str] = None
    tenant_id: Optional[str] = None
    account_id: Optional[str] = None
    session_id: Optional[str] = None
    request_id: Optional[str] = None
    user_id: Optional[str] = None
    user_type: Optional[AuditUserType] = None
    schema_name: Optional[str] = None
    table_name: Optional[str] = None
    record_id: Optional[str] = None
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
    account_id: Optional[str] = None
    session_id: Optional[str] = None
    request_id: Optional[str] = None
    user_id: Optional[str] = None
    user_type: Optional[str] = None
    schema_name: Optional[str] = None
    table_name: Optional[str] = None
    record_id: Optional[str] = None
    action: str
    old_values: Optional[str] = None
    new_values: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    reason: Optional[str] = None
    created_at: datetime
