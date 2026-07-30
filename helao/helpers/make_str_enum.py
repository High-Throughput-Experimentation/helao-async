"""Helper for dynamically constructing string-valued enumerations.

``make_str_enum`` builds a ``StrEnum`` from a name/value mapping. When the
resulting enum has a single member it is patched with a custom
``__get_pydantic_json_schema__`` so the value is emitted as an ``enum``
list rather than a ``const`` literal.
"""

__all__ = ["make_str_enum"]

from enum import StrEnum

from pydantic import GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import CoreSchema


@classmethod
def __get_pydantic_json_schema__(
    cls, core_schema: CoreSchema, handler: GetJsonSchemaHandler
) -> JsonSchemaValue:
    """Emit the enum value as an ``enum`` array instead of a ``const`` literal."""
    json_schema = handler(core_schema)
    json_schema = handler.resolve_ref_schema(json_schema)
    if "const" in json_schema:
        json_schema.pop("const")
    json_schema["enum"] = [x.value for x in cls]

    return json_schema


def make_str_enum(enum_name, valdict) -> StrEnum:
    """Build a ``StrEnum`` from a name/value mapping.

    For single-member enums, attaches a custom Pydantic JSON-schema hook so
    the value is serialised as an ``enum`` list rather than a ``const``.

    Args:
        enum_name: Name of the generated enumeration class.
        valdict: Mapping of member name to string value.

    Returns:
        The newly created ``StrEnum`` subclass.

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
