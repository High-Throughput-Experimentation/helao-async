"""JSONL log records: serializer, rotating writer, sequence dedup, sink handler.

Design: docs/superpowers/specs/2026-10-26-jsonl-unified-logging-design.md (§1, §2).
"""

import copy
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
import zlib
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import zmq

LOG_ENDPOINT_ENV = "HELAO_LOG_ENDPOINT"
ROTATE_RECORDS = 300_000
RETAIN_DAYS = 90
GRACE_S = 10.0
TMP_MAX_AGE_S = 3600
BUFFER_SIZE = 3000
MAX_PERIOD = 16
HWM = 1000
#: kernel buffer bytes on the PUSH (and, in Task 5, the PULL) socket, so the
#: in-flight bound is the zmq HWMs plus a few tens of KB, not megabytes
SOCK_BUF = 65536
#: endpoints whose handshake wait timed out; later connects skip the wait
_NO_WAIT: set = set()
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


def _clean(value):
    """Turn a lone surrogate into literal ``\\udcff`` text: the JSON escape of
    one makes pandas and pyarrow reject the whole file."""
    if isinstance(value, str):
        return value.encode("utf-8", "backslashreplace").decode("utf-8")
    return value


def record_to_json(
    record: logging.LogRecord, seq: int, offset_seconds: float = 0.0
) -> bytes:
    """One ``\\n``-terminated UTF-8 JSON line for ``record`` (spec §1)."""
    ts = datetime.fromtimestamp(record.created + offset_seconds, tz=timezone.utc)
    doc = {
        "ts": ts.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "level": record.levelname,
        "server": _clean(record.name),
        "pid": record.process,
        "seq": seq,
        "func": _clean(record.funcName),
        "file": _clean(record.filename),
        "line": record.lineno,
        "msg": _clean(_message(record)),
    }
    exc = _exc_text(record)
    if exc:
        doc["exc"] = _clean(exc)
    for key in EXTRA_KEYS:
        value = getattr(record, key, None)
        if value is not None:
            doc[key] = _clean(value)
    line = json.dumps(doc, ensure_ascii=False, default=str) + "\n"
    return line.encode("utf-8")


#: records written past a refused rename before trying again
ROTATE_RETRY = 1000


class RotatingJsonlWriter:
    """Append-only JSONL file that rotates every ``rotate_records`` records.

    At rotation the live file is renamed to ``<stem>_<YYYYmmddTHHMMSS>.jsonl``
    and a fresh one is opened before the next write; a daemon thread gzips the
    renamed file and deletes the plain copy ``grace_s`` later (a viewer may
    still be reading it).

    ``shared=True`` is for several writers (processes) with one stem. They keep
    no persistent handle: each ``write()`` opens the live file in append mode,
    writes the line and closes it, so a rename is never blocked (Windows) and
    never appended past. The count is the live file's line count read at the
    first write plus the writer's own writes, so k writers sharing a stem can
    grow the file to about k x ``rotate_records`` before it rotates.
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
        self.tmp_re = re.compile(rf"^{re.escape(stem)}_.*\.jsonl\.gz\..*\.tmp$")
        self._started = False
        self._fh = None
        self._count = 0
        self._retry_at = None
        self._queue: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._thread = None

    def _start(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            with open(self.path, "rb") as f:
                self._count = sum(1 for _ in f)
        for p in sorted(self.dir.iterdir()):
            if p.suffix == ".jsonl" and self.rotated_re.match(p.name):
                self._queue_compress(p)
        self._sweep_tmp()
        self._prune()
        self._started = True

    def _sweep_tmp(self):
        # compressor temp files orphaned by a crash (a live one is minutes old at most)
        cutoff = time.time() - TMP_MAX_AGE_S
        for p in self.dir.iterdir():
            if self.tmp_re.match(p.name):
                try:
                    if p.stat().st_mtime < cutoff:
                        p.unlink()
                except OSError:
                    pass

    def write(self, data: bytes) -> None:
        """Append one serialized record; rotate when the count is reached."""
        self.write_many([data])

    def write_many(self, lines: list) -> None:
        """Append serialized records, one ``write()`` per file they land in.

        Each line counts; the batch is cut at the line where the rotation
        threshold is reached, so a rotated file never holds more than the
        threshold from this writer.
        """
        if not self._started:
            self._start()
        i = 0
        while i < len(lines):
            due = self._retry_at if self._retry_at is not None else self.rotate_records
            batch = lines[i : i + max(1, due - self._count)]
            data = b"".join(batch)
            if self.shared:
                with open(self.path, "ab") as f:
                    f.write(data)
            else:
                if self._fh is None:
                    self._fh = open(self.path, "ab", buffering=0)
                self._fh.write(data)
            self._count += len(batch)
            i += len(batch)
            if self._count >= due:
                try:
                    self._rotate()
                except Exception as exc:  # the records are written; never raise now
                    sys.stderr.write(f"log rotation of {self.path} failed: {exc}\n")

    def _rotate(self):
        stamp = time.strftime("%Y%m%dT%H%M%S")
        dest, n = self.dir / f"{self.stem}_{stamp}.jsonl", 0
        while dest.exists() or Path(f"{dest}.gz").exists():
            n += 1
            dest = self.dir / f"{self.stem}_{stamp}_{n}.jsonl"
        if self._fh is not None:
            fh, self._fh = self._fh, None  # next write() reopens if we bail out
            fh.close()
        try:
            os.rename(self.path, dest)
        except FileNotFoundError:
            dest = None  # a process sharing this stem rotated it first
        except OSError as exc:
            # e.g. Windows: a reader holds the live file; keep appending, retry later
            if self._retry_at is None:
                sys.stderr.write(
                    f"log rotation of {self.path} refused ({exc}); "
                    f"retrying every {ROTATE_RETRY} records\n"
                )
            self._retry_at = self._count + ROTATE_RETRY
            return
        self._retry_at = None
        self._count = 0
        if not self.shared:
            self._fh = open(self.path, "ab", buffering=0)
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
            tmp = f"{path}.gz.{os.getpid()}.{threading.get_ident()}.tmp"
            try:
                try:
                    fin = open(path, "rb")
                except FileNotFoundError:
                    continue  # a peer already finished this file
                with fin, gzip.open(tmp, "wb") as fout:
                    shutil.copyfileobj(fin, fout, 1 << 20)
                os.replace(tmp, f"{path}.gz")
                self._stop.wait(self.grace_s)
                try:
                    os.remove(path)
                except FileNotFoundError:
                    pass
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
    started. ``interval == 0`` disables dedup. Every fed fingerprint goes into
    the history, so a cycle containing an adjacent repeat is still found.
    """

    def __init__(
        self,
        max_period: int = MAX_PERIOD,
        interval: float = 10.0,
        clock=time.monotonic,
    ):
        self.max_period = max_period
        self.interval = interval
        self.clock = clock
        self._hist: deque = deque(maxlen=2 * max_period)
        self._cycle = None

    def feed(self, fp, item) -> list:
        out = []
        c = self._cycle
        if self.interval:
            self._hist.append(fp)
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


def _summary_record(
    period: int, count: int, last: logging.LogRecord
) -> logging.LogRecord:
    rec = copy.copy(last)
    times = f"{count} time{'s' if count != 1 else ''}"
    if period == 1:
        rec.msg = f"{_message(last)} [previous message repeated {times}]"
    else:
        rec.msg = f"[previous {period}-message sequence repeated {times}, ending: {_message(last)}]"
    rec.args = None
    rec.exc_info = None
    rec.exc_text = None
    rec.created = time.time()
    rec.repeat_count = count
    rec.repeat_period = period
    return rec


class JsonlSinkHandler(logging.Handler):
    """Dedup, serialize, and send each record to the launcher, else to own file.

    The ZMQ socket is touched only inside ``emit``/``close``, which
    ``logging.Handler`` runs under the handler lock, so access is serialized
    across the event-loop thread and executor threads.
    """

    def __init__(
        self,
        stem: str,
        log_dir,
        *,
        endpoint=None,
        offset_seconds: float = 0.0,
        dedup_interval: float = 10.0,
        rotate_records: int = ROTATE_RECORDS,
        connect_timeout_ms: int = 1000,
        min_level: int = 0,
    ):
        super().__init__()
        # The handler's own level stays 0 so artefact records always arrive;
        # ordinary records below ``min_level`` are dropped in emit().
        self.min_level = min_level
        self.stem = stem
        self.log_dir = Path(log_dir)
        self.endpoint = endpoint
        self.offset_seconds = offset_seconds
        self.rotate_records = rotate_records
        self.deduper = SequenceDeduper(interval=dedup_interval)
        self.recent: deque = deque(maxlen=BUFFER_SIZE)
        self.seq = 0
        self._spilled = 0
        self._connected = False
        self._log = None
        self._ledger = None
        self._sock = None
        self._pid = os.getpid()
        if endpoint:
            self._connect(connect_timeout_ms)

    @property
    def fallback_path(self) -> Path:
        return self.log_dir / f"{self.stem}.jsonl"

    def _connect(self, timeout_ms: int, flag: bool = True):
        sock = zmq.Context.instance().socket(zmq.PUSH)
        sock.setsockopt(zmq.IMMEDIATE, 1)
        sock.setsockopt(zmq.SNDHWM, HWM)
        sock.setsockopt(zmq.SNDBUF, SOCK_BUF)
        sock.setsockopt(zmq.LINGER, 500)
        mon = sock.get_monitor_socket(zmq.EVENT_HANDSHAKE_SUCCEEDED)
        try:
            sock.connect(self.endpoint)
            # with IMMEDIATE, sends before the ZMTP handshake completes raise Again;
            # wait once (process start) so startup records reach the launcher
            if self.endpoint in _NO_WAIT:
                timeout_ms = 0
            if mon.poll(timeout_ms):
                mon.recv_multipart()
            elif timeout_ms and flag:
                _NO_WAIT.add(self.endpoint)
            sock.disable_monitor()
        except BaseException:
            mon.close(linger=0)
            sock.close(linger=0)
            raise
        mon.close()
        self._sock = sock

    def _after_fork(self):
        # never use the parent's socket or file handles in a forked child
        self._pid = os.getpid()
        self._sock = None
        self._log = self._ledger = None
        self._connected = False
        self.deduper = SequenceDeduper(interval=self.deduper.interval)
        self.recent.clear()
        self._spilled = 0
        if self.endpoint:
            self._connect(200, flag=False)

    def _writer(self, ledger: bool) -> RotatingJsonlWriter:
        if ledger:
            if self._ledger is None:
                self._ledger = RotatingJsonlWriter(
                    self.log_dir,
                    f"artifacts_{self.stem}",
                    rotate_records=self.rotate_records,
                    retain_days=None,
                    shared=True,
                )
            return self._ledger
        if self._log is None:
            self._log = RotatingJsonlWriter(
                self.log_dir, self.stem, rotate_records=self.rotate_records, shared=True
            )
        return self._log

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if os.getpid() != self._pid:
                self._after_fork()
            elif self._sock is None and self.endpoint:
                # closed behind our back (uvicorn's dictConfig runs
                # logging.shutdown on every handler): reattach
                try:
                    self._connect(1000)
                except Exception:
                    self._sock = None  # spill below rather than lose the record
            if is_artifact(record):
                self._out(record)
                return
            if record.levelno < self.min_level:
                return
            for kind, *rest in self.deduper.feed(fingerprint(record), record):
                self._out(rest[0] if kind == "record" else _summary_record(*rest))
        except Exception:
            self.handleError(record)

    def _out(self, record: logging.LogRecord) -> None:
        self.seq += 1
        data = record_to_json(record, self.seq, self.offset_seconds)
        ledger = is_artifact(record)
        entry = [data, ledger, False]
        self.recent.append(entry)
        if self._sock is not None and self._send(data, ledger):
            entry[2] = True
            return
        self._spill(data, ledger)

    def _send(self, data: bytes, ledger: bool) -> bool:
        try:
            if self._spilled:
                note = logging.LogRecord(
                    self.stem,
                    logging.WARNING,
                    __file__,
                    0,
                    f"{self._spilled} records went to {self.fallback_path}",
                    None,
                    None,
                )
                marker = record_to_json(note, self.seq + 1, self.offset_seconds)
                self._sock.send(marker, zmq.NOBLOCK)
                self.seq += 1  # only once sent: a refused marker burns no seq
                self.recent.append([marker, False, True])
                self._spilled = 0
            self._sock.send_multipart(
                [LEDGER_FRAME, data] if ledger else [data], zmq.NOBLOCK
            )
        except zmq.Again:
            if self._connected:
                self._connected = False
                self._replay()
            return False
        self._connected = True
        _NO_WAIT.discard(self.endpoint)
        return True

    def _replay(self):
        # at-least-once: records still in socket buffers when the launcher died
        log, ledger = [], []
        for entry in list(self.recent):
            if entry[2]:
                log.append(entry[0])
                if entry[1]:
                    ledger.append(entry[0])
                entry[2] = False  # once only, or every flip re-spills it
        if log:
            self._writer(False).write_many(log)
        if ledger:
            self._writer(True).write_many(ledger)

    def _spill(self, data: bytes, ledger: bool, count: bool = True):
        self._writer(False).write(data)
        if ledger:
            self._writer(True).write(data)
        if count:
            self._spilled += 1

    def close(self) -> None:
        self.acquire()
        try:
            for kind, *rest in self.deduper.flush():
                self._out(rest[0] if kind == "record" else _summary_record(*rest))
            if self._sock is not None:
                self._sock.close()
                self._sock = None
            for w in (self._log, self._ledger):
                if w is not None:
                    w.close()
            self._log = self._ledger = None
        finally:
            self.release()
            super().close()


def _chunked(pd, src):
    """Stream ``src`` through pandas in chunks: one-shot parsing of a 300k-record
    file peaks near 1 GB."""
    with pd.read_json(src, lines=True, dtype=False, chunksize=20000) as rd:
        return pd.concat(list(rd), ignore_index=True)


def _read_one(p: Path):
    """Records of one JSONL file as a DataFrame, or None. A partial last line
    (a writer mid-append) is trimmed; unparseable lines are skipped with one
    warning on stderr."""
    import io

    import pandas as pd

    gz = p.name.endswith(".gz")
    opener = gzip.open if gz else open
    try:
        if gz:
            # a rotated file is complete; a damaged one raises EOFError/zlib.error,
            # which read_logs reports and skips (only bad JSON falls to the line parser)
            with gzip.open(p, "rb") as f:
                return _chunked(pd, f)
        with open(p, "rb") as f:
            f.seek(-1, os.SEEK_END)
            complete = f.read(1) == b"\n"
        if complete:  # no partial tail: let pandas read the path itself
            return _chunked(pd, p)
        with open(p, "rb") as f:
            raw = f.read()
        raw = raw[: raw.rfind(b"\n") + 1]
        if not raw:
            return None
        buf = io.BytesIO(raw)
        del raw  # the parse must not hold a second copy
        return _chunked(pd, buf)
    except ValueError:
        pass
    good, bad = [], 0
    with opener(p, "rb") as f:
        for ln in f:
            if not ln.endswith(b"\n"):
                continue  # partial tail
            try:
                rec = json.loads(ln)
            except ValueError:
                bad += 1
                continue
            if isinstance(rec, dict):
                good.append(rec)
            else:
                bad += 1
    sys.stderr.write(f"read_logs: skipped {bad} unparseable line(s) in {p}\n")
    return pd.DataFrame(good) if good else None


def read_logs(log_dir, server=None, *, ledger: bool = False):
    """All JSONL records under ``log_dir`` as one DataFrame sorted by ``ts``.

    Reads live and rotated (``.gz``) files; ``ledger=True`` reads only the
    ``artifacts_*`` ledger instead of the logs. Duplicates from replay are
    dropped on ``(server, pid, seq, ts)``: pid and seq alone repeat when a PID
    is reused by a later process.
    """
    import pandas as pd

    frames = []
    for p in sorted(Path(log_dir).iterdir()):
        if not p.name.endswith((".jsonl", ".jsonl.gz")):
            continue
        if p.name.startswith("artifacts_") != ledger:
            continue
        try:
            if not p.stat().st_size:
                continue
            df = _read_one(p)
        except (EOFError, zlib.error) as exc:
            sys.stderr.write(f"read_logs: skipped damaged file {p}: {exc!r}\n")
            continue
        except (OSError, ValueError):
            continue  # deleted or gzipped away between listing and reading
        if df is not None:
            frames.append(df)
    if not frames:
        df = pd.DataFrame(
            {
                "ts": pd.Series([], dtype="datetime64[us, UTC]"),
                "level": pd.Series([], dtype=object),
                "server": pd.Series([], dtype=object),
                "pid": pd.Series([], dtype="int64"),
                "seq": pd.Series([], dtype="int64"),
                "msg": pd.Series([], dtype=object),
            }
        )
        return df
    df = pd.concat(frames, ignore_index=True).drop_duplicates(
        ["server", "pid", "seq", "ts"]
    )
    if server is not None:
        df = df[df["server"] == server]
    df["ts"] = pd.to_datetime(df["ts"], utc=True).astype("datetime64[us, UTC]")
    return df.sort_values(["ts", "pid", "seq"], kind="stable").reset_index(drop=True)
