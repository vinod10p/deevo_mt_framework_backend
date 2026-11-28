"""Live SQL Server: catalog and /run honor role_report; hidden reports are 404."""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from main import app
from mtf.auth.models.role_report import RoleReport
from mtf.rpt.models import ReportDefinition
from mtf.shared.database import SessionLocal
from mtf.shared.deps import CurrentUser, get_current_user
from tests.cleanup import SEEDED_SYSTEM_USER_ID, soft_delete_users
from tests.tenant.rbac_fixtures import report_access

pytestmark = pytest.mark.integration

_SEEDED_KEY = "tenant_account_list"


def _skip_if_disabled() -> None:
    if os.environ.get("DEEVO_SKIP_DB_TESTS", "").lower() in ("1", "true", "yes"):
        pytest.skip("DEEVO_SKIP_DB_TESTS is set")


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _as(user: CurrentUser) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


@pytest.fixture(autouse=True)
def rbac_ready(clear_app_dependency_overrides: None) -> None:
    _skip_if_disabled()
    try:
        with SessionLocal() as db:
            db.execute(select(1))
            present = db.execute(text("SELECT OBJECT_ID('auth.role_report', 'U')")).scalar()
            if present is None:
                pytest.skip("auth.role_report is not present")
            report = db.scalars(
                select(ReportDefinition.id).where(
                    ReportDefinition.report_key == _SEEDED_KEY,
                    ReportDefinition.scope_type == "system",
                    ReportDefinition.is_deleted == False,  # noqa: E712
                )
            ).first()
            if report is None:
                pytest.skip(f"{_SEEDED_KEY} is not seeded")
    except DBAPIError as exc:
        pytest.skip(f"database not available: {exc.__class__.__name__}")


def test_hidden_report_is_omitted_and_404_not_403() -> None:
    tenant_id: str | None = None
    user_id: str | None = None
    system = CurrentUser(
        user_id=SEEDED_SYSTEM_USER_ID,
        user_type="app_user",
        user_scope="system",
        tenant_id=None,
    )
    try:
        admin = _as(system)
        created = admin.post(
            "/api/tenant/",
            json={"name": "RBAC Report Tenant", "subdomain": _unique("rbac-rpt")},
        )
        assert created.status_code == 201, created.text
        tenant_id = created.json()["id"]

        owner = admin.post(
            f"/api/tenant/{tenant_id}/users",
            json={
                "email": f"{_unique('rbac-rpt')}@example.com",
                "password": "Secret123!",
                "role": "admin",
                "first_name": "Rbac",
                "last_name": "Owner",
            },
        )
        assert owner.status_code == 201, owner.text
        user_id = owner.json()["user_id"]
        staff = CurrentUser(
            user_id=user_id,
            user_type="app_user",
            user_scope="tenant",
            tenant_id=tenant_id,
        )
        client = _as(staff)

        with report_access(tenant_id, _SEEDED_KEY, user_id) as report_id:
            listed = client.get("/api/reports")
            assert listed.status_code == 200, listed.text
            assert _SEEDED_KEY in [row["report_key"] for row in listed.json()]

            detail = client.get(f"/api/reports/{_SEEDED_KEY}")
            assert detail.status_code == 200, detail.text

            ran = client.post(f"/api/reports/{_SEEDED_KEY}/run", json={})
            assert ran.status_code == 200, ran.text

            with SessionLocal() as db:
                grants = select(RoleReport).where(
                    RoleReport.tenant_id == tenant_id,
                    RoleReport.report_id == report_id,
                    RoleReport.is_deleted == False,  # noqa: E712
                )
                for grant in db.scalars(grants):
                    grant.is_active = False
                    grant.mark_deleted(SEEDED_SYSTEM_USER_ID)
                db.commit()

            hidden_list = client.get("/api/reports")
            assert hidden_list.status_code == 200, hidden_list.text
            assert _SEEDED_KEY not in [row["report_key"] for row in hidden_list.json()]

            hidden_get = client.get(f"/api/reports/{_SEEDED_KEY}")
            assert hidden_get.status_code == 404, hidden_get.text
            assert hidden_get.json()["detail"]["code"] == "REPORT_NOT_FOUND"

            hidden_run = client.post(f"/api/reports/{_SEEDED_KEY}/run", json={})
            assert hidden_run.status_code == 404, hidden_run.text
            assert hidden_run.json()["detail"]["code"] == "REPORT_NOT_FOUND"
            assert "FORBIDDEN" not in hidden_run.text
    finally:
        if tenant_id is not None:
            _as(system).delete(f"/api/tenant/{tenant_id}")
        if user_id is not None:
            soft_delete_users(user_id)
