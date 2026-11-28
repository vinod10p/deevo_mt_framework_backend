"""prompts/tenant/BUSINESS_UNIT_FRONTEND_PROMPT.md — stays in step with the API (no database)."""

from __future__ import annotations

from pathlib import Path

import pytest

from main import app
from mtf.auth.schemas.session import AccessTokenResponse, BusinessUnitSwitchRequest
from mtf.auth.schemas.user import MeBusinessUnitRead, UserMeRead
from mtf.auth.schemas.user_role import UserRoleCreate
from mtf.tenant.services.business_unit_service import _MESSAGES

PROMPT = Path(__file__).resolve().parents[2] / "prompts/tenant/BUSINESS_UNIT_FRONTEND_PROMPT.md"


@pytest.fixture(scope="module")
def text() -> str:
    return " ".join(PROMPT.read_text(encoding="utf-8").split())


def _fields(model: type, prefix: str = "") -> set[str]:
    return {name for name in model.model_fields if name.startswith(prefix)}


def test_names_every_business_unit_field(text: str) -> None:
    names = (
        _fields(AccessTokenResponse, "business_unit")
        | {"multi_store"}
        | _fields(MeBusinessUnitRead)
        | {"business_unit", "business_units"} & _fields(UserMeRead)
        | _fields(BusinessUnitSwitchRequest)
        | {"business_unit_id"} & _fields(UserRoleCreate)
    )
    assert len(names) >= 11
    for name in names:
        assert f"`{name}`" in text or f'"{name}"' in text, name


def test_names_routes_that_exist(text: str) -> None:
    paths = app.openapi()["paths"]
    for path in ("/auth/session/business-unit", "/auth/browser/session/business-unit"):
        assert f"/api{path}" in paths
        assert f"{{API_BASE}}{path}" in text


def test_quotes_the_store_messages(text: str) -> None:
    for message in _MESSAGES.values():
        assert message in text


def test_keeps_the_repo_boundary(text: str) -> None:
    assert "deevoflow_react" in text
    assert "Do **not** implement this from `deevo_mt_framework_backend`" in text
