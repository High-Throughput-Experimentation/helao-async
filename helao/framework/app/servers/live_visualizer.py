# helao/framework/app/servers/live_visualizer.py
"""Deployment-agnostic live-data visualizer host (framework app layer)."""
__all__ = ["makeBokehApp"]

import os
from socket import gethostname

from bokeh.models.widgets import Div
from bokeh.layouts import layout, Spacer

from helao.framework.app.vis import HelaoVis
from helao.framework.adapters.vis_subscriber import mount_visualizers
from helao.framework.support import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


def makeBokehApp(doc, confPrefix, server_key, helao_repo_root):
    """Build the live-visualizer Bokeh document; mount per-server ``live_vis`` modules."""
    app = HelaoVis(server_key=server_key, doc=doc)
    app.vis.doc.add_root(
        layout(
            [
                Spacer(width=20),
                Div(
                    text=f"<b>Live visualizer on {gethostname().lower()} -- config: {confPrefix}</b>",
                    width=1004,
                    height=32,
                    styles={"font-size": "200%", "color": "#CB4335"},
                ),
            ],
            width=1024,
        )
    )
    app.vis.doc.add_root(Spacer(height=10))
    mount_visualizers(app, "live_vis")
    return doc
