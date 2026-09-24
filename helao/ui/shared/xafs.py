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
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass

from helao.ui.shared import spectra

#: The file role holding one scan.
SPECTRUM_FILE_TYPE = "xafsscan__helao_file"

#: The plottable series holding energy and the ROI count rate.
X_KEY = "Energy(eV)"
Y_KEY = "ROI_CountsPerLive(C/s)"

#: What the fallback scan searches sequence names for.
SEQUENCE_NAME_HINT = "XAFS"

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
