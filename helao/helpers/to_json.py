"""Helpers for coercing Bokeh widget string inputs to native Python types."""

__all__ = ["parse_bokeh_input", "hlo_json_dumps"]

import json

import orjson


def _hlo_json_default(obj):
    """Coerce the one shape orjson refuses that stdlib :mod:`json` accepted.

    orjson serializes subclasses of ``str``, ``int``, ``dict`` and ``list``
    natively but **not** subclasses of ``float``. ``ruamel`` loads every YAML
    float as ``ScalarFloat``, so any value read out of a config and enqueued as
    data hit ``TypeError: Type is not JSON serializable: ScalarFloat`` — which
    the data logger catches and replaces with an error stub, writing
    ``{"error": "data was not serializable"}`` into the ``.hlo`` in place of the
    row. Silent, and only visible as one generic log line.

    Anything else is left to raise. A blanket ``str(obj)`` here would write a
    plausible-looking value for a genuinely wrong object, which is the failure
    this function exists to stop being silent.
    """
    if isinstance(obj, float):
        return float(obj)
    raise TypeError(f"Type is not JSON serializable: {type(obj).__name__}")


def hlo_json_dumps(obj) -> str:
    """Serialize ``obj`` to a strict-valid JSON string for a ``.hlo`` data line.

    Unlike stdlib :func:`json.dumps` (which emits bare ``NaN``/``Infinity``
    tokens that the orjson-based ``.hlo`` reader rejects), this maps non-finite
    floats to ``null`` so every data line is strict-valid JSON. Numpy scalars
    and arrays are serialized natively; non-string dict keys are stringified;
    ``float`` subclasses (``ruamel``'s ``ScalarFloat``, above all) are coerced.
    """
    return orjson.dumps(
        obj,
        default=_hlo_json_default,
        option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_NON_STR_KEYS,
    ).decode()


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
