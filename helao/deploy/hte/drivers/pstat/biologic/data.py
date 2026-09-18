"""Record layouts, conversions, and the canonical HELAO columns.

Layouts are keyed `(technique id, board family, process index)` and
transcribed from PDF section 7's data-format tables. Two rules the tables
encode, both of which produce plausible wrong numbers if broken:

**The family is the channel board's, not the chassis'.** easy-biologic selects
layouts from `device.kind`; the technique encoding follows the board, so in a
mixed-board chassis the two disagree and a record is decoded against the wrong
column count.

**A `NbCols` that disagrees with the table is an error, not a hint.** Realigning
to whatever arrived would emit shifted values that look like data.

`COLUMNS` is the one declaration of what each technique emits. `technique.py`
reads it for `column_plan`, so the registry the column-contract test inspects
and the decoder that fills the buffer cannot drift apart.
"""

import math
from typing import Callable, NamedTuple, Optional

from helao.deploy.hte.drivers.pstat.biologic import vendor


class LayoutError(RuntimeError):
    """A record layout this module does not know, or a NbCols mismatch."""


class Field(NamedTuple):
    name: str
    kind: str  # "single" | "int"


def _i(name: str) -> Field:
    return Field(name, "int")


def _s(name: str) -> Field:
    return Field(name, "single")


_VMP3 = vendor.BoardFamily.VMP3
_VMP300 = vendor.BoardFamily.VMP300

# --- OCV (PDF 7.2.3): VMP3 carries a trailing Ece column VMP300 does not ---
_OCV_VMP3 = (_i("t_high"), _i("t_low"), _s("voltage"), _s("voltage_ce"))
_OCV_VMP300 = (_i("t_high"), _i("t_low"), _s("voltage"))

# --- CV (PDF 7.3.3): VMP3 carries a leading control (Ec) column ---
_CV_VMP3 = (
    _i("t_high"),
    _i("t_low"),
    _s("control"),
    _s("current"),
    _s("voltage"),
    _i("cycle"),
)
_CV_VMP300 = (
    _i("t_high"),
    _i("t_low"),
    _s("current"),
    _s("voltage"),
    _i("cycle"),
)

# --- CA/CP/CALIMIT/CPLIMIT (PDF 7.5.2, 7.6.3 "see CP", 7.36.2, 7.37.3): one
# five-column layout shared by both families ---
_DC_FIELDS = (
    _i("t_high"),
    _i("t_low"),
    _s("voltage"),
    _s("current"),
    _i("cycle"),
)

# --- PEIS/GEIS process 0 (PDF 7.11.3, 7.13.3 "see PEIS"): four columns on
# both families ---
_EIS_P0 = (_i("t_high"), _i("t_low"), _s("voltage"), _s("current"))

# --- PEIS/GEIS process 1 (PDF 7.11.3): 14 fields common to both families,
# VMP3 appends a trailing current_range ---
_EIS_P1_COMMON = (
    _s("frequency"),
    _s("abs_voltage"),
    _s("abs_current"),
    _s("impedance_phase"),
    _s("voltage"),
    _s("current"),
    _i("_pad1"),
    _s("abs_voltage_ce"),
    _s("abs_current_ce"),
    _s("impedance_ce_phase"),
    _s("voltage_ce"),
    _i("_pad2"),
    _i("_pad3"),
    _s("time"),
)
_EIS_P1_VMP3 = _EIS_P1_COMMON + (_s("current_range"),)
_EIS_P1_VMP300 = _EIS_P1_COMMON

# --- SPEIS/SGEIS (PDF 7.12.3, 7.14.3 "see SPEIS"): EIS layouts plus a
# trailing step column, on both processes ---
_SEIS_P0 = _EIS_P0 + (_i("step"),)
_SEIS_P1_VMP3 = _EIS_P1_VMP3 + (_i("step"),)
_SEIS_P1_VMP300 = _EIS_P1_VMP300 + (_i("step"),)

_LAYOUTS: dict[tuple[int, vendor.BoardFamily, int], tuple[Field, ...]] = {
    (vendor.TECH_ID.OCV, _VMP3, 0): _OCV_VMP3,
    (vendor.TECH_ID.OCV, _VMP300, 0): _OCV_VMP300,
    (vendor.TECH_ID.CV, _VMP3, 0): _CV_VMP3,
    (vendor.TECH_ID.CV, _VMP300, 0): _CV_VMP300,
    (vendor.TECH_ID.PEIS, _VMP3, 0): _EIS_P0,
    (vendor.TECH_ID.PEIS, _VMP300, 0): _EIS_P0,
    (vendor.TECH_ID.PEIS, _VMP3, 1): _EIS_P1_VMP3,
    (vendor.TECH_ID.PEIS, _VMP300, 1): _EIS_P1_VMP300,
    (vendor.TECH_ID.GEIS, _VMP3, 0): _EIS_P0,
    (vendor.TECH_ID.GEIS, _VMP300, 0): _EIS_P0,
    (vendor.TECH_ID.GEIS, _VMP3, 1): _EIS_P1_VMP3,
    (vendor.TECH_ID.GEIS, _VMP300, 1): _EIS_P1_VMP300,
    (vendor.TECH_ID.SPEIS, _VMP3, 0): _SEIS_P0,
    (vendor.TECH_ID.SPEIS, _VMP300, 0): _SEIS_P0,
    (vendor.TECH_ID.SPEIS, _VMP3, 1): _SEIS_P1_VMP3,
    (vendor.TECH_ID.SPEIS, _VMP300, 1): _SEIS_P1_VMP300,
    (vendor.TECH_ID.SGEIS, _VMP3, 0): _SEIS_P0,
    (vendor.TECH_ID.SGEIS, _VMP300, 0): _SEIS_P0,
    (vendor.TECH_ID.SGEIS, _VMP3, 1): _SEIS_P1_VMP3,
    (vendor.TECH_ID.SGEIS, _VMP300, 1): _SEIS_P1_VMP300,
}
for _dc_tech in (
    vendor.TECH_ID.CA,
    vendor.TECH_ID.CP,
    vendor.TECH_ID.CALIMIT,
    vendor.TECH_ID.CPLIMIT,
):
    _LAYOUTS[(_dc_tech, _VMP3, 0)] = _DC_FIELDS
    _LAYOUTS[(_dc_tech, _VMP300, 0)] = _DC_FIELDS

_KNOWN_TECH_IDS = {tech_id for (tech_id, _, _) in _LAYOUTS}


def layout(
    tech_id: int, family: vendor.BoardFamily, process: int = 0
) -> tuple[Field, ...]:
    """The column layout for a technique id, board family, and process index.

    Raises `LayoutError` naming the id or the process index rather than
    returning a plausible default -- an unrecognized combination means this
    table does not cover the firmware in front of it.
    """
    if tech_id not in _KNOWN_TECH_IDS:
        raise LayoutError(
            f"no data-format layout registered for technique id {tech_id}"
        )
    try:
        return _LAYOUTS[(tech_id, family, process)]
    except KeyError:
        raise LayoutError(
            f"unknown process index {process} for technique id {tech_id} "
            f"({family.value})"
        )


#: The one declaration of what each technique emits. `technique.py`'s
#: `column_plan` reads this rather than restating it.
_DC = ("t_s", "Ewe_V", "I_A", "P_W", "cycle")
_EIS = (
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

COLUMNS: dict[str, tuple[str, ...]] = {
    "OCV": ("t_s", "Ewe_V"),
    "CA": _DC,
    "CP": _DC,
    "CV": _DC,
    "CAOCV": _DC,
    "CALIMIT": _DC,
    "CPLIMIT": _DC,
    "PEIS": _EIS,
    "GEIS": _EIS,
    "SPEIS": _EIS + ("step",),
    "SGEIS": _EIS + ("step",),
}

_EIS_TECHNIQUES = ("PEIS", "GEIS", "SPEIS", "SGEIS")


def _safe_div(numerator: float, denominator: float) -> float:
    if denominator == 0 or math.isnan(numerator) or math.isnan(denominator):
        return float("nan")
    return numerator / denominator


def _project_dc(row: dict, start: float, to_seconds, values, board_type, out) -> None:
    out["t_s"].append(
        start + to_seconds(row["t_high"], row["t_low"], values.TimeBase, board_type)
    )
    ewe = row["voltage"]
    i = row["current"]
    out["Ewe_V"].append(ewe)
    out["I_A"].append(i)
    out["P_W"].append(ewe * i)
    out["cycle"].append(row["cycle"])


def _project_ocv(row: dict, start: float, to_seconds, values, board_type, out) -> None:
    out["t_s"].append(
        start + to_seconds(row["t_high"], row["t_low"], values.TimeBase, board_type)
    )
    out["Ewe_V"].append(row["voltage"])


def _project_eis(row: dict, t_s: float, info, out: dict) -> None:
    process = info.ProcessIndex
    out["process"].append(process)
    out["t_s"].append(t_s)
    if process == 0:
        ewe = row["voltage"]
        i = row["current"]
        abs_ewe = abs_i = phase = modulus = float("nan")
        ece = abs_ece = abs_ice = phase_ce = modulus_ce = float("nan")
        f_hz = x_ohm = r_ohm = float("nan")
    else:
        ewe = row["voltage"]
        i = row["current"]
        abs_ewe = row["abs_voltage"]
        abs_i = row["abs_current"]
        phase = row["impedance_phase"]
        modulus = _safe_div(abs_ewe, abs_i)
        ece = row["voltage_ce"]
        abs_ece = row["abs_voltage_ce"]
        abs_ice = row["abs_current_ce"]
        phase_ce = row["impedance_ce_phase"]
        modulus_ce = _safe_div(abs_ece, abs_ice)
        f_hz = row["frequency"]
        if math.isnan(modulus) or math.isnan(phase):
            x_ohm = r_ohm = float("nan")
        else:
            x_ohm = -modulus * math.sin(phase)
            r_ohm = modulus * math.cos(phase)

    out["Ewe_V"].append(ewe)
    out["I_A"].append(i)
    out["AbsEwe_V"].append(abs_ewe)
    out["AbsI_A"].append(abs_i)
    out["phase"].append(phase)
    out["modulus"].append(modulus)
    out["Ece_V"].append(ece)
    out["AbsEce_V"].append(abs_ece)
    out["AbsIce_A"].append(abs_ice)
    out["phase_ce"].append(phase_ce)
    out["modulus_ce"].append(modulus_ce)
    out["f_Hz"].append(f_hz)
    out["X_ohm"].append(x_ohm)
    out["R_ohm"].append(r_ohm)

    if "step" in out:
        out["step"].append(row["step"])


def decode(
    name: str,
    info,
    values,
    records,
    to_single: Callable[[int, int], float],
    to_seconds: Callable[[int, int, float, int], float],
    board_type: int,
) -> dict[str, list]:
    """Decode one `BL_GetData` buffer into `COLUMNS[name]`-shaped lists.

    `name` can be a fallback like `"PLAN"` or `"NONE"` (see `_segment_name`)
    on a zero-row terminal poll, which is not a key in `COLUMNS` -- `.get`
    with an empty default means that poll decodes to no columns rather than
    raising `KeyError` on every plan run's last poll.
    """
    if info.TechniqueID == vendor.TECH_ID.NONE or info.NbRows == 0:
        return {c: [] for c in COLUMNS.get(name, ())}

    fields = layout(
        info.TechniqueID, vendor.board_family(board_type), info.ProcessIndex
    )
    if len(fields) != info.NbCols:
        raise LayoutError(
            f"NbCols {info.NbCols} for technique {name} does not match its "
            f"{len(fields)}-column layout"
        )

    start = 0.0 if math.isnan(info.StartTime) else info.StartTime
    out: dict[str, list] = {c: [] for c in COLUMNS.get(name, ())}

    for r in range(info.NbRows):
        row_words = records[r * info.NbCols : (r + 1) * info.NbCols]
        row = {
            field.name: (
                to_single(word, board_type) if field.kind == "single" else int(word)
            )
            for field, word in zip(fields, row_words)
        }
        if name in _EIS_TECHNIQUES:
            if info.ProcessIndex == 0:
                t_s = start + to_seconds(
                    int(row["t_high"]), int(row["t_low"]), values.TimeBase, board_type
                )
            else:
                t_s = row["time"]
            _project_eis(row, t_s, info, out)
        elif name == "OCV":
            _project_ocv(row, start, to_seconds, values, board_type, out)
        else:
            _project_dc(row, start, to_seconds, values, board_type, out)

    return out


#: How many extra `BL_GetData` calls one `get_data` will make while draining
#: the tail. Bounded because the loop it replaces was not: `to_s3`-style
#: "retry until it works" on a call that can keep returning rows is how a
#: worker wedges.
MAX_DRAINS_PER_CALL = 20

#: States that mean the channel is not finished. Named rather than tested with
#: `State > 0`, which also swallows whatever a future firmware adds.
_BUSY_STATES = frozenset(
    {vendor.PROG_STATE.RUN, vendor.PROG_STATE.PAUSE, vendor.PROG_STATE.SYNC}
)

#: How many `observe()` calls a channel may report "starting" before
#: `RunTracker` gives up and reports "error" instead -- targets a firmware
#: start failure, which is a sub-second event, not a legitimate wait. Without
#: this a channel that accepts `BL_StartChannel` and never reaches `RUN` (or
#: `STOP` with rows) polls "starting" forever at `BiologicExec`'s 10 ms rate,
#: with nothing anywhere reporting a fault.
#:
#: This bound must NOT apply to a channel parked on a requested Trigger In:
#: that wait is on an external instrument and is deliberately unbounded, so
#: `start_channel` passes `max_starting_polls=None` whenever `ttl == "in"` --
#: `None` disables the cap outright rather than raising it to a second
#: guessed number. Trigger *Out* is not the same case -- it pulses for its
#: own finite `Trigger_Duration` and returns, waiting on nothing, so it keeps
#: this cap armed. Conflating "firmware never started" (sub-second) with "a
#: trigger the operator asked for" (indefinite) under one cap turns a correct
#: wait into a premature abort.
MAX_STARTING_POLLS = 500


class RunTracker:
    """Decides when a technique has finished, and how far to drain after.

    One per started channel; the driver keeps it from `start_channel` to
    `cleanup`.
    """

    def __init__(
        self,
        max_drains: int = MAX_DRAINS_PER_CALL,
        max_starting_polls: Optional[int] = MAX_STARTING_POLLS,
    ):
        self.max_drains = max_drains
        #: `None` means unbounded -- see MAX_STARTING_POLLS's docstring.
        self.max_starting_polls = max_starting_polls
        self.seen_run = False
        self.skipped = 0
        self.drains = 0
        self._done = False
        self._errored = False
        self._starting_polls = 0
        self._drain_index: Optional[int] = None

    def observe(self, values, info) -> str:
        self.skipped += int(getattr(info, "IRQskipped", 0) or 0)
        if self._errored:
            return "error"
        if self._done:
            return "done"
        state = int(values.State)
        if state in _BUSY_STATES or state not in {int(vendor.PROG_STATE.STOP)}:
            # Busy, or a state this build does not know -- either way not done.
            self.seen_run = True
            self._starting_polls = 0
            return "measuring"
        if int(getattr(info, "NbRows", 0) or 0) > 0:
            # Rows are proof it ran, even if RUN was never sampled.
            self.seen_run = True
        if not self.seen_run:
            self._starting_polls += 1
            if (
                self.max_starting_polls is not None
                and self._starting_polls > self.max_starting_polls
            ):
                self._errored = True
                return "error"
            return "starting"
        self._done = True
        return "done"

    def should_drain(self, info) -> bool:
        if int(getattr(info, "NbRows", 0) or 0) <= 0:
            return False
        index = int(getattr(info, "TechniqueIndex", 0) or 0)
        if self._drain_index is None:
            self._drain_index = index
        elif index != self._drain_index:
            return False
        if self.drains >= self.max_drains:
            return False
        self.drains += 1
        return True
