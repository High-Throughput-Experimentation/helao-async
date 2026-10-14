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
