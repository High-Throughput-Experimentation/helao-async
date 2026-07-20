"""Hexagon-composed analysis_server action server (P3b-2): wraps hte's legacy
analysis_server makeApp through the hexagon factory (fail-loud wiring + co-located
RPC + native write/WS graft via makeActionApp). analysis (config-driven analyze_<name> endpoints via make_analysis_app). Same basename as the
legacy module so the config flips ONLY the `deployment:` key."""

from helao.hexagon.app.factory import makeActionApp

__all__ = ["makeApp"]

LEGACY_MODULE = "helao.deploy.hte.servers.action.analysis_server"


def makeApp(server_key):
    return makeActionApp(server_key, LEGACY_MODULE)
