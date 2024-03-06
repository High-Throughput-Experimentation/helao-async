from dataclasses import dataclass
from typing import Optional
from enum import StrEnum

from .gamry_dtaq import GamryDtaq, DTAQ_CPIV
from .gamry_signal import GamrySignal, SIGNAL_VRAMP

# define enums to match GamryCOM


class OnMethod(StrEnum):
    CellMon = "CellMon"
    CellOn = "CellOn"


@dataclass
class GamryTechnique:
    on_method: OnMethod
    dtaq: GamryDtaq
    signal: GamrySignal
    set_vchrangemode: Optional[bool] = None
    set_ierangemode: Optional[bool] = None


LSV = GamryTechnique(
    on_method=OnMethod.CellOn,
    dtaq=DTAQ_CPIV,
    signal=SIGNAL_VRAMP,
    set_vchrangemode=False,
)
