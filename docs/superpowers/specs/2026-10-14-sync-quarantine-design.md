# Sync quarantine for records that can never sync

Status: design approved in conversation 2026-10-14; this spec awaits review.
Origin: `2026-08-14-legacy-separation-program-design.md` §6, "A quarantine state for records
that can never sync", deferred past the programme; the programme completed with B7c on
2026-10-14. Also named as deferred in `2026-09-28-finish-hooks-design.md` (out-of-scope list).

## 1. Problem

A record whose sync fails is retried forever, and the only trace is a log line.

- An exception that escapes `SyncDriver.sync_yml` is caught by the `syncer` worker
  (`helao/core/drivers/data/sync_driver.py:1488`), logged, and dropped.
- A blocking post-finish hook that fails marks itself `state: failed` in the `.prg`, and
  `sync_yml` returns False (`sync_driver.py:1780-1785`).

Either way the startup sweep (`sync_server.py:sweep_pending`, which calls `finish_pending`)
re-enqueues the record at every SYNC start, and it fails the same way again. The 2026-08-15 case
(three records failing every startup since July) surfaced only because an operator read the logs.

§6's constraint still holds: **the sweep cannot tell "will never succeed" from "was
interrupted"**, so quarantine must not strand work that a later pass would complete.

## 2. Decisions

| # | Decision |
|---|---|
| Q1 | Goal is visibility **and** stopping retries: a quarantined record is skipped by every automatic re-queue until an operator re-queues it. |
| Q2 | Both failure channels count as a strike: an exception escaping `sync_yml`, and a pass where the post-finish chain returns not-synced. |
| Q3 | Quarantine requires `strikes >= N` **and** `now - first_failed >= window`. An S3/API outage shorter than the window never quarantines, however many strikes it adds. |
| Q4 | Defaults `N = 5`, `window = 24 h`, as SYNC server params `quarantine_strikes` and `quarantine_hours`. `quarantine_strikes: 0` disables quarantine (strikes are still recorded). |
| Q5 | State lives in the record's `.prg` (source of truth). The SYNC journal gets a `quarantined` line as an index for listing. |
| Q6 | Surface: one `LOGGER.alert` (email) when a record enters quarantine; `/tasks` gains a `quarantined` list; `POST /finish_yml` on a quarantined record clears it and re-queues it. No new routes and no route-signature changes, so the frozen `hte` `sync_server` checklist is untouched. |
| Q7 | Strikes need not be consecutive and are never reset by a partial success. The age floor carries "has been failing for a while"; a record that syncs is complete and its block is moot. **Amended 2026-10-14 (final review):** failures less than `QUARANTINE_STRIKE_GAP` (1 h) after the last counted strike do not add a strike, though they still update `last_error`. A parent's re-walk retries a failing child several times in one burst; without the gap that burst alone spent the whole budget, so "N strikes" would not mean N separate failures. |

Rejected alternatives:
- A `RUNS_FAILED` tree (§6's first idea). Records no longer move between trees under the
  2026-09-25 runs layout; a tree move would reintroduce exactly the copying that layout removed.
- Journal-only state. The journal is an index, not the source of truth (`run_state.py`
  docstring); a corrupt journal is rebuilt from the run tree, and the state would be lost.
- In-memory strike counts. They reset at every restart, so they count restarts, not failures.
- Dedicated `/list_quarantined` / `/requeue` routes or a Reflex panel. More visible, but they
  require re-freezing the checklist; the alert plus `/tasks` covers visibility.

## 3. The `.prg` block

```yaml
quarantine:
  strikes: 5                 # int, incremented once per failed pass >= 1 h after the last strike
  first_failed: 2026-10-14T09:12:03   # set on the first strike, never moved
  last_failed: 2026-10-15T10:40:51    # time of the last *counted* strike
  quarantined_at: 2026-10-15T10:40:51  # null until the rule in Q3 fires
  last_error: "RuntimeError: Failed to upload ..."   # every failure; truncated to 500 chars
```

`quarantined_at` is written before `last_error`, and the flat-text reader
(`run_state._prg_is_quarantined`) matches only the two-space-indented key. A long `last_error`
folds onto continuation lines indented further, and its text may contain the same key.

Absent block = no failures recorded. Timestamps use the same `isoformat(timespec="seconds")`
form as the hook states in `helao/core/hooks/postfinish.py`. `last_error` is truncated so a
traceback-sized message cannot bloat the sidecar.

## 4. Code units

All of `Progress` and `SyncDriver` lie inside the verbatim region pinned by
`helao/hexagon/tests/test_native_sync_pins.py` (sentinel-bounded, `sync_fixtures.py`). Every
edit below is therefore made in `helao/core/drivers/data/sync_driver.py` and copied
byte-identically into `helao/hexagon/adapters/native/sync_driver.py`. The pin test fails if the
two drift. The region must stay import-free (`assert_region_holds_no_imports`), so any new
import goes in the import block above it, in both files.

### 4.1 `quarantine_due(block, n, hours, now) -> bool`

Module-level pure function. True when `n > 0`, `block["strikes"] >= n`, and
`now - first_failed >= timedelta(hours=hours)`. `now` is a parameter so tests need no clock
patching. This is the only place the rule in Q3 is written.

### 4.2 `Progress` additions

- `quarantine` property: the block or `None`.
- `is_quarantined` property: `quarantine` is not `None` and `quarantined_at` is set.
- `add_strike(error: str, n: int, hours: float, now: datetime) -> bool`: increments the block
  when at least `QUARANTINE_STRIKE_GAP` has passed since `last_failed` (Q7 amendment), sets
  `first_failed` on the first strike, updates `last_failed` on a counted strike and `last_error`
  always, sets
  `quarantined_at` when `quarantine_due` first becomes true, writes the `.prg`, and returns True
  **only on the strike that enters quarantine**. That return value is what makes the alert fire
  once.
- `clear_quarantine()`: deletes the block and writes the `.prg`.

### 4.3 `SyncDriver` changes

- `__init__`: read `quarantine_strikes` (default 5) and `quarantine_hours` (default 24) from
  `config_dict`.
- `_strike(yml_path, error)`: loads the `Progress`, calls `add_strike`, and on True raises one
  `LOGGER.alert` naming the record path, strike count, first/last failure, and `last_error`, then
  appends a `quarantined` journal line via `_journal`. A failure inside `_strike` itself is logged
  and swallowed: recording a strike must never turn a failed pass into a crashed worker.
- `syncer` worker `except` (line 1488): after logging, call `_strike(yml_path, repr(exc))`.
- `sync_yml`, the `if not synced:` branch (line 1780): call `_strike` with the error text of the
  first blocking hook whose state is `failed` in `prog.dict["hooks"]`.
A pass adds at most one strike. A hook that raises is caught inside `run_postfinish_chain` and
surfaces only as `synced = False` (channel 2), so it never also reaches the worker's `except`.

- `enqueue_yml`: before the duplicate checks, if the sibling `.prg` reports `is_quarantined`, log
  one INFO line and return without enqueueing. Every automatic path routes through here: the
  startup sweep and `finish_pending` (line 2382), parent re-walks (1746, 1755, 1816), and the
  sync_yml re-queue (1656).
- `quarantined()`: returns the journal's working-set entries in state `quarantined`, each with
  path, `strikes`, `last_error`, and `quarantined_at` read from the `.prg`.

The other session's fix for interrupted actions (`fix/reconcile-interrupted-actions`) does not
interact: a parent stalled by a stale `active` child returns False before the post-finish chain
runs, which is neither failure channel, so it never collects a strike.

### 4.4 `helao/helpers/run_state.py`

- New state constant `QUARANTINED = "quarantined"`, exported. It is not `done`, so the record
  stays in the working set and survives compaction with no change to compaction.
- `rebuild_from_tree`: when a record's `.prg` carries a block with `quarantined_at` set, emit
  `quarantined` instead of `unsynced`, so a rebuilt journal still lists it.

### 4.5 `helao/deploy/hte/servers/action/sync_server.py`

- `/finish_yml`: before `enqueue_yml`, if the record's `.prg` is quarantined, call
  `clear_quarantine()` and log the operator re-queue at INFO. Signature unchanged. The record's
  next failure starts a fresh strike count and a fresh window.
- `/tasks`: add `"quarantined": app.driver.quarantined()` to the returned dict. The response is an
  untyped dict, so the checklist's pinned schema is unchanged; the implementation confirms this by
  running the checklist gate.

## 5. Testing

Each test must fail when the code it covers is reverted (mutation check), per the
"plan-authored tests must be falsifiable" rule.

1. `quarantine_due`: below N; at N inside the window; at N past the window; `n = 0`.
2. Strikes below N: the record still enqueues.
3. N strikes inside the window (the outage case): not quarantined, no alert.
4. The strike that crosses both thresholds: quarantined, exactly one `LOGGER.alert`; a further
   strike raises no second alert.
5. A quarantined record is skipped by `finish_pending` (startup sweep path) and by a parent's
   child re-walk.
6. `/finish_yml` on a quarantined record clears the block and enqueues it.
7. Both channels add strikes: an exception raised out of `sync_yml`, and a blocking hook marked
   `failed`.
8. `quarantine_strikes: 0`: strikes recorded, never quarantined.
9. `rebuild_from_tree` reports a quarantined record as `quarantined`.
10. `/tasks` lists the record.
11. `test_native_sync_pins.py` passes (twin copy byte-identical) and the `hte` `sync_server`
    checklist gate passes unchanged.

## 6. Out of scope

- A Reflex panel or dedicated routes (Q6 alternative).
- Quarantine for analysis jobs: `STATES/ana_failed/` already covers them.
- Any change to post-finish hook retry semantics.
- Bulk re-queue after an outage longer than the window: an operator POSTs `/finish_yml` per
  record listed in `/tasks`. Add a bulk route only if this turns out to be common.

## 7. Addendum 2026-10-14: immediate quarantine of a permanently incomplete process group

The strike/age threshold (Q3) fits failures a retry may cure. One failure no retry can: a
finished experiment whose process group lists an `action_order` for which no action record
(`*-act.yml`, any state) exists under the experiment dir, e.g. an action lost at a crash. Its group
can never complete, and `s3_upload` would raise "did not sync after N tries" on every pass.

- Detection (`SyncDriver._incomplete_process_groups`, run in `sync_yml` after
  `reconcile_processes`, which is reached only once no child is active or unsynced): an unfinished
  group of a non-legacy experiment with at least one synced action, and a missing order that is
  neither synced nor on disk. A group with no synced action stays a phantom (dropped by
  `sync_process`). A record that exists but has not synced stays on ordinary retry.
- Action: `_strike(..., immediate=True)` sets `quarantined_at` now (strikes and age are bypassed;
  `quarantine_strikes: 0` still disables parking), `last_error` names the group index,
  `process_uuid` and the missing orders, and the usual single `LOGGER.alert` fires. The record is
  parked, never force-closed: nothing incomplete is presented as complete.
- Re-enqueue stops at the existing `enqueue_yml` gate. A parent whose every unsynced child is
  parked no longer re-queues itself either (otherwise the sequence burned its rank budget alone).
- Release is unchanged: `POST /finish_yml`. If the record is still absent the next pass parks it
  again, with a new alert.
- Likely causes: an operator skip or E-STOP partway through a process group (the orchestrator
  clears the remaining actions, the experiment finishes with a partial group and nothing to
  restore), or an action lost at a crash. The alert and `last_error` say so.
- Releasing via `/finish_yml` re-parks the record (with a new alert) while the action record is
  still absent; an explicit operator "write off" route is a planned follow-up, not built here.
- A group whose actions are ALL absent is still dropped as a phantom by `sync_process`
  (unchanged behaviour), so a fully lost group is not parked.
- With `quarantine_strikes: 0` the incomplete-group message is logged at ERROR each pass.
