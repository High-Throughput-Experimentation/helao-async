"""Blocking plate-API, S3 and spec fetches run in worker threads.

Each of these used to run on the event loop: a SAMPLE action server's
``get_platemap`` stalled every other request while it fetched a platemap, and
a Reflex page's first metadata-API call fetched the OpenAPI spec (up to 30 s)
with every session on that server frozen behind it.
"""

import asyncio
import threading
from types import SimpleNamespace

from helao.helpers import sample_api
from helao.ui.shared.composition import api


def test_solid_sample_platemap_is_fetched_off_the_loop():
    seen = []

    def _blocking_fetch(plateid):
        seen.append(threading.get_ident())
        return [{"x": 1.0, "y": 2.0}]

    solid = object.__new__(sample_api.SolidSampleAPI)
    solid.legacyAPI = SimpleNamespace(  # type: ignore[assignment]
        get_platemap_plateid=_blocking_fetch
    )
    sample = SimpleNamespace(plate_id=1, sample_no=1)

    async def _run():
        main = threading.get_ident()
        pm = await solid.get_platemap([sample])  # type: ignore[list-item]
        xy = await solid.get_samples_xy([sample])  # type: ignore[list-item]
        return main, pm, xy

    main, pm, xy = asyncio.run(_run())

    assert pm == [[{"x": 1.0, "y": 2.0}]] and xy == [[1.0, 2.0]]
    assert seen and main not in seen, "platemap fetched on the event loop"


def test_aget_client_builds_the_client_off_the_loop(monkeypatch):
    seen = []

    def _get_client():
        seen.append(threading.get_ident())
        return "client"

    monkeypatch.setattr(api, "get_client", _get_client)

    async def _run():
        return threading.get_ident(), await api.aget_client()

    main, client = asyncio.run(_run())

    assert client == "client"
    assert seen and main not in seen, "spec fetch ran on the event loop"
