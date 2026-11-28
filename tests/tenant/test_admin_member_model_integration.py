"""Live SQL Server: admin|member membership — thin admin template, empty member."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from main import app
from mtf.shared.database import SessionLocal
from mtf.shared.deps import get_current_user
from tests.sql_scripts import apply_sql_script
from tests.staff_login import staff_headers
from tests.tenant.rbac_fixtures import (
    THIN_ADMIN_PERMISSIONS,
    assign_role,
    create_member,
    custom_role,
)
from tests.tenant.test_tenant_multi_role_integration import (
    _cleanup,
    _me_permissions,
    _role_codes,
    _setup,
    stub_system_user,  # noqa: F401
)

pytestmark = pytest.mark.integration

FIX_PATH = Path(__file__).resolve().parents[2] / "sql" / "rbac_fix_05_admin_member_only.sql"

@pytest.fixture(scope="module", autouse=True)
def _applied() -> None:
    if os.environ.get("DEEVO_SKIP_DB_TESTS", "").lower() in ("1", "true", "yes"):
        pytest.skip("DEEVO_SKIP_DB_TESTS is set")
    apply_sql_script(FIX_PATH)


def test_admin_thin_member_empty_and_custom_roles(client: TestClient) -> None:
    ctx = _setup(client)
    tenant_id = ctx["tenant_id"]
    user_ids = [ctx["owner_user_id"]]
    try:
        app.dependency_overrides.pop(get_current_user, None)
        admin = staff_headers(
            client, email=ctx["owner_email"], password="OwnerSecret123!", tenant_id=tenant_id
        )
        assert set(_role_codes(client, admin, ctx["owner_user_id"]).values()) == {"tenant_admin"}
        assert THIN_ADMIN_PERMISSIONS <= _me_permissions(client, admin)
        assert not any(c.startswith("screen.") for c in _me_permissions(client, admin))
        modules = client.get("/api/nav/modules", headers=admin)
        assert modules.status_code == 200
        assert [m["code"] for m in modules.json()["modules"]] == ["ADMIN"]

        member_id, member_email = create_member(client, admin)
        user_ids.append(member_id)
        member = staff_headers(
            client, email=member_email, password="MemberSecret123!", tenant_id=tenant_id
        )
        assert _role_codes(client, admin, member_id) == {}
        assert _me_permissions(client, member) == set()
        empty_nav = client.get("/api/nav/modules", headers=member)
        assert empty_nav.status_code == 200
        assert empty_nav.json()["modules"] == []

        role = custom_role(client, admin, "crm", ["screen.lead.view", "screen.note.view"])
        assign_role(client, admin, member_id, role["id"])
        assert set(_role_codes(client, admin, member_id).values()) == {role["code"]}
        assert _me_permissions(client, member) == {"screen.lead.view", "screen.note.view"}
        assert [
            m["code"] for m in client.get("/api/nav/modules", headers=member).json()["modules"]
        ] == ["CRM"]

        # Platform templates cannot be assigned through Role Admin.
        templates = {
            row["code"]: row["id"]
            for row in client.get("/api/tenant/roles", headers=admin).json()
            if row["is_system"]
        }
        for code in ("tenant_admin", "tenant_member"):
            bad = client.post(
                f"/api/tenant/users/{member_id}/roles",
                headers=admin,
                json={"role_id": templates[code]},
            )
            assert bad.status_code == 409, bad.text
            assert bad.json()["detail"]["code"] == "AUTH_USER_ROLE_CONFLICT"

        # Promote member → admin: gains thin template, keeps custom role.
        staff = client.get(f"/api/tenant/users/{member_id}", headers=admin).json()
        promoted = client.patch(
            f"/api/tenant/users/{member_id}",
            headers=admin,
            json={"row_version": staff["row_version"], "role": "admin"},
        )
        assert promoted.status_code == 200, promoted.text
        assert set(_role_codes(client, admin, member_id).values()) == {
            "tenant_admin",
            role["code"],
        }
        assert THIN_ADMIN_PERMISSIONS <= _me_permissions(client, member)

        # Demote back: loses template, keeps custom.
        staff = client.get(f"/api/tenant/users/{member_id}", headers=admin).json()
        demoted = client.patch(
            f"/api/tenant/users/{member_id}",
            headers=admin,
            json={"row_version": staff["row_version"], "role": "member"},
        )
        assert demoted.status_code == 200, demoted.text
        assert set(_role_codes(client, admin, member_id).values()) == {role["code"]}
        assert _me_permissions(client, member) == {"screen.lead.view", "screen.note.view"}
    finally:
        _cleanup(client, tenant_id, user_ids)


def test_lg_only_a_lg_remains_admin() -> None:
    with SessionLocal() as db:
        rows = db.execute(
            text(
                """
                SELECT u.email_normalized, tu.role
                FROM auth.tenant_user tu
                JOIN auth.app_user u ON u.id = tu.user_id
                JOIN tenant.tenant t ON t.id = tu.tenant_id
                WHERE t.subdomain = 'lg' AND tu.is_deleted = 0
                ORDER BY u.email_normalized
                """
            )
        ).all()
    assert rows == [("a@lg.com", "admin")]
