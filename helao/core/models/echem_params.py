"""Shared StrEnums + coercion helpers for electrochem authoring params.

CARDS Domain-Integrity lever. Each enum's member values are the verbatim
string literals used today in hte experiment signatures and REF_TABLE keys,
so `.value` on the wire is byte-identical to the strings they replace. The
`resolve_*` helpers coerce a wire value to its enum and raise a clear,
catalogued ValueError on an unknown value (replacing silent fallthrough /
KeyError / UnboundLocalError at the dispatch sites).

Import cost: stdlib enum + helao.helpers.constants only. MUST NOT import any
driver module (this is imported by the pre-launch unit-test suite).
"""

__all__ = [
    "RefType",
    "PotentialVersus",
    "WEVersus",
    "BubbleGas",
    "resolve_ref_type",
    "resolve_potential_versus",
    "resolve_we_versus",
    "resolve_bubble_gas",
    "ref_offset",
]

from enum import Enum

from helao.helpers.constants import REF_TABLE


class RefType(str, Enum):
    """Reference-electrode key into REF_TABLE (potential offset in volts)."""

    leakless = "leakless"
    inhouse = "inhouse"
    rhe = "rhe"


class PotentialVersus(str, Enum):
    """Reference frame for an authored potential (ECHE/ADSS)."""

    rhe = "rhe"
    oer = "oer"


class WEVersus(str, Enum):
    """Working-electrode reference frame (ANEC/ECMS)."""

    ref = "ref"
    rhe = "rhe"


class BubbleGas(str, Enum):
    """Solution bubbling gas identity."""

    n2 = "N2"
    o2 = "O2"


def _resolve(enum_cls, value):
    try:
        return enum_cls(value)
    except ValueError:
        valid = ", ".join(m.value for m in enum_cls)
        raise ValueError(
            f"invalid {enum_cls.__name__} {value!r}; valid: {valid}"
        ) from None


def resolve_ref_type(value) -> RefType:
    return _resolve(RefType, value)


def resolve_potential_versus(value) -> PotentialVersus:
    return _resolve(PotentialVersus, value)


def resolve_we_versus(value) -> WEVersus:
    return _resolve(WEVersus, value)


def resolve_bubble_gas(value) -> BubbleGas:
    return _resolve(BubbleGas, value)


def ref_offset(value) -> float:
    """Validate a ref_type and return its REF_TABLE potential offset (volts)."""
    return REF_TABLE[resolve_ref_type(value)]
