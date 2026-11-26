"""An E-STOP landing inside the plan-sidecar write must end the step cleanly."""

import asyncio
import logging
from types import SimpleNamespace

import pytest

from helao.core.error import ErrorCodes
from helao.hexagon.domain.models import LoopStatus
from helao.hexagon.tests.test_estop_fixes import _SeqOrch


class _SeqPlanOrch(_SeqOrch):
    def __init__(self, write):
        super().__init__(n_planned=0)
        self._write = write

    async def write_seq_plan(self, seq):
        return await self._write(self, seq)


class _ExpOrch:
    def __init__(self, write):
        self.active_experiment = SimpleNamespace(aux_files=[], experiment_uuid="u")
        self.action_dq = []
        self.globalstatusmodel = SimpleNamespace(loop_state=LoopStatus.started)
        self.active_sequence = "SEQ"
        self.experiment_dq = ["e"]
        self.verify_plates = False
        self.use_sync = False
        self._write = write

    async def write_exp_plan(self, exp, acts):
        return await self._write(self, exp)


def _exp_runner(orch, monkeypatch):
    from helao.hexagon.app.orch_dispatch import DispatchRunner

    r = DispatchRunner(orch)

    async def _ok_stage():
        return None

    async def _expand():
        return None, ["act"]

    async def _upload():
        assert orch.active_experiment is not None, "upload read a cleared record"

    monkeypatch.setattr(r, "_stage_experiment", _ok_stage)
    monkeypatch.setattr(r, "_expand_experiment_actions", _expand)
    monkeypatch.setattr(r, "_upload_exp_meta_s3", _upload)
    monkeypatch.setattr(r, "_verify_experiment_plate", lambda: _ok_stage())
    return r


@pytest.mark.asyncio
async def test_estop_during_seq_plan_write_returns_estop():
    async def write(o, seq):
        await asyncio.sleep(0)
        o.active_sequence = None  # estop_finish_active
        return "x-seq.plan.json"

    orch = _SeqPlanOrch(write)
    rc = await asyncio.wait_for(orch.dispatch_runner.dispatch_sequence(), 3.0)
    assert rc is ErrorCodes.estop


@pytest.mark.asyncio
async def test_estop_during_exp_plan_write_returns_estop(monkeypatch):
    async def write(o, exp):
        await asyncio.sleep(0)
        o.active_experiment = None
        return "x-exp.plan.json"

    orch = _ExpOrch(write)
    rc = await _exp_runner(orch, monkeypatch).dispatch_experiment()
    assert rc is ErrorCodes.estop


@pytest.mark.asyncio
async def test_failed_seq_plan_write_does_not_stop_the_run(caplog):
    async def write(o, seq):
        raise OSError("disk full")

    orch = _SeqPlanOrch(write)
    with caplog.at_level(logging.ERROR):
        rc = await asyncio.wait_for(orch.dispatch_runner.dispatch_sequence(), 3.0)
    assert rc is ErrorCodes.none
    assert any("plan sidecar" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_failed_exp_plan_write_does_not_stop_the_run(monkeypatch, caplog):
    async def write(o, exp):
        raise OSError("disk full")

    orch = _ExpOrch(write)
    with caplog.at_level(logging.ERROR):
        rc = await _exp_runner(orch, monkeypatch).dispatch_experiment()
    assert rc is ErrorCodes.none
    assert orch.action_dq == ["act"]
