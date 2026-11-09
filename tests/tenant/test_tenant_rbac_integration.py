"""Live SQL Server: tenant assignment CRUD, last-admin, escalation (step 9)."""

from __future__ import annotations

import os
import uuid
from collections.abc import Generator
from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from main import app
from mtf.auth.models.permission import Permission
from mtf.auth.models.role import Role
from mtf.auth.models.user import User
from mtf.rpt.models.report_definition import ReportDefinition
from mtf.shared.database import SessionLocal
from mtf.shared.deps import CurrentUser, get_current_user
from tests.tenant.conftest import SEEDED_SYSTEM_USER_ID

pytestmark = pytest.mark.integration

_TENANT_ADMIN_ID = "01JRACMTFR1000000000000001"


def _skip_if_disabled() -> None:
    if os.environ.get("DEEVO_SKIP_DB_TESTS", "").lower() in ("1", "true", "yes"):
        pytest.skip("DEEVO_SKIP_DB_TESTS is set")


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _cleanup_user(user_id: str) -> None:
    with SessionLocal() as db:
        user = db.scalars(select(User).where(User.id == user_id)).first()
        if user is None:
            return
        user.is_active = False
        user.is_deleted = True
        user.updated_by = SEEDED_SYSTEM_USER_ID
        user.deleted_by = SEEDED_SYSTEM_USER_ID
        db.add(user)
        db.commit()


@pytest.fixture(autouse=True)
def stub_system_user(clear_app_dependency_overrides: None) -> Generator[None, None, None]:
    _skip_if_disabled()
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id=SEEDED_SYSTEM_USER_ID,
        user_type="app_user",
        user_scope="system",
        tenant_id=None,
    )
    yield
    app.dependency_overrides.pop(get_current_user, None)


def _create_tenant_with_owner(client: TestClient) -> dict[str, Any]:
    subdomain = _unique("rbac-asgn")
    owner_email = f"{_unique('asgn-owner')}@example.com"
    create_tenant = client.post(
        "/api/tenant/",
        json={"name": "RBAC Assignment Tenant", "subdomain": subdomain},
    )
    assert create_tenant.status_code == 201, create_tenant.text
    tenant_id = create_tenant.json()["id"]
    create_owner = client.post(
        f"/api/tenant/{tenant_id}/users",
        json={
            "email": owner_email,
            "password": "OwnerSecret123!",
            "role": "owner",
            "first_name": "Assign",
            "last_name": "Owner",
        },
    )
    assert create_owner.status_code == 201, create_owner.text
    return {
        "tenant_id": tenant_id,
        "owner_email": owner_email,
        "owner_user_id": create_owner.json()["user_id"],
    }


def _login(client: TestClient, *, email: str, password: str, tenant_id: str) -> dict[str, str]:
    r = client.post(
        "/api/auth/login",
        json={
            "email": email,
            "password": password,
            "tenant_id": tenant_id,
            "created_from": "web",
        },
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_tenant_assignment_crud_last_admin_and_escalation(client: TestClient) -> None:
    ctx = _create_tenant_with_owner(client)
    tenant_id = ctx["tenant_id"]
    owner_user_id = ctx["owner_user_id"]
    user_ids = [owner_user_id]
    role_id: str | None = None
    extra_permission_id: str | None = None

    try:
        app.dependency_overrides.pop(get_current_user, None)
        headers = _login(
            client,
            email=ctx["owner_email"],
            password="OwnerSecret123!",
            tenant_id=tenant_id,
        )

        roles = client.get("/api/tenant/roles", headers=headers)
        assert roles.status_code == 200, roles.text
        codes = {row["code"] for row in roles.json()}
        assert "tenant_admin" in codes
        assert "tenant_member" in codes

        platform_patch = client.patch(
            f"/api/tenant/roles/{_TENANT_ADMIN_ID}",
            headers=headers,
            json={"row_version": "AAAAAAAAAAA=", "name": "Nope"},
        )
        assert platform_patch.status_code == 403
        assert platform_patch.json()["detail"]["code"] == "AUTH_ROLE_FORBIDDEN"

        last_admin = client.delete(
            f"/api/tenant/users/{owner_user_id}/roles/{_TENANT_ADMIN_ID}",
            headers=headers,
        )
        assert last_admin.status_code == 409, last_admin.text
        assert last_admin.json()["detail"]["code"] == "AUTH_ROLE_CONFLICT"

        created_role = client.post(
            "/api/tenant/roles",
            headers=headers,
            json={"code": f"support_{uuid.uuid4().hex[:8]}", "name": "Support Lead"},
        )
        assert created_role.status_code == 201, created_role.text
        role = created_role.json()
        role_id = role["id"]
        assert role["tenant_id"] == tenant_id
        assert role["is_system"] is False

        with SessionLocal() as db:
            lead_view = db.scalars(
                select(Permission).where(
                    Permission.code == "screen.lead.view",
                    Permission.is_deleted == False,  # noqa: E712
                )
            ).first()
            report = db.scalars(
                select(ReportDefinition).where(
                    ReportDefinition.report_key == "tenant_account_list",
                    ReportDefinition.scope_type == "system",
                    ReportDefinition.is_deleted == False,  # noqa: E712
                )
            ).first()
        assert lead_view is not None
        assert report is not None

        grant = client.post(
            f"/api/tenant/roles/{role_id}/permissions",
            headers=headers,
            json={"permission_id": lead_view.id},
        )
        assert grant.status_code == 201, grant.text

        create_member = client.post(
            "/api/tenant/users",
            headers=headers,
            json={
                "email": f"{_unique('asgn-member')}@example.com",
                "password": "MemberSecret123!",
                "role": "member",
                "first_name": "Assign",
                "last_name": "Member",
            },
        )
        assert create_member.status_code == 201, create_member.text
        member_id = create_member.json()["user_id"]
        user_ids.append(member_id)

        assigned = client.post(
            f"/api/tenant/users/{member_id}/roles",
            headers=headers,
            json={"role_id": role_id},
        )
        assert assigned.status_code == 201, assigned.text
        listed = client.get(f"/api/tenant/users/{member_id}/roles", headers=headers)
        assert listed.status_code == 200
        assert any(row["role_id"] == role_id for row in listed.json())

        report_grant = client.post(
            f"/api/tenant/roles/{role_id}/reports",
            headers=headers,
            json={"report_id": report.id, "can_view": True, "can_export": True},
        )
        assert report_grant.status_code == 201, report_grant.text
        assert report_grant.json()["can_export"] is True

        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            user_id=SEEDED_SYSTEM_USER_ID,
            user_type="app_user",
            user_scope="system",
            tenant_id=None,
        )
        extra = client.post(
            "/api/auth/permissions",
            json={
                "resource_type": "screen",
                "resource_code": f"step9{uuid.uuid4().hex[:8]}",
                "action": "view",
                "user_scope": "tenant",
            },
        )
        assert extra.status_code == 201, extra.text
        extra_permission_id = extra.json()["id"]
        app.dependency_overrides.pop(get_current_user, None)

        escalate = client.post(
            f"/api/tenant/roles/{role_id}/permissions",
            headers=headers,
            json={"permission_id": extra_permission_id},
        )
        assert escalate.status_code == 403, escalate.text
        assert escalate.json()["detail"]["code"] == "AUTH_ROLE_FORBIDDEN"

        assert (
            client.delete(
                f"/api/tenant/users/{member_id}/roles/{role_id}",
                headers=headers,
            ).status_code
            == 204
        )
        assert (
            client.delete(
                f"/api/tenant/roles/{role_id}/permissions/{lead_view.id}",
                headers=headers,
            ).status_code
            == 204
        )
        assert (
            client.delete(
                f"/api/tenant/roles/{role_id}/reports/{report.id}",
                headers=headers,
            ).status_code
            == 204
        )
        assert client.delete(f"/api/tenant/roles/{role_id}", headers=headers).status_code == 204

    finally:
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            user_id=SEEDED_SYSTEM_USER_ID,
            user_type="app_user",
            user_scope="system",
            tenant_id=None,
        )
        if extra_permission_id is not None:
            client.delete(f"/api/auth/permissions/{extra_permission_id}")
        client.delete(f"/api/tenant/{tenant_id}")
        for uid in user_ids:
            _cleanup_user(uid)
        with SessionLocal() as db:
            leftover = db.scalars(
                select(Role).where(
                    Role.tenant_id == tenant_id,
                    Role.is_deleted == False,  # noqa: E712
                )
            ).all()
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            for row in leftover:
                row.is_deleted = True
                row.deleted_at = now
                row.deleted_by = SEEDED_SYSTEM_USER_ID
                row.updated_by = SEEDED_SYSTEM_USER_ID
                db.add(row)
            if leftover:
                db.commit()
