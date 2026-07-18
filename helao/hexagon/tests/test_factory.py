"""Composition factory: fail-loud wiring, OrchAPI construction with graft
hooks, action-app wrap, vis deferral, launcher shim delegation. Construction
level only — full lifecycle is the Task 12 launched smoke."""

import pytest

from helao.hexagon.adapters.errors import HexagonDeferred


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


def test_make_vis_app_defers_loudly():
    from helao.hexagon.app.factory import makeVisApp

    with pytest.raises(HexagonDeferred):
        makeVisApp("LIVE")


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
