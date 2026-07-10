"""Canonical run-state directory names used across HELAO run trees."""

__all__ = ["RunDir", "SYNC_PROGRESSION", "ALL_RUN_DIRS"]

from enum import Enum


class RunDir(str, Enum):
    ACTIVE = "RUNS_ACTIVE"
    FINISHED = "RUNS_FINISHED"
    SYNCED = "RUNS_SYNCED"
    DIAG = "RUNS_DIAG"
    NOSYNC = "RUNS_NOSYNC"


# Order matters: the sync pipeline promotes ACTIVE -> FINISHED -> SYNCED.
SYNC_PROGRESSION = (RunDir.ACTIVE, RunDir.FINISHED, RunDir.SYNCED)
ALL_RUN_DIRS = tuple(RunDir)
