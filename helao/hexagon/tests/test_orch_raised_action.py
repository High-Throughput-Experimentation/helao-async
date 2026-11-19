"""A dispatch that answers 500 after the action published ``active``.

The action server's handler raised, so no terminal status will ever clear the
uuid the orchestrator registered as active. The orchestrator pauses and
re-queues the action; its stop drain must still complete (not wait forever on
that stale uuid), and on resume the same uuid must be re-dispatched and
re-registered as active so a following ``wait_for_all`` action waits on it.
Real HexRuntime + HexDispatchLoop + HexStatusIngestion over a real
GlobalStatusModel; only the HTTP dispatcher is stubbed.
"""

import asyncio
from collections import deque
from uuid import uuid4

import pytest

from helao.core.error import ErrorCodes
from helao.core.models.hlostatus import HloStatus
from helao.core.models.orchstatus import LoopIntent, LoopStatus
from helao.hexagon.app.dispatch_loop import HexDispatchLoop
from helao.hexagon.app.ingestion import HexStatusIngestion
from helao.hexagon.app.orch_dispatch import DispatchRunner
from helao.hexagon.domain.orchestration import (
    EstopRequested,
    StartRequested,
    StopRequested,
)
from helao.hexagon.tests.test_ingestion import _act, _asm, _monitor_setup


def _setup():
    orch, _w, _e, mon = _monitor_setup(bad=set())
    runtime = mon.runtime
    orch._hex_runtime = runtime
    orch.world_cfg = {}
    orch.action_dq = deque()
    orch.last_action_uuid = None
    orch.lbuf_nowait = []
    orch.track_action_uuid = lambda u: None
    orch.put_lbuf_nowait = orch.lbuf_nowait.append

    async def stop():
        if orch.globalstatusmodel.loop_state == LoopStatus.started:
            await runtime.handle(StopRequested())

    orch.stop = stop
    return orch, runtime, HexStatusIngestion(orch, runtime)


def _patch(monkeypatch, fn):
    import helao.helpers.dispatcher as d

    monkeypatch.setattr(d, "async_action_dispatcher", fn, raising=True)


async def _fail(world_cfg, A, **kw):
    return None, ErrorCodes.http


async def _until(pred, t=3.0):
    async def w():
        while not pred():
            await asyncio.sleep(0.02)

    await asyncio.wait_for(w(), t)


async def _publish_active_then_fail(orch, ing, monkeypatch, x):
    """X publishes active, then its dispatch answers 500 (loop started)."""
    gsm = orch.globalstatusmodel
    await ing.update_status(actionservermodel=_asm(_act(x, [HloStatus.active])))
    gsm.loop_state = LoopStatus.started
    _patch(monkeypatch, _fail)
    A = _act(x, [])
    rc, res = await DispatchRunner(orch)._dispatch_action_locked(A)
    assert rc == ErrorCodes.none and res is None
    return A


@pytest.mark.asyncio
async def test_stop_drain_completes_after_dispatch_500(monkeypatch):
    orch, runtime, ing = _setup()
    gsm = orch.globalstatusmodel
    x = uuid4()
    A = await _publish_active_then_fail(orch, ing, monkeypatch, x)
    assert orch.action_dq[0] is A and gsm.loop_intent == LoopIntent.stop
    assert x not in gsm.active_dict
    assert x in gsm.nonactive_dict[HloStatus.skipped]
    loop = HexDispatchLoop(runtime)
    loop.start()
    gsm.loop_state = LoopStatus.stopped  # StartRequested only acts from stopped
    try:
        await runtime.handle(StartRequested())
        await _until(lambda: gsm.loop_state == LoopStatus.stopped)
    finally:
        await loop.close()
    assert orch.action_dq[0] is A  # still re-queued at the head


@pytest.mark.asyncio
async def test_resume_redispatches_same_uuid_and_registers_it(monkeypatch):
    orch, runtime, ing = _setup()
    gsm = orch.globalstatusmodel
    x = uuid4()
    A = await _publish_active_then_fail(orch, ing, monkeypatch, x)
    seen = []

    async def ok(world_cfg, B, **kw):
        seen.append(B.action_uuid)
        return _act(x, [HloStatus.active]).as_dict(), ErrorCodes.none

    _patch(monkeypatch, ok)
    rc, res = await DispatchRunner(orch)._dispatch_action_locked(orch.action_dq[0])
    assert rc is None and seen == [x]
    # self-registered as active: a following wait_for_all action must wait
    assert x in gsm.active_dict and not gsm.actions_idle()
    ep = next(iter(gsm.server_dict.values())).endpoints["acquire"]
    assert x in ep.active_dict
    # its own terminal status clears it
    await ing.update_status(
        actionservermodel=_asm(_act(x, [HloStatus.active, HloStatus.finished]), False)
    )
    assert gsm.actions_idle()


@pytest.mark.asyncio
async def test_estop_during_drain_after_dispatch_500_still_estops(monkeypatch):
    orch, runtime, ing = _setup()
    gsm = orch.globalstatusmodel
    x, y = uuid4(), uuid4()
    # an unrelated action Y keeps the drain parked
    ep_y = _act(y, [HloStatus.active])
    ep_y.action_name = "acquire"
    await ing.update_status(actionservermodel=_asm(ep_y))
    await _publish_active_then_fail(orch, ing, monkeypatch, x)
    loop = HexDispatchLoop(runtime)
    loop.start()
    gsm.loop_state = LoopStatus.stopped  # StartRequested only acts from stopped
    try:
        await runtime.handle(StartRequested())
        await asyncio.sleep(0.2)
        assert gsm.loop_state == LoopStatus.started and y in gsm.active_dict
        await runtime.handle(EstopRequested(reason="test", operator=True))
        await _until(lambda: gsm.loop_state == LoopStatus.estopped)
    finally:
        await loop.close()
