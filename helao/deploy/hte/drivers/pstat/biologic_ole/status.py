"""Decode the 32-real array returned by EC-Lab's ``MeasureStatus``.

Indices and value tables are from the EC-Lab OLE COM User Manual v11.72,
section 5.2.11. The array is positional and untyped on the wire, so this is
the only place in the package that knows what index means what.

Two decisions are deliberate:

* **Idle is exactly ``state_raw == 0``.** An unrecognized state -- a value a
  future EC-Lab introduces -- reads as busy and keeps its raw number. The
  alternative, raising or defaulting to idle, would either take a station down
  on a version bump or report a running channel as finished.
* **Fields the manual says are not reset stay as read.** Section 5.2.11 warns
  that ``Current point index`` and ``Total point index`` retain the previous
  technique's values until overwritten. Correcting for that is the caller's
  job, not the decoder's.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional

__all__ = ["ChannelState", "ChannelStatus", "SafetyLimit", "decode_status"]

#: Length of the status array. The manual specifies exactly 32 reals.
STATUS_LENGTH = 32


class ChannelState(IntEnum):
    """Value of status index 0 (manual section 5.2.11, table of statuses)."""

    STOP = 0
    RUN = 1
    PAUSE = 2
    SYNC = 3
    STOP_REC1 = 4
    STOP_REC2 = 5
    PAUSE_REC = 6


#: The two states that mean "running, and writing the technique's last
#: points". Treating either as finished truncates the tail of every record.
RECORDING_TAIL = frozenset({ChannelState.STOP_REC1, ChannelState.STOP_REC2})


class SafetyLimit(IntEnum):
    """Value of status index 30. Non-zero means a limit tripped."""

    OK = 0
    EMAX = 1
    EMIN = 2
    I = 3  # noqa: E741 - the manual's own name for this code
    Q_Q0 = 4
    EWE_MIN_STACK = 7
    ECE_MIN_STACK = 8
    EWE_MAX_STACK = 9
    ECE_MAX_STACK = 10


@dataclass(frozen=True)
class ChannelStatus:
    """One decoded ``MeasureStatus`` reading."""

    state_raw: int
    state: Optional[ChannelState]
    technique_index: int
    technique_code: int
    sequence_index: int
    cycle: float
    time_s: float
    ewe_v: float
    ece_v: float
    eoc_v: float
    i_a: float
    irange_a: float
    frequency_hz: float
    z_ohm: float
    point_index: int
    total_point_index: int
    safety_limit_raw: int
    safety_limit: Optional[SafetyLimit]
    connected: bool
    raw: tuple[float, ...]

    @property
    def is_busy(self) -> bool:
        """True unless the channel is exactly ``Stop``."""
        return self.state_raw != ChannelState.STOP

    @property
    def is_recording_tail(self) -> bool:
        """True in ``Stop_rec1`` / ``Stop_rec2`` -- running, finishing up."""
        return self.state in RECORDING_TAIL


def _enum_or_none(enum_cls, value: int):
    try:
        return enum_cls(value)
    except ValueError:
        return None


def decode_status(values: Sequence[float]) -> ChannelStatus:
    """Decode a raw ``MeasureStatus`` array.

    Args:
        values: The 32 reals EC-Lab returned, in order.

    Returns:
        The decoded reading, with the raw array preserved.

    Raises:
        ValueError: If ``values`` is not exactly 32 long. A short array means
            the call failed or the API changed, and guessing which indices
            survived would silently mis-read every field after the gap.
    """
    if len(values) != STATUS_LENGTH:
        raise ValueError(
            f"MeasureStatus returned {len(values)} values, expected {STATUS_LENGTH}"
        )
    raw = tuple(float(v) for v in values)
    state_raw = int(raw[0])
    safety_raw = int(raw[30])
    return ChannelStatus(
        state_raw=state_raw,
        state=_enum_or_none(ChannelState, state_raw),
        technique_index=int(raw[4]),
        technique_code=int(raw[5]),
        sequence_index=int(raw[6]),
        cycle=raw[10],
        time_s=raw[15],
        ewe_v=raw[16],
        ece_v=raw[17],
        eoc_v=raw[18],
        i_a=raw[19],
        irange_a=raw[23],
        frequency_hz=raw[25],
        z_ohm=raw[26],
        point_index=int(raw[27]),
        total_point_index=int(raw[28]),
        safety_limit_raw=safety_raw,
        safety_limit=_enum_or_none(SafetyLimit, safety_raw),
        connected=safety_raw is not None and int(raw[31]) == 0,
        raw=raw,
    )
