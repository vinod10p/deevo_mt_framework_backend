"""Pydantic schemas — `tenant.tenant_account`."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

AccountType = Literal["customer", "vendor", "employee"]


class TenantAccountCreate(BaseModel):
    """POST body — ``tenant_id`` comes from JWT or path, not this payload."""

    account_code: Annotated[str, Field(max_length=26)]
    account_type: AccountType
    name: Annotated[str, Field(max_length=255)]

    email: Annotated[str | None, Field(max_length=255)] = None
    phone: Annotated[str | None, Field(max_length=50)] = None
    website: Annotated[str | None, Field(max_length=500)] = None
    custom_fields: str | None = None
    status: Annotated[str | None, Field(max_length=20)] = None


class TenantAccountUpdate(BaseModel):
    """PATCH body — optimistic concurrency via ``row_version``."""

    model_config = ConfigDict(val_json_bytes="base64", ser_json_bytes="base64")

    row_version: bytes

    account_code: Annotated[str | None, Field(max_length=26)] = None
    account_type: AccountType | None = None
    name: Annotated[str | None, Field(max_length=255)] = None
    email: Annotated[str | None, Field(max_length=255)] = None
    phone: Annotated[str | None, Field(max_length=50)] = None
    website: Annotated[str | None, Field(max_length=500)] = None
    custom_fields: str | None = None
    status: Annotated[str | None, Field(max_length=20)] = None
    is_active: bool | None = None
    is_deleted: bool | None = None
    deleted_by: Annotated[str | None, Field(max_length=26)] = None


class TenantAccountRead(BaseModel):
    """API projection — full account row."""

    model_config = ConfigDict(from_attributes=True, ser_json_bytes="base64")

    id: str
    tenant_id: str
    account_code: str
    account_type: str
    name: str
    email: str | None
    phone: str | None
    website: str | None
    custom_fields: str | None
    status: str
    is_active: bool
    is_deleted: bool
    row_version: bytes
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    updated_by: str | None
    deleted_by: str | None


class TenantAccountListResponse(BaseModel):
    items: list[TenantAccountRead]
    total: int
    skip: int
    limit: int
