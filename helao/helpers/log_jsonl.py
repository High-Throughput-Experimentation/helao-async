"""JSONL log records: serializer, rotating writer, sequence dedup, sink handler.

Design: docs/superpowers/specs/2026-10-26-jsonl-unified-logging-design.md (§1, §2).
"""

import gzip
import json
import logging
import os
import queue
import re
import shutil
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

LOG_ENDPOINT_ENV = "HELAO_LOG_ENDPOINT"
ROTATE_RECORDS = 300_000
RETAIN_DAYS = 90
GRACE_S = 10.0
BUFFER_SIZE = 2000
MAX_PERIOD = 16
HWM = 1000
LEDGER_FRAME = b"ledger"
EXTRA_KEYS = (
    "repeat_count",
    "repeat_period",
    "event",
    "kind",
    "uuid",
    "path",
    "bytes",
    "sha256",
    "reason",
)

_FMT = logging.Formatter()


def _message(record: logging.LogRecord) -> str:
    try:
        return record.getMessage()
    except Exception:
        # printf-style args that do not match: keep the raw template
        return str(record.msg)


def _exc_text(record: logging.LogRecord):
    if record.exc_info and not record.exc_text:
        record.exc_text = _FMT.formatException(record.exc_info)
    return record.exc_text or None


def is_artifact(record) -> bool:
    """True for the artefact hash records of spec §5."""
    return str(getattr(record, "event", "") or "").startswith("artifact_")


def fingerprint(record: logging.LogRecord) -> tuple:
    """Identity used by the sequence dedup: level, call site, message, traceback."""
    return (
        record.levelno,
        record.pathname,
        record.lineno,
        _message(record),
        _exc_text(record),
    )


def record_to_json(
    record: logging.LogRecord, seq: int, offset_seconds: float = 0.0
) -> bytes:
    """One ``\\n``-terminated UTF-8 JSON line for ``record`` (spec §1)."""
    ts = datetime.fromtimestamp(record.created + offset_seconds, tz=timezone.utc)
    doc = {
        "ts": ts.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "level": record.levelname,
        "server": record.name,
        "pid": record.process,
        "seq": seq,
        "func": record.funcName,
        "file": record.filename,
        "line": record.lineno,
        "msg": _message(record),
    }
    exc = _exc_text(record)
    if exc:
        doc["exc"] = exc
    for key in EXTRA_KEYS:
        value = getattr(record, key, None)
        if value is not None:
            doc[key] = value
    line = json.dumps(doc, ensure_ascii=False, default=str) + "\n"
    # a lone surrogate (device bytes decoded with surrogateescape) cannot be
    # encoded strictly; escape it rather than lose the record
    return line.encode("utf-8", "backslashreplace")


#: records written past a refused rename before trying again
ROTATE_RETRY = 1000


class RotatingJsonlWriter:
    """Append-only JSONL file that rotates every ``rotate_records`` records.

    At rotation the live file is renamed to ``<stem>_<YYYYmmddTHHMMSS>.jsonl``
    and a fresh one is opened before the next write; a daemon thread gzips the
    renamed file and deletes the plain copy ``grace_s`` later (a viewer may
    still be reading it). ``shared=True`` re-checks the inode before each write
    so a second process with the same stem never appends into a file the first
    one renamed.
    """

    def __init__(
        self,
        log_dir,
        stem: str,
        *,
        rotate_records: int = ROTATE_RECORDS,
        retain_days=RETAIN_DAYS,
        grace_s: float = GRACE_S,
        shared: bool = False,
    ):
        self.dir = Path(log_dir)
        self.stem = stem
        self.path = self.dir / f"{stem}.jsonl"
        self.rotate_records = rotate_records
        self.retain_days = retain_days
        self.grace_s = grace_s
        self.shared = shared
        self.rotated_re = re.compile(
            rf"^{re.escape(stem)}_\d{{8}}T\d{{6}}(?:_\d+)?\.jsonl(?:\.gz)?$"
        )
        self._fh = None
        self._ino = None
        self._count = 0
        self._retry_at = None
        self._queue: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._thread = None

    def _open(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        self._count = 0
        if self.path.exists():
            with open(self.path, "rb") as f:
                self._count = sum(1 for _ in f)
        self._fh = open(self.path, "ab", buffering=0)
        self._ino = os.fstat(self._fh.fileno()).st_ino

    def _moved(self) -> bool:
        try:
            return os.stat(self.path).st_ino != self._ino
        except FileNotFoundError:
            return True

    def write(self, data: bytes) -> None:
        """Append one serialized record; rotate when the count is reached."""
        if self._fh is None:
            self._open()
            for p in sorted(self.dir.iterdir()):
                if p.suffix == ".jsonl" and self.rotated_re.match(p.name):
                    self._queue_compress(p)
            self._prune()
        elif self.shared and self._moved():
            self._fh.close()
            self._open()
        self._fh.write(data)
        self._count += 1
        due = self._retry_at if self._retry_at is not None else self.rotate_records
        if self._count >= due:
            self._rotate()

    def _rotate(self):
        stamp = time.strftime("%Y%m%dT%H%M%S")
        dest, n = self.dir / f"{self.stem}_{stamp}.jsonl", 0
        while dest.exists() or Path(f"{dest}.gz").exists():
            n += 1
            dest = self.dir / f"{self.stem}_{stamp}_{n}.jsonl"
        self._fh.close()
        try:
            os.rename(self.path, dest)
        except FileNotFoundError:
            dest = None  # a process sharing this stem rotated it first
        except PermissionError:
            # Windows: a reader holds the live file; keep appending, retry later
            if self._retry_at is None:
                sys.stderr.write(
                    f"log rotation of {self.path} refused (file in use); "
                    f"retrying every {ROTATE_RETRY} records\n"
                )
            self._fh = open(self.path, "ab", buffering=0)
            self._retry_at = self._count + ROTATE_RETRY
            return
        self._retry_at = None
        self._open()
        if dest is not None:
            self._queue_compress(dest)
        self._prune()

    def _queue_compress(self, path: Path):
        if self._thread is None:
            self._thread = threading.Thread(
                target=self._compress_loop, name=f"gzip_{self.stem}", daemon=True
            )
            self._thread.start()
        self._queue.put(path)

    def _compress_loop(self):
        while True:
            path = self._queue.get()
            if path is None:
                return
            try:
                with open(path, "rb") as fin, gzip.open(f"{path}.gz", "wb") as fout:
                    shutil.copyfileobj(fin, fout, 1 << 20)
                self._stop.wait(self.grace_s)
                os.remove(path)
            except OSError as exc:
                sys.stderr.write(f"log gzip of {path} failed: {exc}\n")

    def _prune(self):
        if self.retain_days is None:
            return
        cutoff = time.time() - self.retain_days * 86400
        for p in self.dir.iterdir():
            if p.name.endswith(".gz") and self.rotated_re.match(p.name):
                try:
                    if p.stat().st_mtime < cutoff:
                        p.unlink()
                except OSError:
                    pass

    def close(self) -> None:
        """Close the live file and finish queued compressions (grace skipped)."""
        if self._fh is not None:
            self._fh.close()
            self._fh = None
        if self._thread is not None:
            self._stop.set()
            self._queue.put(None)
            self._thread.join(timeout=60)
            self._thread = None


class SequenceDeduper:
    """Collapse a repeating sequence of up to ``max_period`` records (spec §1).

    A cycle of period ``p`` is confirmed when the last ``p`` fingerprints equal
    the ``p`` before them; both occurrences have already been emitted. Further
    records that continue the cycle are held back and each full repetition is
    counted. A record that breaks the cycle emits one summary and then the
    held-back partial cycle. A summary is also emitted at a cycle boundary once
    ``interval`` seconds have passed since the cycle (or the last summary)
    started. ``interval == 0`` disables dedup.
    """

    def __init__(
        self, max_period: int = MAX_PERIOD, interval: float = 10.0, clock=time.monotonic
    ):
        self.max_period = max_period
        self.interval = interval
        self.clock = clock
        self._hist: deque = deque(maxlen=2 * max_period)
        self._cycle = None

    def feed(self, fp, item) -> list:
        out = []
        c = self._cycle
        if c is not None:
            if fp == c["pattern"][c["pos"]]:
                c["held"].append(item)
                c["pos"] += 1
                if c["pos"] == len(c["pattern"]):
                    c["count"] += 1
                    c["last"] = item
                    c["held"] = []
                    c["pos"] = 0
                    if self.clock() - c["started"] >= self.interval:
                        out.append(("summary", len(c["pattern"]), c["count"], item))
                        c["count"] = 0
                        c["started"] = self.clock()
                return out
            out.extend(self._close())
        out.append(("record", item))
        if not self.interval:
            return out
        self._hist.append(fp)
        hist = list(self._hist)
        for p in range(1, min(self.max_period, len(hist) // 2) + 1):
            if hist[-p:] == hist[-2 * p : -p]:
                self._cycle = {
                    "pattern": hist[-p:],
                    "pos": 0,
                    "count": 0,
                    "held": [],
                    "started": self.clock(),
                    "last": item,
                }
                self._hist.clear()
                break
        return out

    def _close(self) -> list:
        c, self._cycle = self._cycle, None
        out = []
        if c["count"]:
            out.append(("summary", len(c["pattern"]), c["count"], c["last"]))
        out.extend(("record", h) for h in c["held"])
        return out

    def flush(self) -> list:
        """Everything still pending: a summary and any held-back records."""
        return self._close() if self._cycle is not None else []
