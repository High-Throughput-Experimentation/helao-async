"""Time, NTP synchronization, and UUID utilities for HELAO servers.

Pure stdlib plus ``ntplib`` and ``uuid_extensions``. Importing this module has
no side effects: the NTP offset is read lazily from a file (never via a socket
at import time), and the only socket activity is an explicit
:func:`get_ntp_time` call.
"""

__all__ = [
    "gen_uuid",
    "md5_string",
    "uuid7_from_datetime",
    "set_time",
    "get_ntp_time",
    "read_saved_offset",
]

import hashlib
import uuid
from datetime import datetime
from time import time, ctime
from typing import Optional

import ntplib
from uuid_extensions import uuid7


def uuid7_from_datetime(dt) -> uuid.UUID:
    """Generate a uuid7 seeded from a ``datetime`` instance.

    Args:
        dt: Datetime supplying the seed timestamp (nanosecond precision).

    Returns:
        Time-ordered uuid7.
    """
    return uuid7(int(dt.timestamp() * 1e9))


def gen_uuid(input: Optional[str | int | datetime] = None) -> uuid.UUID:
    """Generate a uuid7, dispatching on the input type.

    With no input a fresh uuid7 is generated. Datetime or int inputs seed the
    uuid7 timestamp; string inputs produce a deterministic uuid5 in the URL
    namespace.

    Args:
        input: Optional seed (``str``, ``int``, or ``datetime``).

    Returns:
        Newly generated UUID.
    """
    if input is None:
        return uuid7()
    elif isinstance(input, datetime):
        return uuid7_from_datetime(input)
    elif isinstance(input, int):
        return uuid7(input)
    else:
        return uuid.uuid5(uuid.NAMESPACE_URL, input)


def md5_string(input: str) -> uuid.UUID:
    """Return the MD5 hash of ``input`` reinterpreted as a :class:`uuid.UUID`."""
    return uuid.UUID(hashlib.md5(input.encode("utf-8")).hexdigest())


def set_time(offset: float = 0) -> datetime:
    """Return ``datetime.now()`` shifted by ``offset`` seconds.

    Args:
        offset: Signed seconds to add to the current time.

    Returns:
        Offset-adjusted datetime.
    """
    dtime = datetime.now()
    if offset is not None:
        dtime = datetime.fromtimestamp(dtime.timestamp() + offset)
    return dtime


def get_ntp_time(ntp_server, output_path):
    """Query an NTP server and write ``"{last_sync},{offset}"`` to ``output_path``.

    On NTP timeout, falls back to the local time and a zero offset.

    Args:
        ntp_server: Hostname or address of the NTP server.
        output_path: Destination file path for the comma-separated record.
    """
    c = ntplib.NTPClient()
    try:
        response = c.request(ntp_server, version=3)
        ntp_response = response
        ntp_last_sync = response.orig_time
        ntp_offset = response.offset
        print(f"retrieved time at {ctime(ntp_response.tx_timestamp)} from {ntp_server}")
    except ntplib.NTPException:
        print(f"{ntp_server} ntp timeout")
        ntp_last_sync = time()
        ntp_offset = 0.0

    print(f"ntp_offset: {ntp_offset}")
    print(f"ntp_last_sync: {ntp_last_sync}")

    with open(output_path, "w") as f:
        f.write(f"{ntp_last_sync},{ntp_offset}")


def read_saved_offset(file_path):
    """Read a saved ``"{last_sync},{offset}"`` record from ``file_path``.

    Args:
        file_path: Path written by :func:`get_ntp_time`.

    Returns:
        ``(last_sync_str, offset_float)`` if the file has two comma-separated
        fields, otherwise ``None`` (implicit).
    """
    with open(file_path, "r") as f:
        tmps = f.readline().strip().split(",")
        if len(tmps) == 2:
            ntp_last_sync, ntp_offset = tmps
            ntp_offset = float(ntp_offset)
            return ntp_last_sync, ntp_offset
