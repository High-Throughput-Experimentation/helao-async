import os
from socket import gethostname
from typing import Optional
from fastapi import FastAPI
from helao.helpers import helao_logging as logging
from helao.helpers import config_loader
from helao.core.models.machine import MachineModel
from helao.core.rpc import RPCDispatcher, derive_rpc_port

"""FastAPI and Bokeh application base classes used by every HELAO server.

Provides :class:`HelaoFastAPI`, a FastAPI subclass that wires in the HELAO
config, logger, machine model, action-aware route class, and co-located ZMQ
RPC dispatcher; and :class:`HelaoBokehAPI`, the equivalent helper for Bokeh
visualizer/operator apps.
"""

__all__ = ["HelaoBokehAPI", "HelaoFastAPI"]


TAGS = [
    {
        "name": "action",
        "description": "action endpoints will register status and block",
    },
    {"name": "private", "description": "private endpoints don't create actions"},
]


class HelaoFastAPI(FastAPI):
    """FastAPI app preconfigured for a HELAO server group entry.

    Installs the action-aware ``ActionAPIRoute`` route class, attaches the
    server's HELAO config slice, builds a :class:`MachineModel`, ensures the
    process-wide logger is initialized, and creates a co-located ZMQ
    :class:`RPCDispatcher` that mirrors every POST route at startup.

    Attributes:
        helao_cfg: Full HELAO configuration dict.
        helao_srv: Server key in ``helao_cfg["servers"]``.
        server_cfg: Per-server config slice.
        server_params: Optional ``params`` block from the server config.
        server: :class:`MachineModel` describing this server's identity.
        rpc_dispatcher: ZMQ dispatcher mirroring POST endpoints.
    """

    def __init__(
        self,
        helao_srv: str,
        *args,
        helao_cfg: Optional[dict] = None,
        **kwargs,
    ):
        """Initialize the FastAPI app and register startup/shutdown hooks.

        Args:
            helao_srv: Server key used to look up this server's configuration.
            *args: Forwarded to :class:`fastapi.FastAPI`.
            helao_cfg: Optional config dict to use instead of the module-level
                ``config_loader.CONFIG`` (injection seam for tests/callers).
            **kwargs: Forwarded to :class:`fastapi.FastAPI`.
        """
        super().__init__(*args, **kwargs, openapi_tags=TAGS)
        # Install the action-aware route class so endpoints tagged
        # "action" are auto-wrapped to populate the per-request
        # ActionInvocation ContextVar. Defer the import to avoid
        # circular imports (base_api -> base -> server_api).
        from helao.core.servers.base_api import ActionAPIRoute

        self.router.route_class = ActionAPIRoute
        self.helao_cfg = helao_cfg if helao_cfg is not None else config_loader.CONFIG
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

            # Bind the ROUTER to the wildcard interface, not the configured
            # host.  libzmq's ``bind(tcp://<fqdn>:port)`` resolves the name and
            # binds a single concrete address; when that address is not a
            # currently-assigned local interface (e.g. a config host set to the
            # machine's FQDN whose DNS record points at an IPv6/stale address)
            # the bind fails with ``Address not available`` (WSAEADDRNOTAVAIL on
            # Windows).  Uvicorn tolerates this because asyncio binds every
            # resolved addrinfo; ZMQ does not.  Binding ``0.0.0.0`` accepts on
            # all local interfaces, so callers dialing the concrete config host
            # still reach it.
            await self.rpc_dispatcher.serve(
                host="0.0.0.0",
                port=derive_rpc_port(self.server_cfg["port"]),
            )

        @self.on_event("shutdown")
        async def _rpc_shutdown():
            await self.rpc_dispatcher.close()


class HelaoBokehAPI:
    """Bokeh application wrapper that mirrors :class:`HelaoFastAPI` setup.

    Attaches the HELAO config slice, ensures the logger is initialized, builds
    a :class:`MachineModel`, sets the Bokeh document title from
    ``params.doc_name``, and stores a placeholder ``vis`` attribute for the
    concrete visualizer to overwrite.

    Attributes:
        helao_srv: Server key in ``helao_cfg["servers"]``.
        helao_cfg: Full HELAO configuration dict.
        server_cfg: Per-server config slice.
        server_params: Optional ``params`` block from the server config.
        server: :class:`MachineModel` describing this server's identity.
        doc_name: Title applied to the Bokeh document.
        doc: The Bokeh ``Document`` for this app.
        vis: Placeholder object overwritten by the concrete visualizer.
    """

    def __init__(self, helao_srv: str, doc, helao_cfg: Optional[dict] = None):
        """Initialize logging, machine identity, and the Bokeh document title.

        Args:
            helao_srv: Server key used to look up this server's configuration.
            doc: The Bokeh ``Document`` to populate.
            helao_cfg: Optional config dict to use instead of the module-level
                ``config_loader.CONFIG`` (injection seam for tests/callers).
        """
        self.helao_srv = helao_srv
        self.helao_cfg = helao_cfg if helao_cfg is not None else config_loader.CONFIG
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
