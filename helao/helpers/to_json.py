"""Helpers for coercing Bokeh widget string inputs to native Python types."""

__all__ = ["parse_bokeh_input"]

import json


def fix_numerics(val):
    """Recursively coerce numeric and boolean strings to their typed equivalents.

    Strings that read as ``"True"`` or ``"False"`` become booleans; strings
    that read as numerics (including scientific notation) become floats; lists
    and dicts are walked recursively via :func:`parse_bokeh_input`.

    Args:
        val: Value to coerce; typically a string, list, or dict.

    Returns:
        ``val`` with numeric/boolean strings rewritten, or unchanged on no match.
    """
    if isinstance(val, str):
        stripped = val.strip()
        if stripped in ["True", "False"]:
            return eval(stripped)
        stripped = stripped.lower()
        cleaned = (
            stripped.lstrip("-")
            .replace(".", "", 1)
            .replace("e-", "", 1)
            .replace("e", "", 1)
        )
        if cleaned.isdigit():
            retval = float(stripped)
            return retval
    elif isinstance(val, list):
        retval = [parse_bokeh_input(x) for x in val]
        return retval
    elif isinstance(val, dict):
        retval = {k: parse_bokeh_input(v) for k, v in val.items()}
        return retval
    return val


def parse_bokeh_input(v):
    """Parse a Bokeh widget value into native Python types.

    Single-quoted JSON-ish strings are rewritten to double quotes and decoded
    with :func:`json.loads`; failures fall back to the raw value. The result
    is then passed through :func:`fix_numerics`.

    Args:
        v: Raw Bokeh widget value, typically a string.

    Returns:
        Decoded and numerically-coerced value.
    """
    try:
        val = json.loads(v.replace("'", '"'))
    except Exception:
        val = v
    return fix_numerics(val)
