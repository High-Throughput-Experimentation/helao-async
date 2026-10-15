"""Write-off marker, Progress helpers and sync gates (sync write-off spec 4.1-4.3)."""

import asyncio
from datetime import datetime

import pytest

import helao.core.drivers.data.sync_driver as legacy_mod
import helao.hexagon.adapters.native.sync_driver as native_mod
from helao.core.models.process import ProcessModel
from helao.hexagon.tests.sync_fixtures import (
    make_action,
    make_exp_tree,
    make_sync_driver,
    mk_uuid,
    teardown_driver,
)

MODS = [legacy_mod, native_mod]
GROUPS = {0: [0, 1], 1: [2, 3]}
NOW = datetime(2026, 10, 15, 12, 0, 0)


@pytest.fixture(autouse=True)
def _hermetic_aws(monkeypatch):
    monkeypatch.delenv("AWS_CONFIG_PATH", raising=False)


async def _lost_order_2(tmp_path, mod, monkeypatch):
    """Experiment with groups {0:[0,1], 1:[2,3]}; actions 0, 1, 3 synced, 2 lost."""
    monkeypatch.setattr(mod.LOGGER, "alert", lambda *a, **k: None)
    drv = make_sync_driver(tmp_path, mod.SyncDriver)
    exp_yml = make_exp_tree(tmp_path, "RUNS", mk_uuid(1), process_order_groups=GROUPS)
    acts = {o: make_action(exp_yml, o, process_finish=o in (1, 3)) for o in (0, 1, 3)}

    async def no_requeue(upath, rank=0, rank_limit=-5):
        return None

    real_enqueue = drv.enqueue_yml
    drv.enqueue_yml = no_requeue
    for o in (0, 1, 3):
        await asyncio.wait_for(drv.sync_yml(yml_path=acts[o]), 15)
    drv.enqueue_yml = real_enqueue
    return drv, exp_yml


def test_process_model_carries_missing_orders():
    base = {"process_uuid": mk_uuid(5)}
    got = ProcessModel.model_validate({**base, "missing_action_orders": [2]})
    assert got.clean_dict()["missing_action_orders"] == [2]
    assert "missing_action_orders" not in ProcessModel.model_validate(base).clean_dict()


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_immediate_hint_is_written_and_carried(tmp_path, mod, monkeypatch):
    drv, exp_yml = await _lost_order_2(tmp_path, mod, monkeypatch)
    try:
        prog = mod.Progress(exp_yml)
        assert prog.add_strike("lost", 5, 24, NOW, immediate=True) is True
        assert mod.Progress(exp_yml).quarantine["immediate"] is True
        # a later strike on the parked record keeps the hint
        prog = mod.Progress(exp_yml)
        assert prog.add_strike("lost again", 5, 24, NOW, immediate=True) is False
        assert mod.Progress(exp_yml).quarantine["immediate"] is True
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_strike_threshold_block_has_no_immediate_key(tmp_path, mod, monkeypatch):
    drv, exp_yml = await _lost_order_2(tmp_path, mod, monkeypatch)
    try:
        prog = mod.Progress(exp_yml)
        # n=1: the first counted strike reaches the threshold; age floor 0 h
        assert prog.add_strike("boom", 1, 0, NOW) is True
        block = mod.Progress(exp_yml).quarantine
        assert block["quarantined_at"] and "immediate" not in block
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_written_off_round_trips_and_lists_only_absent_orders(
    tmp_path, mod, monkeypatch
):
    drv, exp_yml = await _lost_order_2(tmp_path, mod, monkeypatch)
    try:
        prog = mod.Progress(exp_yml)
        assert prog.written_off(1) == []
        prog.dict["write_off"] = {
            "at": "2026-10-15T12:00:00",
            "operator": "op",
            "reason": "r",
            "groups": {1: [2]},
        }
        prog.write_dict()
        fresh = mod.Progress(exp_yml)
        assert fresh.written_off(1) == [2]
        assert fresh.written_off(0) == []
        fresh.dict["process_actions_done"][2] = "x-act.yml"
        assert fresh.written_off(1) == []
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_write_off_block_stops_f3_and_marks_only_its_group(
    tmp_path, mod, monkeypatch
):
    drv, exp_yml = await _lost_order_2(tmp_path, mod, monkeypatch)
    try:
        assert await asyncio.wait_for(drv.sync_yml(exp_yml, rank=1), 15) is False
        prog = mod.Progress(exp_yml)
        assert prog.is_quarantined
        prog.dict["write_off"] = {
            "at": "2026-10-15T12:00:00",
            "operator": "op",
            "reason": "r",
            "groups": {1: [2]},
        }
        prog.dict.pop("quarantine")
        for k in ("process_s3", "process_api"):
            prog.dict[k] = [p for p in prog.dict[k] if p not in (0, 1)]
        prog.write_dict()

        bodies = []
        real_to_s3 = drv.to_s3

        async def spy(msg, target, *a, **k):
            if isinstance(msg, dict) and target.startswith("process/"):
                bodies.append(msg)
            return await real_to_s3(msg, target, *a, **k)

        drv.to_s3 = spy
        result = await asyncio.wait_for(drv.sync_yml(exp_yml, rank=1), 15)
        assert isinstance(result, dict)

        by_group = {}
        for p in exp_yml.parent.glob("*-prc.yml"):
            by_group[int(p.name.split("__")[0])] = mod.yml_load(p, fast=True)
        assert by_group[1]["missing_action_orders"] == [2]
        assert "missing_action_orders" not in by_group[0]
        assert any(b.get("missing_action_orders") == [2] for b in bodies)
        g0 = [b for b in bodies if b.get("process_group_index") == 0]
        assert g0 and all("missing_action_orders" not in b for b in g0)
        assert "synced: true" in exp_yml.with_suffix(".prg").read_text()
    finally:
        await teardown_driver(drv)
