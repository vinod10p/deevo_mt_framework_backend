"""Pydantic schemas — ``auth.user_role`` tenant assignments."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class UserRoleCreate(BaseModel):
    """POST body — ``tenant_id`` and ``user_id`` come from the path / JWT."""

    role_id: Annotated[str, Field(min_length=26, max_length=26)]
    #: Where the role is held. Omitted: the root for a tenant-wide role, else the user's
    #: default store. The root itself is allowed only for tenant-wide roles.
    business_unit_id: Annotated[str | None, Field(min_length=26, max_length=26)] = None


class UserRoleRead(BaseModel):
    """API projection for ``auth.user_role``."""

    model_config = ConfigDict(from_attributes=True, ser_json_bytes="base64")

    id: str
    tenant_id: str | None
    business_unit_id: str | None
    user_id: str
    account_id: str | None
    role_id: str
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
