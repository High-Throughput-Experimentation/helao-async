from dataclasses import dataclass
from typing import Optional
from enum import StrEnum

from .dtaq import (
    GamryDtaq,
    DTAQ_CPIV,
    DTAQ_CHRONOA,
    DTAQ_CHRONOP,
    DTAQ_RCV,
    DTAQ_OCV,
    DTAQ_UNIV,
)
from .signal import (
    GamrySignal,
    VSIGNAL_RAMP,
    ISIGNAL_RAMP,
    VSIGNAL_CONST,
    ISIGNAL_CONST,
    VSIGNAL_ARRAY,
    VSIGNAL_RUPDN,
    OCVSIGNAL_CONST,
)

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


TECH_LSV = GamryTechnique(
    on_method=OnMethod.CellOn,
    dtaq=DTAQ_CPIV,
    signal=VSIGNAL_RAMP,
    set_vchrangemode=False,
)

TECH_LSA = GamryTechnique(
    on_method=OnMethod.CellOn,
    dtaq=DTAQ_CPIV,
    signal=ISIGNAL_RAMP,
    set_vchrangemode=False,
)

TECH_CA = GamryTechnique(
    on_method=OnMethod.CellOn,
    dtaq=DTAQ_CHRONOA,
    signal=VSIGNAL_CONST,
    set_vchrangemode=False,
)
TECH_CP = GamryTechnique(
    on_method=OnMethod.CellOn,
    dtaq=DTAQ_CHRONOP,
    signal=ISIGNAL_CONST,
    set_vchrangemode=False,
)
TECH_CV = GamryTechnique(
    on_method=OnMethod.CellOn,
    dtaq=DTAQ_RCV,
    signal=VSIGNAL_RUPDN,
    set_vchrangemode=False,
)
TECH_OCV = GamryTechnique(
    on_method=OnMethod.CellMon,
    dtaq=DTAQ_OCV,
    signal=OCVSIGNAL_CONST,
    set_vchrangemode=True,
)
TECH_RCA = GamryTechnique(
    on_method=OnMethod.CellOn,
    dtaq=DTAQ_UNIV,
    signal=VSIGNAL_ARRAY,
    set_vchrangemode=True,
)
