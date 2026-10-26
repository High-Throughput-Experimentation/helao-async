# JSONL logs, a unified launcher log, and a live log page

Date: 2026-10-26. Status: design approved in conversation; awaiting spec review.

## Goal

1. Every HELAO log file is JSONL (one JSON object per line) instead of formatted text.
2. When a group runs under `launch.py`, all of its processes log into **one** file owned by
   the launcher, instead of one file per server.
3. Logging never blocks a caller: not a server's event loop, and not the launcher's hotkey,
   restart, or teardown threads.
4. Without a launcher, each process keeps today's per-server file, in JSONL.
5. Files rotate by record count, sized so a consumer with 1 GB of memory can load one rotated
   file into pandas with a single `pd.read_json(..., lines=True, compression="gzip")`.
6. A live log page in the Reflex UI.

The unified log serves both live tailing and later analysis in pandas, equally.

## Measured basis for the rotation size

Synthetic JSONL built from 10,589 real simulated-station log lines, using the §1 schema, loaded
with pandas 3.0.6 in the `helao` env:

| raw JSONL | gzip | rows | `read_json(lines=True)` peak RSS | `chunksize=100k` | pyarrow `read_json` |
|---|---|---|---|---|---|
| 64 MiB | 7.3 MB | 310k | 892 MB | 447 MB | 444 MB |
| 256 MiB | 29 MB | 1.24M | 3015 MB | 666 MB | 939 MB |

A naive load peaks at about 13x the raw size; almost all of that is the JSON parse, not the
DataFrame (49 MB at 64 MiB). The average record is about 216 bytes. **Decision: rotate every
300,000 records** (about 64 MiB, about 7 MB gzipped). A run of long tracebacks can make one
file larger. There is no byte backstop; add one if a real station's files exceed the budget.

## §1 Record schema and the child side

### Record

```json
{"ts": "2026-10-26T17:31:02.123456Z", "level": "INFO", "server": "PSTAT", "pid": 4242,
 "seq": 1834, "func": "setup_action", "file": "action_host.py", "line": 512,
 "msg": "...", "exc": "Traceback (most recent call last): ..."}
```

- `ts`: UTC, ISO-8601, microseconds, `Z` suffix, with the cached NTP offset applied (as
  `NtpOffsetFormatter` does today). `pd.to_datetime` parses it to `datetime64[ns, UTC]`.
- `server`: the logger name (the server key, or the module name for a bare `make_logger`).
- `seq`: a per-process counter, incremented for every record emitted. A gap shows loss.
- `exc`: present only when the record carries `exc_info`; the formatted traceback.
- `repeat_count`, `repeat_period`: present only on a dedup summary record (§1, recent-records
  buffer). The summary says the preceding `repeat_period`-record sequence was suppressed
  `repeat_count` more times.
- `(server, pid, seq)` is unique per record. Replay (below) can write a record twice; readers
  drop duplicates on that key.
- Serialized with `ensure_ascii=False`, UTF-8, `\n`-terminated.

### Handlers built by `make_logger`

`make_logger` keeps its signature, so its 40+ call sites are unchanged.

1. **Console**: the coloured text `StreamHandler`, unchanged. Under the launcher it still flows
   through `ConsoleMux` to the terminal.
2. **`JsonlSinkHandler`** (new; replaces `DedupTimedRotatingFileHandler`). Per record:
   1. **Dedup** against the recent-records buffer (below). Replaces today's
      consecutive-only dedup; `dedup_interval` keeps its meaning.
   2. **Format** the record to the §1 JSON bytes.
   3. **Send**: if `HELAO_LOG_ENDPOINT` is set, `send(NOBLOCK)` on a ZMQ PUSH socket connected
      to it with `IMMEDIATE=1` and `SNDHWM=1000`. `IMMEDIATE` makes the send raise
      `zmq.Again` when no launcher is connected, as well as when the queue is full.
   4. **Fallback**: on `zmq.Again`, or when there is no endpoint, write the record to this
      process's own file through a `RotatingJsonlWriter` (§2), at `<log_dir>/<name>.jsonl`.
      On the first `Again` after a run of successful sends, first **replay** the buffer
      (below) into that file.
   5. **Re-attach marker**: the first successful send after one or more fallback writes is
      preceded by a WARNING record: `"<N> records went to <fallback path>"`.

### Recent-records buffer

Each `JsonlSinkHandler` keeps a `deque(maxlen=2000)` of the records it emitted: fingerprint,
`seq`, the JSON bytes, and whether the bytes were sent to the launcher. About 500 KB per process.
It serves two purposes.

**Repeated-sequence dedup.** Today's dedup compares each message with the previous one only,
so a loop logging `A B C A B C ...` (for example, a cascading exception) is never collapsed.

- Fingerprint: level, `file`, `line`, the rendered message, and the exception type and text
  when present. (Today's comparison ignores the level and the traceback, so two different
  exceptions logged with the same message text collapse into one; this fixes that.)
- For each new record, check every period `p` from 1 to 16 for which the buffer's record `p`
  places back has the same fingerprint. A cycle of period `p` is confirmed when the last `p`
  records equal the `p` before them.
- While the cycle holds, each further record that continues it is held back rather than
  written, and each completed cycle is counted.
- When a record breaks the cycle, or `dedup_interval` (10 s) has passed since the cycle was
  confirmed, write one summary record (`msg`: `"previous <p>-message sequence repeated <M>
  times"`, with `repeat_count` and `repeat_period`). Then write the held-back records of the
  incomplete cycle; they are real records, not repeats. An elapsed interval opens a new
  window, so a sustained loop yields one summary every 10 s.
- `p = 1` is today's behaviour. Messages that differ on every pass (a counter or a timestamp
  inside the f-string) do not match and are not collapsed. Comparing message templates would
  collapse them but hide the changing values; rendered text is kept on purpose.
- The check costs at most 16 fingerprint comparisons per record and runs under the handler
  lock that `emit` already holds.
- `close()` (run by `logging.shutdown` at exit) writes any pending summary and held-back
  records, so a process that stops mid-cycle does not lose the count. Today's handler loses it.

**Replay on launcher loss (at-least-once delivery).** Records in the child's send queue, the
kernel socket buffers, or the collector's receive queue when the launcher dies would be lost.
On the first `Again` after a run of successful sends, the handler writes every buffered record
that was sent to the launcher (oldest first) into its fallback file, then the new record. Some
of them already reached the unified file; readers drop the duplicates on `(server, pid, seq)`.
Records are lost only if more than 2,000 were in flight. The two high-water marks bound that at
`SNDHWM + RCVHWM = 2000`.

   The socket is used only inside `emit`, which `logging.Handler.handle` already runs under
   the handler lock. That serializes access from executor threads and the event-loop thread.
3. **ALERT email and webhook**: unchanged, and still in each process, so alerts go out with no
   launcher.

With no `HELAO_LOG_ENDPOINT` (tests, or a server started by hand with `fast_launcher.py`), no
socket is opened and every record goes to the process's own file: today's behaviour, in JSONL.

## §2 Launcher collector

### Endpoint

- `tcp://127.0.0.1:<log_port>`. `log_port` is a new optional top-level config key. It defaults
  to one above the highest port any server occupies (a Reflex server occupies `port` and
  `port + 1`).
- `launch.py`'s existing `host:port` uniqueness check covers `log_port`. A bound port aborts
  the launch before any server is spawned, like a server port clash.
- The launcher puts `HELAO_LOG_ENDPOINT` into every child's environment. `ConsoleMux.child_env`
  returns an environment always, not only when the mux is active.
- The endpoint is fixed by the config, so a `--reconnect` launcher binds the same port, and a
  detached group's children re-attach without a restart (ZMQ reconnects on its own).

### `LogCollector`

- One daemon thread owns the PULL socket (`RCVHWM=1000`) and the unified file
  `<root>/LOGS/helao_<config_prefix>.jsonl`.
- Loop: poll with a 0.5 s timeout, check the stop flag, and append each received message's
  bytes unchanged. The child already serialized it; the launcher does no JSON work.
- The file is flushed after each drained batch, so a killed launcher loses nothing it already
  wrote (it is in the OS page cache).
- If the collector falls behind, the PULL queue fills, children get `zmq.Again`, and their
  records go to their own files. Nothing blocks.
- The launcher's own `LAUNCH_LOGGER` uses the same `JsonlSinkHandler`, connected to its own
  collector over the same endpoint. Hotkey, restart, and teardown threads therefore only ever
  perform a `NOBLOCK` send; they never touch the file. The collector binds before
  `LAUNCH_LOGGER` is built and before any server is spawned.

### `RotatingJsonlWriter`

Backs both the unified file and each child's fallback file.

- Counts records written. At 300,000 it closes the live file, renames it to
  `<stem>_<YYYYmmddTHHMMSS>.jsonl`, opens a fresh live file, and puts the renamed path on a
  queue. The next record is written at once; it never waits for compression.
- A compressor thread gzips each queued file to `.jsonl.gz`. It deletes the plain copy 10 s
  after the gzip finishes, so a live viewer can finish reading it (§4).
- At startup, any rotated plain `<stem>_*.jsonl` left behind (a crash mid-compress) is queued.
- Retention: rotated `.jsonl.gz` files older than 90 days are deleted at startup and after each
  rotation. This matches today's `backupCount=90` daily files.
- A write `OSError` in the collector is reported to stderr and the record is dropped. It never
  raises into another thread.

### Teardown

- The collector stops last, after the server shutdown sweep, so shutdown records land. It
  drains for up to 2 s, closes the file, and waits for the compressor queue to empty.
- CTRL-d (detach): the collector closes with no final rotation. Children fall back to their own
  files until a `--reconnect` launcher binds the endpoint again.

### Removed

The stale `.txt` log-zipping blocks in `launch.py` (`main`, after `LAUNCH_LOGGER` is built) and
`helao/helpers/helao_dirs.py` no longer match any file the logger writes. Both are deleted.

## §3 Migration, failure modes, tests

### Migration

- **`LoggingPort` / `LegacyLoggingAdapter`**: the contract path becomes
  `<log_root>/<server_key>.jsonl` (the fallback file). The F3 rule is unchanged: a configured
  root never falls back to a temp directory. A temp directory remains only for a bare
  `make_logger()` with no `log_dir`, as today.
- **Reflex backend and Bokeh processes** use `make_logger` and inherit the env, so they join the
  unified log with no change of their own.
- **Readers of `<key>.log`** switch to `.jsonl` or to the unified file:
  `helao/hexagon/tests/test_behavior_hexagon.py`, the golden-capture smoke stubs, `harness`
  capture tests, and smoke checks in private deployments that read `LOGS/ORCH.log`.
  `helao/core/tests/unit_test_logging.py` and `test_gzip_rotator_fallback.py` are rewritten for
  the new writer. Private-deployment code that references the old handler is checked during
  planning.
- **`read_logs(log_dir, server=None) -> DataFrame`** in `helao_logging.py`: reads the live
  files and rotated `.gz` files, concatenates, drops duplicates on `(server, pid, seq)`, filters
  by server, and sorts by `ts`. One helper,
  so tests and pandas consumers do not each re-implement the glob and merge.
- **Docs**: the root `CLAUDE.md` mentions of `LOGS/<server_key>.log`, and the `orch_effects.py`
  and `logging_adapter.py` docstrings.

### Failure modes

| Event | Behaviour |
|---|---|
| Launcher dies or detaches | The next send raises `Again`; records go to the child's own file, after the recent-records buffer is replayed there; a marker is sent on re-attach. Records are lost only if more than 2,000 were in flight. Replayed records may duplicate unified-file records; readers drop them on `(server, pid, seq)`. |
| Collector behind | Children spill to their own files; no caller blocks. |
| Collector disk error | stderr report, record dropped, no raise. |
| `log_port` already bound | Launch aborts before spawning. |
| Child fallback `OSError` | Today's redirect to a temp directory, only when no root is configured; otherwise the record is reported through `handleError`, which must not recurse into logging. |

### Tests

Unit tests, under `run_tests.py`:

- The schema round-trips through `pd.read_json(lines=True)`, with `exc` present only with a
  traceback.
- Rotation at an injected small N. The live file reopens before compression finishes.
  Compression runs on a separate thread. A leftover plain file is compressed at startup.
  The 90-day retention.
- Dedup behaves the same on both sinks.
- Sequence dedup: `A A A` (p = 1) and `A B C` x 20 (p = 3) collapse to one cycle plus a summary
  with the right `repeat_count` and `repeat_period`. A cycle broken mid-way writes the summary
  and then the held-back partial cycle. Two records with the same message but different
  exceptions are not collapsed. The 10 s interval yields periodic summaries.
- With a real in-process PULL that is bound, then unbound, then rebound: `Again` sends records
  to the fallback file, and re-attaching emits the marker with the right count.
- Replay: send records to a PULL that stops reading and then closes. Every record is present
  in the union of the unified and fallback files once duplicates are dropped by `read_logs`.
- Non-blocking: with the collector stopped reading, 10,000 `logger.info` calls finish without
  stalling, and the overflow is in the fallback file.
- Each fallback and rotation test gets a mutation check (break the logic and see it fail).

Integration: launch `goldenreflex` (simulated). Check that the unified file holds records from
every server key. CTRL-d, then `--reconnect`: check the fallback files and the marker.

## §4 Live log page (Reflex `/logs`)

### Shared logic: `helao/ui/shared/log_tail.py`

The logic lives in the shared layer so that a Bokeh front end can be added later without a
fork.

- `tail_init(log_dir, n=2000)`: the newest `n` records across every live `*.jsonl` in the
  directory (the unified file and any fallback files), read backwards from the end of each.
  Returns the records and one cursor per file (path, inode, offset).
- `tail_poll(cursors)`: reads only the bytes appended since each cursor, at most 2 MiB per file
  per tick, and splits on complete lines (a partial final line waits for the next tick).
  A changed inode, or a size below the cursor, means the file rotated. The poll then finds the
  rotated plain `<stem>_*.jsonl` with the cursor's old inode, reads it to the end from the
  cursor, and moves on to the new live file from offset 0. The writer keeps that plain copy
  for 10 s after its gzip finishes (§2), which covers a 1 s poll. If the copy is already gone,
  the poll emits one WARNING row saying records may be missing.
- Filtering by server set, minimum level, and substring; records merge by `ts`.

### Page: `helao/ui/reflex/logs.py`, route `/logs`

- `LogsState` holds the cursors and the newest 2,000 rows as `list[list[str]]`. `rx.foreach`
  needs the element annotation, or the frontend build fails.
- Controls: a server multi-select (filled from the server keys seen), a level floor, a text
  search, and a pause toggle. The table auto-scrolls unless paused. Pause freezes the display
  only; polling continues, so the viewer never misses the window during which a rotated file's
  plain copy is still readable.
- Rows are deduplicated on `(server, pid, seq)`, since a replay can write a record twice.
- The message column is monospace. Level colours come from `helao/ui/shared/palette.py`.
- It ticks from an `rx.moment(interval=1000)` in the page, never from a background loop, so a
  closed tab stops polling.
- The `LOGS` directory is resolved from the config root as an absolute path: the Reflex process
  runs from `_app/`, not the repo root.

### Tests

- `log_tail` unit tests: appends, a partial last line, rotation reset, the 2 MiB per-tick cap,
  filters, and a merge across the unified and fallback files.
- A headless Playwright check of `/logs` on `goldenreflex`: rows appear and the filters narrow
  them.

## Out of scope

- Shipping logs to an external ingest service.
- Changing the console format.
