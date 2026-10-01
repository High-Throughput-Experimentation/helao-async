"""E-STOP finalize vs the clean experiment finish (eche10 station, 2026-09-30).

``estop_finish_active`` landed while ``finish_active_experiment`` was suspended
at one of its awaits, finalized the SAME experiment and cleared
``active_experiment``; the clean path then crashed on
``orch.active_experiment.experiment_uuid`` and the experiment was written twice
and listed twice in ``dispatched_experiments``.

The tests drive the hexagon ``OrchHost`` through ``RunLifecycle`` /
``EstopController``. Until B7b each one also ran against the legacy ``Orch``,
which B7b deleted.
"""

import asyncio
import tempfile
from collections import deque
from types import SimpleNamespace

import pytest

import helao.helpers.yml_tools as yml_tools_module  # B7a: move_dir seam owner
from helao.core.hooks import HookSet
from helao.core.models.hlostatus import HloStatus
from helao.core.models.machine import MachineModel
from helao.core.models.orchstatus import LoopStatus
from helao.core.models.server import GlobalStatusModel
from helao.hexagon.app.orch_host import OrchHost
from helao.helpers.dequedict import DequeDict
from helao.helpers.premodels import Experiment, Sequence


def _make_orch(cls, init_collaborators: str):
    """A bare orchestrator with every attribute the two collaborators touch."""
    orch = cls.__new__(cls)
    orch.server = MachineModel(
        server_name="ORCH", machine_name="m", hostname="127.0.0.1", port=8000
    )
    orch.aloop = asyncio.get_running_loop()
    orch.ntp_offset = 0.0
    orch.global_params = {}
    orch.prefinish_sequence_hooks = HookSet.empty()
    orch.prefinish_experiment_hooks = HookSet.empty()
    orch.helaodirs = SimpleNamespace(save_root=tempfile.mkdtemp(prefix="estop_race_"))
    orch.nonblocking = []
    orch.last_sequence = None
    orch.last_experiment = None
    orch.active_seq_exp_counter = 3
    orch.action_history = DequeDict(maxlen=1000)
    orch.experiment_history = DequeDict(maxlen=1000)
    orch.sequence_history = DequeDict(maxlen=1000)
    orch.globalstatusmodel = GlobalStatusModel(orchestrator=orch.server)
    orch.experiment_dq = deque()
    orch.action_dq = deque()

    orch.written = {"seq": [], "exp": []}

    async def _write_seq(sequence):
        orch.written["seq"].append(sequence.sequence_name)

    async def _write_exp(experiment):
        orch.written["exp"].append(experiment.experiment_name)

    async def _put_lbuf(live_dict):
        return None

    async def _idle():
        return None

    orch.write_seq = _write_seq
    orch.write_exp = _write_exp
    orch.put_lbuf = _put_lbuf
    orch.orch_wait_for_all_actions = _idle
    getattr(orch, init_collaborators)()

    seq = Sequence(sequence_name="seq1", sequence_params={})
    seq.init_seq(time_offset=0.0)
    seq.sequence_status = [HloStatus.active]
    exp = Experiment(experiment_name="exp1", experiment_params={})
    exp.init_exp(time_offset=0.0)
    exp.experiment_status = [HloStatus.active]
    orch.active_sequence = seq
    orch.active_experiment = exp
    return orch


FLAVOURS = [
    pytest.param(OrchHost, "_init_orch_collaborators", id="hexagon"),
]


@pytest.fixture
def move_dir_noop(monkeypatch):
    async def _move_dir(hobj, base=None, retry_delay=5):
        return None

    monkeypatch.setattr(yml_tools_module, "move_dir", _move_dir)


async def _settle():
    for _ in range(20):
        await asyncio.sleep(0)


def _gate_first_call(orch, name: str):
    """Make the FIRST call of ``orch.<name>`` park on an Event the test controls."""
    entered, release = asyncio.Event(), asyncio.Event()
    real = getattr(orch, name)
    calls = []

    async def _gated(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            entered.set()
            await release.wait()
        return await real(*a, **k)

    setattr(orch, name, _gated)
    return entered, release


@pytest.mark.asyncio
@pytest.mark.parametrize("cls,init", FLAVOURS)
@pytest.mark.parametrize("gated", ["write_active_sequence_seq", "put_lbuf"])
async def test_estop_lands_while_clean_experiment_finish_is_suspended(
    cls, init, gated, move_dir_noop
):
    orch = _make_orch(cls, init)
    exp, seq = orch.active_experiment, orch.active_sequence
    entered, release = _gate_first_call(orch, gated)

    clean = asyncio.create_task(orch.finish_active_experiment())
    await asyncio.wait_for(entered.wait(), 5)
    estop = asyncio.create_task(orch.estop_finish_active())
    await _settle()
    release.set()
    await asyncio.wait_for(asyncio.gather(clean, estop), 5)  # no exception

    uuids = [e.experiment_uuid for e in seq.dispatched_experiments]
    assert uuids == [exp.experiment_uuid]
    assert orch.written["exp"] == ["exp1"]
    assert orch.active_experiment is None and orch.active_sequence is None
    assert HloStatus.estopped in orch.last_sequence.sequence_status


@pytest.mark.asyncio
@pytest.mark.parametrize("cls,init", FLAVOURS)
async def test_clean_experiment_finish_requested_while_estop_is_suspended(
    cls, init, move_dir_noop
):
    orch = _make_orch(cls, init)
    exp, seq = orch.active_experiment, orch.active_sequence
    entered, release = _gate_first_call(orch, "write_exp")

    estop = asyncio.create_task(orch.estop_finish_active())
    await asyncio.wait_for(entered.wait(), 5)
    clean = asyncio.create_task(orch.finish_active_experiment())
    await _settle()
    release.set()
    await asyncio.wait_for(asyncio.gather(estop, clean), 5)

    uuids = [e.experiment_uuid for e in seq.dispatched_experiments]
    assert uuids == [exp.experiment_uuid]
    assert orch.written["exp"] == ["exp1"]
    assert HloStatus.estopped in orch.last_experiment.experiment_status
    assert HloStatus.estopped in orch.last_sequence.sequence_status


@pytest.mark.asyncio
@pytest.mark.parametrize("cls,init", FLAVOURS)
async def test_clean_sequence_finish_and_estop_finalize_the_sequence_once(
    cls, init, move_dir_noop
):
    orch = _make_orch(cls, init)
    orch.active_experiment = None
    seq = orch.active_sequence
    entered, release = _gate_first_call(orch, "write_seq")

    clean = asyncio.create_task(orch.finish_active_sequence())
    await asyncio.wait_for(entered.wait(), 5)
    estop = asyncio.create_task(orch.estop_finish_active())
    await _settle()
    release.set()
    await asyncio.wait_for(asyncio.gather(clean, estop), 5)

    assert orch.written["seq"] == ["seq1"]
    assert orch.active_sequence is None
    assert orch.last_sequence.sequence_uuid == seq.sequence_uuid
    assert HloStatus.estopped not in orch.last_sequence.sequence_status


@pytest.mark.asyncio
@pytest.mark.parametrize("cls,init", FLAVOURS)
async def test_station_order_estopped_loop_leaves_finalizing_to_estop(
    cls, init, move_dir_noop
):
    # estop_loop sets loop_state=estopped before the fan-out; the clean path's
    # wait releases and reaches the lock first. estop_finish_active must stay
    # the sole finalizer so the experiment keeps `estopped`.
    orch = _make_orch(cls, init)
    exp, seq = orch.active_experiment, orch.active_sequence
    orch.globalstatusmodel.loop_state = LoopStatus.estopped
    await orch.finish_active_experiment()
    await orch.finish_active_sequence()
    assert orch.written == {"seq": [], "exp": []}
    await orch.estop_finish_active()
    ids = [e.experiment_uuid for e in seq.dispatched_experiments]
    assert ids == [exp.experiment_uuid]
    assert HloStatus.estopped in orch.last_experiment.experiment_status
    assert HloStatus.estopped in seq.dispatched_experiments[0].experiment_status
    assert HloStatus.estopped in orch.last_sequence.sequence_status


@pytest.mark.asyncio
@pytest.mark.parametrize("cls,init", FLAVOURS)
async def test_clean_finish_with_exp_already_in_dispatched_skips_only_the_append(
    cls, init, move_dir_noop
):
    orch = _make_orch(cls, init)
    exp, seq = orch.active_experiment, orch.active_sequence
    seq.dispatched_experiments.append(exp.get_exp())

    await orch.finish_active_experiment()

    assert len(seq.dispatched_experiments) == 1
    assert orch.written["exp"] == ["exp1"]
    assert orch.active_experiment is None
    assert orch.last_experiment.experiment_uuid == exp.experiment_uuid


@pytest.mark.asyncio
@pytest.mark.parametrize("cls,init", FLAVOURS)
async def test_estop_replaces_an_already_appended_experiment(cls, init, move_dir_noop):
    orch = _make_orch(cls, init)
    exp, seq = orch.active_experiment, orch.active_sequence
    seq.dispatched_experiments.append(exp.get_exp())  # stale, pre-estopped copy

    await orch.estop_finish_active()

    assert len(seq.dispatched_experiments) == 1
    assert HloStatus.estopped in seq.dispatched_experiments[0].experiment_status
    assert HloStatus.estopped in orch.last_experiment.experiment_status
