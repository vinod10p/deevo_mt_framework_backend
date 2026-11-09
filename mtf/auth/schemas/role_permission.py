"""Pydantic schemas — ``auth.role_permission`` catalog grants."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class RolePermissionCreate(BaseModel):
    """POST body — ``role_id`` and ``user_scope`` come from the platform role."""

    permission_id: Annotated[str, Field(min_length=26, max_length=26)]


class RolePermissionRead(BaseModel):
    """API projection for ``auth.role_permission``."""

    model_config = ConfigDict(from_attributes=True, ser_json_bytes="base64")

    id: str
    role_id: str
    permission_id: str
    user_scope: str
    is_active: bool
    is_deleted: bool
    row_version: bytes
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    updated_by: str | None
    deleted_at: datetime | None
    deleted_by: str | None
