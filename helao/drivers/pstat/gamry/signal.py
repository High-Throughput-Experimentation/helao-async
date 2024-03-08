from dataclasses import dataclass, field
from typing import List
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
    init_keys=["Freq", "RMS", "Precision"]
)

OCVSIGNAL_CONST = GamrySignal(
    name="GamryCOM.GamrySignalConst",
    param_keys=["Tval__s", "AcqInterval__s"],
    mode=ControlMode.PstatMode,
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
        "holdtime0__s",
        "holdtime1__s",
        "holdtime2__s",
        "AcqInterval__s",
        "cycles",
    ],
    mode=ControlMode.PstatMode,
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
        "Vinit__V",
        "Tinit__s",
        "Vstep__V",
        "Tstep__s",
        "Cycles",
        "AcqInterval__s",
    ],
    mode=ControlMode.PstatMode,
)

ISIGNAL_ARRAY = GamrySignal(
    name="GamryCOM.GamrySignalArray",
    param_keys=[
        "Iinit__A",
        "Tinit__s",
        "Istep__A",
        "Tstep__s",
        "Cycles",
        "AcqInterval__s",
    ],
    mode=ControlMode.GstatMode,
)
