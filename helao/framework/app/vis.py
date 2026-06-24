"""Bokeh visualization host for the HELAO framework (app layer).

Ports legacy ``core/servers/vis.py`` and the Bokeh half of
``helpers/server_api.py:HelaoBokehAPI`` into the framework ``app/`` layer.
``HelaoVis`` hosts the Bokeh ``Document`` and server identity; ``Vis`` is the
per-server helper exposing config, directories and a logger; ``makeBokehApp``
is the factory the bokeh launcher imports.
"""

__all__ = ["Vis", "HelaoVis", "makeBokehApp"]

import os
from socket import gethostname

from bokeh.models.widgets import Div
from bokeh.layouts import layout, Spacer

from helao.framework.support import helao_logging as logging
from helao.framework.support import config_loader
from helao.framework.support.helao_dirs import helao_dirs
from helao.framework.models.machine import MachineModel

LOGGER = logging.LOGGER


class HelaoVis:
    """Bokeh application host: server identity + document + ``Vis`` helper.

    Reads ``config_loader.CONFIG`` live, initializes the logger if unset,
    builds a :class:`MachineModel`, titles the document from
    ``params.doc_name``, and constructs a :class:`Vis` onto ``self.vis``.
    """

    def __init__(self, server_key, doc):
        self.helao_srv = server_key
        self.helao_cfg = config_loader.CONFIG
        self.server_cfg = self.helao_cfg["servers"][self.helao_srv]
        self.server_params = self.server_cfg.get("params", {})
        if logging.LOGGER is None:
            logging.LOGGER = logging.make_logger(
                logger_name=server_key,
                log_dir=os.path.join(self.helao_cfg["root"], "LOGS")
                if "root" in self.helao_cfg
                else None,
                show_debug_console=self.helao_cfg.get("show_debug", False),
            )
        self.server = MachineModel(
            server_name=self.helao_srv,
            machine_name=gethostname().lower(),
        )
        self.doc_name = self.server_params.get("doc_name", f"{self.helao_srv} Bokeh App")
        self.doc = doc
        self.doc.title = self.doc_name
        self.vis = Vis(self)


class Vis:
    """Per-server visualization helper (config, directories, logger)."""

    def __init__(self, bokehapp):
        self.server = MachineModel(
            server_name=bokehapp.helao_srv, machine_name=gethostname().lower()
        )
        self.server_cfg = bokehapp.helao_cfg["servers"][self.server.server_name]
        self.world_cfg = bokehapp.helao_cfg
        self.doc = bokehapp.doc

        self.helaodirs = helao_dirs(self.world_cfg, self.server.server_name)

        if self.helaodirs.root is None:
            raise ValueError(
                "Warning: root directory was not defined. "
                "Logs, PRCs, PRGs, and data will not be written."
            )

    def print_message(self, *args, **kwargs):
        # Drop log_dir kwarg: the framework print_message does not accept it.
        kwargs.pop("log_dir", None)
        logging.print_message(
            logging.LOGGER,
            self.server.server_name,
            *args,
            **kwargs,
        )


def makeBokehApp(doc, confPrefix, server_key, helao_repo_root):
    """Build a generic Bokeh visualizer document for ``server_key``.

    Hosts a :class:`HelaoVis`, mounts a header banner, then mounts one
    per-action visualizer for every server declaring an ``action_vis`` key.
    Deployment-specific visualizer apps may provide their own ``makeBokehApp``.
    """
    from helao.framework.adapters.vis_subscriber import mount_visualizers

    app = HelaoVis(server_key=server_key, doc=doc)
    config = app.helao_cfg
    config_filename = os.path.basename(config["loaded_config_path"])

    app.vis.doc.add_root(
        layout(
            [
                Spacer(width=20),
                Div(
                    text=f"<b>Visualizer on {gethostname().lower()} -- config: {config_filename}</b>",
                    width=1004,
                    height=32,
                    styles={"font-size": "200%", "color": "#CB4335"},
                ),
            ],
            width=1024,
        )
    )
    app.vis.doc.add_root(Spacer(height=10))
    mount_visualizers(app, "action_vis")
    return doc
