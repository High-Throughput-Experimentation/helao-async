"""Composition factory: fail-loud wiring, OrchAPI construction with graft
hooks, action-app wrap, vis deferral, launcher shim delegation. Construction
level only — full lifecycle is the Task 12 launched smoke."""

import inspect
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
            # P7e: makeVisApp composes for real now, so its tests need a server
            # entry build_wiring can resolve.
            "OPERATOR": {
                "host": "127.0.0.1",
                "port": 5901,
                "group": "operator",
                "bokeh": "standalone_operator",
                "deployment": "hexagon",
                "params": {},
            },
            "LIVE": {
                "host": "127.0.0.1",
                "port": 5902,
                "group": "visualizer",
                "bokeh": "live_visualizer",
                "deployment": "hexagon",
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


def test_orchestrator_exposes_loaded_modules(installed_config):
    """An orchestrator must answer /loaded_modules, like every other `fast:` server.

    Two things depend on it, and both failed silently while it was missing.
    `launch.py`'s `server_loaded_files` POSTs it for anything with a `fast:` key
    and treats a non-200 as "no known mapping" -- which fails closed, so the
    hot-reload watcher never restarted an orchestrator no matter what changed
    under it. And it is the only external way to tell whether an orchestrator
    process is running the hexagon shim or the legacy module, because neither
    launcher logs the deployment when a config sets it explicitly.

    `OrchAPI` is a sibling of `BaseAPI`, not a subclass, so this is asserted on
    a real constructed app rather than on the shared registrar -- a registrar
    test would still pass if `OrchAPI` stopped calling it.
    """
    from helao.core.servers.base_api import BaseAPI
    from helao.hexagon.app.factory import makeOrchApp

    app = makeOrchApp("ORCH")
    routes = {r.path for r in app.routes}  # type: ignore[attr-defined]
    assert "/loaded_modules" in routes

    # Registered exactly once. It used to live on BaseAPI's __init__ as well;
    # hoisting it to the shared registrar without removing that would leave two
    # handlers on one path, where FastAPI silently serves the first.
    assert [r.path for r in app.routes].count("/loaded_modules") == 1  # type: ignore[attr-defined]
    assert not any(
        "/loaded_modules" in line
        for line in inspect.getsource(BaseAPI.__init__).splitlines()
    ), "duplicate /loaded_modules registration reintroduced on BaseAPI.__init__"

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


def test_make_action_app_wraps_legacy_module(installed_config):
    from helao.helpers.server_api import HelaoFastAPI
    from helao.hexagon.app.factory import makeActionApp

    app = makeActionApp("SIM", "helao.deploy.test.servers.action.ws_simulator")
    assert isinstance(app, HelaoFastAPI)
    assert app.hexagon_wiring is not None  # type: ignore[attr-defined]
    routes = {r.path for r in app.routes}  # type: ignore[attr-defined]
    assert "/SIM/acquire_data" in routes  # real legacy action route survived


def test_make_vis_app_delegates_to_legacy_module(installed_config, monkeypatch):
    """Compat-facade: makeVisApp imports the named legacy module and calls its
    makeBokehApp with the launcher-shaped args, leaving the RENDERING entirely
    legacy (D1/D2)."""
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


def test_make_vis_app_wires_the_hosted_process(installed_config, monkeypatch):
    """P7e: the hosted bokeh process is COMPOSED, not hexagon in name only.

    Every VIS_REQUIRED port is wired, ui_host is the P7d BokehServerUiHost, and
    the wiring rides the per-session Document the legacy module renders into.
    """
    from bokeh.document import Document

    from helao.hexagon.app import factory
    from helao.hexagon.app.ui_host import BokehServerUiHost
    from helao.hexagon.app.wiring import VIS_REQUIRED

    seen = {}

    class FakeLegacy:
        @staticmethod
        def makeBokehApp(doc, confPrefix, server_key, helao_repo_root):
            # the legacy app must be able to see the wiring while it builds
            seen["wiring_at_render"] = getattr(doc, "hexagon_wiring", None)
            return doc

    monkeypatch.setattr(factory, "import_module", lambda name: FakeLegacy)
    doc = Document()
    factory.makeVisApp("legacy.mod", doc, "goldenhexvis", "LIVE", "/repo")

    wiring = doc.hexagon_wiring  # type: ignore[attr-defined]
    assert wiring is not None
    assert seen["wiring_at_render"] is wiring
    assert isinstance(wiring.ui_host, BokehServerUiHost)
    for name in VIS_REQUIRED:
        assert getattr(wiring, name) is not None, name
    # ui_host is NOT a blanket requirement of the other compositions (P7d)
    from helao.hexagon.app.wiring import ACTION_REQUIRED, ORCH_REQUIRED

    assert "ui_host" not in ACTION_REQUIRED and "ui_host" not in ORCH_REQUIRED


def test_make_vis_app_raises_on_an_unwired_required_port(installed_config, monkeypatch):
    """Fail-loud composition (spec §4.5): an unwired VIS_REQUIRED port aborts
    the session BEFORE the legacy module is imported — a half-composed page is
    never rendered."""
    import pytest as _pytest
    from bokeh.document import Document

    from helao.hexagon.app import factory
    from helao.hexagon.app.wiring import PortWiring, UnwiredPortError
    from helao.hexagon.adapters.legacy.config import from_global_config

    imported = []
    monkeypatch.setattr(factory, "import_module", lambda name: imported.append(name))
    # config wired, logging deliberately absent
    monkeypatch.setattr(
        factory, "build_wiring", lambda key: PortWiring(config=from_global_config())
    )
    doc = Document()
    with _pytest.raises(UnwiredPortError) as ei:
        factory.makeVisApp("legacy.mod", doc, "goldenhexvis", "LIVE", "/repo")
    assert "logging" in str(ei.value)
    assert imported == []


def test_make_vis_app_raises_without_an_installed_config(monkeypatch):
    """No CONFIG at all is the other fail-loud leg: build_wiring raises rather
    than composing a vis process against nothing."""
    import pytest as _pytest
    from bokeh.document import Document

    from helao.helpers import config_loader
    from helao.hexagon.app import factory

    monkeypatch.setattr(config_loader, "CONFIG", None)
    with _pytest.raises(RuntimeError):
        factory.makeVisApp("legacy.mod", Document(), "goldenhexvis", "LIVE", "/repo")


def test_launcher_shims_delegate():
    import inspect

    import helao.deploy.hexagon.servers.action.ws_simulator as sim_shim
    import helao.deploy.hexagon.servers.orchestrator.async_orch2 as orch_shim
    from helao.hexagon.app import factory

    assert (
        orch_shim.makeApp.__module__
        == "helao.deploy.hexagon.servers.orchestrator.async_orch2"
    )
    assert sim_shim.LEGACY_MODULE == "helao.deploy.test.servers.action.ws_simulator"

    # B3b: the orchestrator shim no longer delegates to makeOrchApp. It
    # builds an OrchHost directly, because the host owns the reducer and
    # makeOrchApp's job was to graft it onto a legacy Orch that no longer
    # gets constructed here. The assertion inverts rather than disappears:
    # going back through the factory would wrap the engine again.
    assert not hasattr(orch_shim, "FACTORY")
    assert "OrchHost" in inspect.getsource(orch_shim.makeApp)
    # scoped to makeApp, not the module: the docstring names makeOrchApp
    # precisely to explain why it is no longer called.
    assert "makeOrchApp" not in inspect.getsource(orch_shim.makeApp)
    assert callable(factory.makeOrchApp)  # still there for unported compositions


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
    import helao.hexagon.adapters.legacy.status as status_mod
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
    import helao.hexagon.app.active_graft as active_graft_mod
    from helao.hexagon.adapters.native.ws_publish import WsPublishBridge
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
    # No injected `base` any more: makeActionApp returns an ActionHost, which
    # owns the three fan-out queues itself and answers to `app.base is app`.
    # Assigning one here raised AttributeError once `base` became a read-only
    # property, and the assertions below read the real queues regardless.
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


def test_vis_shims_delegate(installed_config, monkeypatch):
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
            doc, confPrefix="goldenhexvis", server_key="LIVE", helao_repo_root="/repo"
        )
        assert out is doc
        assert calls["module"] == legacy_module
        assert calls["args"] == (doc, "goldenhexvis", "LIVE", "/repo")
        assert doc.hexagon_wiring is not None  # type: ignore[attr-defined]
