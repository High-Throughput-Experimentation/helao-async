"""Composition factory: fail-loud wiring, OrchAPI construction with graft
hooks, action-app wrap, vis deferral, launcher shim delegation. Construction
level only — full lifecycle is the Task 12 launched smoke."""

import pytest


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


def test_make_orch_app_constructs_with_graft_hooks(installed_config):
    from helao.core.servers.orch_api import OrchAPI
    from helao.hexagon.app.factory import makeOrchApp

    app = makeOrchApp("ORCH")
    assert isinstance(app, OrchAPI)
    assert app.hexagon_wiring is not None  # type: ignore[attr-defined]
    routes = {r.path for r in app.routes}  # type: ignore[attr-defined]
    # BaseAPI/OrchAPI system surface present (spec §8.2 spot checks)
    for path in (
        "/start",
        "/stop",
        "/estop_orch",
        "/clear_estop",
        "/append_sequence",
        "/global_status",
        "/update_status",
    ):
        assert path in routes, path
    assert app.rpc_dispatcher is not None  # co-located RPC registry exists


def test_make_action_app_wraps_legacy_module(installed_config):
    from helao.helpers.server_api import HelaoFastAPI
    from helao.hexagon.app.factory import makeActionApp

    app = makeActionApp("SIM", "helao.deploy.test.servers.action.ws_simulator")
    assert isinstance(app, HelaoFastAPI)
    assert app.hexagon_wiring is not None  # type: ignore[attr-defined]
    routes = {r.path for r in app.routes}  # type: ignore[attr-defined]
    assert "/SIM/acquire_data" in routes  # real legacy action route survived


def test_make_vis_app_delegates_to_legacy_module(monkeypatch):
    """P2d compat-facade: makeVisApp imports the named legacy module and
    calls its makeBokehApp with the launcher-shaped args, attaching NOTHING
    (HelaoBokehAPI self-configures from CONFIG; native vis ports = P3)."""
    from bokeh.document import Document

    from helao.hexagon.app import factory

    calls = {}

    class FakeLegacy:
        @staticmethod
        def makeBokehApp(doc, confPrefix, server_key, helao_repo_root):
            calls["args"] = (doc, confPrefix, server_key, helao_repo_root)
            return doc

    def fake_import(name):
        calls["module"] = name
        return FakeLegacy

    monkeypatch.setattr(factory, "import_module", fake_import)
    doc = Document()
    out = factory.makeVisApp(
        "helao.deploy.hte.servers.operator.standalone_operator",
        doc,
        "goldenhexvis",
        "OPERATOR",
        "/repo",
    )
    assert out is doc
    assert calls["module"] == "helao.deploy.hte.servers.operator.standalone_operator"
    assert calls["args"] == (doc, "goldenhexvis", "OPERATOR", "/repo")


def test_launcher_shims_delegate():
    import helao.deploy.hexagon.servers.action.ws_simulator as sim_shim
    import helao.deploy.hexagon.servers.orchestrator.async_orch2 as orch_shim
    from helao.hexagon.app import factory

    assert (
        orch_shim.makeApp.__module__
        == "helao.deploy.hexagon.servers.orchestrator.async_orch2"
    )
    assert sim_shim.LEGACY_MODULE == "helao.deploy.test.servers.action.ws_simulator"
    assert orch_shim.FACTORY is factory.makeOrchApp


def test_build_wiring_status_port_carries_own_identity(installed_config):
    """P1b1 carry: the status adapter must be composed with the server's own
    host/port from config (orch_status_sync keys nonblocking bookkeeping on
    them) — never the ''/0 defaults."""
    from helao.hexagon.adapters.legacy.status import DispatcherStatusAdapter
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
    from helao.core.error import ErrorCodes
    from helao.hexagon.app.factory import build_wiring
    import helao.hexagon.adapters.legacy.status as status_mod

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
    from helao.hexagon.adapters.native.data_sink import NativeDataSinkAdapter
    from helao.hexagon.app.factory import build_wiring
    from helao.hexagon.app.wiring import ACTION_REQUIRED

    w = build_wiring("SIM")
    assert isinstance(w.artifact_store, NativeArtifactStoreAdapter)
    assert isinstance(w.data_sink, NativeDataSinkAdapter)
    assert "artifact_store" in ACTION_REQUIRED and "data_sink" in ACTION_REQUIRED
    w.require(*ACTION_REQUIRED)  # fail-loud stays satisfiable


def test_make_action_app_registers_graft_hooks(installed_config):
    from helao.hexagon.app.factory import makeActionApp

    app = makeActionApp("SIM", "helao.deploy.test.servers.action.ws_simulator")
    assert app.hexagon_wiring.artifact_store is not None
    assert app.hexagon_active_graft is None  # applied at startup, not build
    startup_names = [h.__name__ for h in app.router.on_startup]
    shutdown_names = [h.__name__ for h in app.router.on_shutdown]
    assert "_hexagon_active_graft_startup" in startup_names
    assert "_hexagon_active_graft_shutdown" in shutdown_names
    # ours must be registered AFTER the legacy BaseAPI startup that creates
    # app.base (Starlette preserves registration order)
    assert startup_names[-1] == "_hexagon_active_graft_startup"


@pytest.mark.asyncio
async def test_action_app_startup_binds_ws_publish_bridge(
    installed_config, monkeypatch
):
    """P2b-2 D3: the existing _hexagon_active_graft_startup hook constructs
    WsPublishBridge over the live base's queues and binds it into the status
    adapter (ACTION apps only; makeOrchApp is untouched, Q1)."""
    from types import SimpleNamespace

    from helao.helpers.multisubscriber_queue import MultisubscriberQueue
    from helao.hexagon.adapters.native.ws_publish import WsPublishBridge
    import helao.hexagon.app.active_graft as active_graft_mod
    from helao.hexagon.app.factory import makeActionApp

    class _StubGraft:
        def close(self):
            pass

    # isolate the bind from the P2b-1 write graft (its own tests cover it)
    monkeypatch.setattr(
        active_graft_mod,
        "graft_active_write_path",
        lambda base, wiring: _StubGraft(),
    )
    app = makeActionApp("SIM", "helao.deploy.test.servers.action.ws_simulator")
    assert app.hexagon_ws_bridge is None  # bound at startup, not at build
    app.base = SimpleNamespace(
        status_q=MultisubscriberQueue(),
        data_q=MultisubscriberQueue(),
        live_q=MultisubscriberQueue(),
    )
    hook = [
        h
        for h in app.router.on_startup
        if h.__name__ == "_hexagon_active_graft_startup"
    ][0]
    await hook()
    assert isinstance(app.hexagon_ws_bridge, WsPublishBridge)
    assert app.hexagon_wiring.status._publish_bridge is app.hexagon_ws_bridge
    assert app.hexagon_ws_bridge._status_q is app.base.status_q
    assert app.hexagon_ws_bridge._data_q is app.base.data_q
    assert app.hexagon_ws_bridge._live_q is app.base.live_q


@pytest.mark.asyncio
async def test_status_adapter_unbound_is_fail_loud(installed_config):
    """Controller hardening 3 (Q1/D3 underpinning): a DispatcherStatusAdapter
    is unbound by default and stays fail-loud (UnwiredPortError on
    publish_status). This is what makes "makeOrchApp never binds" SAFE — only
    makeActionApp's startup hook binds the bridge (see
    test_action_app_startup_binds_ws_publish_bridge); makeOrchApp adds no bind
    call, verified by code review, so an orch composition's status adapter
    keeps this default-unbound fail-loud behavior. (Bare-adapter check; not a
    makeOrchApp integration test.)"""
    from helao.hexagon.adapters.errors import UnwiredPortError
    from helao.hexagon.adapters.legacy.status import DispatcherStatusAdapter

    a = DispatcherStatusAdapter("ORCH")
    with pytest.raises(UnwiredPortError):
        await a.publish_status({})


def test_vis_shims_delegate(monkeypatch):
    """P2d: each vis/operator shim exports the 4-arg makeBokehApp shape
    bokeh_launcher calls (doc positional; confPrefix/server_key/
    helao_repo_root as kwargs) and routes through factory.makeVisApp to
    the right legacy module."""
    from bokeh.document import Document

    import helao.deploy.hexagon.servers.operator.standalone_operator as op_shim
    import helao.deploy.hexagon.servers.visualizer.action_visualizer as av_shim
    import helao.deploy.hexagon.servers.visualizer.live_visualizer as lv_shim
    from helao.hexagon.app import factory

    expected = {
        op_shim: "helao.deploy.hte.servers.operator.standalone_operator",
        lv_shim: "helao.deploy.hte.servers.visualizer.live_visualizer",
        av_shim: "helao.deploy.hte.servers.visualizer.action_visualizer",
    }
    calls = {}

    class FakeLegacy:
        @staticmethod
        def makeBokehApp(doc, confPrefix, server_key, helao_repo_root):
            calls["args"] = (doc, confPrefix, server_key, helao_repo_root)
            return doc

    def fake_import(name):
        calls["module"] = name
        return FakeLegacy

    monkeypatch.setattr(factory, "import_module", fake_import)
    for shim, legacy_module in expected.items():
        assert shim.LEGACY_MODULE == legacy_module
        assert shim.FACTORY is factory.makeVisApp
        doc = Document()
        # the EXACT call shape bokeh_launcher.py:185-190 produces
        out = shim.makeBokehApp(
            doc, confPrefix="goldenhexvis", server_key="X", helao_repo_root="/repo"
        )
        assert out is doc
        assert calls["module"] == legacy_module
        assert calls["args"] == (doc, "goldenhexvis", "X", "/repo")
