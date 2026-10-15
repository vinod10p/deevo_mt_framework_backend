"""Pydantic schemas — report catalog (read-only metadata).

``proc_name`` and ``lookup_proc`` are never exposed; criteria carry ``has_lookup`` instead.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ReportScopeType = Literal["system", "tenant"]
ReportDataType = Literal["string", "int", "decimal", "date", "datetime", "bool"]
ReportControlType = Literal[
    "text", "number", "date", "daterange", "dropdown", "multiselect", "bool"
]
ReportAggregateType = Literal["sum", "avg", "count", "min", "max"]
ReportActionType = Literal["report", "screen"]
ReportActionLocation = Literal["toolbar", "row", "column"]
ReportActionScreenMode = Literal["add", "view"]
ReportActionParamSource = Literal["column", "criteria"]


class ReportSummaryRead(BaseModel):
    """List item — ``GET /api/reports``."""

    model_config = ConfigDict(from_attributes=True)

    report_key: str
    display_name: str
    description: str | None
    scope_type: ReportScopeType


class ReportColumnRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    column_name: str
    display_name: str
    data_type: ReportDataType
    display_order: int
    is_displayable: bool
    is_default_visible: bool
    is_sortable: bool
    is_groupable: bool
    is_filterable: bool
    is_aggregatable: bool
    default_aggregate_type: ReportAggregateType | None
    display_format: str | None
    default_width: int | None


class ReportCriteriaRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    criteria_key: str
    display_name: str
    data_type: ReportDataType
    control_type: ReportControlType
    has_lookup: bool
    default_value: str | None
    is_required: bool
    display_order: int


class ReportLookupOption(BaseModel):
    value: str
    label: str


class ReportLookupRead(BaseModel):
    """``GET /api/reports/{report_key}/lookups/{criteria_key}`` — dropdown options."""

    items: list[ReportLookupOption]
    has_more: bool


class ReportRunRequest(BaseModel):
    """``POST /api/reports/{report_key}/run`` body.

    ``criteria`` is keyed by ``criteria_key``; ``max_rows`` is a ceiling request, clamped
    to the report's ``default_max_rows`` (which is also used when omitted).
    """

    criteria: dict[str, Any] = Field(default_factory=dict)
    max_rows: int | None = None


class ReportRunRead(BaseModel):
    """Report rows keyed by ``report_column.column_name``; column metadata comes from
    ``GET /api/reports/{report_key}``."""

    report_key: str
    row_count: int
    truncated: bool
    rows: list[dict[str, Any]]


class ReportActionParamRead(BaseModel):
    """Maps a source row column or current criterion into a resolve target key."""

    source_type: ReportActionParamSource
    source_key: str
    target_key: str


class ReportActionRead(BaseModel):
    """Toolbar, row, or column action on a report. Internal ids are omitted."""

    action_key: str
    display_name: str
    action_type: ReportActionType
    display_location: ReportActionLocation
    trigger_column_key: str | None
    display_order: int
    screen_key: str | None = None
    screen_mode: ReportActionScreenMode | None = None
    report_key: str | None = None
    params: list[ReportActionParamRead] = Field(default_factory=list)


class ReportActionResolveRequest(BaseModel):
    """``POST /api/reports/{report_key}/actions/{action_key}/resolve`` body."""

    model_config = ConfigDict(extra="forbid")

    row: dict[str, Any] = Field(default_factory=dict)
    criteria: dict[str, Any] = Field(default_factory=dict)


class ScreenNavigationRead(BaseModel):
    target_type: Literal["screen"] = "screen"
    screen_key: str
    mode: Literal["add", "view"]
    params: dict[str, Any] = Field(default_factory=dict)


class ReportNavigationRead(BaseModel):
    target_type: Literal["report"] = "report"
    report_key: str
    criteria: dict[str, Any] = Field(default_factory=dict)


ReportActionResolveRead = ScreenNavigationRead | ReportNavigationRead


class ReportDetailRead(BaseModel):
    """``GET /api/reports/{report_key}`` — definition plus grid columns and criteria panel."""

    report_key: str
    display_name: str
    description: str | None
    scope_type: ReportScopeType
    default_max_rows: int
    columns: list[ReportColumnRead]
    criteria: list[ReportCriteriaRead]
    actions: list[ReportActionRead] = Field(default_factory=list)
