"""Sync quarantine (spec docs/superpowers/specs/2026-10-14-sync-quarantine-design.md)."""

import asyncio
import textwrap
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import helao.core.drivers.data.sync_driver as legacy_mod
import helao.hexagon.adapters.native.sync_driver as native_mod
from helao.core.models.helaodirs import HelaoDirs
from helao.core.models.run_dir import RunDir
from helao.helpers.run_state import (
    QUARANTINED,
    UNSYNCED,
    _prg_is_quarantined,
    rebuild_from_tree,
)
from helao.hexagon.tests.sync_fixtures import (
    drain,
    make_action,
    make_exp_tree,
    make_sync_driver,
    mk_uuid,
    teardown_driver,
)

MODS = [legacy_mod, native_mod]
T0 = datetime(2026, 10, 14, 9, 0, 0)


def _write_prg(prg: Path, quarantined_at) -> None:
    qa = "null" if quarantined_at is None else f"'{quarantined_at}'"
    prg.write_text(
        textwrap.dedent(f"""\
            yml: x
            api: false
            s3: false
            quarantine:
              strikes: 5
              first_failed: '2026-10-13T09:00:00'
              last_failed: '2026-10-14T09:00:00'
              last_error: 'RuntimeError: boom'
              quarantined_at: {qa}
            """),
        encoding="utf-8",
    )


def test_prg_is_quarantined_reads_the_flag(tmp_path):
    prg = tmp_path / "a-act.prg"
    _write_prg(prg, "2026-10-14T09:00:00")
    assert _prg_is_quarantined(prg) is True


def test_a_block_without_quarantined_at_is_not_quarantined(tmp_path):
    prg = tmp_path / "a-act.prg"
    _write_prg(prg, None)
    assert _prg_is_quarantined(prg) is False


def test_a_missing_prg_is_not_quarantined(tmp_path):
    assert _prg_is_quarantined(tmp_path / "nope-act.prg") is False


def test_rebuild_reports_a_quarantined_record_as_quarantined(tmp_path):
    exp_yml = make_exp_tree(tmp_path, "RUNS", mk_uuid(1))
    act_yml = make_action(exp_yml, 0)
    _write_prg(act_yml.with_suffix(".prg"), "2026-10-14T09:00:00")
    journal = rebuild_from_tree(tmp_path / "RUNS", tmp_path / "STATES", "SYNC")
    states = {r["kind"]: r["state"] for r in journal.working_set().values()}
    assert states == {"experiment": UNSYNCED, "action": QUARANTINED}


def _block(strikes, first_failed):
    return {
        "strikes": strikes,
        "first_failed": first_failed.isoformat(timespec="seconds"),
    }


@pytest.mark.parametrize("mod", MODS)
def test_quarantine_due_needs_both_strikes_and_age(mod):
    due = mod.quarantine_due
    assert due(_block(4, T0), 5, 24, T0 + timedelta(hours=48)) is False
    assert due(_block(5, T0), 5, 24, T0 + timedelta(hours=23)) is False
    assert due(_block(5, T0), 5, 24, T0 + timedelta(hours=24)) is True
    assert due(_block(9, T0), 0, 24, T0 + timedelta(hours=48)) is False


@pytest.mark.parametrize("mod", MODS)
def test_outage_inside_the_window_never_quarantines(tmp_path, mod):
    act_yml = make_action(make_exp_tree(tmp_path, "RUNS", mk_uuid(1)), 0)
    prog = mod.Progress(act_yml)
    for i in range(10):
        assert prog.add_strike("S3 down", 5, 24, T0 + timedelta(hours=i)) is False
    assert prog.is_quarantined is False
    assert mod.Progress(act_yml).quarantine["strikes"] == 10


@pytest.mark.parametrize("mod", MODS)
def test_the_crossing_strike_returns_true_exactly_once(tmp_path, mod):
    act_yml = make_action(make_exp_tree(tmp_path, "RUNS", mk_uuid(1)), 0)
    prog = mod.Progress(act_yml)
    results = [
        prog.add_strike("boom", 5, 24, T0 + timedelta(hours=h))
        for h in (0, 1, 2, 3, 25, 26)
    ]
    assert results == [False, False, False, False, True, False]
    reread = mod.Progress(act_yml)
    assert reread.is_quarantined is True
    assert reread.quarantine["first_failed"] == T0.isoformat(timespec="seconds")
    assert reread.quarantine["last_error"] == "boom"


@pytest.mark.parametrize("mod", MODS)
def test_a_burst_inside_the_gap_counts_once(tmp_path, mod):
    act_yml = make_action(make_exp_tree(tmp_path, "RUNS", mk_uuid(1)), 0)
    prog = mod.Progress(act_yml)
    for minutes, err in ((0, "e1"), (10, "e2"), (50, "e3")):
        prog.add_strike(err, 5, 24, T0 + timedelta(minutes=minutes))
    block = mod.Progress(act_yml).quarantine
    assert block["strikes"] == 1
    assert block["last_failed"] == T0.isoformat(timespec="seconds")
    assert block["last_error"] == "e3"
    prog.add_strike("e4", 5, 24, T0 + timedelta(minutes=61))
    assert mod.Progress(act_yml).quarantine["strikes"] == 2


def test_a_folded_last_error_cannot_fake_quarantine(tmp_path):
    from helao.helpers.run_state import _prg_is_quarantined

    for mod in MODS:
        act_yml = make_action(
            make_exp_tree(tmp_path / mod.__name__, "RUNS", mk_uuid(1)), 0
        )
        mod.Progress(act_yml).add_strike(
            "E" * 66 + " quarantined_at: 2026-01-01 " + "y " * 40, 5, 24, T0
        )
        # Field order now puts quarantined_at first, which alone defeats the
        # fake; put last_error first, as pre-fix sidecars had it, so the
        # indent anchor is what this test exercises.
        prog = mod.Progress(act_yml)
        blk = prog.quarantine
        prog.dict["quarantine"] = {
            "last_error": blk["last_error"],
            **{k: v for k, v in blk.items() if k != "last_error"},
        }
        prog.write_dict()
        prg = act_yml.with_suffix(".prg")
        lines = [ln.strip() for ln in prg.read_text(encoding="utf-8").splitlines()]
        assert any(ln.startswith("quarantined_at: 2026-01-01") for ln in lines)
        assert _prg_is_quarantined(prg) is False


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_a_shipped_record_is_never_struck(tmp_path, mod):
    drv = make_sync_driver(tmp_path, mod.SyncDriver, QUICK)
    try:
        act_yml = make_action(make_exp_tree(tmp_path, "RUNS", mk_uuid(1)), 0)
        prog = mod.Progress(act_yml)
        prog.dict["synced"] = True
        prog.write_dict()
        await drv._strike(act_yml, "boom")
        assert mod.Progress(act_yml).quarantine is None
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
def test_clear_quarantine_removes_the_block(tmp_path, mod):
    act_yml = make_action(make_exp_tree(tmp_path, "RUNS", mk_uuid(1)), 0)
    prog = mod.Progress(act_yml)
    prog.add_strike("boom", 1, 0, T0)
    assert prog.is_quarantined is True
    prog.clear_quarantine()
    assert mod.Progress(act_yml).quarantine is None


@pytest.mark.parametrize("mod", MODS)
def test_last_error_is_truncated(tmp_path, mod):
    act_yml = make_action(make_exp_tree(tmp_path, "RUNS", mk_uuid(1)), 0)
    prog = mod.Progress(act_yml)
    prog.add_strike("x" * 5000, 5, 24, T0)
    assert (
        len(mod.Progress(act_yml).quarantine["last_error"])
        == mod.QUARANTINE_ERROR_CHARS
    )


@pytest.mark.parametrize("mod", MODS)
def test_add_strike_recovers_from_a_malformed_block(tmp_path, mod):
    act_yml = make_action(make_exp_tree(tmp_path, "RUNS", mk_uuid(1)), 0)
    prog = mod.Progress(act_yml)
    prog.dict["quarantine"] = {"strikes": "lots", "first_failed": "not a date"}
    prog.write_dict()
    assert prog.add_strike("boom", 5, 24, T0) is False
    block = mod.Progress(act_yml).quarantine
    assert block["strikes"] == 1
    assert block["first_failed"] == T0.isoformat(timespec="seconds")


FAILING_HOOK = """
from helao.core.hooks import FinishHook
class Hook(FinishHook):
    blocking = True
    phase = "postfinish"
    async def run(self, ctx):
        raise RuntimeError("push failed")
"""

QUICK = {"quarantine_strikes": 1, "quarantine_hours": 0}


def _driver_with_journal(tmp_path, cls, cfg_extra=None, postfinish_hooks=None):
    hd = HelaoDirs(
        root=tmp_path,
        save_root=tmp_path / RunDir.ACTIVE.value,
        process_root=tmp_path / "PROCESSES",
        states_root=tmp_path / "STATES",
    )
    cfg = {"aws_bucket": "test-bucket", "max_tasks": 1, **(cfg_extra or {})}
    if postfinish_hooks is None:
        return cls(cfg, hd)
    return cls(cfg, hd, postfinish_hooks=postfinish_hooks)


def _count_alerts(monkeypatch, mod):
    alerts = []
    monkeypatch.setattr(mod.LOGGER, "alert", lambda msg, *a, **k: alerts.append(msg))
    return alerts


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_defaults_are_five_strikes_and_24_hours(tmp_path, mod):
    drv = make_sync_driver(tmp_path, mod.SyncDriver)
    try:
        assert (drv.quarantine_strikes, drv.quarantine_hours) == (5, 24)
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_an_exception_out_of_sync_yml_is_a_strike(tmp_path, mod, monkeypatch):
    alerts = _count_alerts(monkeypatch, mod)
    drv = _driver_with_journal(tmp_path, mod.SyncDriver, QUICK)
    try:
        act_yml = make_action(make_exp_tree(tmp_path, "RUNS", mk_uuid(1)), 0)

        async def explode(yml_path, rank=5, **kw):
            raise ValueError("bad yml")

        drv.sync_yml = explode
        await drv.enqueue_yml(act_yml, 0)
        await drain(drv, timeout=15)
        prog = mod.Progress(act_yml)
        assert prog.is_quarantined
        assert prog.quarantine["last_error"] == "ValueError: bad yml"
        assert len(alerts) == 1
        listed = drv.quarantined()
        assert [e["yml"] for e in listed] == [str(act_yml)]
        assert listed[0]["strikes"] == 1
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_a_failed_blocking_hook_is_a_strike(tmp_path, mod):
    hook = tmp_path / "push_api.py"
    hook.write_text(textwrap.dedent(FAILING_HOOK), encoding="utf-8")
    drv = _driver_with_journal(
        tmp_path,
        mod.SyncDriver,
        {"quarantine_strikes": 5, "quarantine_hours": 24},
        postfinish_hooks={"action": {str(hook): ["*"]}},
    )
    try:
        act_yml = make_action(make_exp_tree(tmp_path, "RUNS", mk_uuid(1)), 0)

        async def no_requeue(upath, rank=0, rank_limit=-5):
            return None

        drv.enqueue_yml = no_requeue
        assert (
            await asyncio.wait_for(drv.sync_yml(yml_path=act_yml, rank=0), 15) is False
        )
        block = mod.Progress(act_yml).quarantine
        assert block["strikes"] == 1
        assert "push failed" in block["last_error"]
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_a_quarantined_record_is_never_enqueued(tmp_path, mod):
    drv = make_sync_driver(tmp_path, mod.SyncDriver)
    try:
        exp_yml = make_exp_tree(tmp_path, RunDir.FINISHED.value, mk_uuid(1))
        sick = make_action(exp_yml, 0)
        healthy = make_action(exp_yml, 1)
        mod.Progress(sick).add_strike("boom", 1, 0, T0)
        mod.Progress(healthy).add_strike("blip", 5, 24, T0)  # strikes below N
        synced = []

        async def record(yml_path, rank=5, **kw):
            synced.append(str(yml_path))

        drv.sync_yml = record
        await drv.enqueue_yml(sick, 0)
        await drv.finish_pending(actions_first=True)
        await drain(drv, timeout=15)
        assert str(sick) not in synced
        assert str(healthy) in synced  # the sweep did find this tree
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_release_quarantine_clears_and_reports(tmp_path, mod):
    drv = make_sync_driver(tmp_path, mod.SyncDriver)
    try:
        act_yml = make_action(make_exp_tree(tmp_path, "RUNS", mk_uuid(1)), 0)
        assert drv.release_quarantine(act_yml) is False
        mod.Progress(act_yml).add_strike("boom", 1, 0, T0)
        assert drv.release_quarantine(str(act_yml)) is True
        assert mod.Progress(act_yml).quarantine is None
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_zero_strikes_disables_quarantine_but_records(tmp_path, mod, monkeypatch):
    alerts = _count_alerts(monkeypatch, mod)
    drv = make_sync_driver(
        tmp_path, mod.SyncDriver, {"quarantine_strikes": 0, "quarantine_hours": 0}
    )
    try:
        act_yml = make_action(make_exp_tree(tmp_path, "RUNS", mk_uuid(1)), 0)
        for _ in range(3):
            await drv._strike(act_yml, "boom")
        prog = mod.Progress(act_yml)
        # Three back-to-back failures fall inside QUARANTINE_STRIKE_GAP: one strike.
        assert prog.quarantine["strikes"] == 1 and not prog.is_quarantined
        assert alerts == []
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_strike_on_a_vanished_record_does_not_kill_the_worker(tmp_path, mod):
    drv = make_sync_driver(tmp_path, mod.SyncDriver, QUICK)
    try:
        ghost = tmp_path / "RUNS" / "gone" / "260610.000001000000-act.yml"
        await drv._strike(ghost, "boom")  # Progress raises loading the missing yml
        assert not ghost.with_suffix(".prg").exists()
        act_yml = make_action(make_exp_tree(tmp_path, "RUNS", mk_uuid(1)), 0)
        seen = []

        async def record(yml_path, rank=5, **kw):
            seen.append(str(yml_path))

        drv.sync_yml = record
        await drv.enqueue_yml(act_yml, 0)
        await drain(drv, timeout=15)
        assert seen == [str(act_yml)]
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_no_journal_still_quarantines_and_lists_nothing(
    tmp_path, mod, monkeypatch
):
    alerts = _count_alerts(monkeypatch, mod)
    drv = make_sync_driver(tmp_path, mod.SyncDriver, QUICK)  # no states_root
    try:
        assert drv.run_journal is None
        act_yml = make_action(make_exp_tree(tmp_path, "RUNS", mk_uuid(1)), 0)
        await drv._strike(act_yml, "boom")
        assert mod.Progress(act_yml).is_quarantined
        assert len(alerts) == 1
        assert drv.quarantined() == []
    finally:
        await teardown_driver(drv)
