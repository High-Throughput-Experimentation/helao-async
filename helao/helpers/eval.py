"""Best-effort coercion of string-encoded scalars to native Python types."""

__all__ = ["eval_array", "eval_val"]


def eval_array(x) -> list:
    """Apply :func:`eval_val` element-wise to a list.

    Args:
        x: Iterable of values to coerce.

    Returns:
        New list with each element passed through :func:`eval_val`.
    """
    ret = []
    for y in x:
        nv = eval_val(y)
        ret.append(nv)
    return ret


def eval_val(x):
    """Coerce a value to a native Python type, recursing into containers.

    Lists are processed via :func:`eval_array`. Dicts are walked
    recursively, coercing each value. Strings that look like signed
    integers or decimals become ``int`` or ``float``; ``"NaN"`` becomes a
    float NaN; ``"true"`` / ``"false"`` (any case) become ``bool``. All
    other inputs are returned unchanged.

    Args:
        x: Value to coerce.

    Returns:
        The coerced value, or ``x`` unchanged if no rule matched.
    """
    if isinstance(x, list):
        nv = eval_array(x)
    elif isinstance(x, dict):
        nv = {k: eval_val(dk) for k, dk in x.items()}
    elif isinstance(x, str):
        if x.replace(".", "", 1).lstrip("-").isdigit():
            if "." in x:
                nv = float(x)
            else:
                nv = int(x)
        elif x == "NaN":
            nv = float(x)
        elif x.lower() == "true":
            nv = True
        elif x.lower() == "false":
            nv = False
        else:
            nv = x
    else:
        nv = x
    return nv
