__all__ = ["gen_uuid"]

import uuid


def gen_uuid():
    "Generate a uuid, encode with larger character set, and trucate."
    return uuid.uuid4()
