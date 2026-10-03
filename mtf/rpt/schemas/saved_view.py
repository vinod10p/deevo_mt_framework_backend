"""Pydantic schemas — report saved views."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SavedViewScopeType = Literal["system", "tenant", "user"]

ViewName = Annotated[str, Field(min_length=1, max_length=200)]


class ReportSavedViewCreate(BaseModel):
    """POST body. ``criteria`` / ``layout`` are validated against the report's metadata."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    view_name: ViewName
    scope_type: SavedViewScopeType
    criteria: dict[str, Any] = Field(default_factory=dict)
    layout: dict[str, Any] = Field(default_factory=dict)
    is_default: bool = False


class ReportSavedViewUpdate(BaseModel):
    """PATCH body. Omitted fields are unchanged; ``criteria`` / ``layout`` replace the stored
    object whole. ``scope_type`` is immutable — create a new view to change tiers."""

    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, val_json_bytes="base64"
    )

    row_version: bytes
    view_name: ViewName | None = None
    criteria: dict[str, Any] | None = None
    layout: dict[str, Any] | None = None
    is_default: bool | None = None


class ReportSavedViewRead(BaseModel):
    """A saved view as the grid loads it.

    ``criteria`` / ``layout`` are returned without the stored ``version`` key; ``can_edit``
    reflects the saved-view role rules for the current caller.
    """

    model_config = ConfigDict(ser_json_bytes="base64")

    id: str
    view_name: str
    scope_type: SavedViewScopeType
    is_default: bool
    can_edit: bool
    criteria: dict[str, Any]
    layout: dict[str, Any]
    row_version: bytes
    updated_at: datetime
