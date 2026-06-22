"""Tests for :class:`helao.framework.adapters.ntp_clock.NtpClock`.

The clock realizes the :class:`helao.framework.ports.clock.Clock` port
(``now_ns() -> int``). It returns NTP-corrected nanoseconds when an offset is
configured, otherwise plain system time. No network is touched in these tests:
the offset is injected directly.
"""
import time

from helao.framework.ports.clock import Clock
from helao.framework.adapters.ntp_clock import NtpClock


def test_ntp_clock_realizes_clock_port():
    clock = NtpClock()
    assert isinstance(clock, Clock)


def test_now_ns_returns_int_near_system_time():
    clock = NtpClock()
    before = time.time_ns()
    value = clock.now_ns()
    after = time.time_ns()
    assert isinstance(value, int)
    # within a generous window of the surrounding system clock reads
    assert before - 1_000_000_000 <= value <= after + 1_000_000_000


def test_offset_is_applied_in_nanoseconds():
    # +5 seconds NTP offset must shift now_ns forward by ~5e9 ns.
    clock = NtpClock(offset_seconds=5.0)
    sys_ns = time.time_ns()
    value = clock.now_ns()
    delta = value - sys_ns
    assert 4_500_000_000 <= delta <= 5_500_000_000


def test_now_ns_is_monotonic_nondecreasing():
    clock = NtpClock()
    a = clock.now_ns()
    b = clock.now_ns()
    assert b >= a


def test_now_datetime_matches_now_ns():
    clock = NtpClock(offset_seconds=0.0)
    dt = clock.now_datetime()
    # the datetime helper should agree with now_ns to within a second
    assert abs(dt.timestamp() * 1e9 - clock.now_ns()) <= 2_000_000_000
