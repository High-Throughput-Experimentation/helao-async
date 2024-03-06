from dataclasses import dataclass, field
from typing import Optional, List
from enum import StrEnum


class DtaqType(StrEnum):
    ChronoPot = "ChronoPot"
    ChronoAmp = "ChronoAmp"


@dataclass
class GamryDtaq:
    name: str
    dtaq_type: Optional[DtaqType] = None
    output_keys: List[str] = field(default_factory=list)
    int_param_keys: List[str] = field(default_factory=list)
    bool_param_keys: List[str] = field(default_factor=list)


DTAQ_CPIV = GamryDtaq(
    name="GamryCOM.GamryDtaqCpiv",
    dtaq_type=None,
    output_keys=[
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
    int_param_keys=[
        "SetStopAtDelayIMin",
        "SetStopAtDelayIMax",
        "SetStopAtDelayDIMin",
        "SetStopAtDelayDIMax",
        "SetStopAtDelayADIMin",
        "SetStopAtDelayADIMax",
    ],
    bool_param_keys=[
        "SetThreshIMin",
        "SetThreshIMax",
        "SetThreshVMin",
        "SetThreshVMax",
        "SetThreshTMin",
        "SetThreshTMax",
        "SetStopIMin",
        "SetStopIMax",
        "SetStopDIMin",
        "SetStopDIMax",
        "SetStopADIMin",
        "SetStopADIMax",
    ],
)

DTAQ_CHRONOP = GamryDtaq(
    name="GamryCOM.GamryDtaqChrono",
    dtaq_type=DtaqType.ChronoPot,
    output_keys=[
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
    int_param_keys=[
        "SetStopAtDelayXMin",
        "SetStopAtDelayXMax",
    ],
    bool_param_keys=[
        "SetThreshIMin",
        "SetThreshIMax",
        "SetThreshVMin",
        "SetThreshVMax",
        "SetThreshTMin",
        "SetThreshTMax",
        "SetStopXMin",
        "SetStopXMax",
        "SetDecimation",
    ],
)

DTAQ_CHRONOA = GamryDtaq(
    name="GamryCOM.GamryDtaqChrono",
    dtaq_type=DtaqType.ChronoAmp,
    output_keys=[
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
    int_param_keys=[
        "SetStopAtDelayXMin",
        "SetStopAtDelayXMax",
    ],
    bool_param_keys=[
        "SetThreshIMin",
        "SetThreshIMax",
        "SetThreshVMin",
        "SetThreshVMax",
        "SetThreshTMin",
        "SetThreshTMax",
        "SetStopXMin",
        "SetStopXMax",
        "SetDecimation",
    ],
)


DTAQ_RCV = GamryDtaq(
    name="GamryCOM.GamryDtaqRcv",
    output_keys=[
        "t_s",
        "Ewe_V",
        "Vu",
        "I_A",
        "Vsig",
        "Ach_V",
        "IERange",
        "Overload_HEX",
        "StopTest",
        "Cycle",
        "unknown1",
    ],
    int_param_keys=[
        "SetStopAtDelayIMin",
        "SetStopAtDelayIMax",
    ],
    bool_param_keys=[
        "SetThreshIMin",
        "SetThreshIMax",
        "SetThreshVMin",
        "SetThreshVMax",
        "SetThreshTMin",
        "SetThreshTMax",
        "SetStopIMin",
        "SetStopIMax",
    ],
)

DTAQ_OCV = GamryDtaq(
    name="GamryCOM.GamryDtaqOcv",
    output_keys=[
        "t_s",
        "Ewe_V",
        "Vm",
        "Vsig",
        "Ach_V",
        "Overload_HEX",
        "StopTest",
        "unknown1",
        "unknown2",
        "unknown3",
    ],
    bool_param_keys=[
        "SetStopADVMin",
        "SetStopADVMax",
    ],
)

DTAQ_UNIV = GamryDtaq(
    name="GamryCOM.GamryDtaqUniv",
    output_keys=[
        "t_s",
        "Ewe_V",
        "Vu",
        "I_A",
        "Vsig",
        "Ach_V",
        "IERange",
        "Overload_HEX",
        "unknown1",
    ],
)

DTAQ_EIS = GamryDtaq(
    name="GamryCOM.GamryDtaqEis",
    output_keys=[
        "I_A",
        "Ewe_V",
    ],
)
