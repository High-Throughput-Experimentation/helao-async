__all__ = ["makeBokehApp"]

import os
from socket import gethostname

from bokeh.layouts import Spacer, layout
from bokeh.models.widgets import Div

from helao.core.servers.palette import HEADING_TEXT
from helao.core.servers.bokeh_theme import SECTION_MARGIN, stretch_section
from helao.core.servers.vis import HelaoVis
from helao.core.servers.vis_subscriber import mount_visualizers
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


def makeBokehApp(doc, confPrefix, server_key, helao_repo_root):
    """Build the action-visualizer Bokeh document.

    Instantiates a :class:`HelaoVis` host, adds a header banner, then mounts one
    per-action visualizer for every action server in the config that declares an
    ``action_vis`` key (the ``*_vis.py`` module name). The mapping from action
    server to visualizer module lives in the config rather than this module, so
    this app is deployment-agnostic; see
    :func:`helao.core.servers.vis_subscriber.mount_visualizers`.

    Args:
        doc: Bokeh document supplied by the Bokeh server for this session.
        confPrefix: Config prefix passed by ``bokeh_launcher.py``.
        server_key: Visualizer server key from the configuration.
        helao_repo_root: Absolute path to the HELAO repo root.

    Returns:
        Bokeh ``Document``: The same ``doc`` passed in, with all visualizer
        layouts mounted as roots.
    """

    app = HelaoVis(
        server_key=server_key,
        doc=doc,
    )
    config = app.helao_cfg
    config_filename = os.path.basename(config["loaded_config_path"])

    app.vis.doc.add_root(
        stretch_section(
            layout(
                [
                    Spacer(width=20),
                    Div(
                        text=f"<b>Action visualizer on {gethostname().lower()} -- config: {config_filename}</b>",
                        sizing_mode="stretch_width",
                        height=32,
                        styles={"font-size": "200%", "color": HEADING_TEXT},
                    ),
                ],
                margin=SECTION_MARGIN,
            )
        )
    )
    app.vis.doc.add_root(Spacer(height=10))

    # create visualizer objects for action servers declaring an "action_vis" key
    mount_visualizers(app, "action_vis")

    return doc
