"""Shared Bokeh document builder for the three vis host apps.

``action_visualizer``, ``live_visualizer`` and ``control_visualizer`` differ
only in the config key they mount and their banner text; the launcher resolves
each by module name, so each keeps a thin ``makeBokehApp`` that calls this.
"""

from socket import gethostname

from bokeh.layouts import Spacer, layout
from bokeh.models.widgets import Div

from helao.ui.bokeh.theme import SECTION_MARGIN, stretch_section
from helao.ui.bokeh.vis import HelaoVis
from helao.ui.bokeh.vis_subscriber import mount_visualizers
from helao.ui.shared.palette import HEADING_TEXT


def build_vis_host(doc, server_key, vis_key, title, config_name):
    """Build a visualizer host document and mount every ``vis_key`` panel.

    Args:
        doc: Bokeh document supplied by the Bokeh server for this session.
        server_key: Visualizer server key from the configuration.
        vis_key: Per-action-server config key naming the panel module.
        title: Banner prefix, e.g. ``"Action visualizer"``.
        config_name: Callable taking the :class:`HelaoVis` app and returning
            the config name shown in the banner.

    Returns:
        The same ``doc``, with the banner and all panels mounted as roots.
    """
    app = HelaoVis(server_key=server_key, doc=doc)
    app.vis.doc.add_root(
        stretch_section(
            layout(
                [
                    Spacer(width=20),
                    Div(
                        text=f"<b>{title} on {gethostname().lower()} -- config: {config_name(app)}</b>",
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
    mount_visualizers(app, vis_key)
    return doc
