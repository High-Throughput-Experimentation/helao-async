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
