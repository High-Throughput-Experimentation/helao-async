from helao.framework.ports.clock import Clock
from helao.framework.adapters.fakes.clock import FakeClock


def test_fakeclock_satisfies_protocol():
    clock: Clock = FakeClock(start_ns=1000)
    assert isinstance(clock, Clock)


def test_fakeclock_reports_start_time():
    clock = FakeClock(start_ns=42)
    assert clock.now_ns() == 42


def test_fakeclock_advance_moves_time_forward():
    clock = FakeClock(start_ns=0)
    clock.advance(500)
    clock.advance(500)
    assert clock.now_ns() == 1000


def test_fakeclock_defaults_to_zero():
    assert FakeClock().now_ns() == 0
