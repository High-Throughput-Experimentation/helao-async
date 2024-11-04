from fastapi import FastAPI
from helao.helpers import logging
import os

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
        __init__(helao_cfg: dict, helao_srv: str, *args, **kwargs):
            Initializes the HelaoFastAPI instance with the given configuration and server name.
    """

    def __init__(self, helao_cfg: dict, helao_srv: str, *args, **kwargs):
        super().__init__(*args, **kwargs, openapi_tags=TAGS)
        self.helao_cfg = helao_cfg
        self.helao_srv = helao_srv
        self.server_cfg = self.helao_cfg["servers"][self.helao_srv]
        self.server_params = self.server_cfg.get("params", {})
        if logging.LOGGER is None:
            logging.LOGGER = logging.make_logger(
                logger_name=helao_srv, log_dir=os.path.join(helao_cfg["root"], "LOGS")
            )


class HelaoBokehAPI:
    """
    A class to represent the Helao Bokeh API.

    Attributes:
    -----------
    helao_cfg : dict
        Configuration dictionary for Helao.
    helao_srv : str
        Name of the Helao server.
    doc : Document
        Bokeh document object.

    Methods:
    --------
    __init__(self, helao_cfg: dict, helao_srv: str, doc):
        Initializes the HelaoBokehAPI with the given configuration, server name, and Bokeh document.
    """

    def __init__(self, helao_cfg: dict, helao_srv: str, doc):
        self.helao_srv = helao_srv
        self.helao_cfg = helao_cfg
        self.server_cfg = self.helao_cfg["servers"][self.helao_srv]
        self.server_params = self.server_cfg.get("params", {})
        if logging.LOGGER is None:
            logging.LOGGER = logging.make_logger(
                logger_name=helao_srv, log_dir=os.path.join(helao_cfg["root"], "LOGS")
            )
        self.doc_name = self.server_params.get(
            "doc_name", f"{self.helao_srv} Bokeh App"
        )
        self.doc = doc
        self.doc.title = self.doc_name
        self.vis = object()
