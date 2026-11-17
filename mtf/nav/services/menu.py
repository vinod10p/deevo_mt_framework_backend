"""Read-only nav catalog — modules for the JWT scope, then one module's tree."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from mtf.nav.models import MenuItem, MenuModule
from mtf.nav.schemas import (
    NavMenuItemRead,
    NavModuleItemsRead,
    NavModuleListRead,
    NavModuleSummary,
)
from mtf.rpt.models import ReportDefinition
from mtf.shared.deps import CurrentUser
from mtf.shared.exceptions import not_found

_EMPTY_VERSION = "1970-01-01T00:00:00.000Z"
_ITEM_TYPES = frozenset({"group", "report"})


@dataclass(frozen=True)
class ItemRow:
    """Live menu_item plus optional live report_key — used to nest the tree."""

    id: str
    parent_id: str | None
    code: str
    item_type: str
    label: str
    icon: str | None
    report_key: str | None
    sort_order: int
    updated_at: datetime
    report_updated_at: datetime | None


def version_iso(value: datetime | None) -> str:
    """UTC ISO-8601 with milliseconds and ``Z`` (matches ``datetime2(3)``)."""
    if value is None:
        return _EMPTY_VERSION
    if value.tzinfo is None:
        aware = value.replace(tzinfo=timezone.utc)
    else:
        aware = value.astimezone(timezone.utc)
    return aware.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def build_menu_tree(rows: list[ItemRow]) -> list[NavMenuItemRead]:
    """Nest live items. Drop report rows without a key and children of missing parents."""
    live = [
        row
        for row in rows
        if row.item_type in _ITEM_TYPES
        and not (row.item_type == "report" and not row.report_key)
    ]
    ids = {row.id for row in live}
    by_parent: dict[str | None, list[ItemRow]] = {}
    for row in live:
        if row.parent_id is not None and row.parent_id not in ids:
            continue
        by_parent.setdefault(row.parent_id, []).append(row)

    def to_read(row: ItemRow) -> NavMenuItemRead:
        children: list[NavMenuItemRead] = []
        if row.item_type == "group":
            nested = by_parent.get(row.id, [])
            nested.sort(key=lambda item: (item.sort_order, item.code))
            children = [to_read(child) for child in nested]
        return NavMenuItemRead(
            code=row.code,
            item_type=row.item_type,  # type: ignore[arg-type]
            label=row.label,
            icon=row.icon,
            report_key=row.report_key if row.item_type == "report" else None,
            sort_order=row.sort_order,
            children=children,
        )

    roots = by_parent.get(None, [])
    roots.sort(key=lambda item: (item.sort_order, item.code))
    return [to_read(row) for row in roots]


def _is_live(model: type[Any]):
    return and_(model.is_deleted == False, model.is_active == True)  # noqa: E712


def _module_summary(module: MenuModule) -> NavModuleSummary:
    return NavModuleSummary(
        code=module.code,
        name=module.name,
        icon=module.icon,
        sort_order=module.sort_order,
    )


class NavMenuService:
    """JWT-scoped reads of ``nav.menu_module`` and ``nav.menu_item``."""

    def __init__(self, db: Session, user: CurrentUser) -> None:
        self._db = db
        self._user = user

    def list_modules(self) -> NavModuleListRead:
        modules = list(
            self._db.scalars(
                select(MenuModule)
                .where(
                    MenuModule.user_scope == self._user.user_scope,
                    _is_live(MenuModule),
                )
                .order_by(MenuModule.sort_order, MenuModule.code)
            ).all()
        )
        latest = max((row.updated_at for row in modules), default=None)
        return NavModuleListRead(
            version=version_iso(latest),
            modules=[_module_summary(row) for row in modules],
        )

    def get_module_items(self, module_code: str) -> NavModuleItemsRead:
        code = module_code.strip().upper()
        module = self._db.scalars(
            select(MenuModule).where(
                MenuModule.code == code,
                MenuModule.user_scope == self._user.user_scope,
                _is_live(MenuModule),
            )
        ).first()
        if module is None:
            not_found("NAV_MODULE", "Module not found")

        item_rows = self._load_item_rows(module.id)
        tree = build_menu_tree(item_rows)
        timestamps = [module.updated_at]
        timestamps.extend(row.updated_at for row in item_rows)
        timestamps.extend(
            row.report_updated_at for row in item_rows if row.report_updated_at is not None
        )
        return NavModuleItemsRead(
            version=version_iso(max(timestamps)),
            module=_module_summary(module),
            items=tree,
        )

    def _load_item_rows(self, module_id: str) -> list[ItemRow]:
        stmt = (
            select(MenuItem, ReportDefinition.report_key, ReportDefinition.updated_at)
            .outerjoin(
                ReportDefinition,
                and_(
                    ReportDefinition.id == MenuItem.report_id,
                    _is_live(ReportDefinition),
                ),
            )
            .where(MenuItem.module_id == module_id, _is_live(MenuItem))
            .order_by(MenuItem.sort_order, MenuItem.code)
        )
        rows: list[ItemRow] = []
        for item, report_key, report_updated_at in self._db.execute(stmt).all():
            rows.append(
                ItemRow(
                    id=item.id,
                    parent_id=item.parent_id,
                    code=item.code,
                    item_type=item.item_type,
                    label=item.label,
                    icon=item.icon,
                    report_key=report_key,
                    sort_order=item.sort_order,
                    updated_at=item.updated_at,
                    report_updated_at=report_updated_at,
                )
            )
        return rows
