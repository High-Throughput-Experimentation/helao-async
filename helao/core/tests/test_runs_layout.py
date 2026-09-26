"""The single RUNS tree and the legacy vocabulary (spec §3.1, §7)."""

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from helao.core.models.run_dir import (
    LEGACY_RUN_DIRS,
    diag_root,
    is_legacy_path,
    run_root,
)


def test_run_root_is_a_single_runs_directory():
    assert run_root("/data").name == "RUNS"


def test_diag_root_is_a_sibling_not_a_child_of_runs():
    """Spec §3.4: a manual tree is never written under RUNS."""
    assert diag_root("/data").name == "DIAG"
    assert diag_root("/data").parent == run_root("/data").parent


def test_all_eight_historical_names_are_legacy():
    """Including the three only scan_prg_ghosts knows about (spec §7)."""
    assert set(LEGACY_RUN_DIRS) == {
        "RUNS_ACTIVE",
        "RUNS_FINISHED",
        "RUNS_SYNCED",
        "RUNS_DIAG",
        "RUNS_NOSYNC",
        "RUNS_CORRUPT",
        "RUNS_REBUILD",
        "RUNS_SUPERSEDED",
    }


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/data/RUNS_SYNCED/26.35/0828/seq/f.yml", True),
        ("/data/RUNS_CORRUPT/26.35/0828/seq/f.yml", True),
        ("/data/RUNS/2026/0925/seq/f.yml", False),
        ("/data/DIAG/2026/0925/seq/f.yml", False),
        ("/data/RUNSOMETHING/2026/0925/f.yml", False),
        ("/data/RUNS_ACTIVEX/2026/0925/f.yml", False),
    ],
)
def test_is_legacy_path_matches_whole_segments_only(path, expected):
    assert is_legacy_path(path) is expected


def test_helao_dirs_creates_runs_and_diag_and_no_legacy_dirs(tmp_path: Path):
    from helao.helpers.helao_dirs import _HELAO_DIRS_CACHE, helao_dirs

    _HELAO_DIRS_CACHE.clear()
    dirs = helao_dirs({"root": str(tmp_path)})
    assert (tmp_path / "RUNS").is_dir()
    assert (tmp_path / "DIAG").is_dir()
    assert not (tmp_path / "RUNS_ACTIVE").exists()
    assert Path(str(dirs.save_root)).name == "RUNS"


def test_manual_redirect_swaps_the_root_not_a_substring(tmp_path: Path):
    from helao.hexagon.domain.naming import redirect_manual_dir

    assert redirect_manual_dir(str(tmp_path / "RUNS")) == str(tmp_path / "DIAG")


def test_manual_redirect_is_idempotent(tmp_path: Path):
    from helao.hexagon.domain.naming import redirect_manual_dir

    once = redirect_manual_dir(str(tmp_path / "RUNS"))
    assert redirect_manual_dir(once) == once


def test_manual_redirect_still_handles_a_legacy_active_root(tmp_path: Path):
    from helao.core.models.run_dir import redirect_manual_dir

    legacy = str(tmp_path / "RUNS_ACTIVE")
    assert redirect_manual_dir(legacy) == str(tmp_path / "RUNS_DIAG")


@pytest.mark.asyncio
async def test_move_dir_leaves_the_tree_exactly_where_it_is(tmp_path: Path):
    """Spec §2: a run tree is written once and never moves."""
    from helao.core.tests.run_layout_fixtures import finished_action
    from helao.helpers.yml_tools import move_dir

    hobj, base = finished_action(tmp_path)
    act_dir = Path(str(base.helaodirs.save_root)) / hobj.get_action_dir()
    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))

    await move_dir(hobj, base=base)

    after = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    assert before == after
    assert act_dir.is_dir()


@pytest.mark.asyncio
async def test_move_dir_creates_no_legacy_directory(tmp_path: Path):
    from helao.core.models.run_dir import LEGACY_RUN_DIRS
    from helao.core.tests.run_layout_fixtures import finished_action
    from helao.helpers.yml_tools import move_dir

    hobj, base = finished_action(tmp_path)
    await move_dir(hobj, base=base)

    created = {p.name for p in tmp_path.rglob("*") if p.is_dir()}
    assert created.isdisjoint(LEGACY_RUN_DIRS)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["action", "experiment", "sequence"])
async def test_move_dir_finishes_every_record_kind(tmp_path: Path, kind: str):
    """All three kinds reach the handoff, not just an Action.

    ``move_dir`` selected its directory getter out of a dict literal, and a
    dict literal evaluates every value before a key is chosen -- so building
    it looked up ``get_action_dir`` on an Experiment and raised. The raise was
    swallowed by the event loop's exception handler, so an experiment and a
    sequence were simply never handed to the syncer: observed on a real
    launch as a completed run with no ``-seq.prg`` and an ORCH journal that
    never evicted.
    """
    from helao.core.tests import run_layout_fixtures as fx
    from helao.helpers.yml_tools import move_dir

    hobj, base = getattr(fx, f"finished_{kind}")(tmp_path)
    finished = []
    base.run_journal = SimpleNamespace(append=lambda *a, **kw: finished.append(a))

    await move_dir(hobj, base=base)

    assert finished, f"{kind} was never evicted from the producing journal"
    assert finished[0][1] == kind


def test_is_same_location_sees_through_normalization(tmp_path: Path):
    from helao.core.models.run_dir import is_same_location

    src = tmp_path / "RUNS" / "2026" / "0925"
    assert is_same_location(src, str(src) + "/")
    assert is_same_location(src, src.parent / "0925")
    assert not is_same_location(src, tmp_path / "DIAG" / "2026" / "0925")


def test_a_mover_refuses_when_its_substitution_missed(tmp_path: Path):
    """Plan A24: the identity rewrite must never reach a move or a removal.

    ``move_to_synced`` carried this guard until Task 10 deleted it along with
    the promotion. ``unsync_dir`` is the only mover left in the syncer, and it
    computes its destination the same way.
    """
    from helao.core.drivers.data.sync_driver import SyncDriver

    # No RUNS_SYNCED segment, so .replace(SYNCED, FINISHED) is the identity.
    d = tmp_path / "RUNS" / "2026" / "0925"
    d.mkdir(parents=True)
    src = d / "260925.094102000000-act.yml"
    src.write_text("action_name: do_thing\n")

    SyncDriver.unsync_dir(object(), str(d))  # type: ignore[arg-type]

    assert src.exists()
    assert src.read_text() == "action_name: do_thing\n"


# --- Task 10: the syncer stops promoting and stops zipping ------------------


def _new_layout_seq(tmp_path: Path, status: str = "finished") -> Path:
    d = tmp_path / "RUNS" / "2026" / "0925" / "seq"
    d.mkdir(parents=True)
    yml = d / "260925.094102000000-seq.yml"
    yml.write_text(f"sequence_name: s\nsequence_status: [{status}]\n")
    return yml


def _legacy_seq(tmp_path: Path, tree: str = "RUNS_FINISHED") -> Path:
    d = tmp_path / tree / "26.35" / "0925" / "seq"
    d.mkdir(parents=True)
    yml = d / "260925.094102000000-seq.yml"
    yml.write_text("sequence_name: s\nsequence_status: [finished]\n")
    return yml


@pytest.mark.parametrize("builder", [_new_layout_seq, _legacy_seq])
def test_prg_sits_beside_its_own_yml(tmp_path: Path, builder):
    """Spec §4.5: the receipt lives with the record, not in another tree.

    Both layouts, because only the legacy one can tell the two derivations
    apart: ``synced_path`` is the identity under ``RUNS``, so a new-layout
    record alone would pass with the old ``synced_path``-based location.
    A legacy record's receipt used to land under ``RUNS_SYNCED`` -- a tree
    the record is not in, which is how moving a station root stranded every
    ``.prg`` ever written.
    """
    from helao.core.drivers.data.sync_driver import Progress

    yml = builder(tmp_path)
    prog = Progress(yml)
    assert prog.prg.parent == yml.parent
    assert prog.prg.name == "260925.094102000000-seq.prg"


def test_synced_path_is_identity_for_a_new_layout_record(tmp_path: Path):
    from helao.core.drivers.data.sync_driver import HelaoYml

    yml = _new_layout_seq(tmp_path)
    assert HelaoYml(yml).synced_path == yml


def test_synced_path_still_rewrites_a_legacy_record(tmp_path: Path):
    from helao.core.drivers.data.sync_driver import HelaoYml

    yml = _legacy_seq(tmp_path)
    assert "RUNS_SYNCED" in str(HelaoYml(yml).synced_path)


def test_no_zip_is_produced_for_a_synced_sequence(tmp_path: Path):
    """Spec D9. Paired with the sequence_path alias in Task 12."""
    import helao.core.drivers.data.sync_driver as sd

    assert not hasattr(sd, "move_to_synced")
    assert not hasattr(sd, "revert_to_finished")
    assert "zip_dir" not in sd.__dict__


def test_pending_globs_find_records_in_the_new_layout(tmp_path: Path):
    """Spec §10.9: RUNS/%Y/%m%d/seqdir is the same depth as RUNS_FINISHED/YY.WW/MMDD/seqdir.

    list_pending globs '*/*/*/*-seq.yml' relative to the run root. If the new
    layout were one level shallower or deeper, every pending record would
    become invisible to the syncer's startup sweep -- silently, because an
    empty glob is indistinguishable from an empty queue.

    The tree is built from the real ``get_*_dir()`` builders rather than
    written out literally, so a change to the date path actually reaches the
    assertion instead of being restated by it.
    """
    from glob import glob

    from helao.core.tests.run_layout_fixtures import finished_action

    act, _ = finished_action(tmp_path)
    act_dir = tmp_path / "RUNS" / act.get_action_dir()
    exp_dir = act_dir.parent
    seq_dir = exp_dir.parent
    (seq_dir / "260925.094102000000-seq.yml").write_text("sequence_name: s\n")
    (exp_dir / "260925.094103000000-exp.yml").write_text("experiment_name: e\n")

    root = str(tmp_path / "RUNS")
    assert len(glob(os.path.join(root, "*", "*", "*", "*-seq.yml"))) == 1
    assert len(glob(os.path.join(root, "*", "*", "*", "*", "*-exp.yml"))) == 1
    assert len(glob(os.path.join(root, "*", "*", "*", "*", "*", "*-act.yml"))) == 1


# --- A11: status comes from the record, not from the path -------------------


def test_status_of_a_new_layout_record_comes_from_its_meta(tmp_path: Path):
    """Plan A11: no segment of RUNS/2026/0925 starts with 'RUNS_'.

    The path derivation subscripted an empty list, so every new-layout record
    raised IndexError three frames below sync_yml instead of classifying.
    """
    from helao.core.drivers.data.sync_driver import HelaoYml

    assert HelaoYml(_new_layout_seq(tmp_path / "a", "active")).status == "active"
    assert HelaoYml(_new_layout_seq(tmp_path / "b", "finished")).status == "finished"


def test_status_of_a_new_layout_record_is_synced_once_its_prg_is_complete(
    tmp_path: Path,
):
    """HloStatus has no 'synced' member; the .prg sidecar is the receipt."""
    from helao.core.drivers.data.sync_driver import HelaoYml

    yml = _new_layout_seq(tmp_path)
    assert HelaoYml(yml).status == "finished"
    yml.with_suffix(".prg").write_text("s3: true\napi: true\n")
    assert HelaoYml(yml).status == "synced"


@pytest.mark.parametrize(
    "tree,expected",
    [
        ("RUNS_ACTIVE", "active"),
        ("RUNS_FINISHED", "finished"),
        ("RUNS_SYNCED", "synced"),
    ],
)
def test_a_legacy_record_still_classifies_from_its_path(
    tmp_path: Path, tree: str, expected: str
):
    from helao.core.drivers.data.sync_driver import HelaoYml

    assert HelaoYml(_legacy_seq(tmp_path, tree)).status == expected


def test_legacy_only_helpers_refuse_a_new_layout_path(tmp_path: Path):
    """Plan A11: a clear error naming the amendment, not an IndexError."""
    from helao.core.drivers.data.sync_driver import HelaoYml

    yml = HelaoYml(_new_layout_seq(tmp_path))
    for call in (
        lambda: yml.rename("RUNS_SYNCED"),
        lambda: yml.status_idx,
        lambda: yml.relative_path,
    ):
        with pytest.raises(ValueError, match="A11"):
            call()


def test_sync_yml_refuses_an_active_new_layout_record_and_accepts_a_finished_one(
    tmp_path: Path,
):
    """Both `status` reads on sync_yml's main path (plan A11)."""
    import asyncio

    from helao.core.drivers.data.sync_driver import HelaoYml

    for state, expected in (("active", "active"), ("finished", "finished")):
        yml = _new_layout_seq(tmp_path / state, state)
        assert HelaoYml(yml).status == expected

    async def drive():
        from helao.core.drivers.data.sync_driver import SyncDriver
        from helao.core.models.helaodirs import HelaoDirs

        hd = HelaoDirs(
            root=tmp_path,
            save_root=tmp_path / "RUNS",
            process_root=tmp_path / "PROCESSES",
        )
        drv = SyncDriver({"aws_bucket": "b", "max_tasks": 1}, hd)
        try:
            # An active record is refused (False), not raised at.
            return await drv.sync_yml(
                tmp_path
                / "active"
                / "RUNS"
                / "2026"
                / "0925"
                / "seq"
                / "260925.094102000000-seq.yml"
            )
        finally:
            for task in drv.syncer_loops.values():
                task.cancel()
            await asyncio.gather(*drv.syncer_loops.values(), return_exceptions=True)

    assert asyncio.run(drive()) is False


# --- A1: the startup sweep must not re-enqueue everything ever written ------


def test_list_pending_skips_records_whose_prg_says_they_shipped(tmp_path: Path):
    """Plan A1: save_root IS the search root now, and records never leave it.

    Without the .prg filter the startup sweep enqueues every record ever
    written, unbounded -- and has_pending_work() reads that queue, so the
    hot-reload idle gate sits behind the sweep at every start.
    """
    from helao.core.drivers.data.sync_driver import SyncDriver

    for name, shipped in (("done_seq", True), ("todo_seq", False)):
        d = tmp_path / "RUNS" / "2026" / "0925" / name
        d.mkdir(parents=True)
        yml = d / "260925.094102000000-seq.yml"
        yml.write_text("sequence_name: s\nsequence_status: [finished]\n")
        if shipped:
            yml.with_suffix(".prg").write_text("s3: true\napi: true\n")

    drv = SyncDriver.__new__(SyncDriver)
    drv.helaodirs = SimpleNamespace(save_root=tmp_path / "RUNS")  # type: ignore[assignment]
    pending = drv.list_pending()
    assert [Path(p).parent.name for p in pending] == ["todo_seq"]
