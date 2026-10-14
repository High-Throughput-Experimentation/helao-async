"""Sync quarantine (spec docs/superpowers/specs/2026-10-14-sync-quarantine-design.md)."""

import asyncio
import textwrap
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

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
