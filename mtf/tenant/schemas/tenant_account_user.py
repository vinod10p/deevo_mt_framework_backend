"""Pydantic schemas — tenant account membership (portal users)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

AccountUserRole = Literal["admin", "member"]


class TenantAccountUserCreate(BaseModel):
    email: Annotated[EmailStr, Field(max_length=255)]
    password: Annotated[str | None, Field(default=None, min_length=8, max_length=255)] = None
    role: AccountUserRole = "member"
    first_name: Annotated[str | None, Field(max_length=100)] = None
    last_name: Annotated[str | None, Field(max_length=100)] = None
    phone: Annotated[str | None, Field(max_length=20)] = None
    avatar_url: Annotated[str | None, Field(max_length=500)] = None


class TenantAccountUserUpdate(BaseModel):
    model_config = ConfigDict(val_json_bytes="base64", ser_json_bytes="base64")

    row_version: bytes
    role: AccountUserRole | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=255)
    first_name: Annotated[str | None, Field(max_length=100)] = None
    last_name: Annotated[str | None, Field(max_length=100)] = None
    phone: Annotated[str | None, Field(max_length=20)] = None
    avatar_url: Annotated[str | None, Field(max_length=500)] = None


class TenantAccountUserRead(BaseModel):
    model_config = ConfigDict(ser_json_bytes="base64")

    tenant_account_user_id: str
    tenant_id: str
    account_id: str
    user_id: str
    email: str
    first_name: str | None
    last_name: str | None
    phone: str | None
    avatar_url: str | None
    user_scope: str
    last_login_at: datetime | None
    role: str
    is_active: bool
    is_deleted: bool
    joined_at: datetime | None
    invited_at: datetime | None
    row_version: bytes
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    updated_by: str | None
    deleted_by: str | None
