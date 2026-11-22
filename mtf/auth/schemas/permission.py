"""Pydantic schemas — `auth.permission` catalog."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    module_code: Annotated[
        str,
        Field(min_length=1, max_length=50, pattern=r"^[A-Z][A-Z0-9_]*$"),
    ] = "GENERAL"
    resource_name: Annotated[str | None, Field(min_length=1, max_length=100)] = None
    sort_order: Annotated[int, Field(ge=0)] = 0
    is_tenant_grantable: bool = True

    @field_validator("module_code", mode="before")
    @classmethod
    def uppercase_module_code(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().upper()
        return value


class PermissionUpdate(BaseModel):
    """PATCH body — identity columns are immutable once created."""

    model_config = ConfigDict(val_json_bytes="base64", ser_json_bytes="base64")

    row_version: bytes
    description: Annotated[str | None, Field(max_length=300)] = None
    is_active: bool | None = None
    module_code: Annotated[
        str | None,
        Field(min_length=1, max_length=50, pattern=r"^[A-Z][A-Z0-9_]*$"),
    ] = None
    resource_name: Annotated[str | None, Field(min_length=1, max_length=100)] = None
    sort_order: Annotated[int | None, Field(ge=0)] = None
    is_tenant_grantable: bool | None = None

    @field_validator("module_code", mode="before")
    @classmethod
    def uppercase_module_code(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().upper()
        return value


class TenantPermissionRead(BaseModel):
    """Grantable catalog row for the tenant Role Admin grid."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    code: str
    resource_type: str
    resource_code: str
    action: str
    module_code: str
    resource_name: str
    sort_order: int


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
    module_code: str
    resource_name: str
    sort_order: int
    is_tenant_grantable: bool
    is_active: bool
    is_deleted: bool
    row_version: bytes
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    updated_by: str | None
    deleted_at: datetime | None
    deleted_by: str | None
