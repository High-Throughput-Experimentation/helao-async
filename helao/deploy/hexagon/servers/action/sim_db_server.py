"""Hexagon-composed sim DB server (P2e, D2): wraps the test deployment's
real sim_db_server makeApp through the hexagon factory (fail-loud wiring +
co-located RPC via HelaoFastAPI), then registers ONE extra startup hook —
after makeActionApp's own, which is after BaseAPI's — that cuts app.driver
over to the raw P2c NativeSyncer (sync_graft.py). Same basename as the
legacy module so the config flips ONLY the `deployment:` key."""

from helao.hexagon.app.factory import makeActionApp
from helao.hexagon.app.sync_graft import graft_native_sync

__all__ = ["makeApp"]

LEGACY_MODULE = "helao.deploy.test.servers.action.sim_db_server"


def makeApp(server_key):
    app = makeActionApp(server_key, LEGACY_MODULE)
    app.hexagon_sync_graft = None

    # Registered AFTER BaseAPI's startup_event (app.base + the legacy
    # SimHelaoSyncer on app.driver are live) and AFTER the factory's
    # _hexagon_active_graft_startup (Starlette preserves registration
    # order): the graft cancels the legacy syncer loops and rebinds native.
    @app.on_event("startup")
    async def _hexagon_sync_graft_startup():
        app.hexagon_sync_graft = graft_native_sync(
            app.base, app.base.server_cfg.get("params", {})
        )

    @app.on_event("shutdown")
    async def _hexagon_sync_graft_shutdown():
        if app.hexagon_sync_graft is not None:
            app.hexagon_sync_graft.close()

    return app
