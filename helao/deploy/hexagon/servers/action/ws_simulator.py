"""Hexagon-composed websocket simulator: wraps the test deployment's real
ws_simulator makeApp through the hexagon factory (fail-loud wiring +
co-located RPC via HelaoFastAPI)."""

from helao.hexagon.app.factory import makeActionApp

__all__ = ["makeApp"]

LEGACY_MODULE = "helao.deploy.test.servers.action.ws_simulator"


def makeApp(server_key):
    return makeActionApp(server_key, LEGACY_MODULE)
