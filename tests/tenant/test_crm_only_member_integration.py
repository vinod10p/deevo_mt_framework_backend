"""Live SQL Server: a member with only a CRM custom role sees exactly those grants."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from main import app
from mtf.rpt.models.report_definition import ReportDefinition
from mtf.shared.database import SessionLocal
from mtf.shared.deps import get_current_user
from tests.tenant.rbac_fixtures import assign_role, create_member, custom_role
from tests.tenant.test_tenant_multi_role_integration import (
    _cleanup,
    _login,
    _me_permissions,
    _setup,
    stub_system_user,  # noqa: F401
)

pytestmark = pytest.mark.integration

_CRM_CODES = ["screen.lead.view", "screen.lead.create"]
_GRANTED_REPORT = "crm_lead_list"
_OTHER_REPORT = "crm_account_list"


def _me(client: TestClient, headers: dict[str, str]) -> dict:
    r = client.get("/api/auth/me", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _report_keys(client: TestClient, headers: dict[str, str]) -> set[str]:
    r = client.get("/api/reports", headers=headers)
    assert r.status_code == 200, r.text
    return {row["report_key"] for row in r.json()}


def _forbidden(response) -> None:
    assert response.status_code == 403, response.text
    assert response.json()["detail"]["code"] == "AUTH_FORBIDDEN"


def _system_report_id(report_key: str) -> str:
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


def test_member_with_only_custom_role_access(client: TestClient) -> None:
    ctx = _setup(client)
    tenant_id = ctx["tenant_id"]
    user_ids = [ctx["owner_user_id"]]
    try:
        app.dependency_overrides.pop(get_current_user, None)
        admin = _login(
            client, email=ctx["owner_email"], password="OwnerSecret123!", tenant_id=tenant_id
        )
        member_id, member_email = create_member(client, admin)
        user_ids.append(member_id)
        member = _login(
            client, email=member_email, password="MemberSecret123!", tenant_id=tenant_id
        )
        assert _me_permissions(client, member) == set()
        assert _report_keys(client, member) == set()

        crm = custom_role(client, admin, "crmonly", _CRM_CODES)
        assign_role(client, admin, member_id, crm["id"])

        me = _me(client, member)
        assert set(me["permissions"]) == set(_CRM_CODES)
        assert me["reports"] == []
        assert _report_keys(client, member) == set()
        assert client.get(f"/api/reports/{_GRANTED_REPORT}", headers=member).status_code == 404

        assert client.get("/api/screens/lead", headers=member).status_code == 200
        for key in ("account", "contact", "opportunity", "task", "note"):
            _forbidden(client.get(f"/api/screens/{key}", headers=member))

        _forbidden(client.get("/api/tenant/roles", headers=member))
        _forbidden(client.get("/api/tenant/permissions", headers=member))

        granted = client.post(
            f"/api/tenant/roles/{crm['id']}/reports",
            headers=admin,
            json={
                "report_id": _system_report_id(_GRANTED_REPORT),
                "can_view": True,
                "can_export": False,
            },
        )
        assert granted.status_code == 201, granted.text
        assert _report_keys(client, member) == {_GRANTED_REPORT}
        assert client.get(f"/api/reports/{_GRANTED_REPORT}", headers=member).status_code == 200
        assert client.get(f"/api/reports/{_OTHER_REPORT}", headers=member).status_code == 404
    finally:
        _cleanup(client, tenant_id, user_ids)
