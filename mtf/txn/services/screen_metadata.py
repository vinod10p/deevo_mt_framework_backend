"""Frontend-ready screen metadata — tenant overrides, lookup attachments, hide rules."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from mtf.auth.services.permission_resolver import Actor
from mtf.shared.exceptions import forbidden
from mtf.txn.models import (
    Lookup,
    LookupColumn,
    Screen,
    ScreenField,
    ScreenFieldConfig,
    ScreenSection,
)
from mtf.txn.schemas.screen import (
    ScreenFieldRead,
    ScreenLookupColumnRead,
    ScreenLookupRead,
    ScreenMetadataRead,
    ScreenPermissionsRead,
    ScreenSectionRead,
)
from mtf.txn.services.screen_access import ScreenAccessService
from mtf.txn.services.screen_permission import (
    ScreenEffectivePermissions,
    ScreenPermissionService,
)


def _is_live(model: type[ScreenSection] | type[ScreenField] | type[Lookup] | type[LookupColumn]):
    return and_(model.is_deleted == False, model.is_active == True)  # noqa: E712


def usable_default(value: str | None) -> bool:
    return value is not None and value.strip() != ""


def effective_is_displayed(field: ScreenField, override: ScreenFieldConfig | None) -> bool:
    """Required fields with no usable default cannot be hidden."""
    if field.is_required and not usable_default(field.default_value):
        return True
    if override is not None and override.is_displayed is not None:
        return bool(override.is_displayed)
    return bool(field.is_displayed)


def effective_display_name(field: ScreenField, override: ScreenFieldConfig | None) -> str:
    if override is not None and override.display_name not in (None, ""):
        return override.display_name
    return field.display_name


def effective_display_order(field: ScreenField, override: ScreenFieldConfig | None) -> int:
    if override is not None and override.display_order is not None:
        return override.display_order
    return field.display_order


class ScreenMetadataService:
    def __init__(
        self,
        db: Session,
        permissions: ScreenPermissionService | None = None,
        access: ScreenAccessService | None = None,
    ) -> None:
        self._db = db
        self._permissions = permissions or ScreenPermissionService(db)
        self._access = access

    def get_screen(
        self,
        tenant_id: str,
        user_id: str,
        screen_key: str,
        user: Actor | None = None,
    ) -> ScreenMetadataRead:
        if self._access is not None and user is not None:
            screen, perms = self._access.resolve_with_screen(user, screen_key)
            deny = "AUTH" if self._access.uses_rbac(tenant_id, screen_key) else "SCREEN"
        else:
            screen, perms = self._permissions.resolve_with_screen(
                tenant_id, user_id, screen_key
            )
            deny = "SCREEN"
        if not perms.any_granted():
            forbidden(deny, "Insufficient permissions")
        return self._build(screen, perms, tenant_id)

    def _build(
        self,
        screen: Screen,
        perms: ScreenEffectivePermissions,
        tenant_id: str,
    ) -> ScreenMetadataRead:
        sections = list(
            self._db.scalars(
                select(ScreenSection)
                .where(ScreenSection.screen_id == screen.id, _is_live(ScreenSection))
                .order_by(ScreenSection.display_order, ScreenSection.section_key)
            ).all()
        )
        fields = list(
            self._db.scalars(
                select(ScreenField)
                .where(ScreenField.screen_id == screen.id, _is_live(ScreenField))
                .order_by(ScreenField.display_order, ScreenField.field_key)
            ).all()
        )
        overrides = self._load_overrides(tenant_id, [f.id for f in fields])
        lookups = self._load_lookups(fields)

        fields_by_section: dict[str, list[ScreenFieldRead]] = defaultdict(list)
        for field in fields:
            override = overrides.get(field.id)
            if not effective_is_displayed(field, override):
                continue
            lookup = lookups.get(field.lookup_id) if field.lookup_id else None
            fields_by_section[field.section_id].append(
                self._field_read(field, override, lookup)
            )

        for section_fields in fields_by_section.values():
            section_fields.sort(key=lambda item: (item.display_order, item.field_key))

        section_reads: list[ScreenSectionRead] = []
        for section in sections:
            visible = fields_by_section.get(section.id, [])
            if not visible:
                continue
            section_reads.append(
                ScreenSectionRead(
                    section_key=section.section_key,
                    display_name=section.display_name,
                    display_order=section.display_order,
                    column_count=section.column_count,
                    is_collapsible=section.is_collapsible,
                    is_collapsed_default=section.is_collapsed_default,
                    fields=visible,
                )
            )

        return ScreenMetadataRead(
            screen_key=screen.screen_key,
            display_name=screen.display_name,
            layout_type=screen.layout_type,
            api_base_path=screen.api_base_path,
            permissions=ScreenPermissionsRead(
                can_view=perms.can_view,
                can_add=perms.can_add,
                can_edit=perms.can_edit,
                can_delete=perms.can_delete,
            ),
            sections=section_reads,
        )

    def _load_overrides(
        self,
        tenant_id: str,
        field_ids: list[str],
    ) -> dict[str, ScreenFieldConfig]:
        if not field_ids:
            return {}
        rows = self._db.scalars(
            select(ScreenFieldConfig).where(
                ScreenFieldConfig.tenant_id == tenant_id,
                ScreenFieldConfig.field_id.in_(field_ids),
                ScreenFieldConfig.is_deleted == False,  # noqa: E712
                ScreenFieldConfig.is_active == True,  # noqa: E712
            )
        ).all()
        return {row.field_id: row for row in rows}

    def _load_lookups(self, fields: list[ScreenField]) -> dict[str, ScreenLookupRead]:
        lookup_ids = {field.lookup_id for field in fields if field.lookup_id}
        if not lookup_ids:
            return {}
        lookups = list(
            self._db.scalars(
                select(Lookup).where(Lookup.id.in_(lookup_ids), _is_live(Lookup))
            ).all()
        )
        if not lookups:
            return {}
        columns = list(
            self._db.scalars(
                select(LookupColumn)
                .where(LookupColumn.lookup_id.in_(lookup_ids), _is_live(LookupColumn))
                .order_by(LookupColumn.display_order, LookupColumn.field_key)
            ).all()
        )
        cols_by_lookup: dict[str, list[ScreenLookupColumnRead]] = defaultdict(list)
        for col in columns:
            cols_by_lookup[col.lookup_id].append(
                ScreenLookupColumnRead(
                    field_key=col.field_key,
                    display_name=col.display_name,
                    display_order=col.display_order,
                    is_displayed=col.is_displayed,
                    is_searchable=col.is_searchable,
                    width=col.width,
                    format_type=col.format_type,
                )
            )
        return {
            lookup.id: ScreenLookupRead(
                lookup_key=lookup.lookup_key,
                api_base_path=lookup.api_base_path,
                return_field_key=lookup.return_field_key,
                display_field_key=lookup.display_field_key,
                min_search_chars=lookup.min_search_chars,
                page_size=lookup.page_size,
                columns=cols_by_lookup.get(lookup.id, []),
            )
            for lookup in lookups
        }

    @staticmethod
    def _field_read(
        field: ScreenField,
        override: ScreenFieldConfig | None,
        lookup: ScreenLookupRead | None,
    ) -> ScreenFieldRead:
        return ScreenFieldRead(
            field_key=field.field_key,
            display_name=effective_display_name(field, override),
            data_type=field.data_type,
            control_type=field.control_type,
            display_order=effective_display_order(field, override),
            column_span=field.column_span,
            is_required=field.is_required,
            edit_mode=field.edit_mode,
            default_value=field.default_value,
            max_length=field.max_length,
            min_value=field.min_value,
            max_value=field.max_value,
            format_type=field.format_type,
            help_text=field.help_text,
            lookup=lookup if field.control_type == "dropdown" else None,
        )
