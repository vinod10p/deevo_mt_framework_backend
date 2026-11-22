"""Pydantic schemas — per-user default Member role (``tenant_user.default_member_role_enabled``)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class DefaultMemberRoleRead(BaseModel):
    """``applicable`` is false for owner/admin; PATCH is rejected for them."""

    model_config = ConfigDict(ser_json_bytes="base64")

    default_member_role_enabled: bool
    applicable: bool
    #: ``auth.tenant_user.row_version`` — same value the membership endpoints return.
    row_version: bytes


class DefaultMemberRoleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", val_json_bytes="base64")

    default_member_role_enabled: bool
    row_version: bytes
