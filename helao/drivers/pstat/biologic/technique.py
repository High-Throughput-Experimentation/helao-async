"""Dataclass and instances for Biologic potentiostat techniques."""

from dataclasses import dataclass
from typing import Optional, List, Dict
import easy_biologic.base_programs as blp
from easy_biologic import BiologicProgram


@dataclass
class BiologicTechnique:
    technique_name: str
    easy_class: BiologicProgram
    parameter_map: Optional[Dict[str, str]] = None


OCV = BiologicTechnique(
    technique_name="OCV",
    easy_class=blp.OCV,
    parameter_map={
        "Tval__s": "time",
        "AcqInterval__s": "time_interval",
        "AcqInterval__V": "voltage_interval",
    },
)
CA = BiologicTechnique(
    technique_name="CA",
    easy_class=blp.CA,
    parameter_map={
        "Vval__V": "voltage",
        "Tval__s": "duration",
        "AcqInterval__s": "time_interval",
        "AcqInterval__A": "current_interval",
        "IErange": "current_range",
    },
)
CP = BiologicTechnique(
    technique_name="CP",
    easy_class=blp.CP,
    parameter_map={
        "Ival__A": "current",
        "Tval__s": "duration",
        "AcqInterval__s": "time_interval",
        "AcqInterval__V": "voltage_interval",
    },
)
CV = BiologicTechnique(
    technique_name="CV",
    easy_class=blp.JV_Scan,
    parameter_map={
        "Vinit__V": "start",
        "Vapex1__V": "v1",
        "Vapex2__V": "v2",
        "Vfinal__V": "end",
        "ScanRate__V_s": "rate",
        "Cycles": "cycles",
        "AcqInterval__V": "step",
    },
)
