"""Dispatch-decision golden-master harness for the legacy ``Orch`` orchestrator
(CARDS P5, Stage S0 of S0-S9 -- the verification foundation for the full
in-place decomposition specced in ``CARDS_REFACTOR_P5.md``).

Mirrors the PAL call-trace golden master
(``helao/deploy/hte/tests/test_pal_golden_master.py`` -- ``__new__`` bypass +
fakes + pinned/deterministic timing + recorded ordered JSON-lines trace +
double-capture determinism check) but targets the orchestrator's dispatch
state-machine (spec :sec:`5.3`) instead of the PAL driver.

What is REAL (driven, unmodified, byte-identical to the shipped orchestrator):

* ``Orch.dispatch_loop_task`` / ``loop_task_dispatch_sequence`` /
  ``loop_task_dispatch_experiment`` / ``loop_task_dispatch_action`` /
  ``wait_for_interrupt`` / the intent methods (``intend_skip`` /
  ``intend_stop`` / ``intend_estop`` / ``intend_none``) / the global-param
  fold-in and fold-out blocks / ``estop_loop`` / ``estop_actions`` /
  ``finish_active_experiment`` / ``finish_active_sequence`` /
  ``update_status`` / ``update_nonblocking`` / ``GlobalStatusModel``.
* ``Orch`` is constructed via ``Orch.__new__`` + a minimal attribute fixture
  that bypasses ``Base.__init__`` entirely (no FastAPI app, no disk I/O
  paths, no NTP) -- the same bypass strategy the PAL harness uses for ``PAL``.

What is FAKED/STUBBED (the harness surface, per spec :sec:`5.3`):

* ``async_action_dispatcher`` (module-global rebind on
  ``helao.core.servers.orch``) -- records every call as ``(server,
  action_name, ordered params, start_condition, submit_order)`` and returns a
  canned active/finished action dict per the scenario's script. For each
  successful blocking dispatch it also schedules a background "status ping"
  that drives the REAL ``Orch.update_status`` with a canned finished
  ``ActionServerModel`` a couple of event-loop ticks later -- this is what
  unblocks ``dispatch_loop_task``'s own ``action_history`` wait-loop and the
  ``ActionStartCondition`` wait predicates using the REAL status-ingestion
  code, without any real network I/O or real wall-clock waiting.
* ``async_private_dispatcher`` -- no-op recorder returning ``({}, none)``.
* ``HelaoSyncer.to_s3`` -- no-op recorder (``self.syncer.to_s3``).
* ``PLATE_API.has_access`` -- forced ``False`` for the harness's duration
  (module-global on ``helao.core.servers.orch``), so the plate-verification
  gate is a no-op in every scenario, matching spec's fake list.
* ``move_dir`` (module-global rebind) -- recording no-op (no real file
  moves).
* ``write_seq`` / ``write_exp`` / ``put_lbuf`` / ``put_lbuf_nowait`` --
  recording no-ops bound directly on the ``Orch`` instance (shadowing the
  ``Base`` methods, which need real ``helaodirs``/disk paths this harness
  does not set up).

No production code (``helao/core/servers/orch.py`` or any other module under
``helao/core`` or ``helao/helpers``) is modified by this file.

Determinism notes: every trace entry is built from harness-controlled,
deterministic inputs (server/action names, scripted params, submit_order
counters, enum values). Real ``gen_uuid()``/``set_time()`` calls inside the
driven production code (e.g. stamping ``action_uuid``/``action_timestamp`` on
newly unpacked actions) are deliberately never captured verbatim into the
trace -- the harness only ever records fields it authored or that are
structurally deterministic (counts, enum names, ordered dict keys), exactly
as the "ordered decision trace" in spec :sec:`5.3` describes. This avoids
needing to patch ``gen_uuid``/``time.time`` globally the way the PAL harness
pins ``time.time``/``asyncio.sleep`` -- nothing genuinely random ever reaches
``json.dumps``.

One genuine pre-existing quirk (not a harness bug, not to be fixed here; see
spec :sec:`3.1` rule 5 "no behavior fixes ride along"): ``ActionStartCondition
.wait_for_previous`` compares ``self.last_action_uuid`` (a bare *string*,
stamped from the dispatcher's returned JSON dict) against
``self.globalstatusmodel.active_dict.keys()`` (*UUID* objects) -- the type
mismatch means this predicate can never observe a match and therefore never
actually blocks in the current code. Scenario 2 drives this branch and
records the (structurally guaranteed) immediate pass-through faithfully
rather than fabricating a block that cannot occur.

Run (conda env ``helao``; no pytest harness in this repo -- run as a script)::

    conda run -n helao --no-capture-output python \\
        helao/core/tests/test_orch_dispatch_golden_master.py [--check]

Two modes:

* Default (no args) -- record/dev mode: runs the semantic
  ``_run_and_check`` assertions plus a byte-identical double-capture
  determinism check, and (re)writes scratch traces to
  ``.omc/artifacts/p5/baseline/<scenario>.jsonl`` (gitignored) for local
  inspection. This mode never touches ``baseline_S0/``.
* ``--check`` -- the hard per-stage gate run by every downstream stage
  (S1-S9): captures all 9 scenarios to a temp dir and byte-diffs each
  against the FROZEN reference at ``.omc/artifacts/p5/baseline_S0/``,
  printing per-scenario PASS/DELTA and exiting non-zero on any byte
  difference or missing/extra file. It never writes to ``baseline_S0/``.

``.omc/artifacts/p5/baseline_S0/`` is the frozen S0 reference: it was
captured once, on unmodified ``orch.py`` (verified via ``git diff`` against
the S0 commit), and must never be regenerated during S1-S9 -- doing so would
let a stage silently redefine its own gate. A ``queues.pck`` export/import
round-trip fixture is written to ``.omc/artifacts/p5/queues.pck``.
"""

import asyncio
import json
import os
import pickle
import time
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import helao.core.servers.orch as orch_module
import helao.core.servers.orch_monitor as orch_monitor_module
import helao.core.servers.orch_status_sync as orch_status_sync_module
from helao.core.servers.orch import Orch
from helao.core.error import ErrorCodes
from helao.core.models.action_start_condition import ActionStartCondition
from helao.core.models.experiment import ShortExperimentModel
from helao.core.models.hlostatus import HloStatus
from helao.core.models.machine import MachineModel
from helao.core.models.server import ActionServerModel, EndpointModel, GlobalStatusModel
from helao.helpers.dequedict import DequeDict
from helao.helpers.multisubscriber_queue import MultisubscriberQueue
from helao.helpers.premodels import Action, Experiment, Sequence
from helao.helpers.zdeque import zdeque

REPO_ROOT = Path(__file__).resolve().parents[3]
ARTIFACT_DIR = REPO_ROOT / ".omc" / "artifacts" / "p5"
# Frozen S0 reference (captured once, on unmodified orch.py). Never write to
# this directory outside of the one-time freeze step -- it is the hard gate
# every S1-S9 stage's `--check` run diffs against.
BASELINE_S0_DIR = ARTIFACT_DIR / "baseline_S0"
BASELINE_DIR = ARTIFACT_DIR / "baseline"

ORCH_SERVER_NAME = "ORCH"
ORCH_MACHINE = "test-machine"


def _enum_val(value):
    """Return an enum's ``.value``/``.name`` for JSON-safety, else the value itself."""
    if value is None:
        return None
    if hasattr(value, "value"):
        return value.value
    return value


def _json_safe(obj):
    """Recursively coerce enums/UUIDs/etc. into JSON-safe primitives (no randomness)."""
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if hasattr(obj, "value") and not isinstance(obj, (str, int, float, bool)):
        return obj.value
    return obj


# ---------------------------------------------------------------------------
# Orch fixture construction (Base.__init__ bypass, mirrors PAL's PAL.__new__)
# ---------------------------------------------------------------------------


def _make_orch(tmp_root: Path) -> Orch:
    """Build a bare ``Orch`` with every attribute the dispatch cluster touches."""
    orch = Orch.__new__(Orch)
    os.makedirs(str(tmp_root / "STATES"), exist_ok=True)

    orch.server = MachineModel(
        server_name=ORCH_SERVER_NAME,
        machine_name=ORCH_MACHINE,
        hostname="127.0.0.1",
        port=8000,
    )
    orch.server_cfg = {"host": "127.0.0.1", "port": 8000}
    orch.server_params = {}
    orch.world_cfg = {
        "servers": {
            ORCH_SERVER_NAME: {"host": "127.0.0.1", "port": 8000},
            "SRV1": {"host": "127.0.0.1", "port": 8001},
            "SRV2": {"host": "127.0.0.1", "port": 8002},
            "SRV3": {"host": "127.0.0.1", "port": 8003},
        },
        "root": str(tmp_root),
        "dummy": False,
        "simulation": False,
    }
    orch.orch_key = ORCH_SERVER_NAME
    orch.orch_host = "127.0.0.1"
    orch.orch_port = 8000
    orch.run_type = "test"
    orch.helaodirs = SimpleNamespace(
        root=str(tmp_root),
        save_root=str(tmp_root / "RUNS_ACTIVE"),
        log_root=str(tmp_root / "LOGS"),
        user_exp=str(tmp_root),
        user_seq=str(tmp_root),
    )
    orch.ntp_offset = 0.0
    orch.aiolock = asyncio.Lock()

    orch.experiment_lib = {}
    orch.experiment_codehash_lib = {}
    orch.experiment_codepath_lib = {}
    orch.sequence_lib = {}
    orch.sequence_codehash_lib = {}
    orch.sequence_codepath_lib = {}

    orch.use_db = True
    orch.syncer = SimpleNamespace(to_s3=_make_fake_to_s3())

    orch.sequence_dq = zdeque([])
    orch.experiment_dq = zdeque([])
    orch.action_dq = zdeque([])
    orch.dispatch_buffer = []
    orch.nonblocking = []

    orch.last_dispatched_action_uuid = None
    orch.action_history = DequeDict(maxlen=1000)
    orch.experiment_history = DequeDict(maxlen=1000)
    orch.sequence_history = DequeDict(maxlen=1000)
    orch.last_action_uuid = ""
    orch.last_interrupt = time.time()
    orch.active_experiment = None
    orch.last_experiment = None
    orch.active_sequence = None
    orch.active_seq_exp_counter = 0
    orch.last_sequence = None
    orch.active_run_id = None
    orch.heartbeat_interval = 10
    orch.ignore_heartbeats = []
    orch.verify_plates = True

    orch.globalstatusmodel = GlobalStatusModel(orchestrator=orch.server)
    orch.globalstatusmodel._sort_status()
    orch.interrupt_q = asyncio.Queue()
    orch.incoming_status = asyncio.Queue()
    orch.incoming = None

    orch.init_success = False
    orch.loop_task = None
    orch.status_subscriber = None
    orch.globstat_broadcaster = None
    orch.heartbeat_monitor = None
    orch.driver_monitor = None

    orch.wait_task = None
    orch.current_wait_ts = 0
    orch.last_wait_ts = 0

    orch.globstat_q = MultisubscriberQueue()
    orch.globstat_clients = set()
    orch.current_stop_message = ""

    orch.step_thru_actions = False
    orch.step_thru_experiments = False
    orch.step_thru_sequences = False
    orch.status_summary = {}
    orch.global_params = {}

    orch.exp_postprocessors = []
    orch.exp_postprocess_libs = []
    orch.seq_postprocessors = []
    orch.seq_postprocess_libs = []

    orch._init_collaborators()

    return orch


def _make_fake_to_s3():
    async def _to_s3(payload, key):
        return None

    return _to_s3


def _install_recording_stubs(orch: Orch, trace: list) -> None:
    """Shadow Base's disk/live-buffer methods with recording no-ops (spec :sec:`5.3`)."""

    # Note: live_dict is keyed by a real (random) action/experiment/sequence
    # uuid -- never logged verbatim (would break determinism); only the
    # structurally deterministic value payload (name/status) is recorded.
    async def _put_lbuf(live_dict):
        trace.append(
            {
                "event": "put_lbuf",
                "entries": [_json_safe(v) for v in live_dict.values()],
            }
        )

    def _put_lbuf_nowait(live_dict):
        trace.append(
            {
                "event": "put_lbuf_nowait",
                "entries": [_json_safe(v) for v in live_dict.values()],
            }
        )

    async def _write_seq(sequence):
        trace.append({"event": "write_seq", "sequence_name": sequence.sequence_name})

    async def _write_exp(experiment):
        trace.append(
            {"event": "write_exp", "experiment_name": experiment.experiment_name}
        )

    orch.put_lbuf = _put_lbuf
    orch.put_lbuf_nowait = _put_lbuf_nowait
    orch.write_seq = _write_seq
    orch.write_exp = _write_exp


# ---------------------------------------------------------------------------
# spies -- wrap real bound methods to log entry/exit without changing behavior
# ---------------------------------------------------------------------------


def _status_snapshot(orch: Orch) -> dict:
    return {
        "loop_state": _enum_val(orch.globalstatusmodel.loop_state),
        "loop_intent": _enum_val(orch.globalstatusmodel.loop_intent),
        "orch_state": _enum_val(orch.globalstatusmodel.orch_state),
        "seq_dq": len(orch.sequence_dq),
        "exp_dq": len(orch.experiment_dq),
        "act_dq": len(orch.action_dq),
    }


def _wrap_phase(orch: Orch, name: str, trace: list) -> None:
    orig = getattr(orch, name)

    async def _spy():
        trace.append({"event": "phase_enter", "phase": name, **_status_snapshot(orch)})
        result = await orig()
        trace.append(
            {
                "event": "phase_exit",
                "phase": name,
                "error_code": _enum_val(result),
                **_status_snapshot(orch),
            }
        )
        return result

    setattr(orch, name, _spy)


def _wrap_intent(orch: Orch, name: str, trace: list) -> None:
    orig = getattr(orch, name)

    async def _spy():
        trace.append({"event": "intent_call", "method": name})
        return await orig()

    setattr(orch, name, _spy)


def _wrap_estop_loop(orch: Orch, trace: list) -> None:
    orig = orch.estop_loop

    async def _spy(reason=""):
        trace.append({"event": "estop_loop_call", "reason": reason})
        return await orig(reason)

    orch.estop_loop = _spy


def _wrap_stop(orch: Orch, trace: list) -> None:
    orig = orch.stop

    async def _spy(reset_run_id=False):
        trace.append({"event": "stop_call", "reset_run_id": reset_run_id})
        return await orig(reset_run_id)

    orch.stop = _spy


def _wrap_wait_for_interrupt(orch: Orch, trace: list) -> None:
    orig = orch.wait_for_interrupt

    async def _spy(pending_action=None):
        trace.append(
            {
                "event": "wait_for_interrupt_enter",
                "has_pending": pending_action is not None,
            }
        )
        result = await orig(pending_action)
        trace.append({"event": "wait_for_interrupt_exit", "result": result})
        return result

    orch.wait_for_interrupt = _spy


def _wrap_update_nonblocking(orch: Orch, trace: list) -> None:
    orig = orch.update_nonblocking

    async def _spy(actionmodel, server_host, server_port):
        active = "active" in actionmodel.action_status
        trace.append(
            {
                "event": "update_nonblocking",
                "action_name": actionmodel.action_name,
                "active": active,
            }
        )
        return await orig(actionmodel, server_host, server_port)

    orch.update_nonblocking = _spy


def _install_all_spies(orch: Orch, trace: list) -> None:
    for phase in (
        "loop_task_dispatch_sequence",
        "loop_task_dispatch_experiment",
        "loop_task_dispatch_action",
    ):
        _wrap_phase(orch, phase, trace)
    for intent in ("intend_skip", "intend_stop", "intend_estop", "intend_none"):
        _wrap_intent(orch, intent, trace)
    _wrap_estop_loop(orch, trace)
    _wrap_stop(orch, trace)
    _wrap_wait_for_interrupt(orch, trace)
    _wrap_update_nonblocking(orch, trace)


# ---------------------------------------------------------------------------
# fake module-global dispatchers (patched onto helao.core.servers.orch)
# ---------------------------------------------------------------------------


class _PatchedOrchGlobals:
    """Context manager patching the module-globals ``orch.py`` imports by name."""

    def __init__(self, action_dispatcher, private_dispatcher, move_dir_fn):
        self._action_dispatcher = action_dispatcher
        self._private_dispatcher = private_dispatcher
        self._move_dir_fn = move_dir_fn
        self._orig_action_dispatcher = None
        self._orig_private_dispatcher = None
        self._orig_move_dir = None
        self._orig_plate_api = None

    def __enter__(self):
        self._orig_action_dispatcher = orch_module.async_action_dispatcher
        # CARDS P5 relocated the private-dispatch callers out of ``orch``; the
        # symbol now lives in the ServerMonitor / StatusIngester collaborator
        # modules (677c6ca5 dropped the unused ``orch`` import). Patch both so
        # any private dispatch a scenario triggers is stubbed, matching the
        # original network-isolation intent.
        self._orig_private_dispatcher = orch_status_sync_module.async_private_dispatcher
        self._orig_move_dir = orch_module.move_dir
        self._orig_plate_api = orch_module.PLATE_API
        orch_module.async_action_dispatcher = self._action_dispatcher
        orch_status_sync_module.async_private_dispatcher = self._private_dispatcher
        orch_monitor_module.async_private_dispatcher = self._private_dispatcher
        orch_module.move_dir = self._move_dir_fn
        # HTEPlateAPI.has_access is a read-only property; rebind the whole
        # module-global to a minimal fake rather than mutating the singleton.
        orch_module.PLATE_API = SimpleNamespace(has_access=False)
        return self

    def __exit__(self, *exc):
        orch_module.async_action_dispatcher = self._orig_action_dispatcher
        orch_status_sync_module.async_private_dispatcher = self._orig_private_dispatcher
        orch_monitor_module.async_private_dispatcher = self._orig_private_dispatcher
        orch_module.move_dir = self._orig_move_dir
        orch_module.PLATE_API = self._orig_plate_api
        return False


def _make_fake_private_dispatcher(trace: list):
    async def _fake(
        server_key,
        host,
        port,
        private_action,
        params_dict=None,
        json_dict=None,
        **kwargs,
    ):
        trace.append(
            {
                "event": "private_dispatch",
                "server": server_key,
                "action": private_action,
            }
        )
        return {}, ErrorCodes.none

    return _fake


def _make_fake_move_dir(trace: list):
    async def _fake(hobj, base=None, retry_delay=5):
        kind = (
            "sequence"
            if hasattr(hobj, "sequence_uuid") and not hasattr(hobj, "experiment_uuid")
            else (
                "experiment"
                if hasattr(hobj, "experiment_uuid") and hobj.experiment_uuid is not None
                else "unknown"
            )
        )
        trace.append({"event": "move_dir", "kind": kind})
        return None

    return _fake


async def _deliver_finish_status(
    orch: Orch,
    finished_action: Action,
    server_host: str,
    server_port: int,
    is_nonblocking: bool,
    trace: list,
    ticks: int = 2,
) -> None:
    """Background task: deliver a canned 'finished' status ping via the REAL update_status."""
    for _ in range(ticks):
        await asyncio.sleep(0)
    endpoint_name = finished_action.action_name
    asm = ActionServerModel(
        action_server=finished_action.action_server,
        endpoints={
            endpoint_name: EndpointModel(
                endpoint_name=endpoint_name,
                nonactive_dict={
                    HloStatus.finished: {finished_action.action_uuid: finished_action}
                },
            )
        },
        last_action_uuid=finished_action.action_uuid,
    )
    trace.append(
        {"event": "status_ping", "action_name": endpoint_name, "phase": "finished"}
    )
    await orch.update_status(asm)
    if is_nonblocking:
        await orch.update_nonblocking(
            finished_action.get_act(), server_host, server_port
        )


def make_fake_action_dispatcher(orch: Orch, trace: list, script: Optional[dict] = None):
    """Build the scripted ``async_action_dispatcher`` fake (spec :sec:`5.3`).

    ``script`` maps ``action_name -> directive dict``:
      - ``dispatch_error_code``: ErrorCodes to return as the dispatch-level error
        (simulates transport failure; the canned action dict is discarded).
      - ``result_error_code``: ErrorCodes stamped onto the returned Action itself
        (simulates a successful dispatch whose result carries an error).
      - ``action_output``: dict merged into the returned action's action_output.
      - ``skip_ping``: bool, suppress the background "finished" status delivery.
    """
    script = script or {}
    call_counters: dict = {}

    async def _fake_async_action_dispatcher(
        world_cfg, A: Action, params: Optional[dict] = None
    ):
        name = A.action_name
        call_counters[name] = call_counters.get(name, 0) + 1
        directive = script.get(name, {})

        trace.append(
            {
                "event": "dispatch_call",
                "server": A.action_server.server_name,
                "action_name": name,
                "params": _json_safe(dict(A.action_params)),
                "start_condition": (
                    A.start_condition
                    if isinstance(A.start_condition, int)
                    and not isinstance(A.start_condition, ActionStartCondition)
                    else _enum_val(A.start_condition)
                ),
                "submit_order": A.orch_submit_order,
                "nonblocking": A.nonblocking,
                "extra_params": _json_safe(dict(params)) if params else {},
            }
        )

        dispatch_error_code = directive.get("dispatch_error_code")
        if dispatch_error_code is not None:
            return None, dispatch_error_code

        resp = deepcopy(A)
        if resp.start_condition not in ActionStartCondition.__members__.values():
            # An unsupported/raw start_condition value (scenario 2's fallback
            # case) only governs the orchestrator's OWN pre-dispatch wait
            # decision; a real action-server response model would not echo
            # back an invalid enum member, so the canned response normalizes
            # it rather than round-tripping the invalid value.
            resp.start_condition = ActionStartCondition.wait_for_all
        resp.action_status = [HloStatus.active]
        resp.error_code = directive.get("result_error_code", ErrorCodes.none)
        if "action_output" in directive:
            resp.action_output = dict(directive["action_output"])

        host = A.action_server.hostname or "127.0.0.1"
        port = A.action_server.port or 0

        if A.nonblocking:
            await orch.update_nonblocking(resp.get_act(), host, port)

        # A finished/errored status ping is delivered regardless of whether
        # the RETURNED action carries an error_code -- a real action server
        # eventually reports a terminal status for every action it accepted
        # (dispatch_loop_task's own action_history wait-loop, unconditional
        # on any action_dq turn, would otherwise hang on `None`/an
        # unregistered uuid; see scenario 5/6/7 comments). Only an explicit
        # script directive suppresses it (used to keep a seeded occupancy
        # genuinely blocking for a scenario-controlled duration).
        # `estop_actions`'s broadcast "estop" action never carries a uuid (it
        # is not routed through loop_task_dispatch_action/init_act, so real
        # production code never expects a status ping for it either) --
        # never schedule a ping for it.
        skip_ping = directive.get("skip_ping", False) or resp.action_uuid is None
        if not skip_ping:
            finished = deepcopy(resp)
            finished.action_status = [
                HloStatus.finished
            ]  # replaces active, matches real replace-status semantics
            if orch.active_experiment is not None:
                finished.experiment_uuid = orch.active_experiment.experiment_uuid
            orch.aloop.create_task(
                _deliver_finish_status(orch, finished, host, port, A.nonblocking, trace)
            )

        return resp.as_dict(), ErrorCodes.none

    return _fake_async_action_dispatcher


# ---------------------------------------------------------------------------
# server_dict seeding (real code indexes server_dict[key].endpoints[name]
# unconditionally on first self-registration -- must pre-exist)
# ---------------------------------------------------------------------------


def _seed_server_dict(orch: Orch, pairs) -> None:
    """Pre-register an empty ``ActionServerModel``/``EndpointModel`` per (server, action_name)."""
    for server_name, action_name in pairs:
        key = (server_name, ORCH_MACHINE)
        if key not in orch.globalstatusmodel.server_dict:
            orch.globalstatusmodel.server_dict[key] = ActionServerModel(
                action_server=MachineModel(
                    server_name=server_name,
                    machine_name=ORCH_MACHINE,
                    hostname="127.0.0.1",
                    port=1,
                )
            )
        asm = orch.globalstatusmodel.server_dict[key]
        if action_name not in asm.endpoints:
            asm.endpoints[action_name] = EndpointModel(endpoint_name=action_name)


def _seed_active_action(
    orch: Orch, server_name: str, endpoint_name: str, tag: str
) -> Action:
    """Insert a fake 'currently active' action to make a start-condition wait genuinely block."""
    import uuid as _uuid_mod
    from datetime import datetime as _dt

    a = Action(
        action_name=endpoint_name,
        action_uuid=_uuid_mod.uuid4(),
        action_timestamp=_dt.now(),
        experiment_uuid=_uuid_mod.uuid4(),
        action_server=MachineModel(
            server_name=server_name,
            machine_name=ORCH_MACHINE,
            hostname="127.0.0.1",
            port=1,
        ),
        orchestrator=orch.server,
        action_status=[HloStatus.active],
        action_params={"_seed_tag": tag},
    )
    _seed_server_dict(orch, [(server_name, endpoint_name)])
    key = (server_name, ORCH_MACHINE)
    orch.globalstatusmodel.server_dict[key].endpoints[endpoint_name].active_dict[
        a.action_uuid
    ] = a
    orch.globalstatusmodel.active_dict[a.action_uuid] = a
    return a


def _schedule_clear_active(
    orch: Orch, seeded: Action, trace: list, ticks: int = 2
) -> None:
    """Background task: deliver a 'finished' status for a previously-seeded fake active action."""

    async def _clear():
        for _ in range(ticks):
            await asyncio.sleep(0)
        finished = deepcopy(seeded)
        finished.action_status = [
            HloStatus.finished
        ]  # replaces active, matches real replace-status semantics
        asm = ActionServerModel(
            action_server=finished.action_server,
            endpoints={
                finished.action_name: EndpointModel(
                    endpoint_name=finished.action_name,
                    nonactive_dict={
                        HloStatus.finished: {finished.action_uuid: finished}
                    },
                )
            },
            last_action_uuid=finished.action_uuid,
        )
        trace.append(
            {
                "event": "status_ping",
                "action_name": finished.action_name,
                "phase": "seed_cleared",
            }
        )
        await orch.update_status(asm)

    orch.aloop.create_task(_clear())


# ---------------------------------------------------------------------------
# experiment/sequence library helpers (generic, reused across scenarios)
# ---------------------------------------------------------------------------


def _plan_action(
    experiment: Experiment,
    action_server: str,
    action_name: str,
    action_params: dict,
    **kwargs,
) -> Action:
    """Mirror ``ActionPlanMaker.add``'s construction exactly (proven production pattern)."""
    action_dict = experiment.as_dict()
    action_dict.update(
        {
            "action_server": MachineModel(
                server_name=action_server, machine_name=ORCH_MACHINE
            ).as_dict(),
            "action_name": action_name,
            "action_params": action_params,
            "start_condition": kwargs.pop(
                "start_condition", ActionStartCondition.no_wait
            ),
            "to_global_params": kwargs.pop("to_global_params", []),
            "from_global_act_params": kwargs.pop("from_global_act_params", {}),
        }
    )
    action_dict.update(kwargs)
    return Action.model_validate(action_dict)


def _generic_experiment(experiment: Experiment, actions_spec=None):
    out = []
    for spec in actions_spec or []:
        spec = dict(spec)
        server = spec.pop("server")
        name = spec.pop("name")
        params = spec.pop("params", {})
        out.append(_plan_action(experiment, server, name, params, **spec))
    return out


def _generic_sequence(experiments_spec=None):
    out = []
    for spec in experiments_spec or []:
        out.append(
            ShortExperimentModel(
                experiment_name=spec["experiment_name"],
                experiment_params=spec.get("experiment_params", {}),
                from_global_exp_params=spec.get("from_global_exp_params", {}),
            )
        )
    return out


def _install_generic_libs(orch: Orch) -> None:
    orch.experiment_lib = {"generic_exp": _generic_experiment}
    orch.experiment_codehash_lib = {"generic_exp": "deadbeef"}
    orch.experiment_codepath_lib = {"generic_exp": "harness://generic_exp"}
    orch.sequence_lib = {"generic_seq": _generic_sequence}
    orch.sequence_codehash_lib = {"generic_seq": "deadbeef"}
    orch.sequence_codepath_lib = {"generic_seq": "harness://generic_seq"}


def _mk_sequence(experiments_spec) -> Sequence:
    seq = Sequence(
        sequence_name="generic_seq",
        sequence_params={"experiments_spec": experiments_spec},
    )
    return seq


def _bare_action(
    orch: Orch, server_name: str, action_name: str, action_params: dict, **kwargs
) -> Action:
    """Directly-constructed standalone action (bypasses experiment unpacking) for scenarios
    that drive ``loop_task_dispatch_action``/``wait_for_interrupt`` directly."""
    a = Action(
        action_name=action_name,
        action_params=action_params,
        action_server=MachineModel(
            server_name=server_name,
            machine_name=ORCH_MACHINE,
            hostname="127.0.0.1",
            port=1,
        ),
        orchestrator=orch.server,
        **kwargs,
    )
    return a


async def _run_all_ticks(n: int = 3) -> None:
    for _ in range(n):
        await asyncio.sleep(0)


async def _drain(orch: Orch) -> None:
    """Await dispatch_loop_task; also let any trailing background tasks flush."""
    await orch.dispatch_loop_task()
    await _run_all_ticks(5)


# ---------------------------------------------------------------------------
# scenario 1: plain 2-experiment sequence, all no_wait
# ---------------------------------------------------------------------------


async def _scenario_1(tmp_root: Path) -> dict:
    trace: list = []
    orch = _make_orch(tmp_root / "s1")
    _install_recording_stubs(orch, trace)
    _install_generic_libs(orch)
    orch.aloop = asyncio.get_running_loop()
    _install_all_spies(orch, trace)

    _seed_server_dict(orch, [("SRV1", "act_a"), ("SRV1", "act_b"), ("SRV2", "act_c")])

    seq = _mk_sequence(
        [
            {
                "experiment_name": "generic_exp",
                "experiment_params": {
                    "actions_spec": [
                        {"server": "SRV1", "name": "act_a", "params": {"x": 1}},
                        {"server": "SRV1", "name": "act_b", "params": {"y": 2}},
                    ]
                },
            },
            {
                "experiment_name": "generic_exp",
                "experiment_params": {
                    "actions_spec": [
                        {"server": "SRV2", "name": "act_c", "params": {"z": 3}},
                    ]
                },
            },
        ]
    )
    await orch.add_sequence(seq)

    fake_dispatcher = make_fake_action_dispatcher(orch, trace, script={})
    with _PatchedOrchGlobals(
        fake_dispatcher,
        _make_fake_private_dispatcher(trace),
        _make_fake_move_dir(trace),
    ):
        await _drain(orch)

    final = {
        "loop_state": _enum_val(orch.globalstatusmodel.loop_state),
        "seq_dq": len(orch.sequence_dq),
        "exp_dq": len(orch.experiment_dq),
        "act_dq": len(orch.action_dq),
        "dispatch_calls": [e for e in trace if e.get("event") == "dispatch_call"],
    }
    return {"trace": trace, "final": final}


# ---------------------------------------------------------------------------
# scenario 2: every ActionStartCondition member incl. unsupported fallback
# ---------------------------------------------------------------------------


async def _scenario_2(tmp_root: Path) -> dict:
    trace: list = []
    orch = _make_orch(tmp_root / "s2")
    _install_recording_stubs(orch, trace)
    orch.aloop = asyncio.get_running_loop()
    _install_all_spies(orch, trace)

    exp = Experiment(experiment_name="direct_exp")
    exp.init_exp()
    exp.orchestrator = orch.server
    orch.active_experiment = exp
    orch.globalstatusmodel.new_experiment(exp_uuid=exp.experiment_uuid)

    fake_dispatcher = make_fake_action_dispatcher(orch, trace, script={})

    conditions = [
        ("cond_no_wait", "SRV1", ActionStartCondition.no_wait, False),
        ("cond_wait_endpoint", "SRV1", ActionStartCondition.wait_for_endpoint, True),
        ("cond_wait_server", "SRV1", ActionStartCondition.wait_for_server, True),
        ("cond_wait_orch", ORCH_SERVER_NAME, ActionStartCondition.wait_for_orch, True),
        ("cond_wait_previous", "SRV2", ActionStartCondition.wait_for_previous, False),
        ("cond_wait_all", "SRV2", ActionStartCondition.wait_for_all, True),
        ("cond_unsupported", "SRV3", None, True),
    ]

    with _PatchedOrchGlobals(
        fake_dispatcher,
        _make_fake_private_dispatcher(trace),
        _make_fake_move_dir(trace),
    ):
        for action_name, server_name, condition, seed_block in conditions:
            endpoint_for_block = (
                "wait"
                if condition == ActionStartCondition.wait_for_orch
                else action_name
            )
            block_server = (
                orch.server.server_name
                if condition == ActionStartCondition.wait_for_orch
                else server_name
            )
            seeded = None
            if seed_block:
                seeded = _seed_active_action(
                    orch, block_server, endpoint_for_block, tag=action_name
                )
                _schedule_clear_active(orch, seeded, trace)

            _seed_server_dict(orch, [(server_name, action_name)])
            a = _bare_action(orch, server_name, action_name, {"n": action_name})
            if condition is None:
                # Inject an out-of-range value to exercise the dispatch
                # else-branch fallback. ``Action`` now enables
                # ``validate_assignment`` (7ee179e8), which rejects a raw ``99``
                # on normal assignment, so bypass the validator to plant the
                # unsupported value the same way the pre-validation harness did.
                object.__setattr__(a, "start_condition", 99)
            else:
                a.start_condition = condition
            orch.action_dq.append(a)

            trace.append(
                {
                    "event": "scenario2_condition",
                    "action_name": action_name,
                    "condition": condition.value if condition else 99,
                }
            )
            error_code = await orch.loop_task_dispatch_action()
            trace.append(
                {
                    "event": "scenario2_result",
                    "action_name": action_name,
                    "error_code": _enum_val(error_code),
                }
            )

    final = {
        "act_dq": len(orch.action_dq),
        "dispatch_calls": [e for e in trace if e.get("event") == "dispatch_call"],
    }
    return {"trace": trace, "final": final}


# ---------------------------------------------------------------------------
# scenario 3: to_global_params list-form + dict-form -> next action fold-in
# ---------------------------------------------------------------------------


async def _scenario_3(tmp_root: Path) -> dict:
    trace: list = []
    orch = _make_orch(tmp_root / "s3")
    _install_recording_stubs(orch, trace)
    _install_generic_libs(orch)
    orch.aloop = asyncio.get_running_loop()
    _install_all_spies(orch, trace)

    _seed_server_dict(
        orch,
        [
            ("SRV1", "act_produce_list"),
            ("SRV1", "act_consume_list"),
            ("SRV1", "act_produce_dict"),
            ("SRV1", "act_consume_dict"),
        ],
    )

    seq = _mk_sequence(
        [
            {
                "experiment_name": "generic_exp",
                "experiment_params": {
                    "actions_spec": [
                        {
                            "server": "SRV1",
                            "name": "act_produce_list",
                            "params": {},
                            "to_global_params": ["outkey"],
                        },
                        {
                            "server": "SRV1",
                            "name": "act_consume_list",
                            "params": {},
                            "from_global_act_params": {"outkey": "injected_param"},
                            "to_global_params": {"local_output_key": "gp_dict_key"},
                        },
                        {
                            "server": "SRV1",
                            "name": "act_consume_dict",
                            "params": {},
                            "from_global_act_params": {
                                "gp_dict_key": "injected_param2"
                            },
                        },
                    ]
                },
            },
        ]
    )
    await orch.add_sequence(seq)

    script = {
        "act_produce_list": {"action_output": {"outkey": "VAL1"}},
        "act_consume_list": {"action_output": {"local_output_key": "VAL2"}},
    }
    fake_dispatcher = make_fake_action_dispatcher(orch, trace, script=script)
    with _PatchedOrchGlobals(
        fake_dispatcher,
        _make_fake_private_dispatcher(trace),
        _make_fake_move_dir(trace),
    ):
        await _drain(orch)

    dispatch_calls = [e for e in trace if e.get("event") == "dispatch_call"]
    final = {
        "loop_state": _enum_val(orch.globalstatusmodel.loop_state),
        "dispatch_calls": dispatch_calls,
        "final_global_params": _json_safe(dict(orch.global_params)),
    }
    return {"trace": trace, "final": final}


# ---------------------------------------------------------------------------
# scenario 4: LoopIntent.stop mid-wait -> pending-action requeue via
# wait_for_interrupt (driven directly -- no current call site passes
# pending_action, see module docstring)
# ---------------------------------------------------------------------------


async def _scenario_4(tmp_root: Path) -> dict:
    trace: list = []
    orch = _make_orch(tmp_root / "s4")
    _install_recording_stubs(orch, trace)
    orch.aloop = asyncio.get_running_loop()
    _install_all_spies(orch, trace)

    other = _bare_action(orch, "SRV1", "other_queued", {})
    orch.action_dq.append(other)

    pending = _bare_action(orch, "SRV1", "pending_action", {})

    await orch.intend_stop()
    await orch.interrupt_q.put("operator_stop_signal")

    result = await orch.wait_for_interrupt(pending_action=pending)

    final = {
        "wait_for_interrupt_result": result,
        "act_dq_len": len(orch.action_dq),
        "act_dq_front_is_pending": (
            len(orch.action_dq) > 0
            and orch.action_dq[0].action_name == "pending_action"
        ),
        "loop_intent": _enum_val(orch.globalstatusmodel.loop_intent),
    }
    return {"trace": trace, "final": final}


# ---------------------------------------------------------------------------
# scenario 5: LoopIntent.skip
# ---------------------------------------------------------------------------


async def _scenario_5(tmp_root: Path) -> dict:
    trace: list = []
    orch = _make_orch(tmp_root / "s5")
    _install_recording_stubs(orch, trace)
    _install_generic_libs(orch)
    orch.aloop = asyncio.get_running_loop()
    _install_all_spies(orch, trace)

    _seed_server_dict(
        orch,
        [
            ("SRV1", "act_prime"),
            ("SRV1", "act_skip_1"),
            ("SRV1", "act_skip_2"),
            ("SRV1", "act_skip_3"),
        ],
    )

    # A priming experiment dispatches (and fully completes) one real action
    # first, so `last_dispatched_action_uuid` is already registered in
    # `action_history` by the time skip fires -- otherwise (a skip as the
    # very first thing an orchestrator does in its process lifetime, before
    # ever dispatching anything) dispatch_loop_task's own post-dispatch wait
    # loop (`while last_dispatched_action_uuid not in action_history.keys()`)
    # spins forever on `None`, since skip never calls track_action_uuid. That
    # is a real, pre-existing property of the unmodified code (not something
    # this harness fabricates or is required to exercise/fix here), so the
    # scenario simply avoids the degenerate ordering rather than hang on it.
    seq = _mk_sequence(
        [
            {
                "experiment_name": "generic_exp",
                "experiment_params": {
                    "actions_spec": [
                        {"server": "SRV1", "name": "act_prime", "params": {}},
                    ]
                },
            },
            {
                "experiment_name": "generic_exp",
                "experiment_params": {
                    "actions_spec": [
                        {"server": "SRV1", "name": "act_skip_1", "params": {}},
                        {"server": "SRV1", "name": "act_skip_2", "params": {}},
                        {"server": "SRV1", "name": "act_skip_3", "params": {}},
                    ]
                },
            },
        ]
    )
    await orch.add_sequence(seq)

    # one-shot hook: right after the SECOND experiment is unpacked (action_dq
    # populated with the act_skip_* trio), request a skip before any of them
    # actually dispatches.
    orig_exp_phase = orch.loop_task_dispatch_experiment
    _exp_call_count = {"n": 0}

    async def _exp_then_skip():
        result = await orig_exp_phase()
        _exp_call_count["n"] += 1
        if _exp_call_count["n"] == 2:
            await orch.intend_skip()
        return result

    orch.loop_task_dispatch_experiment = _exp_then_skip

    fake_dispatcher = make_fake_action_dispatcher(orch, trace, script={})
    with _PatchedOrchGlobals(
        fake_dispatcher,
        _make_fake_private_dispatcher(trace),
        _make_fake_move_dir(trace),
    ):
        await _drain(orch)

    dispatch_calls = [e for e in trace if e.get("event") == "dispatch_call"]
    final = {
        "loop_state": _enum_val(orch.globalstatusmodel.loop_state),
        "act_dq": len(orch.action_dq),
        "dispatch_calls_count": len(dispatch_calls),
    }
    return {"trace": trace, "final": final}


# ---------------------------------------------------------------------------
# scenario 6: dispatch failure (error_code != none) -> pause + front-requeue
# ---------------------------------------------------------------------------


async def _scenario_6(tmp_root: Path) -> dict:
    trace: list = []
    orch = _make_orch(tmp_root / "s6")
    _install_recording_stubs(orch, trace)
    _install_generic_libs(orch)
    orch.aloop = asyncio.get_running_loop()
    _install_all_spies(orch, trace)

    _seed_server_dict(
        orch,
        [
            ("SRV1", "act_prime"),
            ("SRV1", "act_will_fail"),
            ("SRV1", "act_never_reached"),
        ],
    )

    # a priming action dispatches+completes first for the same reason as
    # scenario 5 (see its comment): a dispatch-level failure never calls
    # track_action_uuid, so `last_dispatched_action_uuid` must already be a
    # registered uuid or dispatch_loop_task's post-dispatch wait-loop hangs.
    seq = _mk_sequence(
        [
            {
                "experiment_name": "generic_exp",
                "experiment_params": {
                    "actions_spec": [
                        {"server": "SRV1", "name": "act_prime", "params": {}},
                        {"server": "SRV1", "name": "act_will_fail", "params": {}},
                        {"server": "SRV1", "name": "act_never_reached", "params": {}},
                    ]
                },
            },
        ]
    )
    await orch.add_sequence(seq)

    script = {"act_will_fail": {"dispatch_error_code": ErrorCodes.http}}
    fake_dispatcher = make_fake_action_dispatcher(orch, trace, script=script)
    with _PatchedOrchGlobals(
        fake_dispatcher,
        _make_fake_private_dispatcher(trace),
        _make_fake_move_dir(trace),
    ):
        await _drain(orch)

    dispatch_calls = [e for e in trace if e.get("event") == "dispatch_call"]
    final = {
        "loop_state": _enum_val(orch.globalstatusmodel.loop_state),
        "act_dq": len(orch.action_dq),
        "act_dq_front": orch.action_dq[0].action_name if orch.action_dq else None,
        "dispatch_calls": dispatch_calls,
        "current_stop_message_set": bool(orch.current_stop_message),
    }
    return {"trace": trace, "final": final}


# ---------------------------------------------------------------------------
# scenario 7: returned-action error_code -> estop_loop path
# ---------------------------------------------------------------------------


async def _scenario_7(tmp_root: Path) -> dict:
    trace: list = []
    orch = _make_orch(tmp_root / "s7")
    _install_recording_stubs(orch, trace)
    _install_generic_libs(orch)
    orch.aloop = asyncio.get_running_loop()
    _install_all_spies(orch, trace)

    _seed_server_dict(orch, [("SRV1", "act_bad_result"), (ORCH_SERVER_NAME, "estop")])

    seq = _mk_sequence(
        [
            {
                "experiment_name": "generic_exp",
                "experiment_params": {
                    "actions_spec": [
                        {"server": "SRV1", "name": "act_bad_result", "params": {}},
                    ]
                },
            },
        ]
    )
    await orch.add_sequence(seq)

    script = {"act_bad_result": {"result_error_code": ErrorCodes.critical_error}}
    fake_dispatcher = make_fake_action_dispatcher(orch, trace, script=script)
    with _PatchedOrchGlobals(
        fake_dispatcher,
        _make_fake_private_dispatcher(trace),
        _make_fake_move_dir(trace),
    ):
        await _drain(orch)

    dispatch_calls = [e for e in trace if e.get("event") == "dispatch_call"]
    estop_calls = [e for e in dispatch_calls if e["action_name"] == "estop"]
    final = {
        "loop_state": _enum_val(orch.globalstatusmodel.loop_state),
        "dispatch_calls": dispatch_calls,
        "estop_dispatch_count": len(estop_calls),
        "estop_loop_called": any(e.get("event") == "estop_loop_call" for e in trace),
    }
    return {"trace": trace, "final": final}


# ---------------------------------------------------------------------------
# scenario 8: nonblocking action lifecycle
# ---------------------------------------------------------------------------


async def _scenario_8(tmp_root: Path) -> dict:
    trace: list = []
    orch = _make_orch(tmp_root / "s8")
    _install_recording_stubs(orch, trace)
    _install_generic_libs(orch)
    orch.aloop = asyncio.get_running_loop()
    _install_all_spies(orch, trace)

    _seed_server_dict(orch, [("SRV1", "act_nonblocking"), ("SRV1", "act_after")])

    seq = _mk_sequence(
        [
            {
                "experiment_name": "generic_exp",
                "experiment_params": {
                    "actions_spec": [
                        {
                            "server": "SRV1",
                            "name": "act_nonblocking",
                            "params": {},
                            "nonblocking": True,
                        },
                        {"server": "SRV1", "name": "act_after", "params": {}},
                    ]
                },
            },
        ]
    )
    await orch.add_sequence(seq)

    fake_dispatcher = make_fake_action_dispatcher(orch, trace, script={})
    with _PatchedOrchGlobals(
        fake_dispatcher,
        _make_fake_private_dispatcher(trace),
        _make_fake_move_dir(trace),
    ):
        await _drain(orch)

    nb_events = [e for e in trace if e.get("event") == "update_nonblocking"]
    final = {
        "loop_state": _enum_val(orch.globalstatusmodel.loop_state),
        "nonblocking_list_final_len": len(orch.nonblocking),
        "nonblocking_events": nb_events,
        "act_dq": len(orch.action_dq),
    }
    return {"trace": trace, "final": final}


# ---------------------------------------------------------------------------
# scenario 9: step-thru flags (actions, then experiments)
# ---------------------------------------------------------------------------


async def _scenario_9(tmp_root: Path) -> dict:
    trace: list = []
    result = {}

    # -- 9a: step_thru_actions ------------------------------------------------
    orch = _make_orch(tmp_root / "s9a")
    _install_recording_stubs(orch, trace)
    _install_generic_libs(orch)
    orch.aloop = asyncio.get_running_loop()
    _install_all_spies(orch, trace)
    orch.step_thru_actions = True

    _seed_server_dict(orch, [("SRV1", "act_step_1"), ("SRV1", "act_step_2")])
    seq = _mk_sequence(
        [
            {
                "experiment_name": "generic_exp",
                "experiment_params": {
                    "actions_spec": [
                        {"server": "SRV1", "name": "act_step_1", "params": {}},
                        {"server": "SRV1", "name": "act_step_2", "params": {}},
                    ]
                },
            },
        ]
    )
    await orch.add_sequence(seq)
    fake_dispatcher = make_fake_action_dispatcher(orch, trace, script={})
    with _PatchedOrchGlobals(
        fake_dispatcher,
        _make_fake_private_dispatcher(trace),
        _make_fake_move_dir(trace),
    ):
        await _drain(orch)
    dispatch_calls_a = [e for e in trace if e.get("event") == "dispatch_call"]
    result["step_thru_actions"] = {
        "loop_state": _enum_val(orch.globalstatusmodel.loop_state),
        "act_dq": len(orch.action_dq),
        "dispatch_calls_count": len(dispatch_calls_a),
    }

    # -- 9b: step_thru_experiments ---------------------------------------------
    trace2: list = []
    orch2 = _make_orch(tmp_root / "s9b")
    _install_recording_stubs(orch2, trace2)
    _install_generic_libs(orch2)
    orch2.aloop = asyncio.get_running_loop()
    _install_all_spies(orch2, trace2)
    orch2.step_thru_experiments = True

    _seed_server_dict(orch2, [("SRV1", "act_exp1"), ("SRV1", "act_exp2")])
    seq2 = _mk_sequence(
        [
            {
                "experiment_name": "generic_exp",
                "experiment_params": {
                    "actions_spec": [
                        {"server": "SRV1", "name": "act_exp1", "params": {}}
                    ]
                },
            },
            {
                "experiment_name": "generic_exp",
                "experiment_params": {
                    "actions_spec": [
                        {"server": "SRV1", "name": "act_exp2", "params": {}}
                    ]
                },
            },
        ]
    )
    await orch2.add_sequence(seq2)
    fake_dispatcher2 = make_fake_action_dispatcher(orch2, trace2, script={})
    with _PatchedOrchGlobals(
        fake_dispatcher2,
        _make_fake_private_dispatcher(trace2),
        _make_fake_move_dir(trace2),
    ):
        await _drain(orch2)
    dispatch_calls_b = [e for e in trace2 if e.get("event") == "dispatch_call"]
    result["step_thru_experiments"] = {
        "loop_state": _enum_val(orch2.globalstatusmodel.loop_state),
        "exp_dq": len(orch2.experiment_dq),
        "act_dq": len(orch2.action_dq),
        "dispatch_calls_count": len(dispatch_calls_b),
    }

    combined_trace = (
        [{"event": "section", "name": "step_thru_actions"}]
        + trace
        + [{"event": "section", "name": "step_thru_experiments"}]
        + trace2
    )
    return {"trace": combined_trace, "final": result}


SCENARIOS = {
    "1_plain_two_experiment_sequence_no_wait": _scenario_1,
    "2_every_action_start_condition": _scenario_2,
    "3_to_global_params_list_and_dict_fold_in": _scenario_3,
    "4_loop_intent_stop_pending_requeue": _scenario_4,
    "5_loop_intent_skip": _scenario_5,
    "6_dispatch_failure_pause_requeue": _scenario_6,
    "7_returned_action_error_estop_loop": _scenario_7,
    "8_nonblocking_action_lifecycle": _scenario_8,
    "9_step_thru_flags": _scenario_9,
}


async def run_all_scenarios(base_dir: Path, tmp_root: Path) -> dict:
    # Guard rail: nothing in this harness may write into the frozen S0
    # reference. It is captured exactly once (on unmodified orch.py) and
    # every subsequent run only ever reads it for comparison.
    assert base_dir.resolve() != BASELINE_S0_DIR.resolve(), (
        "refusing to write into the frozen baseline_S0/ reference; "
        "use a scratch directory instead"
    )
    base_dir.mkdir(parents=True, exist_ok=True)
    results = {}
    for name, coro_fn in SCENARIOS.items():
        data = await coro_fn(tmp_root / name)
        payload = {"scenario": name, **data}
        text = json.dumps(payload, indent=2, sort_keys=True, default=str)
        (base_dir / f"{name}.jsonl").write_text(text)
        results[name] = text
    return results


# ---------------------------------------------------------------------------
# queues.pck export/import round-trip fixture (uses the CURRENT, unmodified
# export_queues/import_queues -- pins cross-stage pickle compatibility)
# ---------------------------------------------------------------------------


async def capture_queues_pck_fixture(tmp_root: Path) -> dict:
    trace: list = []
    orch = _make_orch(tmp_root / "pck_export")
    _install_recording_stubs(orch, trace)
    _install_generic_libs(orch)
    orch.aloop = asyncio.get_running_loop()

    os.makedirs(os.path.join(orch.world_cfg["root"], "STATES"), exist_ok=True)

    seq = _mk_sequence(
        [
            {
                "experiment_name": "generic_exp",
                "experiment_params": {
                    "actions_spec": [
                        {"server": "SRV1", "name": "act_pck", "params": {"k": "v"}}
                    ]
                },
            },
        ]
    )
    await orch.add_sequence(seq)
    # a second, still-queued sequence so seq_dq is non-empty at export time
    seq2 = _mk_sequence(
        [
            {
                "experiment_name": "generic_exp",
                "experiment_params": {
                    "actions_spec": [
                        {"server": "SRV1", "name": "act_pck2", "params": {}}
                    ]
                },
            },
        ]
    )
    await orch.add_sequence(seq2)

    export_path = orch.export_queues(timestamp_pck=False)
    exported_ok = os.path.exists(export_path)

    with open(export_path, "rb") as f:
        raw = pickle.load(f)
    expected_keys = {
        "seq",
        "exp",
        "act",
        "active_exp",
        "last_exp",
        "active_seq",
        "last_seq",
        "active_counter",
        "last_act",
        "last_dispatched_act",
        "globalstatusmodel",
        "action_history",
        "experiment_history",
        "sequence_history",
    }
    keys_match = expected_keys.issubset(set(raw.keys()))

    # round-trip: fresh orch imports the same pck
    orch2 = _make_orch(tmp_root / "pck_import")
    _install_recording_stubs(orch2, [])
    _install_generic_libs(orch2)
    orch2.aloop = asyncio.get_running_loop()
    imported_path = orch2.import_queues(pck_path=export_path)
    restored_ok = len(orch2.sequence_dq) == len(orch.sequence_dq) == 2

    # persist a canonical copy under the artifact dir for the S1-S9 gates
    artifact_pck = ARTIFACT_DIR / "queues.pck"
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    with open(export_path, "rb") as src, open(artifact_pck, "wb") as dst:
        dst.write(src.read())

    return {
        "export_path": export_path,
        "exported_ok": exported_ok,
        "keys_match": keys_match,
        "restored_ok": restored_ok,
        "artifact_path": str(artifact_pck),
    }


# ---------------------------------------------------------------------------
# assertions + main
# ---------------------------------------------------------------------------


def _check(cond, msg, failures):
    if not cond:
        failures.append(msg)


def _diff_against_baseline_s0(captured: dict) -> list:
    """Byte-diff each freshly captured scenario trace against the frozen
    ``baseline_S0/`` reference. Returns a list of (scenario_name, status,
    detail) tuples; status is one of PASS / DELTA / MISSING_S0_REFERENCE.
    Also reports any extra ``*.jsonl`` files under baseline_S0/ that no
    longer correspond to a current scenario (stale reference)."""
    expected_files = {f"{name}.jsonl" for name in SCENARIOS}
    s0_files = (
        {p.name for p in BASELINE_S0_DIR.glob("*.jsonl")}
        if BASELINE_S0_DIR.is_dir()
        else set()
    )

    results = []
    for name in SCENARIOS:
        fname = f"{name}.jsonl"
        if fname not in s0_files:
            results.append(
                (
                    name,
                    "MISSING_S0_REFERENCE",
                    f"{fname} not found under {BASELINE_S0_DIR}",
                )
            )
            continue
        s0_bytes = (BASELINE_S0_DIR / fname).read_bytes()
        captured_bytes = captured[name].encode("utf-8")
        if captured_bytes == s0_bytes:
            results.append((name, "PASS", None))
        else:
            results.append((name, "DELTA", f"byte diff vs {BASELINE_S0_DIR / fname}"))

    for extra in sorted(s0_files - expected_files):
        results.append(
            (
                extra,
                "EXTRA_S0_REFERENCE",
                f"{extra} under {BASELINE_S0_DIR} has no current scenario",
            )
        )

    return results


def run_check_mode() -> int:
    """Hard gate for S1-S9: capture fresh traces to a throwaway temp dir
    (never overwriting baseline_S0/) and byte-diff every scenario against
    the frozen ``baseline_S0/`` reference. Returns a process exit code
    (0 == all scenarios byte-identical, 1 == any divergence/missing/extra)."""
    import tempfile

    if not BASELINE_S0_DIR.is_dir():
        print(f"FATAL: frozen S0 reference dir missing: {BASELINE_S0_DIR}")
        return 1

    with tempfile.TemporaryDirectory() as capture_dir, tempfile.TemporaryDirectory() as tmp_root:
        captured = asyncio.run(run_all_scenarios(Path(capture_dir), Path(tmp_root)))

    results = _diff_against_baseline_s0(captured)
    any_fail = False
    for name, status, detail in results:
        if status == "PASS":
            print(f"  PASS   {name}")
        else:
            any_fail = True
            print(f"  {status}  {name}: {detail}")

    if any_fail:
        print(f"CHECK FAILED: trace diverged from frozen reference ({BASELINE_S0_DIR})")
        return 1
    print(
        f"CHECK PASSED: all {len(SCENARIOS)} scenarios byte-identical to {BASELINE_S0_DIR}"
    )
    return 0


async def _run_and_check(tmp_root: Path) -> list:
    failures = []

    r1 = await _scenario_1(tmp_root / "chk1")
    _check(
        r1["final"]["loop_state"] == "stopped",
        "s1: loop did not stop cleanly",
        failures,
    )
    _check(
        r1["final"]["seq_dq"] == 0
        and r1["final"]["exp_dq"] == 0
        and r1["final"]["act_dq"] == 0,
        "s1: queues not drained",
        failures,
    )
    _check(
        len(r1["final"]["dispatch_calls"]) == 3,
        "s1: expected 3 dispatch calls",
        failures,
    )

    r2 = await _scenario_2(tmp_root / "chk2")
    _check(
        len(r2["final"]["dispatch_calls"]) == 7,
        "s2: expected 7 dispatch calls (one per condition)",
        failures,
    )
    _check(
        r2["final"]["act_dq"] == 0,
        "s2: action_dq should be drained after each direct dispatch",
        failures,
    )

    r3 = await _scenario_3(tmp_root / "chk3")
    calls3 = r3["final"]["dispatch_calls"]
    _check(len(calls3) == 3, "s3: expected 3 dispatch calls", failures)
    _check(
        calls3[1]["params"].get("injected_param") == "VAL1",
        "s3: list-form to_global_params did not fold into next action",
        failures,
    )
    _check(
        calls3[2]["params"].get("injected_param2") == "VAL2",
        "s3: dict-form to_global_params did not fold into next action",
        failures,
    )

    r4 = await _scenario_4(tmp_root / "chk4")
    _check(
        r4["final"]["wait_for_interrupt_result"] is False,
        "s4: expected wait_for_interrupt to signal bail-out (False)",
        failures,
    )
    _check(
        r4["final"]["act_dq_front_is_pending"],
        "s4: pending action must be requeued at the front",
        failures,
    )

    r5 = await _scenario_5(tmp_root / "chk5")
    _check(r5["final"]["act_dq"] == 0, "s5: skip must clear action_dq", failures)
    _check(
        r5["final"]["dispatch_calls_count"] == 1,
        "s5: only the priming action should have dispatched before the skip",
        failures,
    )

    r6 = await _scenario_6(tmp_root / "chk6")
    _check(
        r6["final"]["act_dq"] == 2,
        "s6: failed action + never-reached action must remain queued",
        failures,
    )
    _check(
        r6["final"]["act_dq_front"] == "act_will_fail",
        "s6: requeued action must be the one that failed",
        failures,
    )
    _check(
        len(r6["final"]["dispatch_calls"]) == 2,
        "s6: only the priming + failing actions should have dispatched (act_never_reached must not)",
        failures,
    )

    r7 = await _scenario_7(tmp_root / "chk7")
    _check(
        r7["final"]["loop_state"] == "estopped", "s7: loop must end estopped", failures
    )
    _check(r7["final"]["estop_loop_called"], "s7: estop_loop must be invoked", failures)
    _check(
        r7["final"]["estop_dispatch_count"] >= 1,
        "s7: estop_actions must fan out an estop dispatch",
        failures,
    )

    r8 = await _scenario_8(tmp_root / "chk8")
    _check(
        r8["final"]["loop_state"] == "stopped",
        "s8: loop did not stop cleanly",
        failures,
    )
    _check(
        r8["final"]["nonblocking_list_final_len"] == 0,
        "s8: nonblocking list must drain back to empty",
        failures,
    )
    active_events = [e for e in r8["final"]["nonblocking_events"] if e["active"]]
    _check(
        len(active_events) >= 1,
        "s8: nonblocking action must register as active at least once",
        failures,
    )

    r9 = await _scenario_9(tmp_root / "chk9")
    _check(
        r9["final"]["step_thru_actions"]["act_dq"] == 1,
        "s9a: one action must remain unqueued after step-thru stop",
        failures,
    )
    _check(
        r9["final"]["step_thru_actions"]["dispatch_calls_count"] == 1,
        "s9a: only first action should dispatch",
        failures,
    )
    # step_thru_experiments's `self.stop()` only flags loop_intent -- it is
    # consulted by loop_task_dispatch_action (which checks it up front), not
    # by loop_task_dispatch_experiment, so the 2nd experiment still gets
    # *unpacked* into action_dq; what actually halts is that its action is
    # then never dispatched (the next loop_task_dispatch_action call sees
    # loop_intent==stop and stops instead). Faithfully pinning this real
    # (if perhaps surprising) behavior, not a harness assumption.
    _check(
        r9["final"]["step_thru_experiments"]["exp_dq"] == 0,
        "s9b: second experiment should have been unpacked (not left in experiment_dq)",
        failures,
    )
    _check(
        r9["final"]["step_thru_experiments"]["act_dq"] == 1,
        "s9b: second experiment's action must remain queued, undispatched",
        failures,
    )
    _check(
        r9["final"]["step_thru_experiments"]["dispatch_calls_count"] == 1,
        "s9b: only the first experiment's action should have dispatched",
        failures,
    )

    fixture = await capture_queues_pck_fixture(tmp_root / "chkpck")
    _check(fixture["exported_ok"], "pck: export_queues did not write a file", failures)
    _check(
        fixture["keys_match"], "pck: exported payload missing expected keys", failures
    )
    _check(fixture["restored_ok"], "pck: import_queues round-trip mismatch", failures)

    return failures


def main():
    import argparse
    import tempfile

    parser = argparse.ArgumentParser(
        description="CARDS P5 dispatch-decision golden-master harness."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Hard gate mode: byte-diff freshly captured scenario traces "
            "against the frozen .omc/artifacts/p5/baseline_S0/ reference. "
            "Never overwrites baseline_S0/. Exits non-zero on any "
            "divergence/missing/extra file. This is the mode run by "
            "every S1-S9 downstream stage."
        ),
    )
    args = parser.parse_args()

    if args.check:
        raise SystemExit(run_check_mode())

    # --- default: record/dev mode. Writes scratch traces to baseline/ for
    # local inspection only; NEVER touches the frozen baseline_S0/ reference
    # (enforced by the assertion in run_all_scenarios). ---
    with tempfile.TemporaryDirectory() as check_root:
        failures = asyncio.run(_run_and_check(Path(check_root)))

    if failures:
        print("SCENARIO CHECKS FAILED:")
        for f in failures:
            print(f"  - {f}")
    else:
        print("ALL 9 SCENARIO CHECKS PASSED (1-9) + queues.pck fixture")

    with tempfile.TemporaryDirectory() as baseline_tmp:
        baseline_texts = asyncio.run(
            run_all_scenarios(BASELINE_DIR, Path(baseline_tmp))
        )
    print(
        f"Dev/record-mode scratch traces written to: {BASELINE_DIR} (NOT the frozen gate -- see baseline_S0/, run with --check to verify against it)"
    )

    with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2, tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
        run1 = asyncio.run(run_all_scenarios(Path(d1), Path(t1)))
        run2 = asyncio.run(run_all_scenarios(Path(d2), Path(t2)))
        det_failures = []
        for name in SCENARIOS:
            if run1[name] != run2[name]:
                det_failures.append(name)
        if det_failures:
            print(f"DETERMINISM CHECK FAILED for: {det_failures}")
        else:
            print(
                "DETERMINISM CHECK PASSED: two capture runs byte-identical for all 9 scenarios"
            )

    if failures or det_failures:
        raise SystemExit(1)
    print("ALL GOLDEN-MASTER HARNESS CHECKS PASSED")


if __name__ == "__main__":
    main()
