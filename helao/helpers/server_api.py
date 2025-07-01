import os
from fastapi import FastAPI
from helao.helpers import helao_logging as logging
from helao.helpers import config_loader
CONFIG = config_loader.CONFIG

__all__ = ["HelaoBokehAPI", "HelaoFastAPI"]


TAGS = [
    {
        "name": "action",
        "description": "action endpoints will register status and block",
    },
    {"name": "private", "description": "private endpoints don't create actions"},
]


class HelaoFastAPI(FastAPI):
    """
    HelaoFastAPI is a subclass of FastAPI that initializes with specific configuration
    parameters for the Helao server.

    Attributes:
        helao_cfg (dict): Configuration dictionary for Helao.
        helao_srv (str): Name of the Helao server.
        server_cfg (dict): Configuration dictionary for the specific server.
        server_params (dict): Additional parameters for the server.

    Methods:
        __init__(helao_srv: str, *args, **kwargs):
            Initializes the HelaoFastAPI instance with the given configuration and server name.
    """

    def __init__(self, helao_srv: str, *args, **kwargs):
        """
        Initializes the server API with the given configuration.

        Args:
            helao_cfg (dict): Configuration dictionary for helao.
            helao_srv (str): Server name.
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.

        Attributes:
            helao_cfg (dict): Stores the helao configuration.
            helao_srv (str): Stores the server name.
            server_cfg (dict): Configuration for the specific server.
            server_params (dict): Parameters for the server configuration.
        """
        super().__init__(*args, **kwargs, openapi_tags=TAGS)
        self.helao_cfg = CONFIG
        self.helao_srv = helao_srv
        self.server_cfg = self.helao_cfg["servers"][self.helao_srv]
        self.server_params = self.server_cfg.get("params", {})
        if logging.LOGGER is None:
            logging.LOGGER = logging.make_logger(
                logger_name=helao_srv,
                log_dir=os.path.join(self.helao_cfg["root"], "LOGS"),
                show_debug_console=self.helao_cfg.get("show_debug", False),
            )


class HelaoBokehAPI:
    """
    A class to represent the Helao Bokeh API.

    Attributes:
    -----------
    helao_srv : str
        Name of the Helao server.
    doc : Document
        Bokeh document object.

    Methods:
    --------
    __init__(self, helao_srv: str, doc):
        Initializes the HelaoBokehAPI with the given configuration, server name, and Bokeh document.
    """

    def __init__(self, helao_srv: str, doc):
        self.helao_srv = helao_srv
        self.helao_cfg = CONFIG
        self.server_cfg = self.helao_cfg["servers"][self.helao_srv]
        self.server_params = self.server_cfg.get("params", {})
        if logging.LOGGER is None:
            logging.LOGGER = logging.make_logger(
                logger_name=helao_srv,
                log_dir=os.path.join(self.helao_cfg["root"], "LOGS"),
                show_debug_console=self.helao_cfg.get("show_debug", False),
            )
        self.doc_name = self.server_params.get(
            "doc_name", f"{self.helao_srv} Bokeh App"
        )
        self.doc = doc
        self.doc.title = self.doc_name
        self.vis = object()
