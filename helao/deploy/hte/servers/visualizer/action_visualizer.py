__all__ = ["makeBokehApp"]

import os
from ._vis_host import build_vis_host
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


def makeBokehApp(doc, confPrefix, server_key, helao_repo_root):
    """Build the action-visualizer Bokeh document.

    Instantiates a :class:`HelaoVis` host, adds a header banner, then mounts one
    per-action visualizer for every action server in the config that declares an
    ``action_vis`` key (the ``*_vis.py`` module name). The mapping from action
    server to visualizer module lives in the config rather than this module, so
    this app is deployment-agnostic; see
    :func:`helao.ui.bokeh.vis_subscriber.mount_visualizers`.

    Args:
        doc: Bokeh document supplied by the Bokeh server for this session.
        confPrefix: Config prefix passed by ``bokeh_launcher.py``.
        server_key: Visualizer server key from the configuration.
        helao_repo_root: Absolute path to the HELAO repo root.

    Returns:
        Bokeh ``Document``: The same ``doc`` passed in, with all visualizer
        layouts mounted as roots.
    """

    return build_vis_host(
        doc,
        server_key,
        "action_vis",
        "Action visualizer",
        lambda app: os.path.basename(app.helao_cfg["loaded_config_path"]),
    )
