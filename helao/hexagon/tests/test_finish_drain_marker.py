"""C4b: ``finish()`` drains the data logger by a marker round-trip, with two bounds.

The old drain was two loops of 5 x 0.1 s: a logger slower than that lost every
packet still queued at finish, silently. Now ``finish`` puts one data-less marker
behind everything already queued and waits for the logger to consume it (the
queue is FIFO), up to ``FINISH_DRAIN_TIMEOUT_S`` (10 s), or
``ESTOP_FINISH_DRAIN_TIMEOUT_S`` (1 s) on an E-STOP path, because ``/estop``
finishes a server's sessions one after another inside a single 10 s RPC.

There is no pytest-timeout plugin in the env, so every finish is bounded with
``asyncio.wait_for``.
"""

import asyncio
import glob
import logging

import pytest

import helao.hexagon.adapters.native.data_stream as data_stream_module
import helao.hexagon.adapters.native.finalizer as finalizer_module
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


async def _session(tmp_path, name, **overrides):
    """An opened session (data logger running) on the golden-master host."""
    trace: list = []
    base = _make_host(tmp_path / "RUNS", trace)
    action = _mk_action(name, **overrides)
    active = ActionSession(base, _active_params(base, action))
    await active.myinit()
    await _ticks()
    return base, active


def _hang_the_logger(active):
    """Make every logger write block on an event nothing ever sets."""
    never = asyncio.Event()

    async def _write(output_str, file_conn_key):
        await never.wait()

    active.write_live_data = _write


def _rows(tmp_path) -> list:
    (path,) = glob.glob(str(tmp_path / "**" / "*.hlo"), recursive=True)
    with open(path, encoding="utf-8") as f:
        text = f.read()
    return [ln for ln in text.split("%%\n", 1)[1].splitlines() if ln.strip()]


@pytest.mark.asyncio
async def test_slow_logger_loses_nothing_queued_before_finish(tmp_path):
    with _PatchedBaseGlobals([]):
        base, active = await _session(tmp_path, "slowlog")
        orig = active.write_live_data

        async def _slow(output_str, file_conn_key):
            await asyncio.sleep(0.15)
            await orig(output_str=output_str, file_conn_key=file_conn_key)

        active.write_live_data = _slow
        dflt = base.dflt_file_conn_key()
        await active.enqueue_data_dflt({"t": 0, "v": 0})
        await _drain_data(active)
        for t in range(1, 11):
            active.enqueue_data_nowait(
                DataModel(
                    data={dflt: {"t": t, "v": t * 10}},
                    errors=[],
                    status=HloStatus.active,
                )
            )

        await asyncio.wait_for(active.finish(), 5.0)

    # the old 2 x 5 x 0.1 s window fit only about 6 of the 10 late rows
    assert len(_rows(tmp_path)) == 11


@pytest.mark.asyncio
async def test_dead_logger_skips_the_wait(tmp_path, monkeypatch):
    monkeypatch.setattr(finalizer_module, "FINISH_DRAIN_TIMEOUT_S", 2.0, raising=True)
    with _PatchedBaseGlobals([]):
        _, active = await _session(tmp_path, "deadlog", save_data=False)
        loop = asyncio.get_running_loop()

        t0 = loop.time()
        await active.drain_data(2.0)
        assert loop.time() - t0 < 0.1

        await asyncio.wait_for(active.finish(), 2.0)


async def _finish_with_a_hung_logger(tmp_path, name, estop):
    with _PatchedBaseGlobals([]):
        _, active = await _session(tmp_path, name)
        _hang_the_logger(active)
        await active.enqueue_data_dflt({"t": 0, "v": 0})
        await asyncio.sleep(0.05)  # the logger is now parked inside the write
        if estop:
            active.set_estop()
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        await asyncio.wait_for(active.finish(), 2.0 if not estop else 1.5)
        return loop.time() - t0


@pytest.mark.asyncio
async def test_hung_logger_is_bounded_and_warns(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(finalizer_module, "FINISH_DRAIN_TIMEOUT_S", 0.4, raising=True)
    caplog.set_level(logging.WARNING)
    # make_logger sets propagate=False: attach caplog's handler directly
    data_stream_module.LOGGER.addHandler(caplog.handler)
    try:
        took = await _finish_with_a_hung_logger(tmp_path, "hung", estop=False)
    finally:
        data_stream_module.LOGGER.removeHandler(caplog.handler)

    assert took < 0.4 + 0.3
    warns = [r for r in caplog.records if "finish drain timed out" in r.getMessage()]
    assert len(warns) == 1


@pytest.mark.asyncio
async def test_estop_finish_uses_the_short_bound(tmp_path, monkeypatch, caplog):
    # the patch only makes the dependency explicit; 1.0 is the real value
    monkeypatch.setattr(
        finalizer_module, "ESTOP_FINISH_DRAIN_TIMEOUT_S", 1.0, raising=True
    )
    assert finalizer_module.FINISH_DRAIN_TIMEOUT_S == 10.0
    caplog.set_level(logging.WARNING)
    data_stream_module.LOGGER.addHandler(caplog.handler)
    try:
        await _finish_with_a_hung_logger(tmp_path, "estophung", estop=True)
    finally:
        data_stream_module.LOGGER.removeHandler(caplog.handler)

    (warn,) = [r for r in caplog.records if "finish drain timed out" in r.getMessage()]
    assert "after 1.0s" in warn.getMessage()
