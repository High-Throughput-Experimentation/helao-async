"""The single RUNS tree and the legacy vocabulary (spec §3.1, §7)."""

from pathlib import Path

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


def test_is_same_location_sees_through_normalization(tmp_path: Path):
    from helao.core.models.run_dir import is_same_location

    src = tmp_path / "RUNS" / "2026" / "0925"
    assert is_same_location(src, str(src) + "/")
    assert is_same_location(src, src.parent / "0925")
    assert not is_same_location(src, tmp_path / "DIAG" / "2026" / "0925")


def test_a_mover_refuses_when_its_substitution_missed(tmp_path: Path):
    """Plan A24: the identity rewrite must never reach a move or a removal."""
    from helao.core.drivers.data.sync_driver import move_to_synced

    # No RUNS_FINISHED segment, so .replace(FINISHED, SYNCED) is the identity.
    src = tmp_path / "RUNS" / "2026" / "0925" / "260925.094102000000-act.yml"
    src.parent.mkdir(parents=True)
    src.write_text("action_name: do_thing\n")

    assert move_to_synced(src) is False
    assert src.read_text() == "action_name: do_thing\n"
