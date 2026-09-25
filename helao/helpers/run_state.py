"""Append-only per-server journal of run records that are not yet done.

HELAO used to encode a record's lifecycle in the name of the directory it
lived in, so a state change meant copying a tree. This journal holds that
state as data instead: one file per writing server under ``<root>/STATES``,
one JSON object per line, appended.

Only the live working set is persisted. A record that reaches a terminal
state gets a ``done`` tombstone, and compaction drops it entirely -- absence
means done, and nothing ever queries for a done record (spec §3 D3). A
station's working set is therefore tens to hundreds of entries regardless of
how long it has been running.

Exactly one process writes each file (spec §4.1), so there is no locking
here. A crash during an append can only truncate the final line; every
earlier record is intact, which is the reason for an append-only journal
rather than a rewritten document.

The journal is an index, not the source of truth. ``rebuild_from_tree``
reconstructs it from the run tree (spec §4.5).

Spec: docs/superpowers/specs/2026-09-25-runs-layout-and-state-journal-design.md §4
"""

__all__ = [
    "ACTIVE",
    "COMPACT_MIN_LINES",
    "COMPACT_RATIO",
    "DONE",
    "UNSYNCED",
    "RunStateJournal",
    "root_relative",
]

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from helao.helpers import helao_logging as logging

LOGGER = logging.LOGGER if logging.LOGGER is not None else logging.make_logger(__file__)

ACTIVE = "active"
UNSYNCED = "unsynced"
DONE = "done"

#: Compaction fires only when the file is both absolutely large and mostly
#: dead weight. The floor stops a quiet station from compacting constantly;
#: the ratio ties the trigger to how much of the file is tombstones rather
#: than to a size someone guessed. Starting points, to be checked against a
#: real campaign's line counts (spec §4.4).
COMPACT_MIN_LINES = 1000
COMPACT_RATIO = 10


def root_relative(path, root) -> str:
    """A station-root-relative, forward-slash path (spec §4.2).

    Absolute paths recorded into sidecars are what made moving a station root
    strand records forever, so nothing this module persists is absolute. A
    path outside ``root`` is returned as-is rather than raising: the caller is
    recording, not validating, and a surprising path is more useful in the
    journal than an exception during a finish.
    """
    try:
        return Path(path).resolve().relative_to(Path(str(root)).resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


class RunStateJournal:
    """One server's journal of records that are still active or unsynced.

    Args:
        states_root: The station's ``<root>/STATES`` directory.
        server_key: The writing server's config key, e.g. ``ORCH`` or ``SYNC``.
    """

    def __init__(self, states_root, server_key: str):
        self.states_root = Path(states_root)
        self.server_key = server_key
        self.path = self.states_root / f"runstate_{server_key}.jsonl"

    def append(
        self,
        uuid: str,
        kind: str,
        state: str,
        path: str,
        parent: Optional[str] = None,
    ) -> None:
        """Record one state transition and compact if the file has earned it.

        Args:
            uuid: The record's action/experiment/sequence uuid.
            kind: ``action`` | ``experiment`` | ``sequence``.
            state: ``active`` | ``unsynced`` | ``done``.
            path: The record's directory, **relative to the station root**,
                forward-slash separated. Absolute paths are what made moving
                a station root strand records forever; the journal must not
                reintroduce that (spec §4.2).
            parent: Parent record uuid, or ``None`` for a sequence.
        """
        record = {
            "ts": datetime.now().isoformat(),
            "uuid": str(uuid),
            "kind": kind,
            "state": state,
            "path": str(path).replace("\\", "/"),
            "parent": str(parent) if parent else None,
        }
        self.states_root.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, separators=(",", ":")) + "\n")
        self._maybe_compact()

    def working_set(self) -> dict:
        """Records that are not done, keyed by uuid, newest state per uuid.

        Raises:
            ValueError: A line other than the last one does not parse, which
                is real corruption rather than a torn write.
        """
        return self._replay()[0]

    def compact(self) -> None:
        """Rewrite the file as one line per surviving record.

        Written to a ``.tmp`` sibling, flushed and fsynced, then
        ``os.replace``'d onto the live name, so a reader either sees the whole
        old file or the whole new one.
        """
        survivors, _ = self._replay()
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        self.states_root.mkdir(parents=True, exist_ok=True)
        with tmp.open("w", encoding="utf-8") as f:
            for record in survivors.values():
                f.write(json.dumps(record, separators=(",", ":")) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)

    def _replay(self) -> tuple:
        """Return ``(working_set, line_count)``."""
        if not self.path.exists():
            return {}, 0
        lines = self.path.read_text(encoding="utf-8").splitlines()
        records: dict = {}
        for i, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                if i == len(lines) - 1:
                    LOGGER.warning(
                        f"Discarding torn final line of {self.path}: {exc}. "
                        "A crash during an append damages only the last record."
                    )
                    continue
                raise ValueError(
                    f"{self.path} line {i + 1} is corrupt: {exc}. Rebuild the "
                    "journal from the run tree (spec §4.5)."
                ) from exc
            uuid = record.get("uuid")
            if not uuid:
                continue
            if record.get("state") == DONE:
                records.pop(uuid, None)
            else:
                records[uuid] = record
        return records, len(lines)

    def _maybe_compact(self) -> None:
        if not self.path.exists():
            return
        survivors, line_count = self._replay()
        if line_count < COMPACT_MIN_LINES:
            return
        if line_count < COMPACT_RATIO * max(len(survivors), 1):
            return
        LOGGER.debug(
            f"Compacting {self.path.name}: {line_count} lines, "
            f"{len(survivors)} live records."
        )
        self.compact()
