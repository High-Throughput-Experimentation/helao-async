__all__ = ["gen_uuid"]

import uuid
from uuid7 import uuid7


def gen_uuid(input:str = None):
    "Generate a uuid, encode with larger character set, and trucate."
    if input is None:
        return uuid7()
    else:
        return uuid.uuid5(input)
