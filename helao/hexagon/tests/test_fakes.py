"""Fakes must satisfy their Protocols and record faithfully."""

from datetime import datetime

from helao.hexagon.adapters import fakes
from helao.hexagon.ports.clock import ClockPort


def test_fakes_satisfy_protocols():
    assert isinstance(fakes.FakeClock(), ClockPort)


def test_fake_clock_is_deterministic():
    clk = fakes.FakeClock(fixed=datetime(2026, 7, 17, 12, 0, 0), offset_s=1.5)
    assert clk.now() == datetime(2026, 7, 17, 12, 0, 0)
    assert clk.offset() == 1.5
    assert clk.now_ns() == int(datetime(2026, 7, 17, 12, 0, 0).timestamp() * 1e9)
