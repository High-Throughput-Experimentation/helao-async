# helao/ui/shared/uvvis.py
"""R_UVVIS reflectance spectra across one plate, for the `/uvvis` page.

**How a plate's spectra are found.** An R_UVVIS *data* process carries no
``process_params.plate_id``, and the search index holds no ``samples_in``, so
the composition page's process search cannot see them. What is searchable is
``sequence_params.plate_id`` on SEQUENCE records -- set by new sequences and
being backfilled onto old ones -- so the path is: sequences for the plate,
then ``/api/sequence/{uuid}/processes`` (full records, ``samples_in``
included), then one ``read_plottable_data`` per spectrum file. A sequence the
backfill has not reached yet is simply not found.

Spectra, the cache and the window arithmetic are shared with `/xafs` and live
in :mod:`helao.ui.shared.spectra`; the names are re-exported here.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from uuid_extensions import uuid_to_datetime

from helao.ui.shared import spectra
from helao.ui.shared.spectra import (  # noqa: F401  (re-exported)
    MAX_CONCURRENT_FETCHES,
    cached_spectrum,
    range_stats,
    reset_cache,
    stack_for,
    window_mean,
    window_means,
)
from helao.ui.shared.spectra import store as _store  # noqa: F401

#: The file role holding one reflectance spectrum.
SPECTRUM_FILE_TYPE = "spec_r_parquet__file"

#: The process name of a reflectance measurement.
PROCESS_NAME = "R_UVVIS"

#: The plottable series holding wavelength and intensity.
X_KEY = "wl_nm"
Y_KEY = "intensity"

#: Wavelength range, in nm, the details table summarizes.
STATS_RANGE = (350.0, 1000.0)


@dataclass(frozen=True)
class UvvisRecord:
    """One R_UVVIS spectrum of one sample (or reference position)."""

    plate_id: int
    sample_no: int
    global_label: str
    run_id: str
    run_use: str
    sequence_uuid: str
    process_uuid: str
    action_uuid: str
    file_name: str


def run_timestamp(run_id: str) -> Optional[datetime]:
    """Local time encoded in a HELAO run_id, or ``None``.

    HELAO's uuid7 comes from ``uuid_extensions``, which packs Unix *seconds*
    into the first 36 bits -- not the 48-bit milliseconds of RFC 9562, which
    reads these ids as the year 2202.
    """
    try:
        return uuid_to_datetime(uuid.UUID(str(run_id))).astimezone()
    except (TypeError, ValueError, AttributeError):
        return None


def run_label(run_id: str) -> str:
    """The run dropdown entry: timestamp first, so entries sort by time."""
    stamp = run_timestamp(run_id)
    return f"{stamp:%Y-%m-%d %H:%M:%S} · {run_id}" if stamp else str(run_id)


def records_from_processes(processes, plate_id: int) -> list:
    """Records for every R_UVVIS spectrum on *plate_id* in *processes*.

    The sample is the ``samples_in`` entry on this plate; a process with none,
    or with no spectrum file, yields nothing.
    """
    out = []
    for proc in processes or []:
        if proc.get("process_name") != PROCESS_NAME:
            continue
        sample = next(
            (
                s
                for s in proc.get("samples_in") or []
                if s.get("plate_id") == plate_id and s.get("sample_no") is not None
            ),
            None,
        )
        spectrum = next(
            (
                f
                for f in proc.get("files") or []
                if f.get("file_type") == SPECTRUM_FILE_TYPE
            ),
            None,
        )
        if sample is None or spectrum is None:
            continue
        out.append(
            UvvisRecord(
                plate_id=plate_id,
                sample_no=int(sample["sample_no"]),
                global_label=str(sample.get("global_label") or ""),
                run_id=str(proc.get("run_id") or ""),
                run_use=str(proc.get("run_use") or ""),
                sequence_uuid=str(proc.get("sequence_uuid") or ""),
                process_uuid=str(proc.get("process_uuid") or ""),
                action_uuid=str(spectrum.get("action_uuid") or ""),
                file_name=str(spectrum.get("file_name") or ""),
            )
        )
    return out


async def sequences_for_plate(client, plate_id: int, *, size: int = 500) -> list:
    """SEQUENCE search items whose ``sequence_params.plate_id`` is *plate_id*."""
    items: list = []
    page = 1
    while True:
        body = {
            "size": size,
            "page": page,
            "match_keys": True,
            "filters": [
                {
                    "field": "sequence_params.plate_id",
                    "operation": "eq",
                    "value": int(plate_id),
                },
                {"field": "entity_type", "operation": "in", "value": ["SEQUENCE"]},
            ],
        }
        response = await client.search(request_body=body)
        batch = (response or {}).get("items") or []
        items.extend(batch)
        total = int((response or {}).get("total") or 0)
        if not batch or len(items) >= total:
            return items
        page += 1


async def records_for_plate(client, plate_id: int) -> list:
    """Every R_UVVIS spectrum record on *plate_id*, across its sequences."""
    sequences = await sequences_for_plate(client, plate_id)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)

    async def _one(sequence_uuid):
        async with semaphore:
            return await client.read_processes_by_sequence(sequence_uuid=sequence_uuid)

    batches = await asyncio.gather(
        *(_one(s["sequence_uuid"]) for s in sequences if s.get("sequence_uuid"))
    )
    return [r for procs in batches for r in records_from_processes(procs, plate_id)]


async def load_spectra(client, records, progress=None) -> int:
    """Fetch every uncached reflectance spectrum of *records*."""
    return await spectra.load_spectra(
        client,
        records,
        file_type=SPECTRUM_FILE_TYPE,
        x_key=X_KEY,
        y_key=Y_KEY,
        progress=progress,
    )
