"""
This module contains the implementation of the HelaoVis and Vis classes for the Helao visualization server.

Classes:
    HelaoVis(HelaoBokehAPI): A server class that extends the HelaoBokehAPI to provide visualization capabilities.
    Vis: A class to represent the visualization server.

HelaoVis:


Vis:
        server (MachineModel): An instance of MachineModel representing the server.
        server_cfg (dict): Configuration dictionary for the server.
        world_cfg (dict): Global configuration dictionary.
        doc (Document): Bokeh document instance.
        helaodirs (HelaoDirs): Directories used by the Helao system.

        __init__(bokehapp: HelaoBokehAPI):
        print_message(*args, **kwargs):
"""

__all__ = ["Vis", "HelaoVis"]

from socket import gethostname
from helao.helpers import helao_logging as logging
from helao.helpers.server_api import HelaoBokehAPI
from helao.helpers.helao_dirs import helao_dirs
from helao.helpers.print_message import print_message
from helao.core.models.machine import MachineModel

LOGGER = logging.LOGGER


# TODO: HelaoVis will return doc to replace makeBokehApp func
class HelaoVis(HelaoBokehAPI):
    """
    HelaoVis is a server class that extends the HelaoBokehAPI to provide visualization capabilities.

    Attributes:
        vis (Vis): An instance of the Vis class for handling visualization tasks.

    Methods:
        __init__(config, server_key, doc):
            Initialize the Vis server with the given configuration, server key, and documentation object.
    """

    def __init__(
        self,
        server_key,
        doc,
    ):
        """
        Initialize the Vis server.

        Args:
            config (dict): Configuration dictionary for the server.
            server_key (str): Unique key identifying the server.
            doc (object): Documentation object for the server.
        """
        super().__init__(server_key, doc)
        self.vis = Vis(self)


class Vis:
    """
    A class to represent the visualization server.

    Attributes
    ----------
    server : MachineModel
        An instance of MachineModel representing the server.
    server_cfg : dict
        Configuration dictionary for the server.
    world_cfg : dict
        Global configuration dictionary.
    doc : Document
        Bokeh document instance.
    helaodirs : HelaoDirs
        Directories used by the Helao system.

    Methods
    -------
    __init__(bokehapp: HelaoBokehAPI)
        Initializes the Vis instance with the given Bokeh application.
    print_message(*args, **kwargs)
        Prints a message using the server configuration and log directory.
    """

    def __init__(self, bokehapp: HelaoBokehAPI):
        """
        Initializes the visualization server.

        Args:
            bokehapp (HelaoBokehAPI): An instance of the HelaoBokehAPI class.

        Raises:
            ValueError: If the root directory is not defined in the configuration.
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
                "Warning: root directory was not defined. Logs, PRCs, PRGs, and data will not be written.",
                error=True,
            )

    def print_message(self, *args, **kwargs):
        """
        Prints a message with the server configuration and server name.

        Parameters:
        *args: Variable length argument list.
        **kwargs: Arbitrary keyword arguments.

        Returns:
        None
        """
        print_message(
            LOGGER,
            self.server.server_name,
            log_dir=self.helaodirs.log_root,
            *args,
            **kwargs
        )
