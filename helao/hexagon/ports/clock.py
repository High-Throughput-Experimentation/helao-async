"""Clock port (spec §4.3.7): NTP offset arithmetic.

Offset file <root>/LOGS/ntpLastSync.txt is written by launch and read at Base
init; set_time(offset) mints every *_timestamp; epoch_ns is stamped at lazy
file open OR header finish (two legal paths — goldens must not diff header
epoch). A deterministic clock may be injected ONLY in unit fixtures, never in
capture runs.
"""

from datetime import datetime
from typing import Protocol, runtime_checkable

__all__ = ["ClockPort"]


@runtime_checkable
class ClockPort(Protocol):
    def now(self) -> datetime:
        """NTP-corrected wall time (legacy set_time(offset=ntp_offset))."""
        ...

    def now_ns(self) -> int:
        """NTP-corrected epoch nanoseconds (legacy get_realtime_nowait)."""
        ...

    def offset(self) -> float:
        """The NTP offset in seconds (legacy ntp_offset)."""
        ...
