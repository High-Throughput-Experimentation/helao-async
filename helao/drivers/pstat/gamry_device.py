from dataclasses import dataclass
from enum import Enum
from helao.drivers.pstat.enum import (
    # Gamry_IErange_dflt,
    Gamry_IErange_IFC1010,
    Gamry_IErange_PCI4G300,
    Gamry_IErange_PCI4G750,
    Gamry_IErange_REF600,
)


@dataclass
class GamryPstat:
    device: str
    ierange: Enum
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


GAMRY_DEVICES = {
    "IFC1010": IFC1010,
    "REF600": REF600,
    "PCI4G300": PCI4G300,
    "PCI4G750": PCI4G750,
}