"""The hexagon sim_db_server shim is a plain makeActionApp delegate (B7b).

It used to register a sync-graft startup hook that swapped app.driver for a
NativeSyncer. The graft is gone: the test deployment's sim_db_server builds an
ActionHost whose driver the DB endpoints use directly, so the shim is the same
delegate as its siblings. The DB endpoint surface itself is pinned by
test_db_endpoint_surface."""

import pytest


def _world(tmp_path):
    return {
        "root": str(tmp_path),
        "dummy": True,
        "simulation": True,
        "servers": {
            "SYNC": {
                "host": "127.0.0.1",
                "port": 8910,
                "group": "action",
                "fast": "sim_db_server",
                "params": {"aws_bucket": "helao-sim", "s3_record": True},
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


def test_db_shim_is_a_plain_make_action_app_delegate(installed_config):
    from helao.deploy.hexagon.servers.action import sim_db_server as shim
    from helao.hexagon.app.action_host import ActionHost

    assert shim.LEGACY_MODULE == "helao.deploy.test.servers.action.sim_db_server"
    app = shim.makeApp("SYNC")
    assert isinstance(app, ActionHost)
    assert app.hexagon_wiring is not None  # set only by makeActionApp
    routes = {r.path for r in app.routes}  # type: ignore[attr-defined]
    # the real DB surface survived the wrap
    for path in ("/finish_yml", "/finish_pending", "/tasks", "/n_queue"):
        assert path in routes, path
    startup_names = [h.__name__ for h in app.router.on_startup]
    shutdown_names = [h.__name__ for h in app.router.on_shutdown]
    # makeActionApp's bridge hook is the last one registered: the shim adds none
    assert startup_names[-1] == "_hexagon_ws_bridge_startup"
    assert not any("sync_graft" in name for name in startup_names + shutdown_names)
