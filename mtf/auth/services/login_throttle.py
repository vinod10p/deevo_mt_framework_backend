"""In-memory throttle for failed logins — per client IP and per (account, IP).

Why both:

* **per (account, IP)** — a handful of wrong passwords blocks *that source* for *that
  account*, so an attacker who knows an email cannot lock the real user out (the old
  behaviour); the user keeps logging in from their own IP.
* **per IP** — caps password spraying (one IP trying many accounts).

A much higher account-wide lockout (``auth.app_user.locked_until``, see
``SessionService``) still stops distributed guessing from many IPs.

State lives in this process only: with N workers / instances an attacker gets up to N×
the limits, and counters reset on restart. Memory is bounded by ``max_keys``.
"""

from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class ThrottleLimits:
    max_failures_per_ip: int
    max_failures_per_account_ip: int
    window_seconds: int


class LoginThrottle:
    """Sliding-window failure counters keyed by IP and by (email, IP)."""

    def __init__(
        self,
        *,
        max_keys: int = 50_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_keys = max_keys
        self._clock = clock
        self._lock = threading.Lock()
        # key -> timestamps of recent failures (oldest first); OrderedDict for LRU eviction.
        self._failures: OrderedDict[tuple[str, ...], deque[float]] = OrderedDict()

    # -- public API ---------------------------------------------------------------

    def retry_after(self, ip: str | None, email: str, limits: ThrottleLimits) -> int | None:
        """Seconds until this source may try again, or ``None`` if not throttled."""
        if not ip:
            return None  # no client address (e.g. unit tests) — nothing to key on
        now = self._clock()
        with self._lock:
            waits = [
                self._wait(("ip", ip), limits.max_failures_per_ip, limits.window_seconds, now),
                self._wait(
                    ("acct", email, ip),
                    limits.max_failures_per_account_ip,
                    limits.window_seconds,
                    now,
                ),
            ]
        blocked = [w for w in waits if w is not None]
        return max(blocked) if blocked else None

    def record_failure(self, ip: str | None, email: str) -> None:
        if not ip:
            return
        now = self._clock()
        with self._lock:
            for key in (("ip", ip), ("acct", email, ip)):
                bucket = self._failures.get(key)
                if bucket is None:
                    bucket = self._failures[key] = deque()
                else:
                    self._failures.move_to_end(key)
                bucket.append(now)
            while len(self._failures) > self._max_keys:
                self._failures.popitem(last=False)

    def record_success(self, ip: str | None, email: str) -> None:
        """A correct password clears this account's counter for this IP (not the IP's)."""
        if not ip:
            return
        with self._lock:
            self._failures.pop(("acct", email, ip), None)

    def clear(self) -> None:
        with self._lock:
            self._failures.clear()

    # -- internals ----------------------------------------------------------------

    def _wait(
        self, key: tuple[str, ...], limit: int, window: int, now: float
    ) -> int | None:
        bucket = self._failures.get(key)
        if bucket is None:
            return None
        while bucket and bucket[0] <= now - window:
            bucket.popleft()
        if not bucket:
            del self._failures[key]
            return None
        if len(bucket) < limit:
            return None
        # Blocked until enough old failures age out to drop below the limit.
        release_at = bucket[len(bucket) - limit] + window
        return max(1, math.ceil(release_at - now))


#: Process-wide instance used by ``SessionService``.
login_throttle = LoginThrottle()
