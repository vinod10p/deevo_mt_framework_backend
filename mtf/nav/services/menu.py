"""Read-only nav catalog — modules for the JWT scope, then one module's tree."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from mtf.auth.services.permission_resolver import PermissionResolver
from mtf.nav.models import MenuItem, MenuModule, NavScreen
from mtf.nav.schemas import (
    NavMenuItemRead,
    NavModuleItemsRead,
    NavModuleListRead,
    NavModuleSummary,
)
from mtf.rpt.models import ReportDefinition
from mtf.rpt.services import ReportCatalogService
from mtf.shared.deps import CurrentUser
from mtf.shared.exceptions import not_found

_EMPTY_VERSION = "1970-01-01T00:00:00.000Z"
_ITEM_TYPES = frozenset({"group", "report", "screen"})


@dataclass(frozen=True)
class ItemRow:
    """Live menu_item plus optional live report/screen codes — used to nest the tree."""

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
    screen_code: str | None = None
    screen_updated_at: datetime | None = None
    #: Permission the caller needs to see a screen item; ``None`` hides it.
    permission_code: str | None = None
    module_id: str | None = None


def filter_visible_rows(
    rows: list[ItemRow],
    *,
    report_keys: frozenset[str] | None,
    permission_codes: frozenset[str] | None,
) -> list[ItemRow]:
    """Keep only items the caller may open; ``None`` for both means no filtering.

    * report item: ``report_key`` is one the caller may view
    * screen item: ``permission_code`` is held (no code hides it)
    * group: at least one visible descendant
    """
    if report_keys is None or permission_codes is None:
        return list(rows)

    children: dict[str, list[ItemRow]] = {}
    for row in rows:
        if row.parent_id is not None:
            children.setdefault(row.parent_id, []).append(row)

    def visible(row: ItemRow, seen: frozenset[str]) -> bool:
        if row.item_type == "report":
            return row.report_key is not None and row.report_key in report_keys
        if row.item_type == "screen":
            return row.permission_code is not None and row.permission_code in permission_codes
        if row.item_type == "group":
            if row.id in seen:
                return False
            return any(visible(child, seen | {row.id}) for child in children.get(row.id, []))
        return False

    return [row for row in rows if visible(row, frozenset())]


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
    """Nest live items. Drop report/screen rows without a live code, and orphan children."""
    live = [
        row
        for row in rows
        if row.item_type in _ITEM_TYPES
        and not (row.item_type == "report" and not row.report_key)
        and not (row.item_type == "screen" and not row.screen_code)
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
            screen_code=row.screen_code if row.item_type == "screen" else None,
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
    """JWT-scoped reads of ``nav.menu_module`` and ``nav.menu_item``.

    Tenant and portal callers get only the items they may open (report grants and
    ``nav.screen.permission_code``); system callers are not filtered.
    """

    def __init__(
        self,
        db: Session,
        user: CurrentUser,
        *,
        resolver: PermissionResolver | None = None,
    ) -> None:
        self._db = db
        self._user = user
        self._resolver = resolver
        self._allowed_cache: tuple[frozenset[str], frozenset[str]] | None = None

    def _allowed(self) -> tuple[frozenset[str], frozenset[str]] | None:
        """``(viewable report keys, permission codes)``, or ``None`` for system callers."""
        if self._user.user_scope == "system":
            return None
        if self._allowed_cache is not None:
            return self._allowed_cache
        resolver = self._resolver or PermissionResolver(self._db)
        self._resolver = resolver
        codes = resolver.permission_codes(self._user)
        report_keys: frozenset[str] = frozenset()
        if self._user.tenant_id is not None:
            catalog = ReportCatalogService(self._db, user=self._user, resolver=resolver)
            report_keys = frozenset(
                summary.report_key for summary in catalog.list_reports(self._user.tenant_id)
            )
        self._allowed_cache = (report_keys, codes)
        return self._allowed_cache

    def _visible(self, rows: list[ItemRow]) -> list[ItemRow]:
        allowed = self._allowed()
        if allowed is None:
            return rows
        report_keys, codes = allowed
        return filter_visible_rows(rows, report_keys=report_keys, permission_codes=codes)

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
        if self._allowed() is not None and modules:
            by_module = self._load_item_rows([row.id for row in modules])
            modules = [row for row in modules if self._visible(by_module.get(row.id, []))]
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

        item_rows = self._visible(self._load_item_rows([module.id]).get(module.id, []))
        if self._allowed() is not None and not item_rows:
            # Same answer as an unknown module: nothing here the caller may open.
            not_found("NAV_MODULE", "Module not found")
        tree = build_menu_tree(item_rows)
        timestamps = [module.updated_at]
        timestamps.extend(row.updated_at for row in item_rows)
        timestamps.extend(
            row.report_updated_at for row in item_rows if row.report_updated_at is not None
        )
        timestamps.extend(
            row.screen_updated_at for row in item_rows if row.screen_updated_at is not None
        )
        return NavModuleItemsRead(
            version=version_iso(max(timestamps)),
            module=_module_summary(module),
            items=tree,
        )

    def _load_item_rows(self, module_ids: list[str]) -> dict[str, list[ItemRow]]:
        """Live items for the given modules, grouped by module id."""
        stmt = (
            select(
                MenuItem,
                ReportDefinition.report_key,
                ReportDefinition.updated_at,
                NavScreen.code,
                NavScreen.updated_at,
                NavScreen.permission_code,
            )
            .outerjoin(
                ReportDefinition,
                and_(
                    ReportDefinition.id == MenuItem.report_id,
                    _is_live(ReportDefinition),
                ),
            )
            .outerjoin(
                NavScreen,
                and_(
                    NavScreen.id == MenuItem.screen_id,
                    _is_live(NavScreen),
                ),
            )
            .where(MenuItem.module_id.in_(module_ids), _is_live(MenuItem))
            .order_by(MenuItem.sort_order, MenuItem.code)
        )
        rows: dict[str, list[ItemRow]] = {}
        for (
            item,
            report_key,
            report_updated_at,
            screen_code,
            screen_updated_at,
            permission_code,
        ) in self._db.execute(stmt).all():
            rows.setdefault(item.module_id, []).append(
                ItemRow(
                    id=item.id,
                    parent_id=item.parent_id,
                    code=item.code,
                    item_type=item.item_type,
                    label=item.label,
                    icon=item.icon,
                    report_key=report_key,
                    screen_code=screen_code,
                    sort_order=item.sort_order,
                    updated_at=item.updated_at,
                    report_updated_at=report_updated_at,
                    screen_updated_at=screen_updated_at,
                    permission_code=permission_code,
                    module_id=item.module_id,
                )
            )
        return rows
