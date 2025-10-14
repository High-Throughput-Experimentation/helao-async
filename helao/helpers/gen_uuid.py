__all__ = ["gen_uuid"]

import hashlib
import uuid
from datetime import datetime
from uuid_extensions import uuid7
from typing import Optional


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
