"""The async orchestration driver: drives the pure FSM through the ports.

This is the SP5 ``app/`` wiring for the orchestrator. The decision logic lives
in :mod:`helao.framework.domain.orchestration` (a pure reducer-style FSM that
returns ``(OrchState, [Command])``); this module owns the asyncio loop, the
awaits, and the realisation of every emitted command through the injected
transport / storage / eventsink / clock ports.

Two things live here that callers reuse:

* :func:`execute_commands` — the **shared** command-execution glue. Both the
  long-lived :class:`OrchDriver` here and the short-lived in-process
  :mod:`helao.framework.runners.micro_orch` call this exact function, so there is
  one place that knows how a :class:`DispatchAction` becomes a transport call, an
  :class:`ExpandSequence` becomes a library expansion, a :class:`PersistMeta`
  becomes a storage write, etc. No command logic is duplicated.
* :class:`OrchDriver` — holds the :class:`OrchState` + ports + library maps and
  exposes the async control surface (``start``/``stop``/``skip``/``estop``/
  ``clear``) plus :meth:`run_dispatch_loop`.

FastAPI is imported ONLY in this layer (and ``app/factory.py``). The single
``app/`` exception boundary wraps the loop body: an unexpected exception is
logged, the FSM is driven to ``estopped`` via ``apply_intent(estop)``, and the
resulting commands are executed (parent spec §6).
"""
from __future__ import annotations

import asyncio
import os
import pickle
import tempfile
import time
import uuid as _uuid
from datetime import datetime
from typing import Any, Callable, List, Mapping, Optional

import pyzstd

from helao.framework.models.errors import ErrorCodes
from helao.framework.models.hlostatus import HloStatus
from helao.framework.models.server import ActionServerModel, EndpointModel

from helao.framework.domain import expansion
from helao.framework.domain import orchestration as orch
from helao.framework.domain.orchestration import OrchState
from helao.framework.domain.run_models import RunAction, RunExperiment, RunSequence
from helao.framework.domain.commands import (
    BroadcastGlobalStatus,
    DispatchAction,
    EstopServers,
    ExpandExperiment,
    ExpandSequence,
    FinishExperiment,
    FinishSequence,
    MoveRunDir,
    OrchDecision,
    PersistMeta,
    StopExecutor,
)

from helao.framework.ports.clock import Clock
from helao.framework.ports.eventsink import EventSink, GLOBAL_STATUS_CHANNEL
from helao.framework.ports.storage import Storage
from helao.framework.ports.transport import DispatchTarget, Transport

from helao.framework.support import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

__all__ = ["OrchPorts", "execute_commands", "OrchDriver", "makeOrchApp", "WaitExec", "OwnStatusIngestor"]


class OrchPorts:
    """Bundle of the injected ports + config the command glue needs.

    Passing one object keeps :func:`execute_commands` and :class:`OrchDriver`
    in sync and lets the runner build the same bundle without an HTTP server.

    Attributes:
        transport: RPC/HTTP dispatch + probe port.
        storage: Meta/aux persistence port.
        eventsink: Status/data/global-status egress port.
        clock: Wall-clock source.
        sequence_lib: Map of sequence name -> factory (returns experiments).
        experiment_lib: Map of experiment name -> factory (returns actions).
        postprocessors: Names of HLO post-processors (passed through to storage).
        action_servers: Map of server_key -> {host, port, ...} for heartbeat pings
            (action-group servers only; subset of servers_map).
        servers_map: Full CONFIG ``servers`` map (all groups including orchestrator
            itself). Used by :func:`_dispatch_target_for` for config-driven target
            resolution including ORCH self-dispatch. Distinct from ``action_servers``
            which is the heartbeat-only subset. None/{} in unit tests / in-process
            runners.
        synthesize_completion: When True (default), a successful dispatch
            immediately calls ``_synthesize_finished_status`` so in-process /
            FakeTransport callers can advance without a real status subscriber.
            Set False when a real transport is wired (e.g. ``HttpTransport``) so
            the loop waits for genuine finished status from the action server's
            ``/ws_status`` feed (Part b).
    """

    def __init__(
        self,
        *,
        transport: Transport,
        storage: Storage,
        eventsink: EventSink,
        clock: Clock,
        sequence_lib: Optional[Mapping[str, Callable]] = None,
        experiment_lib: Optional[Mapping[str, Callable]] = None,
        postprocessors: Optional[List[str]] = None,
        action_servers: Optional[Mapping[str, dict]] = None,
        servers_map: Optional[Mapping[str, dict]] = None,
        synthesize_completion: bool = True,
    ) -> None:
        self.transport = transport
        self.storage = storage
        self.eventsink = eventsink
        self.clock = clock
        self.sequence_lib: Mapping[str, Callable] = dict(sequence_lib or {})
        self.experiment_lib: Mapping[str, Callable] = dict(experiment_lib or {})
        self.postprocessors: List[str] = list(postprocessors or [])
        self.action_servers: dict = dict(action_servers or {})
        self.servers_map: dict = dict(servers_map or {})
        self.synthesize_completion: bool = synthesize_completion

    def now(self) -> datetime:
        """Wall-clock ``datetime`` from the injected clock port."""
        now_dt = getattr(self.clock, "now_datetime", None)
        if callable(now_dt):
            return now_dt()
        return datetime.fromtimestamp(self.clock.now_ns() / 1e9)


# --------------------------------------------------------------------------- #
# the shared command-execution glue (reused by OrchDriver AND micro_orch)
# --------------------------------------------------------------------------- #


def _dispatch_target_for(
    action: RunAction,
    endpoint: str = "run_action",
    *,
    servers_map: Optional[Mapping[str, dict]] = None,
) -> DispatchTarget:
    """Build a :class:`DispatchTarget` from an action's action-server identity.

    Resolution order (a1 — config-driven target resolution):
    1. ``servers_map[server_key]`` — full CONFIG ``servers`` map entry (covers
       both action servers AND the orchestrator's own entry for self-dispatch).
    2. The action's :class:`MachineModel` ``hostname``/``host``/``port`` fields.
    3. Defaults: ``127.0.0.1``:8000.

    The dispatch endpoint is always ``action.action_name`` (e.g. ``"run_for"``,
    ``"wait"``), falling back to the ``endpoint`` arg only when ``action_name``
    is unset.  HELAO action servers and orchestrators both register routes at
    ``/{server_key}/{action_name}``, matching legacy ``orch.py`` convention.

    ``servers_map`` is the complete ``CONFIG["servers"]`` dict injected via
    :class:`OrchPorts`; it is ``None``/empty in unit-tests and in-process runners
    (falls through to the MachineModel path).
    """
    server = action.action_server
    server_key = getattr(server, "server_name", None) or "action"

    # The dispatch endpoint is the action's own ``action_name`` — HELAO action
    # servers (and the orchestrator's own built-ins) register routes at
    # ``/{server_key}/{action_name}`` (e.g. ``/SIM/acquire_data``, ``/ORCH/wait``),
    # matching legacy ``orch.py`` (``endpoint_name=A.action_name``). The
    # ``endpoint`` arg is only a fallback for actions with no ``action_name``.
    resolved_endpoint = getattr(action, "action_name", None) or endpoint
    if not getattr(action, "action_name", None):
        LOGGER.debug(
            "_dispatch_target_for: action for %r has no action_name; "
            "falling back to endpoint %r",
            server_key, endpoint,
        )

    # Priority 1: config servers map
    if servers_map:
        cfg_entry = servers_map.get(server_key)
        if cfg_entry and isinstance(cfg_entry, dict):
            host = cfg_entry.get("host") or cfg_entry.get("hostname") or "127.0.0.1"
            port = cfg_entry.get("port") or 8000
            return DispatchTarget(
                server_key=server_key, host=host, port=int(port), endpoint=resolved_endpoint
            )

    # Priority 2: MachineModel fields
    host = getattr(server, "hostname", None) or getattr(server, "host", None) or "127.0.0.1"
    port = getattr(server, "port", None) or 8000
    return DispatchTarget(
        server_key=server_key, host=host, port=int(port), endpoint=resolved_endpoint
    )


def _synthesize_finished_status(action: RunAction) -> ActionServerModel:
    """Build the status update an action server would send once ``action`` finished.

    In-process drivers (and tests with a synchronous fake transport) have no
    real status WebSocket, so after a successful dispatch we fold the action's
    completion back into the global model exactly as a remote ``finished``
    status push would, freeing the server/endpoint so the loop can advance to
    finish the experiment/sequence.
    """
    finished = action.model_copy(deep=True)
    if HloStatus.active in finished.action_status:
        finished.action_status.remove(HloStatus.active)
    if HloStatus.finished not in finished.action_status:
        finished.action_status.append(HloStatus.finished)
    ep_name = finished.action_name or "run_action"
    endpoint = EndpointModel(
        endpoint_name=ep_name,
        active_dict={},
        nonactive_dict={HloStatus.finished: {finished.action_uuid: finished}},
    )
    return ActionServerModel(
        action_server=finished.action_server, endpoints={ep_name: endpoint}
    )


async def execute_commands(
    state: OrchState, commands: List[Any], *, ports: OrchPorts
) -> List[Any]:
    """Realise each emitted command through the injected ports. **Shared glue.**

    Returns the list of *follow-up* commands produced while realising the input
    commands (e.g. an ``on_dispatch_result`` that requested a stop), so the
    caller's loop can drain them. The state is mutated in place.

    Command -> port mapping (parent spec §6):

    * :class:`BroadcastGlobalStatus` -> ``eventsink.emit_global_status``.
    * :class:`PersistMeta` -> ``storage.write_meta`` (``-{kind}.yml`` relpath).
    * :class:`DispatchAction` -> ``transport.dispatch`` then
      ``orchestration.on_dispatch_result``; on success the action's finished
      status is folded back via ``orchestration.on_status_update``.
    * :class:`EstopServers` / :class:`StopExecutor` -> ``transport.dispatch``.
    * :class:`FinishExperiment` / :class:`FinishSequence` -> ``storage.write_meta``.
    * :class:`MoveRunDir` -> ``storage.relocate``.
    * :class:`ExpandSequence` / :class:`ExpandExperiment` are normally handled by
      the loop *before* calling the dispatch step (the loop pre-expands), so they
      are realised here only as a fallback (library expansion + storage write).
    """
    followups: List[Any] = []
    for cmd in commands:
        if isinstance(cmd, BroadcastGlobalStatus):
            await ports.eventsink.emit_global_status(dict(cmd.payload))

        elif isinstance(cmd, PersistMeta):
            relpath = f"{cmd.uuid}-{cmd.kind}.yml"
            await ports.storage.write_meta(relpath, dict(cmd.payload))

        elif isinstance(cmd, DispatchAction):
            action = cmd.action
            target = _dispatch_target_for(action, servers_map=ports.servers_map)
            result = await ports.transport.dispatch(target, {**(action.action_params or {}), "action": action.as_dict()})
            result_action = action if result.error == ErrorCodes.none else None
            _st, fb = orch.on_dispatch_result(state, result_action, result.error)
            followups.extend(fb)
            if result.error == ErrorCodes.none and not cmd.nonblocking:
                # Synthesize completion only when the flag says so (default: True).
                # With a real transport (HttpTransport), synthesize_completion is
                # False and the loop waits for the real finished status pushed by
                # the action server's /ws_status subscriber (Part b).
                if ports.synthesize_completion:
                    _st2, status_cmds = orch.on_status_update(
                        state, _synthesize_finished_status(action)
                    )
                    followups.extend(status_cmds)

        elif isinstance(cmd, EstopServers):
            # fan estop out to every known action server
            for key, asm in list(state.globalstatusmodel.server_dict.items()):
                server = asm.action_server
                target = DispatchTarget(
                    server_key=getattr(server, "server_name", key),
                    host=getattr(server, "hostname", None)
                    or getattr(server, "host", None)
                    or "127.0.0.1",
                    port=int(getattr(server, "port", None) or 8000),
                    endpoint="estop",
                )
                await ports.transport.dispatch(target, {"switch": cmd.switch})

        elif isinstance(cmd, StopExecutor):
            target = DispatchTarget(
                server_key=cmd.server_key,
                host=cmd.host or "127.0.0.1",
                port=int(cmd.port or 8000),
                endpoint="stop_executor",
                private=True,  # /stop_executor is at root, not /{server_key}/stop_executor
            )
            await ports.transport.dispatch(target, {"executor_id": cmd.executor_id})

        elif isinstance(cmd, FinishExperiment):
            await ports.storage.write_meta(
                f"{cmd.experiment_uuid}-exp.yml", _finish_exp_payload(state)
            )

        elif isinstance(cmd, FinishSequence):
            await ports.storage.write_meta(
                f"{cmd.sequence_uuid}-seq.yml", _finish_seq_payload(state)
            )

        elif isinstance(cmd, MoveRunDir):
            await ports.storage.relocate(cmd.src, cmd.dst)

        elif isinstance(cmd, ExpandSequence):
            # fallback expansion (the loop normally pre-expands before dispatch)
            experiments = expansion.unpack_sequence(
                cmd.sequence_name, dict(cmd.sequence_params),
                sequence_lib=ports.sequence_lib,
            )
            if state.active_sequence is not None and not state.active_sequence.planned_experiments:
                state.active_sequence.planned_experiments = list(experiments)

        elif isinstance(cmd, ExpandExperiment):
            actions = expansion.unpack_experiment(
                state.active_experiment, dict(cmd.experiment_params),
                experiment_lib=ports.experiment_lib,
            ) if state.active_experiment is not None else []
            _stage_actions(state, actions)

        else:
            LOGGER.info(f"execute_commands: unhandled command {cmd!r}")

    return followups


def _finish_exp_payload(state: OrchState) -> dict:
    """Best-effort meta payload for a :class:`FinishExperiment` write."""
    exp = state.active_experiment or state.last_experiment
    return exp.as_dict() if exp is not None else {}


def _finish_seq_payload(state: OrchState) -> dict:
    """Best-effort meta payload for a :class:`FinishSequence` write."""
    seq = state.active_sequence or state.last_sequence
    return seq.as_dict() if seq is not None else {}


def _stage_actions(state: OrchState, actions: List[RunAction]) -> None:
    """Append expanded actions onto ``action_dq`` with order/uuid stamping.

    Mirrors the staging the FSM performs when ``dispatch_experiment`` is given an
    ``expand_result``; used by the :class:`ExpandExperiment` fallback path.
    """
    seed = _uuid.uuid4()
    for i, act in enumerate(actions):
        act.action_order = i
        act.orch_submit_order = i
        if act.action_uuid is None:
            act.action_uuid = _uuid.UUID(int=(seed.int + 1 + i) % (1 << 128))
        if state.active_experiment is not None:
            act.experiment_uuid = state.active_experiment.experiment_uuid
        state.action_dq.append(act)


def _as_run_experiment(exp: Any) -> RunExperiment:
    """Coerce a planned :class:`ExperimentModel` into a :class:`RunExperiment`.

    Stamps ``experiment_uuid`` if unset so a sequence's staged experiments carry a
    uuid while queued (the operator's experiment-queue table shows it). Mirrors
    ``_as_run_sequence`` / ``_as_run_experiment_dict``; dispatch reuses the uuid.
    """
    run_exp = exp if isinstance(exp, RunExperiment) else RunExperiment(**exp.model_dump())
    if run_exp.experiment_uuid is None:
        run_exp.experiment_uuid = _uuid.uuid4()
    return run_exp


def _extract_nonblocking(body: dict) -> bool:
    """Read the ``nonblocking`` flag from a /wait request body.

    The orch dispatch payload is ``{**action_params, "action": action.as_dict()}``
    so the flag sits under ``body["action"]["nonblocking"]``; direct/test calls may
    pass it top-level. Returns ``False`` when absent. Lives at module scope so the
    propagation can be unit-tested without standing up the FastAPI app.
    """
    return bool(
        body.get("nonblocking")
        or (body.get("action") or {}).get("nonblocking")
    )


def _as_run_sequence(d: dict) -> RunSequence:
    """Build a RunSequence from a posted dict (filter to model fields).

    Stamps ``sequence_uuid`` at enqueue (legacy ``Orch._prep_sequence_meta``,
    orch.py:1685) so queued items show a uuid in the operator immediately —
    timestamp/output_dir stay deferred to ``dispatch_sequence``, matching legacy.
    """
    seq = RunSequence(**{k: v for k, v in d.items() if k in RunSequence.model_fields})
    if seq.sequence_uuid is None:
        seq.sequence_uuid = _uuid.uuid4()
    return seq


# --------------------------------------------------------------------------- #
# the async driver
# --------------------------------------------------------------------------- #


class OrchDriver:
    """Async orchestrator driver: holds :class:`OrchState`, drives it via ports.

    The control wrappers (:meth:`start` / :meth:`stop` / :meth:`skip` /
    :meth:`estop` / :meth:`clear`) call :func:`orchestration.apply_intent` and
    execute the returned commands. :meth:`run_dispatch_loop` runs the FSM to a
    natural stop/idle, pre-expanding sequences/experiments through the library
    maps before each dispatch step.

    Attributes:
        server_key: Orchestrator identifier.
        state: The live :class:`OrchState`.
        ports: The injected :class:`OrchPorts` bundle.
    """

    def __init__(
        self,
        server_key: str,
        *,
        ports: OrchPorts,
        state: Optional[OrchState] = None,
    ) -> None:
        self.server_key = server_key
        self.ports = ports
        self.state = state if state is not None else OrchState()
        self.action_servers = dict(getattr(ports, "action_servers", {}) or {})
        self.heartbeat_interval = 5.0
        self._heartbeat_task = None
        # --- SP-ORCH-5c: single Event-driven dispatch loop ---------------------
        # Exactly ONE long-lived dispatch-loop task ever drains the queues. It is
        # parked on ``self._wake`` whenever it reaches a WAIT / no-progress point
        # and resumed by ``on_status_update`` / ``start`` calling ``self._wake.set()``.
        # ``_loop_task`` is the single drainer; it is (re)created lazily by
        # ``_ensure_loop_task`` so concurrent pops are impossible (no second loop).
        self._wake: asyncio.Event = asyncio.Event()
        self._loop_task: Optional[asyncio.Task] = None
        #: optional backref to the co-located FrameworkBase (set by makeOrchApp).
        #: Used to stop the orch's OWN nonblocking executors in-process at
        #: experiment finish — a StopExecutor RPC to the orch's own /stop_executor
        #: would deadlock this single dispatch loop.
        self.base = None

    # --- command execution + draining --------------------------------------

    async def _stop_nonblocking_executors(self, nb_cmds: List[Any]) -> None:
        """Stop tracked nonblocking executors at experiment finish.

        Executors hosted on THIS orchestrator's co-located base are stopped
        IN-PROCESS (dispatching StopExecutor to the orch's own /stop_executor over
        RPC deadlocks the single dispatch loop — the loop would await a response it
        must itself produce). Genuinely remote executors are dispatched over the
        transport, exactly as before.
        """
        local_execs = getattr(self.base, "executors", {}) or {}
        remote: List[Any] = []
        for cmd in nb_cmds:
            executor = local_execs.get(getattr(cmd, "executor_id", None))
            if executor is not None:
                stop_fn = getattr(executor, "stop_action_task", None)
                if callable(stop_fn):
                    stop_fn()
            else:
                remote.append(cmd)
        if remote:
            await self._execute(remote)

    async def _execute(self, commands: List[Any]) -> None:
        """Execute ``commands`` and drain any follow-ups they produce."""
        pending = list(commands)
        # bound the drain so a pathological command->command cycle can't spin
        for _ in range(1000):
            if not pending:
                return
            pending = await execute_commands(self.state, pending, ports=self.ports)
        LOGGER.info("_execute: follow-up command drain exceeded bound, stopping")

    # --- control surface ----------------------------------------------------

    async def _intent(self, intent: str, *, reason: str = "") -> None:
        _st, cmds = orch.apply_intent(self.state, intent, reason=reason)
        await self._execute(cmds)

    async def start(self) -> None:
        """Move the loop to ``started`` (if there is work) and run the single loop.

        SP-ORCH-5c: there is exactly ONE dispatch-loop task. ``start`` applies the
        ``start`` intent, then either

        * runs the loop **inline to completion** when the in-process synthesize
          path is active (``ports.synthesize_completion`` — micro_orch / unit
          tests / FakeTransport callers): every successful dispatch immediately
          folds finished status so the loop never parks at WAIT and drains to a
          terminal IDLE in one pass; ``await start()`` therefore returns once the
          queues are drained, preserving the legacy synchronous-drain contract; or
        * ensures the single long-lived background loop task is running and sets
          the wake event (real transport / production): the HTTP ``/start`` handler
          returns immediately while the loop parks on ``self._wake`` at WAIT and is
          resumed by ``on_status_update``.
        """
        await self._intent("start")
        if getattr(self.ports, "synthesize_completion", True):
            # In-process: drain inline so ``await start()`` blocks until done.
            self._wake.set()
            await self.run_dispatch_loop()
            return
        # Production: a single background drainer; start() returns immediately.
        self._wake.set()
        self._ensure_loop_task()

    def _ensure_loop_task(self) -> None:
        """Create the single background dispatch-loop task if not already alive.

        Only ONE ``run_dispatch_loop`` task ever exists, so concurrent pops of the
        same queue are impossible. A done-callback escalates any unexpected loop
        exception to estop (IMPORTANT-6) instead of letting the task die silently.
        """
        task = self._loop_task
        if task is not None and not task.done():
            return
        self._loop_task = asyncio.create_task(
            self.run_dispatch_loop(), name=f"orch_dispatch_loop_{self.server_key}"
        )
        self._loop_task.add_done_callback(self._on_loop_task_done)

    def _on_loop_task_done(self, task: "asyncio.Task") -> None:
        """Done-callback: surface a crashed loop task and escalate to estop.

        A clean exit (terminal IDLE) or a cancellation at shutdown is expected and
        ignored; any other exception is logged ERROR and the FSM is driven to
        estopped so the failure is operator-visible rather than a swallowed
        "Task exception never retrieved" (IMPORTANT-6).
        """
        if task.cancelled():
            return
        exc = task.exception()
        if exc is None:
            return
        LOGGER.error(f"dispatch loop task crashed: {exc!r}; escalating to estop")
        try:
            _st, cmds = orch.apply_intent(
                self.state, "estop", reason=f"dispatch loop task crashed: {exc}"
            )
            # schedule the estop command execution on the running loop
            asyncio.ensure_future(self._execute(cmds))
        except Exception as inner:  # pragma: no cover - defensive
            LOGGER.error(f"failed to escalate crashed loop task to estop: {inner!r}")

    async def shutdown(self) -> None:
        """Cancel the single dispatch-loop task cleanly (idempotent)."""
        task = self._loop_task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:  # pragma: no cover - defensive
                pass
        self._loop_task = None

    async def stop(self) -> None:
        """Request a graceful stop of the dispatch loop."""
        await self._intent("stop")

    async def skip(self) -> None:
        """Skip the remaining actions of the current experiment."""
        await self._intent("skip")

    async def estop(self, reason: str = "") -> None:
        """Emergency-stop the loop and fan estop out to every action server."""
        await self._intent("estop", reason=reason)

    async def clear_estop(self) -> None:
        """Release a latched estop and return the loop to ``stopped``."""
        await self._intent("clear_estop")

    async def clear_error(self) -> None:
        """Clear errored finished-action uuids."""
        await self._intent("clear_error")

    async def clear(self, which: str) -> None:
        """Clear one of ``sequences``/``experiments``/``actions`` queues."""
        await self._intent(f"clear_{which}")

    async def on_status_update(self, asm: Optional[ActionServerModel]) -> None:
        """Fold a remote action-server status into state and execute reactions.

        SP-ORCH-5c: this NEVER spawns a dispatch loop. After folding status and
        executing its reactions it simply wakes the single long-lived dispatch
        loop task (``self._wake.set()``) so the (one) drainer re-evaluates
        ``decide_next`` and advances past a WAIT it was parked on. Because the
        loop clears the event BEFORE parking, a set that lands mid-step is
        remembered and consumed when it next parks — no lost wakeup, and exactly
        one task ever pops the queues.

        If the loop task is not currently alive (e.g. it exited at a terminal
        IDLE and new work folded in via this status), it is (re)created so the
        wake is not lost.
        """
        _st, cmds = orch.on_status_update(self.state, asm)
        await self._execute(cmds)
        self._wake.set()
        # In production (background loop) a status arriving after the loop exited
        # at IDLE must respawn the single drainer so the wake is honoured. The
        # in-process synthesize path drives the loop inline from start(), so it is
        # never resurrected here.
        if not getattr(self.ports, "synthesize_completion", True):
            from helao.framework.models.orchstatus import LoopStatus

            if self.state.loop_state == LoopStatus.started:
                self._ensure_loop_task()

    async def on_nonblocking(self, actionmodel, host: str, port: int) -> None:
        """Record a nonblocking action transition and wake the dispatch loop.

        Fed by the ``/update_nonblocking`` endpoint when an action server reports
        a nonblocking action's active/finished transition. Delegates to domain
        :func:`orchestration.on_nonblocking` (tracks the executor in
        ``state.nonblocking``, registers it in ``action_history`` — never touches
        ``active_dict``), executes the resulting broadcast, and wakes the single
        drainer so an experiment parked waiting on nonblocking teardown advances.
        Mirrors :meth:`on_status_update`'s loop-resurrection guard.
        """
        _st, cmds = orch.on_nonblocking(self.state, actionmodel, host, port)
        await self._execute(cmds)
        self._wake.set()
        if not getattr(self.ports, "synthesize_completion", True):
            from helao.framework.models.orchstatus import LoopStatus

            if self.state.loop_state == LoopStatus.started:
                self._ensure_loop_task()

    # --- heartbeat -----------------------------------------------------------

    async def _heartbeat_once(self) -> None:
        """One ping pass: dispatch get_status to each pingable server, fold into status_summary."""
        for server_key, host, port in orch.pingable_servers(self.action_servers):
            target = DispatchTarget(
                server_key=server_key,
                host=host,
                port=port,
                endpoint="get_status",
                private=True,  # /get_status is at root, not /{server_key}/get_status
            )
            result = await self.ports.transport.dispatch(
                target, {"client_servkey": self.server_key}
            )
            self.state.status_summary[server_key] = orch.parse_status_response(
                result.response, result.error == ErrorCodes.none
            )

    async def _heartbeat_loop(self) -> None:
        """Refresh status_summary every heartbeat_interval until cancelled."""
        while True:
            try:
                await self._heartbeat_once()
            except Exception as exc:  # a transient ping failure must not kill the loop
                LOGGER.warning(f"heartbeat pass failed: {exc!r}")
            await asyncio.sleep(self.heartbeat_interval)

    def start_heartbeat(self) -> None:
        """Start the background heartbeat task (no-op if no servers / already running)."""
        if not self.action_servers:
            return
        if self._heartbeat_task is not None and not self._heartbeat_task.done():
            return
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    def stop_heartbeat(self) -> None:
        """Cancel the heartbeat task if running (idempotent)."""
        task = self._heartbeat_task
        if task is not None and not task.done():
            task.cancel()
        self._heartbeat_task = None

    # --- enqueue -------------------------------------------------------------

    def enqueue_sequence(self, sequence) -> None:
        """Append a :class:`RunSequence` to the sequence queue."""
        self.state.sequence_dq.append(sequence)

    def enqueue_experiment(self, experiment) -> None:
        """Append a :class:`RunExperiment` to the experiment queue."""
        self.state.experiment_dq.append(experiment)

    # --- the loop ------------------------------------------------------------

    async def run_dispatch_loop(self, *, max_steps: int = 10_000) -> None:
        """The SINGLE long-lived dispatch drainer driven by ``self._wake``.

        Each iteration consults :func:`orchestration.decide_next` and, for the
        seq/exp dispatch decisions, pre-expands through the library maps so the
        pure dispatch step receives its ``expand_result``.

        SP-ORCH-5c parking semantics (kills the spawn-on-status races): instead of
        ``break``-ing at a WAIT / no-progress point, the loop **parks on the wake
        event** — ``self._wake.clear(); await self._wake.wait()`` — and then
        continues. The event is cleared BEFORE awaiting so a ``set`` that lands
        mid-step is remembered and consumed at the next park (no lost wakeup).
        ``on_status_update`` / ``start`` set the event; because there is only ever
        one loop task, concurrent pops are impossible.

        The loop EXITS the task only on a genuine terminal:

        * STOP (stop/estop intent or estopped state), or
        * IDLE with all queues empty and no active experiment/sequence (a clean
          drain; a later enqueue + ``start`` / wake recreates the task), or
        * cancellation at shutdown.

        The single ``app/`` exception boundary wraps the step body: an unexpected
        exception logs, drives the FSM to ``estopped``, executes the estop
        commands, and exits.
        """
        from helao.framework.models.orchstatus import LoopStatus

        steps = 0
        while steps < max_steps:
            steps += 1
            if self.state.loop_state != LoopStatus.started:
                break  # STOP/estopped/stopped — terminal, exit the task
            decision = orch.decide_next(self.state)
            if decision in (OrchDecision.STOP, OrchDecision.IDLE):
                # Natural completion: when every queue is drained (IDLE), transition
                # loop_state started -> stopped and broadcast, so subscribers (the
                # operator) stop showing the orchestrator as "running" after a
                # sequence finishes. (STOP already carries a terminal loop_state.)
                if decision == OrchDecision.IDLE:
                    _st, cmds = orch.complete_idle(self.state)
                    if cmds:
                        await self._execute(cmds)
                        LOGGER.info(
                            "dispatch loop drained: loop_state -> %s (broadcast)",
                            self.state.loop_state,
                        )
                break  # terminal: nothing left to drain
            if decision == OrchDecision.WAIT:
                # Park: clear BEFORE awaiting so a concurrent set is not lost.
                self._wake.clear()
                # Re-check after clearing in case decide_next changed between the
                # clear and the await (a set that already happened is consumed).
                if orch.decide_next(self.state) == OrchDecision.WAIT:
                    await self._wake.wait()
                continue
            try:
                progressed = await self._step(decision)
            except Exception as exc:  # the single app/ exception boundary
                LOGGER.error(f"dispatch loop crashed: {exc!r}; estopping")
                _st, cmds = orch.apply_intent(
                    self.state, "estop", reason=f"loop exception: {exc}"
                )
                await self._execute(cmds)
                break
            if not progressed:
                # No in-process progress (e.g. a start-condition re-queue): park
                # on the wake event rather than spin or exit, so an external
                # status update can advance us. Clear before awaiting (no lost
                # wakeup). The in-process synthesize path never reaches here
                # because each dispatch folds finished status immediately.
                self._wake.clear()
                if not orch.decide_next(self.state) in (
                    OrchDecision.STOP,
                    OrchDecision.IDLE,
                ):
                    await self._wake.wait()

    async def _step(self, decision: OrchDecision) -> bool:
        """Execute one dispatch decision. Returns True if the loop progressed."""
        now = self.ports.now()
        uuid = _uuid.uuid4()

        if decision == OrchDecision.DISPATCH_SEQUENCE:
            seq = self.state.sequence_dq[0]
            experiments = expansion.unpack_sequence(
                seq.sequence_name, dict(seq.sequence_params),
                sequence_lib=self.ports.sequence_lib,
            )
            _st, cmds = orch.dispatch_sequence(
                self.state, now=now, uuid=uuid, expand_result=experiments
            )
            await self._execute(cmds)
            # stage the planned experiments onto the experiment queue
            for planned in self.state.active_sequence.planned_experiments:
                self.state.experiment_dq.append(_as_run_experiment(planned))
            return True

        if decision == OrchDecision.DISPATCH_EXPERIMENT:
            exp = self.state.experiment_dq[0]
            actions = expansion.unpack_experiment(
                exp, dict(exp.experiment_params),
                experiment_lib=self.ports.experiment_lib,
            )
            _st, cmds = orch.dispatch_experiment(
                self.state, now=now, uuid=uuid, expand_result=actions
            )
            await self._execute(cmds)
            return True

        if decision == OrchDecision.DISPATCH_ACTION:
            before = len(self.state.action_dq)
            _st, cmds = orch.dispatch_action(self.state, now=now, uuid=uuid)
            await self._execute(cmds)
            # progressed unless a start condition re-queued the same action with
            # no command emitted (would otherwise spin forever in-process)
            return bool(cmds) or len(self.state.action_dq) != before

        if decision == OrchDecision.FINISH_EXPERIMENT:
            exp = self.state.active_experiment
            # Stop any nonblocking action executors still running for this
            # experiment before finishing it (ports finish_active_experiment's
            # clear_nonblocking loop, orch.py:2110). Blocking actions are already
            # idle (FINISH_EXPERIMENT only fires when actions_idle).
            _st, nb_cmds = orch.clear_nonblocking(self.state)
            if nb_cmds:
                await self._stop_nonblocking_executors(nb_cmds)
                # Best-effort teardown: legacy finish_active_experiment LOOPED
                # clear_nonblocking with sleeps until the list drained (waiting for
                # each executor's finish report). The single-pass FSM instead fires
                # stop_executor once and drops the tracking entries now, so a lost /
                # never-arriving finish report cannot (a) hang the orch nor (b) leave
                # a stale tuple that gets re-stopped at every later experiment finish.
                # A finish report that does still arrive is a harmless no-op (the
                # entry is gone) and its action_history update is unaffected.
                self.state.nonblocking.clear()
            await self._execute([FinishExperiment(experiment_uuid=exp.experiment_uuid)])
            # Mark the experiment finished in state + history so the operator stops
            # showing it as "active" (ports finish_active_experiment, orch.py:2176).
            orch.complete_experiment(self.state, now)
            self.state.last_experiment = exp
            self.state.active_experiment = None
            return True

        if decision == OrchDecision.FINISH_SEQUENCE:
            seq = self.state.active_sequence
            await self._execute([FinishSequence(sequence_uuid=seq.sequence_uuid)])
            # Mark the sequence finished in state + history so the operator stops
            # showing it as "active" (ports finish_active_sequence, orch.py:2084).
            orch.complete_sequence(self.state, now)
            self.state.last_sequence = seq
            self.state.active_sequence = None
            return True

        # WAIT: no in-process progress available
        return False


# --------------------------------------------------------------------------- #
# WaitExec — polled timing executor for the orchestrator's built-in wait action
# --------------------------------------------------------------------------- #


class WaitExec:
    """Executor implementing the orchestrator's ``wait`` built-in action.

    Ported from :class:`helao.core.servers.orch_api.WaitExec` onto the
    framework's :mod:`~helao.framework.domain.executor.Executor` contract.

    Placement: ``app/`` layer because it uses :func:`asyncio.sleep` and
    :func:`time.time` (I/O primitives that are fine in ``app/`` but are
    excluded from the pure ``domain/`` layer).

    ``waittime`` is read from ``active.action.action_params``; ``-1`` means
    indefinite (the executor runs until :meth:`stop_action_task` is called).
    """

    def __init__(self, active, **kwargs):
        from helao.framework.domain.executor import Executor as _Executor

        # Reuse Executor's exec_id stamping logic without inheriting from it
        # to avoid requiring the full Executor ABC in the app/ layer.  We duck-
        # type the interface: ``oneoff=False`` (poll loop), ``poll_rate``,
        # ``exec_id``, ``start_time``, ``concurrent``, ``stop_action_task``.
        self.active = active
        self.oneoff = False
        self.poll_rate = 0.01
        self.concurrent = True
        self.exec_id = f"{active.action.action_name} {active.action.action_uuid}"
        self.active.action.exec_id = self.exec_id
        self.start_time = time.time()
        self.duration = self.active.action.action_params.get("waittime", -1)
        self.print_every_secs = kwargs.get("print_every_secs", 5)
        self.last_print_time = self.start_time
        LOGGER.info("WaitExec initialized.")

    async def _pre_exec(self) -> dict:
        """No-op setup phase."""
        return {"error": ErrorCodes.none}

    async def _exec(self) -> dict:
        """Log the wait duration; poll loop handles timing."""
        LOGGER.info(f" ... wait action: {self.duration}")
        return {"data": {}, "error": ErrorCodes.none}

    async def _poll(self) -> dict:
        """Track elapsed time, log progress, and finish once the wait expires."""
        check_time = time.time()
        elapsed = check_time - self.start_time
        if check_time - self.last_print_time > self.print_every_secs - 0.01:
            LOGGER.info(f" ... orch waited {elapsed:.1f}s / {self.duration:.1f}s")
            self.last_print_time = check_time
        if self.duration < 0 or elapsed < self.duration:
            status = HloStatus.active
        else:
            status = HloStatus.finished
        await asyncio.sleep(0.001)
        return {"error": ErrorCodes.none, "status": status}

    async def _post_exec(self) -> dict:
        """Log completion."""
        LOGGER.info(" ... wait action done")
        return {"error": ErrorCodes.none}

    async def _manual_stop(self) -> dict:
        """No-op manual stop."""
        return {"error": ErrorCodes.none}

    def stop_action_task(self) -> None:
        """Signal the action loop to exit on its next iteration."""
        LOGGER.info("WaitExec stop_action_task called.")
        self.active.manual_stop = True
        self.active.action_loop_running = False


# --------------------------------------------------------------------------- #
# OwnStatusIngestor — in-process self-status subscriber for the orch base
# --------------------------------------------------------------------------- #


class OwnStatusIngestor:
    """In-process subscriber that feeds the orch base's action status into driver.on_status_update.

    The orch's WaitExec emits status via base.eventsink (STATUS_CHANNEL). This
    ingestor subscribes to that eventsink's queue and calls driver.on_status_update
    for each emission, so the FSM sees the wait's finished status and advances.
    """

    def __init__(self, base) -> None:
        from helao.framework.app.base_api import FrameworkBase  # local to avoid circ

        self._base = base
        self._task: Optional[asyncio.Task] = None

    def start(self, driver: "OrchDriver") -> None:
        """Start the ingestion background task."""
        self._task = asyncio.create_task(
            self._ingest_loop(driver),
            name=f"own_status_ingestor_{self._base.server_key}",
        )

    def stop(self) -> None:
        """Cancel the ingestion task (idempotent)."""
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None

    async def _ingest_loop(self, driver: "OrchDriver") -> None:
        """Subscribe to base.eventsink and forward status updates to driver.on_status_update."""
        from helao.framework.adapters.orch_status_subscriber import asm_from_action_dict
        from helao.framework.ports.eventsink import STATUS_CHANNEL

        subscribe = getattr(self._base.eventsink, "subscribe", None)
        if not callable(subscribe):
            LOGGER.warning("OwnStatusIngestor: eventsink has no subscribe(); ingestor inactive")
            return
        queue = subscribe()
        while True:
            try:
                item = await queue.get()
                if isinstance(item, tuple) and len(item) == 2:
                    channel, payload = item
                    if channel != STATUS_CHANNEL:
                        continue
                else:
                    payload = item
                asm = asm_from_action_dict(payload)
                if asm is not None:
                    await driver.on_status_update(asm)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOGGER.warning(f"OwnStatusIngestor: error processing status: {exc!r}")


# --------------------------------------------------------------------------- #
# WebSocket relay (module-level so tests can import it directly)
# --------------------------------------------------------------------------- #


async def _orch_ws_relay(websocket, eventsink, channel: str) -> None:
    """Accept a websocket and forward eventsink items on ``channel`` as JSON.

    Subscribes a fresh per-client queue from the (multisubscriber) eventsink and
    forwards the payload of every ``(channel, payload)`` tuple whose channel
    matches. Mirrors ``BaseAPI._ws_relay`` (SP8); JSON wire format. Ends cleanly
    on client disconnect or any send/recv error.
    """
    from starlette.websockets import WebSocketDisconnect

    await websocket.accept()
    subscribe = getattr(eventsink, "subscribe", None)
    if not callable(subscribe):
        await websocket.close()
        return
    queue = subscribe()
    try:
        while True:
            item = await queue.get()
            if isinstance(item, tuple) and len(item) == 2:
                item_channel, payload = item
            else:
                item_channel, payload = channel, item
            if item_channel != channel:
                continue
            await websocket.send_bytes(pyzstd.compress(pickle.dumps(payload)))
    except WebSocketDisconnect:
        return
    except Exception:
        return


# --------------------------------------------------------------------------- #
# FastAPI assembly (thin wrappers over the driver control surface)
# --------------------------------------------------------------------------- #


def makeOrchApp(
    server_key: str,
    *,
    ports: OrchPorts,
    state: Optional[OrchState] = None,
    save_root: Optional[str] = None,
):
    """Build a FastAPI app wrapping an :class:`OrchDriver`.

    FastAPI is imported lazily so importing this module (and the driver) stays
    dependency-light for the in-process runners. Endpoints are thin wrappers
    over the driver's control methods.

    Returns:
        A configured ``fastapi.FastAPI`` whose ``app.state.driver`` is the
        :class:`OrchDriver`.
    """
    from fastapi import FastAPI

    from helao.core.rpc import RPCDispatcher, derive_rpc_port

    from helao.framework.adapters.orch_status_subscriber import OrchStatusSubscriber

    driver = OrchDriver(server_key, ports=ports, state=state)
    app = FastAPI(title=f"{server_key} (framework orchestrator SP5)")
    app.state.driver = driver
    # Co-located ZMQ-RPC dispatcher mirroring the legacy HelaoFastAPI: POST routes
    # are registered as RPC methods at startup so async_private_dispatcher's fast
    # path resolves instead of paying its ~3s RPC-probe timeout per call (the
    # framework orch is a plain FastAPI, so without this every operator/client
    # private dispatch would fall through to the slow HTTP path).
    app.state.rpc_dispatcher = RPCDispatcher(server_key=server_key)
    # Status subscriber: one task per action server in servers_map (b1).
    # Guarded: if servers_map is empty (unit tests / in-process runners) start()
    # is a no-op so no network connections are attempted.
    app.state.status_subscriber = OrchStatusSubscriber(ports.servers_map)

    # --- SP-ORCH-5c: co-locate a FrameworkBase so the orch hosts its OWN -----
    # --- action endpoints (wait/cancel_wait/interrupt) and feeds its OWN     ----
    # --- action status back into the FSM via OwnStatusIngestor.              ----
    from helao.framework.adapters.fs_storage import FsStorage
    from helao.framework.adapters.ntp_clock import NtpClock as _NtpClock
    from helao.framework.adapters.queue_eventsink import QueueEventSink as _QueueEventSink
    from helao.framework.app.base_api import ActionContext, FrameworkBase

    # Determine save_root (IMPORTANT-5 / SP-ARTIFACT Task 2):
    # An explicit caller-supplied ``save_root`` wins (the caller owns the dir
    # and its lifecycle); else use the config root (the PARENT of RUNS_* dirs —
    # Constraint 1); else a tempfile.mkdtemp that WE own (tracked on
    # ``app.state._owned_tempdir``).
    _save_root = save_root
    if _save_root is None:
        try:
            from helao.framework.support import config_loader as _cl
            _cfg = _cl.CONFIG or {}
            _root = _cfg.get("root")
            if _root:
                _save_root = _root
        except Exception:
            pass
    app.state._owned_tempdir = None
    if _save_root is None:
        _save_root = tempfile.mkdtemp(prefix=f"helao_{server_key}_")
        app.state._owned_tempdir = _save_root  # we created it -> we remove it
    os.makedirs(_save_root, exist_ok=True)

    # SEPARATE eventsink for the base — carries action STATUS_CHANNEL events.
    # Must NOT be the same as ports.eventsink (which carries GLOBAL_STATUS_CHANNEL);
    # mixing them would cause OwnStatusIngestor to receive global-status noise.
    _base_eventsink = _QueueEventSink()

    base = FrameworkBase(
        server_key=server_key,
        storage=FsStorage(save_root=_save_root),
        eventsink=_base_eventsink,
        clock=_NtpClock(),
    )
    app.state.base = base

    # The orch hosts its OWN nonblocking actions (e.g. a nonblocking /wait). Route
    # their status reports STRAIGHT to the driver in-process — do NOT set the base's
    # orch_key, which would make the base auto-attach itself as a regular status
    # client (base_api.py:496) and try to RPC-push every status to itself (the ORCH
    # config entry has no orch_host/orch_port -> derive_rpc_port(None) crash, and it
    # is redundant with OwnStatusIngestor). The in-process sink avoids the HTTP/RPC
    # self-loop entirely; action SERVERS (which DO set orch_key) keep the HTTP path.
    base.nonblocking_sink = driver.on_nonblocking
    # Backref so the driver stops the orch's OWN nonblocking executors in-process
    # at experiment finish (a StopExecutor self-RPC would deadlock the loop).
    driver.base = base

    # OwnStatusIngestor: feeds the orch base's action status into driver.on_status_update
    # so the FSM advances when the wait executor finishes.
    app.state.own_status_ingestor = OwnStatusIngestor(base)

    @app.on_event("startup")
    async def _start_base() -> None:
        """Start FrameworkBase background tasks + register action endpoints."""
        await base.myinit()
        await base.init_endpoint_status(app.routes)
        app.state.own_status_ingestor.start(driver)

    @app.on_event("shutdown")
    async def _stop_base() -> None:
        """Stop FrameworkBase + OwnStatusIngestor + dispatch loop; clean owned tempdir."""
        app.state.own_status_ingestor.stop()
        # SP-ORCH-5c: cancel the single long-lived dispatch-loop task cleanly.
        await driver.shutdown()
        await base.shutdown()
        # IMPORTANT-5: remove the tempdir we created (no-op for caller/CONFIG roots).
        owned = getattr(app.state, "_owned_tempdir", None)
        if owned:
            import shutil
            shutil.rmtree(owned, ignore_errors=True)

    @app.on_event("startup")
    async def _start_heartbeat() -> None:
        driver.start_heartbeat()

    @app.on_event("startup")
    async def _start_status_subscriber() -> None:
        """Start JSON /ws_status subscriber tasks for each action server (b1)."""
        app.state.status_subscriber.start(driver)

    @app.on_event("startup")
    async def _start_rpc() -> None:
        # Walk POST routes (defined below) and mirror them into the dispatcher,
        # then bind the ROUTER socket on the derived RPC port. Guarded: without a
        # config slice (in-process runners / unit tests) we skip the bind.
        from fastapi.routing import APIRoute

        from helao.framework.support import config_loader

        cfg = config_loader.CONFIG or {}
        server_cfg = (cfg.get("servers") or {}).get(server_key)
        if not server_cfg or server_cfg.get("port") is None:
            return
        for route in app.routes:
            if isinstance(route, APIRoute) and "POST" in route.methods:
                app.state.rpc_dispatcher.register(route.path, route.endpoint)
        await app.state.rpc_dispatcher.serve(
            host=server_cfg.get("host", "127.0.0.1"),
            port=derive_rpc_port(server_cfg["port"]),
        )

    @app.on_event("shutdown")
    async def _stop_heartbeat() -> None:
        driver.stop_heartbeat()

    @app.on_event("shutdown")
    async def _stop_status_subscriber() -> None:
        """Cancel all /ws_status subscriber tasks on shutdown (b1)."""
        app.state.status_subscriber.stop()

    @app.on_event("shutdown")
    async def _stop_rpc() -> None:
        await app.state.rpc_dispatcher.close()

    # --- SP-ORCH-5c: built-in action endpoints --------------------------------
    # These endpoints are backed by a FrameworkBase so the orch hosts its own
    # action lifecycle (WaitExec runs as a background task and emits status
    # via base.eventsink; OwnStatusIngestor folds that into driver.on_status_update).

    from fastapi import Body as _Body
    from helao.framework.domain.run_models import RunAction as _RunAction
    from helao.framework.models.machine import MachineModel as _MachineModel

    @app.post(f"/{server_key}/wait")
    async def wait(action_dict: dict = _Body({})) -> dict:
        """Start a timed wait action backed by WaitExec. Returns immediately; executor runs in background.

        Accepts two calling conventions:
        1. Orchestrator self-dispatch: body is a full ``RunAction.as_dict()`` (from
           ``execute_commands`` → ``transport.dispatch``). ``waittime`` is read from
           ``body["action_params"]["waittime"]``.
        2. Direct / test calls: body is ``{"waittime": <float>}`` or ``{"action_params": {"waittime": <float>}}``.

        Empty-args calls (RPC reachability probes / handshakes) return a benign
        no-op ack dict without starting a WaitExec.  A real orch self-dispatch
        always includes ``action_params.waittime`` and is never payload-less.
        """
        # Guard: over RPC, an empty-args call (probe/handshake) leaves action_dict
        # as the fastapi.params.Body sentinel if the default is Body(None).
        # Using Body({}) + isinstance guard ensures we always have a plain dict.
        body = action_dict if isinstance(action_dict, dict) else {}

        # Extract waittime from the body — support three calling conventions:
        # 1. Orch dispatch (new):  {waittime: x, "action": {action_uuid: ..., ...}}
        # 2. Direct/test calls:    {"waittime": x}
        # 3. Legacy orch dispatch: {"action_params": {"waittime": x}}
        if "waittime" in body:
            waittime_val = body["waittime"]
        elif "action_params" in body and isinstance(body["action_params"], dict):
            waittime_val = body["action_params"].get("waittime")
        else:
            _nested_action = body.get("action") or {}
            _nested_params = _nested_action.get("action_params") or {}
            waittime_val = _nested_params.get("waittime")

        # A payload-less call (empty body, no waittime signal) is a probe /
        # handshake — never start a spurious wait; return a benign no-op ack.
        if waittime_val is None:
            LOGGER.debug(
                "/wait called with no waittime (likely RPC probe/handshake) — no-op"
            )
            return {"status": "noop", "reason": "no waittime in request"}

        waittime = float(waittime_val)

        # Reuse the uuid from the dispatched action when present so status
        # correlates back to the FSM's tracked action uuid.
        # With the new payload {**action_params, "action": action.as_dict()},
        # action_uuid sits nested under body["action"]["action_uuid"].
        now = datetime.now()
        _raw_uuid = (
            body.get("action_uuid")
            or (body.get("action") or {}).get("action_uuid")
        )
        if _raw_uuid:
            try:
                action_uuid = _uuid.UUID(str(_raw_uuid))
            except (ValueError, AttributeError):
                action_uuid = _uuid.uuid4()
        else:
            action_uuid = _uuid.uuid4()

        # Propagate the dispatched action's ``nonblocking`` flag (see
        # _extract_nonblocking). Without it the self-hosted wait defaults
        # nonblocking=False, its "active" status is broadcast, folded into
        # gsm.active_dict, and the orch BLOCKS on it — defeating a nonblocking
        # wait (TEST_consecutive_noblocking then runs serially / "too long").
        _nonblocking = _extract_nonblocking(body)

        action = _RunAction(
            action_name="wait",
            action_uuid=action_uuid,
            nonblocking=_nonblocking,
            action_timestamp=now,
            sequence_timestamp=now,
            experiment_timestamp=now,
            sequence_name=body.get("sequence_name", "orch_builtin"),
            experiment_name=body.get("experiment_name", "orch_builtin"),
            action_output_dir=str(action_uuid),
            action_server=_MachineModel(server_name=server_key),
            # MINOR-8 (PRODUCTION-CRITICAL): stamp this self-hosted action's
            # ``orchestrator`` to the orch's OWN GSM identity. ``server.py``'s
            # ``_sort_status`` only removes a finished UUID from ``active_dict``
            # when ``statusmodel.orchestrator == self.orchestrator``. Under a real
            # config the GSM orchestrator is the real server identity; if the wait
            # action kept the default ``MachineModel()`` the equality would fail
            # and the finished wait would never leave ``active_dict`` → permanent
            # WAIT stall. Stamping it here keeps self-status folding correct.
            orchestrator=driver.state.globalstatusmodel.orchestrator,
            action_params={"waittime": waittime},
            action_status=[HloStatus.active],
            save_act=False,
            save_data=False,
        )
        active = await app.state.base.setup_and_contain_action(
            ActionContext(action=action, endpoint_name="wait"),
        )
        executor = WaitExec(active=active)
        result = active.start_executor(executor)
        if isinstance(result, dict):
            return result
        return {"action_uuid": str(action_uuid), "status": "active"}

    @app.post(f"/{server_key}/cancel_wait")
    async def cancel_wait() -> dict:
        """Cancel any running wait executors on this orchestrator."""
        _base = app.state.base
        stopped = []
        for exec_id, executor in list(_base.executors.items()):
            if exec_id.split()[0] == "wait":
                stop_fn = getattr(executor, "stop_action_task", None)
                if callable(stop_fn):
                    stop_fn()
                    stopped.append(exec_id)
        return {"stopped": stopped}

    @app.post(f"/{server_key}/interrupt")
    async def interrupt(reason: str = _Body("interrupt", embed=True)) -> dict:
        """Graceful stop of the orch dispatch loop."""
        await driver.stop()
        return {"stopped": True, "reason": reason}

    # Note: /{server_key}/estop already exists below (FSM-level estop).
    # We extend its body via the existing endpoint — no duplicate registered here.

    @app.post(f"/{server_key}/start")
    async def start() -> dict:
        await driver.start()
        return {"loop_state": driver.state.loop_state.value}

    @app.post(f"/{server_key}/stop")
    async def stop() -> dict:
        await driver.stop()
        return {"loop_intent": driver.state.loop_intent.value}

    @app.post(f"/{server_key}/skip")
    async def skip() -> dict:
        await driver.skip()
        return {"loop_intent": driver.state.loop_intent.value}

    @app.post(f"/{server_key}/estop")
    async def estop(reason: str = "") -> dict:
        await driver.estop(reason=reason)
        return {"loop_state": driver.state.loop_state.value}

    @app.post(f"/{server_key}/clear_estop")
    async def clear_estop() -> dict:
        await driver.clear_estop()
        return {"loop_state": driver.state.loop_state.value}

    @app.get(f"/{server_key}/globstat")
    async def globstat() -> dict:
        return driver.state.globalstatusmodel.as_json()

    # --- operator-facing private endpoints (ROOT path, matching ----------
    # --- async_private_dispatcher: http://host:port/{action}) ------------

    @app.post("/get_histories")
    async def get_histories() -> dict:
        return orch.histories_payload(driver.state)

    @app.post("/get_status_summary")
    async def get_status_summary() -> dict:
        return orch.status_summary_payload(driver.state)

    @app.post("/get_step_flags")
    async def get_step_flags() -> dict:
        return orch.step_flags_payload(driver.state)

    @app.post("/set_step_flag")
    async def set_step_flag(kind: str, value: bool) -> dict:
        return orch.set_step_flag(driver.state, kind, value)

    @app.post("/get_orch_state")
    async def get_orch_state() -> dict:
        payload = orch.orch_state_payload(driver.state)
        payload["active_sequence"] = orch.get_active_sequence(driver.state)
        payload["active_experiment"] = orch.get_active_experiment(driver.state)
        return payload

    @app.post("/list_sequences")
    async def list_sequences(limit: int = 10) -> list:
        return [s.as_dict() for s in orch.list_sequences(driver.state, limit)]

    @app.post("/list_experiments")
    async def list_experiments(limit: int = 10) -> list:
        return [e.as_dict() for e in orch.list_experiments(driver.state, limit)]

    @app.post("/list_actions")
    async def list_actions(limit: int = 10) -> list:
        return [a.as_dict() for a in orch.list_actions(driver.state, limit)]

    @app.post("/get_queue_object")
    async def get_queue_object(kind: str, idx: int) -> dict:
        return orch.queue_object_payload(driver.state, kind, idx)

    @app.post("/get_active_sequence")
    async def get_active_sequence() -> dict:
        return orch.get_active_sequence(driver.state)

    @app.post("/get_active_experiment")
    async def get_active_experiment() -> dict:
        return orch.get_active_experiment(driver.state)

    @app.post("/latest_sequence_uuids")
    async def latest_sequence_uuids() -> list:
        return [str(u) for u in orch.latest_sequence_uuids(driver.state)]

    @app.post("/latest_experiment_uuids")
    async def latest_experiment_uuids() -> list:
        return [str(u) for u in orch.latest_experiment_uuids(driver.state)]

    @app.post("/latest_action_uuids")
    async def latest_action_uuids() -> list:
        return [str(u) for u in orch.latest_action_uuids(driver.state)]

    # --- mutation endpoints (ROOT path) ------------------------------------

    from fastapi import Body

    @app.post("/append_sequence")
    async def append_sequence(sequence: dict = Body(..., embed=True)) -> dict:
        seq = _as_run_sequence(sequence)
        orch.append_sequence(driver.state, seq)
        return {"sequence_uuid": str(seq.sequence_uuid)}

    @app.post("/insert_sequence")
    async def insert_sequence(idx: int, sequence: dict = Body(..., embed=True)) -> dict:
        seq = _as_run_sequence(sequence)
        orch.insert_sequence(driver.state, seq, idx)
        return {"sequence_uuid": str(seq.sequence_uuid)}

    @app.post("/prepend_sequences")
    async def prepend_sequences(sequences: list = Body(..., embed=True)) -> list:
        seqs = [_as_run_sequence(d) for d in sequences]
        uuids = orch.prepend_sequences(driver.state, seqs)
        return [str(u) for u in uuids]

    @app.post("/move_sequence")
    async def move_sequence(from_idx: int, to_idx: int) -> dict:
        orch.move_sequence(driver.state, from_idx, to_idx)
        return {"n_sequences": len(driver.state.sequence_dq)}

    @app.post("/remove_sequence")
    async def remove_sequence(idx: int) -> dict:
        orch.remove_sequence(driver.state, idx)
        return {"n_sequences": len(driver.state.sequence_dq)}

    @app.post("/append_split_sequences")
    async def add_split_sequences(sequence: dict = Body(..., embed=True)) -> list:
        # split-by-seq-param config is not present in OrchPorts; fall back to a
        # plain append (faithful to the legacy no-split branch). Real splitting
        # is a documented follow-up.
        seq = _as_run_sequence(sequence)
        orch.append_sequence(driver.state, seq)
        return [str(seq.sequence_uuid)]

    def _as_run_experiment_dict(experiment: dict) -> RunExperiment:
        """Build a RunExperiment from a posted dict, stamping experiment_uuid at enqueue.

        Mirrors ``_as_run_sequence``: a queued experiment must carry a uuid so the
        operator's queue table shows it (legacy stamped at add, not dispatch).
        """
        exp = RunExperiment(
            **{k: v for k, v in experiment.items() if k in RunExperiment.model_fields}
        )
        if exp.experiment_uuid is None:
            exp.experiment_uuid = _uuid.uuid4()
        return exp

    @app.post("/append_experiment")
    async def append_experiment(experiment: dict = Body(..., embed=True)) -> dict:
        exp = _as_run_experiment_dict(experiment)
        orch.append_experiment(driver.state, exp)
        return {"experiment_uuid": str(exp.experiment_uuid)}

    @app.post("/insert_experiment")
    async def insert_experiment(idx: int, experiment: dict = Body(..., embed=True)) -> dict:
        exp = _as_run_experiment_dict(experiment)
        orch.insert_experiment(driver.state, exp, idx)
        return {"experiment_uuid": str(exp.experiment_uuid)}

    @app.post("/update_nonblocking", tags=["private"])
    async def update_nonblocking(
        actionmodel: dict = Body(..., embed=True),
        server_host: str = "",
        server_port: int = 0,
    ) -> dict:
        """Receive a nonblocking action transition from an action server.

        Counterpart of ``FrameworkBase.send_nonblocking_status``. Rehydrates the
        posted action dict and routes it to :meth:`OrchDriver.on_nonblocking`,
        which tracks the executor and registers it in the action history. Ports
        legacy ``Orch.update_nonblocking`` (orch.py:357).
        """
        from helao.framework.models.action import ActionModel

        am = ActionModel(
            **{k: v for k, v in actionmodel.items() if k in ActionModel.model_fields}
        )
        await driver.on_nonblocking(am, server_host, int(server_port or 0))
        return {"success": True}

    @app.post("/clear_sequences")
    async def clear_sequences() -> dict:
        orch.clear_sequences(driver.state)
        return {"n_sequences": 0}

    @app.post("/clear_experiments")
    async def clear_experiments() -> dict:
        orch.clear_experiments(driver.state)
        return {"n_experiments": 0}

    @app.post("/clear_actions")
    async def clear_actions() -> dict:
        orch.clear_actions(driver.state)
        return {"n_actions": 0}

    # --- control aliases at root (share the driver control surface) ------

    @app.post("/start")
    async def start_root() -> dict:
        await driver.start()
        return {"loop_state": driver.state.loop_state.value}

    @app.post("/stop")
    async def stop_root() -> dict:
        await driver.stop()
        return {"loop_intent": driver.state.loop_intent.value}

    @app.post("/skip_experiment")
    async def skip_root() -> dict:
        await driver.skip()
        return {"loop_intent": driver.state.loop_intent.value}

    @app.post("/estop_orch")
    async def estop_root(reason: str = "") -> dict:
        await driver.estop(reason=reason)
        return {"loop_state": driver.state.loop_state.value}

    @app.post("/clear_estop")
    async def clear_estop_root() -> dict:
        await driver.clear_estop()
        return {"loop_state": driver.state.loop_state.value}

    # --- WebSocket status relay (operator RemoteBackend.subscribe) ---------

    from fastapi import WebSocket as _WebSocket  # noqa: F401
    # Publish WebSocket into this module's globals so FastAPI can resolve the
    # ``websocket: WebSocket`` annotation on the route handler at decoration
    # time. FastAPI uses the handler's __globals__ (this module's dict) to
    # evaluate the annotation string; a function-local import is not visible
    # there. Mirrors the same pattern in base_api.py (line ~994).
    import sys as _sys
    _sys.modules[__name__].__dict__.setdefault("WebSocket", _WebSocket)

    @app.websocket("/ws_status")
    async def ws_status(websocket: "WebSocket") -> None:
        await _orch_ws_relay(websocket, ports.eventsink, GLOBAL_STATUS_CHANNEL)

    return app
