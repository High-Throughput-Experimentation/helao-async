"""Endpoint registration and queued-action dispatch (B1, 3b remainder).

Ports ``base_endpoints.EndpointManager`` and
``base_action_queue.ActionQueueDispatcher``. Both are collaborators over a
``base``; for the hexagon host, ``base`` *is* the host, so they take it directly.

This is what the queuing middleware was blocked on. The middleware's entire
branch condition is ``actionservermodel.endpoints[endpoint].active_dict`` — the
per-endpoint busy check — and its two parking spots are ``endpoint_queues`` and
``local_action_queue``, all of which are registered here.

**Two queues with confusable names, doing different jobs:**

* ``local_action_queue`` (here) holds *actions* that arrived while the server was
  busy and must be redispatched later. Populated by the middleware, drained by
  ``process_unified_queue``.
* ``local_action_task_queue`` (added with the executor runner) holds *action
  uuids* and serializes non-concurrent *executors* inside one action's loop.

Conflating them deadlocks or double-dispatches. They are unrelated mechanisms
that happen to be adjacent in ``Base``.

A queued action is redispatched with ``start_condition = no_wait`` and
``action_params["queued_launch"] = True``. Both matter: without ``no_wait`` the
redispatch would queue itself again behind the very action that just finished,
and ``queued_launch`` is what the middleware checks to let it through rather
than queueing it a second time.
"""

import asyncio

from fastapi.dependencies.utils import get_flat_params

from helao.core.models.action import ActionModel
from helao.core.models.action_start_condition import ActionStartCondition as ASC
from helao.core.models.server import EndpointModel
from helao.helpers import helao_logging as logging
from helao.helpers.dispatcher import async_action_dispatcher
from helao.helpers.zdeque import zdeque

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

__all__ = ["ActionQueueDispatcher", "EndpointManager"]


class EndpointManager:
    """Registers this server's action endpoints for status monitoring."""

    def __init__(self, host):
        """Hold only the host back-reference; endpoint state lives on the host."""
        self.host = host

    def dyn_endpoints_init(self) -> None:
        """Register endpoint status, invoking the ``dyn_endpoints`` callback first."""
        asyncio.gather(self.init_endpoint_status(self.host._dyn_endpoints))

    def endpoint_queues_init(self) -> None:
        """Create a per-endpoint action queue for every action route."""
        for urld in self.host.fast_urls:
            if urld.get("path", "").strip("/").startswith(self.host.server.server_name):
                endpoint_name = urld["path"].strip("/").split("/")[-1]
                self.host.endpoint_queues[endpoint_name] = zdeque([])

    async def init_endpoint_status(self, dyn_endpoints=None) -> None:
        """Register every action endpoint with the action-server status model.

        The ``active_dict`` on each registered ``EndpointModel`` is what the
        queuing middleware reads to decide whether an endpoint is busy, so an
        endpoint missing here is one the middleware will never queue for.

        Args:
            dyn_endpoints: Optional async callable invoked with the app, for
                late route registration.
        """
        if callable(dyn_endpoints):
            await dyn_endpoints(app=self.host)
        for route in self.host.routes:
            path = getattr(route, "path", "")
            if path.startswith(f"/{self.host.server.server_name}"):
                self.host.actionservermodel.endpoints.update(
                    {route.name: EndpointModel(endpoint_name=route.name)}
                )
                self.host.actionservermodel.endpoints[route.name].sort_status()
        LOGGER.info(
            f"Found {len(self.host.actionservermodel.endpoints.keys())} endpoints "
            f"for status monitoring on {self.host.server.server_name}."
        )
        self.host.fast_urls = self.get_endpoint_urls()
        self.endpoint_queues_init()

    def get_endpoint_urls(self) -> list:
        """Return a path/name/params descriptor for every route.

        Consumed by the orchestrator for request-schema generation, so the
        ``params`` shape is part of the wire contract rather than a convenience.
        """
        url_list = []
        for route in self.host.routes:
            routeD = {"path": getattr(route, "path", ""), "name": route.name}
            if "dependant" in dir(route):
                flatParams = get_flat_params(route.dependant)
                paramD = {
                    par.name: {
                        "outer_type": (
                            str(par.field_info.annotation).split("'")[1]
                            if len(str(par.field_info.annotation).split("'")) >= 2
                            else str(par.field_info.annotation)
                        ),
                    }
                    for par in flatParams
                }
                routeD["params"] = paramD
            else:
                routeD["params"] = []
            url_list.append(routeD)
        return url_list


class ActionQueueDispatcher:
    """Redispatches actions that arrived while the server was busy."""

    def __init__(self, host):
        """Hold only the host back-reference; queue state lives on the host."""
        self.host = host

    async def _dispatch_queued_action(self, action_queue, queue_label: str) -> None:
        """Pop one queued action, redispatch it, and requeue it on failure.

        The requeue is why this catches broadly: a dispatch that fails must not
        drop the action, or the caller waits forever on something no longer
        queued anywhere.
        """
        qact, qpars = None, {}
        try:
            qact, qpars = action_queue.popleft()
            LOGGER.info(f"{qact.action_name} was previously queued")
            LOGGER.info(f"running queued {qact.action_name}")
            qact.start_condition = ASC.no_wait
            qact.action_params["queued_launch"] = True
            await async_action_dispatcher(self.host.world_cfg, qact, qpars)
        except Exception:
            LOGGER.error(f"Failed to process {queue_label} queue", exc_info=True)
            if qact is not None:
                LOGGER.info(f"re-queueing {qact.action_name}")
                action_queue.appendleft((qact, qpars))

    async def process_unified_queue(self) -> None:
        """Dispatch the next queued action when concurrency is disallowed."""
        await self._dispatch_queued_action(
            self.host.local_action_queue, "local unified"
        )

    async def process_endpoint_queue(self, status_msg: ActionModel) -> None:
        """Dispatch the next queued action for the endpoint that just freed up."""
        await self._dispatch_queued_action(
            self.host.endpoint_queues[status_msg.action_name],
            f"endpoint '{status_msg.action_name}'",
        )
