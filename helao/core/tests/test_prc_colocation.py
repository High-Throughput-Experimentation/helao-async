"""Colocated -prc.yml: type, guard, globs, write location, move set."""

import asyncio
from pathlib import Path

import pytest

from helao.core.drivers.data.sync_driver import ABR_MAP, HelaoYml


def _tree(tmp_path: Path) -> Path:
    """A minimal RUNS_FINISHED experiment directory with one action child."""
    exp_dir = tmp_path / "RUNS_FINISHED" / "26.35" / "0828" / "seqdir" / "expdir"
    act_dir = exp_dir / "0__0__SIM__do_thing"
    act_dir.mkdir(parents=True)
    (exp_dir / "260828.120000000000-exp.yml").write_text(
        "experiment_uuid: 06a5a2d6-b26c-7019-8000-4c2d967e5df1\n"
        "experiment_name: SIM_exp\n"
    )
    (act_dir / "260828.120001000000-act.yml").write_text(
        "action_uuid: 06a5a2d6-b26c-7673-8000-9f38fe556fd6\naction_order: 0\n"
    )
    return exp_dir


def test_prc_is_a_known_record_type(tmp_path):
    assert ABR_MAP["prc"] == "process"
    exp_dir = _tree(tmp_path)
    prc = exp_dir / "0__06a5a2d6-b26c-7019-8000-4c2d967e5df1__SIM_exp-prc.yml"
    prc.write_text("process_uuid: 06a5a2d6-b26c-7019-8000-4c2d967e5df1\n")
    assert HelaoYml(prc).type == "process"


class _FakeQueue:
    def __init__(self):
        self.items = []

    async def put(self, item):
        self.items.append(item)


class _StubSyncer:
    """Just enough of SyncDriver to exercise enqueue_yml's guard."""

    def __init__(self):
        self.task_queue = _FakeQueue()
        self.task_set = set()
        self.running_tasks = {}

    from helao.core.drivers.data.sync_driver import SyncDriver

    enqueue_yml = SyncDriver.enqueue_yml


def test_enqueue_yml_refuses_a_process_yml(tmp_path):
    exp_dir = _tree(tmp_path)
    prc = exp_dir / "0__06a5a2d6-b26c-7019-8000-4c2d967e5df1__SIM_exp-prc.yml"
    prc.write_text("process_uuid: 06a5a2d6-b26c-7019-8000-4c2d967e5df1\n")
    syncer = _StubSyncer()
    asyncio.run(syncer.enqueue_yml(prc, rank=-1))
    assert syncer.task_queue.items == []
    assert syncer.task_set == set()


def test_enqueue_yml_still_accepts_an_action_yml(tmp_path):
    exp_dir = _tree(tmp_path)
    act = next((exp_dir / "0__0__SIM__do_thing").glob("*-act.yml"))
    syncer = _StubSyncer()
    asyncio.run(syncer.enqueue_yml(act, rank=0))
    assert len(syncer.task_queue.items) == 1
