"""Pydantic schemas — `tenant.tenant_account_address`."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class TenantAccountAddressCreate(BaseModel):
    address_type: Annotated[str, Field(max_length=50)]
    is_default: bool = False
    address_line1: Annotated[str, Field(max_length=255)]
    address_line2: Annotated[str | None, Field(max_length=255)] = None
    city: Annotated[str | None, Field(max_length=100)] = None
    state: Annotated[str | None, Field(max_length=100)] = None
    postal_code: Annotated[str | None, Field(max_length=20)] = None
    country: Annotated[str | None, Field(min_length=2, max_length=2)] = None


class TenantAccountAddressUpdate(BaseModel):
    model_config = ConfigDict(val_json_bytes="base64", ser_json_bytes="base64")

    row_version: bytes
    address_type: Annotated[str | None, Field(max_length=50)] = None
    is_default: bool | None = None
    address_line1: Annotated[str | None, Field(max_length=255)] = None
    address_line2: Annotated[str | None, Field(max_length=255)] = None
    city: Annotated[str | None, Field(max_length=100)] = None
    state: Annotated[str | None, Field(max_length=100)] = None
    postal_code: Annotated[str | None, Field(max_length=20)] = None
    country: Annotated[str | None, Field(min_length=2, max_length=2)] = None
    is_active: bool | None = None
    is_deleted: bool | None = None
    deleted_by: Annotated[str | None, Field(max_length=26)] = None


class TenantAccountAddressRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, ser_json_bytes="base64")

    id: str
    tenant_id: str
    account_id: str
    address_type: str
    is_default: bool
    address_line1: str
    address_line2: str | None
    city: str | None
    state: str | None
    postal_code: str | None
    country: str | None
    is_active: bool
    is_deleted: bool
    row_version: bytes
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    updated_by: str | None
    deleted_by: str | None
