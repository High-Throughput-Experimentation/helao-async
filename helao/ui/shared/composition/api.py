# helao/ui/shared/composition/api.py
"""The HELAO metadata-API calls the composition page makes.

Every call here is unauthenticated HTTP against the public metadata API. The
platemap is the one thing this module does not fetch -- it needs S3 credentials
and comes from `helao.ui.shared.platemap` instead.

**The client is built lazily.** `AsyncOpenAPIClient` fetches the OpenAPI spec
*synchronously in its constructor*, so building one at import would put a
network round-trip in the import graph of every module that imports this one.
"""

from __future__ import annotations

import threading

import httpx

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: The metadata API's OpenAPI document.
API_SPEC_URL = "https://helao-api.caltech-hte.modelyst.com/api/openapi.json"

#: The metadata API root. Used only by :func:`_lookup_key`, which cannot go
#: through the client; see that function.
API_BASE = "https://helao-api.caltech-hte.modelyst.com/api"

#: The spectrum HLO's file_type, required by /api/file/plottable-data.
SPECTRUM_FILE_TYPE = "xrfspec_helao__json_file"

#: Request timeout for the one call that bypasses the client, in seconds.
_TIMEOUT_S = 30

_CLIENT = None
_CLIENT_LOCK = threading.Lock()


def get_client():
    """The shared async metadata-API client, built on first use.

    Returns:
        AsyncOpenAPIClient: bound to `search`, `read_raw_data`,
        `read_plottable_data` and `read_action`, among others.
    """
    global _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is None:
            from helao.helpers.openapi_client import AsyncOpenAPIClient

            _CLIENT = AsyncOpenAPIClient(API_SPEC_URL)
        return _CLIENT


def reset_client() -> None:
    """Drop the cached client. For tests and for a credentials change."""
    global _CLIENT
    with _CLIENT_LOCK:
        _CLIENT = None


async def search_processes(client, plate_id: int, *, size: int = 500) -> list:
    """Every XRF process recorded for *plate_id*.

    Filters on the numeric ``process_params.plate_id`` rather than on a
    ``source_csv_label`` prefix: the filter ``Operation`` enum is exactly
    ``gte``/``lte``/``eq``/``match``/``contains``/``in``, with no ``like``, so a
    label prefix would be a ``contains`` heuristic over a string convention.
    ``plate_id`` is exact.

    Pages until the reported ``total`` is reached. A page that comes back empty
    ends the loop regardless, so a ``total`` the server cannot deliver does not
    spin.
    """
    items: list = []
    page = 1
    while True:
        body = {
            "size": size,
            "page": page,
            "match_keys": True,
            "filters": [
                {
                    "field": "process_params.plate_id",
                    "operation": "eq",
                    "value": int(plate_id),
                },
                {"field": "entity_type", "operation": "in", "value": ["PROCESS"]},
            ],
        }
        response = await client.search(request_body=body)
        batch = (response or {}).get("items") or []
        items.extend(batch)
        total = int((response or {}).get("total") or 0)
        if not batch or len(items) >= total:
            return items
        page += 1


async def fetch_sequences(client, sequence_uuids: list) -> dict:
    """The SEQUENCE records for *sequence_uuids*, keyed by uuid.

    A separate request because a PROCESS record's ``sequence_timestamp`` is
    present and null; the timestamp is the only thing distinguishing two
    sequences that share a name and a label.
    """
    uuids = [u for u in (sequence_uuids or []) if u]
    if not uuids:
        return {}
    body = {
        "size": max(len(uuids), 1),
        "page": 1,
        "match_keys": True,
        "filters": [
            {"field": "sequence_uuid", "operation": "in", "value": uuids},
            {"field": "entity_type", "operation": "in", "value": ["SEQUENCE"]},
        ],
    }
    response = await client.search(request_body=body)
    return {
        str(item.get("sequence_uuid")): item
        for item in ((response or {}).get("items") or [])
        if item.get("sequence_uuid")
    }


async def _lookup_key(action_uuid: str, file_name: str) -> str:
    """The S3 key of one action file, via ``POST /api/file/metadata``.

    **Not through the client, deliberately.** ``OpenAPIClient`` derives a
    method name from each operation's ``summary`` and silently overwrites a
    collision: this operation and ``GET /api/output-file/metadata`` are both
    summarised "Read Metadata", and the GET one wins, so ``read_metadata``
    takes a ``file_path`` query parameter and cannot reach this endpoint at
    all. Do not "simplify" this back into the client without fixing that
    derivation first.
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
        response = await client.post(
            f"{API_BASE}/file/metadata",
            json={"file_name": file_name, "action_uuid": action_uuid},
        )
    response.raise_for_status()
    return str((response.json() or {}).get("file_name") or "")


async def fetch_quant(client, action_uuid: str, file_name: str) -> dict:
    """The quantification HLO's data columns for one action.

    The S3 key is derived rather than looked up -- ``/api/file/metadata``
    returns exactly ``raw_data/<action_uuid>/<file_name>``, verified against
    the production API -- which halves a plate load from two requests per
    process to one. The lookup is the fallback for a record stored under a
    different convention.
    """
    key = f"raw_data/{action_uuid}/{file_name}"
    try:
        response = await client.read_raw_data(request_body={"key": key})
    except Exception:
        key = await _lookup_key(action_uuid, file_name)
        if not key:
            return {}
        response = await client.read_raw_data(request_body={"key": key})
    return ((response or {}).get("data") or {}).get("data") or {}


async def fetch_spectrum(client, action_uuid: str, file_name: str) -> dict:
    """The spectrum series for one action: ``ev``, ``intensity``, ``channel``.

    ``/api/file/plottable-data`` requires an ``action_name``, which a PROCESS
    record does not carry, so the action is read first. That is one extra
    request per *clicked point*, not per process.
    """
    action = await client.read_action(action_uuid=action_uuid)
    body = {
        "file_name": file_name,
        "file_type": SPECTRUM_FILE_TYPE,
        "action_name": str((action or {}).get("action_name") or ""),
        "action_uuid": action_uuid,
    }
    response = await client.read_plottable_data(request_body=body)
    return ((response or {}).get("data") or {}).get("series") or {}
