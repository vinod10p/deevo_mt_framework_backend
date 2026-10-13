"""Pydantic schemas — frontend-ready screen metadata.

Internal ids (screen, section, field, lookup) are not exposed.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

ScreenLayoutType = Literal["standard", "tabs"]
ScreenDataType = Literal["string", "integer", "decimal", "date", "datetime", "boolean"]
ScreenControlType = Literal[
    "text",
    "textarea",
    "number",
    "date",
    "datetime",
    "dropdown",
    "checkbox",
    "email",
    "phone",
]
ScreenEditMode = Literal["editable", "create_only", "readonly"]
ScreenFormatType = Literal["decimal", "currency", "percent", "weight"]


class ScreenPermissionsRead(BaseModel):
    can_view: bool
    can_add: bool
    can_edit: bool
    can_delete: bool


class ScreenLookupColumnRead(BaseModel):
    field_key: str
    display_name: str
    display_order: int
    is_displayed: bool
    is_searchable: bool
    width: int | None
    format_type: str | None


class ScreenLookupRead(BaseModel):
    lookup_key: str
    api_base_path: str
    return_field_key: str
    display_field_key: str | None
    min_search_chars: int
    page_size: int
    columns: list[ScreenLookupColumnRead]


class ScreenFieldRead(BaseModel):
    field_key: str
    display_name: str
    data_type: ScreenDataType
    control_type: ScreenControlType
    display_order: int
    column_span: int
    is_required: bool
    edit_mode: ScreenEditMode
    default_value: str | None
    max_length: int | None
    min_value: Decimal | None
    max_value: Decimal | None
    format_type: str | None
    help_text: str | None
    lookup: ScreenLookupRead | None


class ScreenSectionRead(BaseModel):
    section_key: str
    display_name: str
    display_order: int
    column_count: int
    is_collapsible: bool
    is_collapsed_default: bool
    fields: list[ScreenFieldRead]


class ScreenMetadataRead(BaseModel):
    """``GET /api/screens/{screen_key}``."""

    screen_key: str
    display_name: str
    layout_type: ScreenLayoutType
    api_base_path: str
    permissions: ScreenPermissionsRead
    sections: list[ScreenSectionRead]
