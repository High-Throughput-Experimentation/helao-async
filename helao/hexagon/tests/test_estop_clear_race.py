"""E-STOP clear re-latched by a stale dispatch step (eche10, 2026-09-30).

``dispatch_sequence`` / ``dispatch_experiment`` park on awaits (``put_lbuf``,
``write_seq``, ``to_s3``). An E-STOP that finalizes meanwhile sets
``active_sequence`` / ``active_experiment`` to None, and an operator clear then
sets ``stopped``. The resumed step dereferenced the None record, the loop turned
the AttributeError into ``UncaughtLoopException``, and the reducer re-latched
E-STOP: a second ``estop=True`` fan-out and an alert, with the clear undone.

Part 1 (these tests): a step re-checks the record after each await and returns
``ErrorCodes.estop``. Part 2 (generation counter) is tested in
``test_estop_generation.py``.
"""

import asyncio
import tempfile
from collections import deque
from types import SimpleNamespace

import pytest

from helao.core.error import ErrorCodes
from helao.core.models.hlostatus import HloStatus
from helao.core.models.orchstatus import LoopStatus
from helao.helpers.run_state import RunStateJournal
from helao.helpers.premodels import Experiment, Sequence
from helao.hexagon.app import orch_unpack
from helao.hexagon.app.dispatch_loop import HexRuntime
from helao.hexagon.app.orch_effects import OrchCommandRunner
from helao.hexagon.app.wiring import PortWiring
from helao.hexagon.domain.orchestration import ClearEstopRequested
from helao.hexagon.tests.test_estop_finish_race import (
    FLAVOURS,
    _make_orch,
    _settle,
    move_dir_noop,  # noqa: F401  (fixture)
)
from helao.hexagon.tests.test_orch_effects import _AlertSpy


def _dispatch_ready(orch, monkeypatch, use_sync=True):
    """Bare orch from the finish-race harness plus what a dispatch step reads."""
    orch.active_sequence = None
    orch.active_experiment = None
    orch.sequence_dq = deque()
    orch.world_cfg = {"dummy": False, "simulation": False}
    orch.run_type = "test"
    orch.orch_key = "ORCH"
    orch.orch_host = "127.0.0.1"
    orch.orch_port = 8000
    orch.active_run_id = None
    orch.use_sync = use_sync
    # stations have a root, hence a journal; ``_record_active`` reads the record
    orch.helaodirs.root = orch.helaodirs.save_root
    orch.helaodirs.states_root = tempfile.mkdtemp(prefix="estop_race_states_")
    orch.run_journal = RunStateJournal(orch.helaodirs.states_root, "ORCH")

    orch.s3_uploads = []

    async def _to_s3(*a, **k):
        orch.s3_uploads.append(a)

    orch.syncer = SimpleNamespace(to_s3=_to_s3)
    # the crash site is gated on both; force it so the test is not host-dependent
    orch.verify_plates = True
    monkeypatch.setattr(
        type(orch_unpack.PLATE_API), "has_access", property(lambda self: True)
    )
    orch.verify_plate_in_params = lambda paramd: True
    orch.sequence_lib = {}
    orch.seq_model = None
    orch.register_obj_uuid = lambda *a, **k: None
    orch._resolve_active_run_id = lambda seq: None
    orch.globalstatusmodel.loop_state = LoopStatus.started
    orch.fanout = []
    orch.status_summary = {}
    orch.step_thru_actions = False
    orch.step_thru_experiments = False
    orch.step_thru_sequences = False

    async def _estop_actions(switch):
        orch.fanout.append(switch)

    orch.estop_actions = _estop_actions

    async def _intend_none():
        return None

    orch.intend_none = _intend_none
    orch.interrupt_q = asyncio.Queue()
    orch._hex_runtime = HexRuntime(
        orch, OrchCommandRunner(orch, PortWiring(logging=_AlertSpy()))
    )
    return orch


def _park(orch, name):
    """Park the first call of ``orch.<name>`` on an Event the test controls."""
    entered, release = asyncio.Event(), asyncio.Event()
    owner, _, attr = name.rpartition(".")
    owner = getattr(orch, owner) if owner else orch
    real = getattr(owner, attr)
    seen = []

    async def _gated(*a, **k):
        seen.append(1)
        if len(seen) == 1:
            entered.set()
            await release.wait()
        return await real(*a, **k)

    setattr(owner, attr, _gated)
    return entered, release


async def _estop_then_clear(orch):
    """What the operator does while the step is parked."""
    orch.globalstatusmodel.loop_state = LoopStatus.estopped
    await orch.estop_finish_active()
    await orch._hex_runtime.handle(ClearEstopRequested())
    assert orch.globalstatusmodel.loop_state == LoopStatus.stopped


@pytest.mark.asyncio
@pytest.mark.parametrize("cls,init", FLAVOURS)
@pytest.mark.parametrize(
    "parked,use_sync",
    [
        ("put_lbuf", True),
        ("write_seq", True),
        # crash regression only: the to_s3 guard also catches it; the write_seq
        # guard's own effect is pinned by the stale-S3-upload assert below
        ("write_seq", False),
        ("syncer.to_s3", True),
    ],
)
async def test_sequence_step_parked_across_estop_and_clear_returns_estop(
    cls, init, parked, use_sync, move_dir_noop, monkeypatch  # noqa: F811
):
    orch = _dispatch_ready(_make_orch(cls, init), monkeypatch, use_sync)
    seq = Sequence(sequence_name="seq1", sequence_params={})
    orch.sequence_dq.append(seq)
    entered, release = _park(orch, parked)

    step = asyncio.ensure_future(orch.dispatch_runner.dispatch_sequence())
    await asyncio.wait_for(entered.wait(), 2)

    await _estop_then_clear(orch)
    assert orch.active_sequence is None
    release.set()

    assert await asyncio.wait_for(step, 2) is ErrorCodes.estop  # no AttributeError
    assert orch.globalstatusmodel.loop_state == LoopStatus.stopped
    assert orch.fanout == [False]  # only the clear's release; no re-latch
    if parked in ("put_lbuf", "write_seq") and use_sync:
        # the finalizer owns the record: no stale initial upload after the E-STOP
        assert orch.s3_uploads == []


@pytest.mark.asyncio
@pytest.mark.parametrize("cls,init", FLAVOURS)
@pytest.mark.parametrize("parked", ["put_lbuf", "write_exp", "syncer.to_s3"])
async def test_experiment_step_parked_across_estop_and_clear_returns_estop(
    cls, init, parked, move_dir_noop, monkeypatch  # noqa: F811
):
    orch = _dispatch_ready(_make_orch(cls, init), monkeypatch)
    seq = Sequence(sequence_name="seq1", sequence_params={})
    seq.init_seq(time_offset=0.0)
    seq.sequence_status = [HloStatus.active]
    orch.active_sequence = seq
    exp = Experiment(experiment_name="exp1", experiment_params={})
    orch.experiment_dq.append(exp)
    orch.experiment_lib = {"exp1": lambda experiment: []}
    orch.experiment_codehash_lib = {"exp1": "h"}
    orch.experiment_codepath_lib = {"exp1": "p"}
    entered, release = _park(orch, parked)

    step = asyncio.ensure_future(orch.dispatch_runner.dispatch_experiment())
    await asyncio.wait_for(entered.wait(), 2)

    await _estop_then_clear(orch)
    assert orch.active_experiment is None
    release.set()

    assert await asyncio.wait_for(step, 2) is ErrorCodes.estop
    assert orch.globalstatusmodel.loop_state == LoopStatus.stopped
    assert orch.fanout == [False]
    assert not orch.action_dq
    if parked == "write_exp":
        # no ``active`` journal line behind the finalizer's back
        row = orch.run_journal.working_set().get(str(exp.experiment_uuid))
        assert row is None or row["state"] != "active"
