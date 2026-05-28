"""RPC-only micro-orchestrator client for in-process action dispatch.

Provides :class:`MicroOrch`, a lightweight substitute for the full
orchestrator service. It hosts a single :class:`RPCDispatcher` to receive
``update_status`` callbacks from action servers and maintains a cache of
:class:`RPCClient` instances for outbound action dispatch over ZeroMQ. No
FastAPI server, sequence/experiment queues, or operator UI are started.

Example:
    orch = MicroOrch(server_key="micro", host="127.0.0.1", port=9999,
                     world_cfg=world_cfg)
    await orch.start()
    try:
        result = await orch.run_action(action)
    finally:
        await orch.stop()

The ``port`` argument is the HTTP-style port peers advertise; the
dispatcher itself binds to ``derive_rpc_port(port)`` so action servers
can resolve the callback endpoint with the same offset rule used by
:class:`HelaoFastAPI`.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
from uuid import UUID

import zmq

from helao.core.models.hlostatus import HloStatus
from helao.core.models.server import ActionServerModel
from helao.core.rpc import RPCClient, RPCDispatcher, RPCError, derive_rpc_port
from helao.helpers import helao_logging as logging
from helao.helpers.premodels import Action

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


def _is_terminal(action_status: Optional[List[Any]]) -> bool:
    """Return ``True`` once an action's status list no longer marks it active.

    Args:
        action_status: The ``action_status`` field from an action dump, as a
            list of status values or names.

    Returns:
        ``True`` if the list is non-empty and contains neither
        ``HloStatus.active`` nor the string ``"active"``.
    """
    if not action_status:
        return False
    return HloStatus.active not in action_status and "active" not in action_status


class MicroOrch:
    """Lightweight orchestrator that drives action servers over RPC only.

    Holds one :class:`RPCDispatcher` (to receive ``update_status``
    callbacks) and lazily creates one :class:`RPCClient` per target action
    server. Dispatched actions are tracked by UUID; a per-action future
    is resolved when an incoming status update shows the action has left
    the ``active`` state.

    Attributes:
        server_key: Logical name advertised to peers when subscribing.
        host: Hostname/IP advertised to peers.
        port: HTTP-style port advertised to peers; the dispatcher binds
            to ``derive_rpc_port(port)``.
        world_cfg: Mapping describing peer servers (must contain a
            ``servers`` key keyed by server name).
        default_timeout: Default RPC timeout in seconds.
        dispatcher: Server-side RPC dispatcher receiving status updates.
    """

    def __init__(
        self,
        server_key: str,
        host: str,
        port: int,
        world_cfg: Optional[dict] = None,
        default_timeout: float = 5.0,
    ) -> None:
        """Initialize the micro-orchestrator and register the status handler.

        Args:
            server_key: Logical key used when subscribing to action servers.
            host: Host the dispatcher will bind to.
            port: HTTP-style logical port; the actual bind port is
                ``derive_rpc_port(port)``.
            world_cfg: Optional world configuration providing peer server
                host/port information under the ``servers`` key.
            default_timeout: Default RPC timeout in seconds.
        """
        self.server_key = server_key
        self.host = host
        # Logical (HTTP-style) port advertised to peers.  Action servers
        # call ``derive_rpc_port(port)`` to reach the dispatcher.
        self.port = port
        self.world_cfg = world_cfg or {}
        self.default_timeout = default_timeout

        self.dispatcher = RPCDispatcher(server_key)
        self.dispatcher.register("update_status", self._on_update_status)

        self._clients: Dict[str, RPCClient] = {}
        self._pending: Dict[UUID, asyncio.Future] = {}
        self._latest: Dict[UUID, dict] = {}
        self._subscribed: set = set()
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Bind the RPC dispatcher on ``derive_rpc_port(self.port)``."""
        await self.dispatcher.serve(self.host, derive_rpc_port(self.port))

    async def stop(self) -> None:
        """Close the dispatcher and every cached RPC client.

        Errors raised while closing individual clients are logged and
        suppressed so all clients get a chance to close.
        """
        await self.dispatcher.close()
        clients = list(self._clients.values())
        self._clients.clear()
        self._subscribed.clear()
        for client in clients:
            try:
                await client.close()
            except Exception:
                LOGGER.exception("error closing MicroOrch RPCClient")

    async def __aenter__(self) -> "MicroOrch":
        """Enter the async context manager and call :meth:`start`."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        """Exit the async context manager and call :meth:`stop`."""
        await self.stop()

    # ------------------------------------------------------------------
    # client & subscription management
    # ------------------------------------------------------------------

    def _client_for(self, server_name: str) -> RPCClient:
        """Return a cached :class:`RPCClient` for ``server_name``, creating one if needed.

        Args:
            server_name: Key into ``world_cfg['servers']``.

        Returns:
            The cached or newly created RPC client.

        Raises:
            KeyError: If ``server_name`` is not present in ``world_cfg``.
        """
        client = self._clients.get(server_name)
        if client is not None:
            return client
        srv = self.world_cfg.get("servers", {}).get(server_name)
        if srv is None:
            raise KeyError(
                f"server {server_name!r} not in world_cfg['servers']"
            )
        client = RPCClient(
            endpoint=f"tcp://{srv['host']}:{derive_rpc_port(srv['port'])}",
            default_timeout=self.default_timeout,
        )
        self._clients[server_name] = client
        return client

    async def attach_to(self, server_name: str) -> bool:
        """Subscribe to ``server_name``'s status updates.

        Calls the remote ``attach_client`` endpoint, recording the
        subscription on success.

        Args:
            server_name: Target action server name.

        Returns:
            ``True`` if already subscribed or the subscription succeeded;
            ``False`` if the remote call failed.
        """
        if server_name in self._subscribed:
            return True
        client = self._client_for(server_name)
        try:
            await client.call(
                "attach_client",
                timeout=self.default_timeout,
                client_servkey=self.server_key,
                client_host=self.host,
                client_port=self.port,
            )
        except (RPCError, asyncio.TimeoutError, zmq.ZMQError, OSError):
            LOGGER.exception(f"attach_client to {server_name!r} failed")
            return False
        self._subscribed.add(server_name)
        return True

    async def detach_from(self, server_name: str) -> None:
        """Unsubscribe from ``server_name`` via its ``detach_client`` endpoint.

        The local subscription record is cleared whether or not the remote
        call succeeds.

        Args:
            server_name: Target action server name.
        """
        if server_name not in self._subscribed:
            return
        client = self._client_for(server_name)
        try:
            await client.call(
                "detach_client",
                timeout=self.default_timeout,
                client_servkey=self.server_key,
                client_host=self.host,
                client_port=self.port,
            )
        finally:
            self._subscribed.discard(server_name)

    # ------------------------------------------------------------------
    # update_status handler (registered on the dispatcher)
    # ------------------------------------------------------------------

    async def _on_update_status(
        self,
        actionservermodel: ActionServerModel,
        regular_task: str = "false",
    ) -> bool:
        """Handle an incoming ``update_status`` RPC from an action server.

        Refreshes the per-UUID cache with the latest action dumps and, for
        any UUID that has moved out of the active dict, resolves the
        corresponding pending future.

        Args:
            actionservermodel: Snapshot of the remote action server state.
            regular_task: Marker passed by the action server indicating
                whether the update came from a regular polling task.

        Returns:
            ``True`` once processing completes; ``False`` if no model was
            supplied.
        """
        if actionservermodel is None:
            return False
        async with self._lock:
            for endpoint in actionservermodel.endpoints.values():
                for uuid, act in endpoint.active_dict.items():
                    self._latest[uuid] = act.as_dict()
                for status_dict in endpoint.nonactive_dict.values():
                    for uuid, act in status_dict.items():
                        dump = act.as_dict()
                        self._latest[uuid] = dump
                        fut = self._pending.get(uuid)
                        if fut is not None and not fut.done():
                            fut.set_result(dump)
        return True

    # ------------------------------------------------------------------
    # dispatching
    # ------------------------------------------------------------------

    async def dispatch_action(
        self,
        action: Action,
        params: Optional[dict] = None,
        timeout: float = 60.0,
    ) -> dict:
        """Dispatch ``action`` over RPC and return the server's immediate reply.

        Initializes the action, subscribes to its server, records a pending
        future keyed by the action UUID, and invokes the RPC method
        ``"<server_name>/<action_name>"``. If the returned dump already
        reports a terminal status, the pending future is resolved before
        returning.

        Args:
            action: Pre-built :class:`Action` to dispatch. Must have
                ``action_server.server_name`` set.
            params: Extra keyword arguments forwarded to the RPC method.
            timeout: RPC call timeout in seconds.

        Returns:
            The dict returned by the action server's RPC handler. Callers
            should pass the result through :meth:`wait_for_action` when
            the action is still active.

        Raises:
            AssertionError: If the action lacks a server name or UUID
                after initialization.
            Exception: Any exception raised by the underlying RPC call is
                re-raised after cleaning up the pending future.
        """
        action.init_act()
        server_name = action.action_server.server_name
        action_uuid = action.action_uuid
        assert server_name is not None, "action.action_server.server_name must be set"
        assert action_uuid is not None, "init_act must have assigned action_uuid"

        await self.attach_to(server_name)

        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        async with self._lock:
            self._pending[action_uuid] = fut

        client = self._client_for(server_name)
        rpc_args: Dict[str, Any] = dict(params or {})
        rpc_args["action"] = action.as_dict()
        method = f"{server_name}/{action.action_name}"
        try:
            result = await client.call(method, timeout=timeout, **rpc_args)
        except Exception:
            async with self._lock:
                pending = self._pending.pop(action_uuid, None)
            if pending is not None and not pending.done():
                pending.cancel()
            raise

        if isinstance(result, dict):
            async with self._lock:
                self._latest[action_uuid] = result
                if _is_terminal(result.get("action_status")):
                    pending = self._pending.pop(action_uuid, None)
                    if pending is not None and not pending.done():
                        pending.set_result(result)
        return result

    async def wait_for_action(
        self,
        action_uuid: UUID,
        timeout: Optional[float] = None,
    ) -> dict:
        """Wait for an action to leave the ``active`` state and return its dump.

        Args:
            action_uuid: UUID assigned to the action when it was dispatched.
            timeout: Optional wait timeout in seconds.

        Returns:
            The most recent action dump observed after the action became
            terminal.

        Raises:
            asyncio.TimeoutError: If ``timeout`` expires before a terminal
                status is observed.
        """
        async with self._lock:
            cached = self._latest.get(action_uuid)
            if cached is not None and _is_terminal(cached.get("action_status")):
                self._pending.pop(action_uuid, None)
                return cached
            fut = self._pending.get(action_uuid)
            if fut is None:
                fut = asyncio.get_running_loop().create_future()
                self._pending[action_uuid] = fut
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            async with self._lock:
                self._pending.pop(action_uuid, None)

    async def run_action(
        self,
        action: Action,
        params: Optional[dict] = None,
        dispatch_timeout: float = 60.0,
        wait_timeout: Optional[float] = None,
    ) -> dict:
        """Dispatch ``action`` and wait for it to reach a terminal state.

        Combines :meth:`dispatch_action` and :meth:`wait_for_action`. If
        the dispatch reply is already terminal it is returned directly.

        Args:
            action: Action to run.
            params: Extra keyword arguments forwarded to the RPC method.
            dispatch_timeout: Timeout for the dispatch RPC call.
            wait_timeout: Optional timeout for the post-dispatch wait.

        Returns:
            The terminal action dump.
        """
        result = await self.dispatch_action(
            action, params=params, timeout=dispatch_timeout
        )
        action_status = (
            result.get("action_status") if isinstance(result, dict) else None
        )
        if _is_terminal(action_status):
            return result
        action_uuid = action.action_uuid
        assert action_uuid is not None
        return await self.wait_for_action(action_uuid, timeout=wait_timeout)

    # ------------------------------------------------------------------
    # introspection
    # ------------------------------------------------------------------

    def latest(self, action_uuid: UUID) -> Optional[dict]:
        """Return the most recent dump cached for ``action_uuid``.

        Args:
            action_uuid: UUID of the action to look up.

        Returns:
            The cached action dump, or ``None`` if nothing has been seen
            for this UUID yet.
        """
        return self._latest.get(action_uuid)

    def pending_uuids(self) -> List[UUID]:
        """Return the UUIDs of actions awaiting a terminal status update.

        Returns:
            A list of the UUIDs currently tracked with a pending future.
        """
        return list(self._pending.keys())
