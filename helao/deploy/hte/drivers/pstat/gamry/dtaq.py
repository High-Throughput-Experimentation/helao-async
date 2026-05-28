"""Dataclass and instances describing Gamry dtaq (data acquisition) objects.

A ``GamryDtaq`` captures the GamryCOM ProgID of a dtaq class, the names of
the data columns it emits, and the names of int- and bool-style parameter
setters it accepts so that ``GamryDriver.setup`` can construct, parameterize,
and read from the dtaq without per-technique branching.
"""

from dataclasses import dataclass, field
from typing import Optional, List
from enum import StrEnum


class DtaqType(StrEnum):
    """Subtype passed to ``GamryDtaqChrono.Init`` to select potentiostatic vs
    galvanostatic chronoamperometry.

    Attributes:
        ChronoPot: Chronopotentiometry (controlled current).
        ChronoAmp: Chronoamperometry (controlled potential).
    """

    ChronoPot = "ChronoPot"
    ChronoAmp = "ChronoAmp"


@dataclass
class GamryDtaq:
    """Description of a GamryCOM dtaq class and its parameters.

    Attributes:
        name: GamryCOM ProgID (e.g. ``"GamryCOM.GamryDtaqCpiv"``).
        dtaq_type: Optional ``DtaqType`` subtype passed to ``Init`` for
            dtaqs that require one (e.g. ``GamryDtaqChrono``).
        output_keys: Column names of the data tuples emitted by ``Cook``,
            in order.
        int_param_keys: Names of dtaq setter methods that take a single
            integer / float argument (delay limits etc.).
        bool_param_keys: Names of dtaq setter methods that take an
            ``(enable, value)`` pair.
    """

    name: str
    dtaq_type: Optional[DtaqType] = None
    output_keys: List[str] = field(default_factory=list)
    int_param_keys: List[str] = field(default_factory=list)
    bool_param_keys: List[str] = field(default_factory=list)


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
