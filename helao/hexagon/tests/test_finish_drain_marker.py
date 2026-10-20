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


# --------------------------------------------------------------------------
# the drain itself, on a streamer over a real queue and the real logger loop
# --------------------------------------------------------------------------


class _Rig:
    """A ``NativeDataStreamer`` over a real ``MultisubscriberQueue``.

    ``active`` is the narrow fake the streamer needs; the logger is the real
    ``log_data_task``. ``puts`` counts every package put on the queue.
    """

    def __init__(self, streaming=True, write_delay=0.0):
        from types import SimpleNamespace
        from uuid import uuid4

        from helao.helpers.multisubscriber_queue import MultisubscriberQueue
        from helao.hexagon.adapters.native.data_stream import NativeDataStreamer

        self.key = uuid4()
        action = SimpleNamespace(
            save_data=True,
            action_uuid=uuid4(),
            action_name="rig",
            data_stream_status=HloStatus.active if streaming else None,
        )
        self.q = MultisubscriberQueue()
        self.puts = 0
        real_put = self.q.put

        async def _put(data):
            self.puts += 1
            await real_put(data)

        self.q.put = _put  # type: ignore[method-assign]
        file_conn = SimpleNamespace(
            file=object(),
            added_hlo_separator=True,
            params=SimpleNamespace(json_data_keys=["t"]),
        )

        async def _write(output_str, file_conn_key):
            await asyncio.sleep(write_delay)

        self.active = SimpleNamespace(
            base=SimpleNamespace(data_q=self.q),
            action=action,
            action_list=[action],
            listen_uuids=[action.action_uuid],
            file_conn_dict={self.key: file_conn},
            num_data_queued=0,
            num_data_written=0,
            data_logger=None,
            write_live_data=_write,
            _get_action_for_file_conn_key=lambda file_conn_key: action,
        )
        self.s = NativeDataStreamer(self.active)
        self.active.assemble_data_msg = self.s.assemble_data_msg

    def start_logger(self):
        self.active.data_logger = asyncio.create_task(self.s.log_data_task())

    def packet(self, t):
        return self.s.assemble_data_msg(
            DataModel(data={self.key: {"t": t}}, errors=[], status=HloStatus.active)
        )

    async def stop(self):
        task = self.active.data_logger
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_overlapping_drains_both_return():
    """``/estop`` finishing a session while the stopped executor finishes it too
    puts two drains on one streamer; neither may raise or lose its marker."""
    rig = _Rig()
    rig.start_logger()
    await asyncio.sleep(0.02)
    try:
        t1 = asyncio.create_task(rig.s.drain(1.0))
        t2 = asyncio.create_task(rig.s.drain(1.0))
        assert await t1 is True
        assert await t2 is True
        assert rig.s._drain_waiters == {}
    finally:
        await rig.stop()


@pytest.mark.asyncio
async def test_overlapping_drains_on_a_stuck_logger_each_use_their_own_bound():
    rig = _Rig()
    rig.active.data_logger = asyncio.create_task(asyncio.sleep(3600))  # alive, mute
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    short = asyncio.create_task(rig.s.drain(0.3))
    long_ = asyncio.create_task(rig.s.drain(0.6))
    try:
        assert await short is False
        t_short = loop.time() - t0
        assert await long_ is False
        t_long = loop.time() - t0
    finally:
        await rig.stop()
    assert 0.25 < t_short < 0.55
    assert t_long >= 0.55
    assert rig.s._drain_waiters == {}


@pytest.mark.asyncio
async def test_marker_is_resent_when_nothing_was_consumed():
    """A logger that subscribes after the first put never sees that marker."""
    rig = _Rig()
    drain = asyncio.create_task(rig.s.drain(1.0))
    rig.active.data_logger = asyncio.create_task(asyncio.sleep(3600))
    await asyncio.sleep(0.05)  # the first marker goes to nobody
    rig.active.data_logger.cancel()
    rig.start_logger()  # subscribes now
    try:
        assert await drain is True
    finally:
        await rig.stop()
    assert rig.puts >= 2


@pytest.mark.asyncio
async def test_marker_is_not_resent_while_the_logger_is_consuming():
    rig = _Rig(write_delay=0.06)
    rig.start_logger()
    await asyncio.sleep(0.02)
    for t in range(8):  # ~0.5 s of backlog ahead of the marker
        await rig.q.put(rig.packet(t))
        rig.active.num_data_queued += 1
    puts_before = rig.puts
    try:
        assert await rig.s.drain(3.0) is True
    finally:
        await rig.stop()
    assert rig.puts - puts_before == 1


@pytest.mark.asyncio
async def test_a_session_that_never_streamed_publishes_no_marker():
    rig = _Rig(streaming=False)
    rig.start_logger()
    await asyncio.sleep(0.02)
    loop = asyncio.get_running_loop()
    try:
        t0 = loop.time()
        assert await rig.s.drain(2.0) is True
        assert loop.time() - t0 < 0.05
    finally:
        await rig.stop()
    assert rig.puts == 0


@pytest.mark.asyncio
async def test_a_session_that_streamed_does_publish_the_marker():
    rig = _Rig(streaming=True)
    rig.start_logger()
    await asyncio.sleep(0.02)
    try:
        assert await rig.s.drain(2.0) is True
    finally:
        await rig.stop()
    assert rig.puts == 1


@pytest.mark.asyncio
async def test_a_failing_drain_still_closes_out_the_action(tmp_path):
    with _PatchedBaseGlobals([]):
        base, active = await _session(tmp_path, "faildrain")
        await active.enqueue_data_dflt({"t": 0, "v": 0})
        await _drain_data(active)

        async def _boom(timeout_s):
            raise RuntimeError("drain exploded")

        active.drain_data = _boom
        await asyncio.wait_for(active.finish(), 5.0)

        assert active.file_conn_dict == {}  # handles closed
        assert active.data_logger is not None and active.data_logger.done()
        (act_yml,) = glob.glob(str(tmp_path / "**" / "*-act.yml"), recursive=True)
        with open(act_yml, encoding="utf-8") as f:
            assert "finished" in f.read()
    assert len(_rows(tmp_path)) == 1
