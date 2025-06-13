__all__ = ["make_str_enum"]

from enum import StrEnum
from pydantic_core import CoreSchema

from pydantic import GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue


@classmethod
def __get_pydantic_json_schema__(
    cls, core_schema: CoreSchema, handler: GetJsonSchemaHandler
) -> JsonSchemaValue:
    json_schema = handler(core_schema)
    json_schema = handler.resolve_ref_schema(json_schema)
    json_schema.pop("const")
    json_schema["enum"] = [x.value for x in cls]

    return json_schema


def make_str_enum(enum_name, valdict):
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
    variants = [(k, v) for k, v in valdict.items()]
    enum_out = StrEnum(enum_name, variants)
    if len(enum_out) == 1:
        setattr(enum_out, "__get_pydantic_json_schema__", __get_pydantic_json_schema__)

    return enum_out
