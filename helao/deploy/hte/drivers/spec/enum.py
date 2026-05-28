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


class ReferenceMode(str, Enum):
    """How reference spectra are collected during a plate sweep.

    Attributes:
        internal: Measure the nearest references to the starting and ending
            samples on the plate.
        builtin: Measure a reference position defined in the server config.
        blank: Measure starting and ending samples with auto-stop for a
            manual plate swap.
    """

    internal = "internal"  # measure nearest references to starting and ending samples
    builtin = "builtin"  # measure reference position defined in config
    blank = "blank"  # measure starting and ending samples w/auto-stop for plate swap
