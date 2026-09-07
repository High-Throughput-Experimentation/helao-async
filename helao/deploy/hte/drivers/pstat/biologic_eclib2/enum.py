"""Coerce HELAO range/bandwidth captions into EClib2 enum member names.

Actions send plain strings -- ``"m1"``, ``"AUTO"``, ``"BW5"`` -- matching the
``EC_IRange`` / ``EC_ERange`` / ``EC_Bandwidth`` aliases the EClib1 backend
already accepts. EClib2 wants members of ``IRangeValue``, ``IRangeMode``,
``ERangeValue`` and ``BandwidthValue``.

This module yields member *names* rather than members, so it imports and
answers with no SDK present; :mod:`vendor` turns a name into the real member.

The one shape change from EClib1: ``AUTO`` and ``KEEP`` were IRange *values*
there, but EClib2 splits them into a separate ``IRangeMode`` passed alongside a
value (``BL_SetIRange(handle, mode, value)``). So a current-range caption maps
to a ``(mode_name, value_name)`` pair, not a single name.
"""

# Fixed current ranges, plus BOOSTER -- which EClib1 grouped with AUTO/KEEP but
# EClib2 treats as an ordinary range value.
IRANGE_VALUE_NAMES: dict[str, str] = {
    "p100": "EC_SDK_IRANGE_100pA",
    "n1": "EC_SDK_IRANGE_1nA",
    "n10": "EC_SDK_IRANGE_10nA",
    "n100": "EC_SDK_IRANGE_100nA",
    "u1": "EC_SDK_IRANGE_1uA",
    "u10": "EC_SDK_IRANGE_10uA",
    "u100": "EC_SDK_IRANGE_100uA",
    "m1": "EC_SDK_IRANGE_1mA",
    "m10": "EC_SDK_IRANGE_10mA",
    "m100": "EC_SDK_IRANGE_100mA",
    "a1": "EC_SDK_IRANGE_1A",
    "BOOSTER": "EC_SDK_IRANGE_BOOSTER",
}

# Captions that select a *mode* instead of a range.
IRANGE_MODE_NAMES: dict[str, str] = {
    "AUTO": "I_RANGE_MODE_AUTO",
    "KEEP": "I_RANGE_MODE_KEEP",
}

IRANGE_FIXED_MODE_NAME = "I_RANGE_MODE_FIXED"

# ``BL_SetIRange`` takes a value even when the mode makes it irrelevant, so
# AUTO and KEEP still need one. The vendor's own PEIS example passes
# ``EC_SDK_IRANGE_1mA`` there; matching it keeps the seed a documented choice
# rather than an accident of whichever member happens to be first.
DEFAULT_AUTO_SEED = "m1"

IRANGE_CAPTIONS: tuple[str, ...] = tuple(IRANGE_VALUE_NAMES) + tuple(IRANGE_MODE_NAMES)

ERANGE_CAPTIONS: dict[str, str] = {
    "v2_5": "EC_SDK_ERANGE_2_5",
    "v5": "EC_SDK_ERANGE_5",
    "v10": "EC_SDK_ERANGE_10",
    # EClib2 has a real AUTO member here, unlike the .mps text path where the
    # field is a symmetric min/max voltage pair with no AUTO spelling.
    "AUTO": "EC_SDK_ERANGE_AUTO",
}

# BW1..BW9 and nothing else. The docs' constants table also lists
# EC_SDK_BANDWIDTH_KEEP, but the shipped BandwidthValue enum does not have it --
# and neither did EClib1's EC_Bandwidth, so there is no parity to keep.
BANDWIDTH_CAPTIONS: dict[str, str] = {
    f"BW{n}": f"EC_SDK_BANDWIDTH_{n}" for n in range(1, 10)
}


def irange_plan(caption: str, auto_seed: str = DEFAULT_AUTO_SEED) -> tuple[str, str]:
    """Map a current-range caption to an ``(IRangeMode, IRangeValue)`` name pair.

    Args:
        caption: One of :data:`IRANGE_CAPTIONS`.
        auto_seed: Range whose name accompanies a mode-only caption (``AUTO``
            or ``KEEP``), where the value is required by ``BL_SetIRange`` but
            not honoured. Must itself be a fixed range.

    Returns:
        ``(mode_name, value_name)``, both resolvable against the vendor
        ``IRangeMode`` / ``IRangeValue`` enums.

    Raises:
        ValueError: If ``caption`` is unknown, or ``auto_seed`` is not a fixed
            range.
    """
    if auto_seed not in IRANGE_VALUE_NAMES:
        raise ValueError(
            f"auto_seed must be a fixed current range, got {auto_seed!r}; "
            f"choose from {sorted(IRANGE_VALUE_NAMES)}"
        )
    if caption in IRANGE_MODE_NAMES:
        return IRANGE_MODE_NAMES[caption], IRANGE_VALUE_NAMES[auto_seed]
    if caption in IRANGE_VALUE_NAMES:
        return IRANGE_FIXED_MODE_NAME, IRANGE_VALUE_NAMES[caption]
    raise ValueError(
        f"unknown current range {caption!r}; choose from {sorted(IRANGE_CAPTIONS)}"
    )


def erange_name(caption: str) -> str:
    """Map a voltage-range caption to its ``ERangeValue`` member name.

    Raises:
        ValueError: If ``caption`` is unknown.
    """
    try:
        return ERANGE_CAPTIONS[caption]
    except KeyError:
        raise ValueError(
            f"unknown voltage range {caption!r}; choose from {sorted(ERANGE_CAPTIONS)}"
        ) from None


def bandwidth_name(caption: str) -> str:
    """Map a bandwidth caption to its ``BandwidthValue`` member name.

    Raises:
        ValueError: If ``caption`` is unknown. BW8 and BW9 exist in EClib2 but
            are SP-300-series only; the device rejects them elsewhere. There is
            no KEEP caption -- omit ``Bandwidth`` entirely to leave the channel
            as it is.
    """
    try:
        return BANDWIDTH_CAPTIONS[caption]
    except KeyError:
        raise ValueError(
            f"unknown bandwidth {caption!r}; choose from {sorted(BANDWIDTH_CAPTIONS)}"
        ) from None
