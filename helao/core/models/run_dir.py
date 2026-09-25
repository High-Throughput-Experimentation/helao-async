"""The single run tree, and the vocabulary of the eight it replaced.

HELAO used to name a record's lifecycle state in the directory holding it, so
a reader had to search up to eight roots for one file and a state change meant
copying a tree. Records now live in one place, ``<root>/RUNS``, and never
move; state is held in the per-server journals (``helao.helpers.run_state``).

``LEGACY_RUN_DIRS`` is not dead vocabulary: existing station archives are left
exactly where they are and are never migrated (spec §7), so every reader must
keep resolving them.
"""

__all__ = [
    "ALL_RUN_DIRS",
    "LEGACY_RUN_DIRS",
    "RunDir",
    "SYNC_PROGRESSION",
    "diag_root",
    "is_legacy_path",
    "run_root",
]

from enum import Enum
from pathlib import Path

#: Every directory name a record was ever written under. The last three are
#: repair-tool vocabulary (``scan_prg_ghosts``) rather than states the servers
#: ever wrote, but a reader that meets one today must keep meeting it.
LEGACY_RUN_DIRS = (
    "RUNS_ACTIVE",
    "RUNS_FINISHED",
    "RUNS_SYNCED",
    "RUNS_DIAG",
    "RUNS_NOSYNC",
    "RUNS_CORRUPT",
    "RUNS_REBUILD",
    "RUNS_SUPERSEDED",
)


class RunDir(str, Enum):
    """Retained for the legacy read path only. Nothing writes these."""

    ACTIVE = "RUNS_ACTIVE"
    FINISHED = "RUNS_FINISHED"
    SYNCED = "RUNS_SYNCED"
    DIAG = "RUNS_DIAG"
    NOSYNC = "RUNS_NOSYNC"


SYNC_PROGRESSION = (RunDir.ACTIVE, RunDir.FINISHED, RunDir.SYNCED)
ALL_RUN_DIRS = tuple(RunDir)


def run_root(root) -> Path:
    """The station's single run tree."""
    return Path(root) / "RUNS"


def diag_root(root) -> Path:
    """Manual and diagnostic runs, kept out of RUNS entirely (spec §3.4)."""
    return Path(root) / "DIAG"


def is_legacy_path(path) -> bool:
    """Whether *path* lives under one of the pre-cut-over run trees.

    Matched on whole path segments, so ``RUNSOMETHING`` is not a false
    positive. The two layouts are trivially distinguishable because the run
    root segment differs, which is why no heuristic on the ``YY.WW``
    week-directory shape is needed.
    """
    return any(part in LEGACY_RUN_DIRS for part in Path(path).parts)
