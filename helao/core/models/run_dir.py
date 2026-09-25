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
    "is_same_location",
    "redirect_manual_dir",
    "run_root",
]

import os
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


def redirect_manual_dir(path: str) -> str:
    """Point a save root at the station's DIAG tree instead of RUNS.

    Manual and diagnostic runs are written straight into ``<root>/DIAG`` and
    are never written under ``RUNS`` (spec 3.4). This replaces the old
    ``RUNS_ACTIVE`` -> ``RUNS_DIAG`` string substitution, which ran *after*
    the tree had already been written to the wrong place and then had to
    delete the parent experiment and sequence directories behind itself.

    Idempotent: a path already under DIAG is returned unchanged. A
    pre-cut-over ``RUNS_ACTIVE`` path still gets the legacy substitution, so a
    caller handed an archive path does something sane instead of silently
    returning it unchanged.
    """
    p = Path(path)
    if p.name == "DIAG":
        return str(p)
    if p.name == "RUNS":
        return str(p.parent / "DIAG")
    return str(path).replace(RunDir.ACTIVE.value, RunDir.DIAG.value)


def is_same_location(src, dst) -> bool:
    """Whether a computed move destination is really the source itself.

    Every mover in this codebase builds its destination by substituting one
    ``RUNS_*`` segment for another. When the substitution misses -- which it
    does for every path under the single ``RUNS`` tree -- the "destination" is
    the source. A mover that trusts it copies a tree onto itself, finds every
    destination present on disk, concludes the copy succeeded, and deletes the
    original (plan A24: reproduced, records destroyed).

    A mover must refuse and log when this is True, and must never reach a
    removal branch.
    """
    return os.path.normpath(str(src)) == os.path.normpath(str(dst))
