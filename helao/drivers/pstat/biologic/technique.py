"""Dataclass and instances for Biologic potentiostat techniques."""

from dataclasses import dataclass
from typing import Optional, List, Dict
import easy_biologic.base_programs as blp
from easy_biologic import BiologicProgram


from enum import StrEnum

class EC_IRange(StrEnum):
    p100 = "p100"
    n1   = "n1"  
    n10  = "n10" 
    n100 = "n100"
    u1   = "u1"  
    u10  = "u10" 
    u100 = "u100"
    m1   = "m1"  
    m10  = "m10" 
    m100 = "m100"
    a1   = "a1"    # 1 amp

    KEEP    = "KEEP"   
    BOOSTER = "BOOSTER"
    AUTO    = "AUTO"   

@dataclass
class BiologicTechnique:
    technique_name: str
    easy_class: BiologicProgram
    parameter_map: Optional[Dict[str, str]] = None
    field_map: Optional[Dict[str, str]] = None


TECH_OCV = BiologicTechnique(
    technique_name="OCV",
    easy_class=blp.OCV,
    parameter_map={
        "Tval__s": "time",
        "AcqInterval__s": "time_interval",
        "AcqInterval__V": "voltage_interval",
    },
    field_map={
        "time": "t_s",
        "voltage": "Ewe_V",
    },
)
TECH_CA = BiologicTechnique(
    technique_name="CA",
    easy_class=blp.CA,
    parameter_map={
        "Vval__V": "voltages",
        "Tval__s": "durations",
        "AcqInterval__s": "time_interval",
        "AcqInterval__A": "current_interval",
        "IRange": "current_range",
    },
    field_map={
        "time": "t_s",
        "voltage": "Ewe_V",
        "current": "I_A",
        "power": "P_W",
        "cycle": "cycle",
    },
)
TECH_CP = BiologicTechnique(
    technique_name="CP",
    easy_class=blp.CP,
    parameter_map={
        "Ival__A": "currents",
        "Tval__s": "durations",
        "AcqInterval__s": "time_interval",
        "AcqInterval__V": "voltage_interval",
    },
    field_map={
        "time": "t_s",
        "voltage": "Ewe_V",
        "current": "I_A",
        "power": "P_W",
        "cycle": "cycle",
    },
)
TECH_CV = BiologicTechnique(
    technique_name="CV",
    easy_class=blp.CV,
    parameter_map={
        "Vinit__V": "start",
        "Vapex1__V": "end",
        "Vapex2__V": "E2",
        "Vfinal__V": "Ef",
        "ScanRate__V_s": "rate",
        "Cycles": "N_Cycles",
        "AcqInterval__V": "step",
    },
    field_map={
        "time": "t_s",
        "voltage": "Ewe_V",
        "current": "I_A",
        "power": "P_W",
        "cycle": "cycle",
    },
)

BIOTECHS = {x.technique_name: x for x in [TECH_OCV, TECH_CA, TECH_CP, TECH_CV]}
