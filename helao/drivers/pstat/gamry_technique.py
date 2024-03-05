from dataclasses import dataclass
from typing import Optional, List
from enum import StrEnum


class ControlMode(StrEnum):
    PstatMode = "PstatMode"
    GstatMode = "GstatMode"


class DtaqType(StrEnum):
    ChronoPot = "ChronoPot"
    ChronoAmp = "ChronoAmp"


@dataclass
class GamryTechnique:
    control_mode: ControlMode
    dtaq_mode: str
    dtaq_type: Optional[DtaqType] = None
    dtaq_keys: List[str]
    set_vchrangemode: Optional[bool] = None
    set_ierangemode: Optional[bool] = None
    signal_function: str
    signal_params: List[str]


LSV = GamryTechnique(
    control_mode=ControlMode.PstatMode,
    dtaq_mode="GamryCOM.GamryDtaqCpiv",
    dtaq_keys=[
        "t_s",
        "Ewe_V",
        "Vu",
        "I_A",
        "Vsig",
        "Ach_V",
        "IERange",
        "Overload_HEX",
        "StopTest",
        "unknown1",
    ],
    signal_function="GamryCOM.GamrySignalRamp",
    signal_params=["Vinit__V", "Vfinal__V", "ScanRate__V_s", "AcqInterval__s"],
)
