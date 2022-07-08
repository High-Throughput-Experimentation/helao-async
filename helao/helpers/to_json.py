__all__ = ["to_json"]

import json


def fix_numerics(val):
    if isinstance(val, str):
        stripped = val.lower().strip()
        cleaned = stripped.lstrip('-').replace('.', '', 1).replace('e-', '', 1).replace('e', '', 1)
        if cleaned.isdigit():
            retval = float(stripped)
            return retval
    elif isinstance(val, list):
        retval = [fix_numerics(x) for x in val]
        return retval
    elif isinstance(val, dict):
        retval = {k: fix_numerics(v) for k, v in val.items()}
        return retval
    return val


def to_json(v):
    try:
        val = json.loads(v.replace("'", '"'))
    except ValueError:
        val = v
    return fix_numerics(val)
