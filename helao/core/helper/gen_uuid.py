
__all__ = ["gen_uuid"]

import time
from typing import Optional

import shortuuid


def gen_uuid(label: str, timestamp: Optional[str] = None, trunc: int = 8):
    "Generate a uuid, encode with larger character set, and trucate."
    if timestamp is None:
        timestamp = time.monotonic_ns()
    short = shortuuid.uuid(name=f"{label}_{timestamp}")[:trunc]
    return short
