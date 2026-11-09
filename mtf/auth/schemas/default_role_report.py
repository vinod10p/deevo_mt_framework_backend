"""Pydantic schemas — ``auth.default_role_report`` platform defaults."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class DefaultRoleReportCreate(BaseModel):
    """POST body — ``role_id`` comes from the path; copied to tenants at onboarding."""

    report_id: Annotated[str, Field(min_length=26, max_length=26)]
    can_view: bool = True
    can_export: bool = False


class DefaultRoleReportUpdate(BaseModel):
    """PATCH body — ``can_export`` still requires ``can_view``."""

    model_config = ConfigDict(val_json_bytes="base64", ser_json_bytes="base64")

    row_version: bytes
    can_view: bool | None = None
    can_export: bool | None = None
    is_active: bool | None = None


class DefaultRoleReportRead(BaseModel):
    """API projection for ``auth.default_role_report``."""

    model_config = ConfigDict(from_attributes=True, ser_json_bytes="base64")

    id: str
    role_id: str
    report_id: str
    can_view: bool
    can_export: bool
    is_active: bool
    is_deleted: bool
    row_version: bytes
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    updated_by: str | None
    deleted_at: datetime | None
    deleted_by: str | None
