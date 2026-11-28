"""Business units a staff user may work in — login store and store switch (decisions 6–8).

Access comes from where the user's live roles are held:

* a role at the **root** unit opens every active store, and the root itself ("All stores");
* a role at a **store** opens that store;
* a member with **no live roles** may use only their default store (else the store ``MAIN``).

Store codes are matched trimmed and case-insensitive, within one tenant. Every failure is the
same :class:`StoreAccessError`, so a caller can't tell an unknown store from a forbidden one.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from mtf.auth.models.role import Role
from mtf.auth.models.tenant_user import TenantUser
from mtf.auth.models.user_role import UserRole
from mtf.tenant.business_units import FIRST_STORE_CODE, root_unit_id
from mtf.tenant.models.business_unit import BU_TYPE_ROOT, BusinessUnit

StoreFailure = Literal["store_required", "store_denied"]

_MESSAGES: dict[StoreFailure, str] = {
    "store_required": "Store is required",
    "store_denied": "You don't have access to this store",
}


class StoreAccessError(Exception):
    """The store is missing or not one the user may use; ``reason`` is the audit reason."""

    def __init__(self, reason: StoreFailure) -> None:
        super().__init__(_MESSAGES[reason])
        self.reason = reason


@dataclass(frozen=True)
class AllowedUnits:
    """The units one staff user may log in to or switch to."""

    root_id: str
    has_root_role: bool
    store_ids: frozenset[str]

    @classmethod
    def from_unit_ids(cls, root_id: str, unit_ids: Iterable[str]) -> AllowedUnits:
        """Build from the units the user's roles are held at."""
        unit_ids = set(unit_ids)
        return cls(root_id, root_id in unit_ids, frozenset(unit_ids - {root_id}))

    def allows(self, unit: BusinessUnit) -> bool:
        """Whether ``unit`` (an active unit of the same tenant) is open to the user."""
        if unit.is_root:
            return self.has_root_role
        return self.has_root_role or unit.id in self.store_ids


class BusinessUnitService:
    def __init__(self, session: Session) -> None:
        self._db = session

    def get_root(self, tenant_id: str) -> BusinessUnit:
        return self._db.get_one(BusinessUnit, root_unit_id(self._db, tenant_id))

    def get_active(self, tenant_id: str, unit_id: str) -> BusinessUnit | None:
        return self._db.scalars(self._active(tenant_id).where(BusinessUnit.id == unit_id)).first()

    def get_active_by_code(self, tenant_id: str, code: str) -> BusinessUnit | None:
        by_code = func.upper(BusinessUnit.code) == code.strip().upper()
        return self._db.scalars(self._active(tenant_id).where(by_code)).first()

    def list_active(self, tenant_id: str) -> list[BusinessUnit]:
        return list(self._db.scalars(self._active(tenant_id)))

    def list_open_to_staff(self, tenant_id: str, user_id: str) -> list[BusinessUnit]:
        """Active units the staff user may log in to or switch to, in ``sort_order``."""
        allowed = self.allowed_units_for_staff(tenant_id, user_id)
        return [unit for unit in self.list_active(tenant_id) if allowed.allows(unit)]

    def is_multi_store(self, tenant_id: str) -> bool:
        """Whether the tenant has more than one active store (the app then offers a switcher)."""
        stores = self._active(tenant_id).where(BusinessUnit.bu_type != BU_TYPE_ROOT).limit(2)
        return len(self._db.scalars(stores).all()) > 1

    def allowed_units_for_staff(self, tenant_id: str, user_id: str) -> AllowedUnits:
        unit_ids = set(self._db.scalars(self._role_units(tenant_id, user_id)))
        if not unit_ids:
            default_id = self.default_store_id(tenant_id, user_id)
            unit_ids = {default_id} if default_id else set()
        return AllowedUnits.from_unit_ids(root_unit_id(self._db, tenant_id), unit_ids)

    def resolve_login_unit(self, tenant_id: str, user_id: str, code: str | None) -> BusinessUnit:
        """The active unit ``code`` names, if the user may use it; else ``StoreAccessError``."""
        if not code or not code.strip():
            raise StoreAccessError("store_required")
        return self._open_to(tenant_id, user_id, self.get_active_by_code(tenant_id, code))

    def recheck_session_unit(
        self, tenant_id: str, user_id: str, unit_id: str | None
    ) -> BusinessUnit:
        """The session's unit if still active and still open to the user (on refresh)."""
        unit = self.get_active(tenant_id, unit_id) if unit_id is not None else None
        return self._open_to(tenant_id, user_id, unit)

    def default_store_id(self, tenant_id: str, user_id: str) -> str | None:
        """The member's default store, else the active store coded ``MAIN``."""
        default_id = self._db.scalars(
            select(TenantUser.default_business_unit_id).where(
                TenantUser.tenant_id == tenant_id,
                TenantUser.user_id == user_id,
                TenantUser.is_deleted == False,  # noqa: E712
            )
        ).first()
        if default_id is not None:
            return default_id
        main = self.get_active_by_code(tenant_id, FIRST_STORE_CODE)
        return main.id if main is not None else None

    def _open_to(self, tenant_id: str, user_id: str, unit: BusinessUnit | None) -> BusinessUnit:
        if unit is None or not self.allowed_units_for_staff(tenant_id, user_id).allows(unit):
            raise StoreAccessError("store_denied")
        return unit

    def _active(self, tenant_id: str) -> Select[tuple[BusinessUnit]]:
        return (
            select(BusinessUnit)
            .where(
                BusinessUnit.tenant_id == tenant_id,
                BusinessUnit.is_active == True,  # noqa: E712
                BusinessUnit.is_deleted == False,  # noqa: E712
            )
            .order_by(BusinessUnit.sort_order, BusinessUnit.code)
        )

    def _role_units(self, tenant_id: str, user_id: str) -> Select[tuple[str]]:
        """Units at which the user holds a live tenant role."""
        return (
            select(UserRole.business_unit_id)
            .distinct()
            .join(Role, Role.id == UserRole.role_id)
            .where(
                UserRole.tenant_id == tenant_id,
                UserRole.user_id == user_id,
                UserRole.user_scope == "tenant",
                UserRole.is_active == True,  # noqa: E712
                UserRole.is_deleted == False,  # noqa: E712
                Role.is_active == True,  # noqa: E712
                Role.is_deleted == False,  # noqa: E712
            )
        )
