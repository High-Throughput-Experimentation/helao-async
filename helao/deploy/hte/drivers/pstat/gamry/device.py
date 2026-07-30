"""Device-model descriptions for Gamry potentiostats.

Bundles the GamryCOM ProgID, supported current-range enum, and per-model
sense/range-mode flags into a ``GamryPstat`` dataclass, and defines
pre-configured instances for IFC1010, REF600/REF620, PCI4G300, PCI4G750,
REF30K, and a generic default. The ``GAMRY_DEVICES`` dict maps device name
prefixes to these instances, while ``TTL_OUTPUTS`` and ``TTL_OFF`` hold the
mask/value pairs passed to ``SetDigitalOut`` to assert or clear each TTL line.
"""

from dataclasses import dataclass
from enum import StrEnum

from .range import (
    Gamry_IErange_dflt,
    Gamry_IErange_IFC1010,
    Gamry_IErange_PCI4G300,
    Gamry_IErange_PCI4G750,
    Gamry_IErange_REF30K,
    Gamry_IErange_REF600,
)

TTL_OUTPUTS = {
    0: (1, 1),
    1: (2, 2),
    2: (4, 4),
    3: (8, 8),
}


TTL_OFF = {
    0: (0, 1),
    1: (0, 2),
    2: (0, 4),
    3: (0, 8),
}


@dataclass
class GamryPstat:
    """Describes a specific Gamry potentiostat model.

    Attributes:
        device: GamryCOM ProgID used to create the COM object (e.g.
            ``"GamryCOM.GamryPC6Pstat"``).
        ierange: Current-range ``StrEnum`` class appropriate for the model.
        set_sensemode: Value passed to ``SetSenseSpeedMode`` during setup.
        set_rangemode: Value passed to ``SetIERangeMode`` when auto-ranging.
    """

    device: str
    ierange: StrEnum
    set_sensemode: bool
    set_rangemode: bool


IFC1010 = GamryPstat(
    device="GamryCOM.GamryPC6Pstat",
    ierange=Gamry_IErange_IFC1010,
    set_sensemode=True,
    set_rangemode=False,
)

REF600 = GamryPstat(
    device="GamryCOM.GamryPC5Pstat",
    ierange=Gamry_IErange_REF600,
    set_sensemode=False,
    set_rangemode=True,
)

PCI4G300 = GamryPstat(
    device="GamryCOM.GamryPstat",
    ierange=Gamry_IErange_PCI4G300,
    set_sensemode=False,
    set_rangemode=True,
)

PCI4G750 = GamryPstat(
    device="GamryCOM.GamryPstat",
    ierange=Gamry_IErange_PCI4G750,
    set_sensemode=False,
    set_rangemode=True,
)

DEFAULT = GamryPstat(
    device="GamryCOM.GamryPC5Pstat",
    ierange=Gamry_IErange_dflt,
    set_sensemode=False,
    set_rangemode=True,
)

REF30K = GamryPstat(
    device="GamryCOM.GamryPstat",
    ierange=Gamry_IErange_REF30K,
    set_sensemode=False,
    set_rangemode=False,
)

GAMRY_DEVICES = {
    "IFC1010": IFC1010,
    "REF600": REF600,
    "REF620": REF600,
    "PCI4G300": PCI4G300,
    "PCI4G750": PCI4G750,
    "DEFAULT": DEFAULT,
    "REF30K": REF30K,
}
