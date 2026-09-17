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

from dataclasses import dataclass, field
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
    return {
        "Rest_time_T": p["Tval__s"],
        "Record_every_dT": p["AcqInterval__s"],
        "Record_every_dE": p["AcqInterval__V"],
    }


def _build_ca(p: dict) -> dict[str, Any]:
    steps, durations, vs_initial, last = _steps(p, "Vval__V", "Tval__s")
    return {
        "Voltage_step": steps,
        "vs_initial": vs_initial,
        "Duration_step": durations,
        "Step_number": last,
        "Record_every_dT": p["AcqInterval__s"],
        "Record_every_dI": p["AcqInterval__A"],
        "N_Cycles": p["N_Cycles"],
        **_ranges(p),
    }


def _build_cp(p: dict) -> dict[str, Any]:
    steps, durations, vs_initial, last = _steps(p, "Ival__A", "Tval__s")
    return {
        "Current_step": steps,
        "vs_initial": vs_initial,
        "Duration_step": durations,
        "Step_number": last,
        "Record_every_dT": p["AcqInterval__s"],
        "Record_every_dE": p["AcqInterval__V"],
        "N_Cycles": p["N_Cycles"],
        **_ranges(p),
    }


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
    # easy-biologic's OCV.__init__ defaults: {"time_interval": 1,
    # "voltage_interval": 0.01}.
    defaults={"AcqInterval__s": 1.0, "AcqInterval__V": 0.01},
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
    # easy-biologic's CA.__init__ defaults: {"vs_initial": False,
    # "time_interval": 1.0, "current_interval": 1e-3}.
    defaults={
        "N_Cycles": 0,
        "vs_initial": False,
        "AcqInterval__s": 1.0,
        "AcqInterval__A": 1e-3,
    },
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
    # easy-biologic's CP.__init__ defaults: {"vs_initial": False,
    # "time_interval": 1.0, "voltage_interval": 1e-3}.
    defaults={
        "N_Cycles": 0,
        "vs_initial": False,
        "AcqInterval__s": 1.0,
        "AcqInterval__V": 1e-3,
    },
    build=_build_cp,
)


def ec_sweep(value) -> bool:
    """The ECC ``sweep`` flag for a ``SweepMode``.

    PDF section 7.11.2 declares ``sweep`` boolean, "TRUE for linear points
    spacing". easy-biologic cast the action value with ``bool(...)``, and
    ``bool("log")`` is ``True`` -- so every PEIS and GEIS run swept linearly
    while the recorded ``SweepMode`` said ``log``.

    A bare bool is refused rather than passed through: accepting one would let
    the old ``bool(value)`` call site keep working and silently mean linear.
    """
    if isinstance(value, bool):
        raise ValueError(
            "sweep takes a SweepMode ('lin'/'log'), not a bool -- bool('log') "
            "is True, which is what this function exists to stop"
        )
    return SweepMode(value) is SweepMode.LINEAR


_EIS_SHARED_PARAMS = {
    "vs_initial": Param("vs_initial", "bool", 1),
    "vs_final": Param("vs_final", "bool", 1),
    "Duration_step": Param("Duration_step", "float", 1),
    "Step_number": Param("Step_number", "int", 1),
    "Record_every_dT": Param("Record_every_dT", "float", 1),
    "Final_frequency": Param("Final_frequency", "float", 1),
    "Initial_frequency": Param("Initial_frequency", "float", 1),
    "sweep": Param("sweep", "bool", 1),
    "Frequency_number": Param("Frequency_number", "int", 1),
    "Average_N_times": Param("Average_N_times", "int", 1),
    "Correction": Param("Correction", "bool", 1),
    "Wait_for_steady": Param("Wait_for_steady", "float", 1),
    "I_Range": Param("I_Range", "int", 1),
    "E_Range": Param("E_Range", "int", 1),
    "Bandwidth": Param("Bandwidth", "int", 1),
}


def _build_peis(p: dict) -> dict[str, Any]:
    return {
        "vs_initial": p["vs_initial"],
        "vs_final": p["vs_initial"],
        "Initial_Voltage_step": p["Vinit__V"],
        "Final_Voltage_step": p["Vinit__V"],
        "Duration_step": p["Duration__s"],
        "Step_number": 0,
        "Record_every_dT": p["AcqInterval__s"],
        "Record_every_dI": p["AcqInterval__A"],
        "Final_frequency": p["Ffinal__Hz"],
        "Initial_frequency": p["Finit__Hz"],
        "sweep": ec_sweep(p["SweepMode"]),
        "Amplitude_Voltage": p["Vamp__V"],
        "Frequency_number": p["FrequencyNumber"],
        "Average_N_times": p["Repeats"],
        "Correction": p["Correction"],
        "Wait_for_steady": p["DelayFraction"],
        **_ranges(p),
    }


def _build_geis(p: dict) -> dict[str, Any]:
    return {
        "vs_initial": p["vs_initial"],
        "vs_final": p["vs_initial"],
        "Initial_Current_step": p["Iinit__A"],
        "Final_Current_step": p["Iinit__A"],
        "Duration_step": p["Duration__s"],
        "Step_number": 0,
        "Record_every_dT": p["AcqInterval__s"],
        "Record_every_dE": p["AcqInterval__V"],
        "Final_frequency": p["Ffinal__Hz"],
        "Initial_frequency": p["Finit__Hz"],
        "sweep": ec_sweep(p["SweepMode"]),
        "Amplitude_Current": p["Iamp__A"],
        "Frequency_number": p["FrequencyNumber"],
        "Average_N_times": p["Repeats"],
        "Correction": p["Correction"],
        "Wait_for_steady": p["DelayFraction"],
        **_ranges(p),
    }


TECH_PEIS = BiologicTechnique(
    technique_name="PEIS",
    ecc_stem="peis",
    tech_id=vendor.TECH_ID.PEIS,
    param_table={
        "Initial_Voltage_step": Param("Initial_Voltage_step", "float", 1),
        "Final_Voltage_step": Param("Final_Voltage_step", "float", 1),
        "Amplitude_Voltage": Param("Amplitude_Voltage", "float", 1),
        "Record_every_dI": Param("Record_every_dI", "float", 1),
        **_EIS_SHARED_PARAMS,
    },
    # easy-biologic's PEIS.__init__ defaults: {"vs_initial": False,
    # "current_interval": 0.001, "correction": False}. time_interval, sweep,
    # repeat, and wait are all supplied by the endpoint (AcqInterval__s,
    # SweepMode, Repeats, DelayFraction).
    defaults={
        "vs_initial": False,
        "Correction": False,
        "AcqInterval__A": 0.001,
    },
    build=_build_peis,
)

TECH_GEIS = BiologicTechnique(
    technique_name="GEIS",
    ecc_stem="geis",
    tech_id=vendor.TECH_ID.GEIS,
    param_table={
        "Initial_Current_step": Param("Initial_Current_step", "float", 1),
        "Final_Current_step": Param("Final_Current_step", "float", 1),
        "Amplitude_Current": Param("Amplitude_Current", "float", 1),
        "Record_every_dE": Param("Record_every_dE", "float", 1),
        **_EIS_SHARED_PARAMS,
    },
    # easy-biologic's GEIS.__init__ defaults: {"vs_initial": False,
    # "vs_final": False, "potential_interval": 0.001, "correction": False}.
    # time_interval, sweep, repeat, and wait are all supplied by the endpoint
    # (AcqInterval__s, SweepMode, Repeats, DelayFraction); vs_final is derived
    # from vs_initial in the build, same as PEIS.
    defaults={
        "vs_initial": False,
        "Correction": False,
        "AcqInterval__V": 0.001,
    },
    build=_build_geis,
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
    x.technique_name: x
    for x in [TECH_OCV, TECH_CA, TECH_CP, TECH_CV, TECH_PEIS, TECH_GEIS]
}


LoadStep = NamedTuple(
    "LoadStep", [("ecc_stem", str), ("tech_id", int), ("params", list)]
)


@dataclass
class LoadPlan:
    """The ordered technique list to load onto one channel.

    EClib1 has no unload: `BL_LoadTechnique(..., first=True)` is what clears a
    channel, and `last=True` closes the list. The driver derives both from a
    step's position here rather than from the caller.
    """

    steps: list[LoadStep]

    @property
    def tech_ids(self) -> list[int]:
        return [step.tech_id for step in self.steps]


#: Trigger In / Trigger Out, PDF sections 7.32 and 7.33. Not calls -- techniques,
#: which is why they need `.ecc` files and a slot in the load order.
TECH_TI = BiologicTechnique(
    technique_name="TI",
    ecc_stem="TI",
    tech_id=vendor.TECH_ID.TI,
    param_table={"Trigger_Logic": Param("Trigger_Logic", "int", 1)},
    defaults={},
    build=lambda p: {"Trigger_Logic": p["ttl_logic"]},
)

TECH_TO = BiologicTechnique(
    technique_name="TO",
    ecc_stem="TO",
    tech_id=vendor.TECH_ID.TO,
    param_table={
        "Trigger_Logic": Param("Trigger_Logic", "int", 1),
        "Trigger_Duration": Param("Trigger_Duration", "float", 1),
    },
    defaults={},
    build=lambda p: {
        "Trigger_Logic": p["ttl_logic"],
        "Trigger_Duration": p["ttl_duration"],
    },
)

TTL_TECHS = {"in": TECH_TI, "out": TECH_TO}


def plan_for(
    technique: "BiologicTechnique | PlanTechnique",
    action_params: dict,
    ttl_params: dict | None = None,
):
    """The load order for one technique, with a trigger ahead of it if asked.

    A `PlanTechnique` (multi-technique plan) is dispatched to its own
    `expand`, which builds the trigger itself rather than going through the
    single-technique path below.
    """
    if isinstance(technique, PlanTechnique):
        return technique.expand(action_params, ttl_params)
    steps: list[LoadStep] = []
    mode = (ttl_params or {}).get("ttl", "none")
    if mode != "none":
        try:
            trigger = TTL_TECHS[mode]
        except KeyError:
            raise TechniqueError(
                f"unknown ttl mode {mode!r}; expected 'none', 'in' or 'out'"
            )
        steps.append(
            LoadStep(
                trigger.ecc_stem, trigger.tech_id, entries(trigger, ttl_params or {})
            )
        )
    steps.append(
        LoadStep(
            technique.ecc_stem, technique.tech_id, entries(technique, action_params)
        )
    )
    return LoadPlan(steps)


PlanEntry = NamedTuple("PlanEntry", [("name", str), ("params", dict)])
PlanLoop = NamedTuple("PlanLoop", [("start", int), ("end", int), ("n", int)])

TECH_LOOP = BiologicTechnique(
    technique_name="LOOP",
    ecc_stem="loop",
    tech_id=vendor.TECH_ID.LOOP,
    param_table={
        "loop_N_times": Param("loop_N_times", "int", 1),
        "protocol_number": Param("protocol_number", "int", 1),
    },
    defaults={},
    build=lambda p: {
        "loop_N_times": p["loop_N_times"],
        "protocol_number": p["protocol_number"],
    },
)


def sub_steps(entry: "PlanEntry") -> list[LoadStep]:
    """The loaded steps for one plan entry.

    A plain technique loads as its own single step; Task 11 extends this for
    the two-technique CAOCV entry.
    """
    try:
        technique = BIOTECHS[entry.name]
    except KeyError:
        raise TechniqueError(f"{entry.name!r} is not a known technique")
    merged = {**technique.defaults, **entry.params}
    return plan_for(technique, merged, None).steps


@dataclass
class PlanTechnique:
    """Several techniques on one channel as a single loaded experiment.

    `technique_name` is `"PLAN"` so `data.decode` is called per *segment* with
    the name of whatever technique that segment came from -- the driver reads
    `DataInfo.TechniqueID` and looks the name up, rather than assuming one
    technique for the whole action.
    """

    technique_name: str
    plan_entries: list[PlanEntry]
    loops: list[PlanLoop]

    @property
    def column_plan(self) -> tuple[str, ...]:
        seen: list[str] = []
        for entry in self.plan_entries:
            for column in data.COLUMNS[entry.name]:
                if column not in seen:
                    seen.append(column)
        return tuple(seen)

    def expand(self, action_params: dict, ttl_params=None) -> LoadPlan:
        """Build the flattened, LOOP-inserted load order.

        `action_params` is unused by a plain multi-entry plan -- each
        `PlanEntry` already carries its own params -- but is part of the
        signature so a per-action expander shares this one dispatch instead
        of growing a second path. A `PlanTechnique` subclass whose entries
        are derived from the live action params at call time (Task 11's
        CAOCV, which splits flat `CA_*`/`OCV_*` keys into two techniques)
        overrides `expand` and reads it.
        """
        if not self.plan_entries:
            raise TechniqueError("plan is empty")

        n_entries = len(self.plan_entries)
        for span in self.loops:
            if not (0 <= span.start <= span.end < n_entries):
                raise TechniqueError(
                    f"loop span ({span.start}, {span.end}) out of range for "
                    f"{n_entries} plan entries"
                )
            if span.n == -1:
                raise TechniqueError(
                    "loop_N_times must be >= 1; -1 is the PDF's unlimited "
                    "goto and would never terminate"
                )
            if span.n < 1:
                raise TechniqueError(f"loop_N_times must be >= 1, got {span.n}")

        sorted_spans = sorted(self.loops, key=lambda s: s.start)
        for i, a in enumerate(sorted_spans):
            for b in sorted_spans[i + 1 :]:
                if b.start > a.end:
                    continue
                # a and b overlap (they share at least one entry) -- one
                # must contain the other. Sorting by start alone does not
                # order containment when two spans share a start (e.g.
                # (0, 2) and (0, 4)): either can be the larger one, so both
                # directions must be checked.
                a_contains_b = a.start <= b.start and b.end <= a.end
                b_contains_a = b.start <= a.start and a.end <= b.end
                if not (a_contains_b or b_contains_a):
                    raise TechniqueError(
                        "loop spans must nest, not straddle: "
                        f"({a.start}, {a.end}) vs ({b.start}, {b.end})"
                    )

        # Group spans by the entry they close on. Ties (two spans closing on
        # the same entry, which validation above forces to be nested rather
        # than merely coincident) are emitted innermost first, so an inner
        # LOOP precedes the outer one that wraps it.
        spans_by_end: dict[int, list[PlanLoop]] = {}
        for span in self.loops:
            spans_by_end.setdefault(span.end, []).append(span)
        for spans in spans_by_end.values():
            spans.sort(key=lambda s: (s.end - s.start, -s.start))

        # A single append-only pass, entries in order. `protocol_number` for
        # a span is read from `first_loaded[span.start]` at the moment the
        # span's *end* entry finishes -- and since `start <= end` and entries
        # are walked in order, `first_loaded[span.start]` was fixed on an
        # earlier (or this) iteration and is never touched again, because
        # nothing is ever inserted before the current write position. That
        # is what the shift-and-patch version above got wrong: a LOOP
        # inserted for one span could still slide a *later* span's already
        # -captured `first_loaded` out from under it, which is exactly what
        # happened to two independent (non-nested) spans -- the first LOOP's
        # insertion shifted every following index, but the second span's
        # `protocol_number` had already been read from the pre-shift
        # position and was never revised. Building strictly left-to-right,
        # inserting a LOOP only once its target position is permanent,
        # removes the possibility of that class of bug rather than patching
        # this one instance of it.
        steps: list[LoadStep] = []
        mode = (ttl_params or {}).get("ttl", "none")
        if mode != "none":
            try:
                trigger = TTL_TECHS[mode]
            except KeyError:
                raise TechniqueError(
                    f"unknown ttl mode {mode!r}; expected 'none', 'in' or 'out'"
                )
            steps.append(
                LoadStep(
                    trigger.ecc_stem,
                    trigger.tech_id,
                    entries(trigger, ttl_params or {}),
                )
            )

        first_loaded: list[int] = [0] * n_entries
        for i, entry in enumerate(self.plan_entries):
            first_loaded[i] = len(steps)
            steps.extend(sub_steps(entry))
            for span in spans_by_end.get(i, []):
                steps.append(
                    LoadStep(
                        TECH_LOOP.ecc_stem,
                        TECH_LOOP.tech_id,
                        entries(
                            TECH_LOOP,
                            {
                                "loop_N_times": span.n,
                                "protocol_number": first_loaded[span.start],
                            },
                        ),
                    )
                )

        return LoadPlan(steps)


def plan_technique(entries: list[PlanEntry], loops: list[PlanLoop]) -> PlanTechnique:
    if not entries:
        raise TechniqueError("plan is empty")
    return PlanTechnique("PLAN", entries, loops)


#: `CA_`/`OCV_`-prefixed action key -> the sub-technique's own key.
_CAOCV_RENAME = {"Vval__V_list": "Vval__V", "Tval__s_list": "Tval__s"}


def caocv_sub_params(p: dict) -> tuple[dict, dict]:
    """Split CAOCV's flat action params into a CA dict and an OCV dict.

    The two `_list` keys are renamed because the CA build takes `Vval__V` and
    `Tval__s` whether they are scalars or lists; everything else keeps its
    name with the prefix removed. Each half starts from its own technique's
    `defaults`, so the interval defaults Task 7 pinned to four stations'
    archives still apply to whatever the flat CAOCV params don't override.
    """

    def strip(prefix, defaults):
        out = dict(defaults)
        for key, value in p.items():
            if key.startswith(prefix):
                bare = key[len(prefix) :]
                out[_CAOCV_RENAME.get(bare, bare)] = value
        return out

    return (
        strip("CA_", BIOTECHS["CA"].defaults),
        strip("OCV_", BIOTECHS["OCV"].defaults),
    )


@dataclass
class CaocvTechnique(PlanTechnique):
    """CA followed by OCV, loaded together as one experiment.

    Its two techniques come from splitting one flat `CA_`/`OCV_`-prefixed
    action-param dict at call time (`caocv_sub_params`), not from a list of
    pre-built `PlanEntry`s -- so `expand` is overridden outright instead of
    being driven by `plan_entries`/`loops` (both left empty), and
    `column_plan` reads `data.COLUMNS["CAOCV"]` (the frozen DC set) directly
    instead of unioning per-entry columns.

    The trigger block in `expand` below duplicates `PlanTechnique.expand`'s
    (itself already duplicated once in `plan_for`) rather than extracting a
    shared helper: `PlanTechnique.expand`'s body is out of scope for this
    task, so there is nothing existing to call into.
    """

    defaults: dict[str, Any] = field(default_factory=dict)

    def expand(self, action_params: dict, ttl_params=None) -> LoadPlan:
        steps: list[LoadStep] = []
        mode = (ttl_params or {}).get("ttl", "none")
        if mode != "none":
            try:
                trigger = TTL_TECHS[mode]
            except KeyError:
                raise TechniqueError(
                    f"unknown ttl mode {mode!r}; expected 'none', 'in' or 'out'"
                )
            steps.append(
                LoadStep(
                    trigger.ecc_stem,
                    trigger.tech_id,
                    entries(trigger, ttl_params or {}),
                )
            )
        ca_params, ocv_params = caocv_sub_params(action_params)
        steps.append(
            LoadStep(
                BIOTECHS["CA"].ecc_stem,
                BIOTECHS["CA"].tech_id,
                entries(BIOTECHS["CA"], ca_params),
            )
        )
        steps.append(
            LoadStep(
                BIOTECHS["OCV"].ecc_stem,
                BIOTECHS["OCV"].tech_id,
                entries(BIOTECHS["OCV"], ocv_params),
            )
        )
        return LoadPlan(steps)

    @property
    def column_plan(self) -> tuple[str, ...]:
        return tuple(data.COLUMNS["CAOCV"])


#: `CaocvTechnique` is a `PlanTechnique`, not a `BiologicTechnique` -- it
#: expands to two loaded techniques -- so it does not fit `BIOTECHS`'s
#: declared value type. `sub_steps`/`plan_for`'s `isinstance(technique,
#: PlanTechnique)` dispatch is what actually routes it correctly at runtime;
#: this registration is the one place that dispatch's target type is wider
#: than the dict's annotation says.
BIOTECHS["CAOCV"] = CaocvTechnique(  # type: ignore[assignment]
    technique_name="CAOCV", plan_entries=[], loops=[]
)
