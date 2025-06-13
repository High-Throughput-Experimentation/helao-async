__all__ = ["make_str_enum"]

from enum import Enum


def make_str_enum(name, valdict):
    """
    Dynamically creates a string-based enumeration.

    Args:
        name (str): The name of the enumeration.
        valdict (dict): A dictionary where keys are the enumeration names and values are the corresponding string values.

    Returns:
        Enum: A new enumeration class with string values.

    Example:
        >>> Colors = make_str_enum('Colors', {'RED': 'red', 'GREEN': 'green', 'BLUE': 'blue'})
        >>> Colors.RED
        <Colors.RED: 'red'>
        >>> Colors.RED.value
        'red'
    """
    meta = type(Enum)
    bases = (
        str,
        Enum,
    )


    dummy_counter = 0
    while len(valdict) < 2:
        val = f"__NOVALUE{dummy_counter}__"
        valdict[val] = val
        dummy_counter += 1

    edict = meta.__prepare__(name, bases)
    for k, v in valdict.items():
        edict[k] = v

    return meta(name, bases, edict)
