"""The journal records a record's life and evicts it at the end (spec §4.3).

Task 4 tested the journal in isolation. These tests cover the *wiring*: the
config helper, the ``record_active`` path rule that plan A13 says a
``tmp_path`` test cannot catch on its own, and the syncer's two transition
points -- including the uuid normalization of plan A12, which is the
difference between a working set that drains and one that grows forever.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from helao.core.drivers.data.sync_driver import SyncDriver
from helao.helpers.run_state import (
    ACTIVE,
    DONE,
    UNSYNCED,
    RunStateJournal,
    record_active,
)

ACT_UUID = "0a7f3e2c-1b4d-4c8e-9f10-2a3b4c5d6e7f"
EXP_UUID = "11111111-2222-3333-4444-555555555555"


def _act_yml(directory: Path, uuid: str = ACT_UUID) -> Path:
    """A minimal ``-act.yml`` carrying the two uuids ``_identify`` reads."""
    directory.mkdir(parents=True, exist_ok=True)
    yml = directory / "260925.120000000000-act.yml"
    yml.write_text(
        "file_type: action\n"
        f"action_uuid: {uuid}\n"
        "action_name: noop\n"
        f"experiment_uuid: {EXP_UUID}\n",
        encoding="utf-8",
    )
    return yml


def _fake_syncer(tmp_path: Path) -> SyncDriver:
    """A ``SyncDriver`` with only the attributes the journal code touches.

    ``__init__`` spawns worker tasks and needs a running loop; none of that is
    under test here, and constructing it would test asyncio instead.
    """
    driver = SyncDriver.__new__(SyncDriver)
    driver.helaodirs = SimpleNamespace(  # type: ignore[assignment]
        root=str(tmp_path),
        save_root=str(tmp_path / "RUNS"),
        states_root=str(tmp_path / "STATES"),
    )
    driver.run_journal = RunStateJournal(driver.helaodirs.states_root, "SYNC")
    return driver


def journal_of(driver: SyncDriver) -> RunStateJournal:
    """``driver.run_journal``, narrowed -- the attribute is Optional on the class."""
    assert driver.run_journal is not None
    return driver.run_journal


# --- config surface (spec §6) ------------------------------------------------


def test_sync_finished_defaults_to_true():
    from helao.helpers.config_loader import sync_finished_enabled

    cfg = {"servers": {"SYNC": {"group": "action"}}}
    assert sync_finished_enabled(cfg) is True
    assert sync_finished_enabled({**cfg, "sync_finished": False}) is False
    assert sync_finished_enabled({**cfg, "sync_finished": True}) is True


def test_no_sync_server_means_sync_finished_is_false():
    """Spec §6: a group with no syncer behaves as sync_finished: false."""
    from helao.helpers.config_loader import sync_finished_enabled

    cfg = {"sync_finished": True, "servers": {"ORCH": {"group": "orchestrator"}}}
    assert sync_finished_enabled(cfg) is False
    assert sync_finished_enabled({}) is False


# --- the handoff (spec §4.1, §4.3) -------------------------------------------


def test_a_record_that_finishes_without_syncing_is_evicted(tmp_path: Path):
    """sync_finished: false -> straight to done, never enters the unsynced set."""
    producer = RunStateJournal(tmp_path, "SIM")
    producer.append("u1", "action", ACTIVE, "RUNS/a")
    producer.append("u1", "action", DONE, "RUNS/a")
    assert producer.working_set() == {}


def test_handoff_moves_the_record_between_journals(tmp_path: Path):
    """Spec §4.1: exactly one writer per file; the producer hands off to SYNC."""
    producer = RunStateJournal(tmp_path, "SIM")
    syncer = RunStateJournal(tmp_path, "SYNC")

    producer.append("u1", "action", ACTIVE, "RUNS/a")
    assert set(producer.working_set()) == {"u1"}

    producer.append("u1", "action", DONE, "RUNS/a")
    syncer.append("u1", "action", UNSYNCED, "RUNS/a")
    assert producer.working_set() == {}
    assert set(syncer.working_set()) == {"u1"}

    syncer.append("u1", "action", DONE, "RUNS/a")
    assert syncer.working_set() == {}
    assert producer.path != syncer.path


# --- record_active (plan A13) ------------------------------------------------


def test_record_active_writes_a_root_relative_forward_slash_path(tmp_path: Path):
    """The journalled path is relative to ``root``, not to ``save_root``.

    ``action_output_dir`` is run-relative, so a caller that hands it over
    without joining ``save_root`` gets a cwd-anchored resolve and a bare
    basename out of ``root_relative``. Asserting the *whole* relative path,
    run-root segment included, is what makes that visible.
    """
    base = SimpleNamespace(
        run_journal=RunStateJournal(tmp_path / "STATES", "SIM"),
        helaodirs=SimpleNamespace(root=str(tmp_path)),
    )
    record_dir = tmp_path / "RUNS_ACTIVE" / "26.39" / "0925" / "seq" / "exp" / "act"
    record_dir.mkdir(parents=True)

    record_active(base, "action", ACT_UUID, str(record_dir), parent=EXP_UUID)

    (entry,) = base.run_journal.working_set().values()
    assert entry["path"] == "RUNS_ACTIVE/26.39/0925/seq/exp/act"
    assert entry["uuid"] == ACT_UUID
    assert entry["kind"] == "action"
    assert entry["state"] == ACTIVE
    assert entry["parent"] == EXP_UUID


def test_record_active_is_a_noop_without_a_journal(tmp_path: Path):
    """A server with no ``root`` has no journal and must not raise."""
    base = SimpleNamespace(run_journal=None, helaodirs=SimpleNamespace(root=None))
    record_active(base, "action", ACT_UUID, str(tmp_path))  # must not raise


# --- the SYNC side (plan A12) ------------------------------------------------


def test_syncer_journals_the_record_read_out_of_its_yml(tmp_path: Path):
    driver = _fake_syncer(tmp_path)
    record_dir = tmp_path / "RUNS_FINISHED" / "26.39" / "0925" / "seq" / "exp" / "act"
    yml = _act_yml(record_dir)

    driver._journal(yml, UNSYNCED)

    (entry,) = journal_of(driver).working_set().values()
    assert entry["uuid"] == ACT_UUID
    assert entry["kind"] == "action"
    assert entry["parent"] == EXP_UUID
    assert entry["path"] == "RUNS_FINISHED/26.39/0925/seq/exp/act"


def test_a_noncanonical_uuid_still_evicts(tmp_path: Path):
    """Plan A12: eviction is ``pop(uuid)``, so the key must be normalized.

    An uppercase or braced uuid appended verbatim would not pop the lowercase
    entry, and the phantom would survive every compaction. The normalization
    lives in ``run_state._identify`` (``str(UUID(...))``) -- this pins that it
    reaches the journal, not that the syncer re-does it.
    """
    driver = _fake_syncer(tmp_path)
    enqueued = _act_yml(tmp_path / "RUNS_FINISHED" / "a", uuid=ACT_UUID)
    shouted = _act_yml(tmp_path / "RUNS_FINISHED" / "b", uuid=ACT_UUID.upper())

    driver._journal(enqueued, UNSYNCED)
    assert set(journal_of(driver).working_set()) == {ACT_UUID}

    driver._journal(shouted, DONE)
    assert journal_of(driver).working_set() == {}


def test_a_path_that_is_not_a_record_is_not_journalled(tmp_path: Path):
    driver = _fake_syncer(tmp_path)
    prc = tmp_path / "RUNS_FINISHED" / "260925.120000000000-prc.yml"
    prc.parent.mkdir(parents=True)
    prc.write_text("file_type: process\n", encoding="utf-8")

    driver._journal(prc, UNSYNCED)

    assert journal_of(driver).working_set() == {}


# --- recovery (spec §4.5, plan A8) -------------------------------------------


def test_a_corrupt_journal_is_rebuilt_from_the_run_tree(tmp_path: Path):
    driver = _fake_syncer(tmp_path)
    _act_yml(tmp_path / "RUNS" / "2026" / "0925" / "seq" / "exp" / "act")
    journal_of(driver).states_root.mkdir(parents=True, exist_ok=True)
    journal_of(driver).path.write_text("{ not json\n{ nor this\n", encoding="utf-8")
    with pytest.raises(ValueError):
        journal_of(driver).working_set()

    driver._recover_run_journal()

    entries = journal_of(driver).working_set()
    assert set(entries) == {ACT_UUID}
    assert entries[ACT_UUID]["state"] == UNSYNCED
    assert entries[ACT_UUID]["path"].startswith("RUNS/")


def test_a_degraded_rebuild_is_escalated(tmp_path: Path, monkeypatch):
    """Plan A8: an unreadable directory means records that will never sync."""
    from helao.core.drivers.data import sync_driver

    driver = _fake_syncer(tmp_path)
    journal_of(driver).states_root.mkdir(parents=True, exist_ok=True)
    journal_of(driver).path.write_text("{ not json\n{ nor this\n", encoding="utf-8")

    real_rebuild = sync_driver.rebuild_from_tree

    def degraded(*args, **kwargs):
        journal = real_rebuild(*args, **kwargs)
        journal.unreadable_dirs = 400
        return journal

    errors: list = []
    monkeypatch.setattr(sync_driver, "rebuild_from_tree", degraded)
    monkeypatch.setattr(
        sync_driver,
        "LOGGER",
        SimpleNamespace(
            warning=lambda *a, **k: None,
            error=lambda msg, *a, **k: errors.append(msg),
        ),
    )

    driver._recover_run_journal()

    assert len(errors) == 1
    assert "400" in errors[0] and "never sync" in errors[0]
