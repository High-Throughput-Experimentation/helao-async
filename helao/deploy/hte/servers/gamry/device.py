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
from typing import Optional

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
        set_sensemode: Value passed to ``SetSenseSpeedMode`` during setup;
            ``None`` makes no call and leaves the instrument's own setting.
        set_rangemode: Value passed to ``SetIERangeMode`` for an ``auto``
            IErange; a fixed IErange passes ``False``. ``None`` makes no call
            for either.

    The IFC1010 makes no ``SetSenseSpeedMode`` call, as in the legacy driver
    (2022). Its range mode is set on every run: with ``None`` an ``auto`` run
    kept whatever mode the last CP/LSA/EIS run left (off), and the 2024
    refactor's ``False`` switched auto-ranging off on every ``auto`` run.
    REF30K postdates the legacy driver and keeps its own ``False``/``False``
    ("does not support range mode", 0930d78d).
    """

    device: str
    ierange: StrEnum
    set_sensemode: Optional[bool]
    set_rangemode: Optional[bool]


IFC1010 = GamryPstat(
    device="GamryCOM.GamryPC6Pstat",
    ierange=Gamry_IErange_IFC1010,
    set_sensemode=None,
    # accepts SetIERangeMode: CP/LSA and EIS already send it False on this model
    set_rangemode=True,
)

REF600 = GamryPstat(
    device="GamryCOM.GamryPC5Pstat",
    ierange=Gamry_IErange_REF600,
    set_sensemode=True,
    set_rangemode=True,
)

PCI4G300 = GamryPstat(
    device="GamryCOM.GamryPstat",
    ierange=Gamry_IErange_PCI4G300,
    set_sensemode=True,
    set_rangemode=True,
)

PCI4G750 = GamryPstat(
    device="GamryCOM.GamryPstat",
    ierange=Gamry_IErange_PCI4G750,
    set_sensemode=True,
    set_rangemode=True,
)

DEFAULT = GamryPstat(
    device="GamryCOM.GamryPC5Pstat",
    ierange=Gamry_IErange_dflt,
    set_sensemode=True,
    set_rangemode=True,
)

REF30K = GamryPstat(
    device="GamryCOM.GamryPstat",
    ierange=Gamry_IErange_REF30K,
    set_sensemode=False,  # never sent True by any setup(); unverified on station
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
