"""HexStatusIngestion (P2a T3): verbatim fold parity against the legacy
StatusIngester bodies, the elif-chain event selection evaluated on LIVE
loop_state, lock-held emission, and the two update_nonblocking wire quirks
(None-timestamp TypeError; unknown-exec_id ValueError)."""

import asyncio
from datetime import datetime
from uuid import UUID, uuid4

import pytest

from helao.core.models.hlostatus import HloStatus
from helao.core.models.machine import MachineModel
from helao.core.models.orchstatus import LoopStatus, OrchStatus
from helao.core.models.server import (
    ActionServerModel,
    EndpointModel,
    GlobalStatusModel,
)
from helao.helpers.premodels import Action
from helao.hexagon.app.ingestion import HexStatusIngestion, action_history_meta
from helao.hexagon.app.orch_effects import OrchCommandRunner
from helao.hexagon.app.wiring import PortWiring
from helao.hexagon.domain.orchestration import (
    ErroredUuidIngested,
    EstoppedUuidIngested,
    PruneDeadActions,
    StatusChanged,
)

ORCH_M = MachineModel(server_name="ORCH", machine_name="testhost")
# Action.url is a COMPUTED read-only property (helao/core/models/action.py:
# 167-170): f"http://{action_server.hostname}:{action_server.port}/
# {action_server.server_name}/{action_name}" — NOT a settable field. The
# fixture's MachineModel MUST carry hostname/port or actmod.url computes to
# "http://None:None/SIM/..." and every url string-match downstream (the T6
# monitor probe, the launched item-6) silently misses.
SIM_M = MachineModel(
    server_name="SIM", machine_name="testhost", hostname="127.0.0.1", port=8002
)


class _RuntimeSpy:
    """Records events; also snapshots whether aiolock was held at emission."""

    def __init__(self, orch=None):
        self.orch = orch
        self.events = []
        self.locked_at_emit = []

    async def handle(self, event):
        self.events.append(event)
        if self.orch is not None:
            self.locked_at_emit.append(self.orch.aiolock.locked())


class _IngestOrch:
    """Call-time legacy-orch surface for ingestion (real GlobalStatusModel)."""

    def __init__(self):
        self.aiolock = asyncio.Lock()
        self.globalstatusmodel = GlobalStatusModel(orchestrator=ORCH_M)
        self.interrupt_q = asyncio.Queue()
        self.nonblocking = []
        self.active_experiment = None
        self.active_sequence = None
        self.registered = {}
        self.lbuf = []

    def register_action_uuid(self, action_uuid, action_dict):
        self.registered[action_uuid] = action_dict

    async def put_lbuf(self, live_dict):
        self.lbuf.append(live_dict)


def _act(uuid, statuses):
    # no url= kwarg: url is a computed property (see SIM_M note above);
    # pydantic would silently ignore the kwarg
    return Action(
        action_uuid=uuid,
        action_name="acquire",
        action_status=list(statuses),
        action_server=SIM_M,
        orchestrator=ORCH_M,
        action_timestamp=datetime.now(),
    )


def test_act_fixture_url_matches_monitor_probe_target():
    """Guards the whole T6/item-6 chain: if the MachineModel loses its
    hostname/port, actmod.url no longer matches the probe target and the
    dead-peer detection silently never fires."""
    act = _act(uuid4(), [HloStatus.active])
    assert act.url == "http://127.0.0.1:8002/SIM/acquire"


def _asm(act, active=True, last=None):
    ep = EndpointModel(endpoint_name="acquire")
    if active:
        ep.active_dict[act.action_uuid] = act
    else:
        ep.nonactive_dict.setdefault(HloStatus.finished, {})[act.action_uuid] = act
    return ActionServerModel(
        action_server=SIM_M, endpoints={"acquire": ep}, last_action_uuid=last
    )


def _make():
    orch = _IngestOrch()
    spy = _RuntimeSpy(orch)
    return orch, spy, HexStatusIngestion(orch, spy)


@pytest.mark.asyncio
async def test_none_model_returns_false_without_side_effects():
    orch, spy, ing = _make()
    assert await ing.update_status(actionservermodel=None) is False
    assert spy.events == [] and orch.interrupt_q.empty()


@pytest.mark.asyncio
async def test_active_fold_emits_busy_statuschanged_and_wakes():
    orch, spy, ing = _make()
    u = uuid4()
    assert await ing.update_status(actionservermodel=_asm(_act(u, [HloStatus.active])))
    assert u in orch.globalstatusmodel.active_dict
    assert spy.events == [StatusChanged(any_active=True)]
    assert spy.locked_at_emit == [True]  # emitted INSIDE aiolock (parity)
    assert orch.interrupt_q.get_nowait() is orch.globalstatusmodel
    # DD-2: ingestion itself no longer writes orch_state
    assert orch.globalstatusmodel.orch_state == OrchStatus.idle


@pytest.mark.asyncio
async def test_finished_fold_emits_idle_and_puts_lbuf():
    orch, spy, ing = _make()
    u = uuid4()
    await ing.update_status(actionservermodel=_asm(_act(u, [HloStatus.active])))
    fin = _act(u, [HloStatus.active, HloStatus.finished])
    await ing.update_status(actionservermodel=_asm(fin, active=False, last=u))
    assert spy.events[-1] == StatusChanged(any_active=False)
    assert orch.lbuf == [{u: {"status": HloStatus.finished.name}}]
    # last_action_uuid registration ran with the formatted-timestamp meta
    assert orch.registered[u]["action_name"] == "acquire"
    assert orch.registered[u]["action_timestamp"].strip()


@pytest.mark.asyncio
async def test_estopped_uuid_while_started_emits_estop_event_only():
    orch, spy, ing = _make()
    orch.globalstatusmodel.loop_state = LoopStatus.started
    u = uuid4()
    est = _act(u, [HloStatus.active, HloStatus.finished, HloStatus.estopped])
    await ing.update_status(actionservermodel=_asm(est, active=False))
    assert len(spy.events) == 1
    ev = spy.events[0]
    assert isinstance(ev, EstoppedUuidIngested)
    assert ev.reason.startswith("E-STOP due to action uuid(s): ")
    assert str(u) in ev.reason


@pytest.mark.asyncio
async def test_estopped_uuid_while_stopped_falls_through_to_statuschanged():
    """Legacy elif chain: the estop branch is guarded on started — a
    stopped-loop fold with estopped uuids lands idle/busy instead."""
    orch, spy, ing = _make()
    u = uuid4()
    est = _act(u, [HloStatus.active, HloStatus.finished, HloStatus.estopped])
    await ing.update_status(actionservermodel=_asm(est, active=False))
    assert spy.events == [StatusChanged(any_active=False)]


@pytest.mark.asyncio
async def test_errored_uuid_while_started_emits_errored_event():
    orch, spy, ing = _make()
    orch.globalstatusmodel.loop_state = LoopStatus.started
    u = uuid4()
    err = _act(u, [HloStatus.active, HloStatus.finished, HloStatus.errored])
    await ing.update_status(actionservermodel=_asm(err, active=False))
    assert spy.events == [ErroredUuidIngested()]


@pytest.mark.asyncio
async def test_update_nonblocking_active_appends_and_wakes():
    orch, spy, ing = _make()
    u = uuid4()
    act = _act(u, [HloStatus.active])
    act.exec_id = "acquire exec1"
    out = await ing.update_nonblocking(act, "127.0.0.1", 8002)
    assert out == {"success": True}
    assert orch.nonblocking == [("SIM", "acquire exec1", "127.0.0.1", 8002)]
    assert u in orch.registered
    assert not orch.interrupt_q.empty()


@pytest.mark.asyncio
async def test_update_nonblocking_unknown_exec_id_raises_valueerror():
    """Spec §7.4 wire quirk: list.remove on an unknown exec_id raises —
    reproduced, not guarded."""
    orch, _spy, ing = _make()
    u = uuid4()
    act = _act(u, [HloStatus.finished])
    act.exec_id = "acquire exec1"
    with pytest.raises(ValueError):
        await ing.update_nonblocking(act, "127.0.0.1", 8002)


@pytest.mark.asyncio
async def test_update_nonblocking_none_timestamp_raises_typeerror():
    """status.py third-drift quirk: the %-format f-string rejects None."""
    orch, _spy, ing = _make()
    act = _act(uuid4(), [HloStatus.active])
    act.exec_id = "acquire exec1"
    act.action_timestamp = None
    with pytest.raises(TypeError):
        await ing.update_nonblocking(act, "127.0.0.1", 8002)


def test_action_history_meta_matches_legacy_shape():
    orch = _IngestOrch()
    act = _act(uuid4(), [HloStatus.active])
    meta = action_history_meta(orch, act)
    assert set(meta) == {
        "action_name",
        "action_params",
        "action_status",
        "action_server",
        "action_timestamp",
        "action_finished_timestamp",
        "experiment_name",
        "experiment_uuid",
        "sequence_name",
        "sequence_label",
        "sequence_uuid",
    }
    assert meta["action_server"] == "SIM"
    assert meta["action_finished_timestamp"] is None


class _CountingLock:
    """asyncio.Lock wrapper counting acquisitions (two-owner invariant)."""

    def __init__(self):
        self._lock = asyncio.Lock()
        self.acquisitions = 0

    def locked(self):
        return self._lock.locked()

    async def __aenter__(self):
        self.acquisitions += 1
        return await self._lock.__aenter__()

    async def __aexit__(self, *exc):
        return await self._lock.__aexit__(*exc)


@pytest.mark.asyncio
async def test_prune_dead_actions_unblocks_actions_idle_and_registers():
    orch, spy, ing = _make()
    u = uuid4()
    # fold an active action in (populates gsm.active_dict AND server_dict)
    await ing.update_status(actionservermodel=_asm(_act(u, [HloStatus.active])))
    gsm = orch.globalstatusmodel
    assert not gsm.actions_idle()
    runner = OrchCommandRunner(orch, PortWiring())
    await runner.execute(PruneDeadActions(action_uuids=(str(u),)))
    assert gsm.actions_idle()  # global active_dict pruned
    # per-endpoint active_dict pruned too (else the next fold resurrects it)
    for asm in gsm.server_dict.values():
        for ep in asm.endpoints.values():
            assert u not in ep.active_dict
    # terminal status injected + finished-bucketed + history registered
    pruned = gsm.nonactive_dict[HloStatus.finished][u]
    assert HloStatus.finished in pruned.action_status
    assert pruned.action_finished_timestamp is not None
    assert u in orch.registered
    assert orch.registered[u]["action_finished_timestamp"] is not None
    assert str(u) in runner.pruned_uuids


@pytest.mark.asyncio
async def test_prune_unknown_uuid_is_a_noop():
    orch, _spy, _ing = _make()
    runner = OrchCommandRunner(orch, PortWiring())
    await runner.execute(PruneDeadActions(action_uuids=(str(uuid4()),)))
    assert orch.registered == {}


@pytest.mark.asyncio
async def test_two_lock_owner_invariant_prune_never_takes_aiolock():
    """aiolock owners are ingestion + dispatch critical section ONLY: one
    update_status = exactly one acquisition; the prune adds none."""
    orch, spy, ing = _make()
    orch.aiolock = _CountingLock()  # type: ignore[assignment]
    u = uuid4()
    await ing.update_status(actionservermodel=_asm(_act(u, [HloStatus.active])))
    assert orch.aiolock.acquisitions == 1  # type: ignore[attr-defined]
    runner = OrchCommandRunner(orch, PortWiring())
    await runner.execute(PruneDeadActions(action_uuids=(str(u),)))
    assert orch.aiolock.acquisitions == 1  # type: ignore[attr-defined]


from helao.core.models.orchstatus import LoopIntent
from helao.hexagon.app.dispatch_loop import HexDispatchLoop, HexRuntime
from helao.hexagon.app.ingestion import HexHealthMonitor
from helao.hexagon.domain.orchestration import StartRequested


class _FakeHealth:
    def __init__(self, bad=()):
        self.bad = set(bad)

    async def endpoints_available(self, urls):
        return [(u, u not in self.bad) for u in urls]

    async def ping_action_servers(self):
        return {}

    def status_summary(self):
        return {}


class _AlertSpy:
    def __init__(self):
        self.alerts = []

    def info(self, msg): ...
    def warning(self, msg): ...
    def error(self, msg, exc_info=False): ...

    def alert(self, msg):
        self.alerts.append(msg)

    def file_logger(self, server_key, log_root):
        raise AssertionError("unused")


class _MonitorOrch(_IngestOrch):
    """Full-enough legacy surface for HexRuntime over a real GSM. The
    drain/estop members are FAITHFUL ports of the legacy bodies (not
    conveniences): the two required-fix regression tests below exercise the
    real WaitAllActionsIdle executor and the real estop cascade against
    them, and their hang modes only exist if these behave like legacy."""

    def __init__(self):
        super().__init__()
        self.heartbeat_interval = 0.05
        self.ignore_heartbeats = []
        self.current_stop_message = ""
        self.active_run_id = "RUN"
        self.action_dq, self.experiment_dq, self.sequence_dq = [], [], []
        self.status_summary = {}
        self.step_thru_actions = False
        self.step_thru_experiments = False
        self.step_thru_sequences = False

    # all four intend_* put the intent on interrupt_q, like the real
    # Orch (orch.py:536-571) — the drain path's intend_none wake matters
    async def intend_stop(self):
        self.globalstatusmodel.loop_intent = LoopIntent.stop
        await self.interrupt_q.put(self.globalstatusmodel.loop_intent)

    async def intend_skip(self):
        self.globalstatusmodel.loop_intent = LoopIntent.skip
        await self.interrupt_q.put(self.globalstatusmodel.loop_intent)

    async def intend_estop(self):
        self.globalstatusmodel.loop_intent = LoopIntent.estop
        await self.interrupt_q.put(self.globalstatusmodel.loop_intent)

    async def intend_none(self):
        self.globalstatusmodel.loop_intent = LoopIntent.none
        await self.interrupt_q.put(self.globalstatusmodel.loop_intent)

    async def orch_wait_for_all_actions(self):
        # faithful port of orch.py:443-455: returns IMMEDIATELY (no yield!)
        # once actions_idle(); otherwise parks on the interrupt queue — the
        # exact mechanism the dead-peer race can starve (required fix 2)
        while not self.globalstatusmodel.actions_idle():
            await self.interrupt_q.get()

    def export_queues(self, timestamp_pck: bool = False):
        return None  # finalization's ExportQueuesCmd lands here

    async def estop_actions(self, switch: bool):
        return None  # EstopFanout target; must not need aiolock

    async def estop_finish_active(self):
        return None  # FinishActiveEstopped target; must not need aiolock


def _monitor_setup(bad):
    orch = _MonitorOrch()
    wiring = PortWiring(logging=_AlertSpy())
    effects = OrchCommandRunner(orch, wiring)
    runtime = HexRuntime(orch, effects)
    mon = HexHealthMonitor(orch, runtime, _FakeHealth(bad=bad))
    return orch, wiring, effects, mon


@pytest.mark.asyncio
async def test_monitor_dead_peer_prunes_sets_message_and_goes_idle():
    """The full item-6 chain in-process: probe -> HeartbeatFailed(+uuids)
    -> stop intent + stop message + alert + prune -> StatusChanged fold
    (DD-2 write-back -> orch_state idle) -> interrupt wake."""
    orch, wiring, effects, mon = _monitor_setup(
        bad={"http://127.0.0.1:8002/SIM/acquire"}
    )
    gsm = orch.globalstatusmodel
    gsm.loop_state = LoopStatus.started
    u = uuid4()
    ing = HexStatusIngestion(orch, _RuntimeSpy(orch))
    await ing.update_status(actionservermodel=_asm(_act(u, [HloStatus.active])))
    while not orch.interrupt_q.empty():
        orch.interrupt_q.get_nowait()  # drain the fold wakes

    await mon.probe_once()

    assert orch.current_stop_message == "SIM/acquire endpoints are unavailable"
    assert gsm.loop_intent == LoopIntent.stop
    assert gsm.actions_idle()
    assert gsm.orch_state == OrchStatus.idle  # StatusChanged wrote back
    assert str(u) in effects.pruned_uuids
    assert wiring.logging.alerts == [  # type: ignore[union-attr]
        "SIM/acquire endpoints are unavailable"
    ]
    assert not orch.interrupt_q.empty()  # the wake that releases the drain


@pytest.mark.asyncio
async def test_monitor_noop_when_loop_not_started_or_all_healthy():
    orch, _w, effects, mon = _monitor_setup(bad=set())
    orch.globalstatusmodel.loop_state = LoopStatus.started
    await mon.probe_once()  # no active endpoints -> no-op
    orch2, _w2, effects2, mon2 = _monitor_setup(
        bad={"http://127.0.0.1:8002/SIM/acquire"}
    )
    await mon2.probe_once()  # loop stopped -> no probe at all
    assert effects.pruned_uuids == set() and effects2.pruned_uuids == set()
    assert orch.current_stop_message == "" and orch2.current_stop_message == ""


@pytest.mark.asyncio
async def test_monitor_respects_ignore_heartbeats():
    orch, _w, effects, mon = _monitor_setup(bad={"http://127.0.0.1:8002/SIM/acquire"})
    orch.ignore_heartbeats = ["SIM/acquire"]
    orch.globalstatusmodel.loop_state = LoopStatus.started
    ing = HexStatusIngestion(orch, _RuntimeSpy(orch))
    await ing.update_status(actionservermodel=_asm(_act(uuid4(), [HloStatus.active])))
    await mon.probe_once()
    assert orch.current_stop_message == ""
    assert effects.pruned_uuids == set()


@pytest.mark.asyncio
async def test_dead_peer_race_real_loop_parks_without_hang():
    """REQUIRED-FIX-2 regression: the monitor's prune -> StatusChanged ->
    interrupt-wake ORDERING is load-bearing. The real WaitAllActionsIdle
    executor (orch_effects.py:217-227) loops `while loop_state != stopped:
    await orch_wait_for_all_actions(); if orch_state == idle: break`, and
    orch_wait_for_all_actions returns IMMEDIATELY without yielding once
    actions_idle() is true — so a window where active_dict is pruned but
    orch_state has not landed idle lets the drainer spin without a yield,
    starving the event loop so the StatusChanged coroutine that would set
    orch_state=idle can never be scheduled: the failure mode is a HANG,
    not an assertion failure. This test parks the REAL HexRuntime +
    HexDispatchLoop in the stop-drain with an active action, fires ONE
    probe, and requires the park to complete under a hard timeout."""
    orch, wiring, effects, mon = _monitor_setup(
        bad={"http://127.0.0.1:8002/SIM/acquire"}
    )
    gsm = orch.globalstatusmodel
    u = uuid4()
    runtime = mon.runtime  # the REAL HexRuntime built by _monitor_setup
    # Seed through the REAL runtime (not _RuntimeSpy) so the busy fold
    # actually runs apply_state_delta and flips orch_state to busy --
    # otherwise orch_state would sit at its idle default for the whole
    # test and WaitAllActionsIdle's `if orch_state == idle: break` would
    # succeed trivially, making the test pass even if the monitor's
    # prune -> StatusChanged ordering were broken.
    ing = HexStatusIngestion(orch, runtime)
    await ing.update_status(actionservermodel=_asm(_act(u, [HloStatus.active])))
    while not orch.interrupt_q.empty():
        orch.interrupt_q.get_nowait()  # drain the fold wakes
    assert gsm.orch_state == OrchStatus.busy  # genuine precondition for the guard

    loop = HexDispatchLoop(runtime)
    loop.start()
    # pre-seed intent=stop so the first LoopIterate takes T5 (DrainForStop
    # -> WaitAllActionsIdle) without ever touching a dispatch effect
    gsm.loop_intent = LoopIntent.stop
    orch.action_dq = ["a0"]  # has_work for T1; never dispatched (drain wins)
    await runtime.handle(StartRequested())
    await asyncio.sleep(0.1)
    # drainer is now parked inside orch_wait_for_all_actions on the
    # interrupt queue with one active action; loop_state is still started
    assert gsm.loop_state == LoopStatus.started

    await mon.probe_once()

    async def _parked():
        while not (
            gsm.loop_state == LoopStatus.stopped and gsm.orch_state == OrchStatus.idle
        ):
            await asyncio.sleep(0.02)

    await asyncio.wait_for(_parked(), timeout=5.0)
    assert orch.current_stop_message == "SIM/acquire endpoints are unavailable"
    assert gsm.actions_idle()
    assert str(u) in effects.pruned_uuids
    await loop.close()


@pytest.mark.asyncio
async def test_estop_cascade_under_aiolock_does_not_deadlock():
    """REQUIRED-FIX-3 regression: update_status emits EstoppedUuidIngested
    via `await runtime.handle(...)` while HOLDING orch.aiolock (legacy
    parity — the inline block called estop_loop under the lock,
    orch_status_sync.py:274-275). Legacy was safe because its estop path
    took no lock; the hexagon cascade (ClearActiveRunId, EstopFanout,
    FinishActiveEstopped, SetStopMessage, AlertOperator + apply_state_delta)
    is DIFFERENT code and must never re-acquire aiolock — if any of it did,
    this await chain deadlocks. Runs the REAL HexRuntime (non-spy) through
    a fold carrying an estopped uuid under a hard timeout."""
    orch, wiring, effects, mon = _monitor_setup(bad=set())
    gsm = orch.globalstatusmodel
    gsm.loop_state = LoopStatus.started
    ing = HexStatusIngestion(orch, mon.runtime)  # REAL runtime, no spy
    u = uuid4()
    est = _act(u, [HloStatus.active, HloStatus.finished, HloStatus.estopped])
    ok = await asyncio.wait_for(
        ing.update_status(actionservermodel=_asm(est, active=False)),
        timeout=5.0,
    )
    assert ok is True
    assert gsm.loop_state == LoopStatus.estopped
    assert gsm.orch_state == OrchStatus.estopped  # DD-2 write-back
    assert orch.current_stop_message.startswith("E-STOP due to action uuid(s):")
    assert orch.active_run_id is None  # ClearActiveRunId ran
    assert not orch.aiolock.locked()  # lock released cleanly after the fold
