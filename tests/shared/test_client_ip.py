"""Client IP resolution — forwarded headers only from trusted proxies."""

from __future__ import annotations

import pytest

from mtf.shared.client_ip import parse_trusted_proxies, resolve_client_ip

PROXIES = parse_trusted_proxies(["10.0.0.0/8", "127.0.0.1", "fd00::/8"])


def test_no_trusted_proxies_ignores_forwarded_header() -> None:
    """Default: anyone can send X-Forwarded-For, so it is not believed."""
    assert resolve_client_ip("203.0.113.7", "1.2.3.4", ()) == "203.0.113.7"


def test_untrusted_peer_cannot_spoof() -> None:
    assert resolve_client_ip("203.0.113.7", "1.2.3.4", PROXIES) == "203.0.113.7"


def test_trusted_proxy_uses_forwarded_client() -> None:
    assert resolve_client_ip("10.1.2.3", "198.51.100.9", PROXIES) == "198.51.100.9"


def test_spoofed_left_entries_are_ignored() -> None:
    """Client sends a fake XFF; the proxy appends the real address on the right."""
    xff = "6.6.6.6, 198.51.100.9"
    assert resolve_client_ip("10.1.2.3", xff, PROXIES) == "198.51.100.9"


def test_skips_chained_trusted_proxies() -> None:
    xff = "198.51.100.9, 10.0.0.5, 127.0.0.1"
    assert resolve_client_ip("10.1.2.3", xff, PROXIES) == "198.51.100.9"


def test_all_hops_trusted_uses_left_most() -> None:
    assert resolve_client_ip("10.1.2.3", "10.0.0.9, 10.0.0.5", PROXIES) == "10.0.0.9"


@pytest.mark.parametrize("xff", ["not-an-ip", "198.51.100.9, garbage", "1.2.3.4:5678"])
def test_malformed_chain_falls_back_to_peer(xff: str) -> None:
    assert resolve_client_ip("10.1.2.3", xff, PROXIES) == "10.1.2.3"


@pytest.mark.parametrize("xff", [None, "", " , "])
def test_trusted_proxy_without_header_uses_peer(xff: str | None) -> None:
    assert resolve_client_ip("10.1.2.3", xff, PROXIES) == "10.1.2.3"


def test_ipv6() -> None:
    assert resolve_client_ip("fd00::1", "2001:db8::42", PROXIES) == "2001:db8::42"


def test_no_peer() -> None:
    assert resolve_client_ip(None, "1.2.3.4", PROXIES) is None


def test_non_ip_peer_is_not_trusted() -> None:
    """Starlette's TestClient reports ``testclient`` as the host."""
    assert resolve_client_ip("testclient", "1.2.3.4", PROXIES) == "testclient"


@pytest.mark.parametrize("bad", ["10.0.0.0/33", "proxy.internal", "300.1.1.1"])
def test_settings_reject_bad_proxy_entries(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    from mtf.shared.config import Settings

    monkeypatch.setenv("DEEVO_TRUSTED_PROXIES", f'["{bad}"]')
    with pytest.raises(ValueError, match="DEEVO_TRUSTED_PROXIES"):
        Settings()


def test_settings_accept_ips_and_cidrs(monkeypatch: pytest.MonkeyPatch) -> None:
    from mtf.shared.config import Settings

    monkeypatch.setenv("DEEVO_TRUSTED_PROXIES", '["10.0.0.0/8", "127.0.0.1", "fd00::/8"]')
    assert Settings().trusted_proxies == ["10.0.0.0/8", "127.0.0.1", "fd00::/8"]


def test_settings_default_trusts_nobody(monkeypatch: pytest.MonkeyPatch) -> None:
    from mtf.shared.config import Settings

    monkeypatch.delenv("DEEVO_TRUSTED_PROXIES", raising=False)
    assert Settings(_env_file=None).trusted_proxies == []
