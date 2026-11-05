"""Composition factory: fail-loud wiring and the orchestrator's /loaded_modules
route. Construction level only — full lifecycle
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

    w = build_wiring("ORCH")
    assert isinstance(w.config, ConfigPort)
    assert isinstance(w.logging, LoggingPort)
    assert isinstance(w.clock, ClockPort)
    assert w.config.world_cfg() is installed_config  # raw-dict identity end-to-end
    w.require("config", "logging", "clock", "state_persistence")


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
