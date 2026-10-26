"""Tail a LOGS directory's JSONL files for the /logs page (spec §4).

Reflex-free so a Bokeh front end can reuse it. A cursor is
``{"path", "inode", "offset"}``; ``offset`` only ever advances past a complete
line, so a partial last line waits for the next poll.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from helao.ui.shared.palette import LOG_LEVEL_TEXT

CHUNK = 2 << 20
LEVELS = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
    "ALERT": 60,
}
_ROTATED = re.compile(r"_\d{8}T\d{6}(?:_\d+)?\.jsonl$")


def _s(x) -> str:
    """Text of a field a hand-written line may have typed wrongly."""
    return "" if x is None else str(x)


def _note(msg: str) -> dict:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return {
        "ts": ts,
        "level": "WARNING",
        "server": "logs",
        "pid": 0,
        "seq": 0,
        "msg": msg,
        "_note": True,
    }


def live_files(log_dir) -> list:
    """Live log files: the unified file and any fallback files, not ledgers or rotations."""
    return sorted(
        p
        for p in Path(log_dir).glob("*.jsonl")
        if not _ROTATED.search(p.name) and not p.name.startswith("artifacts_")
    )


def _parse(chunk: bytes):
    end = chunk.rfind(b"\n")
    if end < 0:
        return [], 0
    rows = []
    for line in chunk[:end].split(b"\n"):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows, end + 1


def _read_from(path: Path, cur: dict):
    with open(path, "rb") as f:
        f.seek(cur["offset"])
        chunk = f.read(CHUNK)
        rows, used = _parse(chunk)
        if used or len(chunk) < CHUNK:
            return rows, {**cur, "offset": cur["offset"] + used}
        # one line longer than CHUNK: skip to its end once it is complete
        pos = cur["offset"] + len(chunk)
        while True:
            more = f.read(CHUNK)
            if not more:
                return [], cur  # still being written
            nl = more.find(b"\n")
            if nl >= 0:
                skip_to = pos + nl + 1
                return [_note(f"{path.name}: a line over {CHUNK} bytes was skipped")], {
                    **cur,
                    "offset": skip_to,
                }
            pos += len(more)


def tail_init(log_dir, n: int = 2000):
    """The newest ``n`` records across the live files, and a cursor per file."""
    records, cursors = [], []
    for p in live_files(log_dir):
        try:
            st = p.stat()
            start = max(0, st.st_size - CHUNK)
            with open(p, "rb") as f:
                f.seek(start)
                chunk = f.read(st.st_size - start)
        except OSError:
            continue
        dropped = 0
        if start:
            dropped = chunk.find(b"\n") + 1  # first line is partial
            chunk = chunk[dropped:]
        rows, used = _parse(chunk)
        records += rows[-n:]
        cursors.append(
            {"path": str(p), "inode": st.st_ino, "offset": start + dropped + used}
        )
    return merge([], records, n), cursors


def _finish_rotated(live: Path, cur: dict) -> list:
    """Read the rotated file holding the cursor's inode to its end."""
    missing = [
        _note(f"{live.name} rotated; records written just before may be missing")
    ]
    if not cur[
        "inode"
    ]:  # st_ino 0 (FAT, some network mounts): inodes cannot identify a file
        return missing
    rotated = []
    for p in live.parent.glob(f"{live.stem}_*.jsonl"):
        try:
            rotated.append((p, p.stat()))
        except OSError:
            continue
    mine = next(((p, st) for p, st in rotated if st.st_ino == cur["inode"]), None)
    if mine is None:
        return missing
    p, st = mine
    rows = []
    try:
        while cur["offset"] < p.stat().st_size:
            got, nxt = _read_from(p, cur)
            rows += got
            if nxt["offset"] <= cur["offset"]:
                rows.append(
                    _note(f"{p.name}: tail not fully read (incomplete last line)")
                )
                break
            cur = nxt
    except OSError:
        return rows + missing
    # a newer rotated file means a rotation happened since our last poll
    if any(other.st_mtime > st.st_mtime for _, other in rotated):
        rows.append(
            _note(f"{live.name}: another rotation was skipped; records may be missing")
        )
    return rows


def tail_poll(log_dir, cursors: list):
    """Records appended since ``cursors``; follows a rotation to its renamed file."""
    known = {c["path"]: c for c in cursors}
    out, new, seen = [], [], set()
    for p in live_files(log_dir):
        seen.add(str(p))
        try:
            st = p.stat()
            cur = known.get(str(p)) or {"path": str(p), "inode": st.st_ino, "offset": 0}
            if st.st_ino != cur["inode"] or st.st_size < cur["offset"]:
                out += _finish_rotated(p, cur)
                cur = {"path": str(p), "inode": st.st_ino, "offset": 0}
            rows, cur = _read_from(p, cur)
        except OSError:
            if str(p) in known:
                new.append(known[str(p)])
            continue
        out += rows
        new.append(cur)
    # a file absent for one poll keeps its cursor, so a reappearing file finds its old tail
    new += [c for path, c in known.items() if path not in seen and c not in new]
    return out, new


def merge(old: list, new: list, keep: int) -> list:
    """``old`` + ``new`` without duplicate ``(server, pid, seq, ts)``, by ``ts``, newest ``keep``."""
    seen, out = set(), []
    for r in old + new:
        key = (r.get("server"), r.get("pid"), r.get("seq"), r.get("ts"))
        if not r.get("_note") and key in seen:
            continue
        seen.add(key)
        out.append(r)
    out.sort(key=lambda r: _s(r.get("ts")))
    return out[-keep:]


def filter_records(records, servers, min_level: str, text: str) -> list:
    floor = LEVELS.get(min_level, 0)
    needle = text.lower()
    return [
        r
        for r in records
        if (servers is None or r.get("server") in servers)
        and LEVELS.get(r.get("level"), 0) >= floor
        and (not needle or needle in (_s(r.get("msg")) + _s(r.get("exc"))).lower())
    ]


def to_rows(records) -> list:
    """Newest-first ``[ts, level, server, msg, color]`` rows for the table."""
    rows = []
    for r in reversed(records):
        msg = _s(r.get("msg"))
        if r.get("exc"):
            msg = f"{msg}\n{_s(r['exc'])}"
        level = r.get("level", "")
        rows.append(
            [
                _s(r.get("ts")),
                level,
                r.get("server", ""),
                msg,
                LOG_LEVEL_TEXT.get(level, LOG_LEVEL_TEXT["INFO"]),
            ]
        )
    return rows
