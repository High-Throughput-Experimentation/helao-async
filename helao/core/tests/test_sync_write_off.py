"""Write-off marker, Progress helpers and sync gates (sync write-off spec 4.1-4.3)."""

import asyncio
import json
from datetime import datetime

import pytest

import helao.core.drivers.data.sync_driver as legacy_mod
import helao.hexagon.adapters.native.sync_driver as native_mod
from helao.core.models.helaodirs import HelaoDirs
from helao.core.models.process import ProcessModel
from helao.core.models.run_dir import RunDir
from helao.helpers.run_state import _prg_is_complete, _prg_is_quarantined
from helao.helpers.yml_tools import yml_load
from helao.hexagon.tests.sync_fixtures import (
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


# --- SyncDriver.write_off (spec 4.4-4.5) -----------------------------------


def _alerts(monkeypatch, mod):
    got = []
    monkeypatch.setattr(mod.LOGGER, "alert", lambda msg, *a, **k: got.append(msg))
    return got


def _journal_driver(tmp_path, cls):
    """A driver with a ``states_root``: the ledger and the run journal exist."""
    hd = HelaoDirs(
        root=tmp_path,
        save_root=tmp_path / RunDir.ACTIVE.value,
        process_root=tmp_path / "PROCESSES",
        states_root=tmp_path / "STATES",
    )
    return cls({"aws_bucket": "test-bucket", "max_tasks": 1}, hd)


async def _parked(tmp_path, mod, monkeypatch, strikes=None, runs="RUNS"):
    """``_lost_order_2`` on a journalled driver; the exp is parked by F3.

    ``strikes=0`` disables parking instead. Returns ``(drv, exp_yml, alerts)``,
    with ``alerts`` cleared of the parking alert.
    """
    alerts = _alerts(monkeypatch, mod)
    drv = _journal_driver(tmp_path, mod.SyncDriver)
    if strikes is not None:
        drv.quarantine_strikes = strikes
    exp_yml = make_exp_tree(tmp_path, runs, mk_uuid(1), process_order_groups=GROUPS)
    acts = {o: make_action(exp_yml, o, process_finish=o in (1, 3)) for o in (0, 1, 3)}

    async def no_requeue(upath, rank=0, rank_limit=-5):
        return None

    real_enqueue = drv.enqueue_yml
    drv.enqueue_yml = no_requeue
    for o in (0, 1, 3):
        await asyncio.wait_for(drv.sync_yml(yml_path=acts[o]), 15)
    drv.enqueue_yml = real_enqueue
    assert await asyncio.wait_for(drv.sync_yml(exp_yml, rank=1), 15) is False
    alerts.clear()
    return drv, exp_yml, alerts


def _hold_enqueue(drv):
    """Replace ``enqueue_yml`` with a recorder, so the exp stays unsynced."""
    calls = []

    async def rec(upath, rank=0, rank_limit=-5):
        calls.append(str(upath))

    drv.enqueue_yml = rec
    return calls


def _ledger(tmp_path):
    path = tmp_path / "STATES" / "sync_write_off.jsonl"
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_write_off_ships_experiment_and_sequence(tmp_path, mod, monkeypatch):
    drv, exp_yml, alerts = await _parked(tmp_path, mod, monkeypatch)
    try:
        assert mod.Progress(exp_yml).is_quarantined
        seq_yml = exp_yml.parent.parent / f"{ts(0)}-seq.yml"
        write_yml(seq_yml, {"sequence_uuid": mk_uuid(999), "sequence_name": "s"})
        res = await drv.write_off(str(exp_yml), "estop", "op")
        assert res == {"ok": True, "status": "written off", "groups": {1: [2]}}
        await drain(drv, timeout=15)
        prg = exp_yml.with_suffix(".prg")
        assert _prg_is_complete(prg)
        block = yml_load(prg, fast=True)["write_off"]
        assert (block["operator"], block["reason"]) == ("op", "estop")
        assert block["groups"] == {1: [2]} and block["at"]
        assert _prg_is_complete(seq_yml.with_suffix(".prg"))
        assert drv.quarantined() == []
        (msg,) = alerts
        assert exp_yml.name in msg and "op" in msg and "estop" in msg
        assert [x["action"] for x in _ledger(tmp_path)] == ["write_off"]
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_write_off_marks_the_pushed_process(tmp_path, mod, monkeypatch):
    """End to end: the block the route writes must carry int pidx keys, or
    ``Progress.written_off`` finds nothing and the group is never marked."""
    drv, exp_yml, _ = await _parked(tmp_path, mod, monkeypatch)
    try:
        await drv.write_off(str(exp_yml), "estop", "op")
        await drain(drv, timeout=15)
        assert _prg_is_complete(exp_yml.with_suffix(".prg"))
        by_group = {}
        for p in exp_yml.parent.glob("*-prc.yml"):
            by_group[int(p.name.split("__")[0])] = yml_load(p, fast=True)
        assert by_group[1]["missing_action_orders"] == [2]
        assert "missing_action_orders" not in by_group[0]
        # the ledger line is JSON, so its keys are strings; the .prg keys are not
        assert _ledger(tmp_path)[0]["groups"] == {"1": [2]}
        groups = yml_load(exp_yml.with_suffix(".prg"), fast=True)["write_off"]["groups"]
        assert list(groups) == [1]
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_write_off_repushes_a_backlog_group_with_the_marker(
    tmp_path, mod, monkeypatch
):
    _alerts(monkeypatch, mod)
    drv = _journal_driver(tmp_path, mod.SyncDriver)
    exp_yml = make_exp_tree(tmp_path, "RUNS", mk_uuid(1), process_order_groups=GROUPS)
    acts = {o: make_action(exp_yml, o, process_finish=o in (1, 3)) for o in (0, 1, 3)}
    held = _hold_enqueue(drv)
    try:
        for o in (0, 1, 3):
            await asyncio.wait_for(drv.sync_yml(yml_path=acts[o]), 15)
        # a pre-F3 forced push: the partial group went to S3 with no marker
        prog = drv.reconcile_processes(mod.Progress(exp_yml))
        meta = prog.dict["process_metas"][1]
        uuid = meta["process_uuid"]
        old = exp_yml.parent / f"1__{uuid}__{meta['technique_name']}-prc.yml"
        write_yml(old, ProcessModel.model_validate(meta).clean_dict(strip_private=True))
        prog.dict["process_s3"] = [0, 1]
        prog.write_dict()
        assert mod.Progress(exp_yml).add_strike("boom", 1, 0, NOW) is True

        bodies = []
        real_to_s3 = drv.to_s3

        async def spy(msg, target, *a, **k):
            if isinstance(msg, dict) and target == f"process/{uuid}.json":
                bodies.append(msg)
            return await real_to_s3(msg, target, *a, **k)

        drv.to_s3 = spy
        held.clear()
        res = await drv.write_off(str(exp_yml), "estop", "op")
        assert res["status"] == "written off" and held == [str(exp_yml)]
        del drv.enqueue_yml  # back to the real one
        await drv.enqueue_yml(exp_yml, 1)
        await drain(drv, timeout=15)
        assert yml_load(old, fast=True)["missing_action_orders"] == [2]
        assert bodies and all(b["missing_action_orders"] == [2] for b in bodies)
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_write_off_refuses_strike_quarantine(tmp_path, mod, monkeypatch):
    _alerts(monkeypatch, mod)
    drv = _journal_driver(tmp_path, mod.SyncDriver)
    exp_yml = make_exp_tree(tmp_path, "RUNS", mk_uuid(1), process_order_groups=GROUPS)
    _hold_enqueue(drv)  # the actions must not carry the exp through a sync
    try:
        for o in range(4):
            await asyncio.wait_for(
                drv.sync_yml(
                    yml_path=make_action(exp_yml, o, process_finish=o in (1, 3))
                ),
                15,
            )
        assert mod.Progress(exp_yml).add_strike("boom", 1, 0, NOW) is True
        prg = exp_yml.with_suffix(".prg")
        before = prg.read_bytes()
        res = await drv.write_off(str(exp_yml), "r", "op")
        assert res["ok"] is False and "/finish_yml" in res["error"]
        assert prg.read_bytes() == before
        assert _ledger(tmp_path) == []
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_write_off_refuses_an_incomplete_but_unparked_exp(
    tmp_path, mod, monkeypatch
):
    drv, exp_yml, _ = await _parked(tmp_path, mod, monkeypatch, strikes=0)
    try:
        prg = exp_yml.with_suffix(".prg")
        assert not _prg_is_quarantined(prg)
        before = prg.read_bytes()
        res = await drv.write_off(str(exp_yml), "r", "op")
        assert res["ok"] is False and "not in sync quarantine" in res["error"]
        assert prg.read_bytes() == before and "\nwrite_off:" not in prg.read_text()
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_write_off_refuses_bad_args_without_touching_disk(
    tmp_path, mod, monkeypatch
):
    drv, exp_yml, alerts = await _parked(tmp_path, mod, monkeypatch)
    try:
        prg = exp_yml.with_suffix(".prg")
        before = prg.read_bytes()
        act = make_action(exp_yml, 0)
        out_dir = tmp_path.parent / f"{tmp_path.name}_outside"
        outside = out_dir / f"{ts(0)}-exp.yml"
        write_yml(outside, {"experiment_uuid": mk_uuid(7)})
        outside.with_suffix(".prg").write_text("yml: x\n", encoding="utf-8")
        # under root, so the missing .prg is the only reason to refuse it
        under_root = exp_yml.parent / f"{ts(9)}-exp.yml"
        write_yml(under_root, {"experiment_uuid": mk_uuid(3)})
        cases = [
            (exp_yml, "  ", "op"),
            (exp_yml, "r", ""),
            (exp_yml, "x" * 501, "op"),
            (exp_yml, "r", "o" * 81),
            (act, "r", "op"),
            (outside, "r", "op"),
            (under_root, "r", "op"),
        ]
        for path, reason, operator in cases:
            res = await drv.write_off(str(path), reason, operator)
            assert res["ok"] is False, (path.name, reason[:5], operator[:5])
        assert prg.read_bytes() == before
        assert not under_root.with_suffix(".prg").exists()
        assert not outside.with_suffix(".prg").read_text().count("write_off")
        assert alerts == [] and _ledger(tmp_path) == []
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_write_off_is_idempotent(tmp_path, mod, monkeypatch):
    drv, exp_yml, alerts = await _parked(tmp_path, mod, monkeypatch)
    try:
        real_enqueue = drv.enqueue_yml
        held = _hold_enqueue(drv)
        first = await drv.write_off(str(exp_yml), "estop", "op")
        assert first["status"] == "written off"
        prg = exp_yml.with_suffix(".prg")
        before = prg.read_bytes()
        at = yml_load(prg, fast=True)["write_off"]["at"]
        again = await drv.write_off(str(exp_yml), "other reason", "someone")
        assert again == {"ok": True, "status": "requeued", "at": at, "operator": "op"}
        assert prg.read_bytes() == before
        assert [x["action"] for x in _ledger(tmp_path)] == ["write_off", "requeue"]
        assert len(alerts) == 1 and len(held) == 2
        drv.enqueue_yml = real_enqueue
        await drv.enqueue_yml(exp_yml, 1)
        await drain(drv, timeout=15)
        assert _prg_is_complete(prg)
        held = _hold_enqueue(drv)
        done = await drv.write_off(str(exp_yml), "r", "op")
        assert done == {"ok": True, "status": "already synced"}
        assert held == []  # a no-op must not re-queue
        assert len(_ledger(tmp_path)) == 2 and len(alerts) == 1
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_ledger_failure_writes_no_block(tmp_path, mod, monkeypatch):
    drv, exp_yml, alerts = await _parked(tmp_path, mod, monkeypatch)
    try:

        def boom(entry):
            raise OSError("disk full")

        monkeypatch.setattr(drv, "_append_write_off_ledger", boom)
        prg = exp_yml.with_suffix(".prg")
        res = await drv.write_off(str(exp_yml), "estop", "op")
        assert res["ok"] is False
        assert _prg_is_quarantined(prg) and "\nwrite_off:" not in prg.read_text()
        assert alerts == []
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_reason_and_operator_are_one_line(tmp_path, mod, monkeypatch):
    drv, exp_yml, _ = await _parked(tmp_path, mod, monkeypatch)
    try:
        _hold_enqueue(drv)
        res = await drv.write_off(str(exp_yml), "a\n  quarantined_at: 2026", " o\tp ")
        assert res["status"] == "written off"
        prg = exp_yml.with_suffix(".prg")
        block = yml_load(prg, fast=True)["write_off"]
        assert block["reason"] == "a quarantined_at: 2026"
        assert block["operator"] == "o p"
        assert _prg_is_quarantined(prg) is False
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_write_off_waits_for_the_experiment_lock(tmp_path, mod, monkeypatch):
    drv, exp_yml, _ = await _parked(tmp_path, mod, monkeypatch, runs="RUNS_FINISHED")
    try:
        _hold_enqueue(drv)
        _, exp_key = drv._node_keys(exp_yml)
        async with drv._get_exp_lock(exp_key):
            task = asyncio.create_task(drv.write_off(str(exp_yml), "r", "op"))
            await asyncio.sleep(0.3)
            assert not task.done()
            assert "\nwrite_off:" not in exp_yml.with_suffix(".prg").read_text()
        res = await asyncio.wait_for(task, 15)
        assert res["status"] == "written off"
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_requeue_ledger_failure_is_ok_false_and_does_not_enqueue(
    tmp_path, mod, monkeypatch
):
    drv, exp_yml, _ = await _parked(tmp_path, mod, monkeypatch)
    try:
        held = _hold_enqueue(drv)
        assert (await drv.write_off(str(exp_yml), "r", "op"))["ok"] is True
        held.clear()

        def boom(entry):
            raise OSError("disk full")

        monkeypatch.setattr(drv, "_append_write_off_ledger", boom)
        res = await drv.write_off(str(exp_yml), "r", "op")
        assert res["ok"] is False and held == []
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_tail_failure_is_a_warning_not_a_raise(tmp_path, mod, monkeypatch):
    drv, exp_yml, _ = await _parked(tmp_path, mod, monkeypatch)
    try:

        async def boom(upath, rank=0, rank_limit=-5):
            raise OSError("journal gone")

        drv.enqueue_yml = boom
        res = await drv.write_off(str(exp_yml), "r", "op")
        assert res["ok"] is True and res["status"] == "written off"
        assert "not re-queued" in res["warning"]
        assert "\nwrite_off:" in exp_yml.with_suffix(".prg").read_text()
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_ledger_creates_a_missing_states_dir(tmp_path, mod, monkeypatch):
    drv, exp_yml, _ = await _parked(tmp_path, mod, monkeypatch)
    try:
        _hold_enqueue(drv)
        (tmp_path / "STATES" / "sync_write_off.jsonl").unlink(missing_ok=True)
        for p in (tmp_path / "STATES").iterdir():
            p.unlink()
        (tmp_path / "STATES").rmdir()
        assert (await drv.write_off(str(exp_yml), "r", "op"))["ok"] is True
        assert len(_ledger(tmp_path)) == 1
    finally:
        await teardown_driver(drv)
