__all__ = ["gen_uuid"]

import uuid


def gen_uuid(input:str = None):
    "Generate a uuid, encode with larger character set, and trucate."
    if input is None:
        return uuid.uuid4()
    else:
        return uuid.uuid5(input)
