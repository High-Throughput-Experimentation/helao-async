"""Build an ordered EClib2 technique plan from HELAO action parameters.

The plan is declarative -- parameter *names* and plain values, no SDK objects --
so the whole mapping is unit-testable without the vendor package, and
:mod:`sdk_client` reduces to an interpreter over it.

A plan holds a *list* of techniques because two of the seven HELAO techniques
are not single EClib2 techniques:

- **PEIS/GEIS** are sweep-only in EClib2. There is no DC potential or current
  parameter, and no ``Duration``/``record_every_dT``: the technique docs say to
  "run a CA technique just before the PEIS", and the vendor's own PEIS example
  does exactly that. So the EClib1 keys ``Vinit__V``/``Iinit__A``,
  ``Duration__s`` and ``AcqInterval__s`` build a preceding CA/CP leg, which is
  also what restores the ``process`` column EClib1 emitted.
- **CAOCV** was an easy-biologic composite, never a vendor technique. It
  becomes CA then OCV.

Parameter names here were taken from ``Python/Constants/bl_constants.py``, not
from the technique doc tables, which disagree with the shipped enums in three
places: ``RECORD_EVERY_DT_MODE`` is really ``RECORD_EVERY_DT_ARRAY_MODE``, the
OCV/CV record triggers are float *arrays* rather than scalars, and GEIS's
current amplitude is ``AMPLITUDE_CURRENT_IN_AMP`` rather than the table's
``EC_SDK_ANALOG_GAIN`` (which is not a member of anything).
"""

from dataclasses import dataclass
from typing import Any

from helao.deploy.hte.drivers.pstat.biologic_eclib2 import data as ec2data
from helao.deploy.hte.drivers.pstat.biologic_eclib2 import enum as ec2enum

#: Setter kinds, one per ``BL_Set*Parameter`` entry point.
PARAM_KINDS: tuple[str, ...] = (
    "float",
    "float_array",
    "int",
    "bool",
    "enum",
    "enum_array",
)

#: Which ``BL_ProcessRawTo*Data`` + :mod:`data` mapper reads a technique's rows.
READERS: tuple[str, ...] = ("ocv", "step", "eis")

READER_BY_IDENTIFIER: dict[str, str] = {
    "EC_SDK_TECHNIQUE_OCV": "ocv",
    "EC_SDK_TECHNIQUE_CA": "step",
    "EC_SDK_TECHNIQUE_CP": "step",
    "EC_SDK_TECHNIQUE_CV": "step",
    "EC_SDK_TECHNIQUE_PEIS": "eis",
    "EC_SDK_TECHNIQUE_GEIS": "eis",
}

TECHNIQUE_NAMES: tuple[str, ...] = ("OCV", "CA", "CP", "CV", "PEIS", "GEIS", "CAOCV")

SWEEP_MODES: dict[str, str] = {
    "log": "EC_SDK_SWEEP_LOG",
    "lin": "EC_SDK_SWEEP_LINEAR",
    "LOG": "EC_SDK_SWEEP_LOG",
    "LINEAR": "EC_SDK_SWEEP_LINEAR",
}

#: EClib1 exposed no current-averaging window on CV. These are the vendor CV
#: example's values, used so the default is a documented number rather than an
#: accident; override with ``BeginMeasuringI``/``EndMeasuringI``.
CV_DEFAULT_BEGIN_MEASURING_I = 0.5
CV_DEFAULT_END_MEASURING_I = 1.0

#: CV has exactly four scans (Ei->E1, E1->E2, E2->E1, E2->Ef). The CV parameter
#: table does not list ``SCAN_NUMBER`` at all, but the vendor CV example sets it
#: to 2; mirrored verbatim rather than derived, since nothing documents the
#: relation. Confirm against a real channel at the station gate.
CV_SCAN_NUMBER = 2


@dataclass(frozen=True)
class ParamSet:
    """One ``BL_Set*Parameter`` call.

    Attributes:
        kind: One of :data:`PARAM_KINDS`, selecting the entry point.
        name: Member name in the matching vendor parameter enum.
        value: Plain Python value. For ``enum``/``enum_array`` kinds this is a
            member *name* (or list of names), resolved by the vendor loader.
    """

    kind: str
    name: str
    value: Any


@dataclass(frozen=True)
class TechniquePlan:
    """One technique to add to the experiment, with everything it needs set.

    Attributes:
        identifier: ``TechniqueIdentifier`` member name.
        reader: Which :mod:`data` mapper reads its rows.
        params: Parameter setter calls, in the order to make them.
        irange: ``(IRangeMode, IRangeValue)`` member names, or None to leave
            the channel as it is.
        erange: ``ERangeValue`` member name, or None.
        bandwidth: ``BandwidthValue`` member name, or None.
    """

    identifier: str
    reader: str
    params: tuple[ParamSet, ...]
    irange: tuple[str, str] | None = None
    erange: str | None = None
    bandwidth: str | None = None


@dataclass(frozen=True)
class ActionPlan:
    """Everything one HELAO action asks of a channel.

    Attributes:
        technique_name: The HELAO technique caption (e.g. ``"PEIS"``).
        techniques: Techniques to add, in execution order.
        columns: The emitted column contract for the whole action.
    """

    technique_name: str
    techniques: tuple[TechniquePlan, ...]
    columns: tuple[str, ...]


# ---------------------------------------------------------------------------
# parameter plumbing
# ---------------------------------------------------------------------------


def _require(params: dict, key: str) -> Any:
    """Fetch a required parameter, naming it if absent.

    Defaulting a missing physical parameter would run the cell to a value
    nobody asked for and record it as if they had.
    """
    if key not in params or params[key] is None:
        raise ValueError(
            f"{key} is required for this technique; got keys {sorted(params)}"
        )
    return params[key]


def _as_list(value: Any) -> list:
    """Normalize a scalar-or-list action parameter to a list."""
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _sweep_mode(caption: Any) -> str:
    try:
        return SWEEP_MODES[caption]
    except (KeyError, TypeError):
        raise ValueError(
            f"unknown sweep mode {caption!r}; choose from {sorted(set(SWEEP_MODES))}"
        ) from None


def _ranges(
    params: dict, prefix: str = ""
) -> tuple[tuple[str, str] | None, str | None, str | None]:
    """Coerce the optional IRange/ERange/Bandwidth trio, if the action set them.

    Absent means "leave the channel alone", matching what EClib1 did with a
    KEEP value.
    """
    irange = params.get(f"{prefix}IRange")
    erange = params.get(f"{prefix}ERange")
    bandwidth = params.get(f"{prefix}Bandwidth")
    return (
        ec2enum.irange_plan(irange) if irange is not None else None,
        ec2enum.erange_name(erange) if erange is not None else None,
        ec2enum.bandwidth_name(bandwidth) if bandwidth is not None else None,
    )


def _record_every(
    name: str, mode_name: str, value: Any, n_steps: int
) -> list[ParamSet]:
    """A record trigger plus the flag saying whether it is per-step.

    One value covers every step (array mode off); one value per step turns
    array mode on. Anything else is neither, and would be silently truncated
    by the firmware.
    """
    values = _as_list(value)
    if len(values) == 1:
        per_step = False
    elif len(values) == n_steps:
        per_step = True
    else:
        raise ValueError(
            f"{name} needs either 1 value or one per step ({n_steps}), "
            f"got {len(values)}"
        )
    return [
        ParamSet("float_array", name, values),
        ParamSet("bool", mode_name, per_step),
    ]


def _steps(
    params: dict,
    *,
    level_key: str,
    level_name: str,
    duration_key: str,
    vs_initial: str,
) -> tuple[list[ParamSet], int]:
    """The shared CA/CP step block: levels, durations, count, and vs-initial."""
    levels = _as_list(_require(params, level_key))
    durations = _as_list(_require(params, duration_key))
    if len(levels) != len(durations):
        raise ValueError(
            f"{level_key} and {duration_key} must be the same length; "
            f"got {len(levels)} and {len(durations)}"
        )
    n = len(levels)
    return (
        [
            ParamSet("float_array", level_name, levels),
            ParamSet("float_array", "EC_SDK_DURATION_STEP_IN_S", durations),
            # "Number of step minus 1", per the CA/CP parameter tables.
            ParamSet("int", "EC_SDK_STEP_NUMBER", n - 1),
            ParamSet("enum_array", "EC_SDK_VS_INITIAL", [vs_initial] * n),
        ],
        n,
    )


# ---------------------------------------------------------------------------
# per-technique builders
# ---------------------------------------------------------------------------


def _ocv_technique(
    params: dict, *, time_key: str, dt_key: str, de_key: str
) -> TechniquePlan:
    return TechniquePlan(
        identifier="EC_SDK_TECHNIQUE_OCV",
        reader="ocv",
        params=(
            ParamSet("float", "EC_SDK_REST_TIME_IN_S", _require(params, time_key)),
            # Float arrays in the shipped enums, despite the doc table.
            ParamSet(
                "float_array",
                "EC_SDK_RECORD_EVERY_DT",
                _as_list(_require(params, dt_key)),
            ),
            ParamSet(
                "float_array",
                "EC_SDK_RECORD_EVERY_DE",
                _as_list(_require(params, de_key)),
            ),
        ),
    )


def _ca_technique(
    params: dict,
    *,
    level_key: str,
    duration_key: str,
    dt_key: str,
    di_key: str,
    prefix: str = "",
    cycles: int = 0,
) -> TechniquePlan:
    block, n = _steps(
        params,
        level_key=level_key,
        level_name="EC_SDK_VOLTAGE_STEP_IN_V",
        duration_key=duration_key,
        vs_initial="EC_SDK_VS_EREF",
    )
    block += _record_every(
        "EC_SDK_RECORD_EVERY_DT",
        "EC_SDK_RECORD_EVERY_DT_ARRAY_MODE",
        _require(params, dt_key),
        n,
    )
    block += _record_every(
        "EC_SDK_RECORD_EVERY_DI",
        "EC_SDK_RECORD_EVERY_DI_ARRAY_MODE",
        _require(params, di_key),
        n,
    )
    block.append(ParamSet("int", "EC_SDK_N_CYCLES", cycles))
    irange, erange, bandwidth = _ranges(params, prefix)
    return TechniquePlan(
        identifier="EC_SDK_TECHNIQUE_CA",
        reader="step",
        params=tuple(block),
        irange=irange,
        erange=erange,
        bandwidth=bandwidth,
    )


def _cp_technique(
    params: dict,
    *,
    level_key: str,
    duration_key: str,
    dt_key: str,
    de_key: str,
    cycles: int = 0,
) -> TechniquePlan:
    block, n = _steps(
        params,
        level_key=level_key,
        level_name="EC_SDK_CURRENT_STEP_IN_A",
        duration_key=duration_key,
        vs_initial="EC_SDK_VS_IREF",
    )
    block += _record_every(
        "EC_SDK_RECORD_EVERY_DT",
        "EC_SDK_RECORD_EVERY_DT_ARRAY_MODE",
        _require(params, dt_key),
        n,
    )
    block += _record_every(
        "EC_SDK_RECORD_EVERY_DE",
        "EC_SDK_RECORD_EVERY_DE_ARRAY_MODE",
        _require(params, de_key),
        n,
    )
    block.append(ParamSet("int", "EC_SDK_N_CYCLES", cycles))
    irange, erange, bandwidth = _ranges(params)
    return TechniquePlan(
        identifier="EC_SDK_TECHNIQUE_CP",
        reader="step",
        params=tuple(block),
        irange=irange,
        erange=erange,
        bandwidth=bandwidth,
    )


def _cv_technique(params: dict) -> TechniquePlan:
    # EClib1 carried four scalars; EClib2 wants one array in [Ei, E1, E2, Ef]
    # order, and a scan rate per phase.
    voltages = [
        _require(params, "Vinit__V"),
        _require(params, "Vapex1__V"),
        _require(params, "Vapex2__V"),
        _require(params, "Vfinal__V"),
    ]
    rate = _as_list(_require(params, "ScanRate__V_s"))
    if len(rate) == 1:
        rate = rate * 4
    elif len(rate) != 4:
        raise ValueError(
            f"ScanRate__V_s needs 1 value or one per phase (4), got {len(rate)}"
        )
    irange, erange, bandwidth = _ranges(params)
    return TechniquePlan(
        identifier="EC_SDK_TECHNIQUE_CV",
        reader="step",
        params=(
            ParamSet("float_array", "EC_SDK_VOLTAGE_STEP_IN_V", voltages),
            ParamSet("enum_array", "EC_SDK_VS_INITIAL", ["EC_SDK_VS_EREF"] * 4),
            ParamSet("float_array", "EC_SDK_SCAN_RATE_IN_V_PER_S", rate),
            ParamSet("int", "EC_SDK_SCAN_NUMBER", CV_SCAN_NUMBER),
            ParamSet(
                "float_array",
                "EC_SDK_RECORD_EVERY_DE",
                _as_list(_require(params, "AcqInterval__V")),
            ),
            ParamSet(
                "bool",
                "EC_SDK_ENABLE_AVERAGE_EVERY_DE",
                bool(params.get("AverageOverDE", False)),
            ),
            ParamSet("int", "EC_SDK_N_CYCLES", int(_require(params, "Cycles"))),
            ParamSet(
                "float",
                "EC_SDK_BEGIN_MEASURING_I",
                params.get("BeginMeasuringI", CV_DEFAULT_BEGIN_MEASURING_I),
            ),
            ParamSet(
                "float",
                "EC_SDK_END_MEASURING_I",
                params.get("EndMeasuringI", CV_DEFAULT_END_MEASURING_I),
            ),
        ),
        irange=irange,
        erange=erange,
        bandwidth=bandwidth,
    )


def _eis_technique(params: dict, *, identifier: str) -> TechniquePlan:
    """The PEIS or GEIS sweep itself, which differ only in the amplitude field."""
    if identifier == "EC_SDK_TECHNIQUE_PEIS":
        amplitude = ParamSet(
            "float",
            "EC_SDK_AMPLITUDE_VOLTAGE_IN_V",
            _require(params, "Vamp__V"),
        )
    else:
        # Not EC_SDK_ANALOG_GAIN, whatever the GEIS doc table says.
        amplitude = ParamSet(
            "float",
            "EC_SDK_AMPLITUDE_CURRENT_IN_AMP",
            _require(params, "Iamp__A"),
        )
    irange, erange, bandwidth = _ranges(params)
    return TechniquePlan(
        identifier=identifier,
        reader="eis",
        params=(
            ParamSet(
                "float",
                "EC_SDK_INITIAL_FREQUENCY_IN_HZ",
                _require(params, "Finit__Hz"),
            ),
            ParamSet(
                "float", "EC_SDK_FINAL_FREQUENCY_IN_HZ", _require(params, "Ffinal__Hz")
            ),
            ParamSet("enum", "EC_SDK_SWEEP_MODE", _sweep_mode(params.get("SweepMode"))),
            amplitude,
            ParamSet(
                "int",
                "EC_SDK_FREQUENCY_NUMBER",
                int(_require(params, "FrequencyNumber")),
            ),
            # EClib1 called these Repeats and DelayFraction.
            ParamSet("int", "EC_SDK_AVERAGE_N_TIMES", int(_require(params, "Repeats"))),
            ParamSet(
                "float",
                "EC_SDK_WAIT_FOR_STEADY_IN_SINE_PERIOD",
                _require(params, "DelayFraction"),
            ),
            ParamSet(
                "bool",
                "EC_SDK_ENABLE_DRIFT_CORRECTION",
                bool(params.get("DriftCorrection", False)),
            ),
        ),
        irange=irange,
        erange=erange,
        bandwidth=bandwidth,
    )


# ---------------------------------------------------------------------------
# plan builders
# ---------------------------------------------------------------------------


def _plan_ocv(params: dict) -> ActionPlan:
    return ActionPlan(
        technique_name="OCV",
        techniques=(
            _ocv_technique(
                params,
                time_key="Tval__s",
                dt_key="AcqInterval__s",
                de_key="AcqInterval__V",
            ),
        ),
        columns=ec2data.OCV_COLUMNS,
    )


def _plan_ca(params: dict) -> ActionPlan:
    return ActionPlan(
        technique_name="CA",
        techniques=(
            _ca_technique(
                params,
                level_key="Vval__V",
                duration_key="Tval__s",
                dt_key="AcqInterval__s",
                di_key="AcqInterval__A",
            ),
        ),
        columns=ec2data.STEP_COLUMNS,
    )


def _plan_cp(params: dict) -> ActionPlan:
    return ActionPlan(
        technique_name="CP",
        techniques=(
            _cp_technique(
                params,
                level_key="Ival__A",
                duration_key="Tval__s",
                dt_key="AcqInterval__s",
                de_key="AcqInterval__V",
            ),
        ),
        columns=ec2data.STEP_COLUMNS,
    )


def _plan_cv(params: dict) -> ActionPlan:
    return ActionPlan(
        technique_name="CV",
        techniques=(_cv_technique(params),),
        columns=ec2data.STEP_COLUMNS,
    )


def _plan_peis(params: dict) -> ActionPlan:
    # The bias leg carries EClib1's Vinit__V / Duration__s / AcqInterval__s,
    # which have no home on an EClib2 PEIS. AcqInterval__A is not part of the
    # EClib1 PEIS surface, so the current record trigger is left wide: dt alone
    # decides the density of the time-domain leg.
    bias = _ca_technique(
        {**params, "_di": _EIS_BIAS_WIDE_DI},
        level_key="Vinit__V",
        duration_key="Duration__s",
        dt_key="AcqInterval__s",
        di_key="_di",
    )
    return ActionPlan(
        technique_name="PEIS",
        techniques=(bias, _eis_technique(params, identifier="EC_SDK_TECHNIQUE_PEIS")),
        columns=ec2data.EIS_COLUMNS,
    )


def _plan_geis(params: dict) -> ActionPlan:
    bias = _cp_technique(
        {**params, "_de": _EIS_BIAS_WIDE_DE},
        level_key="Iinit__A",
        duration_key="Duration__s",
        dt_key="AcqInterval__s",
        de_key="_de",
    )
    return ActionPlan(
        technique_name="GEIS",
        techniques=(bias, _eis_technique(params, identifier="EC_SDK_TECHNIQUE_GEIS")),
        columns=ec2data.EIS_COLUMNS,
    )


def _plan_caocv(params: dict) -> ActionPlan:
    ca = _ca_technique(
        params,
        level_key="CA_Vval__V_list",
        duration_key="CA_Tval__s_list",
        dt_key="CA_AcqInterval__s",
        di_key="CA_AcqInterval__A",
        prefix="CA_",
    )
    # No ranges on the OCV leg: OCV disconnects the cell from the amplifier, so
    # a current or voltage range there is meaningless. CAOCV's keys are
    # CA-prefixed for the same reason.
    ocv = _ocv_technique(
        params,
        time_key="OCV_Tval__s",
        dt_key="OCV_AcqInterval__s",
        de_key="OCV_AcqInterval__V",
    )
    return ActionPlan(
        technique_name="CAOCV",
        techniques=(ca, ocv),
        columns=ec2data.STEP_COLUMNS,
    )


#: An EIS bias leg records on time alone. These stand in for the per-step
#: current/voltage record triggers the firmware requires but the EClib1 EIS
#: parameter surface never exposed; they are far outside any real signal, so
#: they never trigger a record on their own.
_EIS_BIAS_WIDE_DI = 1e3
_EIS_BIAS_WIDE_DE = 1e3


_BUILDERS = {
    "OCV": _plan_ocv,
    "CA": _plan_ca,
    "CP": _plan_cp,
    "CV": _plan_cv,
    "PEIS": _plan_peis,
    "GEIS": _plan_geis,
    "CAOCV": _plan_caocv,
}


def build_plan(technique_name: str, params: dict) -> ActionPlan:
    """Turn a HELAO technique name and action params into an :class:`ActionPlan`.

    Args:
        technique_name: One of :data:`TECHNIQUE_NAMES`.
        params: The action's parameters, keyed as the EClib1 backend's
            ``parameter_map`` keys them.

    Returns:
        The techniques to add to the experiment, in order, plus the column
        contract the action emits.

    Raises:
        ValueError: On an unknown technique, an unknown enum caption, a missing
            required parameter, or inconsistent array lengths.
    """
    try:
        builder = _BUILDERS[technique_name]
    except KeyError:
        raise ValueError(
            f"unknown technique {technique_name!r}; choose from {sorted(TECHNIQUE_NAMES)}"
        ) from None
    return builder(params)
