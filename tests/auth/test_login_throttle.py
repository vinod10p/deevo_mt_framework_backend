"""``LoginThrottle`` — sliding windows, keys, eviction (no DB, fake clock)."""

from __future__ import annotations

import pytest

from mtf.auth.services.login_throttle import LoginThrottle, ThrottleLimits

LIMITS = ThrottleLimits(max_failures_per_ip=10, max_failures_per_account_ip=3, window_seconds=60)
IP = "203.0.113.7"
OTHER_IP = "198.51.100.9"
EMAIL = "victim@example.com"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def throttle(clock: FakeClock) -> LoginThrottle:
    return LoginThrottle(clock=clock)


def _fail(throttle: LoginThrottle, n: int, ip: str = IP, email: str = EMAIL) -> None:
    for _ in range(n):
        throttle.record_failure(ip, email)


def test_not_throttled_below_account_ip_limit(throttle: LoginThrottle) -> None:
    _fail(throttle, 2)
    assert throttle.retry_after(IP, EMAIL, LIMITS) is None


def test_throttled_at_account_ip_limit(throttle: LoginThrottle) -> None:
    _fail(throttle, 3)
    assert throttle.retry_after(IP, EMAIL, LIMITS) == 60


def test_other_ip_for_same_account_is_not_blocked(throttle: LoginThrottle) -> None:
    """The core of the fix: the attacker's IP is blocked, the real user's is not."""
    _fail(throttle, 3, ip=IP)
    assert throttle.retry_after(IP, EMAIL, LIMITS) is not None
    assert throttle.retry_after(OTHER_IP, EMAIL, LIMITS) is None


def test_other_account_from_same_ip_not_blocked_until_ip_limit(
    throttle: LoginThrottle,
) -> None:
    _fail(throttle, 3, email=EMAIL)
    assert throttle.retry_after(IP, "someone-else@example.com", LIMITS) is None


def test_ip_limit_stops_password_spraying(throttle: LoginThrottle) -> None:
    for i in range(10):  # one failure each on ten different accounts
        throttle.record_failure(IP, f"user{i}@example.com")
    assert throttle.retry_after(IP, "fresh@example.com", LIMITS) == 60
    assert throttle.retry_after(OTHER_IP, "fresh@example.com", LIMITS) is None


def test_window_slides(throttle: LoginThrottle, clock: FakeClock) -> None:
    throttle.record_failure(IP, EMAIL)  # t=1000
    clock.now += 30
    _fail(throttle, 2)  # t=1030
    assert throttle.retry_after(IP, EMAIL, LIMITS) == 30  # oldest ages out at t=1060
    clock.now += 30
    assert throttle.retry_after(IP, EMAIL, LIMITS) is None  # back to 2 in window
    clock.now += 31
    _fail(throttle, 2)
    assert throttle.retry_after(IP, EMAIL, LIMITS) is None  # old ones expired


def test_retry_after_is_at_least_one_second(throttle: LoginThrottle, clock: FakeClock) -> None:
    _fail(throttle, 3)
    clock.now += 59.9
    assert throttle.retry_after(IP, EMAIL, LIMITS) == 1


def test_success_clears_account_counter_but_not_ip_counter(throttle: LoginThrottle) -> None:
    _fail(throttle, 2)
    throttle.record_success(IP, EMAIL)
    _fail(throttle, 2)
    assert throttle.retry_after(IP, EMAIL, LIMITS) is None  # 2 < 3 after reset
    for i in range(6):
        throttle.record_failure(IP, f"x{i}@example.com")
    assert throttle.retry_after(IP, "y@example.com", LIMITS) == 60  # 2+2+6 = 10 on the IP


def test_no_ip_is_never_throttled_or_recorded(throttle: LoginThrottle) -> None:
    _fail(throttle, 50, ip="")
    for ip in (None, ""):
        throttle.record_failure(ip, EMAIL)
        assert throttle.retry_after(ip, EMAIL, LIMITS) is None
    assert throttle.retry_after(IP, EMAIL, LIMITS) is None


def test_memory_is_bounded(clock: FakeClock) -> None:
    throttle = LoginThrottle(max_keys=100, clock=clock)
    for i in range(1_000):
        throttle.record_failure(f"10.0.{i // 256}.{i % 256}", f"u{i}@example.com")
    assert len(throttle._failures) <= 100


def test_eviction_drops_least_recently_used(clock: FakeClock) -> None:
    throttle = LoginThrottle(max_keys=4, clock=clock)  # 2 keys per failure (ip + acct)
    _fail(throttle, 3, ip=IP)
    throttle.record_failure("10.0.0.1", "a@example.com")
    throttle.record_failure("10.0.0.2", "b@example.com")
    # The first IP's keys were evicted, so it is no longer remembered.
    assert throttle.retry_after(IP, EMAIL, LIMITS) is None


def test_clear(throttle: LoginThrottle) -> None:
    _fail(throttle, 3)
    throttle.clear()
    assert throttle.retry_after(IP, EMAIL, LIMITS) is None


def test_thread_safety_under_concurrent_failures(throttle: LoginThrottle) -> None:
    import threading

    def worker() -> None:
        for _ in range(200):
            throttle.record_failure(IP, EMAIL)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(throttle._failures[("ip", IP)]) == 1_600
