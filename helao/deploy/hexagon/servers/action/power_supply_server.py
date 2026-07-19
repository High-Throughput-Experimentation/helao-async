"""Hexagon-composed power supply action server (P3b): wraps hte's legacy
power_supply_server makeApp through the hexagon factory (fail-loud wiring + co-located
RPC + native write/WS graft via makeActionApp). Same basename as the legacy
module so the config flips ONLY the `deployment:` key."""

from helao.hexagon.app.factory import makeActionApp

__all__ = ["makeApp"]

LEGACY_MODULE = "helao.deploy.hte.servers.action.power_supply_server"


def makeApp(server_key):
    return makeActionApp(server_key, LEGACY_MODULE)
