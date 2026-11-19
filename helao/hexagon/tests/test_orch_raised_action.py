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


async def _fail_unknown(world_cfg, A, **kw):
    return None, ErrorCodes.unspecified  # sent, outcome unknown: may be running


@pytest.mark.asyncio
async def test_transport_error_keeps_waiting_for_the_running_action(monkeypatch):
    orch, runtime, ing = _setup()
    gsm = orch.globalstatusmodel
    x = uuid4()
    await ing.update_status(actionservermodel=_asm(_act(x, [HloStatus.active])))
    gsm.loop_state = LoopStatus.started
    _patch(monkeypatch, _fail_unknown)
    await DispatchRunner(orch)._dispatch_action_locked(_act(x, []))
    assert x in gsm.active_dict  # not retired: the action may still be running
    loop = HexDispatchLoop(runtime)
    loop.start()
    gsm.loop_state = LoopStatus.stopped
    try:
        await runtime.handle(StartRequested())
        await asyncio.sleep(0.4)
        assert gsm.loop_state == LoopStatus.started  # drain still waiting
        await ing.update_status(
            actionservermodel=_asm(
                _act(x, [HloStatus.active, HloStatus.finished]), False
            )
        )
        await _until(lambda: gsm.loop_state == LoopStatus.stopped)
    finally:
        await loop.close()


@pytest.mark.asyncio
async def test_late_active_push_after_500_is_ignored_until_redispatch(monkeypatch):
    orch, runtime, ing = _setup()
    gsm = orch.globalstatusmodel
    x = uuid4()
    gsm.loop_state = LoopStatus.started
    _patch(monkeypatch, _fail)
    await DispatchRunner(orch)._dispatch_action_locked(_act(x, []))  # 500 first
    await ing.update_status(actionservermodel=_asm(_act(x, [HloStatus.active])))
    assert x not in gsm.active_dict and gsm.actions_idle()

    async def ok(world_cfg, B, **kw):
        return _act(x, [HloStatus.active]).as_dict(), ErrorCodes.none

    _patch(monkeypatch, ok)
    await DispatchRunner(orch)._dispatch_action_locked(orch.action_dq[0])
    assert x in gsm.active_dict  # re-dispatch registers it
    await ing.update_status(actionservermodel=_asm(_act(x, [HloStatus.active])))
    assert x in gsm.active_dict  # and its own active pushes count again


@pytest.mark.parametrize("variant", ["errored_before_drain", "errored_during_drain"])
@pytest.mark.asyncio
async def test_stop_drain_ends_after_an_errored_action(variant):
    """An action that ends errored leaves orch_state at error; the stop drain
    used to wait for idle forever and hot-spin (bounded here by wait_for)."""
    orch, runtime, ing = _setup()
    gsm = orch.globalstatusmodel
    x = uuid4()
    term = [HloStatus.active, HloStatus.errored, HloStatus.finished]
    await ing.update_status(actionservermodel=_asm(_act(x, [HloStatus.active])))
    loop = HexDispatchLoop(runtime)
    loop.start()
    orch.action_dq = ["requeued"]
    try:
        if variant == "errored_before_drain":
            gsm.loop_state = LoopStatus.started
            await ing.update_status(actionservermodel=_asm(_act(x, term), False))
            gsm.loop_state = LoopStatus.stopped
        gsm.loop_intent = LoopIntent.stop
        await runtime.handle(StartRequested())
        await asyncio.sleep(0.1)
        if variant == "errored_during_drain":
            await ing.update_status(actionservermodel=_asm(_act(x, term), False))
        await _until(lambda: gsm.loop_state == LoopStatus.stopped)
    finally:
        await loop.close()
