"""Login-store rules against dev3 (live SQL Server): code matching and real role rows.

Two tenants: ``home`` has COMPANY (root), MAIN, MAYFAIR, KNIGHTSBRIDGE, an inactive CLOSED
and a deleted GONE; ``other`` has BONDST. Staff of ``home``: an admin (``tenant_admin`` at
root), a member with no roles, the same with no default store, and a member with a role
at KNIGHTSBRIDGE only.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from main import app
from mtf.auth.models.tenant_user import TenantUser
from mtf.shared.database import SessionLocal
from mtf.shared.deps import CurrentUser, get_current_user
from mtf.tenant.models.business_unit import BusinessUnit
from mtf.tenant.services.business_unit_service import BusinessUnitService, StoreAccessError
from tests.business_unit_fixtures import add_stores, grant_store_role
from tests.cleanup import (
    SEEDED_SYSTEM_USER_ID,
    soft_delete_tenant_roles,
    soft_delete_tenants,
    soft_delete_users,
)

pytestmark = pytest.mark.integration

BY = SEEDED_SYSTEM_USER_ID


def _create_tenant(client: TestClient, name: str) -> str:
    r = client.post(
        "/api/tenant/", json={"name": name, "subdomain": f"bu-{uuid.uuid4().hex[:12]}"}
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _add_staff(client: TestClient, tenant_id: str, role: str) -> str:
    r = client.post(
        f"/api/tenant/{tenant_id}/users",
        json={
            "email": f"bu-{uuid.uuid4().hex[:12]}@example.com",
            "password": "Secret123!",
            "role": role,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["user_id"]


@pytest.fixture(scope="module")
def world(client: TestClient) -> Iterator[dict[str, str]]:
    if os.environ.get("DEEVO_SKIP_DB_TESTS", "").lower() in ("1", "true", "yes"):
        pytest.skip("DEEVO_SKIP_DB_TESTS is set")
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id=BY, user_type="app_user", user_scope="system", tenant_id=None
    )
    tenant_ids: list[str] = []
    user_ids: list[str] = []
    try:
        home = _create_tenant(client, "Business Unit Home")
        tenant_ids.append(home)
        other = _create_tenant(client, "Business Unit Other")
        tenant_ids.append(other)
        user_ids += [
            admin := _add_staff(client, home, "admin"),
            member := _add_staff(client, home, "member"),
            unplaced := _add_staff(client, home, "member"),
            store_member := _add_staff(client, home, "member"),
        ]
        add_stores(other, "BONDST")
        stores = add_stores(home, "MAYFAIR", "KNIGHTSBRIDGE", "CLOSED", "GONE")
        grant_store_role(home, store_member, stores["KNIGHTSBRIDGE"])
        with SessionLocal() as db:
            db.get_one(BusinessUnit, stores["CLOSED"]).is_active = False
            db.get_one(BusinessUnit, stores["GONE"]).mark_deleted(BY)
            db.scalars(
                select(TenantUser).where(TenantUser.user_id == unplaced)
            ).one().default_business_unit_id = None
            db.commit()
        yield {
            "home": home,
            "admin": admin,
            "member": member,
            "unplaced": unplaced,
            "store_member": store_member,
        }
    finally:
        for tenant_id in tenant_ids:
            soft_delete_tenant_roles(tenant_id)
        soft_delete_tenants(*tenant_ids)
        soft_delete_users(*user_ids)
        app.dependency_overrides.pop(get_current_user, None)


def _resolve(world: dict[str, str], user: str, code: str) -> str:
    """The code of the unit the user logs in to, or the failure reason."""
    with SessionLocal() as db:
        try:
            unit = BusinessUnitService(db).resolve_login_unit(world["home"], world[user], code)
        except StoreAccessError as error:
            return error.reason
        return unit.code


@pytest.mark.parametrize(
    ("user", "code", "expected"),
    [
        # Root role: any active store, or the root code for "All stores".
        ("admin", "MAYFAIR", "MAYFAIR"),
        ("admin", "  mayfair ", "MAYFAIR"),
        ("admin", "company", "COMPANY"),
        ("admin", "CLOSED", "store_denied"),
        ("admin", "GONE", "store_denied"),
        ("admin", "BONDST", "store_denied"),
        ("admin", "NOPE", "store_denied"),
        ("admin", " ", "store_required"),
        # Member with no roles: their default store (MAIN) only.
        ("member", "main", "MAIN"),
        ("member", "MAYFAIR", "store_denied"),
        ("member", "COMPANY", "store_denied"),
        # No default store: the store coded MAIN.
        ("unplaced", "MAIN", "MAIN"),
        ("unplaced", "MAYFAIR", "store_denied"),
        # Role at one store: that store only, never the root.
        ("store_member", "Knightsbridge", "KNIGHTSBRIDGE"),
        ("store_member", "MAIN", "store_denied"),
        ("store_member", "COMPANY", "store_denied"),
    ],
)
def test_login_store(world: dict[str, str], user: str, code: str, expected: str) -> None:
    assert _resolve(world, user, code) == expected


def test_list_active_skips_inactive_and_deleted_root_first(world: dict[str, str]) -> None:
    with SessionLocal() as db:
        units = BusinessUnitService(db).list_active(world["home"])
    assert [unit.code for unit in units] == ["COMPANY", "MAIN", "MAYFAIR", "KNIGHTSBRIDGE"]


def test_get_root(world: dict[str, str]) -> None:
    with SessionLocal() as db:
        root = BusinessUnitService(db).get_root(world["home"])
    assert root.is_root and root.code == "COMPANY"
