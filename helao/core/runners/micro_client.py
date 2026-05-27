"""RPC-only micro orchestrator for in-process action dispatch.

:class:`MicroOrch` is a lightweight stand-in for the full ``Orch`` +
``OrchAPI`` pair.  It hosts an :class:`RPCDispatcher` (so action servers
can call ``update_status`` back to it) and a cache of :class:`RPCClient`
instances (for dispatching actions over ZMQ), but does NOT spin up a
FastAPI server, sequence/experiment queues, the operator UI, or any of
the other orchestrator scaffolding.

Typical use::

    orch = MicroOrch(
        server_key="micro",
        host="127.0.0.1",
        port=9999,
        world_cfg=world_cfg,
    )
    await orch.start()
    try:
        result = await orch.run_action(action)   # dispatch + await terminal state
    finally:
        await orch.stop()

The ``port`` argument is the HTTP-equivalent port that peers advertise
to each other; the dispatcher binds to ``derive_rpc_port(port)`` (i.e.
``port + RPC_PORT_OFFSET``), mirroring what :class:`HelaoFastAPI` does
so action servers can use the same ``derive_rpc_port`` rule when
sending status updates back.
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
    """An action is terminal once ``HloStatus.active`` is no longer in its status list."""
    if not action_status:
        return False
    return HloStatus.active not in action_status and "active" not in action_status


class MicroOrch:
    """Lightweight orchestrator that talks to action servers over RPC only.

    Carries one :class:`RPCDispatcher` (server side, to receive
    ``update_status`` callbacks) and lazily-created :class:`RPCClient`
    instances (one per target action server).  Tracks dispatched actions
    by UUID and resolves a per-action future when status updates report
    the action has left the ``active`` state.
    """

    def __init__(
        self,
        server_key: str,
        host: str,
        port: int,
        world_cfg: Optional[dict] = None,
        default_timeout: float = 5.0,
    ) -> None:
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
        await self.dispatcher.serve(self.host, derive_rpc_port(self.port))

    async def stop(self) -> None:
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
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.stop()

    # ------------------------------------------------------------------
    # client & subscription management
    # ------------------------------------------------------------------

    def _client_for(self, server_name: str) -> RPCClient:
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
        """Subscribe to *server_name*'s status updates via its ``attach_client`` endpoint."""
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
        """Dispatch *action* via RPC and return the action dict the server replied with.

        If the returned dump is still ``active``, call
        :meth:`wait_for_action` to await the terminal state.
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
        """Return the action's dump once it leaves the ``active`` state."""
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
        """Dispatch *action* and await its terminal dump in one call."""
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
        """Return the most recent dump observed for *action_uuid*, or ``None``."""
        return self._latest.get(action_uuid)

    def pending_uuids(self) -> List[UUID]:
        return list(self._pending.keys())
