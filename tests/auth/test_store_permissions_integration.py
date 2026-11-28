"""Live SQL Server — permissions follow the session's store, and ``/me`` lists the stores
(product decision 9, step 6).

The ``staff`` tenant gets MAYFAIR and KNIGHTSBRIDGE next to MAIN. Its admin holds
``tenant_admin`` at the root and, for these tests, a role at KNIGHTSBRIDGE that grants
``screen.lead.view``.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from mtf.tenant.business_units import FIRST_STORE_CODE, ROOT_UNIT_CODE
from tests.business_unit_fixtures import add_stores, grant_store_role
from tests.cleanup import soft_delete_users
from tests.staff_login import PASSWORD, bearer, login_staff
from tests.tenant.rbac_fixtures import THIN_ADMIN_PERMISSIONS

pytestmark = pytest.mark.integration

STORE_PERMISSION = "screen.lead.view"


@pytest.fixture
def stores(staff: dict) -> dict[str, str]:
    stores = add_stores(staff["tenant_id"], "MAYFAIR", "KNIGHTSBRIDGE")
    grant_store_role(
        staff["tenant_id"], staff["user_id"], stores["KNIGHTSBRIDGE"], STORE_PERMISSION
    )
    return stores


def _me_at(client: TestClient, staff: dict, store: str, email: str | None = None) -> dict:
    tokens = login_staff(client, email or staff["email"], staff["tenant_id"], store=store)
    r = client.get("/api/auth/me", headers=bearer(tokens["access_token"]))
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize(
    ("store", "has_store_permission"),
    [
        ("KNIGHTSBRIDGE", True),  # root role + the role held at this store
        ("MAYFAIR", False),  # a KNIGHTSBRIDGE role grants nothing here
        (ROOT_UNIT_CODE, False),  # "All stores" mode counts root roles only
    ],
)
def test_permissions_follow_the_session_store(
    client: TestClient, staff: dict, stores: dict, store: str, has_store_permission: bool
) -> None:
    permissions = set(_me_at(client, staff, store)["permissions"])
    assert THIN_ADMIN_PERMISSIONS <= permissions  # the root role counts in every store
    assert (STORE_PERMISSION in permissions) is has_store_permission


def test_me_shows_the_store_and_the_stores_to_switch_to(
    client: TestClient, staff: dict, stores: dict
) -> None:
    me = _me_at(client, staff, "mayfair")
    assert me["business_unit"] == {
        "id": stores["MAYFAIR"], "code": "MAYFAIR", "name": "Mayfair", "bu_type": "store",
    }
    assert me["multi_store"] is True
    codes = [unit["code"] for unit in me["business_units"]]
    assert codes == [ROOT_UNIT_CODE, FIRST_STORE_CODE, "MAYFAIR", "KNIGHTSBRIDGE"]


def test_member_without_roles_can_switch_only_to_the_default_store(
    client: TestClient, staff: dict, stores: dict, system_auth_headers: dict[str, str]
) -> None:
    email = f"member-{staff['email']}"
    r = client.post(
        f"/api/tenant/{staff['tenant_id']}/users",
        json={"email": email, "password": PASSWORD, "role": "member"},
        headers=system_auth_headers,
    )
    assert r.status_code == 201, r.text
    try:
        me = _me_at(client, staff, FIRST_STORE_CODE, email=email)
        assert me["permissions"] == []
        assert [unit["code"] for unit in me["business_units"]] == [FIRST_STORE_CODE]
    finally:
        soft_delete_users(r.json()["user_id"])
