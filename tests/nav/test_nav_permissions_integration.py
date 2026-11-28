"""Live SQL Server: the nav menu only shows what the signed-in user may open."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from main import app
from mtf.rpt.models.report_definition import ReportDefinition
from mtf.shared.database import SessionLocal
from mtf.shared.deps import get_current_user
from tests.staff_login import staff_headers
from tests.tenant.rbac_fixtures import assign_role, create_member, custom_role
from tests.tenant.test_tenant_multi_role_integration import (
    _cleanup,
    _setup,
    stub_system_user,  # noqa: F401
)

pytestmark = pytest.mark.integration

_EPOCH = "1970-01-01T00:00:00.000Z"


def _modules(client: TestClient, headers: dict[str, str]) -> list[str]:
    r = client.get("/api/nav/modules", headers=headers)
    assert r.status_code == 200, r.text
    return [row["code"] for row in r.json()["modules"]]


def _items(client: TestClient, headers: dict[str, str], module: str) -> dict[str, dict]:
    r = client.get(f"/api/nav/modules/{module}/items", headers=headers)
    assert r.status_code == 200, r.text
    flat: dict[str, dict] = {}

    def walk(rows: list[dict]) -> None:
        for row in rows:
            flat[row["code"]] = row
            walk(row["children"])

    walk(r.json()["items"])
    return flat


def _hidden(client: TestClient, headers: dict[str, str], module: str) -> None:
    r = client.get(f"/api/nav/modules/{module}/items", headers=headers)
    assert r.status_code == 404, r.text
    assert r.json()["detail"]["code"] == "NAV_MODULE_NOT_FOUND"


def _report_id(report_key: str) -> str:
    with SessionLocal() as db:
        report = db.scalars(
            select(ReportDefinition).where(
                ReportDefinition.report_key == report_key,
                ReportDefinition.scope_type == "system",
                ReportDefinition.is_deleted == False,  # noqa: E712
            )
        ).first()
    assert report is not None, report_key
    return report.id


def test_menu_follows_roles_and_report_grants(client: TestClient) -> None:
    ctx = _setup(client)
    tenant_id = ctx["tenant_id"]
    user_ids = [ctx["owner_user_id"]]
    try:
        app.dependency_overrides.pop(get_current_user, None)
        admin = staff_headers(
            client, email=ctx["owner_email"], password="OwnerSecret123!", tenant_id=tenant_id
        )

        # Thin admin: Admin module only.
        assert _modules(client, admin) == ["ADMIN"]
        admin_items = _items(client, admin, "ADMIN")
        assert {"ADMIN.USERS", "ADMIN.PORTAL_ACCOUNTS"} <= set(admin_items)
        _hidden(client, admin, "CRM")
        _hidden(client, admin, "WF")

        # Empty member: no modules.
        member_id, member_email = create_member(client, admin)
        user_ids.append(member_id)
        member = staff_headers(
            client, email=member_email, password="MemberSecret123!", tenant_id=tenant_id
        )
        assert _modules(client, member) == []
        _hidden(client, member, "ADMIN")

        # Screen permissions open matching screen items only.
        part_id, part_email = create_member(client, admin)
        user_ids.append(part_id)
        part = staff_headers(client, part_email, tenant_id, password="MemberSecret123!")
        role = custom_role(client, admin, "partial", ["screen.note.view", "menu.wf_inbox.view"])
        assign_role(client, admin, part_id, role["id"])
        assert _modules(client, part) == ["CRM", "WF"]
        assert set(_items(client, part, "CRM")) == {"CRM.NOTES"}
        assert set(_items(client, part, "WF")) == {"WF.INBOX"}
        _hidden(client, part, "EMAIL")
        _hidden(client, part, "ADMIN")

        granted = client.post(
            f"/api/tenant/roles/{role['id']}/reports",
            headers=admin,
            json={"report_id": _report_id("crm_lead_list"), "can_view": True, "can_export": False},
        )
        assert granted.status_code == 201, granted.text
        assert set(_items(client, part, "CRM")) == {"CRM.LEADS", "CRM.NOTES"}

        only_id, only_email = create_member(client, admin)
        user_ids.append(only_id)
        only = staff_headers(client, only_email, tenant_id, password="MemberSecret123!")
        crm_only = custom_role(client, admin, "crmonly", ["screen.lead.view", "screen.lead.create"])
        assign_role(client, admin, only_id, crm_only["id"])
        r = client.get("/api/nav/modules", headers=only)
        assert r.status_code == 200, r.text
        assert r.json() == {"version": _EPOCH, "modules": []}
        _hidden(client, only, "CRM")
    finally:
        _cleanup(client, tenant_id, user_ids)
