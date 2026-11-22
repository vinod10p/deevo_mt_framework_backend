"""prompts/auth/ROLE_ADMIN_FRONTEND_PROMPT.md — static contract checks (no database)."""

from __future__ import annotations

from pathlib import Path

PROMPT_PATH = (
    Path(__file__).resolve().parents[2] / "prompts" / "auth" / "ROLE_ADMIN_FRONTEND_PROMPT.md"
)


def _prompt() -> str:
    return " ".join(PROMPT_PATH.read_text(encoding="utf-8").split())


def test_prompt_file_exists() -> None:
    assert PROMPT_PATH.is_file()


def test_targets_react_not_this_repo() -> None:
    text = _prompt()
    assert "deevoflow_react" in text
    assert "Do **not** implement this from `deevo_mt_framework_backend`" in text
    assert "Do **not** implement this in `deevoflow_backend`" in text
    assert "Do not add a DeevoFlow proxy" in text
    assert "DEEVOFLOW_TENANT_ROLE_ADMIN.md" in text
    assert "Portal Role Admin is **later**" in text


def test_never_sends_tenant_id() -> None:
    text = _prompt()
    assert "Never send `tenant_id`" in text or "never sent" in text
    assert "must not include `tenant_id`" in text


def test_hides_without_role_admin_permission() -> None:
    text = _prompt()
    assert "api.auth.role.update" in text
    assert "GET {API_BASE}/auth/me" in text
    assert "AUTH_FORBIDDEN" in text


def test_catalog_is_get_only() -> None:
    text = _prompt()
    assert "GET {API_BASE}/tenant/permissions" in text
    assert "Tenants never create or edit the permission catalog" in text
    assert "permission_id" in text
    assert "never by composing a code" in text


def test_templates_are_read_only_and_copy_is_out_of_scope() -> None:
    text = _prompt()
    assert "is_system" in text
    assert "read-only" in text.lower() or "read-only" in text
    assert "source_role_id" in text
    assert "No copy-from-template" in text or "no `source_role_id`" in text


def test_grant_and_assign_paths() -> None:
    text = _prompt()
    assert "POST {API_BASE}/tenant/roles/{role_id}/permissions" in text
    assert "DELETE {API_BASE}/tenant/roles/{role_id}/permissions/{permission_id}" in text
    assert "POST {API_BASE}/tenant/users/{user_id}/roles" in text
    assert "AUTH_ROLE_FORBIDDEN" in text
    assert "AUTH_ROLE_CONFLICT" in text
    assert "Do not invent a bulk save endpoint" in text


def test_membership_is_admin_or_member_only() -> None:
    text = _prompt()
    assert "admin" in text.lower()
    assert "member" in text.lower()



def test_grid_groups_by_module() -> None:
    text = _prompt()
    assert "module_code" in text
    assert "CRM" in text
    assert "WF" in text
    assert "GENERAL" in text
    assert "resource_name" in text
