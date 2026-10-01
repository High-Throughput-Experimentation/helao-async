"""Hexagon-composed sim DB server: wraps the test deployment's real
sim_db_server makeApp through the hexagon factory (fail-loud wiring +
co-located RPC via HelaoFastAPI)."""

from helao.hexagon.app.factory import makeActionApp

__all__ = ["makeApp"]

LEGACY_MODULE = "helao.deploy.test.servers.action.sim_db_server"


def makeApp(server_key):
    return makeActionApp(server_key, LEGACY_MODULE)
