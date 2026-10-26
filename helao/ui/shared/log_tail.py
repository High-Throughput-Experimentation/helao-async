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


def _note(msg: str) -> dict:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return {
        "ts": ts,
        "level": "WARNING",
        "server": "logs",
        "pid": 0,
        "seq": 0,
        "msg": msg,
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
            rows.append(json.loads(line))
        except ValueError:
            continue
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
        st = p.stat()
        start = max(0, st.st_size - CHUNK)
        with open(p, "rb") as f:
            f.seek(start)
            chunk = f.read(st.st_size - start)
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
    for p in live.parent.glob(f"{live.stem}_*.jsonl"):
        try:
            if p.stat().st_ino == cur["inode"]:
                rows, _ = _read_from(p, cur)
                return rows
        except OSError:
            continue
    return [_note(f"{live.name} rotated; records written just before may be missing")]


def tail_poll(log_dir, cursors: list):
    """Records appended since ``cursors``; follows a rotation to its renamed file."""
    known = {c["path"]: c for c in cursors}
    out, new = [], []
    for p in live_files(log_dir):
        st = p.stat()
        cur = known.get(str(p)) or {"path": str(p), "inode": st.st_ino, "offset": 0}
        if st.st_ino != cur["inode"] or st.st_size < cur["offset"]:
            out += _finish_rotated(p, cur)
            cur = {"path": str(p), "inode": st.st_ino, "offset": 0}
        rows, cur = _read_from(p, cur)
        out += rows
        new.append(cur)
    return out, new


def merge(old: list, new: list, keep: int) -> list:
    """``old`` + ``new`` without duplicate ``(server, pid, seq, ts)``, by ``ts``, newest ``keep``."""
    seen, out = set(), []
    for r in old + new:
        key = (r.get("server"), r.get("pid"), r.get("seq"), r.get("ts"))
        if r.get("server") != "logs" and key in seen:
            continue
        seen.add(key)
        out.append(r)
    out.sort(key=lambda r: r.get("ts", ""))
    return out[-keep:]


def filter_records(records, servers, min_level: str, text: str) -> list:
    floor = LEVELS.get(min_level, 0)
    needle = text.lower()
    return [
        r
        for r in records
        if (servers is None or r.get("server") in servers)
        and LEVELS.get(r.get("level"), 0) >= floor
        and (not needle or needle in (r.get("msg", "") + r.get("exc", "")).lower())
    ]


def to_rows(records) -> list:
    """Newest-first ``[ts, level, server, msg, color]`` rows for the table."""
    rows = []
    for r in reversed(records):
        msg = r.get("msg", "")
        if r.get("exc"):
            msg = f"{msg}\n{r['exc']}"
        level = r.get("level", "")
        rows.append(
            [
                r.get("ts", ""),
                level,
                r.get("server", ""),
                msg,
                LOG_LEVEL_TEXT.get(level, LOG_LEVEL_TEXT["INFO"]),
            ]
        )
    return rows
