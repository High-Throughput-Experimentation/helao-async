__all__ = ["make_str_enum"]

from enum import Enum


def make_str_enum(name, valdict):
    meta = type(Enum)
    bases = (
        str,
        Enum,
    )
    dict = meta.__prepare__(name, bases)
    for k, v in valdict.items():
        dict[k] = v
    return meta(name, bases, dict)
