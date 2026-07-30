"""Dataclass and instances for Gamry potentiostat excitation signals.

Each ``GamrySignal`` describes one of the ``GamryCOM.GamrySignal*`` COM
classes (ramp, constant, ramp-up-down, array) by ProgID, control mode, and
the list of parameter keys consumed by its ``Init`` method. Parameter keys
are ordered to match the underlying ``Init`` argument order and named to
mirror the GamryCOM API except that ``ScanRate`` is renamed to
``ScanRate__V_s`` / ``ScanRate__A_s`` and ``AcqInterval`` is suffixed with
its unit.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Union


class ControlMode(StrEnum):
    """Potentiostat control mode passed to ``SetCtrlMode``.

    Attributes:
        PstatMode: Potentiostatic (voltage-controlled) operation.
        GstatMode: Galvanostatic (current-controlled) operation.
    """

    PstatMode = "PstatMode"
    GstatMode = "GstatMode"


@dataclass
class GamrySignal:
    """Description of a GamryCOM signal COM class and its parameters.

    Attributes:
        name: GamryCOM ProgID (e.g. ``"GamryCOM.GamrySignalRamp"``).
        mode: Required potentiostat control mode for this signal.
        param_keys: Ordered list of parameter keys consumed by the signal
            ``Init`` method, after the ``pstat`` and control-mode arguments.
        init_keys: Additional keys consumed by some dtaq ``Init`` methods
            (e.g. EIS ``Freq``/``RMS``/``Precision``).
        map_keys: Optional default fill-ins for ``param_keys``. A value can be
            a numeric literal (used directly) or a string naming another
            action-parameter key whose value is copied in during setup.
    """

    name: str
    mode: ControlMode
    param_keys: list[str] = field(default_factory=list)
    init_keys: list[str] = field(default_factory=list)
    map_keys: dict[str, Union[int, float, str]] = field(default_factory=dict)


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
    param_keys=["Cycles", "AcqInterval__s", "AcqPointsPerCycle", "SignalArray__V"],
    mode=ControlMode.PstatMode,
)

ISIGNAL_ARRAY = GamrySignal(
    name="GamryCOM.GamrySignalArray",
    param_keys=["Cycles", "AcqInterval__s", "AcqPointsPerCycle", "SignalArray__V"],
    mode=ControlMode.GstatMode,
)
