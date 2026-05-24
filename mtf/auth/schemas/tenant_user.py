"""Pydantic schemas — `auth.tenant_user` (app user ↔ tenant membership)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

# CK_tenant_user_role in database
TenantUserRole = Literal["owner", "admin", "member", "viewer"]


class TenantMembershipCreate(BaseModel):
    """POST body — link an existing ``auth.app_user`` to a tenant (system admin API)."""

    tenant_id: Annotated[str, Field(max_length=26)]
    user_id: Annotated[str, Field(max_length=26)]
    role: TenantUserRole

    invited_at: datetime | None = None
    invited_by: Annotated[str | None, Field(max_length=26)] = None
    joined_at: datetime | None = None


class TenantMembershipUpdate(BaseModel):
    """PATCH body — optimistic concurrency via ``row_version`` (membership row only)."""

    model_config = ConfigDict(val_json_bytes="base64", ser_json_bytes="base64")

    row_version: bytes

    role: TenantUserRole | None = None

    invited_at: datetime | None = None
    invited_by: Annotated[str | None, Field(max_length=26)] = None
    joined_at: datetime | None = None

    is_active: bool | None = None
    is_deleted: bool | None = None
    deleted_by: Annotated[str | None, Field(max_length=26)] = None


class TenantMembershipRead(BaseModel):
    """API projection for ``auth.tenant_user`` — excludes ``invite_token``."""

    model_config = ConfigDict(from_attributes=True, ser_json_bytes="base64")

    id: str
    tenant_id: str
    user_id: str
    role: str

    invited_at: datetime | None
    invited_by: str | None
    joined_at: datetime | None

    is_active: bool
    is_deleted: bool

    row_version: bytes
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    updated_by: str | None
    deleted_by: str | None


TenantUserCreate = TenantMembershipCreate
TenantUserUpdate = TenantMembershipUpdate
TenantUserRead = TenantMembershipRead
