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

import uuid as _uuid
from datetime import datetime
from typing import Any, Callable, List, Mapping, Optional

from helao.framework.models.errors import ErrorCodes
from helao.framework.models.hlostatus import HloStatus
from helao.framework.models.server import ActionServerModel, EndpointModel

from helao.framework.domain import expansion
from helao.framework.domain import orchestration as orch
from helao.framework.domain.orchestration import OrchState
from helao.framework.domain.run_models import RunAction, RunExperiment
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
from helao.framework.ports.eventsink import EventSink
from helao.framework.ports.storage import Storage
from helao.framework.ports.transport import DispatchTarget, Transport

from helao.framework.support import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

__all__ = ["OrchPorts", "execute_commands", "OrchDriver", "makeOrchApp"]


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
    ) -> None:
        self.transport = transport
        self.storage = storage
        self.eventsink = eventsink
        self.clock = clock
        self.sequence_lib: Mapping[str, Callable] = dict(sequence_lib or {})
        self.experiment_lib: Mapping[str, Callable] = dict(experiment_lib or {})
        self.postprocessors: List[str] = list(postprocessors or [])

    def now(self) -> datetime:
        """Wall-clock ``datetime`` from the injected clock port."""
        now_dt = getattr(self.clock, "now_datetime", None)
        if callable(now_dt):
            return now_dt()
        return datetime.fromtimestamp(self.clock.now_ns() / 1e9)


# --------------------------------------------------------------------------- #
# the shared command-execution glue (reused by OrchDriver AND micro_orch)
# --------------------------------------------------------------------------- #


def _dispatch_target_for(action: RunAction, endpoint: str = "run_action") -> DispatchTarget:
    """Build a :class:`DispatchTarget` from an action's action-server identity."""
    server = action.action_server
    server_key = getattr(server, "server_name", None) or "action"
    host = getattr(server, "hostname", None) or getattr(server, "host", None) or "127.0.0.1"
    port = getattr(server, "port", None) or 8000
    return DispatchTarget(
        server_key=server_key, host=host, port=int(port), endpoint=endpoint
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
            target = _dispatch_target_for(action)
            result = await ports.transport.dispatch(target, action.as_dict())
            result_action = action if result.error == ErrorCodes.none else None
            _st, fb = orch.on_dispatch_result(state, result_action, result.error)
            followups.extend(fb)
            if result.error == ErrorCodes.none and not cmd.nonblocking:
                # fold the (now finished) action back in, as a status push would
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
    """Coerce a planned :class:`ExperimentModel` into a :class:`RunExperiment`."""
    if isinstance(exp, RunExperiment):
        return exp
    return RunExperiment(**exp.model_dump())


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

    # --- command execution + draining --------------------------------------

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
        """Move the loop to ``started`` (if there is work) and run it."""
        await self._intent("start")
        await self.run_dispatch_loop()

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
        """Fold a remote action-server status into state and execute reactions."""
        _st, cmds = orch.on_status_update(self.state, asm)
        await self._execute(cmds)

    # --- enqueue -------------------------------------------------------------

    def enqueue_sequence(self, sequence) -> None:
        """Append a :class:`RunSequence` to the sequence queue."""
        self.state.sequence_dq.append(sequence)

    def enqueue_experiment(self, experiment) -> None:
        """Append a :class:`RunExperiment` to the experiment queue."""
        self.state.experiment_dq.append(experiment)

    # --- the loop ------------------------------------------------------------

    async def run_dispatch_loop(self, *, max_steps: int = 10_000) -> None:
        """Drive the FSM to a natural stop/idle, realising commands via ports.

        Each iteration consults :func:`orchestration.decide_next` and, for the
        seq/exp dispatch decisions, pre-expands through the library maps so the
        pure dispatch step receives its ``expand_result``. The single ``app/``
        exception boundary wraps the body: an unexpected exception logs, drives
        the FSM to ``estopped``, executes the estop commands, and breaks.
        """
        from helao.framework.models.orchstatus import LoopStatus

        steps = 0
        while steps < max_steps:
            steps += 1
            if self.state.loop_state != LoopStatus.started:
                break
            decision = orch.decide_next(self.state)
            if decision in (OrchDecision.STOP, OrchDecision.IDLE):
                break
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
                # WAIT with nothing externally driving us forward: avoid a spin.
                break

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
            await self._execute([FinishExperiment(experiment_uuid=exp.experiment_uuid)])
            self.state.last_experiment = exp
            self.state.active_experiment = None
            return True

        if decision == OrchDecision.FINISH_SEQUENCE:
            seq = self.state.active_sequence
            await self._execute([FinishSequence(sequence_uuid=seq.sequence_uuid)])
            self.state.last_sequence = seq
            self.state.active_sequence = None
            return True

        # WAIT: no in-process progress available
        return False


# --------------------------------------------------------------------------- #
# FastAPI assembly (thin wrappers over the driver control surface)
# --------------------------------------------------------------------------- #


def makeOrchApp(
    server_key: str,
    *,
    ports: OrchPorts,
    state: Optional[OrchState] = None,
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

    driver = OrchDriver(server_key, ports=ports, state=state)
    app = FastAPI(title=f"{server_key} (framework orchestrator SP5)")
    app.state.driver = driver

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

    return app
