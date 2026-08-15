"""Bokeh visualization server base classes for HELAO."""

__all__ = ["Vis", "HelaoVis"]

from socket import gethostname

from helao.core.models.machine import MachineModel
from helao.ui.bokeh.theme import apply_theme
from helao.helpers import helao_logging as logging
from helao.helpers.helao_dirs import helao_dirs
from helao.helpers.helao_logging import print_message
from helao.helpers.server_api import HelaoBokehAPI

LOGGER = logging.LOGGER


# TODO: HelaoVis will return doc to replace makeBokehApp func
class HelaoVis(HelaoBokehAPI):
    """Bokeh application wrapper that pairs a ``HelaoBokehAPI`` with a ``Vis`` helper.

    Attributes:
        vis: ``Vis`` instance that exposes config, directories and a logger
            for the underlying Bokeh document.
    """

    def __init__(
        self,
        server_key,
        doc,
    ):
        """Initialize the Bokeh visualization server.

        Args:
            server_key: Unique key identifying the server in the world config.
            doc: Bokeh ``Document`` for this server instance.
        """
        super().__init__(server_key, doc)
        # Single seam for the palette: every HELAO Bokeh document is a HelaoVis,
        # including the aligner whose Server is built inside an action-server
        # process and never passes through bokeh_launcher.py.
        apply_theme(self.doc)
        self.vis = Vis(self)


class Vis:
    """Per-server visualization helper.

    Wraps server identity, the loaded world config, the Bokeh document, and
    the HELAO directory layout so visualizer code can share a single entry
    point for printing and resolving paths.

    Attributes:
        server: ``MachineModel`` describing the server name and host.
        server_cfg: Configuration dictionary for this server entry.
        world_cfg: Full HELAO world configuration.
        doc: The Bokeh document associated with this visualizer.
        helaodirs: Resolved HELAO directory layout.
    """

    def __init__(self, bokehapp: HelaoBokehAPI):
        """Wire the visualization helper to a running Bokeh app.

        Args:
            bokehapp: The ``HelaoBokehAPI`` instance hosting this visualizer.

        Raises:
            ValueError: If the world config does not define a root directory.
        """
        self.server = MachineModel(
            server_name=bokehapp.helao_srv, machine_name=gethostname().lower()
        )
        self.server_cfg = bokehapp.helao_cfg["servers"][self.server.server_name]
        self.world_cfg = bokehapp.helao_cfg
        self.doc = bokehapp.doc

        self.helaodirs = helao_dirs(self.world_cfg, self.server.server_name)

        if self.helaodirs.root is None:
            raise ValueError(
                "Warning: root directory was not defined. Logs, PRCs, PRGs, and data will not be written."
            )

    def print_message(self, *args, **kwargs):
        """Forward a log message through the shared HELAO logger.

        Args:
            *args: Positional message arguments passed through to ``print_message``.
            **kwargs: Keyword arguments forwarded to the logger.
        """
        print_message(
            LOGGER,
            self.server.server_name,
            log_dir=self.helaodirs.log_root,
            *args,
            **kwargs,
        )
