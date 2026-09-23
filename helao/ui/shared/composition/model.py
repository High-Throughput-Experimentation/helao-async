# helao/ui/shared/composition/model.py
"""One XRF measurement of one sample, as the composition page needs it.

A metadata-API PROCESS item carries everything except two things: the sequence
timestamp (present but null on a process; it comes from a separate SEQUENCE
search) and the analysis values themselves (in an HLO named by the item's
`files` list). `record_from_process` builds the record from the item, and
`with_values` folds in the quantification payload once it has been fetched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Optional

#: Columns of the quantification HLO that are not per-transition measurements.
#: `element` and `transition` are the row identity; the rest are per-file
#: scalars the API returns as one-element lists. Handing any of them to `plots`
#: raises `could not convert string to float` from inside the render, which
#: takes down the whole chart rather than one series.
NON_NUMERIC_COLUMNS = frozenset(
    {
        "element",
        "transition",
        "global_sample_label",
        "analysis_name",
        "output_type",
        "calibration_date",
    }
)

#: The quantification HLO's `file_type`.
QUANT_FILE_TYPE = "xrfs_quant_helao__json_file"

#: The spectrum HLO's `file_type`.
SPECTRUM_FILE_TYPE = "xrfspec_helao__json_file"

#: Trailing sample number of a global label, e.g. `legacy__solid__10244_42`.
_TRAILING_NUMBER = re.compile(r"_(\d+)\s*$")


@dataclass(frozen=True)
class CompositionRecord:
    """One XRF process on one sample.

    Attributes:
        sample_no: ``None`` until known. Some plates' PROCESS records carry no
            label at all (plate 6138: ``process_params`` is ``{"plate_id"}``
            only), and the number then comes from the quantification payload
            in :func:`with_values`.
        values: ``transition -> unit -> value``. A value is ``None`` where the
            API reported null -- an uncalibrated transition has no
            ``atomic_fraction``, and ``0.0`` there would plot as a measurement.
    """

    plate_id: int
    sample_no: Optional[int]
    global_label: str
    run_use: str
    sequence_uuid: str
    sequence_timestamp: str
    process_uuid: str
    process_timestamp: str
    quant_action_uuid: str
    quant_file_name: str
    spectrum_action_uuid: str
    spectrum_file_name: str
    values: dict


def sample_no_from(process_params: Optional[dict]) -> Optional[int]:
    """Sample number of one process, or ``None`` when it cannot be determined.

    `source_csv_label` is the global label (`legacy__solid__10244_42`) and is
    tried first; `stage_label` is the fallback. A record that yields neither is
    dropped by :func:`record_from_process` rather than plotted at an invented
    position.
    """
    params = process_params or {}
    label = params.get("source_csv_label")
    if isinstance(label, str):
        match = _TRAILING_NUMBER.search(label)
        if match:
            return int(match.group(1))
    stage = params.get("stage_label")
    try:
        return int(str(stage).strip())
    except (TypeError, ValueError):
        return None


def _file_named(files: Optional[list], file_type: str) -> tuple:
    """``(action_uuid, file_name)`` of the first file of *file_type*."""
    for entry in files or []:
        if (entry or {}).get("file_type") == file_type:
            return str(entry.get("action_uuid") or ""), str(
                entry.get("file_name") or ""
            )
    return "", ""


def record_from_process(
    item: Optional[dict], sequences: Optional[dict]
) -> Optional[CompositionRecord]:
    """Build a record from one search item, or ``None`` when it is unusable.

    Args:
        item: One element of a `/api/search` PROCESS response.
        sequences: ``sequence_uuid -> sequence item``, from the SEQUENCE search.

    Returns:
        CompositionRecord with an empty ``values``, or ``None`` when the item
        carries no quantification file. A missing sample number is not a
        reason to drop the item here: :func:`with_values` may still find one.
    """
    entry = item or {}
    params = entry.get("process_params") or {}
    sample_no = sample_no_from(params)
    quant_uuid, quant_name = _file_named(entry.get("files"), QUANT_FILE_TYPE)
    if not quant_uuid or not quant_name:
        return None
    spec_uuid, spec_name = _file_named(entry.get("files"), SPECTRUM_FILE_TYPE)
    sequence_uuid = str(entry.get("sequence_uuid") or "")
    sequence = ((sequences or {}).get(sequence_uuid)) or {}
    try:
        raw = params.get("plate_id")
        plate_id = 0 if raw is None else int(raw)
    except (TypeError, ValueError):
        plate_id = 0
    return CompositionRecord(
        plate_id=plate_id,
        sample_no=sample_no,
        global_label=str(params.get("source_csv_label") or ""),
        run_use=str(entry.get("run_use") or ""),
        sequence_uuid=sequence_uuid,
        sequence_timestamp=str(sequence.get("sequence_timestamp") or ""),
        process_uuid=str(entry.get("process_uuid") or ""),
        process_timestamp=str(entry.get("process_timestamp") or ""),
        quant_action_uuid=quant_uuid,
        quant_file_name=quant_name,
        spectrum_action_uuid=spec_uuid,
        spectrum_file_name=spec_name,
        values={},
    )


def with_values(record: CompositionRecord, quant: Optional[dict]) -> CompositionRecord:
    """Return *record* with the quantification payload folded into ``values``.

    A record whose PROCESS item named no sample takes its sample number and
    global label from the payload's ``global_sample_label``, and keeps
    ``sample_no=None`` if that is missing too -- the caller drops it.

    A column shorter than the transition list is skipped rather than zipped:
    `global_sample_label` carries one entry for five transitions, and zipping
    would truncate every other unit to one value while nothing reported a
    fault.
    """
    payload = quant or {}
    transitions = [str(t) for t in (payload.get("transition") or [])]
    values: dict = {name: {} for name in transitions}
    for column, series in payload.items():
        if column in NON_NUMERIC_COLUMNS:
            continue
        if not isinstance(series, list) or len(series) != len(transitions):
            continue
        for name, value in zip(transitions, series):
            values[name][column] = None if value is None else float(value)
    if record.sample_no is not None:
        return replace(record, values=values)
    labels = payload.get("global_sample_label") or []
    label = str(labels[0]) if labels else ""
    return replace(
        record,
        values=values,
        sample_no=sample_no_from({"source_csv_label": label}),
        global_label=record.global_label or label,
    )


def transition_names(records: Optional[list]) -> list:
    """Every transition any record carries, sorted."""
    names: set = set()
    for record in records or []:
        names.update(record.values)
    return sorted(names)


def unit_names(records: Optional[list]) -> list:
    """Every unit any record carries, sorted."""
    names: set = set()
    for record in records or []:
        for per_unit in record.values.values():
            names.update(per_unit)
    return sorted(names)
