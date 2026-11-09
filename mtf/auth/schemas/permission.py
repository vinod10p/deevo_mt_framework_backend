"""Pydantic schemas — `auth.permission` catalog."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from mtf.auth.schemas.user import UserScope

PermissionResourceType = Literal["menu", "screen", "api"]
PermissionAction = Literal[
    "view",
    "create",
    "update",
    "delete",
    "export",
    "import",
    "approve",
]


class PermissionCreate(BaseModel):
    """POST body — ``code`` is composed as ``resource_type.resource_code.action``."""

    resource_type: PermissionResourceType
    resource_code: Annotated[
        str,
        Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_.]*$"),
    ]
    action: PermissionAction
    user_scope: UserScope
    description: Annotated[str | None, Field(max_length=300)] = None


class PermissionUpdate(BaseModel):
    """PATCH body — identity columns are immutable once created."""

    model_config = ConfigDict(val_json_bytes="base64", ser_json_bytes="base64")

    row_version: bytes
    description: Annotated[str | None, Field(max_length=300)] = None
    is_active: bool | None = None


class PermissionRead(BaseModel):
    """API projection for ``auth.permission``."""

    model_config = ConfigDict(from_attributes=True, ser_json_bytes="base64")

    id: str
    code: str
    resource_type: str
    resource_code: str
    action: str
    user_scope: str
    description: str | None
    is_active: bool
    is_deleted: bool
    row_version: bytes
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    updated_by: str | None
    deleted_at: datetime | None
    deleted_by: str | None
