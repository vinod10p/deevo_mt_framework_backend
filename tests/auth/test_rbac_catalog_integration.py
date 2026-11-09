"""Live SQL Server: system catalog CRUD for RBAC v3 (step 8)."""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from main import app
from mtf.audit.models import AuditLog
from mtf.auth.models.permission import Permission
from mtf.auth.models.role import Role
from mtf.rpt.models.report_definition import ReportDefinition
from mtf.shared.database import SessionLocal
from mtf.shared.deps import CurrentUser, get_current_user
from tests.tenant.conftest import SEEDED_SYSTEM_USER_ID, TEST_TENANT_ID

pytestmark = pytest.mark.integration

_SYSTEM_ADMIN_ID = "01JRACMTFR1000000000000005"


def _skip_if_disabled() -> None:
    if os.environ.get("DEEVO_SKIP_DB_TESTS", "").lower() in ("1", "true", "yes"):
        pytest.skip("DEEVO_SKIP_DB_TESTS is set")


def _unique_code(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


@pytest.fixture(autouse=True)
def stub_system_user(clear_app_dependency_overrides: None) -> None:
    _skip_if_disabled()
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id=SEEDED_SYSTEM_USER_ID,
        user_type="app_user",
        user_scope="system",
        tenant_id=None,
    )
    yield
    app.dependency_overrides.pop(get_current_user, None)


def _audit_actions(table_name: str, record_id: str) -> list[str]:
    with SessionLocal() as db:
        rows = db.scalars(
            select(AuditLog.action).where(
                AuditLog.schema_name == "auth",
                AuditLog.table_name == table_name,
                AuditLog.record_id == record_id,
            )
        ).all()
    return list(rows)


def test_catalog_crud_round_trip(client: TestClient) -> None:
    resource_code = _unique_code("step8")
    role_code = _unique_code("step8role")
    permission_id: str | None = None
    role_id: str | None = None
    report_id: str | None = None

    try:
        created_perm = client.post(
            "/api/auth/permissions",
            json={
                "resource_type": "screen",
                "resource_code": resource_code,
                "action": "view",
                "user_scope": "tenant",
                "description": "Step 8 catalog test",
            },
        )
        assert created_perm.status_code == 201, created_perm.text
        perm = created_perm.json()
        permission_id = perm["id"]
        expected_code = f"screen.{resource_code}.view"
        assert perm["code"] == expected_code
        assert perm["is_deleted"] is False
        assert "insert" in _audit_actions("permission", permission_id)

        duplicate = client.post(
            "/api/auth/permissions",
            json={
                "resource_type": "screen",
                "resource_code": resource_code,
                "action": "view",
                "user_scope": "tenant",
            },
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["detail"]["code"] == "AUTH_PERMISSION_CONFLICT"

        listed = client.get(
            "/api/auth/permissions",
            params={"resource_type": "screen", "user_scope": "tenant"},
        )
        assert listed.status_code == 200
        assert any(row["id"] == permission_id for row in listed.json())

        patched = client.patch(
            f"/api/auth/permissions/{permission_id}",
            json={"row_version": perm["row_version"], "description": "Patched"},
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["description"] == "Patched"
        assert patched.json()["code"] == expected_code
        assert "update" in _audit_actions("permission", permission_id)

        created_role = client.post(
            "/api/auth/roles",
            json={
                "code": role_code,
                "name": "Step 8 Role",
                "user_scope": "tenant",
            },
        )
        assert created_role.status_code == 201, created_role.text
        role = created_role.json()
        role_id = role["id"]
        assert role["tenant_id"] is None
        assert role["is_system"] is True
        assert "insert" in _audit_actions("role", role_id)

        grant = client.post(
            f"/api/auth/roles/{role_id}/permissions",
            json={"permission_id": permission_id},
        )
        assert grant.status_code == 201, grant.text
        assert grant.json()["user_scope"] == "tenant"
        grants = client.get(f"/api/auth/roles/{role_id}/permissions")
        assert grants.status_code == 200
        assert any(row["permission_id"] == permission_id for row in grants.json())

        with SessionLocal() as db:
            system_perm = db.scalars(
                select(Permission).where(
                    Permission.code == "api.system.role.update",
                    Permission.is_deleted == False,  # noqa: E712
                )
            ).first()
            system_report = db.scalars(
                select(ReportDefinition).where(
                    ReportDefinition.report_key == "tenant_account_list",
                    ReportDefinition.scope_type == "system",
                    ReportDefinition.is_deleted == False,  # noqa: E712
                )
            ).first()
            tenant_report = db.scalars(
                select(ReportDefinition).where(
                    ReportDefinition.scope_type == "tenant",
                    ReportDefinition.is_deleted == False,  # noqa: E712
                ).limit(1)
            ).first()
        if system_perm is not None:
            mismatch = client.post(
                f"/api/auth/roles/{role_id}/permissions",
                json={"permission_id": system_perm.id},
            )
            assert mismatch.status_code == 400
            assert mismatch.json()["detail"]["code"] == "AUTH_ROLE_PERMISSION_BAD_REQUEST"
        assert system_report is not None
        report_id = system_report.id

        export_without_view = client.post(
            f"/api/auth/roles/{role_id}/default-reports",
            json={"report_id": report_id, "can_view": False, "can_export": True},
        )
        assert export_without_view.status_code == 400
        assert (
            export_without_view.json()["detail"]["code"]
            == "AUTH_DEFAULT_ROLE_REPORT_BAD_REQUEST"
        )

        default = client.post(
            f"/api/auth/roles/{role_id}/default-reports",
            json={"report_id": report_id, "can_view": True, "can_export": False},
        )
        assert default.status_code == 201, default.text
        assert default.json()["can_export"] is False
        patched_default = client.patch(
            f"/api/auth/roles/{role_id}/default-reports/{report_id}",
            json={"row_version": default.json()["row_version"], "can_export": True},
        )
        assert patched_default.status_code == 200, patched_default.text
        assert patched_default.json()["can_export"] is True

        system_admin_default = client.post(
            f"/api/auth/roles/{_SYSTEM_ADMIN_ID}/default-reports",
            json={"report_id": report_id, "can_view": True},
        )
        assert system_admin_default.status_code == 400
        assert (
            system_admin_default.json()["detail"]["code"]
            == "AUTH_DEFAULT_ROLE_REPORT_BAD_REQUEST"
        )

        if tenant_report is not None:
            tenant_default = client.post(
                f"/api/auth/roles/{role_id}/default-reports",
                json={"report_id": tenant_report.id, "can_view": True},
            )
            assert tenant_default.status_code == 400
            assert (
                tenant_default.json()["detail"]["code"]
                == "AUTH_DEFAULT_ROLE_REPORT_BAD_REQUEST"
            )

        assert (
            client.delete(
                f"/api/auth/roles/{role_id}/default-reports/{report_id}"
            ).status_code
            == 204
        )
        assert (
            client.delete(
                f"/api/auth/roles/{role_id}/permissions/{permission_id}"
            ).status_code
            == 204
        )
        assert client.delete(f"/api/auth/roles/{role_id}").status_code == 204
        assert client.delete(f"/api/auth/permissions/{permission_id}").status_code == 204
        assert "delete" in _audit_actions("permission", permission_id)

        revived = client.post(
            "/api/auth/permissions",
            json={
                "resource_type": "screen",
                "resource_code": resource_code,
                "action": "view",
                "user_scope": "tenant",
            },
        )
        assert revived.status_code == 201, revived.text
        permission_id = revived.json()["id"]
        assert revived.json()["code"] == expected_code

        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            user_id=SEEDED_SYSTEM_USER_ID,
            user_type="app_user",
            user_scope="tenant",
            tenant_id=TEST_TENANT_ID,
        )
        forbidden = client.get("/api/auth/permissions")
        assert forbidden.status_code == 403
        assert forbidden.json()["detail"]["code"] == "AUTH_FORBIDDEN"

    finally:
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            user_id=SEEDED_SYSTEM_USER_ID,
            user_type="app_user",
            user_scope="system",
            tenant_id=None,
        )
        if role_id is not None and permission_id is not None:
            client.delete(f"/api/auth/roles/{role_id}/permissions/{permission_id}")
        if role_id is not None and report_id is not None:
            client.delete(f"/api/auth/roles/{role_id}/default-reports/{report_id}")
        if role_id is not None:
            client.delete(f"/api/auth/roles/{role_id}")
        if permission_id is not None:
            client.delete(f"/api/auth/permissions/{permission_id}")
        with SessionLocal() as db:
            leftover = db.scalars(
                select(Role).where(Role.code == role_code, Role.tenant_id.is_(None))
            ).first()
            if leftover is not None and leftover.is_deleted is False:
                leftover.is_deleted = True
                leftover.deleted_by = SEEDED_SYSTEM_USER_ID
                leftover.deleted_at = leftover.updated_at
                leftover.updated_by = SEEDED_SYSTEM_USER_ID
                db.add(leftover)
                db.commit()
