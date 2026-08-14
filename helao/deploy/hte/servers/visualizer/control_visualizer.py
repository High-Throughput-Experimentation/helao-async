"""Engineering control panel: the Bokeh page hosting every ``control_vis``.

The third visualizer host, beside ``action_visualizer`` and ``live_visualizer``
and built the same way: it mounts one panel per action server that declares a
``control_vis`` key. A separate key rather than reusing ``action_vis`` because a
server can want both — the NI server already declares ``action_vis: nidaqmx_vis``
for its plots, and the control panel is a different page's worth of widgets.

``mount_visualizers`` and ``import_vis_class`` are generic over the key name, so
nothing else in the framework needed changing to add this one.
"""

__all__ = ["makeBokehApp"]

from socket import gethostname

from bokeh.layouts import Spacer, layout
from bokeh.models.widgets import Div

from helao.ui.bokeh.theme import SECTION_MARGIN, stretch_section
from helao.ui.shared.palette import HEADING_TEXT
from helao.core.servers.vis import HelaoVis
from helao.core.servers.vis_subscriber import mount_visualizers
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


def makeBokehApp(doc, confPrefix, server_key, helao_repo_root):
    """Build the engineering control-panel Bokeh document.

    Args:
        doc: Bokeh document supplied by the Bokeh server for this session.
        confPrefix: Config prefix passed by ``bokeh_launcher.py``.
        server_key: Visualizer server key from the configuration.
        helao_repo_root: Absolute path to the HELAO repo root.

    Returns:
        Bokeh ``Document``: The same ``doc``, with one control panel mounted
        per action server declaring ``control_vis``.
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
                        text=(
                            f"<b>Engineering controls on {gethostname().lower()}"
                            f" -- config: {confPrefix}</b>"
                        ),
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

    mount_visualizers(app, "control_vis")

    return doc
