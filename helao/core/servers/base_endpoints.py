"""Endpoint-registration collaborator extracted from ``Base`` (CARDS P6, Stage S4).

``Base``'s dynamic-endpoint / action-status-monitoring setup -- the
``dyn_endpoints`` bootstrap, the per-endpoint queue builder, the endpoint
status registration, and the route/url introspection used both internally
and by ``base_api``'s request-schema generation -- is moved here into an
``EndpointManager`` collaborator that ``Base`` delegates to. This follows the
``LiveBuffer`` (S1) / ``StatusBroadcaster`` (S2) / ``MetaFileWriter`` (S3)
pattern exactly.

Methods relocated (bodies byte-identical to the original inline ``Base``
methods, with ``self.`` rewritten to ``self.base.``):

- ``dyn_endpoints_init`` -- initialize endpoint status entries via the
  configured ``dyn_endpoints`` callback.
- ``endpoint_queues_init`` -- create a per-endpoint action queue for every
  action route on this server.
- ``init_endpoint_status`` -- register every action endpoint with the
  action-server status model.
- ``get_endpoint_urls`` -- return a list of route descriptors for every
  endpoint; used by ``base_api`` for request-schema generation.

State stays on ``Base`` (rule 3, same as the earlier collaborators):
``dyn_endpoints``, ``fast_urls``, and ``endpoint_queues`` remain attributes of
``Base``, constructed exactly where they are today in ``Base.__init__``.
``EndpointManager`` caches none of it -- it holds only the ``base``
back-reference and reads those attributes through it at call time.

Note: ``base_api.py`` calls ``self.base.dyn_endpoints_init()`` and relies on
``Base.get_endpoint_urls`` for request-schema generation -- both keep working
unchanged via the thin ``Base`` delegators; ``base_api.py`` itself is not
modified by this stage.
"""

from helao.helpers import helao_logging as logging

import asyncio

from fastapi.dependencies.utils import get_flat_params

from helao.core.models.server import EndpointModel
from helao.helpers.zdeque import zdeque

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class EndpointManager:
    """Endpoint-registration methods for a ``Base``.

    Holds only the ``base`` back-reference (never cached endpoint state), per
    the call-time state resolution rule -- see module docstring.
    """

    def __init__(self, base):
        self.base = base

    def dyn_endpoints_init(self):
        """Initialize endpoint status entries via the configured ``dyn_endpoints`` callback."""
        asyncio.gather(self.base.init_endpoint_status(self.base.dyn_endpoints))

    def endpoint_queues_init(self):
        """Create a per-endpoint action queue for every action route on this server."""
        for urld in self.base.fast_urls:
            if urld.get("path", "").strip("/").startswith(
                self.base.server.server_name
            ):
                endpoint_name = urld["path"].strip("/").split("/")[-1]
                self.base.endpoint_queues[endpoint_name] = zdeque([])

    # TODO: add app: FastAPI parameter for BaseAPI to pass app
    async def init_endpoint_status(self, dyn_endpoints=None):
        """Register every action endpoint with the action-server status model.

        Optionally invokes ``dyn_endpoints(app=self.app)`` first to allow late
        registration of routes.

        Args:
            dyn_endpoints: Optional async callable invoked with the FastAPI app.
        """
        if callable(dyn_endpoints):
            await dyn_endpoints(app=self.base.app)
        for route in self.base.app.routes:
            # print(route.path)
            if route.path.startswith(f"/{self.base.server.server_name}"):
                self.base.actionservermodel.endpoints.update(
                    {route.name: EndpointModel(endpoint_name=route.name)}
                )
                self.base.actionservermodel.endpoints[route.name].sort_status()
        LOGGER.info(
            f"Found {len(self.base.actionservermodel.endpoints.keys())} endpoints for status monitoring on {self.base.server.server_name}."
        )
        self.base.fast_urls = self.base.get_endpoint_urls()
        self.base.endpoint_queues_init()

    def get_endpoint_urls(self) -> list:
        """Return a list of route descriptors (path/name/params) for every endpoint."""
        url_list = []
        for route in self.base.app.routes:
            routeD = {"path": route.path, "name": route.name}
            if "dependant" in dir(route):
                flatParams = get_flat_params(route.dependant)
                paramD = {
                    par.name: {
                        "outer_type": (
                            str(par.field_info.annotation).split("'")[1]
                            if len(str(par.field_info.annotation).split("'")) >= 2
                            else str(par.field_info.annotation)
                        ),
                        # "type": (
                        #     str(par.type_).split("'")[1]
                        #     if len(str(par.type_).split("'")) >= 2
                        #     else str(par.type_)
                        # ),
                        # "required": par.required,
                        # "shape": par.shape,
                        # "default": par.default if par.default is not ... else None,
                    }
                    for par in flatParams
                }
                routeD["params"] = paramD
            else:
                routeD["params"] = []
            url_list.append(routeD)
        return url_list
