"""The queuing middleware (B1, 3b remainder).

Nothing in a route diff sees any of this: serialized and concurrent execution
both return 200. Only the interleaving differs, and on a station that
difference is two actions driving one instrument at once. Every assertion here
is therefore on observed behaviour, never on registration.
"""

import asyncio
import tempfile

import httpx
import pytest

from helao.hexagon.app.action_context import ActionContext


def _host(**server_params):
    from helao.hexagon.adapters.native.artifact_store import NativeArtifactStoreAdapter
    from helao.hexagon.app.action_host import ActionHost
    from helao.hexagon.app.wiring import PortWiring

    class _Clock:
        def now_ns(self):
            return 0

        def offset(self):
            return 0.0

    class _Stub:
        def __getattr__(self, name):
            raise AssertionError(f"port member {name!r} used unexpectedly")

    return ActionHost(
        server_key="SIM",
        server_title="SIM",
        description="middleware test",
        version=1.0,
        wiring=PortWiring(
            config=_Stub(),
            logging=_Stub(),
            clock=_Clock(),
            transport=_Stub(),
            state_persistence=_Stub(),
            status=_Stub(),
            health=_Stub(),
            artifact_store=NativeArtifactStoreAdapter(config=_Stub(), clock=_Clock()),
            data_sink=_Stub(),
        ),
        helao_cfg={
            "root": tempfile.mkdtemp(prefix="helao_mw_"),
            "servers": {
                "SIM": {"host": "127.0.0.1", "port": 8002, "params": server_params}
            },
        },
    )


def _client(host):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=host), base_url="http://t"
    )


@pytest.mark.asyncio
async def test_an_idle_endpoint_passes_straight_through():
    host = _host()
    ran = []

    @host.action()
    async def acquire_data(ctx: ActionContext):
        ran.append(1)
        return {"ok": True}

    await host.init_endpoint_status()
    async with _client(host) as c:
        resp = await c.post("/SIM/acquire_data", json={})
    assert resp.status_code == 200
    assert ran == [1], "an idle endpoint did not run the handler"


@pytest.mark.asyncio
async def test_a_busy_endpoint_parks_the_second_request():
    """The handler must NOT run; the caller still gets an action uuid back."""
    host = _host()
    ran = []

    @host.action()
    async def acquire_data(ctx: ActionContext):
        ran.append(1)
        return {"ok": True}

    await host.init_endpoint_status()
    # mark the endpoint busy exactly as a live action would
    host.actionservermodel.endpoints["acquire_data"].active_dict["u1"] = object()

    async with _client(host) as c:
        resp = await c.post("/SIM/acquire_data", json={})

    assert resp.status_code == 200
    assert ran == [], "a busy endpoint ran the handler instead of queuing"
    assert len(host.endpoint_queues["acquire_data"]) == 1, "action was not parked"
    assert resp.json().get("action_uuid"), "queued caller got no action uuid to track"


@pytest.mark.asyncio
async def test_no_wait_bypasses_the_queue():
    """start_condition=no_wait is how the orchestrator forces a busy endpoint."""
    from helao.core.models.action_start_condition import ActionStartCondition as ASC

    host = _host()
    ran = []

    @host.action()
    async def acquire_data(ctx: ActionContext):
        ran.append(1)
        return {"ok": True}

    await host.init_endpoint_status()
    host.actionservermodel.endpoints["acquire_data"].active_dict["u1"] = object()

    async with _client(host) as c:
        await c.post(
            "/SIM/acquire_data", json={"action": {"start_condition": int(ASC.no_wait)}}
        )
    assert ran == [1], "no_wait was queued instead of running"


@pytest.mark.asyncio
async def test_a_requeued_launch_is_not_queued_again():
    """queued_launch is what stops a redispatch parking itself forever."""
    host = _host()
    ran = []

    @host.action()
    async def acquire_data(ctx: ActionContext):
        ran.append(1)
        return {"ok": True}

    await host.init_endpoint_status()
    host.actionservermodel.endpoints["acquire_data"].active_dict["u1"] = object()

    async with _client(host) as c:
        await c.post(
            "/SIM/acquire_data",
            json={"action": {"action_params": {"queued_launch": True}}},
        )
    assert ran == [1], "a requeued launch was parked again"


@pytest.mark.asyncio
async def test_disallowing_concurrency_parks_on_the_unified_queue():
    """A different endpoint being busy is enough when concurrency is off."""
    host = _host(allow_concurrent_actions=False)
    ran = []

    @host.action()
    async def acquire_data(ctx: ActionContext):
        ran.append(1)
        return {"ok": True}

    @host.action()
    async def other_action(ctx: ActionContext):
        return {"ok": True}

    await host.init_endpoint_status()
    host.actionservermodel.endpoints["acquire_data"].active_dict["u1"] = object()
    host.actionservermodel.endpoints["other_action"].active_dict["u2"] = object()

    async with _client(host) as c:
        await c.post("/SIM/acquire_data", json={})

    assert ran == [], "ran while another endpoint was busy and concurrency is off"
    assert len(host.local_action_queue) == 1, "not parked on the unified queue"
    assert len(host.endpoint_queues["acquire_data"]) == 0, "parked on the wrong queue"


@pytest.mark.asyncio
async def test_a_private_route_is_never_queued():
    """Only /<server_key>/... POSTs go through the queuing path."""
    host = _host()
    await host.init_endpoint_status()
    async with _client(host) as c:
        resp = await c.post("/get_config", json={})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_head_requests_short_circuit():
    """The endpoint checker probes with HEAD; 405 reads as unhealthy."""
    host = _host()

    @host.action()
    async def acquire_data(ctx: ActionContext):
        return {"ok": True}

    await host.init_endpoint_status()
    async with _client(host) as c:
        resp = await c.head("/SIM/acquire_data")
    assert resp.status_code == 200
