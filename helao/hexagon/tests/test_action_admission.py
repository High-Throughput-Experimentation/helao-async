"""Action admission, shared by the HTTP middleware and the RPC fast path.

The production fault: ``async_action_dispatcher`` probes over RPC, the probe
times out on any handler slower than the probe, and the same action is re-POSTed
over HTTP. The RPC handler keeps running, so the action ran twice. These tests
drive both transports against one host and assert on what ran and what uuid
came back, never on registration.
"""

import asyncio
import contextlib
import socket
import uuid as uuidlib

import httpx
import pytest
import uvicorn
from fastapi.routing import APIRoute

from helao.core.error import ErrorCodes
from helao.core.models.action_start_condition import ActionStartCondition as ASC
from helao.core.models.hlostatus import HloStatus
from helao.core.models.machine import MachineModel
from helao.core.rpc import RPCClient, RPCError, RPCHandlerError, derive_rpc_port
from helao.core.rpc.zmq_rpc import (
    RPC_PORT_OFFSET,
    RPCRequest,
    _REQ_ENCODER,
    _RESP_DECODER,
)
from helao.helpers import dispatcher
from helao.helpers.premodels import Action
from helao.hexagon.app.action_context import ActionContext
from helao.hexagon.tests.test_action_middleware import _client, _host


def _free_http_port() -> int:
    """A port whose derived RPC port is also free (best effort)."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    rpc_port = s.getsockname()[1]
    s.close()
    return rpc_port - RPC_PORT_OFFSET


def _uid() -> str:
    return str(uuidlib.uuid4())


def _busy(host, endpoint="slow"):
    host.actionservermodel.endpoints[endpoint].active_dict["u1"] = object()


class _Counter:
    """A handler body that counts runs and can be held open."""

    def __init__(self, hold: float = 0.0):
        self.runs = 0
        self.hold = hold
        self.started = asyncio.Event()

    async def __call__(self):
        self.runs += 1
        self.started.set()
        await asyncio.sleep(self.hold)
        return {"ok": True}


def _slow_host(counter, **server_params):
    host = _host(**server_params)

    @host.action()
    async def slow(ctx: ActionContext):
        return await counter()

    return host


# --- a: _park keeps the uuid and carries a real action_server -----------------


@pytest.mark.asyncio
async def test_a_parked_action_keeps_its_uuid_and_has_a_real_server():
    host = _slow_host(_Counter())
    await host.init_endpoint_status()
    _busy(host)
    x = _uid()
    async with _client(host) as c:
        resp = await c.post("/SIM/slow", json={"action": {"action_uuid": x}})
    assert resp.json()["action_uuid"] == x
    ((queued, _),) = list(host.endpoint_queues["slow"])
    assert str(queued.action_uuid) == x
    assert queued.action_server.hostname == "127.0.0.1"
    assert queued.action_server.port == 8002
    assert "None" not in queued.url


@pytest.mark.asyncio
async def test_a_parked_action_without_a_uuid_gets_a_generated_one():
    host = _slow_host(_Counter())
    await host.init_endpoint_status()
    _busy(host)
    async with _client(host) as c:
        resp = await c.post("/SIM/slow", json={"action": {}})
        resp2 = await c.post("/SIM/slow", json={"action": {"action_uuid": None}})
    u1, u2 = resp.json()["action_uuid"], resp2.json()["action_uuid"]
    assert u1 and u2 and u1 != u2
    uuidlib.UUID(u1)
    uuidlib.UUID(u2)


# --- b: HTTP duplicates --------------------------------------------------------


@pytest.mark.asyncio
async def test_b_a_repeat_while_running_and_after_finish_is_not_run_again():
    counter = _Counter(hold=0.3)
    host = _slow_host(counter)
    await host.init_endpoint_status()
    x = _uid()
    body = {"action": {"action_uuid": x}}
    async with _client(host) as c:
        first = asyncio.create_task(c.post("/SIM/slow", json=body))
        await counter.started.wait()
        during = await c.post("/SIM/slow", json=body)
        assert counter.runs == 1, "a repeat of a running action ran the handler"
        assert (await first).json() == {"ok": True}
        after = await c.post("/SIM/slow", json=body)
    assert during.json() == {"ok": True}, "the repeat lost the real result"
    assert after.json() == {"ok": True}
    assert counter.runs == 1, "a repeat of a finished action ran the handler"


@pytest.mark.asyncio
async def test_b_a_repeat_of_a_parked_action_is_not_parked_again():
    host = _slow_host(_Counter())
    await host.init_endpoint_status()
    _busy(host)
    x = _uid()
    body = {"action": {"action_uuid": x}}
    async with _client(host) as c:
        await c.post("/SIM/slow", json=body)
        again = await c.post("/SIM/slow", json=body)
    assert again.json()["action_uuid"] == x
    assert len(host.endpoint_queues["slow"]) == 1


@pytest.mark.asyncio
async def test_b_two_actions_with_different_uuids_both_run():
    counter = _Counter()
    host = _slow_host(counter)
    await host.init_endpoint_status()
    async with _client(host) as c:
        await c.post("/SIM/slow", json={"action": {"action_uuid": _uid()}})
        await c.post("/SIM/slow", json={"action": {"action_uuid": _uid()}})
    assert counter.runs == 2


@pytest.mark.asyncio
async def test_b_a_failed_action_can_be_retried_with_its_uuid():
    runs = []
    host = _host()

    @host.action()
    async def slow(ctx: ActionContext):
        runs.append(1)
        if len(runs) == 1:
            raise ValueError("driver fell over")
        return {"ok": True}

    await host.init_endpoint_status()
    body = {"action": {"action_uuid": _uid()}}
    transport = httpx.ASGITransport(app=host, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        assert (await c.post("/SIM/slow", json=body)).status_code == 500
        retry = await asyncio.wait_for(c.post("/SIM/slow", json=body), 5)
    assert retry.json() == {"ok": True}
    assert len(runs) == 2


@pytest.mark.asyncio
async def test_b_a_repeat_of_a_running_action_that_fails_fails_too():
    started = asyncio.Event()
    host = _host()

    @host.action()
    async def slow(ctx: ActionContext):
        started.set()
        await asyncio.sleep(0.3)
        raise ValueError("driver fell over")

    await host.init_endpoint_status()
    body = {"action": {"action_uuid": _uid()}}
    transport = httpx.ASGITransport(app=host, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        first = asyncio.create_task(c.post("/SIM/slow", json=body))
        await started.wait()
        during = await asyncio.wait_for(c.post("/SIM/slow", json=body), 5)
        assert (await asyncio.wait_for(first, 5)).status_code == 500
    assert during.status_code == 500, "a repeat reported success for a failed action"


@pytest.mark.asyncio
async def test_b_a_repeat_is_answered_from_a_real_session_then_history():
    counter = _Counter()
    host = _slow_host(counter)
    await host.init_endpoint_status()
    x = uuidlib.UUID(_uid())
    session = await host.begin_session(Action(action_uuid=x, action_name="slow"))
    body = {"action": {"action_uuid": str(x)}}
    async with _client(host) as c:
        live = await c.post("/SIM/slow", json=body)
        host.history[x] = host.actives.pop(x).action
        done = await c.post("/SIM/slow", json=body)
    assert session.action.action_uuid == x
    assert live.json()["action_uuid"] == str(x), "not answered from host.actives"
    assert done.json()["action_uuid"] == str(x), "not answered from host.history"
    assert counter.runs == 0


# --- c: RPC ---------------------------------------------------------------------


async def _serve_rpc(host):
    """Mirror HelaoFastAPI._rpc_startup's registration on a free RPC port."""
    for route in host.routes:
        if isinstance(route, APIRoute) and "POST" in (route.methods or ()):
            host.rpc_dispatcher.register(route.path, route.endpoint)
    http_port = _free_http_port()
    endpoint = f"tcp://127.0.0.1:{derive_rpc_port(http_port)}"
    await host.rpc_dispatcher.serve("127.0.0.1", derive_rpc_port(http_port))
    return RPCClient(endpoint, default_timeout=5.0)


@pytest.mark.asyncio
async def test_c_rpc_busy_endpoint_parks_and_keeps_the_uuid():
    counter = _Counter()
    host = _slow_host(counter)
    await host.init_endpoint_status()
    _busy(host)
    client = await _serve_rpc(host)
    x = _uid()
    try:
        result = await client.call(
            "SIM/slow", args={"action": Action(action_uuid=uuidlib.UUID(x)).as_dict()}
        )
    finally:
        await host.rpc_dispatcher.close()
    assert result["action_uuid"] == x
    assert counter.runs == 0
    ((queued, _),) = list(host.endpoint_queues["slow"])
    assert str(queued.action_uuid) == x and "None" not in queued.url


@pytest.mark.asyncio
async def test_c_rpc_repeat_returns_the_existing_record():
    counter = _Counter(hold=0.3)
    host = _slow_host(counter)
    await host.init_endpoint_status()
    client = await _serve_rpc(host)
    x = _uid()
    args = {"action": Action(action_uuid=uuidlib.UUID(x)).as_dict()}
    try:
        first = asyncio.create_task(client.call("SIM/slow", args=args))
        await counter.started.wait()
        during = await client.call("SIM/slow", args=args)
        assert counter.runs == 1
        assert await first == {"ok": True}
        after = await client.call("SIM/slow", args=args)
    finally:
        await host.rpc_dispatcher.close()
    assert during == {"ok": True}, "the repeat lost the real result"
    assert after == {"ok": True}
    assert counter.runs == 1


@pytest.mark.asyncio
async def test_c_rpc_failed_action_can_be_retried_by_a_new_request():
    runs = []
    host = _host()

    @host.action()
    async def slow(ctx: ActionContext):
        runs.append(1)
        if len(runs) == 1:
            raise ValueError("driver fell over")
        return {"ok": True}

    await host.init_endpoint_status()
    client = await _serve_rpc(host)
    args = {"action": Action(action_uuid=uuidlib.UUID(_uid())).as_dict()}
    try:
        with pytest.raises(RPCHandlerError):
            await client.call("SIM/slow", args=args)
        # an explicit new request may reuse the uuid; the dispatcher never does
        assert await client.call("SIM/slow", args=args) == {"ok": True}
    finally:
        await host.rpc_dispatcher.close()
    assert len(runs) == 2


@pytest.mark.asyncio
async def test_c_rpc_repeat_of_a_running_action_that_fails_fails_too():
    started = asyncio.Event()
    host = _host()

    @host.action()
    async def slow(ctx: ActionContext):
        started.set()
        await asyncio.sleep(0.3)
        raise ValueError("driver fell over")

    await host.init_endpoint_status()
    client = await _serve_rpc(host)
    args = {"action": Action(action_uuid=uuidlib.UUID(_uid())).as_dict()}
    try:
        first = asyncio.create_task(client.call("SIM/slow", args=args))
        await started.wait()
        with pytest.raises(RPCHandlerError):
            await asyncio.wait_for(client.call("SIM/slow", args=args), 5)
        with pytest.raises(RPCHandlerError):
            await asyncio.wait_for(first, 5)
    finally:
        await host.rpc_dispatcher.close()


@pytest.mark.asyncio
async def test_c_an_unknown_rpc_method_is_not_a_handler_error():
    host = _host()
    await host.init_endpoint_status()
    client = await _serve_rpc(host)
    try:
        with pytest.raises(RPCError) as ei:
            await client.call("SIM/nope", args={})
    finally:
        await host.rpc_dispatcher.close()
    assert not isinstance(ei.value, RPCHandlerError)


@pytest.mark.asyncio
async def test_c_non_action_rpc_methods_skip_admission():
    host = _host()
    asked = []
    real = host.admission.admit

    async def spy(*a, **k):
        asked.append(a)
        return await real(*a, **k)

    host.admission.admit = spy
    host.rpc_dispatcher.register("update_status", lambda **kw: {"got": True})
    await host.init_endpoint_status()
    client = await _serve_rpc(host)
    try:
        assert await client.call("update_status", args={}) == {"got": True}
    finally:
        await host.rpc_dispatcher.close()
    assert asked == [], "a non-action RPC method went through admission"


# --- d: the production sequence end to end --------------------------------------


@contextlib.asynccontextmanager
async def _serve_http_and_rpc(host):
    """Run *host* under uvicorn; yield ``(world_config, action)`` for SIM/slow."""
    http_port = _free_http_port()
    host.server_cfg["port"] = http_port
    server = uvicorn.Server(
        uvicorn.Config(host, host="127.0.0.1", port=http_port, log_level="warning")
    )
    serving = asyncio.create_task(server.serve())
    try:
        for _ in range(200):
            if server.started:
                break
            await asyncio.sleep(0.05)
        assert server.started
        await asyncio.sleep(0.3)  # let startup finish registering endpoints
        act = Action(
            action_uuid=uuidlib.UUID(_uid()),
            action_name="slow",
            action_server=MachineModel(server_name="SIM", machine_name="m"),
        )
        yield {"servers": {"SIM": {"host": "127.0.0.1", "port": http_port}}}, act
    finally:
        server.should_exit = True
        await asyncio.wait_for(serving, 10)


@pytest.mark.asyncio
async def test_d_rpc_timeout_then_http_fallback_runs_the_action_once(monkeypatch):
    monkeypatch.setattr(dispatcher, "_RPC_PROBE_TIMEOUT", 0.3)
    counter = _Counter(hold=1.2)
    host = _slow_host(counter)
    async with _serve_http_and_rpc(host) as (world, act):
        response, code = await dispatcher.async_action_dispatcher(
            world, act, params={}, timeout=5
        )
        assert code == ErrorCodes.none
        assert response == {"ok": True}, "the fallback did not get the handler's result"
        await asyncio.sleep(1.5)  # the RPC handler finishes in the background
        assert counter.runs == 1, "the HTTP fallback ran the action a second time"


@pytest.mark.asyncio
async def test_d_a_handler_error_over_rpc_does_not_fall_back_to_http(monkeypatch):
    runs = []
    host = _host()

    @host.action()
    async def slow(ctx: ActionContext):
        runs.append(1)
        raise ValueError("driver fell over")

    posts = []
    real_post = dispatcher.aiohttp.ClientSession.post

    def _spy(self, *a, **kw):
        posts.append(1)
        return real_post(self, *a, **kw)

    monkeypatch.setattr(dispatcher.aiohttp.ClientSession, "post", _spy)
    async with _serve_http_and_rpc(host) as (world, act):
        response, code = await dispatcher.async_action_dispatcher(
            world, act, params={}, timeout=5
        )
        await asyncio.sleep(0.5)
    assert response is None and code == ErrorCodes.http
    assert len(runs) == 1, "a handler error was re-sent over HTTP"
    assert not posts, "a handler error was re-sent over HTTP"


# --- e: a queued relaunch still runs ----------------------------------------------


@pytest.mark.asyncio
async def test_e_a_parked_action_relaunches_once_and_only_once():
    counter = _Counter()
    host = _slow_host(counter)
    await host.init_endpoint_status()
    _busy(host)
    x = _uid()
    async with _client(host) as c:
        await c.post("/SIM/slow", json={"action": {"action_uuid": x}})
        qact, _ = host.endpoint_queues["slow"].popleft()
        # exactly what ActionQueueDispatcher._dispatch_queued_action does
        qact.start_condition = ASC.no_wait
        qact.action_params["queued_launch"] = True
        body = {"action": qact.as_dict()}
        await c.post("/SIM/slow", json=body)
        assert counter.runs == 1, "the relaunch was judged a duplicate of itself"
        again = await c.post("/SIM/slow", json=body)
    assert again.json() == {"ok": True}
    assert counter.runs == 1, "a repeated relaunch ran again"


@pytest.mark.asyncio
async def test_e_a_repeat_during_a_held_relaunch_waits_for_its_result():
    counter = _Counter(hold=0.5)
    host = _slow_host(counter)
    await host.init_endpoint_status()
    _busy(host)
    x = _uid()
    async with _client(host) as c:
        await c.post("/SIM/slow", json={"action": {"action_uuid": x}})
        qact, _ = host.endpoint_queues["slow"].popleft()
        qact.start_condition = ASC.no_wait
        qact.action_params["queued_launch"] = True
        body = {"action": qact.as_dict()}
        first = asyncio.create_task(c.post("/SIM/slow", json=body))
        await counter.started.wait()
        dup = await asyncio.wait_for(c.post("/SIM/slow", json=body), 5)
        await first
    assert dup.json() == {"ok": True}, "the repeat got the parked stub, not the result"
    assert counter.runs == 1


# --- f: orchestrator resume re-sends a failed action under its uuid ----------------


def _failing_once_host(runs):
    """A handler that opens a session then raises on its first run only."""
    host = _host()

    @host.action()
    async def slow(ctx: ActionContext):
        runs.append(1)
        n = len(runs)
        await host.begin_session(
            Action(
                action_uuid=uuidlib.UUID(str(ctx.action.action_uuid)),
                action_name="slow",
            )
        )
        if n == 1:
            raise ValueError("driver fell over")
        return {"ran": n}

    return host


def _records(host, x):
    return [d for d in (host.actives, host.history) for k in d if str(k) == x]


@pytest.mark.asyncio
async def test_f_http_resend_of_a_failed_uuid_reruns_and_leaves_one_record():
    runs = []
    host = _failing_once_host(runs)
    await host.init_endpoint_status()
    x = _uid()
    body = {"action": {"action_uuid": x}}
    transport = httpx.ASGITransport(app=host, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        assert (await c.post("/SIM/slow", json=body)).status_code == 500
        stale = host.actives[uuidlib.UUID(x)]
        again = await asyncio.wait_for(c.post("/SIM/slow", json=body), 5)
    assert again.json() == {"ran": 2}, "the step was skipped, not re-run"
    assert len(runs) == 2
    assert len(_records(host, x)) == 1
    assert host.actives[uuidlib.UUID(x)] is not stale, "the stale session shadows"


@pytest.mark.asyncio
async def test_f_rpc_resend_of_a_failed_uuid_reruns_and_leaves_one_record():
    runs = []
    host = _failing_once_host(runs)
    await host.init_endpoint_status()
    client = await _serve_rpc(host)
    x = _uid()
    args = {"action": Action(action_uuid=uuidlib.UUID(x)).as_dict()}
    try:
        with pytest.raises(RPCHandlerError):
            await client.call("SIM/slow", args=args)
        assert await client.call("SIM/slow", args=args) == {"ran": 2}
    finally:
        await host.rpc_dispatcher.close()
    assert len(runs) == 2
    assert len(_records(host, x)) == 1


@pytest.mark.asyncio
async def test_f_a_successfully_finished_uuid_is_never_rerun():
    runs = []
    host = _host()

    @host.action()
    async def slow(ctx: ActionContext):
        runs.append(1)
        session = await host.begin_session(
            Action(
                action_uuid=uuidlib.UUID(str(ctx.action.action_uuid)),
                action_name="slow",
            )
        )
        await session.finish()
        return {"ran": len(runs)}

    await host.init_endpoint_status()
    x = _uid()
    body = {"action": {"action_uuid": x}}
    async with _client(host) as c:
        await c.post("/SIM/slow", json=body)
        again = await c.post("/SIM/slow", json=body)
    assert len(runs) == 1, "a finished, non-failed uuid ran again"
    assert again.json()["action_uuid"] == x


# --- g: robustness of the shared path ---------------------------------------------


@pytest.mark.asyncio
async def test_g_http_repeat_of_an_rpc_original_with_non_json_result():
    started = asyncio.Event()
    host = _host()

    @host.action()
    async def slow(ctx: ActionContext):
        started.set()
        await asyncio.sleep(0.5)
        return {"u": uuidlib.uuid4()}

    await host.init_endpoint_status()
    client = await _serve_rpc(host)
    x = _uid()
    try:
        rpc = asyncio.create_task(
            client.call("/SIM/slow", args={"action": {"action_uuid": x}}, timeout=10)
        )
        await started.wait()
        async with _client(host) as c:
            dup = await asyncio.wait_for(
                c.post("/SIM/slow", json={"action": {"action_uuid": x}}), 5
            )
        await rpc
    finally:
        await host.rpc_dispatcher.close()
    assert dup.status_code == 200
    uuidlib.UUID(dup.json()["u"])


@pytest.mark.asyncio
async def test_g_an_rpc_argument_binding_failure_is_not_a_handler_error():
    runs = []
    host = _host()

    @host.action()
    async def slow(ctx: ActionContext, needed: int):
        runs.append(1)
        return {"ok": True}

    await host.init_endpoint_status()
    client = await _serve_rpc(host)
    x = _uid()
    try:
        with pytest.raises(RPCError) as ei:
            await client.call(
                "SIM/slow", args={"action": {"action_uuid": x}}, dispatch_id="D1"
            )
        # nothing ran, so the HTTP copy of the same send runs
        async with _client(host) as c:
            resp = await asyncio.wait_for(
                c.post(
                    "/SIM/slow",
                    params={"needed": 1},
                    json={"action": {"action_uuid": x}},
                    headers={"X-Helao-Dispatch-Id": "D1"},
                ),
                5,
            )
    finally:
        await host.rpc_dispatcher.close()
    assert not isinstance(ei.value, RPCHandlerError)
    assert resp.json() == {"ok": True} and len(runs) == 1


@pytest.mark.asyncio
async def test_g_an_unserializable_rpc_result_fails_the_waiting_repeat():
    from pydantic import BaseModel, ConfigDict

    class _Bad(BaseModel):
        model_config = ConfigDict(arbitrary_types_allowed=True)
        thing: object

    started = asyncio.Event()
    host = _host()

    @host.action()
    async def slow(ctx: ActionContext):
        started.set()
        await asyncio.sleep(0.3)
        return _Bad(thing=lambda: 1)

    await host.init_endpoint_status()
    client = await _serve_rpc(host)
    x = _uid()
    try:
        first = asyncio.create_task(
            client.call("SIM/slow", args={"action": {"action_uuid": x}})
        )
        await started.wait()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=host, raise_app_exceptions=False),
            base_url="http://t",
        ) as c:
            dup = await asyncio.wait_for(
                c.post("/SIM/slow", json={"action": {"action_uuid": x}}), 5
            )
        with pytest.raises(RPCHandlerError):
            await asyncio.wait_for(first, 5)
    finally:
        await host.rpc_dispatcher.close()
    assert dup.status_code == 500


@pytest.mark.asyncio
async def test_g_cancelling_an_http_original_fails_its_waiting_repeat():
    counter = _Counter(hold=30)
    host = _slow_host(counter)
    await host.init_endpoint_status()
    body = {"action": {"action_uuid": _uid()}}
    transport = httpx.ASGITransport(app=host, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        first = asyncio.create_task(c.post("/SIM/slow", json=body))
        await counter.started.wait()
        dup = asyncio.create_task(c.post("/SIM/slow", json=body))
        await asyncio.sleep(0.2)
        first.cancel()
        resp = await asyncio.wait_for(dup, 5)
    assert resp.status_code == 500


@pytest.mark.asyncio
async def test_g_cancelling_an_rpc_original_fails_its_waiting_repeat():
    counter = _Counter(hold=30)
    host = _slow_host(counter)
    await host.init_endpoint_status()
    client = await _serve_rpc(host)
    x = _uid()
    rpc = asyncio.create_task(
        client.call("/SIM/slow", args={"action": {"action_uuid": x}}, timeout=60)
    )
    try:
        await counter.started.wait()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=host, raise_app_exceptions=False),
            base_url="http://t",
        ) as c:
            dup = asyncio.create_task(
                c.post("/SIM/slow", json={"action": {"action_uuid": x}})
            )
            await asyncio.sleep(0.2)
            for t in asyncio.all_tasks():
                if "_handle" in repr(t.get_coro()):
                    t.cancel()
            resp = await asyncio.wait_for(dup, 5)
    finally:
        rpc.cancel()
        await host.rpc_dispatcher.close()
    assert resp.status_code == 500


@pytest.mark.asyncio
async def test_f_a_rerun_that_opens_no_session_leaves_no_stale_record():
    runs = []
    host = _host()

    @host.action()
    async def slow(ctx: ActionContext):
        runs.append(1)
        if len(runs) == 1:
            await host.begin_session(
                Action(
                    action_uuid=uuidlib.UUID(str(ctx.action.action_uuid)),
                    action_name="slow",
                )
            )
            raise ValueError("driver fell over")
        return {"ran": len(runs)}

    await host.init_endpoint_status()
    x = _uid()
    body = {"action": {"action_uuid": x}}
    transport = httpx.ASGITransport(app=host, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        await c.post("/SIM/slow", json=body)
        host.history[uuidlib.UUID(x)] = host.actives[uuidlib.UUID(x)].action
        again = await asyncio.wait_for(c.post("/SIM/slow", json=body), 5)
    assert again.json() == {"ran": 2}
    assert _records(host, x) == [], "the failed run's record outlived its retry"


# --- h: one dispatch_id covers a send's RPC and HTTP copies ---------------------


class _FakeSock:
    """Stands in for the RPC reply socket, so no port is bound."""

    def __init__(self):
        self.sent = []

    async def send_multipart(self, parts):
        self.sent.append(_RESP_DECODER.decode(parts[-1]))


def _tolerant(host):
    """A client that turns a handler exception into a 500, as a server does."""
    transport = httpx.ASGITransport(app=host, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://t")


def _action_args(x, **action_params):
    return {
        "action": Action(
            action_uuid=uuidlib.UUID(x), action_params=action_params
        ).as_dict()
    }


async def _rpc_send(host, x, dispatch_id=None, **action_params):
    """Run one RPC request for uuid *x* through the dispatcher; return its reply."""
    if host.rpc_dispatcher._socket is None:
        for r in host.routes:
            if isinstance(r, APIRoute) and "POST" in (r.methods or ()):
                host.rpc_dispatcher.register(r.path, r.endpoint)
        host.rpc_dispatcher._socket = _FakeSock()
    payload = _REQ_ENCODER.encode(
        RPCRequest(
            id=1,
            method="SIM/slow",
            args=_action_args(x, **action_params),
            dispatch_id=dispatch_id,
        )
    )
    await host.rpc_dispatcher._handle([b"c"], payload)
    return host.rpc_dispatcher._socket.sent[-1]


def _http_send(c, x, dispatch_id=None, **action_params):
    headers = {"X-Helao-Dispatch-Id": dispatch_id} if dispatch_id else {}
    return asyncio.wait_for(
        c.post("/SIM/slow", json=_action_args(x, **action_params), headers=headers), 5
    )


def _failing_host(runs, fail_runs=1):
    """A handler that raises on its first *fail_runs* runs."""
    host = _host()

    @host.action()
    async def slow(ctx: ActionContext):
        runs.append(1)
        if len(runs) <= fail_runs:
            raise ValueError("driver fell over")
        return {"ran": len(runs)}

    return host


@pytest.mark.asyncio
@pytest.mark.parametrize("first", ["rpc", "http"])
async def test_h_the_other_copy_of_a_failed_send_is_not_run(first):
    runs = []
    host = _failing_host(runs)
    await host.init_endpoint_status()
    x = _uid()
    async with _tolerant(host) as c:

        async def copy(which):
            if which == "rpc":
                r = await _rpc_send(host, x, "D1")
                return r.ok
            return (await _http_send(c, x, "D1")).status_code == 200

        assert await copy(first) is False
        assert len(runs) == 1
        other = "http" if first == "rpc" else "rpc"
        assert await copy(other) is False, "the other copy of the send was admitted"
        assert len(runs) == 1, "the other copy of the send ran the action again"
        # A later dispatch of the same uuid (the orchestrator's resume) re-runs.
        again = await _http_send(c, x, "D2")
    assert again.json() == {"ran": 2}


@pytest.mark.asyncio
async def test_h_a_resume_without_a_dispatch_id_still_reruns():
    runs = []
    host = _failing_host(runs)
    await host.init_endpoint_status()
    x = _uid()
    async with _tolerant(host) as c:
        assert (await _http_send(c, x)).status_code == 500
        again = await _http_send(c, x)
    assert again.json() == {"ran": 2}


@pytest.mark.asyncio
async def test_h_a_late_copy_of_an_earlier_send_does_not_run_a_third_time():
    runs = []
    host = _failing_host(runs, fail_runs=2)
    await host.init_endpoint_status()
    x = _uid()
    async with _tolerant(host) as c:
        assert (await _http_send(c, x, "D1")).status_code == 500
        assert (await _http_send(c, x, "D2")).status_code == 500
        assert len(runs) == 2
        late = await _rpc_send(host, x, "D1")
    assert late.ok is False
    assert len(runs) == 2, "a late copy of the first send ran the action again"


@pytest.mark.asyncio
@pytest.mark.parametrize("first", ["rpc", "http"])
async def test_h_a_relaunched_actions_two_copies_run_once(first):
    runs = []
    host = _failing_host(runs)
    await host.init_endpoint_status()
    _busy(host)
    x = _uid()
    async with _tolerant(host) as c:
        # parked behind the busy endpoint, then relaunched under one dispatch id
        assert (await _http_send(c, x)).status_code == 200
        host.actionservermodel.endpoints["slow"].active_dict.clear()
        launch = {"queued_launch": True}
        if first == "rpc":
            assert (await _rpc_send(host, x, "R1", **launch)).ok is False
            second = (await _http_send(c, x, "R1", **launch)).status_code == 500
        else:
            assert (await _http_send(c, x, "R1", **launch)).status_code == 500
            second = (await _rpc_send(host, x, "R1", **launch)).ok is False
    assert second, "the other copy of the relaunch was admitted"
    assert len(runs) == 1, "the relaunch ran twice"


@pytest.mark.asyncio
async def test_h_a_real_rpc_call_carries_its_dispatch_id_to_admission():
    runs = []
    host = _failing_host(runs)
    await host.init_endpoint_status()
    client = await _serve_rpc(host)
    args = _action_args(_uid())
    try:
        with pytest.raises(RPCHandlerError):
            await client.call("SIM/slow", args=args, dispatch_id="D1")
        # the same send again (its other copy) is refused without running
        with pytest.raises(RPCError):
            await client.call("SIM/slow", args=args, dispatch_id="D1")
        assert len(runs) == 1
        assert await client.call("SIM/slow", args=args, dispatch_id="D2") == {"ran": 2}
    finally:
        await host.rpc_dispatcher.close()


@pytest.mark.asyncio
async def test_h_the_dispatcher_puts_one_id_on_both_copies(monkeypatch):
    seen = {}

    class _Resp:
        status = 200

        async def json(self, **kw):
            return {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class _Session:
        def __init__(self, *a, **kw):
            pass

        def post(self, url, **kw):
            seen["headers"] = kw["headers"]
            return _Resp()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    async def _no_rpc(*a, dispatch_id=None, **kw):
        seen["rpc_id"] = dispatch_id
        raise RPCError("unregistered")

    class _Client:
        call = staticmethod(_no_rpc)

    async def _get(*a, **kw):
        return _Client()

    monkeypatch.setattr(dispatcher, "_get_rpc_client", _get)
    monkeypatch.setattr(dispatcher.aiohttp, "ClientSession", _Session)
    A = Action(action_uuid=uuidlib.uuid4(), action_name="slow")
    A.action_server = MachineModel(server_name="SIM", machine_name="m")
    world = {"servers": {"SIM": {"host": "127.0.0.1", "port": 1}}}
    await dispatcher.async_action_dispatcher(world, A)
    first = seen["rpc_id"]
    assert first and seen["headers"] == {"X-Helao-Dispatch-Id": first}
    await dispatcher.async_action_dispatcher(world, A)
    assert seen["rpc_id"] != first, "two sends shared a dispatch id"


# --- i: a record failed by status, not by an exception --------------------------


def _status_host(runs, status):
    """A handler whose session ends *status* and finishes, returning normally."""
    host = _host()

    @host.action()
    async def slow(ctx: ActionContext):
        runs.append(1)
        session = await host.begin_session(
            Action(
                action_uuid=uuidlib.UUID(str(ctx.action.action_uuid)),
                action_name="slow",
            )
        )
        if len(runs) == 1:
            session.action.append_action_status(status)
        await session.finish()
        return {"ran": len(runs)}

    return host


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [HloStatus.errored, HloStatus.estopped])
async def test_i_a_status_failed_uuid_reruns_fresh_but_not_for_its_own_send(status):
    runs = []
    host = _status_host(runs, status)
    await host.init_endpoint_status()
    x = _uid()
    async with _client(host) as c:
        assert (await _http_send(c, x, "D1")).status_code == 200
        copy = await _http_send(c, x, "D1")
        assert copy.status_code == 500
        assert len(runs) == 1, "the send's other copy re-ran a status-failed action"
        again = await _http_send(c, x, "D2")
    assert again.json() == {"ran": 2}
    assert len(runs) == 2


# --- j: a stale live session is stopped, and cannot evict its re-run ------------


def _stale_session_host(sessions):
    """Run 1 opens a session then raises; run 2 opens its own and stays live."""
    host = _host()

    @host.action()
    async def slow(ctx: ActionContext):
        sessions.append(
            await host.begin_session(
                Action(
                    action_uuid=uuidlib.UUID(str(ctx.action.action_uuid)),
                    action_name="slow",
                )
            )
        )
        if len(sessions) == 1:
            raise ValueError("driver fell over")
        return {"ran": 2}

    return host


@pytest.mark.asyncio
async def test_j_a_stale_session_finishing_late_leaves_the_rerun_in_actives():
    sessions = []
    host = _stale_session_host(sessions)
    await host.init_endpoint_status()
    x = _uid()
    body = {"action": {"action_uuid": x}}
    transport = httpx.ASGITransport(app=host, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        await c.post("/SIM/slow", json=body)
        await asyncio.wait_for(c.post("/SIM/slow", json=body), 5)
    stale, rerun = sessions
    assert host.actives[uuidlib.UUID(x)] is rerun
    await stale.finish()
    assert host.actives.get(uuidlib.UUID(x)) is rerun, "the stale finalizer popped it"


@pytest.mark.asyncio
async def test_j_a_stale_session_is_stopped_when_its_uuid_re_runs():
    sessions = []
    host = _stale_session_host(sessions)
    await host.init_endpoint_status()
    body = {"action": {"action_uuid": _uid()}}
    transport = httpx.ASGITransport(app=host, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        await c.post("/SIM/slow", json=body)
        stale = sessions[0]
        assert stale.data_logger is not None and not stale.data_logger.done()
        await asyncio.wait_for(c.post("/SIM/slow", json=body), 5)
    await asyncio.sleep(0)
    assert HloStatus.estopped in stale.action.action_status
    assert stale.manual_stop is True
    assert stale.action_loop_running is False
    assert stale.data_logger.done(), "the stale data logger kept running"


def _executor_session_host(sessions, stops):
    """Run 1 opens a session with a live executor, then raises.

    The executor loop finishes the session only once it is stopped, as the real
    one does after ``stop_action_task``. Run 2 returns normally.
    """
    host = _host()

    @host.action()
    async def slow(ctx: ActionContext):
        sess = await host.begin_session(
            Action(
                action_uuid=uuidlib.UUID(str(ctx.action.action_uuid)),
                action_name="slow",
            )
        )
        sessions.append(sess)
        if len(sessions) > 1:
            return {"ran": len(sessions)}
        sess.action_loop_running = True
        host.executors["e1"] = sess

        async def executor_loop():
            while sess.action_loop_running:
                await asyncio.sleep(0.01)
            host.executors.pop("e1")
            await sess.finish()

        stops.append(asyncio.create_task(executor_loop()))
        raise ValueError("driver fell over")

    return host


@pytest.mark.asyncio
async def test_j_a_failed_attempt_with_a_live_executor_is_not_replaced_until_it_ends():
    sessions, stops = [], []
    host = _executor_session_host(sessions, stops)
    await host.init_endpoint_status()
    x = _uid()
    body = {"action": {"action_uuid": x}}
    published, written = [], []
    orig_put = host.status_q.put
    orig_write = host.write_act

    async def put(m):
        published.append((str(m.action_uuid), [s.name for s in m.action_status]))
        return await orig_put(m)

    async def write(action, **kw):
        written.append(
            (str(action.action_uuid), [s.name for s in action.action_status])
        )
        return await orig_write(action=action, **kw)

    host.status_q.put = put  # type: ignore[method-assign]
    host.write_act = write  # type: ignore[method-assign]
    transport = httpx.ASGITransport(app=host, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        assert (await c.post("/SIM/slow", json=body)).status_code == 500
        stale = sessions[0]
        again = await asyncio.wait_for(c.post("/SIM/slow", json=body), 5)
        assert again.status_code == 500, "a live stale executor was replaced"
        assert len(sessions) == 1, "a re-run started beside the stale executor"
        assert stale.manual_stop is True and stale.action_loop_running is False
        assert HloStatus.estopped in stale.action.action_status
        await asyncio.wait_for(stops[0], 5)  # the stopped executor finishes
        published.clear()
        written.clear()
        rerun = await asyncio.wait_for(c.post("/SIM/slow", json=body), 5)
        assert rerun.json() == {"ran": 2}
    assert len(sessions) == 2
    assert not [p for p in published if p[0] == x and "estopped" in p[1]], published
    assert not [w for w in written if w[0] == x and "estopped" in w[1]], written


@pytest.mark.asyncio
async def test_j_the_other_copy_of_a_refused_send_does_not_run_later():
    sessions, stops = [], []
    host = _executor_session_host(sessions, stops)
    await host.init_endpoint_status()
    x = _uid()
    body = {"action": {"action_uuid": x}}
    transport = httpx.ASGITransport(app=host, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        hdr = {"X-Helao-Dispatch-Id": "D1"}
        assert (await c.post("/SIM/slow", json=body, headers=hdr)).status_code == 500
        hdr = {"X-Helao-Dispatch-Id": "D2"}
        refused = await asyncio.wait_for(c.post("/SIM/slow", json=body, headers=hdr), 5)
        assert refused.status_code == 500
    await asyncio.wait_for(stops[0], 5)  # the stale executor ends
    late = await _rpc_send(host, x, "D2")  # the delayed RPC copy of that send
    assert not late.ok
    assert len(sessions) == 1, "a refused send ran behind a paused orchestrator"


# --- k: lookup order -------------------------------------------------------------


@pytest.mark.asyncio
async def test_k_the_seen_result_outranks_a_stale_endpoint_active_dict():
    host = _slow_host(_Counter())
    await host.init_endpoint_status()
    x = _uid()
    body = {"action": {"action_uuid": x}}
    async with _client(host) as c:
        await c.post("/SIM/slow", json=body)
        stale = type("A", (), {"as_dict": lambda self: {"stale": True}})()
        host.actionservermodel.endpoints["slow"].active_dict[x] = stale  # type: ignore
        again = await c.post("/SIM/slow", json=body)
    assert again.json() == {"ok": True}
