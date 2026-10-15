# Sync write-off for an experiment whose process group can never complete

Date: 2026-10-15. Status: approved decisions, ready for planning.
Follows: `2026-10-14-sync-quarantine-design.md` (§7 addendum, "a write-off route is a
planned follow-up"). Page template: `2026-10-06-sequence-retire-page-design.md`.

## 1. Problem

Since the §7 addendum, an experiment with a part-synced process group that lists an
`action_order` with no action record anywhere under the experiment dir is parked at
first detection (`SyncDriver._incomplete_process_groups`, called from `sync_yml` after
`reconcile_processes`). The usual causes are an operator skip or E-STOP partway through
a group, or an action lost at a crash. Nothing can bring the record back. Today the only
operator action is `POST /finish_yml`, and while the record is still absent it re-parks
the experiment on the next pass. So the experiment, its sequence, and the sequence's
analyses never ship.

The operator needs one deliberate, audited action: "close this group with the actions
that exist, and record which orders are missing."

## 2. Decisions (binding)

| # | Decision |
|---|---|
| D1 | Marker: a new optional field on `ProcessModel`, `missing_action_orders: Optional[list[int]] = None`. It is absent on a normal process because `clean_dict` drops `None`, so normal `-prc.yml` and `process/{uuid}.json` output stays byte-identical. A flat list is enough: the who, when and why live in the `.prg` block and the ledger, and a list cannot drift from the record it describes. |
| D2 | Push the partial group with the marker set. Do not drop it. |
| D3 | Scope: only an incomplete-process-group quarantine. A strike-quarantined record is refused, with an error that names `/finish_yml`. The route recomputes the incomplete groups itself after `reconcile_processes` and never trusts `last_error`. |
| D4 | New route `POST /write_off(yml_path: str, reason: str, operator: str)` on `sync_server.py`, plus one `checklists/hte/_additions.json` entry. No re-freeze. |
| D5 | Opt-in `/quarantine` Reflex page (`params.sync_quarantine: true`). Reflex-free logic lives in `helao/ui/shared/sync_quarantine.py`. No Bokeh version. |
| D6 | Analyses run on written-off experiments. The marker is visible to them through the process JSON. |
| D7 | No marker on the experiment JSON in v1. There are no external strict-schema consumers of `process/*.json` (confirmed by the user). |
| D8 | The route is idempotent. It writes a `.prg` `write_off:` block, appends a line to the `STATES/sync_write_off.jsonl` ledger, raises one `LOGGER.alert`, and then enqueues. |
| D9 | Bulk "release all" is left out (YAGNI). The page releases one row at a time, which is the same thing the quarantine spec §6 already settled for curl. |

### Correction to the quarantine spec premise

Quarantine spec Q6 and §2 rejected new routes because they "require re-freezing the
checklist". That is not true. `helao/hexagon/tests/checklists/hte/_additions.json`
allowlists intentional new routes (`harness/endpoints.py` `filter_allowed_additions`),
and it already holds 12 entries. `harness/freeze.py` keeps the allowlist out of the
frozen record. One entry admits `/write_off`. The frozen `sync_server.json` is not
touched.

## 3. Data shapes

### 3.1 `.prg` blocks

```yaml
quarantine:            # existing; entering via immediate=True now also writes:
  immediate: true      # display hint only. The route never trusts it.
write_off:             # new; first decision wins, never rewritten
  at: 2026-10-15T12:00:00
  operator: jdoe
  reason: E-STOP mid-group, action 2 never ran
  groups: {1: [2]}     # pidx -> action_orders absent at write-off time
```

- Neither block may hold a two-space-indented `quarantined_at:` line besides the
  `quarantine` block's own key. `run_state._prg_is_quarantined` is a flat-text reader
  that returns on the first such line. `reason` and `operator` are whitespace-collapsed
  (`" ".join(s.split())`), so `yml_dumps` keeps them on one line and a folded
  continuation cannot carry a fake key. After collapsing, `reason` is capped at 500
  characters and `operator` at 80. Anything longer is refused, not truncated, so a
  pasted log cannot bloat the `.prg`, the ledger or the alert email.
- The hint is `immediate`, not `kind`. `SyncDriver.quarantined()` builds each `/tasks`
  entry with `entry.update(block)` on top of the record's own `kind`
  (`action`/`experiment`/`sequence`). A block key named `kind` would overwrite that
  field. The investigation's `kind: incomplete_group` suggestion would have caused this
  collision.
- `immediate: true` is written only on the strike that enters quarantine with
  `immediate=True`. Today that is only the F3 path. Records parked before this ships
  have no hint. Releasing one makes F3 re-park it on the next pass, and that pass
  writes the hint. Release is the migration path.
- `add_strike` rebuilds the block on every strike, so it carries `immediate: true`
  forward when the record is already quarantined. A later strike must not drop it.
- The page needs `immediate` to decide which rows get a Write off button, so it is
  kept. The server never relies on it.

### 3.2 Process output

For a written-off group,
`missing_action_orders = [i for i in write_off.groups[pidx] if i not in process_actions_done]`
is computed at push time. If a lost action later reappears, `reconcile_processes` and
the existing re-attempt reopen (`update_process`) fold it in, the list comes out empty,
and the field is `None`, so it is absent from the re-pushed process. The marker is set
on the dict passed to `ProcessModel.model_validate` and never stored in
`process_metas`. The `.prg` stays the source, and the field cannot go stale there.

**The backlog was already pushed once.** Before F3 existed, the forced S3 loop pushed a
partial group, wrote its `-prc.yml` and appended the group index to `process_s3`. Only
the un-forced API loop held it back. Those experiments then struck out and were parked
by strikes. The route accepts them, because it recomputes the incomplete groups and
`api_unf` still lists the index. The S3 loop, though, only iterates `s3_unfinished`, so
it would never re-push the group with the marker. The write-off therefore removes every
written-off group index from both `process_s3` and `process_api` in the same
`write_dict()` that adds the block. The forced loop then re-pushes the group and
overwrites `process/{uuid}.json` and the `-prc.yml` with the marked body. For an
experiment parked by F3 the removal is a no-op.

A partial group whose `min(group)` order is missing has no `process_timestamp`, because
only that action sets it. The field is `Optional`. This is accepted and documented, not
patched.

### 3.3 Ledger

`<root>/STATES/sync_write_off.jsonl`, append-only, one JSON object per call that changes
anything:

```json
{"ts": "...", "yml": "...", "action": "write_off|requeue", "operator": "...", "reason": "...", "groups": {"1": [2]}}
```

The ledger line is written by `SyncDriver._append_write_off_ledger(entry)`, before the
`.prg` block, and under a module-level `threading.Lock`. Write-offs of different
experiments run concurrently in threads against one file, and appends are not atomic
on Windows or CIFS. The retire ledger uses a lock for the same reason. If the append
raises `OSError`, the call returns `{"ok": False, "error": ...}` and never raises. A
raise would come back as an `RPCError`, the dispatcher would fall back to HTTP, and the
call would replay. A write-off whose ledger append fails writes no block. The
`reconcile_processes` refresh of `process_metas` may already have happened by then;
that refresh is idempotent bookkeeping that any sync pass also performs. With no
`states_root` (bare test drivers) the ledger is skipped, matching the `run_journal`
precedent. The `.prg` block and the alert remain.

## 4. Code units

All `sync_driver` edits are made byte-identically in `helao/core/drivers/data/sync_driver.py`
and `helao/hexagon/adapters/native/sync_driver.py`. `test_native_sync_pins.py` enforces
this through `test_verbatim_region`.

### 4.1 `ProcessModel` (`helao/core/models/process.py`)

Add `missing_action_orders: Optional[list[int]] = None` and a one-line docstring entry.

### 4.2 `Progress`

- `add_strike`: set `new_block["immediate"] = True` when `entered and immediate`, or
  when `already` and the old block has `immediate` true (carry it forward).
- New `written_off(pidx) -> list[int]`: the orders in `write_off.groups[pidx]` that are
  not in `process_actions_done`. It returns `[]` when there is no block.

### 4.3 `SyncDriver` gates

| Site (core line, verified 2026-10-15) | Change |
|---|---|
| `_incomplete_process_groups` L1453 | Drop orders returned by `prog.written_off(p)` from each `lacking` list before the phantom filter. |
| `sync_process` S3 loop, before `ProcessModel.model_validate(meta)` L2467 | Validate `{**meta, "missing_action_orders": exp_prog.written_off(pidx) or None}`. |
| `sync_process` API loop gate L2494 | Count an order as done if it is in `process_actions_done` or in `written_off(pidx)`. |

The non-forced S3 gate (L2385) is left alone. The experiment-level `s3_upload` hook
calls `sync_process(force=True)` (`s3_upload.py:217`), and no contributing action ships
after a write-off. Phantom and unrebuildable handling are unchanged.

### 4.4 `SyncDriver.write_off(yml_path, reason, operator) -> dict`

The method is async:

```python
async with AsyncExitStack() as stack:
    await self._acquire_hierarchy_locks(stack, yml_path)
    result = await asyncio.to_thread(self._write_off, yml_path, reason, operator)
# async tail runs here, after the locks are released
```

The async tail runs **outside** the locks, because `enqueue_yml` must not hold the
sequence lock.

**Refusals never create or write a `.prg`.** Steps 1-4 use only flat-text readers and
`yml_load`, and `Progress` is constructed only once the record is known to be a
quarantined experiment with a `.prg` already on disk.

Blocking half `_write_off`, in order. The first match returns:

1. Collapse whitespace in `reason` and `operator`. If either is empty or over its cap
   (500/80), return `{"ok": False, "error": ...}`.
2. The path must end in `-exp.yml`, exist, resolve under `helaodirs.root`, and have a
   `.prg` beside it (`prg.exists()`). Otherwise return an error.
3. If `_prg_is_complete(prg)` is true, return `{"ok": True, "status": "already synced"}`.
   This is a no-op.
4. `d = yml_load(prg, fast=True)`. If `d` has a `write_off` block:
   - if `_prg_is_quarantined(prg)` is true, refuse and name `/finish_yml`. A record
     parked after a write-off has a strike cause; any orders that are gone are
     subtracted, and `reset_sync` recreates the `.prg` without the block.
   - otherwise append a `requeue` ledger line and return
     `{"ok": True, "status": "requeued", "at": ..., "operator": ...}` from the existing
     block, which is left unchanged.
5. If `_prg_is_quarantined(prg)` is false, return an error: "not in sync quarantine".
6. `prog = self.reconcile_processes(Progress(yml_path))`, then
   `groups = self._incomplete_process_groups(prog)`. If `groups` is empty, return an
   error: "not an incomplete-process-group quarantine; fix the cause and POST
   /finish_yml".
7. Append a `write_off` ledger line; if the append fails, return `ok: False`. Then:
   - set `prog.dict["write_off"] = {at, operator, reason, groups}`;
   - pop `quarantine`;
   - remove each pidx in `groups` from `process_s3` and `process_api` (§3.2);
   - call `write_dict()` once.

   Return `{"ok": True, "status": "written off", "groups": groups}`.

Async tail, run only on `written off` or `requeued`:
- One `LOGGER.alert`, on `written off` only. It names the yml, the groups, the operator
  and the reason.
- Then `await self.enqueue_yml(yml_path, 1)`, which journals `unsynced`.

Refusals log at INFO. They never alert, and they never raise to the route. Anything
unexpected in `_write_off` is caught and returned as `ok: False`, with the traceback
logged. The method returns a 200 dict, not an HTTP error, for two reasons:
- `async_private_dispatcher` falls back to HTTP on an `RPCError`, a timeout, a
  `ZMQError` or an `OSError`, and it retries non-200 responses. A raised refusal would
  therefore run more than once.
- The page reads one shape.

Idempotency also covers transport replays. The RPC fast path is capped at 3 s
(`_RPC_PROBE_TIMEOUT`). If a write-off that takes longer (a sequence write lock, a long
reconcile) is applied and then replayed over HTTP, the replay hits step 4 and answers
`requeued`, with the original `at` and `operator`. `enqueue_yml` dedupes on `task_set`.
The page renders `requeued` as success: "already written off at <at> by <operator>;
re-queued".

**Races with other `.prg` writers.** Three writers do not take the hierarchy lock:
`release_quarantine` (`/finish_yml`), `/reset_sync`, and the `_strike` in `syncer`'s
`except` path. A concurrent `/finish_yml` could read the dict before step 7's write and
write it back after, which would lose the block while the ledger and alert say it was
written off. Here is how each case is settled:
- The page serializes Release and Write off behind one module-level lock per Reflex
  process (§4.7).
- A parked record is never running in `syncer`, so the `_strike` path cannot overlap a
  write-off of the same record.
- A hand-curled `/finish_yml` or `/reset_sync` racing a write-off is accepted. The
  failure is visible: F3 re-parks the record with a fresh alert, and the operator
  writes it off again.

### 4.5 Route

`sync_server.py`:

```python
@app.post("/write_off", tags=["private"])
async def write_off(yml_path: str, reason: str, operator: str) -> dict:
    return await app.driver.write_off(yml_path.strip('"').strip("'"), reason, operator)
```

In `_strike`'s immediate branch, in both twins, change the end of the alert text:

- Before: `"... releases it, but it is parked again while the record is still absent (a write-off route is planned)."`
- After: `"... releases it, but it is parked again while the record is still absent. POST /write_off records a write-off of the missing actions."`

The new text keeps the substring `write-off`, which
`test_sync_incomplete_process.py::test_alert_names_the_causes_and_the_repark` asserts.

`/tasks` (`running()`): run `app.driver.quarantined()` through `asyncio.to_thread`. It
replays the journal and reads one `.prg` per parked record, and the page now polls it.
Also correct the docstring's "a new route would break that gate" to name
`_additions.json`.

`_additions.json` entry:

```json
{"module": "sync_server.py", "path": "/write_off", "method": "post", "date": "2026-10-15",
 "why": "operator write-off of an experiment parked for a process group that can never complete (sync write-off spec)"}
```

The test-deployment `sim_db_server.py` mirror is not extended, because the harness does
not need it.

### 4.6 `helao/ui/shared/sync_quarantine.py` (Reflex-free)

- `sync_target(world_cfg) -> Optional[tuple[str, str, int]]`: `(key, host, port)` via
  `resolve_sync_server_key`. A `ValueError` (unmigrated `DB` key) or a missing
  host/port gives `None`.
- `async fetch(target) -> Optional[list[dict]]`: `/tasks` → `quarantined`. It returns
  `None` on any dispatcher error, non-`none` error code, or malformed body. **`None`
  means unknown, never empty.**
- `incomplete(entry) -> bool`: `entry.get("kind") == "experiment" and entry.get("immediate") is True`.
- `rows(entries) -> list[list[str]]`: `[yml, dir name, cause, quarantined_at, strikes, last_error[:200], "1"|""]`.
  The dir name is `Path(entry["path"]).name`.
- `is_armed(dir_name, confirm, reason, operator) -> bool`: `confirm.strip() == dir_name`,
  and `reason` and `operator` are non-blank.
- `async release(target, yml) -> tuple[Optional[bool], str]` calls `/finish_yml`.
  `async write_off(target, yml, reason, operator) -> tuple[Optional[bool], str]` calls
  `/write_off`. Both call `async_private_dispatcher` with `retries=1`; the default of 5
  would replay a mutating call. The message reports **the route's actual answer**:
  - `True` and the route's `status`, phrased for each case (`written off`; `requeued`
    as "already written off at <at> by <operator>; re-queued"; `already synced`).
  - `False` and the route's `error`.
  - `None` and the fixed text "sent, outcome unknown — refresh" when the dispatcher
    raised, returned a non-`none` error code, or returned a body without `ok`.

  A transport failure is never reported as success or as refusal. The only bound on
  the HTTP leg is connect time (the RPC leg is capped at 3 s), so the outcome of a slow
  call may be unknown.

The typed confirmation is the record **directory name**, not a parsed experiment name.
It is shown in the row, it contains the experiment name, and it needs no yml parse. This
is a deliberate narrowing of D5's "experiment name".

### 4.7 `helao/ui/reflex/sync_quarantine.py` + wiring

- `configure_quarantine(world_cfg, server_key)` is a copy of `configure_retire`'s
  guards. It enables only on literal `params.sync_quarantine is True` and a non-`None`
  `sync_target`. It is called from `build_app` before `add_page`.
- `QuarantineState(rx.State)` holds `rows: list[list[str]]`, `status: str`,
  `selected: str` (yml), `selected_dir: str`, `confirm`, `reason`, `operator`, `armed`,
  and `busy`. It acts on rows **by yml path**, never by index. Every handler re-checks
  `quarantine_enabled()`.
- `refresh(_tick)` is a background handler bound to the button (`refresh("")`) and to
  `rx.moment(interval=60000)`.
  - It skips while `busy`.
  - `fetch` returning `None` gives `status = "SYNC unreachable: quarantine state
    unknown"` and `rows = []`. The status text is what tells "unknown" apart from
    "nothing quarantined".
  - If the selected yml is no longer in the rows, it clears `selected`, `confirm` and
    `armed`.
- Rows:
  - A row whose `yml` is `None` (record dir without its yml) gets no action buttons.
  - Per-row Release goes to `release(yml)`.
  - Write off appears only on rows with `incomplete == "1"`. It selects the row, and the
    form's submit button is enabled only while `armed`.
- One module-level `asyncio.Lock` serializes Release **and** Write off per Reflex
  process (§4.4, races). The status line shows the message from §4.6 verbatim.
- In `app.py`: `/quarantine` goes in `SHELL_ROUTES`, a nav link, and `add_page`. It is
  not in `CREDENTIAL_ROUTES`, because it uses no API or S3.
- Palette: `TW["red-50"] = "#fef2f2"` (canonical Tailwind) and
  `REFLEX_PAGE_TINTS["/quarantine"] = "red-50"`. No unused `-50` shade exists in `TW`.
  Contrast rows, measured: slate-900 16.32, slate-600 6.93, slate-500 4.35. The last
  one is below 4.5, so `red-50` joins the slate-500 failing set, and that test becomes
  "five of the twelve". No border's worst tint changes.

## 5. Testing

Each test names the mutation that makes it fail. See the plan.

- Write-off of an F3-parked experiment: the experiment syncs, its `-prc.yml` for the
  partial group carries `missing_action_orders: [2]`, and the complete group's
  `-prc.yml` lacks the key. The complete group is re-pushed while the block exists.
- Write-off of a backlog experiment, one whose partial group was already pushed before
  F3: the group is re-pushed, and both the S3 body and the `-prc.yml` carry the marker.
- Refusals leave no `.prg` behind where there was none.
- The page reports `requeued` as success and a transport failure as "outcome unknown".
- The route forwards stripped arguments to the driver (`TestClient`).
- The `test_sync_postfinish_golden` golden passes unchanged. This proves byte-identity
  for normal output.
- A strike-quarantined record is refused with `/finish_yml` in the error, and the
  `.prg` is unchanged. A non-quarantined record is refused. Blank reason or operator is
  refused.
- Repeat calls: an already-synced record returns a no-op, and an unsynced record with a
  block returns `requeued` and keeps the block.
- F3 does not re-park after a write-off. The sequence is re-queued and syncs.
- Ledger lines are written, `OSError` on the ledger leaves the `.prg` untouched, and
  exactly one alert fires.
- Twin pin, route checklist gate, palette suite, Reflex route e2e, and offline shared
  tests all pass.

## 6. Out of scope

- Writing off strike-quarantined records, and skipping a failed hook.
- An experiment-JSON marker (D7), a bulk release (D9), and a Bokeh panel.
- Undoing a write-off after the S3 push. If the action reappears, the existing
  re-attempt path re-pushes the process without the marker.
- `reset_sync` on a written-off experiment recreates the `.prg` without the block, so
  F3 re-parks it and the operator writes it off again.
- Suppressing analyses for written-off experiments (D6). Analysis code can read
  `missing_action_orders`.

## 7. Review rulings (2026-10-15)

| Item | Resolution | Where |
|---|---|---|
| I1 | Write-off clears the group indexes from `process_s3`/`process_api`, so the backlog re-pushes with the marker. | §3.2, §4.4 step 7 |
| I2 | Exact alert text that keeps `write-off`. | §4.5 |
| M2 | Refusals never create or write a `.prg`. | §4.4 |
| M3 | The ledger has a named seam and a lock, and a failure returns `ok: False`. | §3.3 |
| M4 | The page lock covers Release and Write off; a curl race is accepted and visible. | §4.4 |
| M5 | `immediate` is kept and carried forward across strikes. | §3.1, §4.2 |
| M6 | Real lock signature; the tail runs outside the locks. | §4.4 |
| M7 | Old step 7 folded into step 4. | §4.4 |
| M8 | The page reports the route's real answer, and a transport failure as "outcome unknown". | §4.4, §4.6 |
| M9 | 60 s poll; `quarantined()` runs in a thread; `/tasks` docstring fixed. | §4.5, §4.7 |
| M10 | Rows with no yml get no buttons; refresh guards `busy` and stale selection. | §4.7 |
| M11 | `reason`/`operator` capped at 500/80. | §3.1 |
| M12-M14 | Test fixes and a route-level test. | plan |

Deferred:
- **M15**: the nav link shows even where the page is disabled. The page body then says
  it is disabled, the same as `/retire` without `retire: true`. Gate the link when a
  station asks.
- **M16**: removed from the plan.
