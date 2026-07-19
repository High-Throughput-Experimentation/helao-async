"""Hexagon-composed dbpack_server action server (P3b-2): wraps hte's legacy
dbpack_server makeApp through the hexagon factory (fail-loud wiring + co-located
RPC + native write/WS graft via makeActionApp). data-packaging / sync (HelaoSyncer; legacy syncer kept — native-sync cut-over is a separate P2e-style step). Same basename as the
legacy module so the config flips ONLY the `deployment:` key."""

from helao.hexagon.app.factory import makeActionApp

__all__ = ["makeApp"]

LEGACY_MODULE = "helao.deploy.hte.servers.action.dbpack_server"


def makeApp(server_key):
    return makeActionApp(server_key, LEGACY_MODULE)
