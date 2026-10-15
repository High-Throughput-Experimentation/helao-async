"""Concurrent calls on one SampleModelAPI must not interleave their db sessions.

The "lock" used to be a fresh ``asyncio.Lock()`` per call, which excludes
nothing, so two coroutines shared ``self._con``/``self._cur`` and one closed the
other's connection mid-query.
"""

import asyncio
import types

import pytest

from helao.helpers.sample_api import LiquidSampleAPI


@pytest.mark.asyncio
async def test_concurrent_calls_do_not_overlap_db_sessions(tmp_path):
    serv = types.SimpleNamespace(helaodirs=types.SimpleNamespace(db_root=str(tmp_path)))
    api = LiquidSampleAPI(serv)
    await api.init_db()

    open_now = 0
    max_open = 0
    orig_open, orig_close = api._open_db, api._close_db

    async def _open():
        nonlocal open_now, max_open
        await orig_open()
        open_now += 1
        max_open = max(max_open, open_now)
        await asyncio.sleep(0.05)

    def _close():
        nonlocal open_now
        open_now -= 1
        orig_close()

    api._open_db, api._close_db = _open, _close
    counts = await asyncio.gather(*(api.count_samples() for _ in range(3)))
    assert counts == [0, 0, 0]
    assert max_open == 1
