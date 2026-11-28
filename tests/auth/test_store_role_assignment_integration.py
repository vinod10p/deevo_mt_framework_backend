"""Live SQL Server — assigning a role at a store (product decision 10, step 8).

The ``staff`` tenant's admin assigns a custom role to a new member at MAYFAIR and
KNIGHTSBRIDGE. The role grants ``menu.admin_users.view``, which the admin holds, so the
no-escalation rule allows it.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from mtf.shared.database import SessionLocal
from mtf.tenant.business_units import root_unit_id
from tests.business_unit_fixtures import add_stores
from tests.cleanup import soft_delete_users
from tests.staff_login import staff_headers
from tests.tenant.rbac_fixtures import create_member, custom_role

pytestmark = pytest.mark.integration

PERMISSION = "menu.admin_users.view"


@pytest.fixture
def world(client: TestClient, staff: dict) -> Iterator[dict]:
    headers = staff_headers(client, staff["email"], staff["tenant_id"])
    member_id, member_email = create_member(client, headers)
    stores = add_stores(staff["tenant_id"], "MAYFAIR", "KNIGHTSBRIDGE")
    with SessionLocal() as db:
        stores["COMPANY"] = root_unit_id(db, staff["tenant_id"])
    role = custom_role(client, headers, "store_clerk", [PERMISSION])
    yield {
        "headers": headers,
        "tenant_id": staff["tenant_id"],
        "member_id": member_id,
        "member_email": member_email,
        "role_id": role["id"],
        "stores": stores,
    }
    soft_delete_users(member_id)


def _roles_url(world: dict) -> str:
    return f"/api/tenant/users/{world['member_id']}/roles"


def _assign(client: TestClient, world: dict, store: str | None = None):
    body = {"role_id": world["role_id"]}
    if store is not None:
        body["business_unit_id"] = world["stores"].get(store, store)
    return client.post(_roles_url(world), json=body, headers=world["headers"])


def _held_at(client: TestClient, world: dict) -> set[str]:
    r = client.get(_roles_url(world), headers=world["headers"])
    assert r.status_code == 200, r.text
    by_id = {unit_id: code for code, unit_id in world["stores"].items()}
    return {
        by_id.get(row["business_unit_id"], "MAIN")
        for row in r.json()
        if row["role_id"] == world["role_id"]
    }


def test_one_role_held_at_two_stores_and_revoked_at_one(client: TestClient, world: dict) -> None:
    for store in ("MAYFAIR", "KNIGHTSBRIDGE"):
        r = _assign(client, world, store)
        assert r.status_code == 201, r.text
        assert r.json()["business_unit_id"] == world["stores"][store]
    assert _held_at(client, world) == {"MAYFAIR", "KNIGHTSBRIDGE"}

    again = _assign(client, world, "MAYFAIR")
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "AUTH_USER_ROLE_CONFLICT"

    revoke_url = f"{_roles_url(world)}/{world['role_id']}"
    ambiguous = client.delete(revoke_url, headers=world["headers"])
    assert ambiguous.status_code == 409, ambiguous.text

    r = client.delete(
        revoke_url,
        params={"business_unit_id": world["stores"]["MAYFAIR"]},
        headers=world["headers"],
    )
    assert r.status_code == 204, r.text
    assert _held_at(client, world) == {"KNIGHTSBRIDGE"}


def test_custom_role_without_a_store_lands_at_the_default_store(
    client: TestClient, world: dict
) -> None:
    r = _assign(client, world)
    assert r.status_code == 201, r.text
    assert _held_at(client, world) == {"MAIN"}


def test_custom_role_cannot_be_held_at_the_root(client: TestClient, world: dict) -> None:
    r = _assign(client, world, "COMPANY")
    assert r.status_code == 409
    assert r.json()["detail"] == {
        "code": "AUTH_ROLE_CONFLICT", "message": "This role can only be assigned to a store",
    }


def test_unknown_store_is_not_found(client: TestClient, world: dict) -> None:
    r = _assign(client, world, "01HZYJZGXM0KV0K4T8Y9NOSUCH")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "TENANT_BUSINESS_UNIT_NOT_FOUND"
