"""Client IP for audit rows and login throttling.

By default this is the TCP peer (``request.client.host``) and forwarded headers are
ignored — anyone can send ``X-Forwarded-For``. Only when the peer is one of
``DEEVO_TRUSTED_PROXIES`` (IPs or CIDRs) is the header used: it is read right-to-left,
skipping trusted proxies, and the first untrusted address is the client.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable

from starlette.requests import Request

from mtf.shared.config import get_settings

_Network = ipaddress.IPv4Network | ipaddress.IPv6Network


def parse_trusted_proxies(values: Iterable[str]) -> tuple[_Network, ...]:
    """``["10.0.0.0/8", "127.0.0.1"]`` → networks. Raises ``ValueError`` on bad input."""
    return tuple(ipaddress.ip_network(v.strip(), strict=False) for v in values if v.strip())


def _is_trusted(address: str, trusted: tuple[_Network, ...]) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(ip in net for net in trusted)


def resolve_client_ip(
    peer: str | None,
    forwarded_for: str | None,
    trusted: tuple[_Network, ...],
) -> str | None:
    if not peer or not trusted or not _is_trusted(peer, trusted) or not forwarded_for:
        return peer
    hops = [h.strip() for h in forwarded_for.split(",") if h.strip()]
    for hop in reversed(hops):
        try:
            ipaddress.ip_address(hop)
        except ValueError:
            return peer  # malformed chain — don't trust any of it
        if not _is_trusted(hop, trusted):
            return hop
    # Every hop is a trusted proxy: use the left-most (closest to the client).
    return hops[0] if hops else peer


def client_ip(request: Request) -> str | None:
    """Best-known client address for ``request`` (see module docstring)."""
    peer = request.client.host if request.client else None
    trusted = parse_trusted_proxies(get_settings().trusted_proxies)
    return resolve_client_ip(peer, request.headers.get("x-forwarded-for"), trusted)
