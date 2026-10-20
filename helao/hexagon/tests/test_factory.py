"""Composition factory: fail-loud wiring, the status adapter's identity, the
orchestrator's /loaded_modules route. Construction level only — full lifecycle
is the Task 12 launched smoke."""

import os

import pytest

import helao

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(helao.__file__)))


def _world(tmp_path):
    return {
        "root": str(tmp_path),
        "dummy": True,
        "simulation": True,
        "servers": {
            "ORCH": {
                "host": "127.0.0.1",
                "port": 8901,
                "group": "orchestrator",
                "fast": "async_orch2",
                "params": {},
            },
            "SIM": {
                "host": "127.0.0.1",
                "port": 8902,
                "group": "action",
                "fast": "ws_simulator",
                "params": {},
            },
        },
    }


@pytest.fixture()
def installed_config(tmp_path, monkeypatch):
    from helao.helpers import config_loader

    world = _world(tmp_path)
    (tmp_path / "LOGS").mkdir()
    monkeypatch.setattr(config_loader, "CONFIG", world)
    return world


def test_build_wiring_fail_loud_without_config(monkeypatch):
    from helao.helpers import config_loader
    from helao.hexagon.app.factory import build_wiring

    monkeypatch.setattr(config_loader, "CONFIG", None)
    with pytest.raises(RuntimeError):
        build_wiring("ORCH")


def test_build_wiring_produces_real_adapters(installed_config):
    from helao.hexagon.app.factory import build_wiring
    from helao.hexagon.ports.clock import ClockPort
    from helao.hexagon.ports.config import ConfigPort
    from helao.hexagon.ports.logging import LoggingPort
    from helao.hexagon.ports.transport import TransportPort

    w = build_wiring("ORCH")
    assert isinstance(w.config, ConfigPort)
    assert isinstance(w.logging, LoggingPort)
    assert isinstance(w.clock, ClockPort)
    assert isinstance(w.transport, TransportPort)
    assert w.config.world_cfg() is installed_config  # raw-dict identity end-to-end
    w.require("config", "logging", "clock", "transport", "state_persistence")


def test_orchestrator_exposes_loaded_modules(installed_config):
    """An orchestrator must answer /loaded_modules, like every other `fast:` server.

    Two things depend on it, and both failed silently while it was missing.
    `launch.py`'s `server_loaded_files` POSTs it for anything with a `fast:` key
    and treats a non-200 as "no known mapping" -- which fails closed, so the
    hot-reload watcher never restarted an orchestrator no matter what changed
    under it.

    Asserted on the app the orchestrator module really builds (an ``OrchHost``),
    not on the shared registrar: a registrar test would still pass if the host
    stopped calling it.
    """
    from helao.deploy.hte.servers.orchestrator.async_orch2 import makeApp

    app = makeApp("ORCH")
    routes = {r.path for r in app.routes}  # type: ignore[attr-defined]
    assert "/loaded_modules" in routes

    # Registered exactly once: a second handler on one path is accepted
    # silently by FastAPI, which then serves the first.
    assert [r.path for r in app.routes].count("/loaded_modules") == 1  # type: ignore[attr-defined]

    # The payload is the watcher's contract: {abs repo .py path: sha1}. An empty
    # dict would satisfy a presence-only check while mapping nothing.
    handler = next(
        r.endpoint  # type: ignore[attr-defined]
        for r in app.routes  # type: ignore[attr-defined]
        if r.path == "/loaded_modules"  # type: ignore[attr-defined]
    )
    loaded = handler()
    assert isinstance(loaded, dict) and loaded
    assert __file__ in loaded, "this test's own module is loaded but unreported"
    assert all(
        p.startswith(str(REPO_ROOT)) and p.endswith(".py") for p in loaded
    ), sorted(p for p in loaded if not p.endswith(".py"))[:5]
    assert all(len(h) == 40 for h in loaded.values())


def test_build_wiring_status_port_carries_own_identity(installed_config):
    """P1b1 carry: the status adapter must be composed with the server's own
    host/port from config (orch_status_sync keys nonblocking bookkeeping on
    them) — never the ''/0 defaults."""
    from helao.hexagon.adapters.shared.status import DispatcherStatusAdapter
    from helao.hexagon.app.factory import build_wiring
    from helao.hexagon.ports.status import StatusPort

    w = build_wiring("SIM")
    assert isinstance(w.status, DispatcherStatusAdapter)
    assert isinstance(w.status, StatusPort)
    assert w.status._own_host == "127.0.0.1"
    assert w.status._own_port == 8902
    # the composition's consumed set now includes status (fail-loud stays real)
    w.require("config", "logging", "clock", "transport", "status")


@pytest.mark.asyncio
async def test_status_wire_send_carries_composed_identity(
    installed_config, monkeypatch
):
    """send_nonblocking_status must put the COMPOSED host/port on the wire
    (params_dict server_host/server_port), not ''/0."""
    import helao.hexagon.adapters.shared.status as status_mod
    from helao.core.error import ErrorCodes
    from helao.hexagon.app.factory import build_wiring

    sent = []

    async def _fake_dispatch(
        server_key,
        host,
        port,
        private_action,
        params_dict,
        json_dict,
        timeout=60,
        retries=5,
    ):
        sent.append((private_action, params_dict))
        return {}, ErrorCodes.none

    monkeypatch.setattr(status_mod, "async_private_dispatcher", _fake_dispatch)
    w = build_wiring("SIM")
    assert w.status is not None
    await w.status.send_nonblocking_status(
        "ORCH", "127.0.0.1", 8901, "SIM", "SIM exec_1", None, "active"  # type: ignore[arg-type]
    )
    action, params = sent[0]
    assert action == "update_nonblocking"
    assert params == {"server_host": "127.0.0.1", "server_port": 8902}


def test_build_wiring_wires_native_write_adapters(installed_config):
    from helao.hexagon.adapters.native.artifact_store import (
        NativeArtifactStoreAdapter,
    )
    from helao.hexagon.app.factory import build_wiring
    from helao.hexagon.app.wiring import ACTION_REQUIRED

    w = build_wiring("SIM")
    assert isinstance(w.artifact_store, NativeArtifactStoreAdapter)
    assert "artifact_store" in ACTION_REQUIRED
    w.require(*ACTION_REQUIRED)  # fail-loud stays satisfiable


@pytest.mark.asyncio
async def test_status_adapter_unbound_is_fail_loud(installed_config):
    """Controller hardening 3 (Q1/D3 underpinning): a DispatcherStatusAdapter
    is unbound by default and stays fail-loud (UnwiredPortError on
    publish_status). Only `ActionHost.__init__` binds the bridge (see
    test_ws_publish_bridge::test_an_action_host_binds_the_bridge_to_its_own_queues);
    the composed orchestrator side is pinned by
    test_vis_hexagon_producer_parity::test_no_hexagon_orch_ws_producer_exists.
    (Bare-adapter check.)"""
    from helao.hexagon.adapters.errors import UnwiredPortError
    from helao.hexagon.adapters.shared.status import DispatcherStatusAdapter

    a = DispatcherStatusAdapter("ORCH")
    with pytest.raises(UnwiredPortError):
        await a.publish_status({})
