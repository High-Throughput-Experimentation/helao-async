"""Clock port: monotonic-ish wall time in nanoseconds."""
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """Source of the current time in integer nanoseconds."""

    def now_ns(self) -> int:
        """Return the current time in nanoseconds since an arbitrary epoch."""
        ...
