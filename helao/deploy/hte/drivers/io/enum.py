"""Enum types for the HTE IO drivers."""

from enum import IntEnum


class TriggerType(IntEnum):
    """Digital trigger edge type used by Galil IO cycling routines.

    Attributes:
        fallingedge: Trigger on a high-to-low transition.
        risingedge: Trigger on a low-to-high transition.
        blip: Trigger on a momentary pulse (rising followed by falling).
    """

    fallingedge = 0
    risingedge = 1
    blip = 2
