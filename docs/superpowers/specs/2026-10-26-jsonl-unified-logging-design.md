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
7. A SHA-256 record for every output artefact when it is finalized and whenever it is rewritten
   afterwards, also kept in a ledger that is never deleted (§5).

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
{"ts": "2026-10-26T17:31:02.123456Z", "level": "INFO", "server": "PSTAT", "logger": "dispatcher",
 "pid": 4242, "seq": 1834, "func": "setup_action", "file": "action_host.py", "line": 512,
 "msg": "...", "exc": "Traceback (most recent call last): ..."}
```

- `ts`: UTC, ISO-8601, microseconds, `Z` suffix, with the cached NTP offset applied (as
  `NtpOffsetFormatter` does today). `pd.to_datetime` parses it to `datetime64[ns, UTC]`.
- `server`: the process's server key, set once with `helao_logging.set_server_key` (the
  launcher's own process is `launch`). Before a process has set one, the logger name stands in.
- `logger`: the record's logger name (`record.name`), e.g. `dispatcher` or `api`. Records written
  before this field existed have none; readers treat it as `""`.
- `seq`: a per-process counter, incremented for every record emitted. A gap shows loss.
- `exc`: present only when the record carries `exc_info`; the formatted traceback.
- `repeat_count`, `repeat_period`: present only on a dedup summary record (§1, recent-records
  buffer). The summary says the preceding `repeat_period`-record sequence was suppressed
  `repeat_count` more times.
- `event`, `kind`, `uuid`, `path`, `bytes`, `sha256`, `reason`: present only on artefact hash
  records (§5). `uuid` is omitted when the owner is unknown. The artefact `msg` is short,
  `"<event> <kind>"` (for example `artifact_final act`); the path and hash are fields only.
- `(server, logger, pid, seq, ts)` identifies a record. Replay (below) can write a record twice;
  readers drop duplicates on that key. `(pid, seq)` alone repeats when a PID is reused by a later
  process, and the loggers of one process share `server` but each count `seq` themselves.
- Serialized with `ensure_ascii=False`, UTF-8, `\n`-terminated.

### Handlers built by `make_logger`

`make_logger` keeps its signature, so its 40+ call sites are unchanged.

1. **Console**: the coloured text `StreamHandler`, unchanged. Under the launcher it still flows
   through `ConsoleMux` to the terminal.
2. **`JsonlSinkHandler`** (new; replaces `DedupTimedRotatingFileHandler`). Per record:
   1. **Level filter and dedup.** The sink has handler level 0 and its own `min_level` (the
      configured `log_level`): an ordinary record below it is dropped inside `emit`, but an
      artefact record (`event` starting `artifact_`) always passes, so a `log_level` of 30 or
      more cannot silently empty the ledger. The logger's level is `min(10, log_level)` so the
      records reach the handler. Then **dedup** against the recent-records buffer (below).
      Replaces today's consecutive-only dedup; `dedup_interval` keeps its meaning.
   2. **Format** the record to the §1 JSON bytes.
   3. **Send**: if `HELAO_LOG_ENDPOINT` is set, `send(NOBLOCK)` on a ZMQ PUSH socket connected
      to it with `IMMEDIATE=1`, `SNDHWM=1000`, `SNDBUF=65536` and `LINGER=500`. `IMMEDIATE` makes
      the send raise `zmq.Again` when no launcher is connected, as well as when the queue is
      full. Because a send before the ZMTP handshake completes also raises `Again`, the connect
      waits once (up to 1 s) for the handshake so startup records reach the launcher; if that
      wait times out the endpoint goes into `_NO_WAIT` and later connects in the process do not
      wait. The socket is opened and closed only under the handler lock.
   4. **Fallback**: on `zmq.Again`, or when there is no endpoint, write the record to this
      process's own file through a `RotatingJsonlWriter` (§2), at `<log_dir>/<name>.jsonl`.
      On the first `Again` after a run of successful sends, first **replay** the buffer
      (below) into that file.
   5. **Re-attach marker**: the first successful send after one or more fallback writes is
      preceded by a WARNING record: `"<N> records went to <fallback path>"`. The marker takes
      `seq + 1` and the counter advances only once the marker is sent, so a refused marker
      burns no `seq`.
   6. **Lazy reconnect and fork reset.** uvicorn's `dictConfig` runs `logging.shutdown` on every
      handler, which closes the socket; the next `emit` reconnects (1 s handshake wait, spilling
      to the file if that fails). In a forked child (`os.getpid()` differs) the handler drops
      the parent's socket and writers, resets the deduper and buffer, and reconnects with a
      200 ms wait.

### Recent-records buffer

Each `JsonlSinkHandler` keeps a `deque(maxlen=3000)` (`BUFFER_SIZE`) of the records it emitted.
Each entry is `[json_bytes, is_ledger, sent]`; the fingerprint lives in the deduper. About 650 KB
per process.
It serves two purposes.

**Repeated-sequence dedup.** Today's dedup compares each message with the previous one only,
so a loop logging `A B C A B C ...` (for example, a cascading exception) is never collapsed.

- Fingerprint: level, `pathname` (the full path, not the basename), line number, the rendered
  message, and the formatted traceback when present. (Today's comparison ignores the level and the traceback, so two different
  exceptions logged with the same message text collapse into one; this fixes that.)
- For each new record, check every period `p` from 1 to 16 for which the buffer's record `p`
  places back has the same fingerprint. A cycle of period `p` is confirmed when the last `p`
  records equal the `p` before them.
- While the cycle holds, each further record that continues it is held back rather than
  written, and each completed cycle is counted.
- When a record breaks the cycle, or `dedup_interval` (10 s) has passed since the cycle was
  confirmed, write one summary record (`msg`: `"previous <p>-message sequence repeated <M>
  times"`, with `repeat_count` and `repeat_period`). Then write the held-back records of the
  incomplete cycle; they are real records, not repeats. Summary `msg` formats: for `p = 1`,
  `"<message> [previous message repeated M times]"`; otherwise `"[previous <p>-message sequence
  repeated M times, ending: <last message>]"`; `time` is singular when `M = 1`. An elapsed interval opens a new
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
of them already reached the unified file; readers drop the duplicates on `(server, logger, pid, seq, ts)`. Replay writes all the entries for a
file with one `write_many` call per writer, not one open/append/close per record.
Records are lost only if more than 2,000 were in flight. The two high-water marks bound that at
`SNDHWM + RCVHWM = 2000`; `SNDBUF` and `RCVBUF` are 65536 (`SOCK_BUF`) on both ends, so the kernel
buffers add only a few tens of KB. The buffer holds 3,000 records, so everything in flight is in it.

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
  `port + 1`), skipping any port taken by a server, a server's RPC port (`port + 10000`) or a
  plate-aligner port (`params.bokeh_port`, else `port + 1000`; the rule is preflight's
  `_aligner_port`). An explicit `log_port` must be an int in 1..65535 clear of all of those.
- `resolve_log_port` checks `log_port` against the server, RPC and aligner ports before the
  collector binds. A bound port aborts the launch before any server is spawned, with a message
  that names the pid file and says to stop the earlier launcher or use `--force-relaunch`; the
  collector binds before the stale-group check, so a second launcher fails on the port.
- The launcher sets `HELAO_LOG_ENDPOINT` in its own environment, and every child inherits it
  (as with `PARENT_PID_ENV`); nothing passes it explicitly.
- A visualizer-only launcher (`extraopt` `liveonly` or `gpvis`) shares the config, and so the
  port, with the full launcher of its group. It starts no collector and sets no endpoint; its
  children write their own fallback files. `wants_collector(extraopt)` in `launch.py` decides.
- The endpoint is fixed by the config, so a `--reconnect` launcher binds the same port, and a
  detached group's children re-attach without a restart (ZMQ reconnects on its own).

### `LogCollector`

- One daemon thread owns the PULL socket (`RCVHWM=1000`, `RCVBUF=65536`, `LINGER=0`; each
  drain writes at most `HWM` records before re-checking the stop flag) and the unified file
  `<root>/LOGS/helao_<config_prefix>.jsonl`.
- Loop: poll with a 0.5 s timeout, check the stop flag, and append each received message's
  bytes unchanged. The child already serialized it; the launcher does no JSON work.
- Writers are `shared=True` everywhere (collector, fallback, ledger): each write opens the file
  in append mode and closes it, so a rename is never blocked (Windows) and never appended past.
  A killed launcher loses nothing it already wrote (it is in the OS page cache).
- If the collector falls behind, the PULL queue fills, children get `zmq.Again`, and their
  records go to their own files. Nothing blocks.
- The launcher's own `LAUNCH_LOGGER` uses the same `JsonlSinkHandler`, connected to its own
  collector over the same endpoint. Hotkey, restart, and teardown threads therefore only ever
  perform a `NOBLOCK` send; they never touch the file. The collector binds before
  `LAUNCH_LOGGER` is built and before any server is spawned.

### `RotatingJsonlWriter`

Backs both the unified file and each child's fallback file.

- Counts records written (`write_many` counts each line and cuts the batch at the threshold
  line). At 300,000 it renames the live file to `<stem>_<YYYYmmddTHHMMSS>.jsonl` (local time;
  `_<n>` is appended if that name or its `.gz` exists), the next write opens a fresh live file,
  and the renamed path goes on a queue. If the rename is refused (a reader holds the file on
  Windows) it keeps appending and retries every `ROTATE_RETRY = 1000` records. The next record is written at once; it never waits for compression.
- A compressor thread gzips each queued file through a temporary name
  (`<name>.jsonl.gz.<id>.tmp`, swept at startup when over an hour old) to `.jsonl.gz`. It deletes
  the plain copy 10 s after the gzip finishes, so a live viewer can finish reading it (§4);
  `close()` skips that grace.
- At startup, any rotated plain `<stem>_*.jsonl` left behind (a crash mid-compress) is queued.
- Retention: rotated `.jsonl.gz` log files older than 90 days are deleted at startup and after
  each rotation. The artefact ledger (§5) is never deleted. This matches today's `backupCount=90` daily files.
- A write `OSError` in the collector is reported to stderr and the record is dropped. It never
  raises into another thread. In a child, an unwritable `log_dir` goes to `handleError`.

### Teardown

- The collector stops last, after the server shutdown sweep, so shutdown records land. It
  drains for up to 2 s, closes the file, and waits for the compressor queue to empty.
- The launcher also registers `collector.stop` with `atexit` (it is idempotent), and the
  teardown stops it in a `finally` around the shutdown sweep, so the final records are not lost
  when the launcher exits another way.
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
  `helao/core/tests/unit_test_logging.py` is rewritten for the new writer, and the old gzip
  rotator test (`test_gzip_rotator_fallback.py`) is deleted. Private-deployment code that references the old handler is checked during
  planning.
- **`read_logs(log_dir, server=None, *, ledger=False) -> DataFrame`** (reads each file in
  chunks, trims a partial last line, skips unparseable lines with one stderr line per file, and
  skips a damaged `.gz` with a stderr line naming it) in
  `helao/helpers/log_jsonl.py`, re-exported by `helao_logging`: reads the live
  files and rotated `.gz` files, concatenates, drops duplicates on `(server, logger, pid, seq, ts)`, filters
  by server, and sorts by `ts`. One helper,
  so tests and pandas consumers do not each re-implement the glob and merge.
- **Docs**: the root `CLAUDE.md` mentions of `LOGS/<server_key>.log`, and the `orch_effects.py`
  and `logging_adapter.py` docstrings.

### Failure modes

| Event | Behaviour |
|---|---|
| Launcher dies or detaches | The next send raises `Again`; records go to the child's own file, after the recent-records buffer is replayed there; a marker is sent on re-attach. Records are lost only if more than 2,000 were in flight. Replayed records may duplicate unified-file records; readers drop them on `(server, logger, pid, seq, ts)`. |
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
  directory (the unified file and any fallback files; not `artifacts_*` ledgers or rotated
  files). It reads only the last 2 MiB (`CHUNK`) of each file. Returns the records and one
  cursor per file (path, inode, offset).
- `tail_poll(log_dir, cursors)`: reads only the bytes appended since each cursor, at most 2 MiB
  per file per tick, and splits on complete lines (a partial final line waits for the next tick).
  A changed inode, or a size below the cursor, means the file rotated. The poll then finds the
  rotated plain `<stem>_*.jsonl` with the cursor's old inode, reads it to the end from the
  cursor, and moves on to the new live file from offset 0. The writer keeps that plain copy
  for 10 s after its gzip finishes (§2), which covers a 1 s poll. If the copy is already gone,
  the poll emits one WARNING row saying records may be missing. The rotated name is matched
  with the exact rotated-name pattern (`<stem>_<YYYYmmddTHHMMSS>[_<n>].jsonl`), so `UI_*.jsonl`
  does not match `UI_backend.jsonl`. One call reads at most `MAX_ROTATED_TAIL = 32 * CHUNK`
  from a rotated file; a viewer further behind skips to the last such span and emits a note
  `"<N> bytes of <file> skipped (viewer fell behind)"`. A line over 2 MiB is skipped with a
  note.
- Filtering by server set, minimum level, and substring; records merge by `ts`.

### Page: `helao/ui/reflex/logs.py`, route `/logs`

- `LogsState` holds the cursors and the newest 2,000 rows as `list[list[str]]`. `rx.foreach`
  needs the element annotation, or the frontend build fails.
- Controls: a server checkbox per server key seen, a level floor (`DEBUG` to `ALERT`), a text
  search, and a pause toggle. Rows are newest-first, so the latest records stay at the top
  without scroll scripting. Pause freezes the display
  only (it shows a frozen snapshot; filter changes still apply to it); polling continues, so
  the viewer never misses the window during which a rotated file's plain copy is still
  readable.
- Rows are deduplicated on `(server, logger, pid, seq, ts)`, since a replay can write a record twice.
- The message column is monospace. Each row's text colour (a column of the row, `row[4]`) comes
  from `helao/ui/shared/palette.py` (`LOG_LEVEL_TEXT`). The table body is white
  (`palette.REFLEX_TABLE_HUES`) and the page uses the tint indigo-50.
- `start` and `tick` are background events: the file I/O runs in `asyncio.to_thread` between two
  `async with self` blocks, and a `_busy` flag drops a tick that arrives during a slow read.
  `_all` and `_cursors` are tuples (a list var costs ~30 ms per busy tick as a `MutableProxy`).
  The tick never logs.
- It ticks from an `rx.moment(interval=1000)` in the page, never from a background loop, so a
  closed tab stops polling.
- The `LOGS` directory is resolved from the config root as an absolute path: the Reflex process
  runs from `_app/`, not the repo root.

### Tests

- `log_tail` unit tests: appends, a partial last line, rotation reset, the 2 MiB per-tick cap,
  filters, and a merge across the unified and fallback files.
- A headless Playwright check of `/logs` on `goldenreflex`: rows appear and the filters narrow
  them.

## §5 Artefact SHA-256 records

Every output artefact is hashed when it is finalized and again whenever it is rewritten after
that. The hash goes to the log and to a ledger that is never deleted. Hashes are **not** added to
the records themselves.

### Which files

- Records: `-act.json`, `-exp.json`, `-seq.json`, `-prc.json`, `-ana.json` (and an existing
  `.yml` record, which stays YAML).
- Every entry in an action's `files[]`: data `.jsonl` plus its `.meta.json`, `.parquet`, and
  any other attached file.
- Every file in an analysis's `outputs`.
- An action's data files are hashed at a terminal status even when `save_act` is false (the
  act record is not saved). If the action has no `action_output_dir`, the data hash is skipped
  with a warning.
- Kinds are `act|exp|seq|prc|ana|data|output`, plus `zip` (a rewritten zip's digest) and
  `record` (a rewritten record whose kind `meta_kind` cannot name).

### `log_artifact_hashes(paths, *, kind, owner_uuid, event="artifact_final", reason=None, root=None, logger=None)`

- Lives in `helao/helpers/artifact_hash.py` (it imports `helao_logging`, so it cannot live
  inside it). It is async: each file is hashed with
  `hashlib.file_digest(f, "sha256")` inside `asyncio.to_thread`, so a large raw file never
  blocks the event loop. A sync twin, `log_artifact_hashes_sync`, serves standalone tools and
  other non-async callers. `root=` and `logger=` override the config root and the logger. Helpers:
  `record_uuid(doc)` picks the owning uuid, `root_for(path)` finds the helao root above a
  run-tree path (`RUNS`, `RUNS_*`, `DIAG`, `ANALYSES`), and `use_root_logger(path, name)` gives a
  CLI tool a logger writing to `<root>/LOGS`.
- For each file it logs one INFO record with these extra fields: `event`, `kind`
  (`act|exp|seq|prc|ana|data|output`), `uuid` (the owning record's uuid; omitted when unknown),
  `path` (relative to the root when under it, else absolute; always with forward slashes),
  `bytes`, `sha256`, and `reason` (rewrites only). The root is the `root=` argument, else the
  config root, else the root `use_root_logger` found, else `root_for(path)` per file, so a tool
  with no config logs the same `RUNS/...` string as a server and "latest record per `path`"
  matches. The `msg` is `"<event> <kind>"`.
- A missing or unreadable file logs a WARNING with `event: "artifact_hash_failed"` and the
  error. It never raises into the caller and never fails an action.
- **Awaited**, not fire-and-forget: the hash runs after the final write and before
  finalization returns, so a record is never mutated mid-hash, and the event's order in the
  log is meaningful. At SHA-NI speed (about 1-2 GB/s) a 100 MB data file adds about 0.1 s to
  an action's finish.
- Artefact records bypass the §1 sequence dedup (each is distinct anyway, by `path`).

### Finalization points (`event: "artifact_final"`)

| Artefact | Point |
|---|---|
| `-act.json` and `files[]` | `MetaWriter.write_act`, after any write whose `action_status` holds a terminal status (`finished`, `errored`, `aborted`, `skipped`, `estopped`, `retired`). The finalizer's final write is such a write; data files are already closed. |
| `-exp.json`, `-seq.json` | `MetaWriter.write_exp` / `write_seq`, on the same terminal-status rule. Every exp/seq record write goes through them. |
| `-prc.json` | Where the sync driver writes it (`sync_driver.py`, the process-record `write_meta`). |
| `-ana.json` and `outputs` | Analysis driver, after `write_model_json` and `publish_outputs` complete; `publish_outputs` hashes in a `finally`, so a failed upload still hashes what was written. |
| `-exp.json`, `-seq.json` of a micro-orchestrator | `MicroOrch` hashes its terminal exp and seq records. |

### Rewrites after finalization (`event: "artifact_rewritten"`)

Any code path that changes the bytes of a finalized artefact calls `log_artifact_hashes` with
`event="artifact_rewritten"` and a `reason` naming the path (for example `"set_run_use"`,
`"set_plate_id"`, `"process_repush"`, `"reconcile_interrupted"`). A `MetaWriter` write with a
terminal status logs `artifact_final` again; a caller that passes `reason=` logs
`artifact_rewritten`. Consumers take the latest record per `path`. Sites found in planning:

- `_record_rewrite.rewrite_dir`, `rewrite_zip` and `rewrite_processes` (used by `set_run_use`);
- the `-prc.json` re-push after a write-off (`sync_driver.py`, `reason="process_repush"`); the
  prc is hashed only when its bytes change;
- the interrupted-action reconcile (`ActionHost._reconcile_one`), which hashes the data files as
  rewritten;

`reset_sync` and `write_off` are not rewrite sites. `reset_sync` deletes `.prg`/`.lock`
sidecars and extracts a zip, and `write_off` writes the `.prg` and a ledger line. Neither
changes a record's bytes.
- the standalone repair tools under `helao/core/tests/` that rewrite records or zips
  (`set_plate_id`, `set_run_use`), through the sync twin;
- private-deployment tools that inject into or rewrite existing records, which are
  inventoried and changed in their own repos.

A move that does not change the bytes (such as `/retire` moving a run to `RUNS_SUPERSEDED`) is
not a rewrite and logs no hash.

**Gate test** (`helao/core/tests/test_artifact_hash_gate.py`): an AST sweep lists every call to the record writers (`write_meta`, the YAML
record dump, and the zip rewrite helpers) outside the finalization points. Each call must
either be followed by a `log_artifact_hashes` call in the same function or be on a short
allowlist with a reason (for example, the data `.meta.json` header rewritten on every
`write_file`, which is hashed at action finalization). A new rewrite site without a rehash
fails the sweep.

### Ledger

- `artifact_*` records go to the normal log **and** to a ledger:
  `<root>/LOGS/artifacts_<config_prefix>.jsonl` under the launcher, and
  `<root>/LOGS/artifacts_<name>.jsonl` in a child's fallback or a standalone tool.
- The child sends artefact records as a two-frame ZMQ message (`b"ledger"`, then the bytes).
  The collector writes such messages to both files; ordinary records are one frame. In
  fallback, the child's writer does the same with its own two files.
- The ledger uses the same `RotatingJsonlWriter` (300,000 records, gzip in the background) but
  is **excluded from the 90-day retention**. The retention sweep matches only the log stems,
  never `artifacts_*`. At about 300 bytes per file, the ledger grows slowly.
- Artefact records are included in the §1 replay, so a launcher death does not lose ledger
  entries. Duplicates are dropped on `(server, logger, pid, seq, ts)` as for the log.
- A tool run with no config root logs a WARNING that the ledger entry went to a temporary
  directory, unless it called `use_root_logger`, which puts its log and ledger in `<root>/LOGS`.
- A failed hash is a WARNING with `event: "artifact_hash_failed"`; it also goes to the ledger,
  so the ledger has failure rows.
- Rows are about 300 bytes: the `msg` is `"<event> <kind>"`, with the path and hash as fields
  only (an earlier repeat of both in `msg` made them about 726 bytes).
- An artefact record bypasses the sink's level filter (§1), so the ledger is complete at any
  `log_level`.
- Every `make_logger` call, including per-module loggers, gets its own sink; those loggers'
  names appear as `logger` in the unified file (`server` stays the process's server key).
  The sink's fallback file is still named after the logger.
- Calling `make_logger` again for a name replaces that logger's sink, console and queue handlers
  instead of stacking duplicates.

### Tests

- An action with two data files logs `artifact_final` for `-act.json` and for each data
  `.jsonl` and `.meta.json`. Each `sha256` equals `hashlib.sha256` of the file on disk, and
  each record is in both the log and the ledger.
- An analysis with two outputs logs hashes for `-ana.json` and both outputs.
- A rewrite through `_record_rewrite.rewrite_dir` logs `artifact_rewritten` with the new hash and
  the reason; a `rewrite_zip` logs the new zip's hash.
- A missing file logs `artifact_hash_failed` and the action still finishes.
- A ledger file older than 90 days survives the retention sweep; a log file of that age does
  not.
- The AST gate fails on a planted rewrite without a rehash.
- Mutation checks: delete one finalization call site, and delete the ledger tee; each must
  fail a test.

## Known limits / follow-ups

- Private-deployment rewrite tools are not hashed yet.
- Resolved: module logger names used to appear as servers in the unified file; they now go in
  `logger`, and `server` is the server key. The `/logs` server column reads `<server> · <logger>`
  when the two differ.
- Windows `TIME_WAIT` can delay the collector re-bind on a quick `--reconnect`.
- Co-hosted groups on one machine each derive a default `log_port` from their own ports; set
  `log_port` explicitly if two groups could pick the same one.

## Out of scope

- Shipping logs to an external ingest service.
- Changing the console format.
