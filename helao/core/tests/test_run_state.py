"""The per-server run-state journal (spec §4)."""

import json
from pathlib import Path

import pytest

from helao.helpers.run_state import (
    ACTIVE,
    DONE,
    UNSYNCED,
    RunStateJournal,
    rebuild_from_tree,
)

UUID_A = "11111111-1111-1111-1111-111111111111"
UUID_B = "22222222-2222-2222-2222-222222222222"


def test_appended_record_is_in_the_working_set(tmp_path: Path):
    j = RunStateJournal(tmp_path, "SIM")
    j.append(UUID_A, "action", ACTIVE, "RUNS/2026/0925/094102__s__l/e/a")
    assert set(j.working_set()) == {UUID_A}
    assert j.working_set()[UUID_A]["state"] == ACTIVE


def test_last_line_wins(tmp_path: Path):
    j = RunStateJournal(tmp_path, "SIM")
    j.append(UUID_A, "action", ACTIVE, "RUNS/a")
    j.append(UUID_A, "action", UNSYNCED, "RUNS/a")
    assert j.working_set()[UUID_A]["state"] == UNSYNCED


def test_done_evicts_rather_than_marking(tmp_path: Path):
    """Spec §3 D3: absence means done; nothing queries for done records."""
    j = RunStateJournal(tmp_path, "SIM")
    j.append(UUID_A, "action", ACTIVE, "RUNS/a")
    j.append(UUID_B, "action", ACTIVE, "RUNS/b")
    j.append(UUID_A, "action", DONE, "RUNS/a")
    assert set(j.working_set()) == {UUID_B}


def test_stored_path_is_forward_slash(tmp_path: Path):
    """Spec §9: a journal is byte-identical across platforms."""
    j = RunStateJournal(tmp_path, "SIM")
    j.append(UUID_A, "action", ACTIVE, "RUNS\\2026\\0925\\seq")
    line = json.loads(j.path.read_text().splitlines()[0])
    assert line["path"] == "RUNS/2026/0925/seq"


def test_torn_final_line_is_discarded_and_warned(tmp_path: Path, caplog):
    """Spec §4.4: a crash mid-append can only damage the last line."""
    j = RunStateJournal(tmp_path, "SIM")
    j.append(UUID_A, "action", ACTIVE, "RUNS/a")
    j.append(UUID_B, "action", ACTIVE, "RUNS/b")
    with j.path.open("a") as f:
        f.write('{"uuid": "333')  # truncated, no newline

    with caplog.at_level("WARNING"):
        ws = j.working_set()
    assert set(ws) == {UUID_A, UUID_B}
    assert "discarding" in caplog.text.lower()


def test_corruption_before_the_last_line_raises(tmp_path: Path):
    """A bad line anywhere else is real corruption, not a torn write."""
    j = RunStateJournal(tmp_path, "SIM")
    j.append(UUID_A, "action", ACTIVE, "RUNS/a")
    lines = j.path.read_text().splitlines()
    j.path.write_text("not json at all\n" + "\n".join(lines) + "\n")
    with pytest.raises(ValueError):
        j.working_set()


def _raw_append(journal: RunStateJournal, uuid: str, state: str, path: str) -> None:
    """Append a line without going through ``append``'s compaction check.

    Building a >1000-line file with ``append`` is impossible: the automatic
    compaction under test here fires partway through the setup and empties
    the file. This is the only place that matters, so the test writes the
    same record shape by hand rather than the module growing a seam for it.
    """
    journal.states_root.mkdir(parents=True, exist_ok=True)
    with journal.path.open("a", encoding="utf-8") as f:
        record = {
            "ts": "2026-09-25T09:41:02",
            "uuid": uuid,
            "kind": "action",
            "state": state,
            "path": path,
            "parent": None,
        }
        f.write(json.dumps(record, separators=(",", ":")) + "\n")


def test_compaction_drops_tombstones_and_preserves_survivors(tmp_path: Path):
    j = RunStateJournal(tmp_path, "SIM")
    for _ in range(600):
        _raw_append(j, UUID_A, ACTIVE, "RUNS/a")
        _raw_append(j, UUID_A, DONE, "RUNS/a")
    _raw_append(j, UUID_B, ACTIVE, "RUNS/b")
    before = len(j.path.read_text().splitlines())
    assert before > 1000

    j.compact()
    after = j.path.read_text().splitlines()
    assert len(after) == 1
    assert json.loads(after[0])["uuid"] == UUID_B
    assert set(j.working_set()) == {UUID_B}


def test_compaction_does_not_fire_below_the_line_floor(tmp_path: Path):
    """Spec §4.4: a two-record station must not compact constantly."""
    j = RunStateJournal(tmp_path, "SIM")
    for _ in range(20):
        j.append(UUID_A, "action", ACTIVE, "RUNS/a")
        j.append(UUID_A, "action", DONE, "RUNS/a")
    assert len(j.path.read_text().splitlines()) == 40


def test_compaction_fires_automatically_once_both_thresholds_are_met(tmp_path):
    j = RunStateJournal(tmp_path, "SIM")
    j.append(UUID_B, "action", ACTIVE, "RUNS/b")
    for _ in range(600):
        j.append(UUID_A, "action", ACTIVE, "RUNS/a")
        j.append(UUID_A, "action", DONE, "RUNS/a")
    # 1201 lines written, working set is 1 -> 1201 > 1000 and 1201 > 10*1
    assert len(j.path.read_text().splitlines()) < 1000
    assert set(j.working_set()) == {UUID_B}


def test_missing_file_is_an_empty_working_set(tmp_path: Path):
    assert RunStateJournal(tmp_path, "NEVERWRITTEN").working_set() == {}


def _record(runs_root: Path, rel: str, stem: str, prg: bool, complete: bool):
    """A record directory with a yml and optionally a ``.prg`` beside it.

    The sidecar is written the way ``Progress`` actually writes it -- the
    ``yml`` key first, then lowercase ``api``/``s3`` booleans -- so these
    tests fail if the real serialization drifts away from what
    ``_prg_is_complete`` looks for.
    """
    d = runs_root / rel
    d.mkdir(parents=True, exist_ok=True)
    yml = d / f"{stem}.yml"
    yml.write_text("action_name: x\n")
    if prg:
        state = "true" if complete else "false"
        (d / f"{stem}.prg").write_text(
            f"yml: {yml}\napi: {state}\ns3: {state}\n"
            "files_pending: []\nfiles_s3: {}\n"
        )
    return d


def test_record_with_a_complete_prg_is_done(tmp_path: Path):
    runs = tmp_path / "RUNS"
    _record(runs, "2026/0925/seq", "260925.120000000000-seq", prg=True, complete=True)
    j = rebuild_from_tree(runs, tmp_path / "STATES", "SYNC")
    assert j.working_set() == {}


def test_record_without_a_prg_is_unsynced(tmp_path: Path):
    runs = tmp_path / "RUNS"
    _record(runs, "2026/0925/seq", "260925.120000000000-seq", prg=False, complete=False)
    j = rebuild_from_tree(runs, tmp_path / "STATES", "SYNC")
    ws = j.working_set()
    assert len(ws) == 1
    assert next(iter(ws.values()))["state"] == UNSYNCED


def test_record_with_an_incomplete_prg_is_unsynced(tmp_path: Path):
    runs = tmp_path / "RUNS"
    _record(runs, "2026/0925/seq", "260925.120000000000-seq", prg=True, complete=False)
    assert len(rebuild_from_tree(runs, tmp_path / "STATES", "SYNC").working_set()) == 1


def test_rebuilt_paths_are_root_relative_and_forward_slash(tmp_path: Path):
    runs = tmp_path / "RUNS"
    _record(runs, "2026/0925/seq", "260925.120000000000-seq", prg=False, complete=False)
    j = rebuild_from_tree(runs, tmp_path / "STATES", "SYNC")
    stored = next(iter(j.working_set().values()))["path"]
    assert stored == "RUNS/2026/0925/seq"


def test_rebuild_classifies_all_three_kinds(tmp_path: Path):
    runs = tmp_path / "RUNS"
    base = "2026/0925/seq"
    _record(runs, base, "260925.120000000000-seq", prg=False, complete=False)
    _record(runs, f"{base}/exp", "260925.120001000000-exp", prg=False, complete=False)
    _record(
        runs, f"{base}/exp/act", "260925.120002000000-act", prg=False, complete=False
    )
    kinds = {
        r["kind"]
        for r in rebuild_from_tree(runs, tmp_path / "STATES", "SYNC")
        .working_set()
        .values()
    }
    assert kinds == {"sequence", "experiment", "action"}


def test_rebuild_overwrites_a_corrupt_journal(tmp_path: Path):
    runs = tmp_path / "RUNS"
    states = tmp_path / "STATES"
    states.mkdir()
    (states / "runstate_SYNC.jsonl").write_text("garbage\ngarbage\n")
    _record(runs, "2026/0925/seq", "260925.120000000000-seq", prg=False, complete=False)
    assert len(rebuild_from_tree(runs, states, "SYNC").working_set()) == 1
