"""What each technique needs: a template, a parameter map, a column plan.

Two mappings live here and both are silent when wrong.

* **Parameter map** -- HELAO action key to ``.mps`` parameter caption. A wrong
  or missing caption patches nothing, so the template's own default runs on a
  real cell with no error from EC-Lab or from the API.
* **Column plan** -- emitted HELAO column to EC-Lab variable code (appendix
  7.2 of the OLE COM manual). A wrong code returns a different quantity under
  the right column name.

Technique codes come from appendix 7.1, which lists most techniques **twice**
under two families -- CA is 24 and 54, OCV 11 and 55, and so on. Which one a
template yields depends on the template, so both are accepted and the driver
checks membership after ``LoadSettings`` rather than equality.

The emitted column set must equal the sibling ``biologic/technique.py``
registry's ``field_map`` values; ``test_ole_technique.py`` and
``test_biologic_column_contract.py`` both pin that.
"""

from dataclasses import dataclass, field
from typing import Literal, Optional

__all__ = [
    "BANDWIDTH_VALUES",
    "ColumnPlan",
    "DC_COLUMNS",
    "EIS_COLUMNS",
    "ERANGE_VOLTS",
    "MpsParam",
    "OLE_TECHS",
    "OleTechnique",
    "SPACING_VALUES",
    "UNIT_PREFIXES",
    "IRANGE_VALUES",
    "VAR_CODES",
    "columns",
    "erange_rows",
    "format_value",
    "irange_value",
    "resolve",
    "scale_to_unit",
    "spacing_value",
]

#: EC-Lab variable codes, appendix 7.2, keyed by the HELAO column they fill.
VAR_CODES: dict[str, int] = {
    "t_s": 4,
    "Ewe_V": 6,
    "I_A": 8,
    "Ece_V": 9,
    "cycle": 24,
    "f_Hz": 32,
    "AbsEwe_V": 33,
    "AbsI_A": 34,
    "phase": 35,
    "modulus": 36,
    "P_W": 70,
    "AbsEce_V": 96,
    "AbsIce_A": 97,
    "phase_ce": 98,
    "modulus_ce": 99,
}


@dataclass(frozen=True)
class MpsParam:
    """One HELAO parameter's landing place in an ``.mps`` file.

    Attributes:
        param_id: The parameter's caption -- its label in the ``.mps`` table,
            and the ``ParamID`` ``ModifyOnTheFly`` would take.
        unit_param_id: Caption of the companion unit row. EC-Lab spells a
            current, charge or frequency as a magnitude row plus a unit row,
            and formats every number to three decimals -- so a 1 uA setpoint
            written unscaled lands as ``0.000``. Set together with
            ``base_unit``; the driver then calls ``scale_to_unit``.
        base_unit: The unscaled unit symbol (``"A"``, ``"Hz"``). Its presence
            is what selects the scale-and-unit path over ``fmt``.
        fmt: How to render the value when there is no unit row. A
            ``str.format`` spec, or one of the sentinels ``"hms"`` (EC-Lab's
            ``h:mm:s.ffff``), ``"bandwidth"`` (the bare integer 1-9),
            ``"V_to_mV"`` (a volts parameter landing in a millivolts row), or
            ``"spacing"`` (a sweep mode as "Linear"/"Logarithmic").
        technique: Which technique block the row lives in, 0-based, for
            multi-technique templates. ``None`` means the first match
            anywhere. CAOCV needs it: its template holds a CA block and an
            OCV block, and both carry ``E range min (V)``.
    """

    param_id: str
    unit_param_id: Optional[str] = None
    base_unit: Optional[str] = None
    fmt: str = "{}"
    technique: Optional[int] = None


@dataclass(frozen=True)
class ColumnPlan:
    """How one technique's emitted columns are obtained.

    Attributes:
        kind: ``"dc"`` reads via ``MeasureDcValue``, ``"eis"`` via
            ``MeasureEisValue``. The two return different tuples and an EIS
            file read as DC yields plausible-looking nonsense.
        var_codes: Columns fetched one at a time with ``MeasureValueByCode``.
        derived: Columns computed rather than fetched -- see ``mpr_cursor``.
    """

    kind: Literal["dc", "eis"]
    var_codes: dict[str, int] = field(default_factory=dict)
    derived: tuple[str, ...] = ()


@dataclass(frozen=True)
class OleTechnique:
    """Everything the driver needs to run one technique through EC-Lab."""

    technique_name: str
    template: str
    parameter_map: dict[str, MpsParam]
    column_plan: ColumnPlan
    technique_codes: frozenset[int]


def columns(plan: ColumnPlan) -> tuple[str, ...]:
    """Every column this plan produces, fetched and derived alike.

    ``MeasureDcValue`` supplies ``t_s``/``Ewe_V``/``I_A`` and
    ``MeasureEisValue`` supplies ``t_s``/``f_Hz`` plus the impedance pair, so
    those arrive without a ``var_codes`` entry; they are listed in ``derived``
    to keep this function the single answer to "what does this technique
    emit".
    """
    return tuple(dict.fromkeys((*plan.var_codes, *plan.derived)))


#: Columns every DC technique but OCV emits.
DC_COLUMNS = ("t_s", "Ewe_V", "I_A", "P_W", "cycle")

#: Columns both EIS techniques emit.
EIS_COLUMNS = (
    "process",
    "t_s",
    "Ewe_V",
    "I_A",
    "AbsEwe_V",
    "AbsI_A",
    "phase",
    "modulus",
    "Ece_V",
    "AbsEce_V",
    "AbsIce_A",
    "phase_ce",
    "modulus_ce",
    "f_Hz",
    "X_ohm",
    "R_ohm",
)


def _dc_plan() -> ColumnPlan:
    """``MeasureDcValue`` gives t/Ewe/I; P_W and cycle are derived.

    ``P_W`` is fetched-equivalent, not approximated: EC-Lab defines variable 70
    as ``|Ewe * I|``. ``cycle`` comes from status index 10 at poll time.
    """
    return ColumnPlan(kind="dc", derived=("t_s", "Ewe_V", "I_A", "P_W", "cycle"))


def _eis_plan() -> ColumnPlan:
    """``MeasureEisValue`` gives t/f/Re/-Im; the rest come by code.

    ``R_ohm`` is ``Re(Z)`` and ``X_ohm`` is the manual's "imaginary part",
    which section 5.2.14 states is already ``-Im(Z)`` -- exactly what the eclib
    path computes as ``-modulus * sin(phase)``. ``process`` is reconstructed
    from the frequency: the manual states a non-EIS index returns frequency
    zero, so a non-zero frequency is an EIS period.
    """
    return ColumnPlan(
        kind="eis",
        var_codes={
            name: VAR_CODES[name]
            for name in (
                "Ewe_V",
                "I_A",
                "AbsEwe_V",
                "AbsI_A",
                "phase",
                "modulus",
                "Ece_V",
                "AbsEce_V",
                "AbsIce_A",
                "phase_ce",
                "modulus_ce",
            )
        },
        derived=("t_s", "f_Hz", "X_ohm", "R_ohm", "process"),
    )


#: The full-scale voltage each ``EC_ERange`` alias selects, used to write the
#: ``.mps`` file's symmetric min/max pair. ``AUTO`` has no numeric equivalent,
#: so it is handled by ``erange_rows`` rather than appearing here.
ERANGE_VOLTS = {"v2_5": 2.5, "v5": 5.0, "v10": 10.0}

#: EC-Lab writes bandwidth as a bare integer 1-9, **not** as "BW4". Verified
#: against a working third-party writer; writing the alias string produces a
#: file EC-Lab loads and then runs at whatever bandwidth it defaulted to.
BANDWIDTH_VALUES = {f"BW{i}": i for i in range(1, 10)}

#: SI prefixes EC-Lab accepts on a unit row, with the latin-1 micro sign.
#: Ordered large to small; the first whose scaled magnitude is >= 1 wins.
UNIT_PREFIXES = (
    ("M", 1e6),
    ("k", 1e3),
    ("", 1.0),
    ("m", 1e-3),
    ("µ", 1e-6),
    ("n", 1e-9),
    ("p", 1e-12),
)


def scale_to_unit(value: float, base_unit: str) -> tuple[str, str]:
    """Split a physical value into the magnitude and unit EC-Lab writes.

    EC-Lab spells a current, charge or frequency as **two rows** -- a
    magnitude and a matching unit -- and formats every number to three
    decimals. So a 1 uA setpoint written straight into ``Is`` would land as
    ``0.000``: the value has to be scaled and the prefix written alongside it.
    This is the mechanism, not a nicety.

    Args:
        value: The value in base SI units (A, Hz, C ...).
        base_unit: The unscaled unit symbol, e.g. ``"A"`` or ``"Hz"``.

    Returns:
        ``(magnitude, unit)`` -- e.g. ``(1e-6, "A")`` yields
        ``("1.000", "µA")``. Zero yields the unprefixed unit, since no
        prefix is more correct than any other for it.
    """
    magnitude = abs(float(value))
    if magnitude == 0:
        return "0.000", base_unit
    for prefix, scale in UNIT_PREFIXES:
        if magnitude >= scale:
            return f"{float(value) / scale:.3f}", f"{prefix}{base_unit}"
    prefix, scale = UNIT_PREFIXES[-1]
    return f"{float(value) / scale:.3f}", f"{prefix}{base_unit}"


def erange_rows(value: str) -> dict[str, str]:
    """The ``.mps`` rows that express an ``EC_ERange`` selection.

    EC-Lab has no single "E range" row: the potential window is a symmetric
    ``E range min (V)`` / ``E range max (V)`` pair. ``AUTO`` has no numeric
    equivalent at all, so it writes nothing and leaves the template's own
    window in place -- which is the widest the station configured by hand, and
    the only honest reading of "auto" here.

    Returns:
        Caption-to-value rows to set, empty for ``AUTO`` or an unknown alias.
    """
    volts = ERANGE_VOLTS.get(str(value))
    if volts is None:
        return {}
    return {
        "E range min (V)": f"{-volts:.3f}",
        "E range max (V)": f"{volts:.3f}",
    }


#: How each ``EC_IRange`` alias is spelled in the ``.mps`` ``I Range`` row.
#: EC-Lab writes a **display string**, not the alias -- the real templates
#: hold ``Auto``, ``100 µA`` and ``1 mA``. Writing ``u100`` gives a file that
#: loads and runs on whatever range the template carried.
#:
#: ``KEEP`` and ``BOOSTER`` are absent deliberately: no observed template
#: shows how EC-Lab spells them, and ``irange_value`` refuses rather than
#: inventing a string the device would silently reject or misread.
IRANGE_VALUES = {
    "p100": "100 pA",
    "n1": "1 nA",
    "n10": "10 nA",
    "n100": "100 nA",
    "u1": "1 µA",
    "u10": "10 µA",
    "u100": "100 µA",
    "m1": "1 mA",
    "m10": "10 mA",
    "m100": "100 mA",
    "a1": "1 A",
    "AUTO": "Auto",
}


def irange_value(value: str) -> str:
    """EC-Lab's ``I Range`` display string for an ``EC_IRange`` alias.

    Raises:
        ValueError: On ``KEEP``, ``BOOSTER`` or an unknown alias. Refusing is
            the point: this row silently determines the measurement range, so
            a value EC-Lab does not recognise is a wrong experiment rather
            than an error, and a guessed spelling is the same thing.
    """
    try:
        return IRANGE_VALUES[str(value)]
    except KeyError:
        raise ValueError(
            f"no EC-Lab I Range spelling for {value!r}; expected one of "
            f"{sorted(IRANGE_VALUES)}"
        ) from None


#: How each HELAO ``SweepMode`` value is spelled in the ``.mps`` ``spacing``
#: row. The caption is ``spacing``, not ``sweep``, and the values are words.
SPACING_VALUES = {"lin": "Linear", "log": "Logarithmic"}


def spacing_value(value: str) -> str:
    """EC-Lab's ``spacing`` word for a HELAO ``SweepMode``."""
    return SPACING_VALUES.get(str(value), "Logarithmic")


#: Shared current-range and bandwidth captions. Present on every technique
#: that exposes them; OCV has neither, which is why its map is the short one.
#:
#: ``ERange`` is deliberately absent: unlike these it is not one row but a
#: min/max pair, so the driver applies it through ``erange_rows``. Mapping it
#: onto a single caption would write the string "AUTO" into a field EC-Lab
#: reads as a voltage.
_RANGES = {
    "IRange": MpsParam(param_id="I Range", fmt="irange"),
    "Bandwidth": MpsParam(param_id="Bandwidth", fmt="bandwidth"),
}

OLE_TECHS: dict[str, OleTechnique] = {
    "OCV": OleTechnique(
        technique_name="OCV",
        template="OCV.mps",
        parameter_map={
            "Tval__s": MpsParam(param_id="tR (h:m:s)", fmt="hms"),
            "AcqInterval__s": MpsParam(param_id="dtR (s)", fmt="{:.4f}"),
            # EC-Lab's dER is in millivolts; the HELAO parameter is volts.
            "AcqInterval__V": MpsParam(param_id="dER (mV)", fmt="V_to_mV"),
        },
        column_plan=ColumnPlan(kind="dc", derived=("t_s", "Ewe_V")),
        technique_codes=frozenset({11, 55}),
    ),
    "CA": OleTechnique(
        technique_name="CA",
        template="CA.mps",
        parameter_map={
            "Vval__V": MpsParam(param_id="Ei (V)", fmt="{:.3f}"),
            "Tval__s": MpsParam(param_id="ti (h:m:s)", fmt="hms"),
            "AcqInterval__s": MpsParam(param_id="dta (s)", fmt="{:.4f}"),
            # The current-change record threshold is a magnitude/unit pair.
            "AcqInterval__A": MpsParam(
                param_id="dI", unit_param_id="unit dI", base_unit="A"
            ),
            **_RANGES,
        },
        column_plan=_dc_plan(),
        technique_codes=frozenset({24, 54}),
    ),
    "CP": OleTechnique(
        technique_name="CP",
        template="CP.mps",
        parameter_map={
            "Ival__A": MpsParam(param_id="Is", unit_param_id="unit Is", base_unit="A"),
            "Tval__s": MpsParam(param_id="ts (h:m:s)", fmt="hms"),
            "AcqInterval__s": MpsParam(param_id="dts (s)", fmt="{:.4f}"),
            "AcqInterval__V": MpsParam(param_id="dEs (mV)", fmt="V_to_mV"),
            **_RANGES,
        },
        column_plan=_dc_plan(),
        technique_codes=frozenset({25, 56}),
    ),
    # Every caption below is read off the real CV.mps fixture, including the
    # `dE/dt` + `dE/dt unit` pair (which the file spells `20.000` / `mV/s`,
    # so the scan rate is a scale-and-unit parameter like a current).
    #
    # `AcqInterval__V` is deliberately ABSENT. EC-Lab's Cyclic Voltammetry
    # has **no `dE (mV)` row** -- the recording interval is governed by
    # `Step percent` and `N`, whose relationship to a volts-per-point
    # interval is not documented anywhere available here. The endpoint still
    # computes `AcqInterval__V` (`AcqInterval__s * ScanRate__V_s`) for the
    # eclib backend, which maps it to easy-biologic's `step`; on this backend
    # the template's own `Step percent`/`N` stand. Mapping it onto a guessed
    # row would change the sampling of every CV on the station. Resolve at
    # at-station gate 1, with the station owner.
    "CV": OleTechnique(
        technique_name="CV",
        template="CV.mps",
        parameter_map={
            "Vinit__V": MpsParam(param_id="Ei (V)", fmt="{:.3f}"),
            "Vapex1__V": MpsParam(param_id="E1 (V)", fmt="{:.3f}"),
            "Vapex2__V": MpsParam(param_id="E2 (V)", fmt="{:.3f}"),
            "Vfinal__V": MpsParam(param_id="Ef (V)", fmt="{:.3f}"),
            "ScanRate__V_s": MpsParam(
                param_id="dE/dt", unit_param_id="dE/dt unit", base_unit="V/s"
            ),
            "Cycles": MpsParam(param_id="nc cycles", fmt="{:d}"),
            **_RANGES,
        },
        column_plan=_dc_plan(),
        technique_codes=frozenset({6, 57}),
    ),
    "PEIS": OleTechnique(
        technique_name="PEIS",
        template="PEIS.mps",
        parameter_map={
            "Vinit__V": MpsParam(param_id="E (V)", fmt="{:.3f}"),
            # Va is millivolts. Writing volts here is a 1000x error that
            # EC-Lab accepts without complaint.
            "Vamp__V": MpsParam(param_id="Va (mV)", fmt="V_to_mV"),
            "Finit__Hz": MpsParam(
                param_id="fi", unit_param_id="unit fi", base_unit="Hz"
            ),
            "Ffinal__Hz": MpsParam(
                param_id="ff", unit_param_id="unit ff", base_unit="Hz"
            ),
            "FrequencyNumber": MpsParam(param_id="Nd", fmt="{:d}"),
            "Duration__s": MpsParam(param_id="tE (h:m:s)", fmt="hms"),
            "AcqInterval__s": MpsParam(param_id="dt (s)", fmt="{:.4f}"),
            # The caption is `spacing`, not `sweep`, and the values are the
            # words "Linear" / "Logarithmic".
            "SweepMode": MpsParam(param_id="spacing", fmt="spacing"),
            "Repeats": MpsParam(param_id="Na", fmt="{:d}"),
            "DelayFraction": MpsParam(param_id="pw", fmt="{:.2f}"),
            **_RANGES,
        },
        column_plan=_eis_plan(),
        technique_codes=frozenset({29, 60}),
    ),
    "GEIS": OleTechnique(
        technique_name="GEIS",
        template="GEIS.mps",
        parameter_map={
            "Iinit__A": MpsParam(param_id="Is", unit_param_id="unit Is", base_unit="A"),
            # GEIS spells the AC amplitude's unit row with TWO spaces --
            # `unit  Ia`. That is EC-Lab's, not a typo here, and it is why
            # mps_template parses by column rather than by whitespace runs.
            "Iamp__A": MpsParam(param_id="Ia", unit_param_id="unit  Ia", base_unit="A"),
            "Finit__Hz": MpsParam(
                param_id="fi", unit_param_id="unit fi", base_unit="Hz"
            ),
            "Ffinal__Hz": MpsParam(
                param_id="ff", unit_param_id="unit ff", base_unit="Hz"
            ),
            "FrequencyNumber": MpsParam(param_id="Nd", fmt="{:d}"),
            # GEIS's conditioning-time caption is tIs, not tE.
            "Duration__s": MpsParam(param_id="tIs (h:m:s)", fmt="hms"),
            "AcqInterval__s": MpsParam(param_id="dt (s)", fmt="{:.4f}"),
            "SweepMode": MpsParam(param_id="spacing", fmt="spacing"),
            "Repeats": MpsParam(param_id="Na", fmt="{:d}"),
            "DelayFraction": MpsParam(param_id="pw", fmt="{:.2f}"),
            **_RANGES,
        },
        column_plan=_eis_plan(),
        technique_codes=frozenset({30, 61}),
    ),
    "CAOCV": OleTechnique(
        technique_name="CAOCV",
        template="CAOCV.mps",
        parameter_map={
            # Two technique blocks in one template, so every row is scoped:
            # both carry `E range min (V)`, and an unscoped patch would put
            # the OCV settings into the CA step.
            "CA_Vval__V_list": MpsParam(param_id="Ei (V)", fmt="{:.3f}", technique=0),
            "CA_Tval__s_list": MpsParam(param_id="ti (h:m:s)", fmt="hms", technique=0),
            "CA_AcqInterval__s": MpsParam(
                param_id="dta (s)", fmt="{:.4f}", technique=0
            ),
            "CA_AcqInterval__A": MpsParam(
                param_id="dI", unit_param_id="unit dI", base_unit="A", technique=0
            ),
            "CA_IRange": MpsParam(param_id="I Range", fmt="irange", technique=0),
            "CA_Bandwidth": MpsParam(
                param_id="Bandwidth", fmt="bandwidth", technique=0
            ),
            "OCV_Tval__s": MpsParam(param_id="tR (h:m:s)", fmt="hms", technique=1),
            "OCV_AcqInterval__s": MpsParam(
                param_id="dtR (s)", fmt="{:.4f}", technique=1
            ),
            "OCV_AcqInterval__V": MpsParam(
                param_id="dER (mV)", fmt="V_to_mV", technique=1
            ),
        },
        column_plan=_dc_plan(),
        technique_codes=frozenset({24, 54, 11, 55}),
    ),
}


def resolve(name: str) -> OleTechnique:
    """The registry entry for ``name``.

    Raises:
        ValueError: On an unknown technique. Naming the alternatives matters
            because the caller is usually a station config or an experiment
            library, where a typo is otherwise diagnosed at the instrument.
    """
    try:
        return OLE_TECHS[name]
    except KeyError:
        raise ValueError(
            f"unknown OLE technique {name!r}; expected one of {sorted(OLE_TECHS)}"
        ) from None


def format_value(value, fmt: str) -> str:
    """Render ``value`` as EC-Lab spells it in an ``.mps`` table.

    Four sentinels stand in for things no single ``str.format`` spec produces,
    and each exists because writing the obvious thing yields a file EC-Lab
    accepts and then runs wrongly:

    * ``"hms"`` -- EC-Lab's duration spelling, ``h:mm:s.ffff``.
    * ``"bandwidth"`` -- the bare integer 1-9. Writing ``"BW4"`` gives a file
      that loads and runs at whatever bandwidth the template carried.
    * ``"V_to_mV"`` -- a volts parameter landing in a millivolts row
      (``Va (mV)``, ``dER (mV)``, ``dEs (mV)``). Otherwise a 1000x error.
    * ``"spacing"`` -- a sweep mode as EC-Lab's word, "Linear"/"Logarithmic".
    * ``"irange"`` -- a current range as EC-Lab's display string, e.g.
      ``100 µA``. Writing the ``u100`` alias runs on the template's range.

    Anything else is a plain spec applied verbatim. Values needing a companion
    unit row never come through here -- see ``scale_to_unit``.
    """
    if fmt == "hms":
        # The one real duration in a GUI-authored file is `0:00:0.0010`
        # (TI_CV_TO.mps, Trigger Out's `td`): hours and seconds unpadded,
        # minutes padded to two. A third-party writer emits `00:00:00.0010`
        # instead and reportedly works, so EC-Lab is probably lenient on
        # read -- but what it *writes* is the only evidence there is, and a
        # patched file that differs from a GUI-authored one for no reason is
        # a difference nobody will remember making. Confirm with a
        # longer-than-a-minute duration at at-station gate 1.
        total = float(value)
        hours = int(total / 3600.0)
        minutes = int((total % 3600.0) / 60.0)
        seconds = int(total % 60.0)
        fraction = "{:.4f}".format(round(total % 1, 4)).split(".")[1]
        return f"{hours}:{minutes:02d}:{seconds}.{fraction}"
    if fmt == "bandwidth":
        return str(BANDWIDTH_VALUES[str(value)])
    if fmt == "V_to_mV":
        return f"{float(value) * 1000.0:.3f}"
    if fmt == "spacing":
        return spacing_value(value)
    if fmt == "irange":
        return irange_value(value)
    return fmt.format(value)
