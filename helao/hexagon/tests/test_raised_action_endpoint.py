"""A handler that raises after ``ctx.begin()`` must not wedge its endpoint.

The raised action's uuid used to stay in the endpoint's ``active_dict`` forever
(nothing published a terminal status), so with ``log_status_task`` running every
later request on that endpoint was parked behind it.
"""

import asyncio
import uuid as uuidlib

import httpx
import pytest

from helao.hexagon.app.action_context import ActionContext
from helao.hexagon.tests.test_action_middleware import _host


@pytest.mark.asyncio
async def test_raised_handler_frees_endpoint():
    host = _host()
    calls = []

    @host.action()
    async def slow(ctx: ActionContext):
        active = await ctx.begin()
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("motion timeout")
        fin = await active.finish()
        return fin.as_dict()

    await host.init_endpoint_status()
    task = asyncio.create_task(host.log_status_task())
    await asyncio.sleep(0.1)
    x = str(uuidlib.uuid4())
    transport = httpx.ASGITransport(app=host, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            r1 = await c.post("/SIM/slow", json={"action": {"action_uuid": x}})
            assert r1.status_code == 500
            await asyncio.sleep(0.3)
            ep = host.actionservermodel.endpoints["slow"]
            assert not ep.active_dict
            for u in (x, str(uuidlib.uuid4())):
                r = await asyncio.wait_for(
                    c.post("/SIM/slow", json={"action": {"action_uuid": u}}), 5
                )
                assert r.status_code == 200
                assert not (r.json().get("action_params") or {}).get(
                    "queued_on_actserv"
                )
            await asyncio.sleep(0.5)
            assert len(calls) == 3
            assert not host.endpoint_queues["slow"]
            assert not ep.active_dict
    finally:
        task.cancel()


def _terminal(q, x):
    out = []
    while not q.empty():
        m = q.get_nowait()
        if str(m.action_uuid) == x and "finished" in [
            str(s.value) for s in m.action_status
        ]:
            out.append(m)
    return out


@pytest.mark.asyncio
async def test_raise_publishes_no_status():
    host = _host()

    @host.action()
    async def slow(ctx: ActionContext):
        await ctx.begin()
        raise RuntimeError("boom")

    await host.init_endpoint_status()
    task = asyncio.create_task(host.log_status_task())
    q = host.status_q.queue()
    await asyncio.sleep(0.1)
    x = str(uuidlib.uuid4())
    transport = httpx.ASGITransport(app=host, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            r = await c.post("/SIM/slow", json={"action": {"action_uuid": x}})
            assert r.status_code == 500
            await asyncio.sleep(0.3)
            assert not host.actionservermodel.endpoints["slow"].active_dict
            assert _terminal(q, x) == []
    finally:
        task.cancel()


@pytest.mark.asyncio
async def test_raise_with_live_executor_keeps_endpoint_busy():
    from helao.hexagon.app.orch_wait import WaitExec

    host = _host()
    host.aloop = asyncio.get_running_loop()
    runs = []

    @host.action()
    async def slow(ctx: ActionContext):
        active = await ctx.begin()
        runs.append(1)
        active.action.action_params["waittime"] = 1.0
        if len(runs) == 1:
            active.start_executor(WaitExec(active=active, oneoff=False, poll_rate=0.05))
            await asyncio.sleep(0.1)
            raise RuntimeError("raised after starting executor")
        fin = await active.finish()
        return fin.as_dict()

    await host.init_endpoint_status()
    task = asyncio.create_task(host.log_status_task())
    q = host.status_q.queue()
    await asyncio.sleep(0.1)
    x = str(uuidlib.uuid4())
    transport = httpx.ASGITransport(app=host, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            r1 = await c.post("/SIM/slow", json={"action": {"action_uuid": x}})
            assert r1.status_code == 500
            await asyncio.sleep(0.3)
            ep = host.actionservermodel.endpoints["slow"]
            assert host.executors and x in {str(k) for k in ep.active_dict}
            r2 = await c.post(
                "/SIM/slow", json={"action": {"action_uuid": str(uuidlib.uuid4())}}
            )
            assert r2.json()["action_params"].get("queued_on_actserv")
            await asyncio.sleep(2.5)
            assert len(_terminal(q, x)) == 1
            assert not host.endpoint_queues["slow"]
    finally:
        task.cancel()


@pytest.mark.asyncio
async def test_parked_actions_never_run_concurrently_after_raise():
    """X raises with P, Q parked and a status subscriber attached: P and Q must
    run one after the other (the drain is serialized with log_status_task)."""
    import helao.hexagon.app.endpoint_manager as em
    from helao.core.error import ErrorCodes

    host = _host()
    host.aloop = asyncio.get_running_loop()
    tr = httpx.ASGITransport(app=host, raise_app_exceptions=False)
    c = httpx.AsyncClient(transport=tr, base_url="http://t", timeout=30)

    async def fake_dispatch(world, A, params=None, **kw):
        r = await c.post(f"/SIM/{A.action_name}", json={"action": A.as_dict()})
        return r.json(), None

    orig = em.async_action_dispatcher
    em.async_action_dispatcher = fake_dispatch
    gate = asyncio.Event()
    inflight = {"n": 0, "max": 0, "ran": []}

    @host.action()
    async def slow(ctx: ActionContext):
        active = await ctx.begin()
        tag = active.action.action_params.get("tag")
        if tag == "X":
            await gate.wait()
            raise RuntimeError("motion timeout")
        inflight["n"] += 1
        inflight["max"] = max(inflight["max"], inflight["n"])
        inflight["ran"].append(tag)
        await asyncio.sleep(0.5)
        inflight["n"] -= 1
        fin = await active.finish()
        return fin.as_dict()

    async def fake_send(**kw):
        await asyncio.sleep(0.05)  # a subscriber's round trip
        return {"ok": True}, ErrorCodes.none

    host.send_statuspackage = fake_send
    host.status_clients.add(("ORCH", "127.0.0.1", 1))
    await host.init_endpoint_status()
    t = asyncio.create_task(host.log_status_task())
    await asyncio.sleep(0.1)

    def body(tag):
        return {
            "action": {
                "action_uuid": str(uuidlib.uuid4()),
                "action_params": {"tag": tag},
            }
        }

    try:
        rx = asyncio.create_task(c.post("/SIM/slow", json=body("X")))
        await asyncio.sleep(0.3)
        await c.post("/SIM/slow", json=body("P"))
        await asyncio.sleep(0.5)
        rq = asyncio.create_task(c.post("/SIM/slow", json=body("Q")))
        await asyncio.sleep(0)
        gate.set()
        await rq
        assert (await rx).status_code == 500
        await asyncio.sleep(4)
        assert inflight["ran"] == ["P", "Q"]
        assert inflight["max"] == 1
    finally:
        em.async_action_dispatcher = orig
        t.cancel()
        await c.aclose()


@pytest.mark.asyncio
async def test_raise_after_split_frees_endpoint():
    host = _host()
    host.aloop = asyncio.get_running_loop()
    calls = []

    @host.action()
    async def slow(ctx: ActionContext):
        active = await ctx.begin()
        calls.append(1)
        if len(calls) == 1:
            await active.split()
            await asyncio.sleep(0.2)
            raise RuntimeError("raise after split")
        fin = await active.finish()
        return fin.as_dict()

    await host.init_endpoint_status()
    task = asyncio.create_task(host.log_status_task())
    await asyncio.sleep(0.1)
    transport = httpx.ASGITransport(app=host, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            r1 = await c.post(
                "/SIM/slow", json={"action": {"action_uuid": str(uuidlib.uuid4())}}
            )
            assert r1.status_code == 500
            await asyncio.sleep(0.5)
            assert not host.actionservermodel.endpoints["slow"].active_dict
            r2 = await asyncio.wait_for(
                c.post(
                    "/SIM/slow", json={"action": {"action_uuid": str(uuidlib.uuid4())}}
                ),
                5,
            )
            assert not (r2.json().get("action_params") or {}).get("queued_on_actserv")
    finally:
        task.cancel()
