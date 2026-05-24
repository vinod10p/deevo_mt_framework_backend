"""Pydantic schemas — tenant-managed users under ``tenant.tenant``."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

TenantUserRole = Literal["owner", "admin", "member", "viewer"]


class TenantUserCreate(BaseModel):
    """POST body for creating an ``auth.app_user`` and linking it to a tenant."""

    email: Annotated[EmailStr, Field(max_length=255)]
    password: Annotated[str | None, Field(default=None, min_length=8, max_length=255)] = None
    role: TenantUserRole

    first_name: Annotated[str | None, Field(max_length=100)] = None
    last_name: Annotated[str | None, Field(max_length=100)] = None
    phone: Annotated[str | None, Field(max_length=20)] = None
    avatar_url: Annotated[str | None, Field(max_length=500)] = None


class TenantUserUpdate(BaseModel):
    """PATCH body — membership + optional ``app_user`` profile fields."""

    model_config = ConfigDict(val_json_bytes="base64", ser_json_bytes="base64")

    row_version: bytes
    role: TenantUserRole | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=255)
    first_name: Annotated[str | None, Field(max_length=100)] = None
    last_name: Annotated[str | None, Field(max_length=100)] = None
    phone: Annotated[str | None, Field(max_length=20)] = None
    avatar_url: Annotated[str | None, Field(max_length=500)] = None


class TenantUserRead(BaseModel):
    """Join response combining ``auth.tenant_user`` and ``auth.app_user`` fields."""

    model_config = ConfigDict(ser_json_bytes="base64")

    tenant_user_id: str
    tenant_id: str
    user_id: str

    email: str
    first_name: str | None
    last_name: str | None
    phone: str | None
    avatar_url: str | None
    user_scope: str
    last_login_at: datetime | None
    is_deleted: bool

    role: str
    is_active: bool
    joined_at: datetime | None
    invited_at: datetime | None

    row_version: bytes
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    updated_by: str | None
    deleted_by: str | None
