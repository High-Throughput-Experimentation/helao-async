__all__ = ["parse_bokeh_input"]

import json


def fix_numerics(val):
    if isinstance(val, str):
        stripped = val.lower().strip()
        if stripped in ('True', 'False'):
            return eval(stripped)
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


def parse_bokeh_input(v):
    try:
        val = json.loads(v.replace("'", '"'))
    except ValueError:
        val = v
    return fix_numerics(val)
