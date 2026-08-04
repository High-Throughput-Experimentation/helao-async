__all__ = ["makeBokehApp"]

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
    """Build the live-data visualizer Bokeh document.

    Instantiates a :class:`HelaoVis` host with a header banner, then mounts one
    per-instrument live visualizer for every action server in the config that
    declares a ``live_vis`` key (the ``*_vis.py`` module name). The mapping from
    action server to visualizer module lives in the config rather than this
    module, so this app is deployment-agnostic; see
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

    app.vis.doc.add_root(
        stretch_section(
            layout(
                [
                    Spacer(width=20),
                    Div(
                        text=f"<b>Live visualizer on {gethostname().lower()} -- config: {confPrefix}.py</b>",
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

    # create visualizer objects for action servers declaring a "live_vis" key
    mount_visualizers(app, "live_vis")

    return doc
