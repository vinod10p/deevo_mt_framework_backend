"""Pydantic schemas — `tenant.tenant`."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# CK_tenant_status / CK_tenant_plan_type in database
TenantStatus = Literal["pending", "expired", "cancelled", "suspended", "trial", "active"]
TenantPlanType = Literal["custom", "enterprise", "professional", "starter", "trial"]


class TenantCreate(BaseModel):
    """POST body — ``id``, ``row_version``, and audit timestamps are server-generated."""

    name: Annotated[str, Field(max_length=255)]
    subdomain: Annotated[str, Field(max_length=100)]
    status: TenantStatus | None = None
    plan_type: TenantPlanType | None = None

    max_users: int | None = Field(default=None, gt=0)
    max_agents: int | None = Field(default=None, gt=0)
    max_contacts: int | None = Field(default=None, ge=0)
    storage_limit_gb: int | None = Field(default=None, ge=0)

    subscription_start_date: datetime | None = None
    subscription_end_date: datetime | None = None

    billing_email: Annotated[str | None, Field(max_length=255)] = None
    contact_email: Annotated[str | None, Field(max_length=255)] = None
    contact_phone: Annotated[str | None, Field(max_length=50)] = None

    address_line1: Annotated[str | None, Field(max_length=255)] = None
    address_line2: Annotated[str | None, Field(max_length=255)] = None
    city: Annotated[str | None, Field(max_length=100)] = None
    state: Annotated[str | None, Field(max_length=100)] = None
    postal_code: Annotated[str | None, Field(max_length=20)] = None
    country: Annotated[str | None, Field(min_length=2, max_length=2)] = None

    timezone: Annotated[str | None, Field(max_length=50)] = None
    locale: Annotated[str | None, Field(max_length=10)] = None

    logo_url: Annotated[str | None, Field(max_length=500)] = None
    settings: str | None = None
    features_enabled: str | None = None


class TenantUpdate(BaseModel):
    """PATCH body — optimistic concurrency via ``row_version``."""

    model_config = ConfigDict(val_json_bytes="base64", ser_json_bytes="base64")

    row_version: bytes

    name: Annotated[str | None, Field(max_length=255)] = None
    subdomain: Annotated[str | None, Field(max_length=100)] = None
    status: TenantStatus | None = None
    is_active: bool | None = None
    plan_type: TenantPlanType | None = None

    max_users: int | None = Field(default=None, gt=0)
    max_agents: int | None = Field(default=None, gt=0)
    max_contacts: int | None = Field(default=None, ge=0)
    storage_limit_gb: int | None = Field(default=None, ge=0)

    subscription_start_date: datetime | None = None
    subscription_end_date: datetime | None = None

    billing_email: Annotated[str | None, Field(max_length=255)] = None
    contact_email: Annotated[str | None, Field(max_length=255)] = None
    contact_phone: Annotated[str | None, Field(max_length=50)] = None

    address_line1: Annotated[str | None, Field(max_length=255)] = None
    address_line2: Annotated[str | None, Field(max_length=255)] = None
    city: Annotated[str | None, Field(max_length=100)] = None
    state: Annotated[str | None, Field(max_length=100)] = None
    postal_code: Annotated[str | None, Field(max_length=20)] = None
    country: Annotated[str | None, Field(min_length=2, max_length=2)] = None

    timezone: Annotated[str | None, Field(max_length=50)] = None
    locale: Annotated[str | None, Field(max_length=10)] = None

    logo_url: Annotated[str | None, Field(max_length=500)] = None
    settings: str | None = None
    features_enabled: str | None = None

    @field_validator("subdomain", mode="before")
    @classmethod
    def reject_null_subdomain(cls, value: object) -> object:
        if value is None:
            raise ValueError("subdomain cannot be null")
        return value


class TenantRead(BaseModel):
    """API projection — full row (JSON settings/features as strings)."""

    model_config = ConfigDict(from_attributes=True, ser_json_bytes="base64")

    id: str
    name: str
    subdomain: str

    status: str
    is_active: bool
    is_deleted: bool

    plan_type: str
    max_users: int
    max_agents: int
    max_contacts: int | None
    storage_limit_gb: int | None

    subscription_start_date: datetime | None
    subscription_end_date: datetime | None

    billing_email: str | None
    contact_email: str | None
    contact_phone: str | None

    address_line1: str | None
    address_line2: str | None
    city: str | None
    state: str | None
    postal_code: str | None
    country: str | None

    timezone: str
    locale: str

    logo_url: str | None
    settings: str | None
    features_enabled: str | None

    row_version: bytes
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    updated_by: str | None
    deleted_by: str | None


class TenantSubdomainRead(BaseModel):
    """Minimal public response for subdomain lookup — used by login pages."""

    tenant_id: str
    tenant_name: str
    subdomain: str
    is_active: bool
