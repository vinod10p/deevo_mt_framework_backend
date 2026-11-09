"""Live SQL Server: catalog and /run honor role_report; hidden reports are 404."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from main import app
from mtf.auth.models.role_report import RoleReport
from mtf.auth.models.user import User
from mtf.rpt.models import ReportDefinition
from mtf.shared.database import SessionLocal
from mtf.shared.deps import CurrentUser, get_current_user

SEEDED_SYSTEM_USER_ID = "01HYSTEM00000000000000000"

pytestmark = pytest.mark.integration

_SEEDED_KEY = "tenant_account_list"


def _skip_if_disabled() -> None:
    if os.environ.get("DEEVO_SKIP_DB_TESTS", "").lower() in ("1", "true", "yes"):
        pytest.skip("DEEVO_SKIP_DB_TESTS is set")


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


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
                "role": "owner",
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

        listed = client.get("/api/reports")
        assert listed.status_code == 200, listed.text
        keys = [row["report_key"] for row in listed.json()]
        assert _SEEDED_KEY in keys

        detail = client.get(f"/api/reports/{_SEEDED_KEY}")
        assert detail.status_code == 200, detail.text

        ran = client.post(f"/api/reports/{_SEEDED_KEY}/run", json={})
        assert ran.status_code == 200, ran.text

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with SessionLocal() as db:
            report_id = db.scalars(
                select(ReportDefinition.id).where(
                    ReportDefinition.report_key == _SEEDED_KEY,
                    ReportDefinition.scope_type == "system",
                    ReportDefinition.is_deleted == False,  # noqa: E712
                )
            ).one()
            grants = list(
                db.scalars(
                    select(RoleReport).where(
                        RoleReport.tenant_id == tenant_id,
                        RoleReport.report_id == report_id,
                        RoleReport.is_deleted == False,  # noqa: E712
                    )
                ).all()
            )
            assert grants, "onboarding should have copied default_role_report"
            for row in grants:
                row.is_active = False
                row.is_deleted = True
                row.deleted_at = now
                row.deleted_by = SEEDED_SYSTEM_USER_ID
                row.updated_by = SEEDED_SYSTEM_USER_ID
                db.add(row)
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
            _cleanup_user(user_id)
