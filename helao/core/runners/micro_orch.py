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
        result = await orch.run_action(action)              # one-shot
        results = await orch.run_experiment(my_exp_func,    # full experiment
                                            experiment=exp)
    finally:
        await orch.stop()

The ``port`` argument is the HTTP-style port peers advertise; the
dispatcher itself binds to ``derive_rpc_port(port)`` so action servers
can resolve the callback endpoint with the same offset rule used by
:class:`HelaoFastAPI`.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from uuid import UUID

import zmq

from helao.core.models.action_start_condition import ActionStartCondition
from helao.core.models.hlostatus import HloStatus
from helao.core.models.server import ActionServerModel
from helao.core.rpc import RPCClient, RPCDispatcher, RPCError, derive_rpc_port
from helao.helpers import helao_logging as logging
from helao.helpers.gen_uuid import gen_uuid
from helao.helpers.premodels import Action, Experiment

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


# (server_name, action_name, nonblocking) — what start-condition checks need.
_PendingMeta = Tuple[str, str, bool]


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
        # Mirrors _pending; populated/cleared in lockstep with it so
        # start-condition checks can introspect what's in flight.
        self._pending_meta: Dict[UUID, _PendingMeta] = {}
        self._latest: Dict[UUID, dict] = {}
        self._subscribed: set = set()
        # Single condition variable: anyone waiting on a start condition
        # gets a notify_all() whenever an action terminates.
        self._cond = asyncio.Condition()

        # Mirrors Orch.global_params: experiment functions can read these
        # in via ``from_global_act_params`` and write them out via
        # ``to_global_params`` on their actions.
        self.global_params: Dict[str, Any] = {}
        self.last_action_uuid: Optional[UUID] = None

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
            raise KeyError(f"server {server_name!r} not in world_cfg['servers']")
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
        async with self._cond:
            for endpoint in actionservermodel.endpoints.values():
                for uuid, act in endpoint.active_dict.items():
                    self._latest[uuid] = act.as_dict()
                for status_dict in endpoint.nonactive_dict.values():
                    for uuid, act in status_dict.items():
                        dump = act.as_dict()
                        self._latest[uuid] = dump
                        self._retire_locked(uuid, dump)
            self._cond.notify_all()
        return True

    def _retire_locked(self, action_uuid: UUID, dump: dict) -> None:
        """Mark an action as terminal: resolve its future and drop pending meta.

        Caller must already hold ``self._cond``'s lock.
        """
        self._pending_meta.pop(action_uuid, None)
        fut = self._pending.pop(action_uuid, None)
        if fut is not None and not fut.done():
            fut.set_result(dump)

    # ------------------------------------------------------------------
    # start-condition gating (mirrors Orch.loop_task_dispatch_action)
    # ------------------------------------------------------------------

    def _endpoint_busy_locked(self, server_name: str, action_name: str) -> bool:
        return any(
            s == server_name and a == action_name and not nb
            for s, a, nb in self._pending_meta.values()
        )

    def _server_busy_locked(self, server_name: str) -> bool:
        return any(
            s == server_name and not nb for s, _a, nb in self._pending_meta.values()
        )

    def _any_blocking_active_locked(self) -> bool:
        return any(not nb for _s, _a, nb in self._pending_meta.values())

    async def _wait_for_start_condition(self, action: Action) -> None:
        """Block until *action*'s ``start_condition`` is satisfied.

        Matches the per-condition logic in
        :meth:`Orch.loop_task_dispatch_action`.  ``wait_for_orch`` has no
        natural meaning here (MicroOrch hosts no action endpoints of its
        own), so we treat it as ``no_wait`` -- the orch's "wait" endpoint
        is by definition free when nothing is hosted on it.
        """
        cond = action.start_condition
        server_name = action.action_server.server_name
        action_name = action.action_name

        if cond == ActionStartCondition.no_wait:
            return
        if cond == ActionStartCondition.wait_for_orch:
            return
        if server_name is None or action_name is None:
            return

        async with self._cond:
            if cond == ActionStartCondition.wait_for_endpoint:
                await self._cond.wait_for(
                    lambda: not self._endpoint_busy_locked(server_name, action_name)
                )
            elif cond == ActionStartCondition.wait_for_server:
                await self._cond.wait_for(
                    lambda: not self._server_busy_locked(server_name)
                )
            elif cond == ActionStartCondition.wait_for_previous:
                last = self.last_action_uuid
                if last is None:
                    return
                await self._cond.wait_for(lambda: last not in self._pending_meta)
            else:
                # wait_for_all (3) is the documented default for unknown values
                await self._cond.wait_for(
                    lambda: not self._any_blocking_active_locked()
                )

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
        returning. Does not honour ``action.start_condition`` -- callers using
        :meth:`dispatch_action` directly are expected to handle their own
        sequencing.  Use :meth:`run_experiment` (or call
        :meth:`_wait_for_start_condition` yourself) to gate dispatches
        the way the full orchestrator does.

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
        action_name = action.action_name
        action_uuid = action.action_uuid
        assert server_name is not None, "action.action_server.server_name must be set"
        assert action_name is not None, "action.action_name must be set"
        assert action_uuid is not None, "init_act must have assigned action_uuid"

        await self.attach_to(server_name)

        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        async with self._cond:
            self._pending[action_uuid] = fut
            self._pending_meta[action_uuid] = (
                server_name,
                action_name,
                bool(action.nonblocking),
            )
            self.last_action_uuid = action_uuid

        client = self._client_for(server_name)
        rpc_args: Dict[str, Any] = dict(params or {})
        rpc_args["action"] = action.as_dict()
        method = f"{server_name}/{action_name}"
        try:
            result = await client.call(method, timeout=timeout, **rpc_args)
        except Exception:
            async with self._cond:
                self._pending_meta.pop(action_uuid, None)
                pending = self._pending.pop(action_uuid, None)
                if pending is not None and not pending.done():
                    pending.cancel()
                self._cond.notify_all()
            raise

        if isinstance(result, dict):
            async with self._cond:
                self._latest[action_uuid] = result
                if _is_terminal(result.get("action_status")):
                    self._retire_locked(action_uuid, result)
                    self._cond.notify_all()
        return result

    async def wait_for_action(
        self,
        action_uuid: UUID,
        timeout: Optional[float] = None,
    ) -> dict:
        """Return the action's dump once it leaves the ``active`` state.

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
        async with self._cond:
            cached = self._latest.get(action_uuid)
            if cached is not None and _is_terminal(cached.get("action_status")):
                return cached
            fut = self._pending.get(action_uuid)
            if fut is None:
                # Never dispatched (or already retired without a cached dump):
                # nothing to wait on.
                raise KeyError(f"no pending action with uuid {action_uuid}")
        return await asyncio.wait_for(fut, timeout=timeout)

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
    # experiment running
    # ------------------------------------------------------------------

    async def run_experiment(
        self,
        exp_func: Callable[..., Union[List[Action], Experiment]],
        experiment: Optional[Experiment] = None,
        await_completion: bool = True,
        dispatch_timeout: float = 60.0,
        wait_timeout: Optional[float] = None,
        **exp_params: Any,
    ) -> List[dict]:
        """Run a HELAO experiment function end-to-end.

        Replicates the action-unpacking + per-action dispatch logic from
        :meth:`Orch.loop_task_dispatch_experiment` /
        :meth:`Orch.loop_task_dispatch_action`, but without the
        sequence/experiment queues, the operator UI, or any persistence
        side-effects.

        *exp_func* may return either a ``list[Action]`` (as
        ``UVIS_sub_*`` functions in ``UVIS_exp.py`` do via
        ``apm.planned_actions``) or an ``Experiment`` (as ``TEST_sub_*``
        functions in ``TEST_exp.py`` do via ``apm.experiment``).  Each
        returned action is staged with a fresh UUID, the orchestrator
        identity (``self``), and its target server's host/port resolved
        from ``world_cfg``.  ``from_global_act_params`` is applied
        before dispatch, the start condition is enforced, and
        ``to_global_params`` is captured from each reply.

        Args:
            exp_func: The experiment function to invoke.
            experiment: The :class:`Experiment` passed as the function's
                first positional argument.  A blank ``Experiment()`` is
                used if ``None`` (matching ``ActionPlanMaker``'s
                fallback).
            await_completion: If ``True`` (default), wait for every
                dispatched action to reach a terminal state before
                returning; the returned list contains terminal dumps.
                If ``False``, return the immediate dispatch replies
                (some may still be ``active``).
            dispatch_timeout: Per-action RPC timeout.
            wait_timeout: Per-action terminal-state wait timeout.  Only
                consulted when ``await_completion`` is true.
            **exp_params: Keyword args forwarded to *exp_func*; only
                those whose names appear in the function's signature
                are passed through (mirrors the orchestrator's filtering
                by ``inspect.getfullargspec``).

        Returns:
            A list of action dumps, one per dispatched action, in order.
        """
        if experiment is None:
            experiment = Experiment()

        func_args = inspect.getfullargspec(exp_func).args
        supplied = {k: v for k, v in exp_params.items() if k in func_args}
        exp_return = exp_func(experiment, **supplied)

        if isinstance(exp_return, list):
            actions = exp_return
        elif isinstance(exp_return, Experiment):
            actions = exp_return.planned_actions
        else:
            raise TypeError(
                f"exp_func {exp_func.__name__!r} returned "
                f"{type(exp_return).__name__}; expected list[Action] or Experiment"
            )

        if not actions:
            return []

        for i, act in enumerate(actions):
            self._stage_action(act, order=i)

        results: List[dict] = []
        for act in actions:
            self._apply_from_global(act)
            await self._wait_for_start_condition(act)
            result = await self.dispatch_action(act, timeout=dispatch_timeout)
            results.append(result)
            self._capture_to_global(result, act.to_global_params)

        if not await_completion:
            return results

        terminal_results: List[dict] = []
        for act, immediate in zip(actions, results):
            status = (
                immediate.get("action_status") if isinstance(immediate, dict) else None
            )
            if _is_terminal(status) or act.nonblocking:
                terminal_results.append(immediate)
                continue
            action_uuid = act.action_uuid
            assert action_uuid is not None
            terminal_results.append(
                await self.wait_for_action(action_uuid, timeout=wait_timeout)
            )
        return terminal_results

    # ------------------------------------------------------------------
    # helpers shared by run_experiment
    # ------------------------------------------------------------------

    def _stage_action(self, act: Action, order: int) -> None:
        """Assign UUID, ordering, orch identity, and server address (from world_cfg)."""
        act.action_uuid = gen_uuid()
        act.action_order = int(order)
        act.orch_submit_order = int(order)
        act.orch_key = self.server_key
        act.orch_host = self.host
        act.orch_port = self.port
        srv = self.world_cfg.get("servers", {}).get(act.action_server.server_name)
        if srv is not None:
            act.action_server.hostname = srv["host"]
            act.action_server.port = srv["port"]

    def _apply_from_global(self, act: Action) -> None:
        """Copy ``self.global_params[k]`` into ``act.action_params[v]`` for each ``k: v``."""
        mapping = act.from_global_act_params or {}
        for k, v in mapping.items():
            if k not in self.global_params:
                continue
            val = self.global_params[k]
            if isinstance(v, list):
                for vv in v:
                    act.action_params[vv] = val
            else:
                act.action_params[v] = val

    def _capture_to_global(
        self, result: dict, to_global_params: Union[list, dict, None]
    ) -> None:
        """Pull keys named in ``to_global_params`` out of *result* into ``self.global_params``."""
        if not isinstance(result, dict) or not to_global_params:
            return
        action_params = result.get("action_params") or {}
        action_output = result.get("action_output") or {}
        if isinstance(to_global_params, list):
            for k in to_global_params:
                if k in action_params:
                    self.global_params[k] = action_params[k]
                elif k in action_output:
                    self.global_params[k] = action_output[k]
        elif isinstance(to_global_params, dict):
            for k1, k2 in to_global_params.items():
                if k1 in action_params:
                    self.global_params[k2] = action_params[k1]
                elif k1 in action_output:
                    self.global_params[k2] = action_output[k1]

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
