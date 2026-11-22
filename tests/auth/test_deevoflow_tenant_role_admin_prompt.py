"""prompts/auth/DEEVOFLOW_TENANT_ROLE_ADMIN.md — static contract checks (no database)."""

from __future__ import annotations

from pathlib import Path

PROMPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "prompts"
    / "auth"
    / "DEEVOFLOW_TENANT_ROLE_ADMIN.md"
)


def _prompt() -> str:
    return " ".join(PROMPT_PATH.read_text(encoding="utf-8").split())


def test_prompt_file_exists() -> None:
    assert PROMPT_PATH.is_file()


def test_targets_deevoflow_backend_not_this_repo() -> None:
    text = _prompt()
    assert "deevoflow_backend" in text
    assert "Do not implement this from `deevo_mt_framework_backend`" in text
    assert "Do not implement React here" in text
    assert "Do not add `app/` routers" in text or "no DeevoFlow proxy" in text


def test_tenant_only_portal_later() -> None:
    text = _prompt()
    assert "Tenant staff only" in text
    assert "Portal" in text
    assert "later" in text.lower()
    assert "tenant_account" in text


def test_mount_and_paths() -> None:
    text = _prompt()
    assert "/api/v1/tenant/permissions" in text
    assert "mtf.tenant" in text
    assert "api.auth.role.update" in text
    assert "AUTH_FORBIDDEN" in text
    assert "AUTH_ROLE_FORBIDDEN" in text
    assert "GET-only" in text or "grantable catalog" in text


def test_points_at_react_prompt() -> None:
    text = _prompt()
    assert "ROLE_ADMIN_FRONTEND_PROMPT.md" in text
    assert "deevoflow_react" in text
