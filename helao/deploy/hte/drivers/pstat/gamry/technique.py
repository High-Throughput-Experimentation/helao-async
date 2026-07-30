"""Dataclass and instances for Gamry potentiostat techniques.

Pairs a ``GamryDtaq`` (data acquisition class) with a ``GamrySignal``
(excitation waveform) plus range-handling flags to fully describe a single
electrochemical technique. Pre-built instances cover LSV, LSA, CA, CP, CV,
OCV, and RCA.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Optional

from .dtaq import (
    DTAQ_CHRONOA,
    DTAQ_CHRONOP,
    DTAQ_CPIV,
    DTAQ_OCV,
    DTAQ_RCV,
    DTAQ_UNIV,
    GamryDtaq,
)
from .signal import (
    ISIGNAL_CONST,
    ISIGNAL_RAMP,
    OCVSIGNAL_CONST,
    VSIGNAL_ARRAY,
    VSIGNAL_CONST,
    VSIGNAL_RAMP,
    VSIGNAL_RUPDN,
    GamrySignal,
)

# define enums to match GamryCOM


class OnMethod(StrEnum):
    """``SetCell`` mode used to energize the cell for a technique.

    Attributes:
        CellMon: Cell-monitor (passive, e.g. OCV) — no driven excitation.
        CellOn: Cell on (actively driven by the configured signal).
    """

    CellMon = "CellMon"
    CellOn = "CellOn"


@dataclass
class GamryTechnique:
    """Description of a Gamry electrochemical technique.

    Attributes:
        name: Short technique label (e.g. ``"LSV"``).
        on_method: ``SetCell`` mode used when starting the measurement.
        dtaq: ``GamryDtaq`` descriptor for the data acquisition object.
        signal: ``GamrySignal`` descriptor for the excitation waveform.
        set_decimation: Optional value passed to ``dtaq.SetDecimation``.
        set_vchrangemode: Optional override of voltage channel auto-range
            mode applied via ``SetVchRangeMode``.
        set_ierangemode: Optional override of current range auto-range
            mode applied via ``SetIERangeMode``.
        vchrange_keys: Signal parameter names whose maximum absolute value
            sets the voltage channel range.
        ierange_keys: Signal parameter names whose maximum absolute value
            sets the current channel range.
    """

    name: str
    on_method: OnMethod
    dtaq: GamryDtaq
    signal: GamrySignal
    set_decimation: Optional[bool] = None
    set_vchrangemode: Optional[bool] = None
    set_ierangemode: Optional[bool] = None
    vchrange_keys: Optional[list[str]] = None
    ierange_keys: Optional[list[str]] = None


TECH_LSV = GamryTechnique(
    name="LSV",
    on_method=OnMethod.CellOn,
    dtaq=DTAQ_CPIV,
    signal=VSIGNAL_RAMP,
    set_vchrangemode=False,
    vchrange_keys=[
        "Vinit__V",
        "Vfinal__V",
    ],  # max absolute value of these params to set range
)

TECH_LSA = GamryTechnique(
    name="LSA",
    on_method=OnMethod.CellOn,
    dtaq=DTAQ_CPIV,
    signal=ISIGNAL_RAMP,
    set_ierangemode=False,
    ierange_keys=[
        "Iinit__A",
        "Ifinal__A",
    ],  # max absolute value of these params to set rang
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
    ierange_keys=["Ival__A"],
)
TECH_CV = GamryTechnique(
    name="CV",
    on_method=OnMethod.CellOn,
    dtaq=DTAQ_RCV,
    signal=VSIGNAL_RUPDN,
    set_vchrangemode=False,
    vchrange_keys=["Vinit__V", "Vapex1__V", "Vapex2__V", "Vfinal__V"],
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
