"""Enumerations used by spectrometer drivers and action servers."""

from enum import Enum, IntEnum


class SpecTrigType(IntEnum):
    """Trigger source codes accepted by spectrometer SDKs.

    Attributes:
        off: Trigger disabled.
        internal: Use the spectrometer's own internal trigger.
        external: Wait for an external hardware trigger.
    """

    off = 10
    internal = 11
    external = 12


class SpecType(str, Enum):
    """Spectrum acquisition modes.

    Attributes:
        T: Transmission spectrum.
        R: Reflection spectrum.
    """

    T = "T"
    R = "R"
