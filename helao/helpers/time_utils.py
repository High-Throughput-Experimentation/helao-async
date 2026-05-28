"""Time, NTP-sync, and UUID utilities.

Consolidates the former gen_uuid, set_time, and get_ntp_time modules.
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
    "Generate a uuid7 from a datetime object."
    return uuid7(int(dt.timestamp() * 1e9))


def gen_uuid(input: Optional[str | int | datetime] = None) -> uuid.UUID:
    "Generate a uuid, encode with larger character set, and trucate."
    if input is None:
        return uuid7()
    elif isinstance(input, datetime):
        return uuid7_from_datetime(input)
    elif isinstance(input, int):
        return uuid7(input)
    else:
        return uuid.uuid5(uuid.NAMESPACE_URL, input)


def md5_string(input: str) -> uuid.UUID:
    "Generate a hash string from input string."
    return uuid.UUID(hashlib.md5(input.encode("utf-8")).hexdigest())


def set_time(offset: float = 0):
    dtime = datetime.now()
    if offset is not None:
        dtime = datetime.fromtimestamp(dtime.timestamp() + offset)
    return dtime


def get_ntp_time(ntp_server, output_path):
    """
    Retrieves the current time from an NTP server and writes the offset
    and last-sync values to ``output_path`` as ``"{last_sync},{offset}"``.
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
    with open(file_path, "r") as f:
        tmps = f.readline().strip().split(",")
        if len(tmps) == 2:
            ntp_last_sync, ntp_offset = tmps
            ntp_offset = float(ntp_offset)
            return ntp_last_sync, ntp_offset
