# JSONL Logs, Unified Launcher Log, Artefact Hashes, and /logs Page — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every HELAO process logs JSONL records to one launcher-owned file over a non-blocking ZMQ path, falls back to its own file without a launcher, rotates by record count, logs a SHA-256 for every finalized or rewritten output artefact into a never-deleted ledger, and the Reflex UI gets a live `/logs` page.

**Architecture:** A new `JsonlSinkHandler` (in `helao/helpers/log_jsonl.py`) replaces the text file handler inside `make_logger`. It deduplicates repeated message sequences, serializes each record to JSON bytes, and sends them with `NOBLOCK` over a ZMQ PUSH socket (`IMMEDIATE=1`) to a `LogCollector` thread in `launch.py`. On `zmq.Again` it replays its recent-records buffer and then writes to its own `RotatingJsonlWriter`. Artefact hashes (`helao/helpers/artifact_hash.py`) are ordinary log records with extra fields, which the handler and the collector also tee to a ledger file. `helao/ui/shared/log_tail.py` tails the files, and `helao/ui/reflex/logs.py` renders them.

**Tech Stack:** Python 3.14, stdlib `logging`/`hashlib`/`gzip`/`threading`, pyzmq (already a dependency), pandas 3 (for `read_logs` only), Reflex.

**Spec:** `docs/superpowers/specs/2026-10-26-jsonl-unified-logging-design.md`

## Global Constraints

- Run everything in the `helao` conda env with `PYTHONPATH` set to the repo root. Python is `/home/dan/miniforge3/envs/helao/bin/python` on the dev box. Tests run as `python -m pytest <file> -q`, one file per process.
- Rotation: `ROTATE_RECORDS = 300_000` records; the gzip runs on a separate thread; the next record never waits.
- Rotated plain copy is deleted `GRACE_S = 10.0` seconds after its gzip finishes.
- Retention: rotated log `.jsonl.gz` older than `RETAIN_DAYS = 90` days are deleted. Ledger files (`artifacts_*`) are never deleted.
- Recent-records buffer: `BUFFER_SIZE = 2000` per handler; `SNDHWM = RCVHWM = 1000`.
- Sequence dedup: periods 1 to `MAX_PERIOD = 16`; `dedup_interval` default 10 s (`DEFAULT_DEDUP_INTERVAL`), `0` disables dedup.
- Endpoint: `tcp://127.0.0.1:<log_port>`; env var `HELAO_LOG_ENDPOINT`; `log_port` defaults to one above the highest port any server occupies (Reflex occupies `port` and `port + 1`).
- Unified file: `<root>/LOGS/helao_<config_prefix>.jsonl`; ledger: `<root>/LOGS/artifacts_<config_prefix>.jsonl`; fallback: `<log_dir>/<name>.jsonl` and `<log_dir>/artifacts_<name>.jsonl`.
- Record keys: `ts` (UTC ISO-8601, microseconds, `Z`), `level`, `server`, `pid`, `seq`, `func`, `file`, `line`, `msg`, optional `exc`, optional `repeat_count`/`repeat_period`, optional `event`/`kind`/`uuid`/`path`/`bytes`/`sha256`/`reason`. `(server, pid, seq)` is the duplicate key.
- `make_logger`'s signature does not change.
- Never hardcode a colour outside `helao/ui/shared/palette.py` (`helao/core/tests/test_palette.py` enforces it).
- Before editing anything under `helao/ui/reflex/`, read `helao/ui/reflex/CLAUDE.md`. Before editing `launch.py`'s spawn path, read `helao/helpers/CLAUDE.md`.
- The parent repo is public: never name a private deployment in a tracked parent file. Private deployments are the `helao/deploy/*` directories that are their own git repos.
- Subagents never run `git add`, `commit`, `push`, or `stash`; every git call uses `git -C <repo>`. The **Commit** steps below are run by the main session, after user approval.
- Run `black` on changed Python files immediately before each commit, in the repo that owns them.

## Deviations from the spec (decided while planning)

The spec is updated in the same commit as this plan.

1. `log_artifact_hashes` lives in `helao/helpers/artifact_hash.py`, not `helao_logging.py`, because it imports `helao_logging` (a cycle otherwise). `read_logs` lives in `helao/helpers/log_jsonl.py` and is re-exported from `helao_logging`.
2. `reset_sync` does not change any record's bytes (it deletes `.prg`/`.lock` sidecars and extracts a zip), so it is not a rewrite site. The rewrite test uses `_record_rewrite.rewrite_dir` instead.
3. The record-level seam for act/exp/seq hashes is `MetaWriter.write_act/write_exp/write_seq`. Every write whose status list holds a terminal status (`finished`, `errored`, `aborted`, `skipped`, `estopped`, `retired`) logs `artifact_final`. A caller that passes `reason=` logs `artifact_rewritten`. A record re-written in-process with a terminal status logs a second `artifact_final`; consumers take the latest per `path`.
4. The writer opens files unbuffered, so every record is one `write` syscall and there is nothing to flush per batch.
5. The `/logs` table shows newest-first, so the latest records are always at the top without scroll JavaScript.

## Review Focus

1. **Windows rotation while a reader holds the file.** `os.rename` raises `PermissionError` on Windows if the viewer or `tail` has the live file open. Expected: no record is lost and nothing raises; rotation is retried after 1,000 more records, with one stderr warning. Test: Task 2, `test_rotation_retries_when_rename_is_refused`.
2. **Two processes with the same logger name write one fallback file.** For example, two module-level `make_logger(__file__)` loggers, or a restarted server overlapping its predecessor. Expected: every line stays intact and parseable, and after one process rotates, the other notices the inode change and reopens instead of appending into the renamed file. Test: Task 2, `test_shared_writer_reopens_after_another_rotates`.
3. **A message with a lone surrogate or control characters** (for example, bytes decoded with `errors="surrogateescape"` from a device). Expected: the record is still written as exactly one valid JSON line. Test: Task 1, `test_surrogates_and_newlines_stay_one_line`.
4. **A process forks after its logger exists** (a `multiprocessing` pool with the `fork` start method on Linux). Expected: the child never uses the parent's ZMQ socket or file handle; it reconnects or falls back on its own. Test: Task 4, `test_fork_resets_socket_and_writers`.
5. **One log line larger than the viewer's 2 MiB per-tick read** (for example, a dumped array). Expected: the viewer skips that line with a note row and keeps tailing, instead of stalling forever. Test: Task 10, `test_oversized_line_is_skipped_with_note`.

---

## File Structure

| File | Responsibility |
|---|---|
| `helao/helpers/log_jsonl.py` (new) | `record_to_json`, `RotatingJsonlWriter`, `SequenceDeduper`, `JsonlSinkHandler`, `read_logs`, constants. |
| `helao/helpers/log_collector.py` (new) | `LogCollector`, `resolve_log_port`, `log_endpoint`. |
| `helao/helpers/artifact_hash.py` (new) | `log_artifact_hashes`, `log_artifact_hashes_sync`, `record_uuid`. |
| `helao/helpers/helao_logging.py` | `make_logger` builds `JsonlSinkHandler`; old file handler and rotator removed; re-exports `read_logs`. |
| `launch.py` | Starts and stops the collector, sets the env var, and loses the stale `.txt` zip block. |
| `helao/helpers/helao_dirs.py` | Loses the stale `.txt` zip block. |
| `helao/hexagon/adapters/native/meta_writer.py` | Terminal-status record writes log hashes. |
| `helao/hexagon/app/action_host.py` | `write_act(action, reason=None)` passthrough; reconcile passes a reason. |
| `helao/hexagon/adapters/native/sync_driver.py` | `-prc.json` hash. |
| `helao/core/drivers/data/analysis_layout.py`, `analysis_driver.py` | `local_output_path`; `-ana.json` and outputs hashed. |
| `helao/core/tests/_record_rewrite.py`, `set_plate_id.py`, `set_run_use.py` | Rewrite hashes. |
| `helao/ui/shared/log_tail.py` (new) | File tailing, rotation follow, filters, rows. |
| `helao/ui/reflex/logs.py` (new), `helao/ui/reflex/app.py`, `helao/ui/shared/palette.py` | The `/logs` page. |
| Tests (new) | `helao/core/tests/test_log_jsonl.py`, `test_log_handler.py`, `test_log_collector.py`, `test_artifact_hash.py`, `test_artifact_hash_sites.py`, `test_artifact_hash_gate.py`, `test_log_tail.py`. |

---

### Task 1: JSON record serializer

**Files:**
- Create: `helao/helpers/log_jsonl.py`
- Test: `helao/core/tests/test_log_jsonl.py`

**Interfaces:**
- Produces:
  - `record_to_json(record: logging.LogRecord, seq: int, offset_seconds: float = 0.0) -> bytes`
  - `is_artifact(record) -> bool`
  - `fingerprint(record) -> tuple`
  - constants `LOG_ENDPOINT_ENV`, `ROTATE_RECORDS`, `RETAIN_DAYS`, `GRACE_S`, `BUFFER_SIZE`, `MAX_PERIOD`, `HWM`, `LEDGER_FRAME`, `EXTRA_KEYS`

- [ ] **Step 1: Write the failing test**

```python
"""JSONL record serialization (spec §1)."""

import json
import logging
import sys

import pandas as pd

from helao.helpers.log_jsonl import fingerprint, is_artifact, record_to_json


def _rec(msg="hello", level=logging.INFO, exc=None, **extra):
    r = logging.LogRecord("PSTAT", level, "/x/action_host.py", 512, msg, None, exc, "setup")
    r.created = 1_793_000_000.123456
    for k, v in extra.items():
        setattr(r, k, v)
    return r


def test_schema_keys_and_values():
    doc = json.loads(record_to_json(_rec(), 7))
    assert doc == {
        "ts": "2026-10-26T07:33:20.123456Z",
        "level": "INFO", "server": "PSTAT", "pid": doc["pid"], "seq": 7,
        "func": "setup", "file": "action_host.py", "line": 512, "msg": "hello",
    }


def test_offset_shifts_ts():
    doc = json.loads(record_to_json(_rec(), 1, offset_seconds=2.5))
    assert doc["ts"] == "2026-10-26T07:33:22.623456Z"


def test_exc_present_only_with_traceback():
    assert "exc" not in json.loads(record_to_json(_rec(), 1))
    try:
        raise ValueError("boom")
    except ValueError:
        doc = json.loads(record_to_json(_rec(exc=sys.exc_info()), 1))
    assert doc["exc"].startswith("Traceback") and "ValueError: boom" in doc["exc"]


def test_extra_keys_included_when_set():
    doc = json.loads(record_to_json(_rec(event="artifact_final", sha256="ab", bytes=3), 1))
    assert (doc["event"], doc["sha256"], doc["bytes"]) == ("artifact_final", "ab", 3)
    assert "reason" not in doc


def test_surrogates_and_newlines_stay_one_line():
    raw = record_to_json(_rec("a\nb\udcff\x00c"), 1)
    assert raw.endswith(b"\n") and raw.count(b"\n") == 1
    assert json.loads(raw)["msg"].startswith("a\nb")


def test_round_trips_through_pandas(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_bytes(b"".join(record_to_json(_rec(f"m{i}"), i) for i in range(3)))
    df = pd.read_json(p, lines=True, dtype=False)
    assert list(df["seq"]) == [0, 1, 2]
    assert pd.to_datetime(df["ts"], utc=True).dt.tz is not None


def test_is_artifact_and_fingerprint():
    assert is_artifact(_rec(event="artifact_rewritten"))
    assert not is_artifact(_rec())
    a, b = _rec("same"), _rec("same")
    assert fingerprint(a) == fingerprint(b)
    assert fingerprint(_rec("same", level=logging.WARNING)) != fingerprint(a)
    try:
        raise KeyError("k")
    except KeyError:
        c = _rec("same", exc=sys.exc_info())
    assert fingerprint(c) != fingerprint(a)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest helao/core/tests/test_log_jsonl.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'helao.helpers.log_jsonl'`

- [ ] **Step 3: Write the minimal implementation**

```python
"""JSONL log records: serializer, rotating writer, sequence dedup, sink handler.

Design: docs/superpowers/specs/2026-10-26-jsonl-unified-logging-design.md (§1, §2).
"""

import json
import logging
from datetime import datetime, timezone

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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest helao/core/tests/test_log_jsonl.py -q`
Expected: PASS (7 passed). If `test_schema_keys_and_values` fails only on `ts`, recompute the expected string with `datetime.fromtimestamp(1_793_000_000.123456, tz=timezone.utc)` and correct the literal. The literal is the test's independent expectation, so check it by hand rather than copying the code's output.

- [ ] **Step 5: Mutation check**

Temporarily drop `"backslashreplace"` from the encode call and confirm `test_surrogates_and_newlines_stay_one_line` fails; then restore it.

- [ ] **Step 6: Commit** (main session)

```bash
black helao/helpers/log_jsonl.py helao/core/tests/test_log_jsonl.py
git -C . add helao/helpers/log_jsonl.py helao/core/tests/test_log_jsonl.py
git -C . commit -m "feat(logging): JSONL record serializer"
```

---

### Task 2: `RotatingJsonlWriter`

**Files:**
- Modify: `helao/helpers/log_jsonl.py` (append)
- Test: `helao/core/tests/test_log_jsonl.py` (append)

**Interfaces:**
- Consumes: Task 1 constants.
- Produces:
  - `RotatingJsonlWriter(log_dir, stem, *, rotate_records=ROTATE_RECORDS, retain_days: float | None = RETAIN_DAYS, grace_s=GRACE_S, shared=False)`
  - methods `.write(data: bytes) -> None` and `.close() -> None`
  - attributes `.path: Path` (live file) and `.rotated_re: re.Pattern`

- [ ] **Step 1: Write the failing tests** (append)

```python
import gzip
import os
import re
import time
from pathlib import Path

from helao.helpers import log_jsonl
from helao.helpers.log_jsonl import RotatingJsonlWriter


def _wait(pred, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


def _lines(n, start=0):
    return [f'{{"seq": {i}}}\n'.encode() for i in range(start, start + n)]


def test_rotates_at_n_and_compresses_in_background(tmp_path):
    w = RotatingJsonlWriter(tmp_path, "helao_x", rotate_records=3, grace_s=0.2)
    for line in _lines(4):
        w.write(line)
    assert w.path.read_bytes() == b'{"seq": 3}\n'  # fresh live file at once
    assert _wait(lambda: list(tmp_path.glob("helao_x_*.jsonl.gz")))
    gz = next(tmp_path.glob("helao_x_*.jsonl.gz"))
    assert w.rotated_re.match(gz.name)
    assert gzip.open(gz).read() == b"".join(_lines(3))
    assert _wait(lambda: not list(tmp_path.glob("helao_x_*.jsonl")))  # grace over
    w.close()


def test_plain_copy_kept_during_grace(tmp_path):
    w = RotatingJsonlWriter(tmp_path, "s", rotate_records=1, grace_s=5.0)
    w.write(b"a\n")
    assert _wait(lambda: list(tmp_path.glob("s_*.jsonl.gz")))
    assert list(tmp_path.glob("s_*.jsonl"))  # still readable by a viewer
    w.close()


def test_leftover_plain_rotated_file_compressed_at_open(tmp_path):
    (tmp_path / "s_20260101T000000.jsonl").write_bytes(b"old\n")
    w = RotatingJsonlWriter(tmp_path, "s", grace_s=0)
    w.write(b"new\n")
    assert _wait(lambda: (tmp_path / "s_20260101T000000.jsonl.gz").exists())
    w.close()


def test_count_resumes_from_existing_live_file(tmp_path):
    (tmp_path / "s.jsonl").write_bytes(b"".join(_lines(2)))
    w = RotatingJsonlWriter(tmp_path, "s", rotate_records=3, grace_s=0)
    w.write(b"x\n")  # third record: rotates
    assert w.path.read_bytes() == b""
    w.close()


def test_retention_deletes_old_logs_not_ledger_or_other_stems(tmp_path):
    old = time.time() - 91 * 86400
    names = ["s_20250101T000000.jsonl.gz", "artifacts_s_20250101T000000.jsonl.gz",
             "s_2_20250101T000000.jsonl.gz"]
    for n in names:
        (tmp_path / n).write_bytes(b"")
        os.utime(tmp_path / n, (old, old))
    RotatingJsonlWriter(tmp_path, "s").write(b"x\n")
    RotatingJsonlWriter(tmp_path, "artifacts_s", retain_days=None).write(b"x\n")
    assert not (tmp_path / names[0]).exists()
    assert (tmp_path / names[1]).exists() and (tmp_path / names[2]).exists()


def test_rotation_retries_when_rename_is_refused(tmp_path, monkeypatch, capsys):
    real = os.rename
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError("in use")
        return real(src, dst)

    monkeypatch.setattr(log_jsonl.os, "rename", flaky)
    w = RotatingJsonlWriter(tmp_path, "s", rotate_records=2, grace_s=0)
    for line in _lines(2):
        w.write(line)  # rotation refused: keeps appending
    assert w.path.read_bytes() == b"".join(_lines(2))
    assert "rotation" in capsys.readouterr().err
    w._retry_at = 0  # make the retry due now
    w.write(b"z\n")
    assert w.path.read_bytes() == b""
    w.close()


def test_shared_writer_reopens_after_another_rotates(tmp_path):
    a = RotatingJsonlWriter(tmp_path, "s", rotate_records=2, grace_s=60, shared=True)
    b = RotatingJsonlWriter(tmp_path, "s", rotate_records=10, grace_s=60, shared=True)
    a.write(b"a1\n"); b.write(b"b1\n")   # a's count 1; live has 2 lines
    a.write(b"a2\n")                       # a rotates
    b.write(b"b2\n")                       # b must notice and reopen
    assert (tmp_path / "s.jsonl").read_bytes() == b"b2\n"
    rotated = next(tmp_path.glob("s_*.jsonl"))
    assert sorted(rotated.read_bytes().splitlines()) == [b"a1", b"a2", b"b1"]
    a.close(); b.close()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest helao/core/tests/test_log_jsonl.py -q`
Expected: FAIL with `ImportError: cannot import name 'RotatingJsonlWriter'`

- [ ] **Step 3: Write the implementation** (append to `log_jsonl.py`; merge the imports into the module's import block)

```python
import gzip
import os
import queue
import re
import shutil
import sys
import threading
import time
from pathlib import Path

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
```

Note `test_retention_deletes_old_logs_not_ledger_or_other_stems`: the stem `s` regex must not match `s_2_20250101T000000.jsonl.gz`. It does not, because the regex requires `_\d{8}T` right after the stem.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest helao/core/tests/test_log_jsonl.py -q`
Expected: PASS (14 passed)

- [ ] **Step 5: Mutation checks**

(a) Replace `self._stop.wait(self.grace_s)` with nothing: `test_plain_copy_kept_during_grace` must fail. (b) Remove the `elif self.shared and self._moved()` branch: `test_shared_writer_reopens_after_another_rotates` must fail. Restore both.

- [ ] **Step 6: Commit** (main session)

```bash
black helao/helpers/log_jsonl.py helao/core/tests/test_log_jsonl.py
git -C . add helao/helpers/log_jsonl.py helao/core/tests/test_log_jsonl.py
git -C . commit -m "feat(logging): record-count rotating JSONL writer with background gzip"
```

---

### Task 3: `SequenceDeduper`

**Files:**
- Modify: `helao/helpers/log_jsonl.py` (append)
- Test: `helao/core/tests/test_log_jsonl.py` (append)

**Interfaces:**
- Produces:
  - `SequenceDeduper(max_period=MAX_PERIOD, interval=10.0, clock=time.monotonic)`
  - `.feed(fp, item) -> list[tuple]`
  - `.flush() -> list[tuple]`
  - Each returned tuple is `("record", item)` or `("summary", period: int, count: int, last_item)`.

- [ ] **Step 1: Write the failing tests** (append)

```python
from helao.helpers.log_jsonl import SequenceDeduper


def _run(d, seq):
    out = []
    for x in seq:
        out += d.feed(x, x)
    return out


def test_single_repeat_collapses():
    d = SequenceDeduper(interval=10, clock=lambda: 0.0)
    out = _run(d, "AAAAB") + d.flush()
    assert out == [("record", "A"), ("record", "A"), ("summary", 1, 2, "A"), ("record", "B")]


def test_cycle_of_three_repeated_twenty_times():
    d = SequenceDeduper(interval=10, clock=lambda: 0.0)
    out = _run(d, "ABC" * 20 + "Z")
    records = [o[1] for o in out if o[0] == "record"]
    assert records == list("ABCABC") + ["Z"]
    assert ("summary", 3, 18, "C") in out


def test_broken_cycle_writes_summary_then_held_partial():
    d = SequenceDeduper(interval=10, clock=lambda: 0.0)
    out = _run(d, "ABCABCABCAB" + "Q")
    assert out[-4:] == [("summary", 3, 1, "C"), ("record", "A"), ("record", "B"), ("record", "Q")]


def test_flush_reports_pending_count_and_partial():
    d = SequenceDeduper(interval=10, clock=lambda: 0.0)
    _run(d, "ABABABA")
    assert d.flush() == [("summary", 2, 1, "B"), ("record", "A")]
    assert d.flush() == []


def test_interval_yields_periodic_summaries():
    now = [0.0]
    d = SequenceDeduper(interval=10, clock=lambda: now[0])
    _run(d, "AA")          # cycle confirmed at t=0
    out = []
    for t in range(1, 25):
        now[0] = float(t)
        out += d.feed("A", "A")
    summaries = [o for o in out if o[0] == "summary"]
    assert [s[2] for s in summaries] == [10, 10]


def test_interval_zero_disables():
    d = SequenceDeduper(interval=0)
    assert [o[1] for o in _run(d, "AAAA")] == list("AAAA")


def test_longest_period_bound():
    d = SequenceDeduper(max_period=2, interval=10, clock=lambda: 0.0)
    out = _run(d, "ABC" * 4)
    assert all(o[0] == "record" for o in out)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest helao/core/tests/test_log_jsonl.py -q -k "repeat or cycle or flush or interval or period"`
Expected: FAIL with `ImportError: cannot import name 'SequenceDeduper'`

- [ ] **Step 3: Write the implementation** (append; add `from collections import deque` to the imports)

```python
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

    def __init__(self, max_period: int = MAX_PERIOD, interval: float = 10.0, clock=time.monotonic):
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest helao/core/tests/test_log_jsonl.py -q`
Expected: PASS (21 passed). If `test_broken_cycle_writes_summary_then_held_partial` disagrees, trace it by hand. `ABCABC` is emitted and confirms the cycle. `ABC` then counts 1. `AB` is held. `Q` breaks the cycle and emits summary (3, 1, "C"), then A, then B, then Q. Fix the code, not the expectation.

- [ ] **Step 5: Mutation check**

Delete `out.extend(("record", h) for h in c["held"])`: `test_broken_cycle_writes_summary_then_held_partial` must fail. Restore it.

- [ ] **Step 6: Commit** (main session)

```bash
black helao/helpers/log_jsonl.py helao/core/tests/test_log_jsonl.py
git -C . add helao/helpers/log_jsonl.py helao/core/tests/test_log_jsonl.py
git -C . commit -m "feat(logging): repeated-sequence dedup"
```

---

### Task 4: `JsonlSinkHandler` and `make_logger` wiring

**Files:**
- Modify: `helao/helpers/log_jsonl.py` (append)
- Modify: `helao/helpers/helao_logging.py`: the module docstring, imports at lines 18-41, delete `GZipRotator` (lines 123-137) and `DedupTimedRotatingFileHandler` (lines 227-315), and in `make_logger` (lines 396-579) replace the file handler.
- Modify: `helao/core/tests/unit_test_logging.py` (sections at lines 155-172 and 344-446 use the removed classes)
- Delete: `helao/core/tests/test_gzip_rotator_fallback.py`
- Modify: `helao/hexagon/tests/test_behavior_hexagon.py:71-73` (`HEXBEH.log` becomes `HEXBEH.jsonl`)
- Test: `helao/core/tests/test_log_handler.py`

**Interfaces:**
- Consumes: Tasks 1-3.
- Produces:
  - `JsonlSinkHandler(stem: str, log_dir, *, endpoint: str | None = None, offset_seconds=0.0, dedup_interval=10.0, rotate_records=ROTATE_RECORDS, connect_timeout_ms=1000)`
  - attributes `.endpoint`, `.fallback_path: Path`, `.seq: int`
  - The ZMQ wire format consumed by Task 5: one frame `[record_bytes]`, or two frames `[LEDGER_FRAME, record_bytes]` for artefact records.

- [ ] **Step 1: Write the failing tests**

```python
"""JsonlSinkHandler: dedup, ZMQ send, fallback, replay, marker, ledger (spec §1)."""

import json
import logging
import os
import time
from pathlib import Path

import zmq

from helao.helpers.log_jsonl import LEDGER_FRAME, JsonlSinkHandler


def _logger(name, handler):
    lg = logging.getLogger(name)
    lg.handlers[:] = [handler]
    lg.setLevel(10)
    lg.propagate = False
    return lg


def _read(path):
    p = Path(path)
    return [json.loads(x) for x in p.read_bytes().splitlines()] if p.exists() else []


def _pull(port=None):
    s = zmq.Context.instance().socket(zmq.PULL)
    s.setsockopt(zmq.LINGER, 0)
    if port is None:
        port = s.bind_to_random_port("tcp://127.0.0.1")
    else:
        s.bind(f"tcp://127.0.0.1:{port}")
    return s, port


def _recv_all(sock, timeout=2.0):
    out, end = [], time.monotonic() + timeout
    while time.monotonic() < end:
        if sock.poll(50):
            out.append(sock.recv_multipart())
        elif out:
            break
    return out


def test_no_endpoint_writes_own_file(tmp_path):
    h = JsonlSinkHandler("SRV", tmp_path)
    lg = _logger("t_noep", h)
    lg.info("one"); lg.warning("two")
    h.close()
    rows = _read(tmp_path / "SRV.jsonl")
    assert [r["msg"] for r in rows] == ["one", "two"] and [r["seq"] for r in rows] == [1, 2]


def test_sends_to_launcher_when_connected(tmp_path):
    pull, port = _pull()
    h = JsonlSinkHandler("SRV", tmp_path, endpoint=f"tcp://127.0.0.1:{port}")
    lg = _logger("t_send", h)
    lg.info("hello")
    frames = _recv_all(pull)
    assert len(frames) == 1 and json.loads(frames[0][0])["msg"] == "hello"
    assert not (tmp_path / "SRV.jsonl").exists()
    h.close(); pull.close()


def test_artifact_records_use_ledger_frame_and_skip_dedup(tmp_path):
    pull, port = _pull()
    h = JsonlSinkHandler("SRV", tmp_path, endpoint=f"tcp://127.0.0.1:{port}")
    lg = _logger("t_ledger", h)
    for _ in range(3):
        lg.info("artifact_final act x", extra={"event": "artifact_final", "path": "x"})
    frames = _recv_all(pull)
    assert len(frames) == 3 and all(f[0] == LEDGER_FRAME for f in frames)
    h.close(); pull.close()


def test_dedup_applies_and_summary_fields(tmp_path):
    h = JsonlSinkHandler("SRV", tmp_path)
    lg = _logger("t_dedup", h)
    for _ in range(20):
        lg.error("A"); lg.error("B")
    lg.info("done")
    h.close()
    rows = _read(tmp_path / "SRV.jsonl")
    assert [r["msg"] for r in rows if "repeat_count" not in r] == ["A", "B", "A", "B", "done"]
    (s,) = [r for r in rows if "repeat_count" in r]
    assert (s["repeat_count"], s["repeat_period"]) == (18, 2)


def test_same_message_different_exceptions_not_collapsed(tmp_path):
    h = JsonlSinkHandler("SRV", tmp_path)
    lg = _logger("t_exc", h)
    for exc in (ValueError, KeyError, ValueError, KeyError):
        try:
            raise exc("x")
        except Exception:
            lg.exception("failed")
    h.close()
    rows = _read(tmp_path / "SRV.jsonl")
    assert [r["exc"].splitlines()[-1].split(":")[0] for r in rows[:2]] == ["ValueError", "KeyError"]


def test_launcher_loss_replays_then_falls_back_and_marks_on_reattach(tmp_path):
    pull, port = _pull()
    ep = f"tcp://127.0.0.1:{port}"
    h = JsonlSinkHandler("SRV", tmp_path, endpoint=ep, dedup_interval=0)
    lg = _logger("t_loss", h)
    for i in range(5):
        lg.info(f"m{i}")
    got = [json.loads(f[0])["seq"] for f in _recv_all(pull)]
    pull.close()                          # launcher dies
    end = time.monotonic() + 5
    while time.monotonic() < end and not (tmp_path / "SRV.jsonl").exists():
        lg.info("probe"); time.sleep(0.05)
    fb = _read(tmp_path / "SRV.jsonl")
    assert {r["seq"] for r in fb} >= set(range(1, 6))   # replayed (may duplicate)
    pull2, _ = _pull(port)                # a --reconnect launcher
    end, frames = time.monotonic() + 5, []
    while time.monotonic() < end and not frames:
        lg.info("back"); frames = _recv_all(pull2, 0.3)
    msgs = [json.loads(f[-1])["msg"] for f in frames]
    assert any(m.endswith(f"records went to {tmp_path / 'SRV.jsonl'}") for m in msgs)
    assert got == [1, 2, 3, 4, 5]
    h.close(); pull2.close()


def test_never_blocks_when_collector_stops_reading(tmp_path):
    pull, port = _pull()
    pull.setsockopt(zmq.RCVHWM, 10)
    h = JsonlSinkHandler("SRV", tmp_path, endpoint=f"tcp://127.0.0.1:{port}", dedup_interval=0)
    lg = _logger("t_block", h)
    t0 = time.monotonic()
    for i in range(10_000):
        lg.info(f"r{i}")
    assert time.monotonic() - t0 < 5.0
    assert len(_read(tmp_path / "SRV.jsonl")) > 0      # overflow spilled
    h.close(); pull.close()


def test_fork_resets_socket_and_writers(tmp_path):
    pull, port = _pull()
    h = JsonlSinkHandler("SRV", tmp_path, endpoint=f"tcp://127.0.0.1:{port}")
    old_sock = h._sock
    h._pid = -1                       # what a forked child observes
    lg = _logger("t_fork", h)
    lg.info("after fork")
    assert h._sock is not old_sock and h._pid == os.getpid()
    h.close(); pull.close()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest helao/core/tests/test_log_handler.py -q`
Expected: FAIL with `ImportError: cannot import name 'JsonlSinkHandler'`

- [ ] **Step 3: Implement the handler** (append to `log_jsonl.py`; add `import copy` and `import zmq` to the imports)

```python
def _summary_record(period: int, count: int, last: logging.LogRecord) -> logging.LogRecord:
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
    ):
        super().__init__()
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

    def _connect(self, timeout_ms: int):
        sock = zmq.Context.instance().socket(zmq.PUSH)
        sock.setsockopt(zmq.IMMEDIATE, 1)
        sock.setsockopt(zmq.SNDHWM, HWM)
        sock.setsockopt(zmq.LINGER, 500)
        mon = sock.get_monitor_socket(zmq.EVENT_CONNECTED)
        sock.connect(self.endpoint)
        # with IMMEDIATE, sends before the TCP handshake completes raise Again;
        # wait once (process start) so startup records reach the launcher
        if mon.poll(timeout_ms):
            mon.recv_multipart()
        sock.disable_monitor()
        mon.close()
        self._sock = sock

    def _after_fork(self):
        # never use the parent's socket or file handles in a forked child
        self._pid = os.getpid()
        self._sock = None
        self._log = self._ledger = None
        self._connected = False
        if self.endpoint:
            self._connect(200)

    def _writer(self, ledger: bool) -> RotatingJsonlWriter:
        if ledger:
            if self._ledger is None:
                self._ledger = RotatingJsonlWriter(
                    self.log_dir, f"artifacts_{self.stem}",
                    rotate_records=self.rotate_records, retain_days=None, shared=True,
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
            if is_artifact(record):
                self._out(record)
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
                self.seq += 1
                note = logging.LogRecord(
                    self.stem, logging.WARNING, __file__, 0,
                    f"{self._spilled} records went to {self.fallback_path}", None, None,
                )
                self._sock.send(record_to_json(note, self.seq, self.offset_seconds), zmq.NOBLOCK)
                self._spilled = 0
            self._sock.send_multipart([LEDGER_FRAME, data] if ledger else [data], zmq.NOBLOCK)
        except zmq.Again:
            if self._connected:
                self._connected = False
                self._replay()
            return False
        self._connected = True
        return True

    def _replay(self):
        # at-least-once: records still in socket buffers when the launcher died
        for data, ledger, sent in list(self.recent):
            if sent:
                self._spill(data, ledger, count=False)

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
```

- [ ] **Step 4: Run the handler tests**

Run: `python -m pytest helao/core/tests/test_log_handler.py -q`
Expected: PASS (8 passed). If `test_launcher_loss_replays...` times out because a closed PULL does not produce `Again` quickly, the loop already probes for up to 5 s. Do not lengthen it beyond that; report the timing to the main session instead.

- [ ] **Step 5: Wire it into `make_logger` and remove the old handler**

In `helao/helpers/helao_logging.py`:

- Imports: remove `gzip`, `shutil`, `subprocess`, and `TimedRotatingFileHandler` (keep `QueueHandler`, `QueueListener`, `SMTPHandler`). Remove `copy` if nothing else uses it (run `rg -n "copy\." helao/helpers/helao_logging.py`). Add:

```python
from helao.helpers.log_jsonl import LOG_ENDPOINT_ENV, JsonlSinkHandler, read_logs  # noqa: F401
```

  (`read_logs` arrives in Task 5. Until then, import only `LOG_ENDPOINT_ENV, JsonlSinkHandler`, and add `read_logs` in Task 5.)
- Delete `class GZipRotator` and `class DedupTimedRotatingFileHandler` in full.
- Update the module docstring: "a JSONL sink handler (launcher collector over ZMQ, else its own `<log_dir>/<name>.jsonl`, rotating every 300,000 records)" replaces the daily `TimedRotatingFileHandler` sentence.
- In `make_logger`, replace from `temp_dir = tempfile.mkdtemp()` through the end of the `handlers = [timed_rotation]` loop with:

```python
    if logger_name is not None and logger_name.endswith(".py"):
        logger_name = os.path.basename(logger_name).replace(".py", "")
    # a temp dir only when the caller gave none (spec §3: F3 keeps configured
    # roots off it); the old code made one on every call and leaked it
    log_dir = tempfile.mkdtemp() if log_dir is None else log_dir
    ntp_path = os.path.join(log_dir, "ntpLastSync.txt")
    # (keep the existing offset_seconds / formatter / colored_formatter lines
    # here exactly as they are; only the log_path line above them goes)
    logger_instance = logging.getLogger(logger_name)
    logger_instance.setLevel(min(10, log_level))

    console = logging.StreamHandler()
    console.setFormatter(colored_formatter)
    sink = JsonlSinkHandler(
        logger_name or "root",
        log_dir,
        endpoint=os.environ.get(LOG_ENDPOINT_ENV),
        offset_seconds=offset_seconds,
        dedup_interval=dedup_interval,
    )
    sink.setLevel(log_level)
    logger_instance.addHandler(sink)
```

  Keep the console block and the email and webhook blocks unchanged. Replace the final `logger_instance.info(f"writing log events to {log_path}")` with:

```python
    target = sink.endpoint or sink.fallback_path
    logger_instance.info(f"writing log events to {target}")
```

  Update the `dedup_interval` docstring: "Seconds a repeated message sequence (period 1-16) is collapsed before a summary record is written; `0` disables". Update `DEFAULT_DEDUP_INTERVAL`'s comment the same way. Remove the `Path`/`log_path` local if unused.

- [ ] **Step 6: Update the dependent tests**

- `helao/core/tests/unit_test_logging.py`: remove `DedupTimedRotatingFileHandler` and `GZipRotator` from the import list (lines 31-32). Delete the "GZipRotator rename behaviour" section (from `reporter.section("GZipRotator rename behaviour")` to just before the next `reporter.section`). Delete the "DedupTimedRotatingFileHandler collapses repeats" section and its sub-sections, to the end of those checks. Dedup and rotation are now covered by `test_log_jsonl.py` and `test_log_handler.py`. In the "make_logger configures a working logger" section, replace any assertion on a `.log` file with:

```python
        reporter.check(
            "make_logger writes <name>.jsonl",
            (Path(tmp) / "unit_test_logging.jsonl").exists(),
        )
```

  Use the logger name and temp dir variable names that section already uses (read lines 60-150 first).
- Delete `helao/core/tests/test_gzip_rotator_fallback.py` with `git -C . rm --cached` at commit time; the main session stages the deletion.
- `helao/hexagon/tests/test_behavior_hexagon.py:71-73`: change `"HEXBEH.log"` to `"HEXBEH.jsonl"` in both places.

- [ ] **Step 7: Run the affected tests**

Run each in turn:
`python -m pytest helao/core/tests/test_log_handler.py helao/core/tests/test_log_jsonl.py -q`
`python helao/core/tests/unit_test_logging.py`
`python -m pytest helao/hexagon/tests/test_behavior_hexagon.py -q`
`python -m pytest helao/core/tests/test_alert.py -q`
Expected: all PASS. `unit_test_logging.py` is a standalone script; it prints a PASS/FAIL report and exits 0 on pass.

- [ ] **Step 8: Mutation checks**

(a) In `_send`, replace `self._replay()` with `pass`: `test_launcher_loss_replays...` must fail. (b) Change `is_artifact(record)` in `emit` to `False`: `test_artifact_records_use_ledger_frame_and_skip_dedup` must fail. Restore both.

- [ ] **Step 9: Commit** (main session)

```bash
black helao/helpers/log_jsonl.py helao/helpers/helao_logging.py helao/core/tests/test_log_handler.py helao/core/tests/unit_test_logging.py helao/hexagon/tests/test_behavior_hexagon.py
git -C . rm --cached helao/core/tests/test_gzip_rotator_fallback.py && rm helao/core/tests/test_gzip_rotator_fallback.py
git -C . add helao/helpers/log_jsonl.py helao/helpers/helao_logging.py helao/core/tests/test_log_handler.py helao/core/tests/unit_test_logging.py helao/hexagon/tests/test_behavior_hexagon.py
git -C . commit -m "feat(logging)!: JSONL sink handler replaces the daily text file handler"
```

---

### Task 5: `LogCollector`, `resolve_log_port`, `read_logs`

**Files:**
- Create: `helao/helpers/log_collector.py`
- Modify: `helao/helpers/log_jsonl.py` (append `read_logs`), `helao/helpers/helao_logging.py` (re-export `read_logs`)
- Test: `helao/core/tests/test_log_collector.py`

**Interfaces:**
- Consumes: `RotatingJsonlWriter`, `LEDGER_FRAME`, `HWM`, `JsonlSinkHandler`.
- Produces:
  - `LogCollector(endpoint: str, log_dir, prefix: str, *, rotate_records=ROTATE_RECORDS)`, with `.start()` (raises `zmq.ZMQError` when the port is taken) and `.stop(drain_s: float = 2.0)`
  - `resolve_log_port(config: dict) -> int` (raises `ValueError`)
  - `log_endpoint(port: int) -> str`
  - `read_logs(log_dir, server: str | None = None, *, ledger: bool = False) -> pandas.DataFrame`

- [ ] **Step 1: Write the failing tests**

```python
"""LogCollector, log_port resolution, read_logs (spec §2, §3)."""

import json
import logging
import time

import pytest
import zmq

from helao.helpers.log_collector import LogCollector, log_endpoint, resolve_log_port
from helao.helpers.log_jsonl import JsonlSinkHandler, read_logs


def _free_port():
    s = zmq.Context.instance().socket(zmq.PULL)
    port = s.bind_to_random_port("tcp://127.0.0.1")
    s.close(linger=0)
    return port


def _logger(name, h):
    lg = logging.getLogger(name)
    lg.handlers[:] = [h]; lg.setLevel(10); lg.propagate = False
    return lg


def test_resolve_log_port_default_skips_reflex_backend():
    cfg = {"servers": {"A": {"host": "127.0.0.1", "port": 8001},
                       "UI": {"host": "127.0.0.1", "port": 8005, "reflex": "app"}}}
    assert resolve_log_port(cfg) == 8007


def test_resolve_log_port_explicit_and_collision():
    cfg = {"log_port": 9000, "servers": {"A": {"host": "h", "port": 8001}}}
    assert resolve_log_port(cfg) == 9000
    with pytest.raises(ValueError):
        resolve_log_port({"log_port": 8001, "servers": {"A": {"host": "h", "port": 8001}}})


def test_collector_writes_unified_file_and_ledger(tmp_path):
    ep = log_endpoint(_free_port())
    col = LogCollector(ep, tmp_path, "grp")
    col.start()
    h1 = JsonlSinkHandler("A", tmp_path, endpoint=ep)
    h2 = JsonlSinkHandler("B", tmp_path, endpoint=ep)
    _logger("tc_a", h1).info("from A")
    _logger("tc_b", h2).info("hash", extra={"event": "artifact_final", "sha256": "ff"})
    time.sleep(0.5)
    h1.close(); h2.close(); col.stop()
    unified = [json.loads(x) for x in (tmp_path / "helao_grp.jsonl").read_bytes().splitlines()]
    assert {r["server"] for r in unified} >= {"A", "B"}
    ledger = [json.loads(x) for x in (tmp_path / "artifacts_grp.jsonl").read_bytes().splitlines()]
    assert [r["sha256"] for r in ledger] == ["ff"]
    assert not (tmp_path / "A.jsonl").exists()


def test_second_bind_fails(tmp_path):
    ep = log_endpoint(_free_port())
    a = LogCollector(ep, tmp_path, "g"); a.start()
    with pytest.raises(zmq.ZMQError):
        LogCollector(ep, tmp_path / "b", "g").start()
    a.stop()


def test_read_logs_merges_dedups_sorts(tmp_path):
    import gzip
    recs = [{"ts": f"2026-10-26T00:00:0{i}.000000Z", "level": "INFO", "server": "A",
             "pid": 1, "seq": i, "msg": str(i)} for i in range(4)]
    line = lambda r: (json.dumps(r) + "\n").encode()
    (tmp_path / "helao_g.jsonl").write_bytes(line(recs[3]) + line(recs[1]))
    with gzip.open(tmp_path / "helao_g_20261026T000000.jsonl.gz", "wb") as f:
        f.write(line(recs[0]) + line(recs[1]))
    (tmp_path / "A.jsonl").write_bytes(line(recs[2]))
    (tmp_path / "artifacts_g.jsonl").write_bytes(line({**recs[0], "seq": 99}))
    df = read_logs(tmp_path)
    assert list(df["seq"]) == [0, 1, 2, 3]
    assert list(read_logs(tmp_path, ledger=True)["seq"]) == [99]
    assert read_logs(tmp_path, server="nobody").empty
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest helao/core/tests/test_log_collector.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'helao.helpers.log_collector'`

- [ ] **Step 3: Implement `log_collector.py`**

```python
"""Launcher-side log collector: one PULL socket, one unified JSONL file (spec §2)."""

import sys
import threading
import time

import zmq

from helao.helpers.log_jsonl import HWM, LEDGER_FRAME, ROTATE_RECORDS, RotatingJsonlWriter

__all__ = ["LogCollector", "log_endpoint", "resolve_log_port"]


def log_endpoint(port: int) -> str:
    return f"tcp://127.0.0.1:{port}"


def resolve_log_port(config: dict) -> int:
    """``log_port`` from the config, else one above every port a server occupies."""
    from helao.ui.shared.discovery import reserved_addresses

    taken = {
        int(addr.rsplit(":", 1)[1])
        for entry in (config.get("servers") or {}).values()
        if isinstance(entry, dict)
        for addr in reserved_addresses(entry)
    }
    port = config.get("log_port")
    if port is None:
        return max(taken, default=8000) + 1
    if not isinstance(port, int) or isinstance(port, bool) or port in taken:
        raise ValueError(
            f"log_port {port!r} must be an int that no server occupies "
            f"(taken: {sorted(taken)})"
        )
    return port


class LogCollector:
    """Daemon thread that appends every child's records to one file.

    Never raises into another thread; a disk error is reported to stderr and
    the record dropped. Children whose sends fail spill to their own files.
    """

    def __init__(self, endpoint: str, log_dir, prefix: str, *, rotate_records: int = ROTATE_RECORDS):
        self.endpoint = endpoint
        self._log = RotatingJsonlWriter(log_dir, f"helao_{prefix}", rotate_records=rotate_records)
        self._ledger = RotatingJsonlWriter(
            log_dir, f"artifacts_{prefix}", rotate_records=rotate_records, retain_days=None
        )
        self._stop = threading.Event()
        self._drain_s = 2.0
        self._sock = None
        self._thread = None

    def start(self) -> None:
        sock = zmq.Context.instance().socket(zmq.PULL)
        sock.setsockopt(zmq.RCVHWM, HWM)
        sock.setsockopt(zmq.LINGER, 0)
        try:
            sock.bind(self.endpoint)
        except zmq.ZMQError:
            sock.close()
            raise
        self._sock = sock
        self._thread = threading.Thread(target=self._run, name="log_collector", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        poller = zmq.Poller()
        poller.register(self._sock, zmq.POLLIN)
        while not self._stop.is_set():
            if poller.poll(500):
                self._drain()
        deadline = time.monotonic() + self._drain_s
        while time.monotonic() < deadline and poller.poll(100):
            self._drain()
        self._sock.close()
        self._log.close()
        self._ledger.close()

    def _drain(self) -> None:
        while True:
            try:
                frames = self._sock.recv_multipart(zmq.NOBLOCK)
            except zmq.Again:
                return
            try:
                self._log.write(frames[-1])
                if len(frames) == 2 and frames[0] == LEDGER_FRAME:
                    self._ledger.write(frames[1])
            except OSError as exc:
                sys.stderr.write(f"log collector write failed: {exc}\n")

    def stop(self, drain_s: float = 2.0) -> None:
        """Drain for up to ``drain_s`` seconds, close files, finish gzips."""
        if self._thread is None:
            return
        self._drain_s = drain_s
        self._stop.set()
        self._thread.join(timeout=drain_s + 65)
        self._thread = None
```

- [ ] **Step 4: Implement `read_logs`** (append to `log_jsonl.py`)

```python
def read_logs(log_dir, server=None, *, ledger: bool = False):
    """All JSONL records under ``log_dir`` as one DataFrame sorted by ``ts``.

    Reads live and rotated (``.gz``) files; ``ledger=True`` reads only the
    ``artifacts_*`` ledger instead of the logs. Duplicates from replay are
    dropped on ``(server, pid, seq)``.
    """
    import pandas as pd

    frames = []
    for p in sorted(Path(log_dir).iterdir()):
        if not p.name.endswith((".jsonl", ".jsonl.gz")):
            continue
        if p.name.startswith("artifacts_") != ledger or not p.stat().st_size:
            continue
        try:
            frames.append(pd.read_json(p, lines=True, compression="infer", dtype=False))
        except (EOFError, OSError, ValueError):
            continue  # a .gz still being written; its plain copy is read instead
    if not frames:
        return pd.DataFrame(columns=["ts", "level", "server", "pid", "seq", "msg"])
    df = pd.concat(frames, ignore_index=True).drop_duplicates(["server", "pid", "seq"])
    if server is not None:
        df = df[df["server"] == server]
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.sort_values(["ts", "pid", "seq"], kind="stable").reset_index(drop=True)
```

  Then add `read_logs` to the `helao_logging` import line from Task 4.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest helao/core/tests/test_log_collector.py -q`
Expected: PASS (5 passed)

- [ ] **Step 6: Mutation check**

Remove the ledger `write` in `_drain`: `test_collector_writes_unified_file_and_ledger` must fail. Restore it.

- [ ] **Step 7: Commit** (main session)

```bash
black helao/helpers/log_collector.py helao/helpers/log_jsonl.py helao/helpers/helao_logging.py helao/core/tests/test_log_collector.py
git -C . add helao/helpers/log_collector.py helao/helpers/log_jsonl.py helao/helpers/helao_logging.py helao/core/tests/test_log_collector.py
git -C . commit -m "feat(logging): launcher log collector, log_port, read_logs"
```

---

### Task 6: Launcher integration, stale-log cleanup, readers, docs

**Files:**
- Modify: `launch.py`. Imports; `main()` around lines 2105-2160 (`LAUNCH_LOGGER` creation and the `.txt` zip loop); `teardown_group` (line 2339, after `pidd.close()` at ~2364); the CTRL-d branch (~2798-2820); the `ConsoleMux.register` error text at line 281.
- Modify: `helao/helpers/helao_dirs.py:95-125` (delete the zip loop; drop the `zipfile`/`re`/`glob` imports if they become unused)
- Modify: `helao/hexagon/ports/logging.py`, `helao/hexagon/adapters/shared/logging_adapter.py`, `helao/hexagon/app/orch_effects.py:55-63` (docstrings: `.log` becomes `.jsonl`)
- Modify: root `CLAUDE.md` ("Data and state on disk" LOGS bullet; the `launch.py` "zips old `*.txt` logs" sentence); `docs/config-schema.md` (add `log_port`)
- Modify: the golden-capture stubs and harness tests that write `LOGS/<KEY>.log` (find them with the command in Step 4)
- Test: `helao/core/tests/test_launch_logging.py`

**Interfaces:**
- Consumes: `LogCollector`, `resolve_log_port`, `log_endpoint`, `LOG_ENDPOINT_ENV`.
- Produces: children inherit `HELAO_LOG_ENDPOINT` through `os.environ` (as they do `PARENT_PID_ENV`), so `ConsoleMux.child_env` needs no change: when active it copies `os.environ`, and when inactive the child inherits it.

- [ ] **Step 1: Write the failing test** (checks the helper the launcher uses, not a live launch)

```python
"""launch.py starts the collector before anything logs (spec §2)."""

import ast
from pathlib import Path


def _main_src():
    tree = ast.parse(Path("launch.py").read_text(encoding="utf-8"))
    (main,) = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"]
    return ast.get_source_segment(Path("launch.py").read_text(encoding="utf-8"), main)


def test_collector_started_and_env_set_before_launch_logger():
    src = _main_src()
    i_start = src.index("collector.start()")
    i_env = src.index("os.environ[LOG_ENDPOINT_ENV]")
    i_logger = src.index("LAUNCH_LOGGER = logging.make_logger(")
    assert i_start < i_env < i_logger


def test_collector_stopped_in_teardown_and_detach():
    src = _main_src()
    teardown = src[src.index("def teardown_group"):src.index("def restart_server")]
    assert "collector.stop()" in teardown
    detach = src[src.index("Disconnecting action monitor"):]
    assert "collector.stop()" in detach


def test_stale_txt_zip_blocks_removed():
    assert "Compressing:" not in Path("launch.py").read_text(encoding="utf-8")
    assert "Compressing:" not in Path("helao/helpers/helao_dirs.py").read_text(encoding="utf-8")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest helao/core/tests/test_launch_logging.py -q`
Expected: FAIL with `ValueError: substring not found`

- [ ] **Step 3: Implement in `launch.py`**

Read `helao/helpers/CLAUDE.md` first. Add to the imports:

```python
import zmq

from helao.helpers.log_collector import LogCollector, log_endpoint, resolve_log_port
from helao.helpers.log_jsonl import LOG_ENDPOINT_ENV
```

Immediately before `global LAUNCH_LOGGER` / `LAUNCH_LOGGER = logging.make_logger(` in `main()`, insert:

```python
    # One collector for the whole group, bound before anything logs so the
    # launcher's own logger and every child (which inherits the env var, like
    # PARENT_PID_ENV below) connect to it. Fixed by the config, so a
    # --reconnect launcher re-binds the same port and detached children
    # re-attach on their own.
    try:
        log_port = resolve_log_port(config)
    except ValueError as exc:
        cprint(f"\n{exc}\n", "red", attrs=["bold"])
        sys.exit(1)
    log_prefix = os.path.splitext(os.path.basename(confArg))[0]
    collector = LogCollector(log_endpoint(log_port), helaodirs.log_root, log_prefix)
    try:
        collector.start()
    except zmq.ZMQError as exc:
        cprint(
            f"\nlog_port {log_port} is in use ({exc}). Is another launcher for "
            f"this group running? Set log_port in the config if it is taken by "
            f"something else.\n",
            "red",
            attrs=["bold"],
        )
        sys.exit(1)
    os.environ[LOG_ENDPOINT_ENV] = log_endpoint(log_port)
```

If `helaodirs.log_root` can be `None` at this point (config without `root`), guard the collector with `if helaodirs.log_root is not None:`. The existing check further down exits with a clear message for that case. Read the code between line 2090 and 2113 to confirm where `helaodirs` is assigned.

Delete the `# compress old logs:` block: from `log_root = os.path.join(config["root"], "LOGS")` through the end of its `for server_name in [...]` loop. Remove the `zipfile` and `re` imports only if `rg -n "zipfile\.|re\." launch.py` shows no other use.

In `teardown_group`, after `pidd.close()` and inside the `with pidd_lock:` block, add:

```python
            # last: the shutdown sweep's records are in by now
            collector.stop()
```

In the CTRL-d branch, after the final `LAUNCH_LOGGER.info(f"Disconnecting action monitor. ...")`, add:

```python
            # children spill to their own files until a --reconnect launcher
            # binds the endpoint again
            collector.stop()
```

At line 281 change `(LOGS/{server_key}.log is unaffected)` to `(its records still reach LOGS/ through the log collector)`.

- [ ] **Step 4: `helao_dirs.py`, docstrings, readers, docs**

- `helao/helpers/helao_dirs.py`: delete the `if server_name is not None:` zip block (lines 95-125). Keep any other statement inside it; read the whole block first.
- Docstrings: `helao/hexagon/ports/logging.py` and `helao/hexagon/adapters/shared/logging_adapter.py`: "Contractual path: `<log_root>/<server_key>.jsonl` (the fallback file; under the launcher, records go to `<root>/LOGS/helao_<prefix>.jsonl`)". `orch_effects.py:61`: `<root>/LOGS/<server_key>.log` becomes `the server's JSONL log`.
- Readers: run
  `rg -n "LOGS.*\.log\b|_key\}\.log|\"[A-Z_]+\.log\"" --type py helao harness -g '!helao/deploy/*/' ; rg -n "\.log\b" helao/deploy/hte helao/deploy/test --type py`.
  Change each test stub that writes `LOGS/<KEY>.log` to `.jsonl` (`harness/tests/test_capture.py:50` and the `test_golden_capture_*.py` stubs). Run each changed test file.
- Root `CLAUDE.md`, "Data and state on disk": replace the `LOGS/<server_name>/` bullet with: "`LOGS/` — JSONL logs. Under `launch.py` every process sends records to the launcher's collector, which writes `helao_<prefix>.jsonl`; without a launcher each process writes `<server_key>.jsonl`. Files rotate every 300,000 records (gzipped in the background); rotated logs are deleted after 90 days; `artifacts_*.jsonl` (artefact SHA-256 ledger) is never deleted. Read with `helao_logging.read_logs`. Spec: `docs/superpowers/specs/2026-10-26-jsonl-unified-logging-design.md`." Also remove "launch.py zips old `*.txt` logs at startup using a timestamp parsed from the first log line".
- `docs/config-schema.md`: add a top-level `log_port` row: "optional int; the launcher's log collector port on 127.0.0.1; default one above the highest port any server occupies".

- [ ] **Step 5: Run the tests**

Run: `python -m pytest helao/core/tests/test_launch_logging.py -q`, then every test file changed in Step 4, one file per process.
Expected: PASS.

- [ ] **Step 6: Live smoke of the collector** (main session or implementer; run in the background with a marker file, per the background-sweep rule)

```bash
D=$CLAUDE_JOB_DIR/tmp/logsmoke; mkdir -p $D
( timeout 120 ./helao.sh goldenreflex > $D/launch.out 2>&1 < /dev/null; echo $? > $D/done ) &
# after ~60 s, in a second shell:
python -c "from helao.helpers.helao_logging import read_logs; df=read_logs('/tmp/helao-reflex/LOGS'); print(sorted(df.server.unique()))"
```

Expected: every server key of `goldenreflex` plus `launch` is listed, from `helao_goldenreflex.jsonl`. Report the list.

- [ ] **Step 7: Commit** (main session)

```bash
black launch.py helao/helpers/helao_dirs.py helao/hexagon/ports/logging.py helao/hexagon/adapters/shared/logging_adapter.py helao/hexagon/app/orch_effects.py helao/core/tests/test_launch_logging.py <changed test stubs>
git -C . add -u && git -C . add helao/core/tests/test_launch_logging.py
git -C . commit -m "feat(launch): unified group log via the log collector; drop stale txt zipping"
```

---

### Task 7: Artefact hash records

**Files:**
- Create: `helao/helpers/artifact_hash.py`
- Test: `helao/core/tests/test_artifact_hash.py`

**Interfaces:**
- Consumes: the handler's ledger tee (Task 4) and the collector's ledger tee (Task 5).
- Produces:
  - `async log_artifact_hashes(paths, *, kind: str, owner_uuid, event: str = "artifact_final", reason: str | None = None, root: str | None = None, logger=None) -> None`
  - `log_artifact_hashes_sync(...)` with the same signature
  - `record_uuid(doc: dict) -> str | None`
  - kinds are `act|exp|seq|prc|ana|data|output|zip`

- [ ] **Step 1: Write the failing tests**

```python
"""Artefact SHA-256 records (spec §5)."""

import asyncio
import hashlib
import json
import logging
import os

from helao.helpers.artifact_hash import log_artifact_hashes, log_artifact_hashes_sync, record_uuid
from helao.helpers.log_jsonl import JsonlSinkHandler


def _setup(tmp_path):
    h = JsonlSinkHandler("SRV", tmp_path / "LOGS")
    lg = logging.getLogger("t_art")
    lg.handlers[:] = [h]; lg.setLevel(10); lg.propagate = False
    return h, lg


def _rows(p):
    return [json.loads(x) for x in p.read_bytes().splitlines()] if p.exists() else []


def test_hashes_logged_to_log_and_ledger(tmp_path):
    h, lg = _setup(tmp_path)
    f = tmp_path / "RUNS" / "a.jsonl"
    f.parent.mkdir()
    f.write_bytes(b"x" * 1000)
    asyncio.run(log_artifact_hashes([f], kind="data", owner_uuid="u1", root=str(tmp_path), logger=lg))
    h.close()
    want = hashlib.sha256(b"x" * 1000).hexdigest()
    for p in (tmp_path / "LOGS" / "SRV.jsonl", tmp_path / "LOGS" / "artifacts_SRV.jsonl"):
        (r,) = [r for r in _rows(p) if r.get("event") == "artifact_final"]
        assert (r["sha256"], r["bytes"], r["kind"], r["uuid"]) == (want, 1000, "data", "u1")
        assert r["path"] == os.path.join("RUNS", "a.jsonl")


def test_rewrite_event_and_reason(tmp_path):
    h, lg = _setup(tmp_path)
    f = tmp_path / "r-act.json"; f.write_text("{}")
    log_artifact_hashes_sync([f], kind="act", owner_uuid="u", event="artifact_rewritten",
                             reason="set_plate_id", root=str(tmp_path), logger=lg)
    h.close()
    (r,) = _rows(tmp_path / "LOGS" / "artifacts_SRV.jsonl")
    assert (r["event"], r["reason"]) == ("artifact_rewritten", "set_plate_id")


def test_missing_file_warns_never_raises(tmp_path):
    h, lg = _setup(tmp_path)
    log_artifact_hashes_sync([tmp_path / "gone"], kind="data", owner_uuid="u", logger=lg)
    h.close()
    (r,) = _rows(tmp_path / "LOGS" / "SRV.jsonl")
    assert r["event"] == "artifact_hash_failed" and r["level"] == "WARNING"


def test_path_outside_root_is_absolute(tmp_path):
    h, lg = _setup(tmp_path)
    f = tmp_path / "x"; f.write_text("1")
    log_artifact_hashes_sync([f], kind="output", owner_uuid="u", root=str(tmp_path / "other"), logger=lg)
    h.close()
    assert _rows(tmp_path / "LOGS" / "SRV.jsonl")[0]["path"] == str(f.resolve())


def test_record_uuid():
    assert record_uuid({"action_uuid": "a"}) == "a"
    assert record_uuid({"process_uuid": "p"}) == "p"
    assert record_uuid({}) is None
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest helao/core/tests/test_artifact_hash.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
"""SHA-256 log records for finalized and rewritten output artefacts (spec §5).

Each file gets one INFO record with ``event``/``kind``/``uuid``/``path``/
``bytes``/``sha256`` (and ``reason`` on a rewrite). ``JsonlSinkHandler`` and
the launcher's collector also write those records to the never-deleted
``artifacts_*`` ledger. Never raises: an unreadable file logs
``artifact_hash_failed`` at WARNING.
"""

import asyncio
import hashlib
import os
from typing import Optional

from helao.helpers import helao_logging

__all__ = ["log_artifact_hashes", "log_artifact_hashes_sync", "record_uuid"]

_UUID_KEYS = (
    "action_uuid",
    "experiment_uuid",
    "sequence_uuid",
    "process_uuid",
    "analysis_uuid",
)
_FALLBACK = None


def record_uuid(doc: dict) -> Optional[str]:
    """The owning uuid of a record dict (action/experiment/sequence/process/analysis)."""
    for key in _UUID_KEYS:
        if doc.get(key):
            return str(doc[key])
    return None


def _logger(logger):
    global _FALLBACK
    if logger is not None:
        return logger
    if helao_logging.LOGGER is not None:
        return helao_logging.LOGGER
    if _FALLBACK is None:
        _FALLBACK = helao_logging.make_logger("artifact_hash")
        _FALLBACK.warning("no config root: artefact ledger entries go to a temporary directory")
    return _FALLBACK


def _root(root):
    if root is not None:
        return root
    from helao.helpers import config_loader

    cfg = config_loader.CONFIG
    return cfg.get("root") if isinstance(cfg, dict) else None


def _rel(path: str, root) -> str:
    absolute = os.path.abspath(path)
    if root:
        base = os.path.abspath(root)
        try:
            if os.path.commonpath([absolute, base]) == base:
                return os.path.relpath(absolute, base)
        except ValueError:
            pass  # different drives on Windows
    return absolute


def log_artifact_hashes_sync(
    paths,
    *,
    kind: str,
    owner_uuid,
    event: str = "artifact_final",
    reason: Optional[str] = None,
    root: Optional[str] = None,
    logger=None,
) -> None:
    """Hash each file and log one record per file; for non-async callers."""
    log = _logger(logger)
    root = _root(root)
    for path in paths:
        path = os.fspath(path)
        rel = _rel(path, root)
        common = {"kind": kind, "uuid": str(owner_uuid), "path": rel}
        try:
            with open(path, "rb") as f:
                digest = hashlib.file_digest(f, "sha256").hexdigest()
            size = os.path.getsize(path)
        except OSError as exc:
            log.warning(
                f"artifact_hash_failed {kind} {rel}: {exc}",
                extra={**common, "event": "artifact_hash_failed", "reason": str(exc)},
            )
            continue
        log.info(
            f"{event} {kind} {rel} sha256={digest}",
            extra={**common, "event": event, "bytes": size, "sha256": digest, "reason": reason},
        )


async def log_artifact_hashes(paths, **kwargs) -> None:
    """``log_artifact_hashes_sync`` on a worker thread; awaited by the caller."""
    await asyncio.to_thread(log_artifact_hashes_sync, list(paths), **kwargs)
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest helao/core/tests/test_artifact_hash.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit** (main session)

```bash
black helao/helpers/artifact_hash.py helao/core/tests/test_artifact_hash.py
git -C . add helao/helpers/artifact_hash.py helao/core/tests/test_artifact_hash.py
git -C . commit -m "feat(logging): artefact SHA-256 records and ledger tee"
```

---

### Task 8: Finalization call sites

**Files:**
- Modify: `helao/hexagon/adapters/native/meta_writer.py` (`write_act` line 76, `write_exp` 106, `write_seq` 128)
- Modify: `helao/hexagon/app/action_host.py:477-485` (`write_act(self, action, reason=None)`)
- Modify: `helao/hexagon/ports/artifact_store.py:48` and `helao/hexagon/adapters/native/artifact_store.py:90` (add `reason: Optional[str] = None` to `write_act` and pass it through)
- Modify: `helao/hexagon/adapters/native/sync_driver.py:~2592` (the `-prc.json` `write_meta` in `sync_process`, which is async)
- Modify: `helao/core/drivers/data/analysis_layout.py` (add `local_output_path`, use it in `publish_outputs`) and `helao/core/drivers/data/analysis_driver.py:~1232-1245`
- Test: `helao/core/tests/test_artifact_hash_sites.py`

**Interfaces:**
- Consumes: `log_artifact_hashes`.
- Produces:
  - `MetaWriter.write_act(action, reason: str | None = None)`, `MetaWriter.write_exp(experiment, reason=None)`, `MetaWriter.write_seq(sequence, reason=None)`
  - `local_output_path(output: dict, local_ana_dir: str) -> str`
  - `TERMINAL_STATUSES: frozenset[HloStatus]`, in `meta_writer.py`

- [ ] **Step 1: Verify the field names before writing code**

Run: `rg -n "action_status|experiment_status|sequence_status" helao/core/models/action.py helao/core/models/experiment.py helao/core/models/sequence.py | head` and `rg -n "^class HloStatus" -A 30 helao/core/models/hlostatus.py`.
Confirm `action.action_status`, `experiment.experiment_status` and `sequence.sequence_status` are `list[HloStatus]`, and that `HloStatus` has `finished, errored, aborted, skipped, estopped, retired`. If any differ, stop and report.

- [ ] **Step 2: Write the failing tests**

```python
"""Artefact hashes at the finalization points (spec §5)."""

import asyncio
import hashlib
import json
import logging
from types import SimpleNamespace

import pytest

from helao.core.models.hlostatus import HloStatus
from helao.helpers import helao_logging
from helao.helpers.log_jsonl import JsonlSinkHandler


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    h = JsonlSinkHandler("SRV", tmp_path / "LOGS")
    lg = logging.getLogger("t_sites")
    lg.handlers[:] = [h]; lg.setLevel(10); lg.propagate = False
    monkeypatch.setattr(helao_logging, "LOGGER", lg)

    def rows():
        h.flush()
        p = tmp_path / "LOGS" / "artifacts_SRV.jsonl"
        return [json.loads(x) for x in p.read_bytes().splitlines()] if p.exists() else []

    yield rows
    h.close()


def _writer(tmp_path):
    from helao.hexagon.adapters.native.meta_writer import MetaWriter

    async def atomic(path, text):
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    base = SimpleNamespace(helaodirs=SimpleNamespace(save_root=tmp_path / "RUNS"), _write_meta_atomic=atomic)
    return MetaWriter(base)
```

> Read `MetaWriter.__init__` (`meta_writer.py:40-75`) first and build `base` with exactly the attributes `write_act` touches. The `SimpleNamespace` above is the expected shape; if `__init__` needs more, add those attributes rather than changing `MetaWriter`.

```python
def _action(tmp_path, status, files):
    from helao.helpers.premodels import Action

    a = Action(action_name="CA", action_server={"server_name": "PSTAT", "machine_name": "m"})
    a.action_status = status
    a.action_output_dir = "seqdir/expdir/actdir"
    a.files = files
    return a


def test_finished_action_hashes_record_and_files(tmp_path, ledger):
    from helao.core.models.file import FileInfo

    d = tmp_path / "RUNS" / "seqdir/expdir/actdir"
    d.mkdir(parents=True)
    (d / "CA-0__0.jsonl").write_bytes(b"1\n2\n")
    (d / "CA-0__0.meta.json").write_bytes(b"{}")
    a = _action(tmp_path, [HloStatus.finished], [FileInfo(file_name="CA-0__0.jsonl")])
    asyncio.run(_writer(tmp_path).write_act(a))
    rows = ledger()
    assert sorted(r["kind"] for r in rows) == ["act", "data", "data"]
    (data,) = [r for r in rows if r["path"].endswith("CA-0__0.jsonl")]
    assert data["sha256"] == hashlib.sha256(b"1\n2\n").hexdigest()
    assert any(r["path"].endswith("CA-0__0.meta.json") for r in rows)
    assert all(r["event"] == "artifact_final" for r in rows)


def test_active_action_write_is_not_hashed(tmp_path, ledger):
    (tmp_path / "RUNS" / "seqdir/expdir/actdir").mkdir(parents=True)
    asyncio.run(_writer(tmp_path).write_act(_action(tmp_path, [HloStatus.active], [])))
    assert ledger() == []


def test_reason_logs_rewritten(tmp_path, ledger):
    (tmp_path / "RUNS" / "seqdir/expdir/actdir").mkdir(parents=True)
    a = _action(tmp_path, [HloStatus.errored], [])
    asyncio.run(_writer(tmp_path).write_act(a, reason="reconcile_interrupted"))
    (r,) = ledger()
    assert (r["event"], r["reason"]) == ("artifact_rewritten", "reconcile_interrupted")


def test_local_output_path(tmp_path):
    import os

    from helao.core.drivers.data.analysis_layout import local_output_path

    out = {"analysis_output_path": {"key": "analysis/abc/out_1.json"}}
    assert local_output_path(out, str(tmp_path)) == os.path.join(str(tmp_path), "out_1.json")
```

> `_action` guesses the `Action` constructor. Read `helao/helpers/premodels.py` (`class Action`) and the `Action` fixtures in `helao/hexagon/tests/test_native_meta_writer.py`, and build a minimal valid `Action` the same way. Keep the test's assertions unchanged.

- [ ] **Step 3: Run them to verify they fail**

Run: `python -m pytest helao/core/tests/test_artifact_hash_sites.py -q`
Expected: FAIL. `write_act()` gets an unexpected keyword `reason` and/or no ledger rows are written.

- [ ] **Step 4: Implement in `meta_writer.py`**

Add the imports and helpers:

```python
from typing import Optional

from helao.core.models.hlostatus import HloStatus
from helao.helpers.artifact_hash import log_artifact_hashes
from helao.hexagon.domain.naming import DATA_SUFFIX, HEADER_SUFFIX, data_sibling

TERMINAL_STATUSES = frozenset(
    {
        HloStatus.finished,
        HloStatus.errored,
        HloStatus.aborted,
        HloStatus.skipped,
        HloStatus.estopped,
        HloStatus.retired,
    }
)


def _terminal(statuses) -> bool:
    return any(s in TERMINAL_STATUSES for s in (statuses or []))


def _event(reason):
    return "artifact_rewritten" if reason else "artifact_final"


def _action_files(output_path: str, action) -> list:
    """Every file in ``action.files`` plus the ``.meta.json`` header of a data file."""
    paths = []
    for f in action.files or []:
        if not f.file_name:
            continue
        p = os.path.join(output_path, f.file_name)
        paths.append(p)
        if p.endswith(DATA_SUFFIX):
            header = data_sibling(p, HEADER_SUFFIX)
            if os.path.exists(header):
                paths.append(header)
    return paths
```

In `write_act(self, action: Action, reason: Optional[str] = None)`, after `await self.base._write_meta_atomic(...)` and inside `if action.save_act:`:

```python
            if _terminal(action.action_status):
                await log_artifact_hashes(
                    [target], kind="act", owner_uuid=action.action_uuid,
                    event=_event(reason), reason=reason,
                )
                await log_artifact_hashes(
                    _action_files(output_path, action), kind="data",
                    owner_uuid=action.action_uuid, event=_event(reason), reason=reason,
                )
```

`write_exp(self, experiment, reason=None)` and `write_seq(self, sequence, reason=None)`: after the atomic write,

```python
        if _terminal(experiment.experiment_status):
            await log_artifact_hashes(
                [target], kind="exp", owner_uuid=experiment.experiment_uuid,
                event=_event(reason), reason=reason,
            )
```

and the same in `write_seq` with `sequence.sequence_status`, `kind="seq"` and `sequence.sequence_uuid`. If `DATA_SUFFIX` is not exported by `naming.py`, use the constant `action_host.py:65` imports; it is the same module.

`action_host.py:477`:

```python
    async def write_act(self, action, reason=None) -> None:
        ...  # docstring unchanged, plus: "``reason`` marks a post-finalize rewrite (spec §5)."
        await self.meta_writer.write_act(action, reason=reason)
```

Apply the same passthrough to the `artifact_store` port and its adapter. Read both first: if the adapter calls `meta_writer.write_act`, pass `reason` through; if not, add only the optional parameter.

- [ ] **Step 5: `-prc.json` in `sync_driver.py`** (inside `sync_process`, the `write_meta(os.path.join(save_dir, f"{pidx}__{uuid_key}__...-prc.json"), model)` call)

```python
                prc_path = os.path.join(
                    save_dir,
                    f"{pidx}__{uuid_key}__{meta['technique_name']}-prc.json",
                )
                existed = os.path.exists(prc_path)
                write_meta(prc_path, model)
                # a re-push after a write-off rewrites the record (spec §5)
                await log_artifact_hashes(
                    [prc_path],
                    kind="prc",
                    owner_uuid=uuid_key,
                    event="artifact_rewritten" if existed else "artifact_final",
                    reason="process_repush" if existed else None,
                )
```

Add the import `from helao.helpers.artifact_hash import log_artifact_hashes`.

- [ ] **Step 6: Analysis**

In `analysis_layout.py`, add and export (`__all__`):

```python
def local_output_path(output: dict, local_ana_dir: str) -> str:
    """Where :func:`publish_outputs` writes one output group locally."""
    return os.path.join(local_ana_dir, os.path.basename(output["analysis_output_path"]["key"]))
```

In `publish_outputs`, replace `target = output["analysis_output_path"]["key"]` and `local_json_out = os.path.join(local_ana_dir, os.path.basename(target))` with `target = output["analysis_output_path"]["key"]` and `local_json_out = local_output_path(output, local_ana_dir)`, leaving `target` for the uploader.

In `analysis_driver.py`, replace the `if await publish_outputs(...)` block:

```python
            published = await publish_outputs(
                model_dict, output_dict, local_ana_dir, uploader=uploader
            )
            await log_artifact_hashes(
                [os.path.join(local_ana_dir, f"{eua.analysis_uuid}-ana.json")],
                kind="ana", owner_uuid=eua.analysis_uuid,
            )
            await log_artifact_hashes(
                [local_output_path(o, local_ana_dir) for o in model_dict.get("outputs", [])],
                kind="output", owner_uuid=eua.analysis_uuid,
            )
            if published:
                LOGGER.info(f"Successfully synced {eua.analysis_uuid}")
                return True
```

Add the imports `local_output_path` (from `analysis_layout`) and `log_artifact_hashes`, plus `os` if missing. Confirm the `-ana.json` file name by reading `write_model_json` (`analysis_layout.py:292`): it is `<local_ana_dir>/<analysis_uuid>-ana.json`.

Add one test to `test_artifact_hash_sites.py` that calls `publish_outputs(model_dict, output_dict, str(tmp_path), uploader=None)` with one output, then `local_output_path`. It asserts the file exists at that path, so the helper and the writer cannot drift. Read `publish_outputs`' docstring for the `model_dict`/`output_dict` shapes, and build the smallest valid pair from its existing test (`rg -n "publish_outputs" helao/hexagon/tests helao/core/tests`).

- [ ] **Step 7: Run the tests**

Run: `python -m pytest helao/core/tests/test_artifact_hash_sites.py -q`, then the existing suites for every touched module, one file per process:
`helao/hexagon/tests/test_native_meta_writer.py`, `helao/hexagon/tests/test_analysis_artifact.py`, `helao/hexagon/tests/test_sync_port_wiring.py`, and `rg -l "sync_process|publish_outputs|write_act" helao/hexagon/tests helao/core/tests helao/deploy/hte/tests`.
Then both golden masters: `python helao/core/tests/test_active_golden_master.py --check` (14) and `python helao/core/tests/test_orch_dispatch_golden_master.py --check` (9).
Expected: all PASS, golden masters unchanged. If a golden master diffs only by new `artifact_*` log lines, stop and report; do not regenerate.

- [ ] **Step 8: Mutation check**

Delete the `kind="data"` call in `write_act`: `test_finished_action_hashes_record_and_files` must fail. Restore it.

- [ ] **Step 9: Commit** (main session)

```bash
black <every changed .py>
git -C . add -u && git -C . add helao/core/tests/test_artifact_hash_sites.py
git -C . commit -m "feat: SHA-256 records for finalized act/exp/seq/prc/ana records, data files and analysis outputs"
```

---

### Task 9: Rewrite sites, AST gate, private-deployment inventory

**Files:**
- Modify: `helao/core/tests/_record_rewrite.py`. `rewrite_dir` (~216-245), `rewrite_zip` (~261-340) and `rewrite_processes` (~490-531) each gain `reason: str = "record_rewrite"`.
- Modify: `helao/core/tests/set_run_use.py:164-189` (pass `reason="set_run_use"`), `helao/core/tests/set_plate_id.py:601`
- Modify: `helao/hexagon/app/action_host.py` `_reconcile_one` (the `await self.write_act(action)` ~line 1454) to pass `reason="reconcile_interrupted"`
- Test: `helao/core/tests/test_artifact_hash_gate.py`; extend `helao/core/tests/test_artifact_hash_sites.py`

**Interfaces:**
- Consumes: `log_artifact_hashes_sync`, `record_uuid`, `MetaWriter.write_act(reason=)`.

- [ ] **Step 1: Write the gate test**

```python
"""Every record write outside the finalization seam logs a rehash (spec §5)."""

import ast
import subprocess
from pathlib import Path

WRITERS = {"write_meta"}
HASHERS = {"log_artifact_hashes", "log_artifact_hashes_sync"}
# (file, function) -> why no rehash is needed there
ALLOW = {
    ("helao/core/drivers/data/analysis_layout.py", "write_model_json"):
        "hashed by AnalysisDriver after publish_outputs",
    ("helao/hexagon/adapters/native/data_file.py", "*"):
        "data .meta.json header, rewritten on every write_file; hashed at action finalization",
    ("helao/hexagon/adapters/native/posthoc_writer.py", "*"):
        "data .meta.json header; hashed at action finalization",
    ("helao/hexagon/adapters/native/sync_driver.py", "write_meta"):
        "method named write_meta (the .prg sidecar), not a record writer",
}


def _called(fn) -> set:
    names = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            f = n.func
            names.add(f.id if isinstance(f, ast.Name) else getattr(f, "attr", None))
    return names


def _files():
    out = subprocess.run(["git", "-C", ".", "ls-files", "*.py"], capture_output=True, text=True, check=True).stdout
    return [p for p in out.split() if not Path(p).name.startswith("test_")
            and not p.startswith("harness/") and "/smoke/" not in p]


def test_record_writes_rehash_or_are_allowlisted():
    bad = []
    for path in _files():
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            called = _called(fn)
            if called & WRITERS and not called & HASHERS:
                if (path, fn.name) in ALLOW or (path, "*") in ALLOW:
                    continue
                bad.append(f"{path}:{fn.lineno} {fn.name}")
    assert not bad, "record write without log_artifact_hashes:\n" + "\n".join(bad)


def test_gate_catches_a_planted_site(tmp_path):
    src = "def f(p, d):\n    write_meta(p, d)\n"
    fn = ast.parse(src).body[0]
    assert _called(fn) & WRITERS and not _called(fn) & HASHERS
```

- [ ] **Step 2: Run it**

Run: `python -m pytest helao/core/tests/test_artifact_hash_gate.py -q`
Expected: FAIL, listing at least `_record_rewrite.py rewrite_dir`, `rewrite_processes` and `set_plate_id.py main` (or the enclosing function at line 601). Any other site listed must be judged with one rule. If it rewrites a finalized record, add a rehash. If it writes a data header or a non-record file, add it to `ALLOW` with a reason. If you can't tell, stop and report the site to the main session rather than allowlisting it.

- [ ] **Step 3: Implement the rewrite hashes**

`_record_rewrite.rewrite_dir`: add `reason: str = "record_rewrite"` and, right after `write_meta(path, doc)`:

```python
            log_artifact_hashes_sync(
                [path], kind=kind_for(path) or "record", owner_uuid=record_uuid(doc),
                event="artifact_rewritten", reason=reason,
            )
```

`rewrite_processes`: the same after its `write_meta(path, doc)`, with `kind="prc"`.

`rewrite_zip`: add `reason: str = "record_rewrite"`; after `os.replace(staged, zip_path)` (~line 335), when not `dry_run`:

```python
    log_artifact_hashes_sync(
        [zip_path], kind="zip", owner_uuid=sequence_uuid,
        event="artifact_rewritten", reason=reason,
    )
```

Use the variable that holds the sequence uuid in that function; read it first.

Thread `reason` through the `set_run_use.rewrite_zip`/`rewrite_processes` wrappers with `reason="set_run_use"`. If `set_plate_id` calls the `_record_rewrite` functions, pass `reason="set_plate_id"` there too.

`set_plate_id.py:601`: after `write_meta(path, ynew)`:

```python
        log_artifact_hashes_sync(
            [path], kind=kind_for(path) or "record", owner_uuid=record_uuid(ynew),
            event="artifact_rewritten", reason="set_plate_id",
        )
```

`kind_for` comes from `_record_rewrite` (already imported there?). Check, and import it if not. Imports: `from helao.helpers.artifact_hash import log_artifact_hashes_sync, record_uuid`.

`action_host.py _reconcile_one`: `await self.write_act(action, reason="reconcile_interrupted")`.

- [ ] **Step 4: Rewrite tests** (append to `test_artifact_hash_sites.py`)

```python
def test_rewrite_dir_logs_rewritten(tmp_path, ledger):
    from helao.core.tests import _record_rewrite
    from helao.helpers.meta_io import write_meta

    p = write_meta(tmp_path / "250101.000000000000-act.json", {"action_uuid": "a1", "run_use": "data"})

    def apply(doc):
        doc["run_use"] = "ref"
        return doc

    _record_rewrite.rewrite_dir(tmp_path, apply, reason="set_run_use")
    (r,) = [r for r in ledger() if r["event"] == "artifact_rewritten"]
    assert (r["uuid"], r["reason"], r["kind"]) == ("a1", "set_run_use", "act")
```

Read `rewrite_dir`'s real signature and what `apply` must return (`rg -n "def rewrite_dir" -A 25 helao/core/tests/_record_rewrite.py`), and adapt the call while keeping the assertions. Do the same for one `rewrite_zip` test: build a zip containing one `-act.json`, rewrite it, and assert a `kind == "zip"` row whose `sha256` equals the new zip's digest.

- [ ] **Step 5: Run the tests**

Run: `python -m pytest helao/core/tests/test_artifact_hash_gate.py helao/core/tests/test_artifact_hash_sites.py -q`, then the existing tool tests one per process: `rg -l "set_run_use|set_plate_id|_record_rewrite|_reconcile_one" helao/core/tests helao/hexagon/tests`.
Expected: all PASS.

- [ ] **Step 6: Mutation check**

Remove the rehash in `rewrite_processes`: the gate test must fail and name it. Restore it.

- [ ] **Step 7: Private-deployment inventory** (report only; no edits until the main session approves)

```bash
for d in helao/deploy/*/; do
  top=$(git -C "$d" rev-parse --show-toplevel 2>/dev/null)
  [ "$top" = "$(realpath "$d")" ] || continue
  echo "== $d"
  rg -uu -n "write_meta\(|_record_rewrite|rewrite_zip|writestr|DedupTimedRotating|GZipRotator|LOGS.*\.log\b|_key\}\.log" "$d" --type py
done
```

For each hit, classify it as one of: (a) rewrites a finalized record: needs `log_artifact_hashes_sync(..., event="artifact_rewritten", reason=<tool name>)`; (b) reads `LOGS/<key>.log`: switch to `read_logs`; (c) references the removed classes; (d) unaffected. Return the table to the main session. The main session gets user approval before the nested-repo edits, which are made and committed in each nested repo separately (`git -C helao/deploy/<d>`).

- [ ] **Step 8: Commit** (main session; parent repo only)

```bash
black <changed .py>
git -C . add -u && git -C . add helao/core/tests/test_artifact_hash_gate.py
git -C . commit -m "feat: rehash records on post-finalize rewrites; AST gate for record writers"
```

---

### Task 10: `log_tail` shared module

**Files:**
- Create: `helao/ui/shared/log_tail.py`
- Modify: `helao/ui/shared/palette.py` (add `LOG_LEVEL_TEXT`)
- Test: `helao/core/tests/test_log_tail.py`

**Interfaces:**
- Produces:
  - `tail_init(log_dir, n: int = 2000) -> tuple[list[dict], list[dict]]` (records, cursors)
  - `tail_poll(log_dir, cursors: list[dict]) -> tuple[list[dict], list[dict]]`
  - `merge(old: list[dict], new: list[dict], keep: int) -> list[dict]`
  - `filter_records(records, servers: set | None, min_level: str, text: str) -> list[dict]`
  - `to_rows(records) -> list[list[str]]`, each row `[ts, level, server, msg, color]`, newest first
  - a cursor is `{"path": str, "inode": int, "offset": int}`
  - constant `CHUNK = 2 << 20`

- [ ] **Step 1: Add the palette role** (read `helao/ui/shared/CLAUDE.md` first)

In `palette.py`, beside the other text roles (~line 766):

```python
#: Row text colour per log level on the Reflex /logs page.
LOG_LEVEL_TEXT: Final[dict[str, str]] = {
    "DEBUG": TW["slate-500"],
    "INFO": TW["slate-900"],
    "WARNING": TW["amber-700"],
    "ERROR": TW["red-700"],
    "CRITICAL": TW["red-700"],
    "ALERT": TW["red-700"],
}
```

Run `python -m pytest helao/core/tests/test_palette.py -q`. If it needs the new role registered for contrast floors, follow what the existing text roles do. If it needs recalibrating a frozen fixture, stop and report.

- [ ] **Step 2: Write the failing tests**

```python
"""Tailing JSONL logs for the /logs page (spec §4)."""

import json
import os
import time

from helao.ui.shared import log_tail


def _line(seq, server="A", level="INFO", msg=None, ts=None):
    ts = ts or f"2026-10-26T00:00:{seq % 60:02d}.000000Z"
    return (json.dumps({"ts": ts, "level": level, "server": server, "pid": 1,
                        "seq": seq, "msg": msg or f"m{seq}"}) + "\n").encode()


def test_init_reads_newest_n_and_poll_reads_appends(tmp_path):
    f = tmp_path / "helao_g.jsonl"
    f.write_bytes(b"".join(_line(i) for i in range(10)))
    recs, cur = log_tail.tail_init(tmp_path, n=3)
    assert [r["seq"] for r in recs] == [7, 8, 9]
    with open(f, "ab") as fh:
        fh.write(_line(10) + b'{"partial": ')
    recs, cur = log_tail.tail_poll(tmp_path, cur)
    assert [r["seq"] for r in recs] == [10]          # partial line waits
    with open(f, "ab") as fh:
        fh.write(b'1, "ts": "2026-10-26T00:01:00.000000Z", "server": "A", "pid": 1, "seq": 11, "level": "INFO", "msg": "x"}\n')
    recs, _ = log_tail.tail_poll(tmp_path, cur)
    assert [r["seq"] for r in recs] == [11]


def test_rotation_finishes_renamed_file_then_new(tmp_path):
    f = tmp_path / "helao_g.jsonl"
    f.write_bytes(_line(1))
    _, cur = log_tail.tail_init(tmp_path)
    with open(f, "ab") as fh:
        fh.write(_line(2))                 # written after the last poll
    os.rename(f, tmp_path / "helao_g_20261026T000000.jsonl")
    f.write_bytes(_line(3))
    recs, _ = log_tail.tail_poll(tmp_path, cur)
    assert [r["seq"] for r in recs] == [2, 3]


def test_rotation_with_plain_copy_gone_emits_warning_row(tmp_path):
    f = tmp_path / "helao_g.jsonl"
    f.write_bytes(_line(1))
    _, cur = log_tail.tail_init(tmp_path)
    f.unlink(); f.write_bytes(_line(5))
    recs, _ = log_tail.tail_poll(tmp_path, cur)
    assert recs[0]["level"] == "WARNING" and "may be missing" in recs[0]["msg"]
    assert recs[-1]["seq"] == 5


def test_oversized_line_is_skipped_with_note(tmp_path, monkeypatch):
    monkeypatch.setattr(log_tail, "CHUNK", 64)
    f = tmp_path / "helao_g.jsonl"
    f.write_bytes(b"")
    _, cur = log_tail.tail_init(tmp_path)
    f.write_bytes(b'{"msg": "' + b"x" * 500 + b'"}\n' + _line(7))
    recs, cur = log_tail.tail_poll(tmp_path, cur)
    recs2, _ = log_tail.tail_poll(tmp_path, cur)
    allrecs = recs + recs2
    assert any("over" in r["msg"] and "skipped" in r["msg"] for r in allrecs)
    assert allrecs[-1]["seq"] == 7


def test_ignores_ledger_and_rotated_files(tmp_path):
    (tmp_path / "artifacts_g.jsonl").write_bytes(_line(1))
    (tmp_path / "helao_g_20261026T000000.jsonl").write_bytes(_line(2))
    (tmp_path / "A.jsonl").write_bytes(_line(3, server="A"))
    recs, _ = log_tail.tail_init(tmp_path)
    assert [r["seq"] for r in recs] == [3]


def test_merge_dedups_and_keeps_newest():
    a = [json.loads(_line(i)) for i in range(5)]
    m = log_tail.merge(a, a[3:] + [json.loads(_line(9))], keep=4)
    assert [r["seq"] for r in m] == [2, 3, 4, 9]


def test_filter_and_rows():
    recs = [json.loads(_line(1, "A", "DEBUG")), json.loads(_line(2, "B", "ERROR", "disk full"))]
    assert [r["seq"] for r in log_tail.filter_records(recs, None, "INFO", "")] == [2]
    assert log_tail.filter_records(recs, {"A"}, "DEBUG", "") == recs[:1]
    assert log_tail.filter_records(recs, None, "DEBUG", "DISK") == recs[1:]
    rows = log_tail.to_rows(recs)
    assert rows[0][2] == "B" and rows[0][4].startswith("#")   # newest first, colour
```

- [ ] **Step 3: Run them to verify they fail**

Run: `python -m pytest helao/core/tests/test_log_tail.py -q`
Expected: FAIL with `ImportError`

- [ ] **Step 4: Implement**

```python
"""Tail a LOGS directory's JSONL files for the /logs page (spec §4).

Reflex-free so a Bokeh front end can reuse it. A cursor is
``{"path", "inode", "offset"}``; ``offset`` only ever advances past a complete
line, so a partial last line waits for the next poll.
"""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from helao.ui.shared.palette import LOG_LEVEL_TEXT

CHUNK = 2 << 20
LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50, "ALERT": 60}
_ROTATED = re.compile(r"_\d{8}T\d{6}(?:_\d+)?\.jsonl$")


def _note(msg: str) -> dict:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return {"ts": ts, "level": "WARNING", "server": "logs", "pid": 0, "seq": 0, "msg": msg}


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
        cursors.append({"path": str(p), "inode": st.st_ino, "offset": start + dropped + used})
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
    """``old`` + ``new`` without duplicate ``(server, pid, seq)``, by ``ts``, newest ``keep``."""
    seen, out = set(), []
    for r in old + new:
        key = (r.get("server"), r.get("pid"), r.get("seq"))
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
        rows.append([r.get("ts", ""), level, r.get("server", ""), msg, LOG_LEVEL_TEXT.get(level, LOG_LEVEL_TEXT["INFO"])])
    return rows
```

`os` is imported for parity with callers; drop it if unused (`black` won't flag it, so check with `rg -n "os\." helao/ui/shared/log_tail.py`).

- [ ] **Step 5: Run the tests**

Run: `python -m pytest helao/core/tests/test_log_tail.py helao/core/tests/test_palette.py -q`
Expected: PASS

- [ ] **Step 6: Mutation check**

Make `_finish_rotated` return `[]` immediately: `test_rotation_finishes_renamed_file_then_new` must fail. Restore it.

- [ ] **Step 7: Commit** (main session)

```bash
black helao/ui/shared/log_tail.py helao/ui/shared/palette.py helao/core/tests/test_log_tail.py
git -C . add helao/ui/shared/log_tail.py helao/ui/shared/palette.py helao/core/tests/test_log_tail.py
git -C . commit -m "feat(ui): shared JSONL log tail with rotation follow"
```

---

### Task 11: Reflex `/logs` page

**Files:**
- Create: `helao/ui/reflex/logs.py`
- Modify: `helao/ui/reflex/app.py`. Add `"/logs"` to `SHELL_ROUTES` (~line 89); add a nav link beside `rx.link("Quarantine", href="/quarantine")` (~line 359); call `configure_logs(world_cfg, server_key)` beside `configure_quarantine` (~line 539); add `add_page` beside the quarantine page (~line 643); add the imports.
- Test: `helao/core/tests/test_reflex_logs_page.py`

**Interfaces:**
- Consumes: `log_tail.*`.
- Produces: `configure_logs(world_cfg: dict, server_key: str) -> None`, `LogsState`, `logs_page() -> rx.Component`.

- [ ] **Step 1: Read `helao/ui/reflex/CLAUDE.md`**

Note especially the rules on `rx.moment` ticks, `foreach` element annotations, the `_app/` working directory, and the mixin and lazy `add_page` rules.

- [ ] **Step 2: Write the failing test** (state logic without a browser)

```python
"""The /logs page state (spec §4)."""

import json

from helao.ui.reflex import logs


def _line(seq, server="A", level="INFO"):
    return (json.dumps({"ts": f"2026-10-26T00:00:{seq:02d}.000000Z", "level": level,
                        "server": server, "pid": 1, "seq": seq, "msg": f"m{seq}"}) + "\n").encode()


def test_configure_logs_absolute_dir(tmp_path):
    logs.configure_logs({"root": str(tmp_path)}, "UI")
    assert logs._CONFIG["log_dir"] == str((tmp_path / "LOGS").resolve())


def test_state_start_tick_filter_pause(tmp_path):
    d = tmp_path / "LOGS"; d.mkdir()
    (d / "helao_g.jsonl").write_bytes(_line(1, "A") + _line(2, "B", "ERROR"))
    logs.configure_logs({"root": str(tmp_path)}, "UI")
    s = logs.LogsState()
    s.start()
    assert s.servers == ["A", "B"] and [r[2] for r in s.rows] == ["B", "A"]
    s.set_min_level("ERROR")
    assert [r[2] for r in s.rows] == ["B"]
    s.toggle_pause()
    with open(d / "helao_g.jsonl", "ab") as f:
        f.write(_line(3, "B", "ERROR"))
    s.tick()
    assert len(s.rows) == 1                      # display frozen
    s.toggle_pause()
    assert len(s.rows) == 2                      # polled while paused
```

> Reflex state classes may not be instantiable outside an app context. If `logs.LogsState()` raises, move the handler bodies into plain functions in `logs.py` (`_start(state)`, `_tick(state)`, ...) that take any object with the same attributes, call those from the `@rx.event` methods, and test them with a `SimpleNamespace`. This is the `sync_quarantine.py` pattern (`_rearm(state)`). Keep the test's assertions unchanged.

- [ ] **Step 3: Implement `logs.py`**

```python
"""The /logs page: live tail of this group's JSONL logs.

The logic lives in ``helao/ui/shared/log_tail.py`` (Reflex-free). Design:
docs/superpowers/specs/2026-10-26-jsonl-unified-logging-design.md (section 4).
"""

import os

import reflex as rx

from helao.ui.shared import log_tail

_CONFIG: dict = {"log_dir": None}

MAX_ROWS = 2000
TICK_MS = 1000
LEVEL_CHOICES = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "ALERT"]


def configure_logs(world_cfg: dict, server_key: str) -> None:
    """Point the page at ``<root>/LOGS`` as an absolute path.

    Never raises: runs from ``build_app`` at import time. Absolute because the
    Reflex process runs from ``_app/``, not the repo root.
    """
    root = world_cfg.get("root") if isinstance(world_cfg, dict) else None
    _CONFIG["log_dir"] = os.path.realpath(os.path.join(root, "LOGS")) if root else None


def _log_dir():
    d = _CONFIG.get("log_dir")
    return d if d and os.path.isdir(d) else None


def _refresh(state) -> None:
    if state.paused:
        return
    servers = set(state.selected) or None
    state.rows = log_tail.to_rows(
        log_tail.filter_records(state._all, servers, state.min_level, state.text)
    )


def _start(state) -> None:
    d = _log_dir()
    if d is None:
        state.rows = []
        return
    state._all, state._cursors = log_tail.tail_init(d, MAX_ROWS)
    state.servers = sorted({r.get("server", "") for r in state._all})
    _refresh(state)


def _tick(state) -> None:
    d = _log_dir()
    if d is None:
        return
    new, state._cursors = log_tail.tail_poll(d, state._cursors)
    if new:
        state._all = log_tail.merge(state._all, new, MAX_ROWS)
        state.servers = sorted({r.get("server", "") for r in state._all})
        _refresh(state)


class LogsState(rx.State):
    """Per-tab tail state. ``_all``/``_cursors`` are backend-only."""

    _all: list = []
    _cursors: list = []
    rows: list[list[str]] = []
    servers: list[str] = []
    selected: list[str] = []
    min_level: str = "INFO"
    text: str = ""
    paused: bool = False

    @rx.event
    def start(self):
        _start(self)

    @rx.event
    def tick(self, _value=None):
        # polls even while paused (only the display is frozen), so a rotated
        # file's plain copy is read inside its grace window
        _tick(self)

    @rx.event
    def set_min_level(self, value: str):
        self.min_level = value
        _refresh(self)

    @rx.event
    def set_text(self, value: str):
        self.text = value
        _refresh(self)

    @rx.event
    def toggle_server(self, server: str, on: bool):
        chosen = [s for s in self.selected if s != server]
        self.selected = chosen + [server] if on else chosen
        _refresh(self)

    @rx.event
    def toggle_pause(self):
        self.paused = not self.paused
        _refresh(self)


def _server_box(server: rx.Var) -> rx.Component:
    return rx.checkbox(
        server,
        checked=LogsState.selected.contains(server),
        on_change=lambda on: LogsState.toggle_server(server, on),
    )


def _row(row: rx.Var) -> rx.Component:
    return rx.table.row(
        rx.table.cell(row[0], white_space="nowrap"),
        rx.table.cell(row[1]),
        rx.table.cell(row[2]),
        rx.table.cell(row[3], font_family="monospace", white_space="pre-wrap"),
        style={"color": row[4]},
    )


def logs_page() -> rx.Component:
    return rx.vstack(
        rx.moment(interval=TICK_MS, on_change=LogsState.tick, display="none"),
        rx.hstack(
            rx.select(LEVEL_CHOICES, value=LogsState.min_level, on_change=LogsState.set_min_level),
            rx.input(placeholder="search", value=LogsState.text, on_change=LogsState.set_text),
            rx.button(rx.cond(LogsState.paused, "Resume", "Pause"), on_click=LogsState.toggle_pause),
            spacing="3",
        ),
        rx.flex(rx.foreach(LogsState.servers, _server_box), wrap="wrap", spacing="3"),
        rx.table.root(
            rx.table.header(
                rx.table.row(
                    rx.table.column_header_cell("time (UTC)"),
                    rx.table.column_header_cell("level"),
                    rx.table.column_header_cell("server"),
                    rx.table.column_header_cell("message"),
                )
            ),
            rx.table.body(rx.foreach(LogsState.rows, _row)),
            width="100%",
        ),
        on_mount=LogsState.start,
        width="100%",
    )
```

`state._all` and `state._cursors` are assigned through `_start` and `_tick`. If Reflex refuses backend-var assignment through a helper, rename them in both places, keeping the leading underscore.

- [ ] **Step 4: Register in `app.py`**

```python
from helao.ui.reflex.logs import configure_logs, logs_page
```

- In `SHELL_ROUTES`, add `"/logs",` after `"/quarantine",`.
- In the nav, add `rx.link("Logs", href="/logs"),` after the Quarantine link.
- In `build_app`, add `configure_logs(world_cfg, server_key)` after `configure_quarantine(world_cfg, server_key)`.
- After the quarantine `add_page`:

```python
    application.add_page(
        lambda: _page("Logs", logs_page(), "/logs"),
        route="/logs",
        title="HELAO logs",
    )
```

- [ ] **Step 5: Run the tests and the export**

Run: `python -m pytest helao/core/tests/test_reflex_logs_page.py -q`, then the existing Reflex test files `rg -l "SHELL_ROUTES|build_app" helao/core/tests helao/hexagon/tests` (one per process).
Then build the bundle to catch `ForeachVarError`: `python build_reflex_bundle.py goldenreflex --server <reflex key from helao/deploy/test/configs/goldenreflex.yml>`.
Expected: PASS, and the build exits 0.

- [ ] **Step 6: Headless check** (main session)

Launch `goldenreflex` (background, marker file). Then, with the scratch Playwright venv (project memory "Playwright headless checks": playwright 1.62.0, not in the helao env), open `http://127.0.0.1:<reflex port>/logs`. Assert that at least one table row appears within 5 s. Select level `ERROR` and assert the rows are a subset. Type a server key into search and assert every row's message or server matches. Save a screenshot to `$CLAUDE_JOB_DIR/tmp/logs_page.png`.

- [ ] **Step 7: Commit** (main session)

```bash
black helao/ui/reflex/logs.py helao/ui/reflex/app.py helao/core/tests/test_reflex_logs_page.py
git -C . add helao/ui/reflex/logs.py helao/ui/reflex/app.py helao/core/tests/test_reflex_logs_page.py
git -C . commit -m "feat(reflex): /logs live log page"
```

---

### Task 12: End-to-end check and full sweep

**Files:** none new. This task only verifies.

- [ ] **Step 1: Detach and reconnect** (main session, in tmux so keys can be sent)

```bash
D=$CLAUDE_JOB_DIR/tmp/e2e; mkdir -p $D
tmux new-session -d -s logs_e2e "cd $PWD && ./helao.sh goldenreflex 2>&1 | tee $D/launch1.out"
# wait ~60 s for the group, then detach:
tmux send-keys -t logs_e2e C-d
# generate records while detached (e.g. GET /docs or POST an action on a sim server), wait 10 s, then:
tmux new-session -d -s logs_e2e2 "cd $PWD && ./helao.sh goldenreflex --reconnect 2>&1 | tee $D/launch2.out"
```

Check with `read_logs('/tmp/helao-reflex/LOGS')`:
- every server key appears in `helao_goldenreflex.jsonl`;
- at least one `<KEY>.jsonl` fallback file exists from the detached window;
- a `records went to` marker record exists after the reconnect;
- `read_logs` returns no duplicate `(server, pid, seq)`.

Then CTRL-x the second launcher (`tmux send-keys -t logs_e2e2 C-x`) and confirm every process exits.

- [ ] **Step 2: Artefact ledger end to end**

While the group runs, dispatch one simulated action that writes a data file (use the `goldenreflex` operator or a POST to a sim action server; pick the action from `helao/deploy/test/configs/goldenreflex.yml`). Then:
`python -c "from helao.helpers.helao_logging import read_logs; print(read_logs('/tmp/helao-reflex/LOGS', ledger=True)[['kind','path','sha256']])"`
Expected: an `act` row and `data` rows for that action. Each `sha256` must equal `sha256sum` of the file under `/tmp/helao-reflex`.

- [ ] **Step 3: Full sweep** (background + marker file, per `background-sweep-watchers`)

```bash
D=$CLAUDE_JOB_DIR/tmp/sweep; mkdir -p $D
( PYTHONPATH=$PWD python run_tests.py > $D/run.log 2>&1; echo $? > $D/done )   # background command 1
for i in $(seq 1 720); do [ -f $D/done ] && break; sleep 15; done; echo "rc=$(cat $D/done)"; tail -5 $D/run.log   # background command 2
```

Expected: no FAIL beyond the pre-change baseline (last baseline: 485 PASS, 6 ENV, 0 FAIL, plus the new test files). Then run `python run_unit_tests.py` and the two golden masters (`--check`).

- [ ] **Step 4: Station rows**

Hand the user the station checks that cannot be run here:
- On a Windows station: the rotation retry while a viewer holds the file. Force it with a small `rotate_records` via a temporary config override; do not commit it.
- On a Windows station: the `launch_orphan_win.bat` smoke, because `launch.py`'s startup changed.
- On one production group: `/logs` on a real group's volume.

---

## Self-Review Notes

- **Spec coverage:**
  - §1 schema: Task 1. Handler: Task 4. Buffer, dedup and replay: Tasks 3 and 4.
  - §2 endpoint and collector: Task 5. Integration: Task 6. Writer: Task 2. Teardown: Task 6. Removed zip blocks: Task 6.
  - §3 migration: Tasks 4 and 6, plus Task 9 Step 7 for private repos. Failure modes: Tasks 2, 4 and 5. Tests: each task.
  - §4 viewer: Tasks 10 and 11.
  - §5 hashing: Task 7. Finalization: Task 8. Rewrites and gate: Task 9. Ledger: Tasks 4, 5 and 7. Retention exemption: Task 2.
- **Review Focus mapping:** items 1-2 are in Task 2, item 3 in Task 1, item 4 in Task 4, item 5 in Task 10.
- **Type consistency:**
  - Cursor dicts use keys `path`/`inode`/`offset` throughout.
  - The handler takes `stem` as its first argument, called with the logger name.
  - `RotatingJsonlWriter(..., retain_days=None)` marks every ledger writer.
  - `LEDGER_FRAME` is used identically by the handler and the collector.
