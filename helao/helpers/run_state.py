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
    "rebuild_from_tree",
    "root_relative",
]

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import UUID

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


_KIND_BY_SUFFIX = {"-seq": "sequence", "-exp": "experiment", "-act": "action"}
_UUID_KEY = {
    "sequence": "sequence_uuid",
    "experiment": "experiment_uuid",
    "action": "action_uuid",
}
_PARENT_KIND = {"action": "experiment", "experiment": "sequence"}

#: A record yml is read only at its two ends, and both ends are needed. An
#: action carries its own uuid on line 3 and its parent's on line 19, but a
#: sequence's own uuid sits seven lines from the *end* of a file measured in
#: hundreds of thousands of lines -- ``sequence_params`` and
#: ``planned_experiments`` are serialized before it -- and an experiment's
#: parent ``sequence_uuid`` lands ~20 lines from its end for the same reason.
#: Measured across the 26.03-26.05 production archive, where seq ymls run
#: 427k-560k lines: a head-only read would recover no sequence uuid at all.
_HEAD_BYTES = 4096
_TAIL_BYTES = 8192


def _prg_is_complete(prg_path: Path) -> bool:
    """Whether a ``.prg`` sidecar reports its record fully shipped.

    Matched as whole top-level lines against what ``Progress`` actually
    writes (``yml_dumps`` renders a python bool as a bare lowercase
    ``true``/``false``), so a path inside ``files_s3`` cannot be mistaken for
    the flag. Read as flat text rather than through ``yml_load`` so that this
    module stays free of helao imports and a malformed sidecar degrades to
    "not complete" instead of raising mid-rebuild.
    """
    try:
        lines = prg_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    return "s3: true" in lines and "api: true" in lines


def _scan_top_level(path: Path, keys: set) -> dict:
    """``key: value`` pairs for ``keys``, from a bounded window of ``path``.

    Reads only the first :data:`_HEAD_BYTES` and last :data:`_TAIL_BYTES`, so
    the cost is flat whether the yml is 20 lines or half a million. Each
    chunk's boundary line is discarded: a fragment is a prefix of a real line
    and could otherwise yield a truncated value.
    """
    try:
        with path.open("rb") as f:
            head = f.read(_HEAD_BYTES)
            size = f.seek(0, os.SEEK_END)
            f.seek(max(0, size - _TAIL_BYTES))
            tail = f.read(_TAIL_BYTES)
    except OSError:
        return {}
    lines = head.decode("utf-8", "replace").splitlines()
    if size > _HEAD_BYTES:
        lines = lines[:-1]
    tail_lines = tail.decode("utf-8", "replace").splitlines()
    lines += tail_lines[1:] if size > _TAIL_BYTES else tail_lines
    found: dict = {}
    for line in lines:
        key, sep, value = line.partition(": ")
        if sep and key in keys:
            found.setdefault(key, value.strip())
    return found


def _identify(yml: Path, kind: str) -> tuple:
    """``(uuid, parent)`` for a record, from a bounded read of its yml.

    The journal is keyed by uuid and eviction is a ``pop`` by that key, so
    keying a rebuilt record by anything else is not a cosmetic shortcut: the
    ``done`` tombstone the syncer later appends carries the record's real
    uuid, would pop nothing, and the phantom would survive every subsequent
    compaction (spec §3 D3, §4.2).

    A yml too damaged to yield one falls back to the stem and warns rather
    than raising -- one bad record must not cost the whole rebuild -- and the
    warning says what the leftover entry will be.
    """
    self_key = _UUID_KEY[kind]
    parent_key = _UUID_KEY.get(_PARENT_KIND.get(kind, ""))
    found = _scan_top_level(yml, {self_key, parent_key} - {None})
    try:
        own = str(UUID(found[self_key]))
    except (KeyError, TypeError, ValueError):
        LOGGER.warning(
            f"No parseable {self_key} in {yml}; keying its journal record by "
            "the file stem instead. A done tombstone carries the real uuid, "
            "so this entry will linger until the yml is repaired."
        )
        return yml.stem, None
    try:
        parent = str(UUID(found[parent_key]))
    except (KeyError, TypeError, ValueError):
        parent = None
    return own, parent


def rebuild_from_tree(runs_root, states_root, server_key: str) -> "RunStateJournal":
    """Reconstruct a journal by scanning the run tree (spec §4.5).

    The journal is an index; the ``.prg`` sidecar beside each record's yml is
    the authoritative receipt. A record whose ``.prg`` is present and complete
    is done and is not emitted. Everything else is emitted as ``unsynced``,
    keyed by the uuid read out of its yml.

    This is a full walk of ``runs_root``, which is affordable because the new
    tree accumulates only from cut-over forward -- years of history stay in the
    legacy ``RUNS_*`` trees and are never scanned. It runs on cold start after
    a lost or corrupt journal, never on a hot path.

    Args:
        runs_root: The station's ``<root>/RUNS`` directory.
        states_root: The station's ``<root>/STATES`` directory.
        server_key: Journal owner, e.g. ``SYNC``.

    Returns:
        The rebuilt, already-written journal.
    """
    runs_root = Path(runs_root)
    journal = RunStateJournal(states_root, server_key)
    root_name = runs_root.name
    entries = []

    for yml in sorted(runs_root.rglob("*.yml")):
        kind = _KIND_BY_SUFFIX.get(yml.stem[-4:])
        if kind is None:
            continue
        if _prg_is_complete(yml.with_suffix(".prg")):
            continue
        uuid, parent = _identify(yml, kind)
        rel = yml.parent.relative_to(runs_root).as_posix()
        entries.append(
            {
                "ts": datetime.now().isoformat(),
                "uuid": uuid,
                "kind": kind,
                "state": UNSYNCED,
                "path": f"{root_name}/{rel}" if rel != "." else root_name,
                "parent": parent,
            }
        )

    journal.states_root.mkdir(parents=True, exist_ok=True)
    tmp = journal.path.with_suffix(journal.path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for record in entries:
            f.write(json.dumps(record, separators=(",", ":")) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, journal.path)
    LOGGER.info(
        f"Rebuilt {journal.path.name} from {runs_root}: "
        f"{len(entries)} unsynced record(s)."
    )
    return journal
