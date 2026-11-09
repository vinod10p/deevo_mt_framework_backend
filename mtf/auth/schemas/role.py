"""Pydantic schemas — platform ``auth.role`` catalog (``tenant_id`` NULL)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from mtf.auth.schemas.user import UserScope


class RoleCreate(BaseModel):
    """POST body — catalog always stores ``tenant_id`` NULL and ``is_system`` true."""

    code: Annotated[str, Field(min_length=1, max_length=50, pattern=r"^[a-z][a-z0-9_]*$")]
    name: Annotated[str, Field(min_length=1, max_length=100)]
    user_scope: UserScope
    description: Annotated[str | None, Field(max_length=300)] = None


class TenantRoleCreate(BaseModel):
    """POST body — tenant-owned role (``is_system`` false, ``user_scope=tenant``)."""

    code: Annotated[str, Field(min_length=1, max_length=50, pattern=r"^[a-z][a-z0-9_]*$")]
    name: Annotated[str, Field(min_length=1, max_length=100)]
    description: Annotated[str | None, Field(max_length=300)] = None


class RoleUpdate(BaseModel):
    """PATCH body — ``code``, ``user_scope``, ``tenant_id``, and ``is_system`` stay fixed."""

    model_config = ConfigDict(val_json_bytes="base64", ser_json_bytes="base64")

    row_version: bytes
    name: Annotated[str | None, Field(min_length=1, max_length=100)] = None
    description: Annotated[str | None, Field(max_length=300)] = None
    is_active: bool | None = None


class RoleRead(BaseModel):
    """API projection for a platform ``auth.role``."""

    model_config = ConfigDict(from_attributes=True, ser_json_bytes="base64")

    id: str
    tenant_id: str | None
    code: str
    name: str
    description: str | None
    user_scope: str
    is_system: bool
    is_active: bool
    is_deleted: bool
    row_version: bytes
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    updated_by: str | None
    deleted_at: datetime | None
    deleted_by: str | None
