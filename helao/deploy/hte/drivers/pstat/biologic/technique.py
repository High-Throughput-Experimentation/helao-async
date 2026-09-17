"""ECC parameter tables and per-technique builds for the EClib1 driver.

Each ``BiologicTechnique`` carries the ``.ecc`` stem and vendor technique id
BL_LoadTechnique needs, a ``param_table`` declaring the ECC label/kind/array
width for every parameter the technique accepts, a ``defaults`` dict for
action keys no endpoint supplies, and a ``build`` callable that turns merged
action params into ECC label -> value(s). ``entries()`` expands a build's
output into ``(label, value, index)`` triples, casting each value to its
declared kind, because the DLL has one setter per type
(``BL_DefineSglParameter`` / ``BL_DefineIntParameter`` /
``BL_DefineBoolParameter``) and a value of the wrong Python type would target
the wrong one.

``defaults`` is load-bearing: it reproduces the defaults easy-biologic's
per-program classes supplied when an endpoint left a key unset, since four
production stations' archives were produced under those defaults.

``BIOTECHS`` is the module-level registry ``TECHNIQUE_REGISTRIES["eclib"]``
resolves against; the name and role are unchanged from the easy-biologic
driver this replaces.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable, NamedTuple

from helao.deploy.hte.drivers.pstat.biologic import data, vendor
from helao.deploy.hte.drivers.pstat.biologic.enum import (
    ec_bandwidth,
    ec_erange,
    ec_irange,
)


class TechniqueError(RuntimeError):
    """A build produced a parameter this technique does not declare, or too
    many values for one it does."""


class SweepMode(StrEnum):
    """Frequency sweep direction for EIS techniques.

    Attributes:
        LINEAR: Linear sweep between initial and final frequency.
        LOG: Logarithmic sweep.
    """

    LINEAR = "lin"
    LOG = "log"


Param = NamedTuple("Param", [("label", str), ("kind", str), ("arity", int)])

_KIND_CAST = {"float": float, "int": int, "bool": bool}


@dataclass
class BiologicTechnique:
    """One EClib1 technique: its .ecc file, id, parameters, and build.

    Attributes:
        technique_name: Lookup key in ``BIOTECHS``, and into ``data.COLUMNS``.
        ecc_stem: Base filename (without extension) of the .ecc technique file
            BL_LoadTechnique loads.
        tech_id: Vendor technique id (``vendor.TECH_ID`` member), used to
            confirm the loaded technique against ``GetCurrentValues``.
        param_table: ECC label -> ``Param`` (kind and array width), for
            validating and casting a build's output.
        defaults: Action-key -> value, applied for keys the endpoint omits.
        build: Merged action params -> {ECC label: value or list of values}.
    """

    technique_name: str
    ecc_stem: str
    tech_id: int
    param_table: dict[str, Param]
    defaults: dict[str, Any]
    build: Callable[[dict], dict[str, Any]]

    @property
    def column_plan(self) -> tuple[str, ...]:
        return tuple(data.COLUMNS[self.technique_name])


def entries(
    technique: BiologicTechnique, action_params: dict
) -> list[tuple[str, Any, int]]:
    """Expand a build's output into (label, value, index) triples.

    Casts each value to its declared ECC kind, because the DLL has one setter
    per type and a float sent through `BL_DefineIntParameter` sets a different
    parameter than the caller named.
    """
    out: list[tuple[str, Any, int]] = []
    for label, value in technique.build(action_params).items():
        try:
            param = technique.param_table[label]
        except KeyError:
            raise TechniqueError(
                f"{technique.technique_name}: {label!r} is not a declared "
                f"parameter of {technique.ecc_stem}.ecc"
            )
        values = value if isinstance(value, list) else [value]
        if len(values) > param.arity:
            raise TechniqueError(
                f"{technique.technique_name}: {label} takes at most "
                f"{param.arity} values, got {len(values)}"
            )
        cast = _KIND_CAST[param.kind]
        out.extend((label, cast(v), i) for i, v in enumerate(values))
    return out


def _ranges(p: dict) -> dict[str, int]:
    """Hardware-range parameters, each included only if the caller gave it.

    Not every technique's endpoint exposes all three (OCV exposes none), and
    tests exercising other behavior omit them -- so absence, not a default,
    is what "not supplied" means here.
    """
    out: dict[str, int] = {}
    if "IRange" in p:
        out["I_Range"] = ec_irange(p["IRange"])
    if "ERange" in p:
        out["E_Range"] = ec_erange(p["ERange"])
    if "Bandwidth" in p:
        out["Bandwidth"] = ec_bandwidth(p["Bandwidth"])
    return out


def _steps(p: dict, value_key: str, duration_key: str):
    """Wrap scalar step params into aligned lists.

    Returns (values, durations, vs_initial, last_index). Raises
    `TechniqueError` naming `Duration_step` when the two lengths differ -- the
    DLL would otherwise run the steps it has durations for and stop, silently.
    """
    values = p[value_key] if isinstance(p[value_key], list) else [p[value_key]]
    durations = (
        p[duration_key] if isinstance(p[duration_key], list) else [p[duration_key]]
    )
    if len(values) != len(durations):
        raise TechniqueError(
            f"{value_key} has {len(values)} step(s) but Duration_step has "
            f"{len(durations)}"
        )
    vs_initial = [p["vs_initial"]] * len(values)
    return values, durations, vs_initial, len(values) - 1


def _build_ocv(p: dict) -> dict[str, Any]:
    out = {
        "Rest_time_T": p["Tval__s"],
        "Record_every_dE": p["AcqInterval__V"],
    }
    if "AcqInterval__s" in p:
        out["Record_every_dT"] = p["AcqInterval__s"]
    return out


def _build_ca(p: dict) -> dict[str, Any]:
    steps, durations, vs_initial, last = _steps(p, "Vval__V", "Tval__s")
    out = {
        "Voltage_step": steps,
        "vs_initial": vs_initial,
        "Duration_step": durations,
        "Step_number": last,
        "N_Cycles": p["N_Cycles"],
    }
    if "AcqInterval__s" in p:
        out["Record_every_dT"] = p["AcqInterval__s"]
    if "AcqInterval__A" in p:
        out["Record_every_dI"] = p["AcqInterval__A"]
    out.update(_ranges(p))
    return out


def _build_cp(p: dict) -> dict[str, Any]:
    steps, durations, vs_initial, last = _steps(p, "Ival__A", "Tval__s")
    out = {
        "Current_step": steps,
        "vs_initial": vs_initial,
        "Duration_step": durations,
        "Step_number": last,
        "N_Cycles": p["N_Cycles"],
    }
    if "AcqInterval__s" in p:
        out["Record_every_dT"] = p["AcqInterval__s"]
    if "AcqInterval__V" in p:
        out["Record_every_dE"] = p["AcqInterval__V"]
    out.update(_ranges(p))
    return out


def _build_cv(p: dict) -> dict[str, Any]:
    # PDF section 7.3.2: [Ei, E1, E2, Ei, Ef], and Scan_number is fixed at 2.
    profile = [
        p["Vinit__V"],
        p["Vapex1__V"],
        p["Vapex2__V"],
        p["Vinit__V"],
        p["Vfinal__V"],
    ]
    return {
        "vs_initial": [p["vs_initial"]] * 5,
        "Voltage_step": profile,
        "Scan_Rate": [p["ScanRate__V_s"]] * 5,
        "Scan_number": 2,
        "Record_every_dE": p["AcqInterval__V"],
        "Average_over_dE": p["Average_over_dE"],
        "N_Cycles": p["Cycles"],
        "Begin_measuring_I": p["Begin_measuring_I"],
        "End_measuring_I": p["End_measuring_I"],
        **_ranges(p),
    }


TECH_OCV = BiologicTechnique(
    technique_name="OCV",
    ecc_stem="ocv",
    tech_id=vendor.TECH_ID.OCV,
    param_table={
        "Rest_time_T": Param("Rest_time_T", "float", 1),
        "Record_every_dE": Param("Record_every_dE", "float", 1),
        "Record_every_dT": Param("Record_every_dT", "float", 1),
    },
    defaults={"AcqInterval__V": 0.01},
    build=_build_ocv,
)

_DC_STEP_PARAMS = {
    "vs_initial": Param("vs_initial", "bool", 20),
    "Duration_step": Param("Duration_step", "float", 20),
    "Step_number": Param("Step_number", "int", 1),
    "N_Cycles": Param("N_Cycles", "int", 1),
    "I_Range": Param("I_Range", "int", 1),
    "E_Range": Param("E_Range", "int", 1),
    "Bandwidth": Param("Bandwidth", "int", 1),
}

TECH_CA = BiologicTechnique(
    technique_name="CA",
    ecc_stem="ca",
    tech_id=vendor.TECH_ID.CA,
    param_table={
        "Voltage_step": Param("Voltage_step", "float", 20),
        "Record_every_dT": Param("Record_every_dT", "float", 1),
        "Record_every_dI": Param("Record_every_dI", "float", 1),
        **_DC_STEP_PARAMS,
    },
    defaults={"N_Cycles": 0, "vs_initial": False},
    build=_build_ca,
)

TECH_CP = BiologicTechnique(
    technique_name="CP",
    ecc_stem="cp",
    tech_id=vendor.TECH_ID.CP,
    param_table={
        "Current_step": Param("Current_step", "float", 20),
        "Record_every_dT": Param("Record_every_dT", "float", 1),
        "Record_every_dE": Param("Record_every_dE", "float", 1),
        **_DC_STEP_PARAMS,
    },
    defaults={"N_Cycles": 0, "vs_initial": False},
    build=_build_cp,
)

TECH_CV = BiologicTechnique(
    technique_name="CV",
    ecc_stem="cv",
    tech_id=vendor.TECH_ID.CV,
    param_table={
        "vs_initial": Param("vs_initial", "bool", 5),
        "Voltage_step": Param("Voltage_step", "float", 5),
        "Scan_Rate": Param("Scan_Rate", "float", 5),
        "Scan_number": Param("Scan_number", "int", 1),
        "Record_every_dE": Param("Record_every_dE", "float", 1),
        "Average_over_dE": Param("Average_over_dE", "bool", 1),
        "N_Cycles": Param("N_Cycles", "int", 1),
        "Begin_measuring_I": Param("Begin_measuring_I", "float", 1),
        "End_measuring_I": Param("End_measuring_I", "float", 1),
        "I_Range": Param("I_Range", "int", 1),
        "E_Range": Param("E_Range", "int", 1),
        "Bandwidth": Param("Bandwidth", "int", 1),
    },
    defaults={
        "AcqInterval__V": 0.01,
        "Average_over_dE": False,
        "Begin_measuring_I": 0.5,
        "End_measuring_I": 1.0,
        "vs_initial": False,
    },
    build=_build_cv,
)

BIOTECHS: dict[str, BiologicTechnique] = {
    x.technique_name: x for x in [TECH_OCV, TECH_CA, TECH_CP, TECH_CV]
}
