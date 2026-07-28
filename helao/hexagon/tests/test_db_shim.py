"""P2e DB shim (D2): the launcher-visible hexagon sim_db_server module wraps
the legacy DB makeApp through makeActionApp and registers the sync-graft
startup hook LAST (Starlette preserves registration order, so it runs after
BaseAPI's own startup has bound app.base + the legacy driver). Construction
level only — full lifecycle is the Task 4 launched GM-5 gate."""

from types import SimpleNamespace

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


def test_db_shim_wraps_legacy_and_registers_sync_hook_last(installed_config):
    from helao.helpers.server_api import HelaoFastAPI

    from helao.deploy.hexagon.servers.action import sim_db_server as shim

    assert shim.LEGACY_MODULE == "helao.deploy.test.servers.action.sim_db_server"
    app = shim.makeApp("SYNC")
    assert isinstance(app, HelaoFastAPI)
    assert app.hexagon_wiring is not None  # type: ignore[attr-defined]
    assert app.hexagon_sync_graft is None  # type: ignore[attr-defined]  # applied at startup
    routes = {r.path for r in app.routes}  # type: ignore[attr-defined]
    # real legacy DB surface survived the wrap (sim_db_server.py:99-151)
    for path in ("/finish_yml", "/finish_pending", "/tasks", "/n_queue"):
        assert path in routes, path
    startup_names = [h.__name__ for h in app.router.on_startup]
    shutdown_names = [h.__name__ for h in app.router.on_shutdown]
    assert "_hexagon_active_graft_startup" in startup_names
    assert "_hexagon_sync_graft_startup" in startup_names
    # ours LAST: after BaseAPI's startup_event AND the active-graft hook
    assert startup_names[-1] == "_hexagon_sync_graft_startup"
    assert "_hexagon_sync_graft_shutdown" in shutdown_names


@pytest.mark.asyncio
async def test_db_shim_startup_hook_calls_graft_with_base_params(
    installed_config, monkeypatch
):
    """The hook passes the LIVE app.base + its local server params into
    graft_native_sync and stores the handle (isolated from Task 1's graft
    internals — those have their own tests)."""
    from helao.deploy.hexagon.servers.action import sim_db_server as shim

    calls = {}

    def fake_graft(base, params):
        calls["base"] = base
        calls["params"] = params
        return "HANDLE"

    monkeypatch.setattr(shim, "graft_native_sync", fake_graft)
    app = shim.makeApp("SYNC")
    app.base = SimpleNamespace(
        server_cfg={"params": {"aws_bucket": "helao-sim", "s3_record": True}}
    )
    hook = [
        h for h in app.router.on_startup if h.__name__ == "_hexagon_sync_graft_startup"
    ][0]
    await hook()
    assert app.hexagon_sync_graft == "HANDLE"
    assert calls["base"] is app.base
    assert calls["params"] == {"aws_bucket": "helao-sim", "s3_record": True}


@pytest.mark.asyncio
async def test_db_shim_shutdown_hook_closes_graft(installed_config, monkeypatch):
    from helao.deploy.hexagon.servers.action import sim_db_server as shim

    closed = {"n": 0}

    class FakeHandle:
        def close(self):
            closed["n"] += 1

    monkeypatch.setattr(shim, "graft_native_sync", lambda b, p: FakeHandle())
    app = shim.makeApp("SYNC")
    app.base = SimpleNamespace(server_cfg={"params": {}})
    startup = [
        h for h in app.router.on_startup if h.__name__ == "_hexagon_sync_graft_startup"
    ][0]
    shutdown = [
        h
        for h in app.router.on_shutdown
        if h.__name__ == "_hexagon_sync_graft_shutdown"
    ][0]
    await startup()
    await shutdown()
    assert closed["n"] == 1
