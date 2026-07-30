"""Dataclass and instances for Biologic potentiostat techniques.

Defines the ``BiologicTechnique`` dataclass that pairs an easy-biologic
program class with the action-parameter and data-field name remaps used by
``BiologicDriver``, plus pre-built instances for OCV, CA, CP, CV, PEIS, GEIS,
and CAOCV. The ``BIOTECHS`` dict at module bottom indexes the instances by
technique name.
"""

from dataclasses import dataclass
from typing import Optional

from enum import StrEnum

# P3a-2: the easy-biologic vendor runtime is imported lazily (see
# `resolve_easy_class`) rather than at module import, so this registry — and
# the BiologicDriver that imports it — load without the SDK present (hermetic
# disconnected-construct; the SDK is only needed when a technique is actually
# instantiated in `BiologicDriver.setup`).


def resolve_easy_class(easy_class_name: str):
    """Lazily import ``easy_biologic.base_programs`` and return a program class.

    Args:
        easy_class_name: Attribute name of the ``BiologicProgram`` subclass in
            ``easy_biologic.base_programs`` (e.g. ``"OCV"``, ``"CA"``).

    Returns:
        The requested easy-biologic ``BiologicProgram`` subclass.
    """
    import easy_biologic.base_programs as blp

    return getattr(blp, easy_class_name)


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
    """Frequency sweep direction for EIS techniques.

    Attributes:
        LINEAR: Linear sweep between initial and final frequency.
        LOG: Logarithmic sweep.
    """

    LINEAR = "lin"
    LOG = "log"


@dataclass
class BiologicTechnique:
    """Description of a Biologic technique runnable through easy-biologic.

    Attributes:
        technique_name: Short name used as the lookup key in ``BIOTECHS``.
        easy_class_name: Attribute name of the easy-biologic ``BiologicProgram``
            subclass in ``easy_biologic.base_programs`` (resolved lazily via
            :func:`resolve_easy_class` so this module imports without the SDK).
        parameter_map: Mapping from action-server parameter keys to the
            easy-biologic program parameter names.
        field_map: Mapping from easy-biologic data field names to the HELAO
            canonical column names used in the emitted data dict.
    """

    technique_name: str
    easy_class_name: str
    parameter_map: Optional[dict[str, str]] = None
    field_map: Optional[dict[str, str]] = None


TECH_OCV = BiologicTechnique(
    technique_name="OCV",
    easy_class_name="OCV",
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
    easy_class_name="CA",
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
    easy_class_name="CP",
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
    easy_class_name="CV",
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
    easy_class_name="PEIS",
    parameter_map={
        "Vinit__V": "voltage",
        "Vamp__V": "amplitude_voltage",
        "Finit__Hz": "initial_frequency",
        "Ffinal__Hz": "final_frequency",
        "FrequencyNumber": "frequency_number",
        "Duration__s": "duration",
        "AcqInterval__s": "time_interval",
        "SweepMode": "sweep",
        "Repeats": "repeat",
        "DelayFraction": "wait",
        # "vs_initial": "vs_initial",
        "IRange": "current_range",
        "ERange": "voltage_range",
        "Bandwidth": "bandwidth",
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
    easy_class_name="GEIS",
    parameter_map={
        "Iinit__A": "current",
        "Iamp__A": "amplitude_current",
        "Finit__Hz": "initial_frequency",
        "Ffinal__Hz": "final_frequency",
        "FrequencyNumber": "frequency_number",
        "Duration__s": "duration",
        "AcqInterval__s": "time_interval",
        "SweepMode": "sweep",
        "Repeats": "repeat",
        "DelayFraction": "wait",
        # "vs_initial": "vs_initial",
        "IRange": "current_range",
        "ERange": "voltage_range",
        "Bandwidth": "bandwidth",
        # "AcqInterval__V": "voltage_interval",
        # "DriftCorrection": "correction",
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
TECH_CAOCV = BiologicTechnique(
    technique_name="CAOCV",
    easy_class_name="CAOCV",
    parameter_map={
        "CA_Vval__V_list": "ca_voltages",
        "CA_Tval__s_list": "ca_durations",
        "CA_AcqInterval__s": "ca_time_interval",
        "CA_AcqInterval__A": "ca_current_interval",
        "CA_IRange": "ca_current_range",
        "CA_ERange": "ca_voltage_range",
        "CA_Bandwidth": "ca_bandwidth",
        "OCV_Tval__s": "ocv_time",
        "OCV_AcqInterval__s": "ocv_time_interval",
        "OCV_AcqInterval__V": "ocv_voltage_interval",
    },
    field_map={
        "time": "t_s",
        "voltage": "Ewe_V",
        "current": "I_A",
        "power": "P_W",
        "cycle": "cycle",
    },
)

BIOTECHS = {
    x.technique_name: x
    for x in [TECH_OCV, TECH_CA, TECH_CP, TECH_CV, TECH_GEIS, TECH_PEIS, TECH_CAOCV]
}
