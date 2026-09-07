"""Turn EClib2 row structs into HELAO's emitted columns.

The column names here are a contract, not a choice: they are the ``field_map``
values the EClib1 backend already publishes, and the visualizers
(``servers/visualizer/biologic_vis.py``, ``servers/reflex/biologic_vis.py``) and
the hte experiments read them by name. Several are not EClib2 fields at all and
are derived to match what easy-biologic reported:

- ``P_W`` -- ``Ewe * I``.
- ``modulus`` / ``modulus_ce`` -- ``|Ewe| / |I|``, i.e. ``|Z|``.
- ``R_ohm`` / ``X_ohm`` -- ``|Z|`` resolved onto the real/imaginary axes.
- ``process`` -- 0 for a time-domain row, 1 for a frequency-domain one.

Rows are duck-typed on attribute names so this module needs neither the vendor
dataclasses nor the SDK. Note the vendor Python layer spells CA/CP voltage and
current ``ewe_average``/``i_average`` on every step technique, though the HTML
docs call the CA/CP ones ``ewe``/``i``; the Python layer is what we bind to.
"""

import math
from collections.abc import Iterable, Sequence
from typing import Any

NAN = float("nan")

OCV_COLUMNS: tuple[str, ...] = ("t_s", "Ewe_V")

#: CA, CP, CV and the legs of CAOCV all publish this set.
STEP_COLUMNS: tuple[str, ...] = ("t_s", "Ewe_V", "I_A", "P_W", "cycle")

#: PEIS and GEIS. The trailing two are derived by the EClib1 driver's
#: ``get_data`` rather than by its ``field_map``, but they reach the same
#: consumers, so they belong to the contract.
EIS_COLUMNS: tuple[str, ...] = (
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

#: A row carrying no frequency -- the time-domain leg of a composite.
PROCESS_TIME_DOMAIN = 0
#: A row from an impedance sweep.
PROCESS_FREQUENCY_DOMAIN = 1


def _quotient(numerator: float, denominator: float) -> float:
    """``numerator / denominator``, or NaN when it is not finite.

    At low signal ``|I|`` can come back as exactly zero. easy-biologic's plain
    divide produced inf or nan there; raising would abort a live acquisition
    over a single bad row, so the row is marked unusable instead.
    """
    try:
        value = numerator / denominator
    except ZeroDivisionError:
        return NAN
    return value if math.isfinite(value) else NAN


def ocv_rows(rows: Sequence[Any]) -> dict[str, list]:
    """Column-orient a list of ``OcvData`` rows."""
    return {
        "t_s": [r.time for r in rows],
        "Ewe_V": [r.ewe for r in rows],
    }


def step_rows(rows: Sequence[Any]) -> dict[str, list]:
    """Column-orient a list of ``CaData`` / ``CpData`` / ``CvData`` rows."""
    return {
        "t_s": [r.time for r in rows],
        "Ewe_V": [r.ewe_average for r in rows],
        "I_A": [r.i_average for r in rows],
        "P_W": [r.ewe_average * r.i_average for r in rows],
        "cycle": [r.cycle for r in rows],
    }


def eis_rows(rows: Sequence[Any]) -> dict[str, list]:
    """Column-orient a list of ``EisData`` rows, deriving ``|Z|`` and R/X.

    ``BL_ProcessRawToEisData`` serves PEIS and GEIS alike, so one mapping
    covers both.
    """
    modulus = [_quotient(r.mod_ewe, r.mod_iwe) for r in rows]
    modulus_ce = [_quotient(r.mod_ece, r.mod_ice) for r in rows]
    return {
        "process": [PROCESS_FREQUENCY_DOMAIN] * len(rows),
        "t_s": [r.time_in_s for r in rows],
        "Ewe_V": [r.ewe_dc for r in rows],
        "I_A": [r.iwe_dc for r in rows],
        "AbsEwe_V": [r.mod_ewe for r in rows],
        "AbsI_A": [r.mod_iwe for r in rows],
        "phase": [r.phase_we for r in rows],
        "modulus": modulus,
        "Ece_V": [r.ece_dc for r in rows],
        "AbsEce_V": [r.mod_ece for r in rows],
        "AbsIce_A": [r.mod_ice for r in rows],
        "phase_ce": [r.phase_ce for r in rows],
        "modulus_ce": modulus_ce,
        "f_Hz": [r.frequency for r in rows],
        # phase_we is in radians (per the SDK's own struct documentation).
        "X_ohm": [-m * math.sin(r.phase_we) for m, r in zip(modulus, rows)],
        "R_ohm": [m * math.cos(r.phase_we) for m, r in zip(modulus, rows)],
    }


def concat(
    tables: Iterable[dict[str, list]], columns: Sequence[str]
) -> dict[str, list]:
    """Stack per-technique tables into one table over ``columns``.

    A technique that does not report a column contributes NaN for it, which is
    what makes a composite action emit a single table: EClib2's PEIS is
    sweep-only and takes its DC bias from a CA technique run just before it, so
    a PEIS action yields a time-domain leg and a frequency-domain leg that
    EClib1 published together under one ``process`` flag. CAOCV is the same
    shape with an OCV leg that reports no current.

    Args:
        tables: Per-technique column tables, in the order the techniques ran.
        columns: The emitted contract. Columns outside it are dropped, so one
            leg cannot widen the action's table.

    Returns:
        One table with every column in ``columns``, each the same length.
    """
    out: dict[str, list] = {c: [] for c in columns}
    for table in tables:
        length = max((len(v) for v in table.values()), default=0)
        # A leg with no `process` column is a time-domain technique (CA, CP,
        # CV, OCV); only an impedance sweep sets it itself.
        for column in columns:
            if column in table:
                out[column].extend(table[column])
            elif column == "process":
                out[column].extend([PROCESS_TIME_DOMAIN] * length)
            else:
                out[column].extend([NAN] * length)
    return out
