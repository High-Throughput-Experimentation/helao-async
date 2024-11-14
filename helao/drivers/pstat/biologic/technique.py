"""Dataclass and instances for Biologic potentiostat techniques."""

from dataclasses import dataclass
from typing import Optional, List, Dict
import easy_biologic.base_programs as blp
from easy_biologic import BiologicProgram


from enum import StrEnum

# class IRange(StrEnum):
#     p100 = "p100"
#     n1   = "n1"  
#     n10  = "n10" 
#     n100 = "n100"
#     u1   = "u1"  
#     u10  = "u10" 
#     u100 = "u100"
#     m1   = "m1"  
#     m10  = "m10" 
#     m100 = "m100"
#     a1   = "a1"    # 1 amp

#     KEEP    = "KEEP"   
#     BOOSTER = "BOOSTER"
#     AUTO    = "AUTO"   

# class ERange(StrEnum):
#     v2_5 = "v2_5"
#     v5 = "v5"
#     v10 = "v10"
#     AUTO = "AUTO"

class SweepMode(StrEnum):
    LINEAR = "lin"
    LOG    = "log"

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
        # "IRange": "current_range",
        "ERange": "voltage_range",
        "Bandwidth": "bandwidth",
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
        "ERange": "voltage_range",
        "Bandwidth": "bandwidth",
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
        "IRange": "current_range",
        "ERange": "voltage_range",
        "Bandwidth": "bandwidth",
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
        "IRange": "current_range",
        "ERange": "voltage_range",
        "Bandwidth": "bandwidth",
    },
    field_map={
        "time": "t_s",
        "voltage": "Ewe_V",
        "current": "I_A",
        "power": "P_W",
        "cycle": "cycle",
    },
)

TECH_PEIS = BiologicTechnique(
    technique_name="PEIS",
    easy_class=blp.PEIS,
    parameter_map={
        "Vinit__V": "voltage",
        "Vamp__V": "amplitude_voltage",
        "Finit__Hz": "initial_frequency",
        "Ffinal__Hz": "final_frequency",
        "Duration__s": "duration",
        "AcqInterval__s": "time_interval",
        "vs_initial": "vs_initial",
        "IRange": "current_range",
        "ERange": "voltage_range",
        "Bandwidth": "bandwidth",
        # "AcqInterval__I": "current_interval",
        # "SweepMode": "sweep",
        # "Repeats": "repeat",
        # "DriftCorrection": "correction",
        # "DelayFraction": "wait",
        },
    field_map={
        "process": "process",
        "time": "t_s",
        "voltage": "Ewe_V",
        "current": "I_A",
        "abs_voltage": "AbsEwe_V",
        "abs_current": "AbsI_A",
        "impedance_phase": "phase",
        "impedance_modulus": "modulus",
        "voltage_ce": "Ece_V",
        "abs_voltage_ce": "AbsEce_V",
        "abs_current_ce": "AbsIce_A",
        "impedance_ce_phase": "phase_ce",
        "impedance_ce_modulus": "modulus_ce",
        "frequency": "f_Hz",
        },
)

TECH_GEIS = BiologicTechnique(
    technique_name="GEIS",
    easy_class=blp.GEIS,
    parameter_map={
        "Iinit__A": "current",
        "Iamp__A": "amplitude_current",
        "Finit__Hz": "initial_frequency",
        "Ffinal__Hz": "final_frequency",
        "Duration__s": "duration",
        "AcqInterval__s": "time_interval",
        "vs_initial": "vs_initial",
        "IRange": "current_range",
        "ERange": "voltage_range",
        "Bandwidth": "bandwidth",
        # "AcqInterval__V": "voltage_interval",
        # "SweepMode": "sweep",
        # "Repeats": "repeat",
        # "DriftCorrection": "correction",
        # "DelayFraction": "wait",
        },
    field_map={
        "process": "process",
        "time": "t_s",
        "voltage": "Ewe_V",
        "current": "I_A",
        "abs_voltage": "AbsEwe_V",
        "abs_current": "AbsI_A",
        "impedance_phase": "phase",
        "impedance_modulus": "modulus",
        "voltage_ce": "Ece_V",
        "abs_voltage_ce": "AbsEce_V",
        "abs_current_ce": "AbsIce_A",
        "impedance_ce_phase": "phase_ce",
        "impedance_ce_modulus": "modulus_ce",
        "frequency": "f_Hz",
        },
)

BIOTECHS = {x.technique_name: x for x in [TECH_OCV, TECH_CA, TECH_CP, TECH_CV, TECH_GEIS, TECH_PEIS]}
