"""Pure value objects for the sync domain: HelaoYml, Progress, SyncJob."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

ABR_MAP: dict[str, str] = {
    "act": "action",
    "exp": "experiment",
    "seq": "sequence",
}
MOD_PATCH: dict[str, str] = {"exid": "exec_id"}
PLURALS: dict[str, str] = {
    "action": "actions",
    "experiment": "experiments",
    "sequence": "sequences",
    "process": "processes",
}


def _swap_runs_dir(path: Path, target: str) -> Path:
    parts = list(path.parts)
    for i, part in enumerate(parts):
        if part.startswith("RUNS_"):
            parts[i] = target
            return Path(*parts)
    return path


@dataclass(frozen=True)
class HelaoYml:
    """Pure value object wrapping a single *.yml path inside a RUNS_* tree.

    All properties are computed from the path string — no filesystem access.
    """

    path: Path

    @property
    def type(self) -> str:
        """'action', 'experiment', or 'sequence' parsed from filename stem."""
        suffix = self.path.stem.rsplit("-", 1)[-1]
        return ABR_MAP.get(suffix, suffix)

    @property
    def timestamp(self) -> datetime:
        """Timestamp parsed from the YYYYMMDDTHHMMSS prefix of the filename."""
        match = re.match(r"(\d{8}T\d{6})", self.path.stem)
        if match:
            return datetime.strptime(match.group(1), "%Y%m%dT%H%M%S")
        return datetime.min

    @property
    def status(self) -> str:
        """'active', 'finished', or 'synced' derived from RUNS_* parent dir."""
        for part in self.path.parts:
            if part == "RUNS_ACTIVE":
                return "active"
            if part == "RUNS_FINISHED":
                return "finished"
            if part == "RUNS_SYNCED":
                return "synced"
        return "unknown"

    @property
    def active_path(self) -> Path:
        return _swap_runs_dir(self.path, "RUNS_ACTIVE")

    @property
    def finished_path(self) -> Path:
        return _swap_runs_dir(self.path, "RUNS_FINISHED")

    @property
    def synced_path(self) -> Path:
        return _swap_runs_dir(self.path, "RUNS_SYNCED")

    @property
    def prg_path(self) -> Path:
        """Sidecar .prg path under RUNS_SYNCED (same stem as yml)."""
        return self.synced_path.with_suffix(".prg")

    @property
    def relative_path(self) -> str:
        """Path relative to the RUNS_* root directory."""
        parts = list(self.path.parts)
        for i, part in enumerate(parts):
            if part.startswith("RUNS_"):
                return str(Path(*parts[i + 1 :]))
        return str(self.path)


@dataclass(frozen=True)
class Progress:
    """Immutable sync state loaded from a .prg sidecar file."""

    s3_done: bool = False
    api_done: bool = False
    proc_states: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "Progress":
        return cls(
            s3_done=d.get("s3", False),
            api_done=d.get("api", False),
            proc_states={
                k: v for k, v in d.items() if k not in ("s3", "api", "yml")
            },
        )

    def to_dict(self, yml_path: str = "") -> dict:
        return {
            "yml": yml_path,
            "s3": self.s3_done,
            "api": self.api_done,
            **self.proc_states,
        }


@dataclass
class SyncJob:
    """A HelaoYml paired with its Progress, ready for SyncEngine."""

    yml: HelaoYml
    progress: Progress
    priority: int = 0  # 0=action, 1=experiment, 2=sequence

    def __lt__(self, other: "SyncJob") -> bool:
        return self.priority < other.priority
