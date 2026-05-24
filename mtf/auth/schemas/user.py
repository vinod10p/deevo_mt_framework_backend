"""Pydantic schemas — `auth.app_user`."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

UserScope = Literal["system", "tenant", "tenant_account"]


class UserCreate(BaseModel):
    """POST body — `id` and audit/version columns are server-generated."""

    email: Annotated[EmailStr, Field(max_length=255)]
    user_scope: UserScope | None = None
    password: str | None = None

    first_name: Annotated[str | None, Field(max_length=100)] = None
    last_name: Annotated[str | None, Field(max_length=100)] = None
    phone: Annotated[str | None, Field(max_length=20)] = None
    avatar_url: Annotated[str | None, Field(max_length=500)] = None


class UserUpdate(BaseModel):
    """PATCH body — optimistic concurrency via `row_version`; omit secrets (password/MFA secret)."""

    model_config = ConfigDict(val_json_bytes="base64", ser_json_bytes="base64")

    row_version: bytes

    email: Annotated[EmailStr | None, Field(max_length=255)] = None
    user_scope: UserScope | None = None
    password: str | None = None

    first_name: Annotated[str | None, Field(max_length=100)] = None
    last_name: Annotated[str | None, Field(max_length=100)] = None
    phone: Annotated[str | None, Field(max_length=20)] = None
    avatar_url: Annotated[str | None, Field(max_length=500)] = None

    auth_provider: Annotated[str | None, Field(max_length=30)] = None
    external_id: Annotated[str | None, Field(max_length=255)] = None

    email_verified_at: datetime | None = None
    last_login_at: datetime | None = None

    is_active: bool | None = None
    is_deleted: bool | None = None
    deleted_by: Annotated[str | None, Field(max_length=26)] = None

    failed_login_count: int | None = None
    locked_until: datetime | None = None

    mfa_enabled: bool | None = None
    mfa_confirmed_at: datetime | None = None


class UserMeRead(BaseModel):
    """``GET /api/auth/me`` — profile plus tenant membership when ``user_scope=tenant``."""

    model_config = ConfigDict(from_attributes=True, ser_json_bytes="base64")

    id: str
    email: str
    email_normalized: str

    first_name: str | None
    last_name: str | None
    phone: str | None
    avatar_url: str | None

    password_changed_at: datetime | None

    auth_provider: str
    external_id: str | None

    email_verified_at: datetime | None
    last_login_at: datetime | None

    is_active: bool
    is_deleted: bool
    failed_login_count: int
    locked_until: datetime | None

    mfa_enabled: bool
    mfa_confirmed_at: datetime | None

    user_scope: str

    row_version: bytes
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    updated_by: str | None
    deleted_by: str | None

    tenant_id: str | None = None
    role: str | None = None
    account_id: str | None = None
    account_name: str | None = None
    account_code: str | None = None
    account_type: str | None = None


class UserRead(BaseModel):
    """API projection — excludes `password_hash` and `mfa_secret_enc`."""

    model_config = ConfigDict(from_attributes=True, ser_json_bytes="base64")

    id: str
    email: str
    email_normalized: str

    first_name: str | None
    last_name: str | None
    phone: str | None
    avatar_url: str | None

    password_changed_at: datetime | None

    auth_provider: str
    external_id: str | None

    email_verified_at: datetime | None
    last_login_at: datetime | None

    is_active: bool
    is_deleted: bool
    failed_login_count: int
    locked_until: datetime | None

    mfa_enabled: bool
    mfa_confirmed_at: datetime | None

    user_scope: str

    row_version: bytes
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    updated_by: str | None
    deleted_by: str | None
