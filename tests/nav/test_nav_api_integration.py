"""Nav catalog integration tests (requires live SQL Server with nav schema + seed).

Apply ``sql/nav_menu_schema_v1.sql`` and ``sql/nav_menu_seed_v1.sql`` in SSMS first;
tests skip when the seeded tenant ``CRM`` module is not present.

What a tenant user sees depends on their roles, so those checks live in
``test_nav_permissions_integration.py`` (disposable tenant, real logins).
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from main import app
from mtf.nav.models import MenuModule
from mtf.shared.database import SessionLocal
from mtf.shared.deps import get_current_user
from tests.rpt.conftest import live_portal_user, live_tenant_staff

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def require_seeded_nav() -> None:
    if os.environ.get("DEEVO_SKIP_DB_TESTS", "").lower() in ("1", "true", "yes"):
        pytest.skip("DEEVO_SKIP_DB_TESTS is set")
    try:
        with SessionLocal() as db:
            found = db.scalars(
                select(MenuModule.id).where(
                    MenuModule.code == "CRM",
                    MenuModule.user_scope == "tenant",
                    MenuModule.is_deleted == False,  # noqa: E712
                    MenuModule.is_active == True,  # noqa: E712
                )
            ).first()
    except DBAPIError as exc:
        pytest.skip(f"nav schema not available: {exc.__class__.__name__}")
    if found is None:
        pytest.skip("nav catalog not seeded (sql/nav_menu_seed_v1.sql)")


def test_list_modules_portal_does_not_see_tenant_crm() -> None:
    app.dependency_overrides[get_current_user] = lambda: live_portal_user()
    r = TestClient(app).get("/api/nav/modules")
    assert r.status_code == 200, r.text
    assert "CRM" not in [row["code"] for row in r.json()["modules"]]


def test_unknown_or_portal_module_is_404_for_tenant() -> None:
    app.dependency_overrides[get_current_user] = lambda: live_tenant_staff()
    client = TestClient(app)
    missing = client.get("/api/nav/modules/NOPE/items")
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "NAV_MODULE_NOT_FOUND"
