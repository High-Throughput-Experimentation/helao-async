"""Current-range enums and lookup helpers for Gamry potentiostat models.

Defines a ``StrEnum`` per supported model (IFC1010, REF600/REF620,
PCI4G300, PCI4G750, REF30K, plus a generic default) whose members carry the
human-readable current label (e.g. ``"30nA"``). The ``get_range`` helper
resolves a user-supplied range specifier (by enum name, label, raw float in
amps, or value+unit string) to a member of the appropriate enum, falling back
to ``auto``. The ``RANGES`` dict maps mode names to the integer indices
passed to ``SetIERange``.
"""

from typing import Union
from enum import StrEnum

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

RANGES = {
    "mode0": 0,
    "mode1": 1,
    "mode2": 2,
    "mode3": 3,
    "mode4": 4,
    "mode5": 5,
    "mode6": 6,
    "mode7": 7,
    "mode8": 8,
    "mode9": 9,
    "mode10": 10,
    "mode11": 11,
    "mode12": 12,
    "mode13": 13,
    "mode14": 14,
    "mode15": 15,
}


# for IFC1010
class Gamry_IErange_IFC1010(StrEnum):
    """Current ranges for IFC1010 interface potentiostats.

    The labels below correspond to 300 mA / 30 mA variants; multiply by 2.5
    for 750 mA models and by 2.0 for 600 mA models.
    """

    # NOTE: The ranges listed below are for 300 mA or 30 mA models. For 750 mA models, multiply the ranges by 2.5. For 600 mA models, multiply the ranges by 2.0.
    auto = "auto"
    # mode0 = "N/A"
    # mode1 = "N/A"
    # mode2 = "N/A"
    # mode3 = "N/A"
    mode4 = "10nA"
    mode5 = "100nA"
    mode6 = "1uA"
    mode7 = "10uA"
    mode8 = "100uA"
    mode9 = "1mA"
    mode10 = "10mA"
    mode11 = "100mA"
    mode12 = "1A"
    # mode13 = "N/A"
    # mode14 = "N/A"
    # mode15 = "N/A"


class Gamry_IErange_REF600(StrEnum):
    """Current ranges for Reference 600 / 620 potentiostats."""

    auto = "auto"
    # mode0 = "N/A"
    mode1 = "60pA"
    mode2 = "600pA"
    mode3 = "6nA"
    mode4 = "60nA"
    mode5 = "600nA"
    mode6 = "6uA"
    mode7 = "60uA"
    mode8 = "600uA"
    mode9 = "6mA"
    mode10 = "60mA"
    mode11 = "600mA"
    # mode12 = "N/A"
    # mode13 = "N/A"
    # mode14 = "N/A"
    # mode15 = "N/A"


# G750 is 7.5nA to 750mA
class Gamry_IErange_PCI4G300(StrEnum):
    """Current ranges for PCI4/G300 potentiostats (3 nA to 300 mA)."""

    auto = "auto"
    # mode0 = "N/A"
    # mode1 = "N/A"
    # mode2 = "N/A"
    mode3 = "3nA"
    mode4 = "30nA"
    mode5 = "300nA"
    mode6 = "3uA"
    mode7 = "30uA"
    mode8 = "300uA"
    mode9 = "3mA"
    mode10 = "30mA"
    mode11 = "300mA"
    # mode12 = "N/A"
    # mode13 = "N/A"
    # mode14 = "N/A"
    # mode15 = "N/A"


class Gamry_IErange_PCI4G750(StrEnum):
    """Current ranges for PCI4/G750 potentiostats (7.5 nA to 750 mA)."""

    auto = "auto"
    # mode0 = "N/A"
    # mode1 = "N/A"
    # mode2 = "N/A"
    mode3 = "7.5nA"
    mode4 = "75nA"
    mode5 = "750nA"
    mode6 = "7.5uA"
    mode7 = "75uA"
    mode8 = "750uA"
    mode9 = "7.5mA"
    mode10 = "75mA"
    mode11 = "750mA"
    # mode12 = "N/A"
    # mode13 = "N/A"
    # mode14 = "N/A"
    # mode15 = "N/A"


class Gamry_IErange_dflt(StrEnum):
    """Generic placeholder current ranges (mode0..mode15) for unknown models."""

    auto = "auto"
    mode0 = "mode0"
    mode1 = "mode1"
    mode2 = "mode2"
    mode3 = "mode3"
    mode4 = "mode4"
    mode5 = "mode5"
    mode6 = "mode6"
    mode7 = "mode7"
    mode8 = "mode8"
    mode9 = "mode9"
    mode10 = "mode10"
    mode11 = "mode11"
    mode12 = "mode12"
    mode13 = "mode13"
    mode14 = "mode14"
    mode15 = "mode15"


class Gamry_IErange_REF30K(StrEnum):
    """Current ranges for Reference 30K booster potentiostats (300 pA to 30 A)."""

    auto = "auto"
    # mode0 = "mode0"
    # mode1 = "mode1"
    mode2 = "300pA"
    mode3 = "3nA"
    mode4 = "30nA"
    mode5 = "300nA"
    mode6 = "3uA"
    mode7 = "30uA"
    mode8 = "300uA"
    mode9 = "3mA"
    mode10 = "30mA"
    mode11 = "300mA"
    mode12 = "3A"
    mode13 = "30A"
    # mode14 = "mode14"
    # mode15 = "mode15"


def split_val_unit(val_string: str) -> tuple[float, str]:
    """Split a value+unit string into a numeric magnitude and unit suffix.

    Args:
        val_string: String such as ``"30nA"`` or ``"7.5 mA"``.

    Returns:
        ``(number, unit)`` tuple where ``number`` is the parsed float (or
        ``None`` on parse failure) and ``unit`` is the trailing alphabetic
        suffix.
    """

    def to_float(val):
        try:
            return float(val)
        except ValueError:
            return None

    unit = val_string.lstrip("0123456789. ")
    number = val_string[: -len(unit)]
    return to_float(number), unit


def to_amps(number: float, unit: str) -> Union[float, None]:
    """Convert a numeric value plus current unit suffix to amperes.

    Args:
        number: Numeric magnitude.
        unit: Unit suffix; recognized values are ``aA``, ``fA``, ``pA``,
            ``nA``, ``uA``, ``mA``, ``A``, ``kA`` (case-insensitive).

    Returns:
        The value expressed in amperes, or ``None`` if ``unit`` is not
        recognized.
    """
    unit = unit.lower()
    unit_map = {
        "aa": 1e-18,
        "fa": 1e-15,
        "pa": 1e-12,
        "na": 1e-9,
        "ua": 1e-6,
        "ma": 1e-3,
        "a": 1,
        "ka": 1e3,
    }
    exp = unit_map.get(unit, None)
    if exp is None:
        return None
    return number * exp


def get_range(requested_range: Union[str, None], range_enum: StrEnum) -> StrEnum:
    """Resolve a requested current range to a member of ``range_enum``.

    Accepts the enum member name, the enum value (current label),
    a numeric value in amperes, or a value+unit string. Falls back to
    ``range_enum.auto`` when the request is ``None`` or cannot be parsed.

    Args:
        requested_range: User-supplied range specifier.
        range_enum: Model-specific current-range ``StrEnum`` class.

    Returns:
        The selected ``range_enum`` member. When matched by amperage, returns
        the smallest range whose magnitude is >= the request.
    """
    if requested_range is None:
        LOGGER.warn("could not detect IErange, using 'auto'")
        return range_enum.auto

    LOGGER.info(f"got IErange request for {requested_range}")
    names = [e.name.lower() for e in range_enum]
    vals = [e.value.lower() for e in range_enum]
    lookupvals = [e.value for e in range_enum]

    idx = None
    if isinstance(requested_range, str):
        requested_range = requested_range.lower()

    if requested_range in vals:
        idx = vals.index(requested_range)

    elif requested_range in names:
        idx = names.index(requested_range)

    else:
        # auto should have been detected already above
        # try auto detect range based on value and unit pair

        if isinstance(requested_range, float):
            req_num = requested_range
        else:
            req_num, req_unit = split_val_unit(
                requested_range.replace(" ", "").replace("_", "")
            )
            req_num = to_amps(number=req_num, unit=req_unit)
        if req_num is None:
            return range_enum.auto
        for ret_idx, val in enumerate(vals):
            val_num, val_unit = split_val_unit(val)
            val_num = to_amps(number=val_num, unit=val_unit)
            if val_num is None:
                # skip auto
                continue
            if req_num <= val_num:
                # gamry_range_enum is already sort min to max
                idx = ret_idx
                break

        if idx is None:
            LOGGER.error("could not detect IErange, using 'auto'")
            return range_enum.auto

    ret_range = range_enum(lookupvals[idx])
    LOGGER.info(f"detected IErange: {ret_range}")
    return ret_range
