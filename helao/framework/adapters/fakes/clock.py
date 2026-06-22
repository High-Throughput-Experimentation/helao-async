"""Deterministic in-memory Clock for tests."""
from helao.framework.ports.clock import Clock


class FakeClock(Clock):
    """A clock whose time only changes when the test calls advance()."""

    def __init__(self, start_ns: int = 0) -> None:
        self._now_ns = start_ns

    def now_ns(self) -> int:
        return self._now_ns

    def advance(self, delta_ns: int) -> None:
        """Move time forward by delta_ns."""
        self._now_ns += delta_ns
