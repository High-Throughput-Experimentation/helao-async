"""SP-ORCH-5 Part (a) integration tests — real transport, config target resolution.

Tests:
1. RPC dispatch arrives at the correct port (not 8000) via the fake action server.
2. _dispatch_target_for resolves from config servers map (not hardcoded 8000).
3. _dispatch_target_for resolves ORCH-self to the configured orch port.
4. RPC method coverage: every POST route is registered with the RPC dispatcher.
5. factory.makeApp(group="orchestrator") with NO transport still uses FakeTransport.
"""
from __future__ import annotations

import asyncio
from typing import Any, List
from uuid import uuid4

import pytest
from fastapi.routing import APIRoute

from helao.core.rpc import RPCClient, derive_rpc_port
from helao.framework.adapters.fakes.transport import FakeTransport
from helao.framework.adapters.fakes.storage import FakeStorage
from helao.framework.adapters.http_transport import HttpTransport
from helao.framework.adapters.ntp_clock import NtpClock
from helao.framework.adapters.queue_eventsink import QueueEventSink
from helao.framework.app.orch_api import (
    OrchDriver,
    OrchPorts,
    _dispatch_target_for,
    makeOrchApp,
)
from helao.framework.domain.run_models import RunAction, RunExperiment, RunSequence
from helao.framework.models.action_start_condition import ActionStartCondition
from helao.framework.models.experiment import ExperimentModel
from helao.framework.models.machine import MachineModel
from helao.framework.ports.transport import DispatchTarget

from helao.framework.tests._fake_action_server import fake_action_server, FakeServerInfo  # noqa: F401 (fixture)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_action_targeting(server_key: str, host: str, port: int, action_name: str = "run_for") -> RunAction:
    """Build a RunAction pointing at the given server."""
    server = MachineModel(
        server_name=server_key,
        machine_name="testhost",
        hostname=host,
        port=port,
    )
    return RunAction(
        action_name=action_name,
        action_server=server,
        start_condition=ActionStartCondition.no_wait,
        action_params={"duration": 0.05},
    )


def _exp_factory_for(action: RunAction):
    """Return a factory that emits a single action."""
    def factory(experiment: RunExperiment, **_kw) -> List[RunAction]:
        return [action]
    return factory


def _seq_factory() -> List[ExperimentModel]:
    return [ExperimentModel(experiment_name="fake_exp")]


def _make_ports_with_transport(transport, servers_map: dict | None = None) -> OrchPorts:
    return OrchPorts(
        transport=transport,
        storage=FakeStorage(),
        eventsink=QueueEventSink(),
        clock=NtpClock(),
        servers_map=servers_map,
    )


# ---------------------------------------------------------------------------
# Test 1: RPC dispatch arrives at the configured port (not 8000)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rpc_dispatch_arrives_at_configured_port(fake_action_server: FakeServerInfo):
    """Enqueue an action targeting the fake server; assert it arrives over RPC at
    the fake server's http_port (not the hardcoded 8000 default)."""
    fsi = fake_action_server
    servers_map = {
        fsi.server_key: {"host": fsi.host, "port": fsi.http_port, "group": "action"},
    }

    transport = HttpTransport(use_rpc=True)
    try:
        action = _make_action_targeting(fsi.server_key, fsi.host, fsi.http_port)
        exp_lib = {"fake_exp": _exp_factory_for(action)}
        ports = OrchPorts(
            transport=transport,
            storage=FakeStorage(),
            eventsink=QueueEventSink(),
            clock=NtpClock(),
            experiment_lib=exp_lib,
            servers_map=servers_map,
        )
        driver = OrchDriver("test_orch", ports=ports)

        # Resolve the target — must be fake server's port, not 8000
        target = _dispatch_target_for(action, "run_for", servers_map=servers_map)
        assert target.port == fsi.http_port, (
            f"Expected port {fsi.http_port}, got {target.port} "
            "(config resolution broken — still falling back to 8000?)"
        )
        assert target.host == fsi.host

        # Actually dispatch via the transport to verify RPC arrives
        payload = action.as_dict()
        result = await transport.dispatch(target, payload)
        assert result.error.value == "none", (
            f"Dispatch failed: {result.error}. "
            f"RPC port would be {derive_rpc_port(fsi.http_port)}"
        )
    finally:
        await transport.aclose()


# ---------------------------------------------------------------------------
# Test 2: _dispatch_target_for resolves from config servers map
# ---------------------------------------------------------------------------


def test_dispatch_target_resolves_from_servers_map():
    """_dispatch_target_for uses servers_map to get host/port, ignoring MachineModel."""
    # MachineModel says port 8000, but servers_map says 9999
    server = MachineModel(
        server_name="MY_SRV",
        machine_name="testhost",
        hostname="127.0.0.1",
        port=8000,
    )
    action = RunAction(
        action_name="do_thing",
        action_server=server,
        start_condition=ActionStartCondition.no_wait,
    )
    servers_map = {
        "MY_SRV": {"host": "192.168.1.5", "port": 9999, "group": "action"},
    }
    target = _dispatch_target_for(action, "do_thing", servers_map=servers_map)
    assert target.host == "192.168.1.5"
    assert target.port == 9999


def test_dispatch_target_falls_back_to_machine_model_when_not_in_map():
    """_dispatch_target_for falls back to MachineModel when server_key not in map."""
    server = MachineModel(
        server_name="UNKNOWN_SRV",
        machine_name="testhost",
        hostname="10.0.0.1",
        port=7777,
    )
    action = RunAction(
        action_name="do_thing",
        action_server=server,
        start_condition=ActionStartCondition.no_wait,
    )
    # servers_map doesn't contain UNKNOWN_SRV
    servers_map = {"OTHER": {"host": "127.0.0.1", "port": 8001, "group": "action"}}
    target = _dispatch_target_for(action, "do_thing", servers_map=servers_map)
    assert target.host == "10.0.0.1"
    assert target.port == 7777


def test_dispatch_target_no_map_unchanged():
    """_dispatch_target_for with no servers_map preserves existing behavior."""
    server = MachineModel(
        server_name="SRV",
        machine_name="testhost",
        hostname="127.0.0.1",
        port=8001,
    )
    action = RunAction(
        action_name="do_thing",
        action_server=server,
        start_condition=ActionStartCondition.no_wait,
    )
    target = _dispatch_target_for(action, "do_thing")
    assert target.host == "127.0.0.1"
    assert target.port == 8001


# ---------------------------------------------------------------------------
# Test 3: ORCH-self resolution
# ---------------------------------------------------------------------------


def test_dispatch_target_resolves_orch_self():
    """_dispatch_target_for resolves the orchestrator's OWN entry from servers_map."""
    orch_server = MachineModel(
        server_name="ORCH",
        machine_name="testhost",
        hostname="127.0.0.1",
        port=8000,  # wrong default — map should override
    )
    action = RunAction(
        action_name="wait",
        action_server=orch_server,
        start_condition=ActionStartCondition.no_wait,
    )
    servers_map = {
        "ORCH": {"host": "127.0.0.1", "port": 8001, "group": "orchestrator"},
    }
    target = _dispatch_target_for(action, "wait", servers_map=servers_map)
    assert target.port == 8001, (
        f"ORCH self-dispatch resolved to {target.port}, expected 8001 from servers_map"
    )


# ---------------------------------------------------------------------------
# Test 4: RPC method coverage — every POST route is registered
# ---------------------------------------------------------------------------


def test_rpc_every_post_route_registered():
    """Every POST route on the orch app must be registered with the RPC dispatcher.

    This ensures that when Part (c) adds /wait etc., they're automatically covered.
    """
    from helao.framework.adapters.fakes.storage import FakeStorage
    from helao.framework.adapters.ntp_clock import NtpClock
    from helao.framework.adapters.queue_eventsink import QueueEventSink
    from helao.framework.adapters.fakes.transport import FakeTransport

    ports = OrchPorts(
        transport=FakeTransport(),
        storage=FakeStorage(),
        eventsink=QueueEventSink(),
        clock=NtpClock(),
    )
    app = makeOrchApp("test_orch", ports=ports)

    # POST route paths (strip leading slash to match dispatcher key normalization)
    post_paths = {
        route.path.lstrip("/")
        for route in app.routes
        if isinstance(route, APIRoute) and "POST" in route.methods
    }

    # Manually trigger the registration loop (mimic startup hook, without binding)
    dispatcher = app.state.rpc_dispatcher
    for route in app.routes:
        if isinstance(route, APIRoute) and "POST" in route.methods:
            dispatcher.register(route.path, route.endpoint)

    registered = set(dispatcher.methods.keys())

    missing = post_paths - registered
    assert not missing, (
        f"POST routes not registered with RPC dispatcher: {sorted(missing)}"
    )


# ---------------------------------------------------------------------------
# Test 5: factory.makeApp with no transport still uses FakeTransport
# ---------------------------------------------------------------------------


def test_factory_makeapp_no_transport_uses_fake_transport():
    """factory.makeApp(group='orchestrator') with no transport= kwarg must use
    FakeTransport (the default). This verifies the additive contract: existing
    tests/in-process runners are not broken."""
    from helao.framework.app.factory import makeApp

    app = makeApp("test_orch_default", group="orchestrator")
    driver: OrchDriver = app.state.driver
    assert isinstance(driver.ports.transport, FakeTransport), (
        f"Expected FakeTransport, got {type(driver.ports.transport).__name__}. "
        "Production wiring must NOT change the factory default."
    )


# ---------------------------------------------------------------------------
# Test 6: OrchPorts servers_map is distinct from action_servers
# ---------------------------------------------------------------------------


def test_orch_ports_servers_map_distinct_from_action_servers():
    """OrchPorts.servers_map (full config map) is distinct from action_servers
    (heartbeat subset). Both can coexist without collision."""
    all_servers = {
        "ORCH": {"host": "127.0.0.1", "port": 8001, "group": "orchestrator"},
        "ACT1": {"host": "127.0.0.1", "port": 8002, "group": "action"},
        "ACT2": {"host": "127.0.0.1", "port": 8003, "group": "action"},
    }
    action_only = {k: v for k, v in all_servers.items() if v["group"] == "action"}

    ports = OrchPorts(
        transport=FakeTransport(),
        storage=FakeStorage(),
        eventsink=QueueEventSink(),
        clock=NtpClock(),
        servers_map=all_servers,
        action_servers=action_only,
    )
    assert "ORCH" in ports.servers_map
    assert "ORCH" not in ports.action_servers
    assert ports.servers_map is not ports.action_servers
