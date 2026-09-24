# helao/ui/shared/spectra.py
"""What the plate-spectra pages (`/uvvis`, `/xafs`, `/xrds`) share: a cache,
the loader that fills it, and the window arithmetic.

**Spectra live in a module cache, not in Reflex state.** A selection is
hundreds of spectra; Reflex state is synced and stored per session, and a
recorded spectrum never changes, so spectra are cached here by record key
and a page keeps only the keys. Process uuids are unique across techniques,
so one cache serves every page.

Records are duck-typed: the loader needs ``process_uuid``, ``action_uuid``
and ``file_name``; the pages add ``sample_no``, ``global_label`` and
``run_use``. A record whose process holds more than one spectrum (an XRD
frame's original and background-subtracted patterns) sets ``spectrum_key``;
everything that caches or selects goes through :func:`record_key`.
"""

from __future__ import annotations

import asyncio
import threading
from collections import OrderedDict
from typing import Optional

import numpy as np

#: Concurrent spectrum fetches, as for the composition page's quant fetches.
MAX_CONCURRENT_FETCHES = 30

#: Bytes of spectra kept in memory across sessions, least recently used
#: evicted first. By bytes, not count: a UV-Vis spectrum is ~8 KB as float32,
#: an XRD pattern (10600 points) ~85 KB.
_CACHE_BYTES = 512 * 1024 * 1024

_CACHE: "OrderedDict[str, tuple]" = OrderedDict()
_CACHE_LOCK = threading.Lock()
_cache_size = 0


def record_key(record) -> str:
    """The cache and selection key of *record*'s spectrum."""
    return getattr(record, "spectrum_key", None) or record.process_uuid


def window_mean(x, y, lo: float, hi: float) -> float:
    """Mean of *y* over ``[lo, hi]`` on *x*, either order.

    A window holding no grid point -- both sliders on one value, the default
    -- takes the point nearest its centre instead of returning NaN.
    """
    return float(window_means(x, np.asarray(y, dtype=float)[None, :], lo, hi)[0])


def window_means(x, stack, lo: float, hi: float) -> np.ndarray:
    """:func:`window_mean` for every row of *stack* at once."""
    stack = np.asarray(stack, dtype=float)
    if stack.size == 0:
        return np.empty(0)
    x = np.asarray(x, dtype=float)
    lo, hi = min(lo, hi), max(lo, hi)
    inside = (x >= lo) & (x <= hi)
    if inside.any():
        return stack[:, inside].mean(axis=1)
    return stack[:, int(np.argmin(np.abs(x - (lo + hi) / 2)))]


def range_stats(x, y, lo: float, hi: float) -> dict:
    """min/mean/max/stdev of *y* over ``[lo, hi]`` on *x*.

    Uses the same nearest-point rule as :func:`window_mean` when the range
    holds no grid point, so a zero-width window still has statistics.
    """
    x = np.asarray(x, dtype=float)
    values = np.asarray(y, dtype=float)
    if x.size == 0:
        return {}
    lo, hi = min(lo, hi), max(lo, hi)
    inside = values[(x >= lo) & (x <= hi)]
    if inside.size == 0:
        inside = values[[int(np.argmin(np.abs(x - (lo + hi) / 2)))]]
    return {
        "min": float(inside.min()),
        "mean": float(inside.mean()),
        "max": float(inside.max()),
        "stdev": float(inside.std()),
    }


def cached_spectrum(key: str) -> Optional[tuple]:
    """``(x, y)`` float arrays for *key* (see :func:`record_key`), if loaded."""
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit is not None:
            _CACHE.move_to_end(key)
        return hit


def store(key: str, x, y) -> None:
    """Cache one spectrum, evicting the least recently used past the cap."""
    global _cache_size
    entry = (np.asarray(x, dtype=np.float32), np.asarray(y, dtype=np.float32))
    with _CACHE_LOCK:
        old = _CACHE.pop(key, None)
        if old is not None:
            _cache_size -= old[0].nbytes + old[1].nbytes
        _CACHE[key] = entry
        _cache_size += entry[0].nbytes + entry[1].nbytes
        while _cache_size > _CACHE_BYTES and len(_CACHE) > 1:
            _, dropped = _CACHE.popitem(last=False)
            _cache_size -= dropped[0].nbytes + dropped[1].nbytes


def reset_cache() -> None:
    """Drop every cached spectrum. For tests."""
    global _cache_size
    with _CACHE_LOCK:
        _CACHE.clear()
        _cache_size = 0


async def load_spectra(
    client, records, *, file_type: str, x_key: str, y_key: str, progress=None
) -> int:
    """Fetch every uncached spectrum of *records*; returns how many failed.

    ``read_plottable_data`` wants the action's name, which a process record
    does not carry. One technique's spectrum actions share a name, so it is
    read once from the first action and reused; a fetch that fails with it
    re-reads its own action's name before giving up.

    Args:
        file_type: The spectrum file's ``file_type``.
        x_key: The plottable series holding x.
        y_key: The plottable series holding y.
        progress: Optional ``async (done, total)`` callback, called per batch.
    """
    todo = [r for r in records if cached_spectrum(record_key(r)) is None]
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
            "file_type": file_type,
            "action_name": action_name,
            "action_uuid": record.action_uuid,
        }
        response = await client.read_plottable_data(request_body=body)
        series = ((response or {}).get("data") or {}).get("series") or {}
        x, y = series.get(x_key) or [], series.get(y_key) or []
        if not x or len(x) != len(y):
            raise ValueError(f"no {x_key}/{y_key} series in {record.file_name}")
        store(record_key(record), x, y)

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
    """``(x, stack, kept)``: one grid and a spectra matrix for *records*.

    The grid is the first cached spectrum's; spectra on another grid are
    interpolated onto it. ``kept`` lists the records in ``stack``, row for
    row -- a record with no cached spectrum is left out.
    """
    grid = None
    rows, kept = [], []
    for record in records:
        hit = cached_spectrum(record_key(record))
        if hit is None:
            continue
        x, y = hit
        if grid is None:
            grid = x
        same = x.shape == grid.shape and np.allclose(x, grid)
        rows.append(y if same else np.interp(grid, x, y))
        kept.append(record)
    if grid is None:
        return np.empty(0), np.empty((0, 0)), []
    return np.asarray(grid, dtype=float), np.vstack(rows).astype(float), kept
