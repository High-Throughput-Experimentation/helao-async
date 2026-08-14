"""hte deployment shim for the data browser visualizer.

The browser logic is deployment-agnostic and lives in
``helao.core.servers.data_browser``; this module only provides the
``makeBokehApp`` factory the bokeh launcher imports.
"""

from helao.ui.bokeh.data_browser import build_document
from helao.ui.bokeh.vis import HelaoVis


def makeBokehApp(doc, confPrefix, server_key, helao_repo_root):
    """Build the data browser Bokeh document for this server key."""
    app = HelaoVis(server_key=server_key, doc=doc)
    build_document(app.vis)
    return doc
