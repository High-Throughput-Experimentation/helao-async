"""NTP-corrected system clock adapter realizing the :class:`Clock` port.

``NtpClock`` returns the current wall-clock time in integer nanoseconds, shifted
by an NTP offset (seconds) when one is configured. The offset is the same
``ntp_offset`` value the legacy ``Base`` maintained via
``helao.helpers.time_utils`` (``get_ntp_time`` / ``read_saved_offset``); here it
is injected so the clock has no hard network dependency and is fully testable.

Lives under ``adapters/`` (may perform I/O). The ``refresh`` classmethod is a
convenience that queries an NTP server through the ported ``time_utils`` helpers;
it is optional — production composition may supply the offset directly.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Optional

from helao.framework.ports.clock import Clock


class NtpClock(Clock):
    """System clock with an optional NTP offset, reported in nanoseconds.

    Attributes:
        offset_seconds: Signed seconds added to system time (the NTP offset).
    """

    def __init__(self, offset_seconds: float = 0.0) -> None:
        """Initialize the clock.

        Args:
            offset_seconds: Signed NTP offset in seconds (default ``0.0`` =
                uncorrected system time).
        """
        self.offset_seconds = float(offset_seconds)

    def now_ns(self) -> int:
        """Return NTP-corrected current time in integer nanoseconds."""
        return time.time_ns() + int(round(self.offset_seconds * 1e9))

    def now_datetime(self) -> datetime:
        """Return the NTP-corrected current time as a :class:`datetime`."""
        return datetime.fromtimestamp(self.now_ns() / 1e9)

    @classmethod
    def from_ntp(cls, ntp_server: str, offset_path: str) -> "NtpClock":
        """Build a clock by querying ``ntp_server`` and persisting the offset.

        Writes ``"{last_sync},{offset}"`` to ``offset_path`` and returns a clock
        carrying the resolved offset. Falls back to a zero offset if the read
        comes back empty. Performs network/file I/O (hence adapter-only).

        Args:
            ntp_server: NTP server hostname/address.
            offset_path: File the offset record is written to / read from.
        """
        from helao.framework.support.time_utils import get_ntp_time, read_saved_offset

        get_ntp_time(ntp_server, offset_path)
        record = read_saved_offset(offset_path)
        offset: Optional[float] = record[1] if record else 0.0
        return cls(offset_seconds=offset or 0.0)
