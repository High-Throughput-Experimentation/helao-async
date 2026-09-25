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
