"""Dataclass and instances for Gamry potentiostat signals.

Parameter keys are ordered according to GamryCOM.GamrySignal* Init() args, and names are
modified as little as possible with the exception of ScanRate -> AcqInterval__s.

"""
from dataclasses import dataclass, field
from typing import List, Dict, Union
from enum import StrEnum


class ControlMode(StrEnum):
    PstatMode = "PstatMode"
    GstatMode = "GstatMode"


@dataclass
class GamrySignal:
    name: str
    mode: ControlMode
    param_keys: List[str] = field(default_factory=list)
    init_keys: List[str] = field(default_factory=list)
    map_keys: Dict[str, Union[int, float, str]] = field(default_factory=dict)


VSIGNAL_RAMP = GamrySignal(
    name="GamryCOM.GamrySignalRamp",
    param_keys=["Vinit__V", "Vfinal__V", "ScanRate__V_s", "AcqInterval__s"],
    mode=ControlMode.PstatMode,
)

ISIGNAL_RAMP = GamrySignal(
    name="GamryCOM.GamrySignalRamp",
    param_keys=["Iinit__A", "Ifinal__A", "ScanRate__A_s", "AcqInterval__s"],
    mode=ControlMode.GstatMode,
)

VSIGNAL_CONST = GamrySignal(
    name="GamryCOM.GamrySignalConst",
    param_keys=["Vval__V", "Tval__s", "AcqInterval__s"],
    mode=ControlMode.PstatMode,
)

EISSIGNAL_CONST = GamrySignal(
    name="GamryCOM.GamrySignalConst",
    param_keys=["Vval__V", "Tval__s", "AcqInterval__s"],
    mode=ControlMode.PstatMode,
    init_keys=["Freq", "RMS", "Precision"],
)

OCVSIGNAL_CONST = GamrySignal(
    name="GamryCOM.GamrySignalConst",
    param_keys=["Vval__V", "Tval__s", "AcqInterval__s"],
    mode=ControlMode.PstatMode,
    map_keys={"Vval__V": 0.0},
)

ISIGNAL_CONST = GamrySignal(
    name="GamryCOM.GamrySignalConst",
    param_keys=["Ival__A", "Tval__s", "AcqInterval__s"],
    mode=ControlMode.GstatMode,
)

VSIGNAL_RUPDN = GamrySignal(
    name="GamryCOM.GamrySignalRupdn",
    param_keys=[
        "Vinit__V",
        "Vapex1__V",
        "Vapex2__V",
        "Vfinal__V",
        "ScanInit__V_s",
        "ScanApex__V_s",
        "ScanFinal__V_s",
        "HoldTime0__s",  # hold at Apex 1 in seconds
        "HoldTime1__s",  # hold at Apex 2 in seconds
        "HoldTime2__s",  # Time to hold at Vfinal in seconds
        "AcqInterval__s",
        "Cycles",
    ],
    mode=ControlMode.PstatMode,
    map_keys={
        "ScanInit__V_s": "ScanRate__V_s",
        "ScanApex__V_s": "ScanRate__V_s",
        "ScanFinal__V_s": "ScanRate__V_s",
        "HoldTime0__s": 0.0,
        "HoldTime1__s": 0.0,
        "HoldTime2__s": 0.0,
    },
)

ISIGNAL_RUPDN = GamrySignal(
    name="GamryCOM.GamrySignalRupdn",
    param_keys=[
        "Iinit__A",
        "Iapex1__A",
        "Iapex2__A",
        "Ifinal__A",
        "ScanInit__A_s",
        "ScanApex__A_s",
        "ScanFinal__A_s",
        "holdtime0__s",
        "holdtime1__s",
        "holdtime2__s",
        "AcqInterval__s",
        "cycles",
    ],
    mode=ControlMode.GstatMode,
)


VSIGNAL_ARRAY = GamrySignal(
    name="GamryCOM.GamrySignalArray",
    param_keys=[
        "Cycles",
        "AcqInterval__s",
        "AcqPointsPerCycle",
        "SignalArray__V"
    ],
    mode=ControlMode.PstatMode,
)

ISIGNAL_ARRAY = GamrySignal(
    name="GamryCOM.GamrySignalArray",
    param_keys=[
        "Cycles",
        "AcqInterval__s",
        "AcqPointsPerCycle",
        "SignalArray__V"
    ],
    mode=ControlMode.GstatMode,
)
