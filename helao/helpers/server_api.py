import os
from socket import gethostname
from fastapi import FastAPI
from helao.helpers import helao_logging as logging
from helao.helpers import config_loader
from helao.core.models.machine import MachineModel
from helao.core.rpc import RPCDispatcher, derive_rpc_port

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
        # Install the action-aware route class so endpoints tagged
        # "action" are auto-wrapped to populate the per-request
        # ActionInvocation ContextVar. Defer the import to avoid
        # circular imports (base_api -> base -> server_api).
        from helao.core.servers.base_api import ActionAPIRoute

        self.router.route_class = ActionAPIRoute
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
        self.server = MachineModel(
            server_name=self.helao_srv,
            machine_name=gethostname().lower(),
            hostname=self.server_cfg["host"],
            port=self.server_cfg["port"],
        )
        # Co-located ZMQ-RPC dispatcher.  Routes registered as FastAPI POSTs
        # are auto-mirrored here at startup (see _rpc_startup) so callers can
        # reach them via the fast path.  Creating it here is purely the
        # registry side; the ROUTER socket is bound by the startup hook below
        # once the event loop is running.
        self.rpc_dispatcher = RPCDispatcher(server_key=helao_srv)

        @self.on_event("startup")
        async def _rpc_startup():
            # Walk registered routes and mirror every POST handler into the
            # dispatcher.  We do this at startup because FastAPI's @post()
            # decorator delegates through self.router (not self.add_api_route),
            # so an override at the app level would not catch them.
            #
            # Action routes (path "/<server_key>/...") are intentionally
            # included; callers using the RPC path bypass the action-queuing
            # middleware and are responsible for their own coordination.  In
            # practice today only ``update_status`` is migrated, but the
            # registration lets future callers opt in without code churn.
            from fastapi.routing import APIRoute  # local to avoid import order issues

            for route in self.routes:
                if isinstance(route, APIRoute) and "POST" in route.methods:
                    self.rpc_dispatcher.register(route.path, route.endpoint)

            await self.rpc_dispatcher.serve(
                host="0.0.0.0",
                port=derive_rpc_port(self.server_cfg["port"]),
            )

        @self.on_event("shutdown")
        async def _rpc_shutdown():
            await self.rpc_dispatcher.close()


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
        self.server = MachineModel(
            server_name=self.helao_srv,
            machine_name=gethostname().lower(),
            hostname=self.server_cfg["host"],
            port=self.server_cfg["port"],
        )
        self.doc_name = self.server_params.get(
            "doc_name", f"{self.helao_srv} Bokeh App"
        )
        self.doc = doc
        self.doc.title = self.doc_name
        self.vis = object()
