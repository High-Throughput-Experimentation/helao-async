# helao/ui/shared/composition/grouping.py
"""The composition page's two grouping dropdowns.

Both are plain string selections so they can ride a Reflex var directly, and
both compose: picking a run_use and a sequence intersects.
"""

from __future__ import annotations

#: The "no filter" entry, first in every option list.
ALL = "All"

#: Stands in for an empty ``run_use``. A blank dropdown entry reads as a
#: rendering failure rather than as a record with no run_use.
NO_RUN_USE = "(no run_use)"


def run_use_options(records) -> list:
    """Every ``run_use`` present, sorted, with :data:`ALL` first."""
    seen = {record.run_use or NO_RUN_USE for record in records or []}
    return [ALL] + sorted(seen)


def sequence_label(record) -> str:
    """One sequence's dropdown label.

    The timestamp leads because it is the only thing that distinguishes two
    sequences sharing a name and a label -- which the probed plate has, two
    months apart. The uuid's first field disambiguates two runs in one second.
    """
    if not record.sequence_timestamp:
        return record.sequence_uuid
    head = record.sequence_uuid.split("-")[0] if record.sequence_uuid else ""
    return (
        f"{record.sequence_timestamp} · {head}" if head else record.sequence_timestamp
    )


def sequence_options(records) -> list:
    """Every sequence present, newest first, with :data:`ALL` first."""
    by_label: dict = {}
    for record in records or []:
        by_label.setdefault(sequence_label(record), record.sequence_timestamp)
    ordered = sorted(by_label, key=lambda label: by_label[label], reverse=True)
    return [ALL] + ordered


def filter_records(records, *, run_use: str, sequence: str) -> list:
    """The records matching both selections.

    Args:
        records: Every retrieved record.
        run_use: A :func:`run_use_options` entry.
        sequence: A :func:`sequence_options` entry.
    """
    kept = []
    for record in records or []:
        own_run_use = record.run_use or NO_RUN_USE
        if run_use != ALL and own_run_use != run_use:
            continue
        if sequence != ALL and sequence_label(record) != sequence:
            continue
        kept.append(record)
    return kept
