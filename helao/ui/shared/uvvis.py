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

**Spectra live in a module cache, not in Reflex state.** A run is hundreds of
1024-point spectra; Reflex state is synced and stored per session, and the
spectra are immutable once recorded, so they are cached here by process uuid
and the page keeps only the uuids.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import numpy as np
from uuid_extensions import uuid_to_datetime

#: The file role holding one reflectance spectrum.
SPECTRUM_FILE_TYPE = "spec_r_parquet__file"

#: The process name of a reflectance measurement.
PROCESS_NAME = "R_UVVIS"

#: Wavelength range, in nm, the details table summarizes.
STATS_RANGE = (350.0, 1000.0)

#: Concurrent spectrum fetches, as for the composition page's quant fetches.
MAX_CONCURRENT_FETCHES = 30

#: Spectra kept in memory across sessions. ~4 KB each as float32, so the cap
#: is ~80 MB. ponytail: LRU by count, not bytes; revisit if grids grow.
_CACHE_LIMIT = 20000


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


def window_mean(wl, intensity, lo: float, hi: float) -> float:
    """Mean intensity over ``[lo, hi]`` nm, either order.

    A window holding no grid point -- both sliders on one wavelength, the
    default -- takes the point nearest its centre instead of returning NaN.
    """
    wl = np.asarray(wl, dtype=float)
    values = np.asarray(intensity, dtype=float)
    lo, hi = min(lo, hi), max(lo, hi)
    inside = (wl >= lo) & (wl <= hi)
    if inside.any():
        return float(np.mean(values[..., inside], axis=-1))
    nearest = int(np.argmin(np.abs(wl - (lo + hi) / 2)))
    return float(values[..., nearest])


def window_means(wl, stack, lo: float, hi: float) -> np.ndarray:
    """:func:`window_mean` for every row of *stack* at once."""
    stack = np.asarray(stack, dtype=float)
    if stack.size == 0:
        return np.empty(0)
    wl = np.asarray(wl, dtype=float)
    lo, hi = min(lo, hi), max(lo, hi)
    inside = (wl >= lo) & (wl <= hi)
    if inside.any():
        return stack[:, inside].mean(axis=1)
    return stack[:, int(np.argmin(np.abs(wl - (lo + hi) / 2)))]


def range_stats(wl, intensity, lo=STATS_RANGE[0], hi=STATS_RANGE[1]) -> dict:
    """min/mean/max/stdev of *intensity* over ``[lo, hi]`` nm; empty if none."""
    wl = np.asarray(wl, dtype=float)
    values = np.asarray(intensity, dtype=float)
    inside = values[(wl >= lo) & (wl <= hi)]
    if inside.size == 0:
        return {}
    return {
        "min": float(inside.min()),
        "mean": float(inside.mean()),
        "max": float(inside.max()),
        "stdev": float(inside.std()),
    }


# ---------------------------------------------------------------------------
# API and cache
# ---------------------------------------------------------------------------
_CACHE: "OrderedDict[str, tuple]" = OrderedDict()
_CACHE_LOCK = threading.Lock()


def cached_spectrum(process_uuid: str) -> Optional[tuple]:
    """``(wl, intensity)`` float arrays for *process_uuid*, if loaded."""
    with _CACHE_LOCK:
        hit = _CACHE.get(process_uuid)
        if hit is not None:
            _CACHE.move_to_end(process_uuid)
        return hit


def _store(process_uuid: str, wl, intensity) -> None:
    with _CACHE_LOCK:
        _CACHE[process_uuid] = (
            np.asarray(wl, dtype=np.float32),
            np.asarray(intensity, dtype=np.float32),
        )
        _CACHE.move_to_end(process_uuid)
        while len(_CACHE) > _CACHE_LIMIT:
            _CACHE.popitem(last=False)


def reset_cache() -> None:
    """Drop every cached spectrum. For tests."""
    with _CACHE_LOCK:
        _CACHE.clear()


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
    """Fetch every uncached spectrum of *records*; returns how many failed.

    ``read_plottable_data`` wants the action's name, which a process record
    does not carry. Every spectrum action seen is ``acquire_spec_adv``, so the
    name is read once from the first action and reused; a fetch that fails
    with it re-reads its own action's name before giving up.

    Args:
        progress: Optional ``async (done, total)`` callback, called per batch.
    """
    todo = [r for r in records if cached_spectrum(r.process_uuid) is None]
    if not todo:
        return 0
    names: dict = {}

    async def _name(action_uuid: str) -> str:
        if action_uuid not in names:
            action = await client.read_action(action_uuid=action_uuid)
            names[action_uuid] = str((action or {}).get("action_name") or "")
        return names[action_uuid]

    shared = await _name(todo[0].action_uuid)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)

    async def _fetch(record, action_name):
        body = {
            "file_name": record.file_name,
            "file_type": SPECTRUM_FILE_TYPE,
            "action_name": action_name,
            "action_uuid": record.action_uuid,
        }
        response = await client.read_plottable_data(request_body=body)
        series = ((response or {}).get("data") or {}).get("series") or {}
        wl, intensity = series.get("wl_nm") or [], series.get("intensity") or []
        if not wl or len(wl) != len(intensity):
            raise ValueError(f"no wl_nm/intensity series in {record.file_name}")
        _store(record.process_uuid, wl, intensity)

    async def _one(record):
        async with semaphore:
            try:
                await _fetch(record, shared)
            except Exception:
                await _fetch(record, await _name(record.action_uuid))

    failures = 0
    step = 60
    for start in range(0, len(todo), step):
        chunk = todo[start : start + step]
        results = await asyncio.gather(
            *(_one(r) for r in chunk), return_exceptions=True
        )
        failures += sum(isinstance(r, BaseException) for r in results)
        if progress is not None:
            await progress(min(start + step, len(todo)), len(todo))
    return failures


def stack_for(records) -> tuple:
    """``(wl, stack, kept)``: one grid and a spectra matrix for *records*.

    The grid is the first cached spectrum's. Spectra on another grid are
    interpolated onto it (every run probed so far shares one grid, so this is
    a guard, not a path). Records with no cached spectrum are left out;
    ``kept`` lists the ones in ``stack``, row for row.
    """
    wl = None
    rows, kept = [], []
    for record in records:
        hit = cached_spectrum(record.process_uuid)
        if hit is None:
            continue
        x, y = hit
        if wl is None:
            wl = x
        rows.append(
            y if x.shape == wl.shape and np.allclose(x, wl) else np.interp(wl, x, y)
        )
        kept.append(record)
    if wl is None:
        return np.empty(0), np.empty((0, 0)), []
    return np.asarray(wl, dtype=float), np.vstack(rows).astype(float), kept
