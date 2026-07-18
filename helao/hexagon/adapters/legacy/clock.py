"""ClockPort adapter (spec §9.3): NTP offset arithmetic over legacy helpers.

Offset source: <root>/LOGS/ntpLastSync.txt (written by launch's get_ntp_time,
read via time_utils.read_saved_offset). now() mints via set_time(offset) --
the exact call every legacy *_timestamp uses; now_ns() matches Base's
get_realtime_nowait arithmetic (epoch ns + offset seconds * 1e9).
"""

import os
import time
from datetime import datetime

from helao.helpers.time_utils import read_saved_offset, set_time

__all__ = ["LegacyClockAdapter"]


class LegacyClockAdapter:
    def __init__(self, offset_s: float = 0.0):
        self._offset = float(offset_s)

    @classmethod
    def from_offset_file(cls, log_root: str) -> "LegacyClockAdapter":
        path = os.path.join(log_root, "ntpLastSync.txt")
        if not os.path.exists(path):
            return cls(0.0)
        _last_sync, offset = read_saved_offset(path)
        return cls(float(offset or 0.0))

    def now(self) -> datetime:
        return set_time(offset=self._offset)

    def now_ns(self) -> int:
        return time.time_ns() + int(self._offset * 1e9)

    def offset(self) -> float:
        return self._offset
