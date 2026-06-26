"""The pure orchestration FSM (ex-``Orch`` decision logic).

This module ports the *decision logic* of ``helao.core.servers.orch.Orch`` — the
2428-LOC production orchestrator — into a pure, reducer-style state machine. It
owns the three dispatch queues, the active/last sequence+experiment, the global
status model, the global-param store, and the loop FSM enums, and exposes pure
transition functions that return ``(OrchState, [Command])``: the new state plus a
list of command value objects (see :mod:`helao.framework.domain.commands`) that
``app/orch_api.py`` realises through the injected transport/eventsink/storage
ports.

What lives here (pure): which queue to pull from
(:func:`decide_next`); the intent/state transitions
(:func:`apply_intent`); the status-aggregation reactions
(:func:`on_status_update`); the nonblocking bookkeeping
(:func:`on_nonblocking` / :func:`clear_nonblocking`); the six
``ActionStartCondition`` checks (:func:`start_condition_met`); the per-pull
state transitions after a sequence/experiment/action is popped and (for
seq/exp) expanded (:func:`dispatch_sequence` / :func:`dispatch_experiment` /
:func:`dispatch_action`); and the history maps
(:func:`register_action_uuid` / :func:`track_action_uuid` /
:func:`register_obj_uuid`).

What does NOT live here (``app/`` Wave 4): the asyncio loop, the awaits, the HTTP
dispatch, the library import/expansion call (its *result* is injected, mirroring
how SP4 injects ``now``/``uuid``), the meta-file write, the WS broadcast, the
heartbeat/driver-health probe, and the ``finish_active_*`` aggregation bodies
(the FSM emits :class:`FinishExperiment`/:class:`FinishSequence` commands;
``app/`` performs the work).

**State-mutation pattern.** Transition functions **mutate ``OrchState`` in place
and return it** (along with the command list). This matches SP4's
``ActionSession`` (which mutates its ``RunAction`` in place while lifecycle
helpers emit command objects) and is the natural fit here because ``OrchState``
embeds a :class:`GlobalStatusModel` whose own merge/sort methods already mutate
in place. Callers must still thread the returned state — the return value is the
canonical post-transition state — so the seam stays clean for a future
copy-on-write refactor without touching call sites.

**Expected failures are values, not exceptions.** No transition raises for an
expected condition. Plate-verification failure, dispatch error, estop, etc. are
expressed as state transitions (``loop_state``/``loop_intent``) plus commands;
the ``ErrorCodes`` carried by run-models flow through unchanged.

Purity: imports only from ``helao.framework.models`` / ``domain`` and stdlib. No
asyncio / httpx / fastapi / filesystem / adapters / app coupling (enforced by the
AST boundary test ``helao/framework/tests/test_boundaries.py``).
"""

__all__ = [
    "OrchState",
    "decide_next",
    "apply_intent",
    "on_status_update",
    "on_nonblocking",
    "clear_nonblocking",
    "start_condition_met",
    "dispatch_sequence",
    "dispatch_experiment",
    "dispatch_action",
    "on_dispatch_result",
    "register_obj_uuid",
    "register_action_uuid",
    "track_action_uuid",
    # heartbeat helpers (Task 1)
    "pingable_servers",
    "parse_status_response",
    # read-side ops (Task 2)
    "histories_payload",
    "status_summary_payload",
    "step_flags_payload",
    "set_step_flag",
    "queue_counts",
    "queue_object_payload",
    "list_sequences",
    "list_experiments",
    "list_actions",
    "orch_state_payload",
    "get_active_sequence",
    "get_active_experiment",
    "get_last_sequence",
    "get_last_experiment",
    "latest_sequence_uuids",
    "latest_experiment_uuids",
    "latest_action_uuids",
    # mutation ops (Task 3)
    "move_sequence",
    "remove_sequence",
    "prepend_sequences",
    "append_sequence",
    "insert_sequence",
    "append_experiment",
    "insert_experiment",
    "clear_sequences",
    "clear_experiments",
    "clear_actions",
]

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List, Mapping, Optional, Tuple
from uuid import UUID

from helao.framework.models.action import ActionModel
from helao.framework.models.errors import ErrorCodes
from helao.framework.models.experiment import ExperimentModel
from helao.framework.models.hlostatus import HloStatus
from helao.framework.models.machine import MachineModel
from helao.framework.models.orchstatus import LoopIntent, LoopStatus, OrchStatus
from helao.framework.models.action_start_condition import ActionStartCondition
from helao.framework.models.server import ActionServerModel, GlobalStatusModel

from helao.framework.domain.run_models import RunAction, RunExperiment, RunSequence
from helao.framework.domain import status as status_facade
from helao.framework.domain import expansion
from helao.framework.domain.commands import (
    BroadcastGlobalStatus,
    DispatchAction,
    EstopServers,
    ExpandExperiment,
    ExpandSequence,
    FinishExperiment,
    FinishSequence,
    OrchDecision,
    PersistMeta,
    StopExecutor,
)

from helao.framework.support import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

Command = Any  # one of the frozen command dataclasses in domain.commands


@dataclass
class OrchState:
    """Mutable runtime state of the orchestrator FSM.

    The three queues are plain ``list`` objects used as deques: **index 0 is the
    oldest / next-to-pop end** (``popleft`` semantics) and ``append`` adds at the
    newest end, matching the legacy ``collections.deque`` usage. ``insert(0, x)``
    re-queues an item at the front (the legacy "re-queue on failure" path).

    The loop FSM enums (``loop_state`` / ``loop_intent`` / ``orch_state``) are read
    and written **through** ``globalstatusmodel`` — there is one source of truth.
    Config (libraries, postprocessor names, heartbeat interval) is intentionally
    NOT stored here; it is passed into the pure functions or held by ``app/``.

    Attributes:
        sequence_dq: Pending sequences (oldest at index 0).
        experiment_dq: Pending experiments (oldest at index 0).
        action_dq: Pending actions (oldest at index 0).
        active_sequence: The sequence currently being processed, or ``None``.
        active_experiment: The experiment currently being processed, or ``None``.
        last_sequence: The most recently completed sequence, or ``None``.
        last_experiment: The most recently completed experiment, or ``None``.
        active_seq_exp_counter: Count of experiments dispatched in the active seq.
        active_run_id: Run id attached to dispatched objects, or ``None``.
        global_params: The run-scoped global-param store.
        globalstatusmodel: Aggregate action-server status + loop FSM enums.
        action_history: Action-uuid -> metadata dict.
        experiment_history: Experiment-uuid -> metadata dict.
        sequence_history: Sequence-uuid -> metadata dict.
        last_action_uuid: UUID of the most recently dispatched action (or ``None``).
        current_stop_message: Human-readable reason for the most recent stop.
        step_thru_actions: Pause after each action when True.
        step_thru_experiments: Pause after each experiment when True.
        step_thru_sequences: Pause after each sequence when True.
        nonblocking: Tracked ``(server_key, exec_id, host, port)`` tuples.
        status_summary: Last-seen ``{server_key: (server_status, driver_status)}``
            snapshot. Populated by the network heartbeat (out of scope here);
            read by :func:`status_summary_payload`.
    """

    sequence_dq: List[RunSequence] = field(default_factory=list)
    experiment_dq: List[RunExperiment] = field(default_factory=list)
    action_dq: List[RunAction] = field(default_factory=list)

    active_sequence: Optional[RunSequence] = None
    active_experiment: Optional[RunExperiment] = None
    last_sequence: Optional[RunSequence] = None
    last_experiment: Optional[RunExperiment] = None

    active_seq_exp_counter: int = 0
    active_run_id: Optional[UUID] = None

    global_params: dict = field(default_factory=dict)
    globalstatusmodel: GlobalStatusModel = field(
        default_factory=lambda: GlobalStatusModel(orchestrator=MachineModel())
    )

    action_history: dict = field(default_factory=dict)
    experiment_history: dict = field(default_factory=dict)
    sequence_history: dict = field(default_factory=dict)
    status_summary: dict = field(default_factory=dict)

    last_action_uuid: Optional[UUID] = None
    current_stop_message: str = ""

    step_thru_actions: bool = False
    step_thru_experiments: bool = False
    step_thru_sequences: bool = False

    nonblocking: List[Tuple] = field(default_factory=list)

    # --- loop FSM enums read through the model (single source of truth) ------

    @property
    def loop_state(self) -> LoopStatus:
        """Current dispatch-loop state (read through ``globalstatusmodel``)."""
        return self.globalstatusmodel.loop_state

    @loop_state.setter
    def loop_state(self, value: LoopStatus) -> None:
        self.globalstatusmodel.loop_state = value

    @property
    def loop_intent(self) -> LoopIntent:
        """Pending dispatch-loop intent (read through ``globalstatusmodel``)."""
        return self.globalstatusmodel.loop_intent

    @loop_intent.setter
    def loop_intent(self, value: LoopIntent) -> None:
        self.globalstatusmodel.loop_intent = value

    @property
    def orch_state(self) -> OrchStatus:
        """Orchestrator top-level state (read through ``globalstatusmodel``)."""
        return self.globalstatusmodel.orch_state

    @orch_state.setter
    def orch_state(self, value: OrchStatus) -> None:
        self.globalstatusmodel.orch_state = value


# --- broadcast helper ----------------------------------------------------------


def _broadcast(state: OrchState) -> BroadcastGlobalStatus:
    """Snapshot the global status model into a broadcast command.

    Ports the ``interrupt_q.put(globalstatusmodel)`` push every legacy transition
    issued so subscribers see the new state.
    """
    return BroadcastGlobalStatus(payload=state.globalstatusmodel.as_json())


def complete_idle(state: OrchState) -> Tuple[OrchState, List[Any]]:
    """Natural-completion transition: queues drained -> ``loop_state = stopped``.

    When :func:`decide_next` returns ``IDLE`` (every queue empty, no active
    experiment/sequence, no active actions) the loop has finished all queued
    work. Legacy ``Orch`` stopped the loop at this point; the framework loop
    previously just broke out while leaving ``loop_state == started``, so
    subscribers (the operator) kept showing the orchestrator as "running" after
    a sequence completed. This transitions the loop to ``stopped`` and resets any
    lingering intent, emitting a :class:`BroadcastGlobalStatus` so the operator
    reflects completion. A later ``start`` intent (with new work queued) returns
    the loop to ``started``.

    Returns:
        ``(state, commands)`` with ``state`` mutated in place. Emits the
        broadcast only when an actual ``started -> stopped`` transition occurs.
    """
    gsm = state.globalstatusmodel
    cmds: List[Any] = []
    if gsm.loop_state == LoopStatus.started:
        gsm.loop_state = LoopStatus.stopped
        gsm.loop_intent = LoopIntent.none
        cmds.append(_broadcast(state))
    return state, cmds


# --- heartbeat helpers (Task 1) ------------------------------------------------


def pingable_servers(servers_cfg: dict) -> list:
    """Return (server_key, host, port) for each pingable action server.

    Mirrors the legacy ping_action_servers filter: skip DB/ANA, skip entries with
    ``params.ignore_heartbeats``, and skip UI servers (a ``bokeh``/``demovis`` key).
    """
    out = []
    for server_key, cfg in (servers_cfg or {}).items():
        if server_key in ("DB", "ANA"):
            continue
        if not isinstance(cfg, dict):
            continue
        if "ignore_heartbeats" in (cfg.get("params") or {}):
            continue
        if "bokeh" in cfg or "demovis" in cfg:
            continue
        host = cfg.get("host")
        port = cfg.get("port")
        if host is None or port is None:
            continue
        out.append((server_key, host, port))
    return out


def parse_status_response(response, error_ok: bool) -> tuple:
    """Parse a get_status response into (status_str, driver_status).

    ``("unreachable", "unknown")`` when ``error_ok`` is False or ``response`` is
    None. Otherwise ``driver_status = response["_driver_status"]`` (default
    ``"unknown"``) and ``status_str`` is ``"busy [<eps>]"`` for endpoints whose
    ``active_dict`` is truthy, else ``"idle"``. Mirrors legacy ping parsing.
    """
    if not error_ok or response is None:
        return ("unreachable", "unknown")
    driver_status = response.get("_driver_status", "unknown")
    busy = [
        name
        for name, ep in (response.get("endpoints") or {}).items()
        if ep.get("active_dict")
    ]
    status_str = f"busy [{', '.join(busy)}]" if busy else "idle"
    return (status_str, driver_status)


# --- history maps (pure dict ops) ----------------------------------------------


def register_obj_uuid(
    state: OrchState, obj_uuid_key: Any, obj_uuid_dict: dict, obj_type: str
) -> OrchState:
    """Insert/merge a UUID's metadata into the action/experiment/sequence history.

    Ports ``Orch.register_obj_uuid``: an existing entry is shallow-``update``-d
    with ``obj_uuid_dict``; a new entry is inserted. ``obj_type`` selects the map
    (``"action"`` / ``"experiment"`` / ``"sequence"``).
    """
    obj_map = {
        "action": state.action_history,
        "experiment": state.experiment_history,
        "sequence": state.sequence_history,
    }
    target = obj_map[obj_type]
    if obj_uuid_key in target:
        target[obj_uuid_key].update(obj_uuid_dict)
    else:
        target[obj_uuid_key] = dict(obj_uuid_dict)
    return state


def register_action_uuid(
    state: OrchState, action_uuid: Any, action_dict: dict
) -> OrchState:
    """Record an action UUID and its metadata. Ports ``Orch.register_action_uuid``."""
    return register_obj_uuid(state, action_uuid, action_dict, "action")


def track_action_uuid(state: OrchState, action_uuid: Optional[UUID]) -> OrchState:
    """Remember ``action_uuid`` as the most recently dispatched action.

    Ports ``Orch.track_action_uuid``.
    """
    state.last_action_uuid = action_uuid
    return state


# --- read-side ops (Task 2: payloads, lists, getters) -------------------------


def histories_payload(state: OrchState) -> dict:
    """Action/experiment/sequence history as (uuid, dict) item lists. Ports orch_api._histories_payload."""
    return {
        "action": list(state.action_history.items()),
        "experiment": list(state.experiment_history.items()),
        "sequence": list(state.sequence_history.items()),
    }


def status_summary_payload(state: OrchState) -> dict:
    """{server: [server_status, driver_status]} from state.status_summary. Ports orch_api._status_summary_payload."""
    return {k: list(v) for k, v in state.status_summary.items()}


_STEP_FLAG_ATTR = {
    "actions": "step_thru_actions",
    "experiments": "step_thru_experiments",
    "sequences": "step_thru_sequences",
}


def step_flags_payload(state: OrchState) -> dict:
    """The three step-through flags. Ports orch_api._step_flags_payload."""
    return {
        "actions": state.step_thru_actions,
        "experiments": state.step_thru_experiments,
        "sequences": state.step_thru_sequences,
    }


def set_step_flag(state: OrchState, kind: str, value: bool) -> dict:
    """Set one step flag by kind. Raises KeyError on unknown kind. Ports orch_api._set_step_flag."""
    attr = _STEP_FLAG_ATTR[kind]
    setattr(state, attr, bool(value))
    return {kind: getattr(state, attr)}


def queue_counts(state: OrchState) -> dict:
    """True queue lengths. Ports orch_api._queue_counts."""
    return {
        "n_sequences": len(state.sequence_dq),
        "n_experiments": len(state.experiment_dq),
        "n_actions": len(state.action_dq),
    }


def queue_object_payload(state: OrchState, kind: str, idx: int) -> dict:
    """Full dict for the queued item of kind at idx, or {} (snapshot-safe). Ports orch_api._queue_object_payload."""
    dq = {
        "sequence": state.sequence_dq,
        "experiment": state.experiment_dq,
        "action": state.action_dq,
    }.get(kind)
    if dq is None:
        return {}
    try:
        return dq[idx].as_dict()
    except (IndexError, KeyError, AttributeError):
        return {}


def list_sequences(state: OrchState, limit: int = 10) -> list:
    """At most `limit` sequence summaries from the front of the deque. Ports Orch.list_sequences."""
    return [state.sequence_dq[i].get_seq()
            for i in range(min(len(state.sequence_dq), limit))]


def list_experiments(state: OrchState, limit: int = 10) -> list:
    """At most `limit` experiment summaries. Ports Orch.list_experiments."""
    return [state.experiment_dq[i].get_exp()
            for i in range(min(len(state.experiment_dq), limit))]


def list_actions(state: OrchState, limit: int = 10) -> list:
    """At most `limit` action summaries. Ports Orch.list_actions."""
    return [state.action_dq[i].get_act()
            for i in range(min(len(state.action_dq), limit))]


def orch_state_payload(state: OrchState) -> dict:
    """{loop_state, n_*, current_stop_message} — the shape RemoteBackend.get_orch_state consumes."""
    return {
        "loop_state": state.loop_state,
        "n_sequences": len(state.sequence_dq),
        "n_experiments": len(state.experiment_dq),
        "n_actions": len(state.action_dq),
        "current_stop_message": state.current_stop_message,
    }


def _obj_dict(obj) -> dict:
    """Serialize an active/last sequence|experiment object to a dict, or {}."""
    if obj is None:
        return {}
    try:
        return obj.as_dict()
    except AttributeError:
        return {}


def get_active_sequence(state: OrchState) -> dict:
    return _obj_dict(state.active_sequence)


def get_active_experiment(state: OrchState) -> dict:
    return _obj_dict(state.active_experiment)


def get_last_sequence(state: OrchState) -> dict:
    return _obj_dict(state.last_sequence)


def get_last_experiment(state: OrchState) -> dict:
    return _obj_dict(state.last_experiment)


def latest_sequence_uuids(state: OrchState) -> list:
    """UUIDs of recently registered sequences (history keys)."""
    return list(state.sequence_history.keys())


def latest_experiment_uuids(state: OrchState) -> list:
    return list(state.experiment_history.keys())


def latest_action_uuids(state: OrchState) -> list:
    return list(state.action_history.keys())


# --- mutation ops (Task 3: queue-mutation functions) ----------------------------


def move_sequence(state: OrchState, from_idx: int, to_idx: int) -> OrchState:
    """Move the queued sequence at from_idx to to_idx; out-of-range is a no-op. Ports Orch.move_sequence."""
    dq = state.sequence_dq
    n = len(dq)
    if 0 <= from_idx < n and 0 <= to_idx < n:
        seq = dq.pop(from_idx)
        dq.insert(to_idx, seq)
    return state


def remove_sequence(state: OrchState, idx: int) -> OrchState:
    """Drop the queued sequence at idx; out-of-range no-op. Ports Orch.remove_sequence."""
    if 0 <= idx < len(state.sequence_dq):
        del state.sequence_dq[idx]
    return state


def prepend_sequences(state: OrchState, sequences: list) -> list:
    """Insert sequences at the front preserving order; return their sequence_uuids.

    Pure insert only — run_id/codehash stamping is the app layer's job (SP-ORCH-2).
    Empty list is a no-op returning []. Ports the queue half of Orch.prepend_sequences.
    """
    if not sequences:
        return []
    uuids = []
    for i, sequence in enumerate(sequences):
        state.sequence_dq.insert(i, sequence)
        uuids.append(sequence.sequence_uuid)
    return uuids


def append_sequence(state: OrchState, sequence) -> OrchState:
    """Append a sequence to the back of the queue."""
    state.sequence_dq.append(sequence)
    return state


def insert_sequence(state: OrchState, sequence, idx: int) -> OrchState:
    """Insert a sequence at idx."""
    state.sequence_dq.insert(idx, sequence)
    return state


def append_experiment(state: OrchState, experiment) -> OrchState:
    """Append an experiment to the back of the queue."""
    state.experiment_dq.append(experiment)
    return state


def insert_experiment(state: OrchState, experiment, idx: int) -> OrchState:
    """Insert an experiment at idx."""
    state.experiment_dq.insert(idx, experiment)
    return state


def clear_sequences(state: OrchState) -> OrchState:
    """Empty the sequence queue. Ports Orch.clear_sequences."""
    state.sequence_dq.clear()
    return state


def clear_experiments(state: OrchState) -> OrchState:
    """Empty the experiment queue. Ports Orch.clear_experiments."""
    state.experiment_dq.clear()
    return state


def clear_actions(state: OrchState) -> OrchState:
    """Empty the action queue. Ports Orch.clear_actions."""
    state.action_dq.clear()
    return state


# --- decide_next ---------------------------------------------------------------


def decide_next(state: OrchState) -> OrchDecision:
    """Decide which dispatch step is next. Ports ``Orch.dispatch_loop_task`` ordering.

    Pure read of ``state``; never mutates. Priority order, mirroring the legacy
    loop body:

    1. A stop/estop intent or an ``estopped`` loop state -> ``STOP``.
    2. ``action_dq`` non-empty -> ``DISPATCH_ACTION`` (actions always go first).
    3. else ``experiment_dq`` non-empty: if actions are still running ->
       ``WAIT`` (the legacy ``finish_active_experiment`` waits for all actions);
       once idle -> ``DISPATCH_EXPERIMENT``.
    4. else ``sequence_dq`` non-empty: gated on actions idle the same way ->
       ``WAIT`` / ``DISPATCH_SEQUENCE``.
    5. else (all queues empty): an active experiment to wrap up ->
       ``FINISH_EXPERIMENT``; an active sequence to wrap up ->
       ``FINISH_SEQUENCE``; otherwise -> ``IDLE``.

    Returns:
        The :class:`OrchDecision` describing the next step.
    """
    gsm = state.globalstatusmodel
    if (
        gsm.loop_state == LoopStatus.estopped
        or gsm.loop_intent in (LoopIntent.estop, LoopIntent.stop)
    ):
        return OrchDecision.STOP

    if state.action_dq:
        return OrchDecision.DISPATCH_ACTION

    idle = status_facade.actions_idle(gsm)
    if not idle:
        return OrchDecision.WAIT

    # Actions are idle and none are queued. Experiments run SERIALLY: the active
    # experiment must be FINISHED before the next queued one is dispatched —
    # otherwise dispatch_experiment overwrites active_experiment and the prior
    # experiment is never finished (no FinishExperiment meta, no clear_nonblocking
    # teardown). Ports the legacy dispatch loop, which finished each experiment
    # before dequeuing the next. Same rule for sequences below.
    if state.active_experiment is not None:
        return OrchDecision.FINISH_EXPERIMENT
    if state.experiment_dq:
        return OrchDecision.DISPATCH_EXPERIMENT
    # No active or queued experiments: a finished sequence wraps up before the
    # next sequence is dispatched.
    if state.active_sequence is not None:
        return OrchDecision.FINISH_SEQUENCE
    if state.sequence_dq:
        return OrchDecision.DISPATCH_SEQUENCE
    return OrchDecision.IDLE


# --- intent transitions --------------------------------------------------------


def apply_intent(
    state: OrchState, intent: str, *, reason: str = ""
) -> Tuple[OrchState, List[Command]]:
    """Apply a control intent to the loop FSM. Ports the ``Orch`` intent methods.

    Recognised ``intent`` strings and the legacy method each ports:

    * ``"start"`` -> ``start_loop``: if stopped and there is work (queues or an
      active sequence) move ``loop_state`` to ``started`` and clear the stop
      message; refuse (no-op) under ``estopped``.
    * ``"stop"`` -> ``stop`` / ``intend_stop``: set ``LoopIntent.stop`` while
      started; no-op under estop/stopped.
    * ``"skip"`` -> ``skip`` / ``intend_skip``: set ``LoopIntent.skip`` while
      started; if not started, clear ``action_dq``.
    * ``"estop"`` -> ``estop_loop``: set ``loop_state=estopped``, drop
      ``active_run_id``, reset intent to ``none``, set the stop message, and emit
      an :class:`EstopServers` (switch=False, don't latch) command.
    * ``"clear_estop"`` -> ``clear_estop``: clear estopped uuids, emit
      :class:`EstopServers` release, and move ``loop_state`` back to ``stopped``.
    * ``"clear_error"`` -> ``clear_error``: clear errored uuids.
    * ``"clear_sequences"`` / ``"clear_experiments"`` / ``"clear_actions"`` ->
      empty the corresponding queue.
    * ``"intend_stop"`` / ``"intend_skip"`` / ``"intend_estop"`` /
      ``"intend_none"`` -> set the corresponding ``LoopIntent`` directly.

    Every recognised intent emits a :class:`BroadcastGlobalStatus` so subscribers
    observe the transition (mirroring the legacy ``interrupt_q`` push); estop and
    clear_estop additionally emit an :class:`EstopServers` command.

    Returns:
        ``(state, commands)`` with ``state`` mutated in place.
    """
    gsm = state.globalstatusmodel
    cmds: List[Command] = []

    if intent == "start":
        if gsm.loop_state == LoopStatus.stopped:
            if (
                state.action_dq
                or state.experiment_dq
                or state.sequence_dq
                or state.active_sequence is not None
            ):
                gsm.loop_state = LoopStatus.started
                state.current_stop_message = ""
            # else: nothing to start; remain stopped
        # else: already running, or estopped (refuse) -> no-op
        cmds.append(_broadcast(state))

    elif intent in ("stop", "intend_stop"):
        if intent == "intend_stop" or gsm.loop_state == LoopStatus.started:
            gsm.loop_intent = LoopIntent.stop
        cmds.append(_broadcast(state))

    elif intent in ("skip", "intend_skip"):
        if intent == "skip" and gsm.loop_state != LoopStatus.started:
            state.action_dq.clear()
        else:
            gsm.loop_intent = LoopIntent.skip
        cmds.append(_broadcast(state))

    elif intent == "intend_estop":
        gsm.loop_intent = LoopIntent.estop
        cmds.append(_broadcast(state))

    elif intent == "intend_none":
        gsm.loop_intent = LoopIntent.none
        cmds.append(_broadcast(state))

    elif intent == "estop":
        gsm.loop_state = LoopStatus.estopped
        state.active_run_id = None
        gsm.loop_intent = LoopIntent.none
        suffix = f" {reason}" if reason else ""
        state.current_stop_message = "E-STOP" + suffix
        cmds.append(EstopServers(switch=False, reason=reason))
        cmds.append(_broadcast(state))

    elif intent == "clear_estop":
        gsm.clear_in_finished(hlostatus=HloStatus.estopped)
        gsm.loop_state = LoopStatus.stopped
        cmds.append(EstopServers(switch=False, reason=reason))
        cmds.append(_broadcast(state))

    elif intent == "clear_error":
        gsm.clear_in_finished(hlostatus=HloStatus.errored)
        cmds.append(_broadcast(state))

    elif intent == "clear_sequences":
        state.sequence_dq.clear()
        cmds.append(_broadcast(state))

    elif intent == "clear_experiments":
        state.experiment_dq.clear()
        cmds.append(_broadcast(state))

    elif intent == "clear_actions":
        state.action_dq.clear()
        cmds.append(_broadcast(state))

    else:
        LOGGER.info(f"apply_intent: unrecognised intent {intent!r}, ignoring")

    return state, cmds


# --- status reactions ----------------------------------------------------------


def _fmt_ts(ts: Any) -> Optional[str]:
    """Format an action timestamp like legacy ``f"{ts: %m-%d %H:%M:%S}"`` or None."""
    if ts is None:
        return None
    try:
        return f"{ts: %m-%d %H:%M:%S}"
    except (TypeError, ValueError):
        return str(ts)


def _register_server_actions(
    state: OrchState, actionservermodel: ActionServerModel
) -> None:
    """Register every action carried in ``actionservermodel`` into ``action_history``.

    Ports the registration block of legacy ``Orch.update_status``
    (orch.py:475-531). Unlike the legacy code — which only registered the single
    ``last_action_uuid`` — this registers every action present in the snapshot's
    endpoint buckets (active + nonactive). ``register_action_uuid`` is an
    update-or-insert, so an action seen first ``active`` then ``finished`` simply
    has its entry updated (gaining ``action_finished_timestamp``). The
    experiment/sequence context is attributed only when the action belongs to the
    orch's currently active experiment, matching legacy.
    """
    endpoints = getattr(actionservermodel, "endpoints", None)
    if not endpoints:
        return
    for endpoint_model in endpoints.values():
        act_models: dict = {}
        act_models.update(getattr(endpoint_model, "active_dict", {}) or {})
        for bucket in (getattr(endpoint_model, "nonactive_dict", {}) or {}).values():
            act_models.update(bucket or {})
        for act_uuid, act_model in act_models.items():
            matching_experiment = (
                state.active_experiment is not None
                and state.active_experiment.experiment_uuid == act_model.experiment_uuid
            )
            register_action_uuid(
                state,
                act_uuid,
                {
                    "action_name": act_model.action_name,
                    "action_status": act_model.action_status,
                    "action_server": act_model.action_server.server_name,
                    "action_timestamp": _fmt_ts(
                        getattr(act_model, "action_timestamp", None)
                    ),
                    "action_finished_timestamp": _fmt_ts(
                        getattr(act_model, "action_finished_timestamp", None)
                    ),
                    "experiment_name": (
                        state.active_experiment.experiment_name
                        if matching_experiment
                        else None
                    ),
                    "experiment_uuid": act_model.experiment_uuid,
                    "sequence_name": (
                        state.active_sequence.sequence_name
                        if state.active_sequence is not None and matching_experiment
                        else None
                    ),
                    "sequence_label": (
                        state.active_sequence.sequence_label
                        if state.active_sequence is not None and matching_experiment
                        else None
                    ),
                    "sequence_uuid": (
                        state.active_sequence.sequence_uuid
                        if state.active_sequence is not None and matching_experiment
                        else None
                    ),
                },
            )


def on_status_update(
    state: OrchState, actionservermodel: Optional[ActionServerModel]
) -> Tuple[OrchState, List[Command]]:
    """Fold a remote server status into the global model and react. Ports ``update_status``.

    Merges ``actionservermodel`` via :func:`status.merge_server_status`, then
    classifies (matching the legacy ``update_status`` ladder):

    * estopped uuids present while ``loop_state == started`` -> apply the
      ``estop`` intent (emits :class:`EstopServers` + sets ``estopped``).
    * else errored uuids present while started -> ``orch_state = error``.
    * else no active actions -> ``orch_state = idle``.
    * else -> ``orch_state = busy``.

    A ``None`` model is a no-op returning no commands (legacy returned ``False``).
    Always emits a :class:`BroadcastGlobalStatus` on a real update.

    Returns:
        ``(state, commands)`` with ``state`` mutated in place.
    """
    if actionservermodel is None:
        return state, []

    gsm = state.globalstatusmodel
    cmds: List[Command] = []

    # Record every action this snapshot carries into ``action_history`` BEFORE
    # the merge folds finished actions away. Ports the registration block of
    # legacy ``Orch.update_status`` (orch.py:475-531), which the SP-ORCH-5 port
    # dropped — without it the operator's Action history table is always empty
    # (experiments/sequences register at dispatch; actions never did).
    _register_server_actions(state, actionservermodel)

    status_facade.merge_server_status(gsm, actionservermodel)

    estop_uuids = gsm.find_hlostatus_in_finished(hlostatus=HloStatus.estopped)
    error_uuids = gsm.find_hlostatus_in_finished(hlostatus=HloStatus.errored)

    if estop_uuids and gsm.loop_state == LoopStatus.started:
        _state, estop_cmds = apply_intent(
            state, "estop", reason=f"due to action uuid(s): {list(estop_uuids)}"
        )
        cmds.extend(estop_cmds)
        # estop already broadcast; return early to avoid a duplicate broadcast
        return state, cmds
    elif error_uuids and gsm.loop_state == LoopStatus.started:
        gsm.orch_state = OrchStatus.error
    elif not gsm.active_dict:
        gsm.orch_state = OrchStatus.idle
    else:
        gsm.orch_state = OrchStatus.busy

    cmds.append(_broadcast(state))
    return state, cmds


# --- nonblocking bookkeeping ---------------------------------------------------


def on_nonblocking(
    state: OrchState,
    actionmodel: ActionModel,
    host: str,
    port: int,
) -> Tuple[OrchState, List[Command]]:
    """Record a nonblocking action transition and nudge the loop. Ports ``update_nonblocking``.

    Registers the action in ``action_history``, then adds the
    ``(server_key, exec_id, host, port)`` tuple to ``state.nonblocking`` when the
    action is ``active`` or removes it otherwise. Emits a
    :class:`BroadcastGlobalStatus` to wake the dispatch loop (the legacy code put
    the global model on ``interrupt_q``).

    Returns:
        ``(state, commands)`` with ``state`` mutated in place.
    """
    matching_experiment = (
        state.active_experiment is not None
        and state.active_experiment.experiment_uuid == actionmodel.experiment_uuid
    )
    register_action_uuid(
        state,
        actionmodel.action_uuid,
        {
            "action_name": actionmodel.action_name,
            "action_status": actionmodel.action_status,
            "action_server": actionmodel.action_server.server_name,
            "experiment_uuid": actionmodel.experiment_uuid,
            "experiment_name": (
                state.active_experiment.experiment_name
                if matching_experiment
                else None
            ),
            "sequence_name": (
                state.active_sequence.sequence_name
                if state.active_sequence is not None and matching_experiment
                else None
            ),
            "sequence_uuid": (
                state.active_sequence.sequence_uuid
                if state.active_sequence is not None and matching_experiment
                else None
            ),
        },
    )

    server_key = actionmodel.action_server.server_name
    server_exec_id = (server_key, actionmodel.exec_id, host, port)
    if HloStatus.active in actionmodel.action_status:
        # Idempotent: a status can be delivered more than once (e.g. the orch is
        # both auto-attached AND resolved from CONFIG in send_nonblocking_status's
        # target set). Guard so an executor is tracked at most once — otherwise the
        # matching finish report removes only one copy and the orphan lingers.
        if server_exec_id not in state.nonblocking:
            state.nonblocking.append(server_exec_id)
    elif server_exec_id in state.nonblocking:
        state.nonblocking.remove(server_exec_id)

    return state, [_broadcast(state)]


def clear_nonblocking(state: OrchState) -> Tuple[OrchState, List[Command]]:
    """Emit a ``stop_executor`` command per tracked nonblocking action. Ports ``clear_nonblocking``.

    Returns one :class:`StopExecutor` command for each tuple in
    ``state.nonblocking`` (without clearing the list — the entries are removed by
    :func:`on_nonblocking` when each action reports non-active, exactly as the
    legacy code relied on the subsequent status pushes).

    Returns:
        ``(state, commands)`` with ``state`` unchanged.
    """
    cmds: List[Command] = [
        StopExecutor(
            server_key=server_key, executor_id=exec_id, host=host, port=port
        )
        for server_key, exec_id, host, port in state.nonblocking
    ]
    return state, cmds


# --- start-condition check -----------------------------------------------------


def start_condition_met(state: OrchState, action: RunAction) -> bool:
    """Return True when ``action``'s start condition is satisfied. Ports the wait logic.

    Pure read of the global status model; never mutates. Mirrors the six
    ``ActionStartCondition`` branches inside ``loop_task_dispatch_action`` (the
    legacy code *waited* on each; here we report whether the wait would pass):

    * ``no_wait`` -> always True.
    * ``wait_for_endpoint`` -> endpoint free.
    * ``wait_for_server`` -> server free.
    * ``wait_for_orch`` -> the orchestrator's ``"wait"`` endpoint is free.
    * ``wait_for_previous`` -> the last dispatched action is no longer active.
    * ``wait_for_all`` (and any unsupported value) -> all actions idle.

    Returns:
        ``True`` if the action may dispatch now, else ``False``.
    """
    gsm = state.globalstatusmodel
    cond = action.start_condition

    if cond == ActionStartCondition.no_wait:
        return True
    if cond == ActionStartCondition.wait_for_endpoint:
        return status_facade.endpoint_free(
            gsm, action.action_server, action.action_name
        )
    if cond == ActionStartCondition.wait_for_server:
        return status_facade.server_free(gsm, action.action_server)
    if cond == ActionStartCondition.wait_for_orch:
        return status_facade.endpoint_free(gsm, action.orchestrator, "wait")
    if cond == ActionStartCondition.wait_for_previous:
        return state.last_action_uuid not in gsm.active_dict
    # wait_for_all and any unsupported value
    return status_facade.actions_idle(gsm)


# --- dispatch steps ------------------------------------------------------------


def dispatch_sequence(
    state: OrchState,
    *,
    now: datetime,
    uuid: UUID,
    expand_result: Optional[List[ExperimentModel]] = None,
) -> Tuple[OrchState, List[Command]]:
    """Pop the next sequence, make it active, fold globals, register it. Ports ``loop_task_dispatch_sequence``.

    Pops ``sequence_dq[0]`` into ``active_sequence`` (the prior active sequence is
    retained as ``last_sequence``), stamps the injected ``now``/``uuid`` for any
    missing identity, folds ``from_global_seq_params`` into ``sequence_params``
    (via :func:`expansion.fold_in_global`), derives ``active_run_id``, registers
    the sequence in ``sequence_history``, and resets the per-sequence experiment
    counter.

    The library expansion itself is an ``app/`` side effect: when
    ``expand_result`` is ``None`` an :class:`ExpandSequence` command is emitted so
    ``app/`` calls the factory and re-invokes with the result; when it is provided
    the planned experiments are written onto ``active_sequence.planned_experiments``
    (only if not already populated by the operator). A :class:`PersistMeta`
    (``kind="seq"``) command is always emitted.

    With an empty ``sequence_dq`` this is a no-op returning no commands (the legacy
    "queue empty" branch is handled by :func:`decide_next` returning ``IDLE``).

    Returns:
        ``(state, commands)`` with ``state`` mutated in place.
    """
    if not state.sequence_dq:
        return state, []

    if state.active_sequence is not None:
        state.last_sequence = state.active_sequence

    seq = state.sequence_dq.pop(0)
    state.active_sequence = seq

    if seq.sequence_uuid is None:
        seq.sequence_uuid = uuid
    if seq.sequence_timestamp is None:
        seq.sequence_timestamp = now

    # fold requested global params into sequence params
    seq.sequence_params = expansion.fold_in_global(
        seq.sequence_params, seq.from_global_seq_params, state.global_params
    )

    # derive the active run id from the sequence
    if getattr(seq, "run_id", None) is not None:
        state.active_run_id = seq.run_id
    elif state.active_run_id is None:
        state.active_run_id = seq.sequence_uuid

    register_obj_uuid(
        state,
        seq.sequence_uuid,
        {
            "sequence_name": seq.sequence_name,
            "sequence_status": "active",
            "sequence_label": seq.sequence_label,
        },
        "sequence",
    )

    state.active_seq_exp_counter = 0

    cmds: List[Command] = []
    if expand_result is None:
        cmds.append(
            ExpandSequence(
                sequence_name=seq.sequence_name,
                sequence_params=dict(seq.sequence_params),
            )
        )
    else:
        if not seq.planned_experiments:
            seq.planned_experiments = list(expand_result)

    cmds.append(
        PersistMeta(kind="seq", uuid=seq.sequence_uuid, payload=seq.as_dict())
    )
    return state, cmds


def dispatch_experiment(
    state: OrchState,
    *,
    now: datetime,
    uuid: UUID,
    expand_result: Optional[List[RunAction]] = None,
) -> Tuple[OrchState, List[Command]]:
    """Pop the next experiment, fold globals, expand into staged actions. Ports ``loop_task_dispatch_experiment``.

    Pops ``experiment_dq[0]`` into ``active_experiment`` (prior active experiment
    retained as ``last_experiment``), links it to ``active_sequence``
    (``sequence_uuid``), bumps ``active_seq_exp_counter``, folds
    ``from_global_exp_params`` into ``experiment_params``, stamps injected
    ``now``/``uuid``, attaches ``active_run_id``, calls
    ``globalstatusmodel.new_experiment`` to seed the dispatch counter, and
    registers the experiment in ``experiment_history``.

    The library expansion is an ``app/`` side effect: with ``expand_result``
    ``None`` an :class:`ExpandExperiment` command is emitted; with a result the
    planned actions are staged onto ``action_dq`` — each is assigned an
    ``action_order``/``orch_submit_order`` and a fresh ``action_uuid`` (derived
    deterministically from the injected ``uuid`` so tests are reproducible).
    A :class:`PersistMeta` (``kind="exp"``) command is always emitted.

    Returns:
        ``(state, commands)`` with ``state`` mutated in place.
    """
    if not state.experiment_dq:
        return state, []

    if state.active_experiment is not None:
        state.last_experiment = state.active_experiment

    exp = state.experiment_dq.pop(0)
    state.active_experiment = exp

    if state.active_sequence is not None:
        exp.sequence_uuid = state.active_sequence.sequence_uuid
    state.active_seq_exp_counter += 1

    if exp.experiment_uuid is None:
        exp.experiment_uuid = uuid
    if exp.experiment_timestamp is None:
        exp.experiment_timestamp = now

    # fold requested global params into experiment params
    exp.experiment_params = expansion.fold_in_global(
        exp.experiment_params, exp.from_global_exp_params, state.global_params
    )

    if state.active_run_id is not None:
        exp.run_id = state.active_run_id

    state.globalstatusmodel.new_experiment(exp_uuid=exp.experiment_uuid)

    register_obj_uuid(
        state,
        exp.experiment_uuid,
        {
            "experiment_name": exp.experiment_name,
            "experiment_status": "active",
        },
        "experiment",
    )

    cmds: List[Command] = []
    if expand_result is None:
        cmds.append(
            ExpandExperiment(
                experiment_name=exp.experiment_name,
                experiment_params=dict(exp.experiment_params),
            )
        )
    else:
        for i, act in enumerate(expand_result):
            act.action_order = i
            act.orch_submit_order = i
            if act.action_uuid is None:
                # deterministic per-index uuid derived from the injected seed
                act.action_uuid = UUID(int=(uuid.int + 1 + i) % (1 << 128))
            act.experiment_uuid = exp.experiment_uuid
            state.action_dq.append(act)

    cmds.append(
        PersistMeta(kind="exp", uuid=exp.experiment_uuid, payload=exp.as_dict())
    )
    return state, cmds


def dispatch_action(
    state: OrchState, *, now: datetime, uuid: UUID
) -> Tuple[OrchState, List[Command]]:
    """Prepare and emit the next action for dispatch. Ports ``loop_task_dispatch_action`` (no I/O).

    Handles the loop-intent fast paths first (matching the legacy method's
    leading branches), without popping when the intent is terminal:

    * ``LoopIntent.skip`` -> clear ``action_dq``, reset intent to ``none``, emit a
      broadcast; no dispatch.
    * ``LoopIntent.estop`` -> clear ``action_dq``, reset intent, set
      ``loop_state=estopped``, emit an :class:`EstopServers`; no dispatch.

    Otherwise pops ``action_dq[0]`` and, **only if its start condition is met**
    (:func:`start_condition_met`): folds ``from_global_act_params`` into
    ``action_params``, attaches ``active_run_id``, stamps the injected
    ``now``/``uuid`` for missing identity, bumps the experiment's dispatch counter
    (``orch_submit_order``), self-registers the action as ``active`` in the global
    status model, tracks it as the last dispatched action, and emits a
    :class:`DispatchAction` command. If the start condition is **not** met the
    action is re-queued at the front and no command is emitted (the legacy code
    awaited an interrupt — here ``app/`` simply retries on the next wake).

    Returns:
        ``(state, commands)`` with ``state`` mutated in place.
    """
    gsm = state.globalstatusmodel
    cmds: List[Command] = []

    if not state.action_dq:
        return state, cmds

    if gsm.loop_intent == LoopIntent.skip:
        state.action_dq.clear()
        gsm.loop_intent = LoopIntent.none
        cmds.append(_broadcast(state))
        return state, cmds
    if gsm.loop_intent == LoopIntent.estop:
        state.action_dq.clear()
        gsm.loop_intent = LoopIntent.none
        gsm.loop_state = LoopStatus.estopped
        cmds.append(EstopServers(switch=False))
        cmds.append(_broadcast(state))
        return state, cmds

    action = state.action_dq.pop(0)

    if not start_condition_met(state, action):
        # not ready yet: re-queue at the front, let app/ retry on next wake
        state.action_dq.insert(0, action)
        return state, cmds

    # fold requested global params into action params
    action.action_params = expansion.fold_in_global(
        action.action_params, action.from_global_act_params, state.global_params
    )

    if state.active_run_id is not None:
        action.run_id = state.active_run_id

    if action.action_uuid is None:
        action.action_uuid = uuid
    if action.action_timestamp is None:
        action.action_timestamp = now

    # bump the per-experiment dispatch counter
    if state.active_experiment is not None:
        exp_uuid = state.active_experiment.experiment_uuid
        count = gsm.counter_dispatched_actions.get(exp_uuid, 0)
        action.orch_submit_order = count
        gsm.counter_dispatched_actions[exp_uuid] = count + 1

    # self-register the dispatched action as active (ports the in-loop register)
    if not action.nonblocking and HloStatus.active not in action.action_status:
        action.action_status.append(HloStatus.active)
    if not action.nonblocking:
        gsm.active_dict[action.action_uuid] = action

    track_action_uuid(state, action.action_uuid)

    cmds.append(DispatchAction(action=action, nonblocking=action.nonblocking))
    return state, cmds


def on_dispatch_result(
    state: OrchState, result_action: Optional[RunAction], error: ErrorCodes
) -> Tuple[OrchState, List[Command]]:
    """Fold a dispatch response back into state. Ports the post-dispatch block of ``loop_task_dispatch_action``.

    Called by ``app/`` after realising a :class:`DispatchAction` command:

    * ``error != none`` or ``result_action is None`` -> set the stop message,
      request a graceful ``stop`` intent, and (when an action is available)
      re-queue it at the front; no global-param fold. Mirrors the legacy
      "pause orch and re-queue" path.
    * ``result_action.error_code != none`` -> apply the ``estop`` intent (emits
      :class:`EstopServers`).
    * otherwise -> record the result on the active experiment's
      ``dispatched_actions`` tally and fold ``to_global_params`` back into
      ``state.global_params`` (via :func:`expansion.fold_out_global`).

    Returns:
        ``(state, commands)`` with ``state`` mutated in place.
    """
    cmds: List[Command] = []

    if error != ErrorCodes.none or result_action is None:
        state.current_stop_message = "Dispatch failed. Pausing orch."
        if result_action is not None:
            state.action_dq.insert(0, result_action)
        _state, stop_cmds = apply_intent(state, "stop")
        cmds.extend(stop_cmds)
        return state, cmds

    if result_action.error_code not in (None, ErrorCodes.none):
        _state, estop_cmds = apply_intent(
            state,
            "estop",
            reason=f"{result_action.action_name} returned an error",
        )
        cmds.extend(estop_cmds)
        return state, cmds

    if state.active_experiment is not None:
        state.active_experiment.dispatched_actions.append(result_action)

    if result_action.to_global_params:
        delta = expansion.fold_out_global(
            result_action.to_global_params,
            result_action.action_params,
            result_action.action_output,
        )
        state.global_params.update(delta)

    return state, cmds
