"""Endpoint registration and queued-action dispatch (B1, 3b remainder).

This is what the queuing middleware was blocked on: its branch condition is
``actionservermodel.endpoints[endpoint].active_dict``, and its parking spots are
``endpoint_queues`` and ``local_action_queue``. All three are registered here.
"""

import asyncio
import tempfile

import pytest

from helao.hexagon.app.action_context import ActionContext


class _QueuedAct:
    """Module-level: zdeque pickles its contents, so a local class cannot go in."""

    action_name = "acquire_data"
    start_condition = None

    def __init__(self):
        self.action_params: dict = {}


def _host():
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
        description="endpoint test",
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
            "root": tempfile.mkdtemp(prefix="helao_ep_"),
            "servers": {"SIM": {"host": "127.0.0.1", "port": 8002, "params": {}}},
        },
    )


def test_action_endpoints_are_registered_for_status_monitoring() -> None:
    """Each registered endpoint gets the active_dict the middleware reads."""
    host = _host()

    @host.action()
    async def acquire_data(ctx: ActionContext, duration: float = -1):
        return None

    asyncio.run(host.init_endpoint_status())
    eps = host.actionservermodel.endpoints
    assert "acquire_data" in eps, f"registered endpoints: {sorted(eps)}"
    assert hasattr(eps["acquire_data"], "active_dict")


def test_private_routes_are_not_registered_as_endpoints() -> None:
    """Only /<server_key>/... routes are action endpoints."""
    host = _host()
    asyncio.run(host.init_endpoint_status())
    assert "get_status" not in host.actionservermodel.endpoints


def test_a_queue_is_created_per_action_endpoint() -> None:
    host = _host()

    @host.action()
    async def acquire_data(ctx: ActionContext):
        return None

    asyncio.run(host.init_endpoint_status())
    assert "acquire_data" in host.endpoint_queues
    assert list(host.endpoint_queues["acquire_data"]) == []


def test_the_two_queues_are_distinct_objects() -> None:
    """local_action_queue holds actions; local_action_task_queue holds uuids.

    Adjacent in Base and easily conflated; doing so deadlocks or
    double-dispatches.
    """
    host = _host()
    assert host.local_action_queue is not host.local_action_task_queue


def test_endpoint_urls_carry_the_params_shape() -> None:
    """The orchestrator generates request schemas from this."""
    host = _host()

    @host.action()
    async def acquire_data(ctx: ActionContext, duration: float = -1):
        return None

    asyncio.run(host.init_endpoint_status())
    entry = [u for u in host.fast_urls if u["path"] == "/SIM/acquire_data"]
    assert entry, [u["path"] for u in host.fast_urls]
    params = entry[0]["params"]
    assert "duration" in params
    # action_version is synthesized as a plain int and shows up here.
    assert "action_version" in params
    # `action` does NOT: get_flat_params returns query/path/header params only,
    # and the synthesized envelope is a Body param. Legacy behaves identically,
    # so the orchestrator has never learned the envelope from this route
    # descriptor -- asserted so nobody "fixes" it into the list later.
    assert "action" not in params


@pytest.mark.asyncio
async def test_a_failed_redispatch_requeues_rather_than_dropping() -> None:
    """A dropped action leaves its caller waiting on something queued nowhere."""
    host = _host()
    from helao.helpers.zdeque import zdeque

    q = zdeque([(_QueuedAct(), {})])
    await host.action_queue._dispatch_queued_action(q, "test")
    assert len(q) == 1, "the action was dropped instead of requeued"


# -- moved from helao/core/tests/unit_test_base_endpoints.py (B7b) -----------


@pytest.mark.asyncio
async def test_init_endpoint_status_awaits_the_dyn_endpoints_callback() -> None:
    """Late routes register before the endpoint scan, or they are never monitored."""
    host = _host()
    calls = []

    async def _dyn(app):
        calls.append(app)

    await host.init_endpoint_status(dyn_endpoints=_dyn)
    assert calls == [host]


@pytest.mark.asyncio
async def test_dyn_endpoints_init_schedules_the_endpoint_scan() -> None:
    """The startup hook only schedules the scan; it must still run to completion."""
    host = _host()

    @host.action()
    async def acquire_data(ctx: ActionContext):
        return None

    assert host.endpoint_queues == {}
    host.dyn_endpoints_init()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert "acquire_data" in host.endpoint_queues


@pytest.mark.asyncio
async def test_a_queued_endpoint_action_is_redispatched_no_wait_and_drained(
    monkeypatch,
) -> None:
    """no_wait stops the redispatch queueing behind itself; queued_launch lets the
    middleware pass it through instead of queueing it a second time."""
    from helao.core.models.action import ActionModel
    from helao.core.models.action_start_condition import ActionStartCondition
    from helao.helpers.zdeque import zdeque
    from helao.hexagon.app import endpoint_manager

    host = _host()
    calls = []

    async def _fake_dispatch(world_cfg, qact, qpars):
        calls.append((world_cfg, qact, qpars))
        return {"ok": True}, None

    monkeypatch.setattr(endpoint_manager, "async_action_dispatcher", _fake_dispatch)
    host.endpoint_queues["acquire_data"] = zdeque([(_QueuedAct(), {"p": 1})])
    await host.process_endpoint_queue(ActionModel(action_name="acquire_data"))
    assert len(calls) == 1
    world_cfg, qact, qpars = calls[0]
    assert world_cfg is host.world_cfg
    assert qact.action_name == "acquire_data"
    assert qact.start_condition == ActionStartCondition.no_wait
    assert qact.action_params.get("queued_launch") is True
    assert qpars == {"p": 1}
    assert len(host.endpoint_queues["acquire_data"]) == 0


@pytest.mark.asyncio
async def test_the_unified_queue_is_redispatched_and_drained(monkeypatch) -> None:
    from helao.helpers.zdeque import zdeque
    from helao.hexagon.app import endpoint_manager

    host = _host()
    calls = []

    async def _fake_dispatch(world_cfg, qact, qpars):
        calls.append(qact.action_name)
        return {"ok": True}, None

    monkeypatch.setattr(endpoint_manager, "async_action_dispatcher", _fake_dispatch)
    host.local_action_queue = zdeque([(_QueuedAct(), {})])
    await host.process_unified_queue()
    assert calls == ["acquire_data"]
    assert len(host.local_action_queue) == 0
