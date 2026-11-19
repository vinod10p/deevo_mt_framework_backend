"""Pydantic schemas — nav catalog (read-only)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

NavItemType = Literal["group", "report", "screen"]


class NavModuleSummary(BaseModel):
    """One top-bar module — ``GET /api/nav/modules`` item."""

    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    icon: str | None
    sort_order: int


class NavModuleListRead(BaseModel):
    """``GET /api/nav/modules``."""

    version: str
    modules: list[NavModuleSummary]


class NavMenuItemRead(BaseModel):
    """One submenu row. Level-1 items sit on ``items``; nested reports use ``children``."""

    model_config = ConfigDict(from_attributes=True)

    code: str
    item_type: NavItemType
    label: str
    icon: str | None
    report_key: str | None
    screen_code: str | None
    sort_order: int
    children: list[NavMenuItemRead] = Field(default_factory=list)


class NavModuleItemsRead(BaseModel):
    """``GET /api/nav/modules/{module_code}/items``."""

    version: str
    module: NavModuleSummary
    items: list[NavMenuItemRead]


NavMenuItemRead.model_rebuild()
