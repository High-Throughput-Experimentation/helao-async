"""``enqueue_data_nowait`` is thread-safe: a foreign thread's put runs on the host loop.

The NI-DAQmx hardware callback calls ``enqueue_data_nowait`` from a vendor thread.
The package is built on the calling thread (so a row keeps the action that was current
when the hardware produced it), but the queue put is marshalled onto ``host.aloop``:

* in production order (a thread-safe pending deque, flushed FIFO);
* flushed by every on-loop enqueue and, unconditionally first, by ``drain``, so no
  cross-thread row lands behind the finish marker or is skipped by its guard;
* dropped with one WARNING if the loop is closed, never growing the deque.
"""

import asyncio
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

import pytest

import helao.hexagon.adapters.native.data_stream as data_stream_module
from helao.core.models.data import DataModel
from helao.core.models.hlostatus import HloStatus
from helao.core.tests.test_active_golden_master import (
    _active_params,
    _drain_data,
    _make_host,
    _mk_action,
    _PatchedBaseGlobals,
    _ticks,
)
from helao.hexagon.app.action_session import ActionSession

N = 20


async def _open(tmp_path: Path, name: str):
    trace: list = []
    base = _make_host(tmp_path / "RUNS", trace)
    action = _mk_action(name)
    active = ActionSession(base, _active_params(base, action))
    await active.myinit()
    await _ticks()
    return base, active, trace


def _put_threads(base: Any) -> list:
    """Thread id of every ``put_nowait`` (the golden master's recording queue)."""
    return base.data_q.put_threads


def _row(dflt: Any, i: int) -> DataModel:
    return DataModel(
        data={dflt: {"t": i, "v": i * 10}}, errors=[], status=HloStatus.active
    )


def _hlo_rows(root: Path) -> list[int]:
    """The ``t`` values of every data row, in file order."""
    (hlo,) = sorted(root.rglob("*.jsonl"))
    text = hlo.read_text(encoding="utf-8")
    body = text
    return [json.loads(line)["t"] for line in body.splitlines() if line.strip()]


@pytest.mark.asyncio
async def test_foreign_thread_puts_run_on_the_loop_thread(tmp_path) -> None:
    with _PatchedBaseGlobals([]):
        base, active, _ = await _open(tmp_path, "t1")
        dflt = base.dflt_file_conn_key()

        def worker() -> None:
            for i in range(1, N + 1):
                active.enqueue_data_nowait(_row(dflt, i))

        await asyncio.to_thread(worker)
        await _ticks()
        await _drain_data(active)
        await active.finish()
        await _ticks(10)
        loop_tid = threading.get_ident()
        assert _put_threads(base)
        assert all(t == loop_tid for t in _put_threads(base))
        assert _hlo_rows(tmp_path) == list(range(1, N + 1))


@pytest.mark.asyncio
async def test_foreign_thread_row_is_delivered_promptly(tmp_path) -> None:
    """Without a wake-up the selector sleeps and the row waits for the 1.0 s timer."""
    with _PatchedBaseGlobals([]):
        base, active, _ = await _open(tmp_path, "t2")
        dflt = base.dflt_file_conn_key()
        written = asyncio.Event()
        orig = active.write_live_data

        async def _write(output_str: str, file_conn_key: Any) -> None:
            await orig(output_str, file_conn_key)
            written.set()

        active.write_live_data = _write  # the logger calls it through the session
        loop = asyncio.get_running_loop()

        def _late_put() -> None:
            time.sleep(0.05)  # let the loop reach its select(), so only a wake-up helps
            active.enqueue_data_nowait(_row(dflt, 1))

        worker = threading.Thread(target=_late_put)
        t0 = loop.time()
        worker.start()  # not joined: the loop stays free to run
        try:
            await asyncio.wait_for(written.wait(), 1.0)
        except asyncio.TimeoutError:
            pass
        elapsed = loop.time() - t0
        worker.join()
        await _drain_data(active)
        await active.finish()
        assert written.is_set() and elapsed < 0.2, f"delivered after {elapsed:.3f}s"


@pytest.mark.asyncio
async def test_row_keeps_the_action_current_when_produced(
    tmp_path, monkeypatch
) -> None:
    """The package is built on the calling thread, before the put is marshalled."""
    with _PatchedBaseGlobals([]):
        base, active, _ = await _open(tmp_path, "t3")
        dflt = base.dflt_file_conn_key()
        packages: list = []
        orig_put = base.data_q.put_nowait

        def _spy(data: Any) -> None:
            if getattr(data, "datamodel", None) is not None and data.datamodel.data:
                packages.append(data)
            orig_put(data)

        monkeypatch.setattr(base.data_q, "put_nowait", _spy)
        pre_split = active.action.action_uuid
        worker = threading.Thread(
            target=lambda: active.enqueue_data_nowait(_row(dflt, 1))
        )
        worker.start()
        worker.join()  # the loop is blocked here: the marshalled put has not run yet
        await active.split(uuid_list=[])  # before yielding anywhere else
        await _ticks(
            10
        )  # not _drain_data: the skipped pre-split row never counts as written
        await active.finish()
        # Assert on the put record, not the .hlo: split() drops the old action's
        # uuid from listen_uuids without yielding, so an unconsumed pre-split row
        # is skipped by the logger whichever way it was built (pre-existing, F1).
        assert [p.action_uuid for p in packages] == [pre_split]


@pytest.mark.asyncio
async def test_no_tail_row_is_lost_before_the_marker(tmp_path) -> None:
    with _PatchedBaseGlobals([]):
        base, active, _ = await _open(tmp_path, "t4")
        dflt = base.dflt_file_conn_key()

        def worker() -> None:
            for i in range(1, N + 1):
                active.enqueue_data_nowait(_row(dflt, i))

        th = threading.Thread(target=worker)
        th.start()
        th.join()  # the loop is blocked: nothing marshalled has run
        active.enqueue_data_nowait(_row(dflt, N + 1))  # the runner's cleanup row
        await active.finish()  # no _ticks, no drain, no sleep
        await _ticks(10)
        assert _hlo_rows(tmp_path) == list(range(1, N + 2))


@pytest.mark.asyncio
async def test_no_tail_row_is_lost_without_an_on_loop_row(tmp_path) -> None:
    """Only ``drain``'s own flush can save these: nothing on the loop flushes first."""
    with _PatchedBaseGlobals([]):
        base, active, _ = await _open(tmp_path, "t4b")
        dflt = base.dflt_file_conn_key()

        def worker() -> None:
            for i in range(1, N + 1):
                active.enqueue_data_nowait(_row(dflt, i))

        th = threading.Thread(target=worker)
        th.start()
        th.join()
        await active.finish()
        await _ticks(10)
        assert _hlo_rows(tmp_path) == list(range(1, N + 1))


@pytest.mark.asyncio
async def test_closed_loop_drops_and_warns_once(tmp_path, caplog) -> None:
    with _PatchedBaseGlobals([]):
        base, active, _ = await _open(tmp_path, "t5")
        dflt = base.dflt_file_conn_key()
        live = base.aloop
        scratch = asyncio.new_event_loop()
        scratch.close()
        base.aloop = scratch
        puts_before = len(_put_threads(base))
        lg = data_stream_module.LOGGER
        lg.addHandler(caplog.handler)
        try:
            for i in (1, 2):
                th = threading.Thread(
                    target=lambda i=i: active.enqueue_data_nowait(_row(dflt, i))
                )
                th.start()
                th.join()
        finally:
            lg.removeHandler(caplog.handler)
            base.aloop = live
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert len(_put_threads(base)) == puts_before
        assert not active.data_stream._xthread
        await active.finish()


@pytest.mark.asyncio
async def test_thread_with_its_own_loop_is_marshalled(tmp_path) -> None:
    """A vendor thread that runs its own event loop is still foreign.

    ``running is None`` would treat it as on-loop; the test is "the running loop is
    not ``host.aloop``".
    """
    with _PatchedBaseGlobals([]):
        base, active, _ = await _open(tmp_path, "t6")
        dflt = base.dflt_file_conn_key()

        async def other_loop() -> None:
            active.enqueue_data_nowait(_row(dflt, 1))

        th = threading.Thread(target=lambda: asyncio.run(other_loop()))
        th.start()
        th.join()
        await _ticks()
        tid = threading.get_ident()
        assert _put_threads(base) and all(t == tid for t in _put_threads(base))
        await _drain_data(active)
        await active.finish()
