from dataclasses import dataclass
from typing import Optional, List
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
    name: str
    on_method: OnMethod
    dtaq: GamryDtaq
    signal: GamrySignal
    set_decimation: Optional[bool] = None
    set_vchrangemode: Optional[bool] = None
    set_ierangemode: Optional[bool] = None
    vchrange_keys: Optional[List[str]] = None
    ierange_keys: Optional[List[str]] = None


TECH_LSV = GamryTechnique(
    name="LSV",
    on_method=OnMethod.CellOn,
    dtaq=DTAQ_CPIV,
    signal=VSIGNAL_RAMP,
    set_vchrangemode=False,
    vchrange_keys=["Vinit__V", "Vfinal__V"]
)

TECH_LSA = GamryTechnique(
    name="LSA",
    on_method=OnMethod.CellOn,
    dtaq=DTAQ_CPIV,
    signal=ISIGNAL_RAMP,
    set_ierangemode=False,
    ierange_keys=["Iinit__A", "Ifinal__A"]
)

TECH_CA = GamryTechnique(
    name="CA",
    on_method=OnMethod.CellOn,
    dtaq=DTAQ_CHRONOA,
    signal=VSIGNAL_CONST,
    set_vchrangemode=False,
    set_decimation=True,
    vchrange_keys=["Vval__V"],
)
TECH_CP = GamryTechnique(
    name="CP",
    on_method=OnMethod.CellOn,
    dtaq=DTAQ_CHRONOP,
    signal=ISIGNAL_CONST,
    set_ierangemode=False,
    set_decimation=True,
    ierange_keys=["Ival__A"]
)
TECH_CV = GamryTechnique(
    name="CV",
    on_method=OnMethod.CellOn,
    dtaq=DTAQ_RCV,
    signal=VSIGNAL_RUPDN,
    set_vchrangemode=False,
    vchrange_keys=["Vinit__V", "Vapex1__V", "Vapex2__V", "Vfinal__V"]
)
TECH_OCV = GamryTechnique(
    name="OCV",
    on_method=OnMethod.CellMon,
    dtaq=DTAQ_OCV,
    signal=OCVSIGNAL_CONST,
    set_vchrangemode=True,
)
TECH_RCA = GamryTechnique(
    name="RCA",
    on_method=OnMethod.CellOn,
    dtaq=DTAQ_UNIV,
    signal=VSIGNAL_ARRAY,
    set_vchrangemode=True,
)
