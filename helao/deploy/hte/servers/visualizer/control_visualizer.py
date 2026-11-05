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

from ._vis_host import build_vis_host
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

    return build_vis_host(
        doc, server_key, "control_vis", "Engineering controls", lambda app: confPrefix
    )
