# helao/ui/shared/xafs.py
"""XAFS scans across one plate, for the `/xafs` page.

**Finding a plate's scans.** Like R_UVVIS, an XAFS process carries no
``process_params.plate_id`` and the search index holds no ``samples_in``.
The plate is on the sequence (``sequence_params.plate_id``), but on XAFS
sequences that field was not yet searchable when this was written -- the API
backfill had not reached them. So a plate's sequences are the union of

* a SEQUENCE search on ``sequence_params.plate_id`` (what will eventually
  find everything), and
* a scan of the XAFS sequences themselves: each one's ``read_sequence``
  record says its plate, and a sequence whose params name none is resolved
  from its processes' ``samples_in``. The answer is cached per sequence (a
  sequence never changes plate), so only the first Retrieve pays for it --
  122 sequences read in ~5 s when measured.

**One sequence scans several edges.** A ``CuCo`` sequence holds Cu scans at
8829-9548 eV and Co scans at 7559-8278 eV, so a record carries its
``element`` and the page averages one element at a time.

**What is plotted is the analysis, not the scan.** Each ``xafs_nostds``
process has one ``XAFS_normalize_flatten`` analysis whose ``array`` output
holds 75 arrays (``flattened_*`` and ``processed_*``, 505 points each). The
analysis record comes from the API (``read_analysis_by_process``, ~0.2 s);
its array file is read from the station's own ``<root>/ANALYSES`` tree when
it is there -- 92 files in 0.33 s on note1, against 4.8 s through the API --
and from S3 (``read_raw_data``) when it is not, or when the page asks for S3.
Every array is kept, so the page's x and y dropdowns switch series with no
refetch; the defaults are ``flattened_energy`` and ``flattened_mu``.
"""

from __future__ import annotations

import asyncio
import glob
import json
import os
import threading
from collections import OrderedDict
from dataclasses import dataclass, replace

import numpy as np

from helao.ui.shared import spectra

#: The file role holding one scan.
SPECTRUM_FILE_TYPE = "xafsscan__helao_file"

#: The plottable series holding energy and the ROI count rate.
X_KEY = "Energy(eV)"
Y_KEY = "ROI_CountsPerLive(C/s)"

#: What the fallback scan searches sequence names for.
SEQUENCE_NAME_HINT = "XAFS"

#: The analysis whose arrays are plotted, and its array output's name.
ANALYSIS_NAME = "XAFS_normalize_flatten"
ARRAY_OUTPUT = "array"

#: The analysis arrays plotted on x and y by default.
ANALYSIS_X = "flattened_energy"
ANALYSIS_Y = "flattened_mu"

#: process_uuid -> {array name: float32 array}, least recently used first,
#: bounded by bytes: ~150 KB per analysis (75 arrays x 505 points).
_ANALYSES: "OrderedDict[str, dict]" = OrderedDict()
_ANALYSES_LOCK = threading.Lock()
_ANALYSES_BYTES = 512 * 1024 * 1024
_analyses_size = 0

#: analysis_uuid -> local array file path, from one glob of the ANALYSES tree.
_LOCAL_FILES: dict = {}

_SEQUENCE_PLATES: dict = {}
_SEQUENCE_PLATES_LOCK = threading.Lock()


@dataclass(frozen=True)
class XafsRecord:
    """One XAFS scan of one sample."""

    plate_id: int
    sample_no: int
    global_label: str
    run_use: str
    sequence_uuid: str
    sequence_timestamp: str
    element: str
    process_uuid: str
    action_uuid: str
    file_name: str
    #: ``"x|y"``: the analysis arrays this record plots; empty for the scan.
    series: str = ""

    @property
    def spectrum_key(self) -> str:
        """Process and plotted arrays: one analysis offers many pairs."""
        return (
            f"{self.process_uuid}:{self.series}" if self.series else self.process_uuid
        )


def records_from_processes(processes, plate_id: int, sequence_timestamp="") -> list:
    """Records for every scan on *plate_id* in *processes*.

    Any process with a scan file counts, whatever its name (``xrfs_nostds``
    processes on XAFS runs carry them too). The sample is the ``samples_in``
    entry on this plate.
    """
    out = []
    for proc in processes or []:
        scan = next(
            (
                f
                for f in proc.get("files") or []
                if f.get("file_type") == SPECTRUM_FILE_TYPE
            ),
            None,
        )
        sample = next(
            (
                s
                for s in proc.get("samples_in") or []
                if s.get("plate_id") == plate_id and s.get("sample_no") is not None
            ),
            None,
        )
        if scan is None or sample is None:
            continue
        out.append(
            XafsRecord(
                plate_id=plate_id,
                sample_no=int(sample["sample_no"]),
                global_label=str(sample.get("global_label") or ""),
                run_use=str(proc.get("run_use") or ""),
                sequence_uuid=str(proc.get("sequence_uuid") or ""),
                sequence_timestamp=str(sequence_timestamp or ""),
                element=str((proc.get("process_params") or {}).get("element") or ""),
                process_uuid=str(proc.get("process_uuid") or ""),
                action_uuid=str(scan.get("action_uuid") or ""),
                file_name=str(scan.get("file_name") or ""),
            )
        )
    return out


async def _search_all(client, filters: list, size: int = 500) -> list:
    items: list = []
    page = 1
    while True:
        body = {"size": size, "page": page, "match_keys": True, "filters": filters}
        response = await client.search(request_body=body)
        batch = (response or {}).get("items") or []
        items.extend(batch)
        total = int((response or {}).get("total") or 0)
        if not batch or len(items) >= total:
            return items
        page += 1


def reset_sequence_plates() -> None:
    """Forget every resolved sequence plate. For tests."""
    with _SEQUENCE_PLATES_LOCK:
        _SEQUENCE_PLATES.clear()


async def _plates_of(client, sequence_uuid: str) -> frozenset:
    """The plates one sequence measured, cached."""
    with _SEQUENCE_PLATES_LOCK:
        if sequence_uuid in _SEQUENCE_PLATES:
            return _SEQUENCE_PLATES[sequence_uuid]
    sequence = await client.read_sequence(sequence_uuid=sequence_uuid)
    plate = ((sequence or {}).get("sequence_params") or {}).get("plate_id")
    if plate is not None:
        plates = frozenset({int(plate)})
    else:
        processes = await client.read_processes_by_sequence(sequence_uuid=sequence_uuid)
        plates = frozenset(
            int(s["plate_id"])
            for p in processes or []
            for s in p.get("samples_in") or []
            if s.get("plate_id") is not None
        )
    with _SEQUENCE_PLATES_LOCK:
        _SEQUENCE_PLATES[sequence_uuid] = plates
    return plates


async def sequences_for_plate(client, plate_id: int) -> list:
    """SEQUENCE items for *plate_id*: the indexed search plus the XAFS scan."""
    entity = {"field": "entity_type", "operation": "in", "value": ["SEQUENCE"]}
    indexed = await _search_all(
        client,
        [
            {
                "field": "sequence_params.plate_id",
                "operation": "eq",
                "value": int(plate_id),
            },
            entity,
        ],
    )
    named = await _search_all(
        client,
        [
            {
                "field": "sequence_name",
                "operation": "contains",
                "value": SEQUENCE_NAME_HINT,
            },
            entity,
        ],
    )
    semaphore = asyncio.Semaphore(spectra.MAX_CONCURRENT_FETCHES)

    async def _one(item):
        async with semaphore:
            return item, await _plates_of(client, item["sequence_uuid"])

    resolved = await asyncio.gather(
        *(_one(i) for i in named if i.get("sequence_uuid")), return_exceptions=True
    )
    found = {i["sequence_uuid"]: i for i in indexed if i.get("sequence_uuid")}
    for result in resolved:
        if isinstance(result, BaseException):
            continue
        item, plates = result
        if int(plate_id) in plates:
            found.setdefault(item["sequence_uuid"], item)
    return list(found.values())


async def records_for_plate(client, plate_id: int) -> list:
    """Every scan record on *plate_id*, across its sequences."""
    sequences = await sequences_for_plate(client, plate_id)
    semaphore = asyncio.Semaphore(spectra.MAX_CONCURRENT_FETCHES)

    async def _one(sequence):
        async with semaphore:
            processes = await client.read_processes_by_sequence(
                sequence_uuid=sequence["sequence_uuid"]
            )
        return records_from_processes(
            processes, plate_id, sequence.get("sequence_timestamp")
        )

    batches = await asyncio.gather(*(_one(s) for s in sequences))
    return [record for batch in batches for record in batch]


async def load_spectra(client, records, progress=None) -> int:
    """Fetch every uncached scan of *records*."""
    return await spectra.load_spectra(
        client,
        records,
        file_type=SPECTRUM_FILE_TYPE,
        x_key=X_KEY,
        y_key=Y_KEY,
        progress=progress,
    )


# ---------------------------------------------------------------------------
# XAFS_normalize_flatten arrays
# ---------------------------------------------------------------------------
def reset_analyses() -> None:
    """Forget every loaded analysis and the local file index. For tests."""
    global _analyses_size
    with _ANALYSES_LOCK:
        _ANALYSES.clear()
        _LOCAL_FILES.clear()
        _analyses_size = 0


def _put(process_uuid: str, arrays: dict) -> None:
    global _analyses_size
    size = sum(a.nbytes for a in arrays.values())
    with _ANALYSES_LOCK:
        old = _ANALYSES.pop(process_uuid, None)
        if old is not None:
            _analyses_size -= sum(a.nbytes for a in old.values())
        _ANALYSES[process_uuid] = arrays
        _analyses_size += size
        while _analyses_size > _ANALYSES_BYTES and len(_ANALYSES) > 1:
            _, dropped = _ANALYSES.popitem(last=False)
            _analyses_size -= sum(a.nbytes for a in dropped.values())


def _get(process_uuid: str):
    with _ANALYSES_LOCK:
        arrays = _ANALYSES.get(process_uuid)
        if arrays is not None:
            _ANALYSES.move_to_end(process_uuid)
        return arrays


def array_names(records) -> list:
    """Array names every loaded analysis of *records* carries, sorted with
    the ``flattened_*`` ones first -- the choices for the x and y dropdowns."""
    common = None
    for record in records:
        arrays = _get(record.process_uuid)
        if arrays:
            common = set(arrays) if common is None else common & set(arrays)
    return sorted(common or (), key=lambda n: (not n.startswith("flattened_"), n))


def _index_local(root: str) -> None:
    """Refresh the analysis_uuid -> array file map from ``<root>/ANALYSES``."""
    pattern = os.path.join(
        root, "ANALYSES", "*", "*", f"*__{ANALYSIS_NAME}__*", "*_output_array.json"
    )
    found = {
        os.path.basename(path)[: -len("_output_array.json")]: path
        for path in glob.glob(pattern)
    }
    with _ANALYSES_LOCK:
        _LOCAL_FILES.update(found)


def _read_local(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _keep(arrays: dict) -> dict:
    """Every numeric array of an analysis output, as float32."""
    kept = {}
    for name, values in (arrays or {}).items():
        if isinstance(values, list) and values:
            try:
                kept[name] = np.asarray(values, dtype=np.float32)
            except (TypeError, ValueError):
                continue
    return kept


def with_series(records, x: str = ANALYSIS_X, y: str = ANALYSIS_Y) -> list:
    """*records* set to plot *y* against *x*, each view in the spectra cache.

    The generic page code reads spectra by ``record_key``; this writes the
    ``(x, y)`` arrays of every loaded analysis under the key the returned
    records carry. Records whose analysis is not loaded, lacks either array,
    or has them at different lengths are left out.
    """
    out = []
    for record in records:
        arrays = _get(record.process_uuid)
        if not arrays or x not in arrays or y not in arrays:
            continue
        if arrays[x].shape != arrays[y].shape:
            continue
        # Sorted by x: stack_for interpolates onto the first record's grid,
        # and np.interp needs increasing x (energy is; an encoder may not be).
        order = np.argsort(arrays[x], kind="stable")
        viewed = replace(record, series=f"{x}|{y}")
        spectra.store(viewed.spectrum_key, arrays[x][order], arrays[y][order])
        out.append(viewed)
    return out


async def load_analyses(
    client, records, *, local_root: str = "", use_s3: bool = False, progress=None
) -> int:
    """Load every record's XAFS_normalize_flatten arrays; returns failures.

    The analysis record always comes from the API: it names the analysis uuid
    (and so the local file) and the S3 key. The arrays come from the local
    ANALYSES tree unless *use_s3* is set or the file is not there.

    Args:
        local_root: The station's data root (config ``root``); empty skips
            the local tree.
        use_s3: Read every array from S3 even where a local copy exists.
        progress: Optional ``async (done, total)`` callback, per batch.
    """
    todo = [r for r in records if _get(r.process_uuid) is None]
    if not todo:
        return 0
    local = (
        bool(local_root)
        and not use_s3
        and os.path.isdir(os.path.join(local_root, "ANALYSES"))
    )
    if local:
        await asyncio.to_thread(_index_local, local_root)
    reindexed = False
    semaphore = asyncio.Semaphore(spectra.MAX_CONCURRENT_FETCHES)

    async def _one(record):
        nonlocal reindexed
        async with semaphore:
            analyses = await client.read_analysis_by_process(
                process_uuid=record.process_uuid
            )
            analysis = next(
                (a for a in analyses or [] if a.get("analysis_name") == ANALYSIS_NAME),
                None,
            )
            if analysis is None:
                raise LookupError(f"no {ANALYSIS_NAME} for {record.process_uuid}")
            uuid = str(analysis.get("analysis_uuid") or "")
            key = next(
                (
                    (o.get("analysis_output_path") or {}).get("key")
                    for o in analysis.get("outputs") or []
                    if o.get("output_name") == ARRAY_OUTPUT
                ),
                None,
            )
            arrays = None
            if local:
                path = _LOCAL_FILES.get(uuid)
                if path is None and not reindexed:
                    # A new analysis since the index was built: one re-glob
                    # per load, not one per missing file.
                    reindexed = True
                    await asyncio.to_thread(_index_local, local_root)
                    path = _LOCAL_FILES.get(uuid)
                if path is not None:
                    arrays = await asyncio.to_thread(_read_local, path)
            if arrays is None:
                if not key:
                    raise LookupError(f"no array output on analysis {uuid}")
                response = await client.read_raw_data(request_body={"key": key})
                arrays = (response or {}).get("data") or {}
            kept = _keep(arrays)
            if not kept:
                raise ValueError(f"no arrays in analysis {uuid}")
            _put(record.process_uuid, kept)

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
