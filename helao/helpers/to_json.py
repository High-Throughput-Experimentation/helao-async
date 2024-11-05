__all__ = ["parse_bokeh_input"]

import json


def fix_numerics(val):
    """
    Recursively converts numeric strings in the input to their appropriate numeric types.
    
    Args:
        val (str, list, dict): The input value which can be a string, list, or dictionary.
        
    Returns:
        The input value with numeric strings converted to their respective numeric types.
        - If the input is a string that represents a boolean ('True' or 'False'), it is converted to a boolean.
        - If the input is a string that represents a number, it is converted to a float.
        - If the input is a list, the function is applied recursively to each element.
        - If the input is a dictionary, the function is applied recursively to each value.
        - If the input does not match any of the above conditions, it is returned unchanged.
    """
    if isinstance(val, str):
        stripped = val.strip()
        if stripped in ['True', 'False']:
            return eval(stripped)
        stripped = stripped.lower()
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
    """
    Parses a given input string, attempting to convert it from a JSON-like format
    with single quotes to a proper JSON format with double quotes. If the conversion
    fails, the original input is returned. The resulting value is then processed to
    fix any numeric types.

    Args:
        v (str): The input string to be parsed.

    Returns:
        Any: The parsed and processed value, which could be of any type depending on
        the input and the result of the numeric fixing process.
    """
    try:
        val = json.loads(v.replace("'", '"'))
    except ValueError:
        val = v
    return fix_numerics(val)
