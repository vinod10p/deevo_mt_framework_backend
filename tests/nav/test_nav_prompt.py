"""prompts/nav/NAV_FRONTEND_PROMPT.md — the per-user menu contract (no database)."""

from __future__ import annotations

from pathlib import Path

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "nav" / "NAV_FRONTEND_PROMPT.md"


def _prompt() -> str:
    return " ".join(PROMPT_PATH.read_text(encoding="utf-8").split())


def test_menu_is_per_user_and_not_filtered_in_react() -> None:
    text = _prompt()
    assert "The menu is per user." in text
    assert "Do not filter the menu again in React" in text
    assert "the server already does" in text


def test_version_is_not_a_permission_cache_key() -> None:
    text = _prompt()
    assert "not** the user's permissions" in text
    assert "Do not skip a refetch because it matches" in text


def test_hidden_module_is_404_and_empty_list_is_valid() -> None:
    text = _prompt()
    assert "NAV_MODULE_NOT_FOUND" in text
    assert '"modules": []' in text
