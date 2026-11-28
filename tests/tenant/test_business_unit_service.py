"""Business unit access rules (decision 7) and login-store errors (decision 6) — no database."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mtf.tenant.models.business_unit import BU_TYPE_ROOT, BU_TYPE_STORE, BusinessUnit
from mtf.tenant.services.business_unit_service import (
    AllowedUnits,
    BusinessUnitService,
    StoreAccessError,
)
from tests.conftest import TEST_BUSINESS_UNIT_ID

ROOT = BusinessUnit(id=TEST_BUSINESS_UNIT_ID, bu_type=BU_TYPE_ROOT, code="COMPANY")
MAIN = BusinessUnit(id="BU-MAIN", bu_type=BU_TYPE_STORE, code="MAIN")
MAYFAIR = BusinessUnit(id="BU-MAYFAIR", bu_type=BU_TYPE_STORE, code="MAYFAIR")
KNIGHTSBRIDGE = BusinessUnit(id="BU-KNIGHTSBRIDGE", bu_type=BU_TYPE_STORE, code="KNIGHTSBRIDGE")
ALL_UNITS = (ROOT, MAIN, MAYFAIR, KNIGHTSBRIDGE)
EVERY_CODE = {unit.code for unit in ALL_UNITS}


def _open_units(unit_ids: set[str]) -> set[str]:
    allowed = AllowedUnits.from_unit_ids(ROOT.id, unit_ids)
    return {unit.code for unit in ALL_UNITS if allowed.allows(unit)}


@pytest.mark.parametrize(
    ("role_units", "expected"),
    [
        pytest.param({ROOT.id}, EVERY_CODE, id="root-role"),
        pytest.param({MAYFAIR.id}, {"MAYFAIR"}, id="one-store-role"),
        pytest.param({MAYFAIR.id, KNIGHTSBRIDGE.id}, {"MAYFAIR", "KNIGHTSBRIDGE"}, id="two-stores"),
        pytest.param({ROOT.id, MAYFAIR.id}, EVERY_CODE, id="root-and-store"),
        pytest.param(set(), set(), id="nothing"),
    ],
)
def test_decision_7_units_open_to_each_kind_of_user(
    role_units: set[str], expected: set[str]
) -> None:
    assert _open_units(role_units) == expected


def test_root_code_needs_a_root_role() -> None:
    allowed = AllowedUnits.from_unit_ids(ROOT.id, {MAIN.id, MAYFAIR.id})
    assert allowed.has_root_role is False
    assert allowed.allows(ROOT) is False


def _service(*, role_units: list[str], default_id: str | None) -> BusinessUnitService:
    db = MagicMock()
    db.scalars.return_value = role_units
    service = BusinessUnitService(db)
    service.default_store_id = MagicMock(return_value=default_id)  # type: ignore[method-assign]
    return service


def test_member_without_roles_gets_only_the_default_store() -> None:
    allowed = _service(role_units=[], default_id=MAIN.id).allowed_units_for_staff("t", "u")
    assert allowed == AllowedUnits(ROOT.id, False, frozenset({MAIN.id}))


def test_member_without_roles_or_default_store_gets_nothing() -> None:
    allowed = _service(role_units=[], default_id=None).allowed_units_for_staff("t", "u")
    assert allowed == AllowedUnits(ROOT.id, False, frozenset())


def test_roles_replace_the_default_store() -> None:
    service = _service(role_units=[MAYFAIR.id], default_id=MAIN.id)
    allowed = service.allowed_units_for_staff("t", "u")
    assert allowed.store_ids == {MAYFAIR.id}
    service.default_store_id.assert_not_called()  # type: ignore[attr-defined]


def test_no_default_store_falls_back_to_the_store_coded_main() -> None:
    db = MagicMock()
    db.scalars.return_value.first.return_value = None
    service = BusinessUnitService(db)
    service.get_active_by_code = MagicMock(return_value=MAIN)  # type: ignore[method-assign]
    assert service.default_store_id("t", "u") == MAIN.id
    service.get_active_by_code.assert_called_once_with("t", "MAIN")  # type: ignore[attr-defined]


def _resolver(unit: BusinessUnit | None, *, role_units: set[str]) -> BusinessUnitService:
    service = BusinessUnitService(MagicMock())
    service.get_active_by_code = MagicMock(return_value=unit)  # type: ignore[method-assign]
    service.allowed_units_for_staff = MagicMock(  # type: ignore[method-assign]
        return_value=AllowedUnits.from_unit_ids(ROOT.id, role_units)
    )
    return service


@pytest.mark.parametrize("code", [None, "", "   "])
def test_missing_store_is_required(code: str | None) -> None:
    with pytest.raises(StoreAccessError) as raised:
        _resolver(MAIN, role_units={ROOT.id}).resolve_login_unit("t", "u", code)
    assert raised.value.reason == "store_required"
    assert str(raised.value) == "Store is required"


@pytest.mark.parametrize(
    ("unit", "role_units"),
    [
        pytest.param(None, {ROOT.id}, id="unknown-inactive-deleted-or-other-tenant"),
        pytest.param(MAYFAIR, {KNIGHTSBRIDGE.id}, id="store-without-a-role"),
        pytest.param(ROOT, {MAYFAIR.id}, id="root-code-without-root-role"),
    ],
)
def test_every_store_failure_is_the_same_error(
    unit: BusinessUnit | None, role_units: set[str]
) -> None:
    with pytest.raises(StoreAccessError) as raised:
        _resolver(unit, role_units=role_units).resolve_login_unit("t", "u", "ANY")
    assert raised.value.reason == "store_denied"
    assert str(raised.value) == "You don't have access to this store"


def test_allowed_store_is_returned() -> None:
    service = _resolver(MAYFAIR, role_units={MAYFAIR.id})
    assert service.resolve_login_unit("t", "u", " mayfair ") is MAYFAIR
    service.get_active_by_code.assert_called_once_with("t", " mayfair ")  # type: ignore[attr-defined]
