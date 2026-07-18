"""Hexagon-hosted standalone operator: same module/bokeh name as the hte
app so a config flips ONLY the `deployment:` key. P2d compat-facade —
delegates to the legacy makeBokehApp UNMODIFIED (native vis = P3)."""

from helao.hexagon.app.factory import makeVisApp

__all__ = ["makeBokehApp"]

LEGACY_MODULE = "helao.deploy.hte.servers.operator.standalone_operator"
FACTORY = makeVisApp


def makeBokehApp(doc, confPrefix, server_key, helao_repo_root):
    return FACTORY(LEGACY_MODULE, doc, confPrefix, server_key, helao_repo_root)
