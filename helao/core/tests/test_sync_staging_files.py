"""An atomic write's staging file must never reach S3, nor wedge the syncer.

The production failure this closes, on the XAFS batch-conversion path:

    Failed to upload raw_data/06a8761b-.../.xafs_normal-0.0.0.0__0.hlo.
    93715df4a1b411f19630b07b2514b8fc.tmp to S3, retrying in 30 seconds
    FileNotFoundError: .../0__0__XAFS__normal_scan/.xafs_normal-0.0.0.0__0.hlo.
    93715df4a1b411f19630b07b2514b8fc.tmp

Nothing was wrong with the data. ``posthoc_writer`` writes every artifact by
staging ``.<name>.<uuid1hex>.tmp`` beside its target and renaming it into
place, and the syncer learns an action's non-hlo files by *globbing the record
directory*. The glob landed inside that window, so the syncer recorded a name
that the rename had already consumed.

Three things then compounded, and each is tested here:

* the staging name was uploaded at all -- ``misc_files`` excluded ``.yml``,
  ``.hlo`` and ``.lock``, and nothing else. Two such objects did reach
  ``raw_data/`` on the production bucket, where the race was won the other way;
* it can outlive the race that created it: the pending list is written to the
  ``.prg`` as soon as any *sibling* file uploads, so a ghost beside a real
  artifact is persisted and no later glob can correct it;
* and ``sync_yml``'s upload loop only exits when ``files_pending`` empties,
  while ``to_s3`` returns False rather than raising once its retries are spent.
  A file that can never upload therefore spun that loop forever: 870 log lines
  over 80 minutes for one action, with the record never advancing.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import asyncio  # noqa: E402

import pytest  # noqa: E402

import helao.core.drivers.data.sync_driver as legacy_mod  # noqa: E402
import helao.hexagon.adapters.native.sync_driver as native_mod  # noqa: E402
from helao.core.drivers.data.sync_driver import HelaoYml, Progress  # noqa: E402
from helao.hexagon.tests.sync_fixtures import (  # noqa: E402
    make_action,
    make_exp_tree,
    make_sync_driver,
    mk_uuid,
    teardown_driver,
)

ACT_YML = """access: hte
action_name: normal_scan
action_uuid: 06a8761b-49ba-7431-8000-b27b2e06948c
run_type: xafs
technique_name: XAFS
files:
- file_name: xafs_normal-0.0.0.0__0.hlo
  file_type: xafsscan__helao_file
"""

STAGING_NAME = ".xafs_normal-0.0.0.0__0.hlo.93715df4a1b411f19630b07b2514b8fc.tmp"


def _build_record(root: Path) -> Path:
    """A finished action directory mid-atomic-write; returns its yml path."""
    actdir = (
        root
        / "RUNS_FINISHED/26.33/0820/191516__seq/260820.202108__exp"
        / "0__0__XAFS__normal_scan"
    )
    actdir.mkdir(parents=True, exist_ok=True)
    yml = actdir / "260820.202108607974-act.yml"
    yml.write_text(ACT_YML)
    (actdir / "xafs_normal-0.0.0.0__0.hlo").write_text("{}\n")
    (actdir / "xafs_mca-0.0.0.0__0.npz").write_text("npz")
    (actdir / STAGING_NAME).write_text("half a spectrum")
    return yml


# --- the glob ---------------------------------------------------------------


def test_misc_files_skips_the_staging_file_but_keeps_the_artifact(tmp_path):
    """The whole bug in one assertion: the glob is what uploads."""
    yml = _build_record(tmp_path)
    names = {p.name for p in HelaoYml(yml).misc_files}
    assert names == {"xafs_mca-0.0.0.0__0.npz"}
    assert STAGING_NAME not in names


def test_misc_files_skips_a_bare_tmp_and_a_bare_dotfile(tmp_path):
    """Suffix and leading dot are independent rules, not one rule twice.

    A writer that stages without the dotfile convention is caught by the
    suffix; a writer that stages without the ``.tmp`` suffix is caught by the
    dot. Neither rule subsumes the other, so both are pinned.
    """
    yml = _build_record(tmp_path)
    (yml.parent / "scratch.tmp").write_text("x")
    (yml.parent / ".hidden").write_text("x")
    names = {p.name for p in HelaoYml(yml).misc_files}
    assert names == {"xafs_mca-0.0.0.0__0.npz"}


def test_misc_files_still_recurses_into_subdirectories(tmp_path):
    """Action records rglob; tightening the filter must not have narrowed that."""
    yml = _build_record(tmp_path)
    sub = yml.parent / "spectra"
    sub.mkdir()
    (sub / "scan.SPC").write_text("x")
    (sub / ".scan.SPC.deadbeef.tmp").write_text("x")
    names = {p.name for p in HelaoYml(yml).misc_files}
    assert names == {"xafs_mca-0.0.0.0__0.npz", "scan.SPC"}


def test_the_native_twin_filters_identically(tmp_path):
    """Both copies of the driver are live; a fix in one only is a fix in none."""
    yml = _build_record(tmp_path)
    assert {p.name for p in native_mod.HelaoYml(yml).misc_files} == {
        p.name for p in HelaoYml(yml).misc_files
    }


# --- the sidecar that already holds a ghost ---------------------------------


def _sidecar_with_pending(yml: Path, pending: list) -> Progress:
    prog = Progress(yml)
    prog.dict["files_pending"] = pending
    prog.write_dict()
    return Progress(yml)  # re-read, which is where the healing happens


def test_a_ghost_pending_entry_is_dropped_on_read(tmp_path):
    """Heals the sidecars the race already wrote; nothing else ever would."""
    yml = _build_record(tmp_path)
    (yml.parent / STAGING_NAME).unlink()  # the rename won, as it always does
    prog = _sidecar_with_pending(yml, [STAGING_NAME, "xafs_mca-0.0.0.0__0.npz"])
    assert prog.dict["files_pending"] == ["xafs_mca-0.0.0.0__0.npz"]


def test_a_declared_file_that_is_missing_is_kept(tmp_path):
    """A file the yml declares is data. Its absence is a fault to surface, not
    bookkeeping to sweep up -- dropping it would hide real data loss behind a
    clean sync."""
    yml = _build_record(tmp_path)
    (yml.parent / "xafs_normal-0.0.0.0__0.hlo").unlink()
    prog = _sidecar_with_pending(yml, ["xafs_normal-0.0.0.0__0.hlo"])
    assert prog.dict["files_pending"] == ["xafs_normal-0.0.0.0__0.hlo"]


def test_files_that_exist_are_untouched(tmp_path):
    """The common path must not read the yml or rewrite the list."""
    yml = _build_record(tmp_path)
    prog = _sidecar_with_pending(
        yml, ["xafs_mca-0.0.0.0__0.npz", "xafs_normal-0.0.0.0__0.hlo"]
    )
    assert prog.dict["files_pending"] == [
        "xafs_mca-0.0.0.0__0.npz",
        "xafs_normal-0.0.0.0__0.hlo",
    ]


def test_pruning_runs_after_reanchoring_not_before(tmp_path):
    """An entry still in its pre-relocation absolute form resolves to a path
    that does not exist under the current root. Pruning first would delete
    every one of them -- exactly the sidecars the re-anchoring exists to save.
    """
    yml = _build_record(tmp_path)
    stale = (
        "/some/old/root/RUNS_FINISHED/0__0__XAFS__normal_scan/xafs_mca-0.0.0.0__0.npz"
    )
    prog = _sidecar_with_pending(yml, [stale])
    assert prog.dict["files_pending"] == ["xafs_mca-0.0.0.0__0.npz"]


def test_an_unreadable_yml_drops_nothing(tmp_path):
    """ "Unknown" is not "declares nothing"; pruning against an empty set would
    discard every pending file of a record whose yml is momentarily bad."""
    yml = _build_record(tmp_path)
    (yml.parent / STAGING_NAME).unlink()
    prog = Progress(yml)
    prog.dict["files_pending"] = [STAGING_NAME]
    prog.write_dict()
    yml.write_text("{[not: valid: yaml\n")
    assert Progress(prog.prg).dict["files_pending"] == [STAGING_NAME]


def test_the_native_twin_heals_identically(tmp_path):
    yml = _build_record(tmp_path)
    (yml.parent / STAGING_NAME).unlink()
    prog = Progress(yml)
    prog.dict["files_pending"] = [STAGING_NAME]
    prog.write_dict()
    assert native_mod.Progress(yml).dict["files_pending"] == []


@pytest.mark.parametrize("mod_progress", [Progress, native_mod.Progress])
def test_pruning_is_not_persisted_by_itself(tmp_path, mod_progress):
    """Nothing is written back on read: a record that is never synced again is
    never rewritten, matching how re-anchoring already behaves."""
    yml = _build_record(tmp_path)
    (yml.parent / STAGING_NAME).unlink()
    prog = Progress(yml)
    prog.dict["files_pending"] = [STAGING_NAME]
    prog.write_dict()
    before = prog.prg.read_text()
    mod_progress(yml)
    assert prog.prg.read_text() == before


# --- the loop that used to spin forever -------------------------------------


def _finished_action(root: Path):
    """A finished action with one uploadable misc file, under a seq/exp tree."""
    exp_yml = make_exp_tree(root, "RUNS_FINISHED", mk_uuid(1))
    act_yml = make_action(exp_yml, 0)
    (act_yml.parent / "artifact.npz").write_text("payload")
    return act_yml


@pytest.mark.parametrize("mod", [legacy_mod, native_mod])
@pytest.mark.asyncio
async def test_an_unuploadable_file_ends_the_pass_instead_of_spinning(tmp_path, mod):
    """``to_s3`` returns False rather than raising once its own retries are
    spent, so the loop's only exit was ``files_pending`` emptying. One file
    that can never upload therefore held a worker forever. It must now cost a
    single pass and hand the record back for the next scan."""
    drv = make_sync_driver(tmp_path, mod.SyncDriver)
    try:
        act_yml = _finished_action(tmp_path)
        calls = []

        async def refuse(msg=None, target=None, compress=False, retries=5):
            calls.append(target)
            return False

        drv.to_s3 = refuse
        result = await asyncio.wait_for(drv.sync_yml(yml_path=act_yml), timeout=15)
        assert result is False
        # One pass over the one pending file, not an unbounded number of
        # retries. Before the bound this call did not return at all.
        assert len(calls) == 1, calls
        # The file is still on disk and the record still in RUNS_FINISHED:
        # refusing to upload is not licence to forget data or to advance the
        # record past it.
        assert (act_yml.parent / "artifact.npz").exists()
        assert act_yml.exists()
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", [legacy_mod, native_mod])
@pytest.mark.asyncio
async def test_a_file_that_vanishes_mid_pass_is_dropped_not_retried(tmp_path, mod):
    """The second line of defence, for the race the glob filter cannot close:
    a file present when the directory was globbed and gone by the time its
    turn came. Pruning on read cannot see it -- the entry was created inside
    this very pass."""
    drv = make_sync_driver(tmp_path, mod.SyncDriver)
    try:
        act_yml = _finished_action(tmp_path)
        prog = Progress(act_yml)
        prog.dict["files_pending"] = ["artifact.npz"]
        prog.write_dict()
        (act_yml.parent / "artifact.npz").unlink()  # the rename lands here

        calls = []

        async def record(msg=None, target=None, compress=False, retries=5):
            calls.append(target)
            return True

        drv.to_s3 = record
        await asyncio.wait_for(drv.sync_yml(yml_path=act_yml), timeout=15)
        assert not [c for c in calls if "artifact.npz" in str(c)], calls
        assert "artifact.npz" not in Progress(act_yml).dict["files_pending"]
    finally:
        await teardown_driver(drv)
