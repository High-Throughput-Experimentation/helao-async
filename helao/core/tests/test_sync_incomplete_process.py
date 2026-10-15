"""Immediate quarantine of a permanently incomplete process group.

An experiment whose process group lists an action_order that has NO action
record anywhere under the experiment dir can never complete: the record was lost
(e.g. at a crash). It is parked at first detection instead of failing for a day
(sync quarantine spec, 2026-10-14 note).
"""

import asyncio

import pytest

import helao.core.drivers.data.sync_driver as legacy_mod
import helao.hexagon.adapters.native.sync_driver as native_mod
from helao.hexagon.tests.sync_fixtures import (
    act_meta,
    drain,
    make_action,
    make_exp_tree,
    make_sync_driver,
    mk_uuid,
    teardown_driver,
    ts,
    write_yml,
)

MODS = [legacy_mod, native_mod]
GROUPS = {0: [0, 1], 1: [2, 3]}


@pytest.fixture(autouse=True)
def _hermetic_aws(monkeypatch):
    monkeypatch.delenv("AWS_CONFIG_PATH", raising=False)


def _alerts(monkeypatch, mod):
    got = []
    monkeypatch.setattr(mod.LOGGER, "alert", lambda msg, *a, **k: got.append(msg))
    return got


async def _lost_order_2(tmp_path, mod, monkeypatch):
    """Experiment with groups {0:[0,1], 1:[2,3]}; actions 0, 1, 3 synced, 2 lost."""
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


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_lost_action_quarantines_on_first_detection(tmp_path, mod, monkeypatch):
    alerts = _alerts(monkeypatch, mod)
    drv, exp_yml = await _lost_order_2(tmp_path, mod, monkeypatch)
    try:
        assert await asyncio.wait_for(drv.sync_yml(exp_yml, rank=1), 15) is False
        prog = mod.Progress(exp_yml)
        assert prog.is_quarantined
        err = prog.quarantine["last_error"]
        assert "group 1" in err and "[2]" in err
        assert prog.dict["process_metas"][1]["process_uuid"] in err
        assert len(alerts) == 1
        # a second pass does not alert again, and the gate refuses re-enqueue
        await asyncio.wait_for(drv.sync_yml(exp_yml, rank=0), 15)
        assert len(alerts) == 1
        await drv.enqueue_yml(exp_yml, 1)
        assert drv.task_queue.qsize() == 0 and not drv.task_set
        # the blocking hook never ran, so it never raised
        assert "s3_upload" not in (mod.Progress(exp_yml).dict.get("hooks") or {})
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_no_burst_from_the_sequence_either(tmp_path, mod, monkeypatch):
    _alerts(monkeypatch, mod)
    drv, exp_yml = await _lost_order_2(tmp_path, mod, monkeypatch)
    try:
        seq_yml = exp_yml.parent.parent / f"{ts(0)}-seq.yml"
        write_yml(seq_yml, {"sequence_uuid": mk_uuid(999), "sequence_name": "test_seq"})
        calls = []
        real = drv.sync_yml

        async def counting(yml_path, rank=5, **kw):
            calls.append(yml_path.name)
            return await real(yml_path=yml_path, rank=rank, **kw)

        drv.sync_yml = counting
        await drv.enqueue_yml(seq_yml, 2)
        await drain(drv, timeout=15)
        assert calls.count(exp_yml.name) == 1
        assert calls.count(seq_yml.name) <= 2
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_a_record_that_exists_but_is_unsynced_is_not_quarantined(
    tmp_path, mod, monkeypatch
):
    alerts = _alerts(monkeypatch, mod)
    drv, exp_yml = await _lost_order_2(tmp_path, mod, monkeypatch)
    try:
        make_action(exp_yml, 2)  # present, finished, not yet synced
        prog = drv.reconcile_processes(mod.Progress(exp_yml))
        assert drv._incomplete_process_groups(prog) == {}
        await asyncio.wait_for(drv.sync_yml(exp_yml, rank=1), 15)
        assert not mod.Progress(exp_yml).is_quarantined
        assert alerts == []
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_an_unfinished_child_blocks_quarantine(tmp_path, mod, monkeypatch):
    alerts = _alerts(monkeypatch, mod)
    drv, exp_yml = await _lost_order_2(tmp_path, mod, monkeypatch)
    try:
        running = exp_yml.parent / "4__0__srv__test_action" / f"{ts(5)}-act.yml"
        write_yml(running, {**act_meta(4), "action_status": ["active"]})
        assert await asyncio.wait_for(drv.sync_yml(exp_yml, rank=1), 15) is False
        assert not mod.Progress(exp_yml).is_quarantined
        assert alerts == []
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_release_then_a_later_pass_retries(tmp_path, mod, monkeypatch):
    alerts = _alerts(monkeypatch, mod)
    drv, exp_yml = await _lost_order_2(tmp_path, mod, monkeypatch)
    try:
        await asyncio.wait_for(drv.sync_yml(exp_yml, rank=1), 15)
        assert mod.Progress(exp_yml).is_quarantined
        # what POST /finish_yml does
        assert drv.release_quarantine(str(exp_yml)) is True
        assert mod.Progress(exp_yml).quarantine is None
        await drv.enqueue_yml(exp_yml, 1)
        await drain(drv, timeout=15)
        # still lost: the retry ran and parked it again
        assert mod.Progress(exp_yml).is_quarantined
        assert len(alerts) == 2
        # operator restores the record; the next release lets the experiment ship
        drv.release_quarantine(str(exp_yml))
        act2 = make_action(exp_yml, 2)
        await asyncio.wait_for(drv.sync_yml(act2), 15)
        result = await asyncio.wait_for(drv.sync_yml(exp_yml, rank=1), 15)
        assert isinstance(result, dict)
        assert mod.Progress(exp_yml).quarantine is None
        assert len(alerts) == 2
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_an_existing_record_the_reconcile_skips_is_still_a_record(
    tmp_path, mod, monkeypatch
):
    """A record with no process_contrib never folds into process_actions_done,
    but it exists: the group stays on ordinary retry, not quarantine."""
    drv, exp_yml = await _lost_order_2(tmp_path, mod, monkeypatch)
    try:
        path = exp_yml.parent / "2__0__srv__test_action" / f"{ts(3)}-act.yml"
        write_yml(path, {**act_meta(2), "process_contrib": []})
        prog = drv.reconcile_processes(mod.Progress(exp_yml))
        assert 2 not in prog.dict["process_actions_done"]
        assert drv._incomplete_process_groups(prog) == {}
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_a_group_with_no_synced_action_is_a_phantom_not_incomplete(
    tmp_path, mod, monkeypatch
):
    drv = make_sync_driver(tmp_path, mod.SyncDriver)
    try:
        exp_yml = make_exp_tree(
            tmp_path, "RUNS", mk_uuid(1), process_order_groups=GROUPS
        )
        make_action(exp_yml, 0)
        make_action(exp_yml, 1)
        prog = drv.reconcile_processes(mod.Progress(exp_yml))
        assert drv._incomplete_process_groups(prog) == {}
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_alert_names_the_causes_and_the_repark(tmp_path, mod, monkeypatch):
    alerts = _alerts(monkeypatch, mod)
    drv, exp_yml = await _lost_order_2(tmp_path, mod, monkeypatch)
    try:
        await asyncio.wait_for(drv.sync_yml(exp_yml, rank=1), 15)
        (msg,) = alerts
        assert "operator skip or E-STOP" in msg and "lost at a crash" in msg
        assert "parked again" in msg and "write-off" in msg
        assert "failed passes" not in msg and "Fix the cause" not in msg
        assert (
            "operator skip or E-STOP" in mod.Progress(exp_yml).quarantine["last_error"]
        )
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_parking_disabled_still_logs_the_incomplete_group(
    tmp_path, mod, monkeypatch
):
    alerts = _alerts(monkeypatch, mod)
    errors = []
    monkeypatch.setattr(mod.LOGGER, "error", lambda msg, *a, **k: errors.append(msg))
    drv, exp_yml = await _lost_order_2(tmp_path, mod, monkeypatch)
    drv.quarantine_strikes = 0
    try:
        await asyncio.wait_for(drv.sync_yml(exp_yml, rank=1), 15)
        assert not mod.Progress(exp_yml).is_quarantined and alerts == []
        assert any("group 1" in e and "[2]" in e for e in errors)
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_a_legacy_experiment_never_qualifies(tmp_path, mod, monkeypatch):
    drv = make_sync_driver(tmp_path, mod.SyncDriver)
    try:
        exp_yml = make_exp_tree(tmp_path, "RUNS", mk_uuid(1))  # no groups: legacy
        make_action(exp_yml, 0)
        make_action(exp_yml, 1, process_finish=True)
        prog = drv.reconcile_processes(mod.Progress(exp_yml))
        assert prog.dict["legacy_experiment"] is True
        # a partly-synced group with an absent order, as a non-legacy one would be
        prog.dict["process_groups"][0] = [0, 1, 7]
        prog.dict["process_actions_done"].pop(1)
        assert drv._incomplete_process_groups(prog) == {}
    finally:
        await teardown_driver(drv)
