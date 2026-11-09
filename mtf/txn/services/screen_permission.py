"""Effective screen permissions — open / restricted / explicit-row rules.

Report permission wiring is a later step. Product routes pass their own ``screen_key``
(for example ``"lead"``); this module never hard-codes an entity.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from mtf.shared.exceptions import not_found
from mtf.txn.models import Screen, ScreenPermission

ScreenOperation = Literal["view", "add", "edit", "delete"]


@dataclass(frozen=True)
class ScreenEffectivePermissions:
    """Resolved flags after combining screen capabilities with the user row."""

    can_view: bool
    can_add: bool
    can_edit: bool
    can_delete: bool

    def allows(self, operation: ScreenOperation) -> bool:
        return {
            "view": self.can_view,
            "add": self.can_add,
            "edit": self.can_edit,
            "delete": self.can_delete,
        }[operation]

    def any_granted(self) -> bool:
        return self.can_view or self.can_add or self.can_edit or self.can_delete


_DENY = ScreenEffectivePermissions(
    can_view=False,
    can_add=False,
    can_edit=False,
    can_delete=False,
)


def resolve_screen_permissions(
    screen: Screen,
    row: ScreenPermission | None,
) -> ScreenEffectivePermissions:
    """Apply the API-design rules. ``row`` must be a live (not deleted) row or None.

    Deleted rows are the caller's job to drop before calling this. An inactive live
    row denies everything and does not fall back to open-mode defaults.
    """
    if row is not None and not row.is_active:
        return _DENY

    if row is None:
        if screen.permission_mode != "open":
            return _DENY
        can_view = bool(screen.allow_view)
        can_add = bool(screen.allow_add)
        can_edit = bool(screen.allow_edit) and can_view
        can_delete = bool(screen.allow_delete) and can_view
        return ScreenEffectivePermissions(
            can_view=can_view,
            can_add=can_add,
            can_edit=can_edit,
            can_delete=can_delete,
        )

    can_view = bool(screen.allow_view and row.can_access and row.can_view)
    can_add = bool(screen.allow_add and row.can_access and row.can_add)
    can_edit = bool(screen.allow_edit and row.can_access and row.can_edit and can_view)
    can_delete = bool(screen.allow_delete and row.can_access and row.can_delete and can_view)
    return ScreenEffectivePermissions(
        can_view=can_view,
        can_add=can_add,
        can_edit=can_edit,
        can_delete=can_delete,
    )


class ScreenPermissionService:
    """Load a live screen and the caller's permission row, then resolve flags."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def resolve(
        self,
        tenant_id: str,
        user_id: str,
        screen_key: str,
    ) -> ScreenEffectivePermissions:
        _, perms = self.resolve_with_screen(tenant_id, user_id, screen_key)
        return perms

    def get_live_screen(self, screen_key: str) -> Screen:
        return self._live_screen(screen_key)

    def resolve_with_screen(
        self,
        tenant_id: str,
        user_id: str,
        screen_key: str,
    ) -> tuple[Screen, ScreenEffectivePermissions]:
        screen = self.get_live_screen(screen_key)
        return screen, self.resolve_for_screen(tenant_id, user_id, screen)

    def resolve_for_screen(
        self,
        tenant_id: str,
        user_id: str,
        screen: Screen,
    ) -> ScreenEffectivePermissions:
        """Resolve flags for an already-loaded live screen (no extra screen lookup)."""
        row = self._live_permission_row(tenant_id, user_id, screen.id)
        return resolve_screen_permissions(screen, row)

    def _live_screen(self, screen_key: str) -> Screen:
        stmt = select(Screen).where(
            Screen.screen_key == screen_key,
            Screen.is_deleted == False,  # noqa: E712
            Screen.is_active == True,  # noqa: E712
        )
        screen = self._db.scalars(stmt).first()
        if screen is None:
            not_found("SCREEN", "Screen not found")
        return screen

    def _live_permission_row(
        self,
        tenant_id: str,
        user_id: str,
        screen_id: str,
    ) -> ScreenPermission | None:
        """Non-deleted row only. Inactive rows are returned so the resolver can deny."""
        stmt = select(ScreenPermission).where(
            ScreenPermission.tenant_id == tenant_id,
            ScreenPermission.user_id == user_id,
            ScreenPermission.screen_id == screen_id,
            ScreenPermission.is_deleted == False,  # noqa: E712
        )
        return self._db.scalars(stmt).first()
