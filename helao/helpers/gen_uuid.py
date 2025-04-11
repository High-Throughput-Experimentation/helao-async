__all__ = ["gen_uuid"]

import uuid
from uuid_extensions import uuid7
from typing import Optional


def gen_uuid(input: Optional[str] = None) -> uuid.UUID:
    "Generate a uuid, encode with larger character set, and trucate."
    if input is None:
        return uuid7()
    else:
        return uuid.uuid5(uuid.NAMESPACE_URL, input)
