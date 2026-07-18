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
