# Sync write-off implementation plan

Spec: `docs/superpowers/specs/2026-10-15-sync-write-off-design.md`. Read it first. This
plan does not restate the design. It gives the order, the files, the tests and the
gates.

Worktree: `/mnt/STORAGE/repos/helao/fu-wo`, branch `feat/sync-write-off` (base `ed0a367f`).

## Global constraints

- **Twins.** Make every edit to `helao/core/drivers/data/sync_driver.py` byte-identically
  in `helao/hexagon/adapters/native/sync_driver.py`. The code is the same, with a +3 line
  offset inside the pinned region. `helao/hexagon/tests/test_native_sync_pins.py` must
  pass after every task that touches either file.
- **Black and the twins.** The core twin is black-formatted. The native twin is
  black-excluded: never run `black` on it. New core code must already be black-stable,
  so T1 and T2 verify with `black --check helao/core/drivers/data/sync_driver.py`. If the
  check fails, run `black` on the core twin, copy the reformatted lines into the native
  twin, and re-run `test_native_sync_pins.py`.
  Never run `black` on `helao/core/tests/fixtures/sweeper_calibration/`.
- **No outward actions.** No `git add`, `commit`, `push` or `stash`. No writes outside
  the worktree, except scratch files under `/tmp/claude-1000/`. Use
  `git -C /mnt/STORAGE/repos/helao/fu-wo` on every git call.
- **Running.** The worktree's filesystem is noexec: run `python x.py`, never `./x.py`.
  `conda run -n helao` drops stdin, so put scripts in files. Run each test file on its
  own, the way `run_tests.py` does:
  `PYTHONPATH=/mnt/STORAGE/repos/helao/fu-wo conda run -n helao python -m pytest <file> -q`
- **Public repo.** Never name a private deployment or a station hostname in any
  tracked file.
- **Palette.** No colour literal outside `helao/ui/shared/palette.py`. Muted Reflex text
  is `slate-600`, never `text-slate-500`.
- **Reflex.**
  - The state class must be importable at module load, and `configure_*` runs before
    `add_page`.
  - Add the route to `SHELL_ROUTES`.
  - Annotate `rx.foreach` vars (`list[list[str]]`).
  - Act on rows by yml path, never by row index.
  - No server-side polling loop. Use `rx.moment`.
  - A handler bound to both a button and the moment gets the tick arg explicitly
    (`State.refresh("")`).
- **Falsifiable tests.** Each new test below names the mutation that must turn it red.
  Apply that mutation once, see the test go red, revert, and report it.
- **Escalate, don't choose.** If the spec does not settle a decision, stop the task and
  report it. This applies especially to anything that changes the bytes of normal
  process or experiment output.

## T1: marker field, Progress helpers, sync gates (both twins)

Files: `helao/core/models/process.py`, both `sync_driver.py` twins, new
`helao/core/tests/test_sync_write_off.py`, `helao/hexagon/tests/test_native_sync_pins.py`.

Write the tests first in `test_sync_write_off.py`:
- Parametrize over `[legacy_mod, native_mod]`.
- Reuse `helao.hexagon.tests.sync_fixtures`.
- Use the `_lost_order_2` shape from `test_sync_incomplete_process.py`: groups
  `{0:[0,1], 1:[2,3]}`, with order 2 lost.

1. `test_process_model_carries_missing_orders`: `ProcessModel.model_validate({...,
   "missing_action_orders": [2]}).clean_dict()` holds `[2]`. Without the key, the dict
   has no `missing_action_orders`.
   Mutation: do not add the field. Pydantic's `extra="ignore"` then drops `[2]`, and
   the test goes red. `= []` is not a valid mutation, because `clean_dict` drops `[]`
   too.
2. `test_immediate_hint_is_written_and_carried`:
   - `add_strike(..., immediate=True)` entering quarantine sets `immediate: True`.
   - A later `add_strike` on the parked record keeps it.
   - A block that entered quarantine through the strike threshold has no `immediate`
     key.

   Mutations:
   - Delete the assignment: red.
   - Drop the carry-forward: red on the second assertion.
   - Set the key unconditionally: red on the third.
3. `test_written_off_round_trips_and_lists_only_absent_orders`:
   - Set `write_off.groups {1:[2]}`, call `write_dict()`, then build a **fresh**
     `Progress`. Expect `written_off(1) == [2]` and `written_off(0) == []`.
   - Record order 2 in `process_actions_done`. Expect `written_off(1) == []`.

   Mutations:
   - Return the raw block list: red.
   - Look up `str(pidx)`: red.
4. `test_write_off_block_stops_f3_and_marks_only_its_group`:
   - After F3 parks the experiment, hand-write the block: set `write_off`, pop
     `quarantine`, and remove pidx **0 and 1** from `process_s3` and `process_api`.
     Removing 0 is what forces group 0 to be re-pushed while the block exists.
   - Then `sync_yml(exp)` returns a dict.
   - The group-1 `-prc.yml` has `missing_action_orders: [2]`. The group-0 `-prc.yml`
     and group 0's captured `to_s3` body have no such key.
   - The `.prg` has `synced: true`.

   Mutations:
   - Skip the subtraction in `_incomplete_process_groups`: the record is re-parked, red.
   - Skip the API gate change: "did not sync after N tries", red.
   - Drop the marker: red.
   - Set the marker from all groups (`sum(groups.values(), [])`) for every pidx: red on
     group 0.

Implementation follows spec §4.1-4.3, in both twins:
- the `ProcessModel` field;
- the `Progress.add_strike` hint, with carry-forward;
- `Progress.written_off(pidx)`;
- the `_incomplete_process_groups` subtraction;
- in the S3 loop,
  `model_validate({**meta, "missing_action_orders": exp_prog.written_off(pidx) or None})`;
- an API gate that counts `written_off`.

Add `"written_off"` to `PROGRESS` in `test_native_sync_pins.py`.

Verify that all of these pass:
```
helao/core/tests/test_sync_write_off.py
helao/core/tests/test_sync_incomplete_process.py
helao/core/tests/test_sync_quarantine.py
helao/core/tests/test_sync_postfinish_golden.py
helao/core/tests/test_prc_colocation.py
helao/core/tests/unit_test_sync_process_recovery.py
helao/hexagon/tests/test_native_sync_pins.py
helao/hexagon/tests/test_native_sync_process_recovery.py
```
plus `black --check helao/core/drivers/data/sync_driver.py`.

`test_sync_postfinish_golden.py` must stay unchanged and green. That is the proof that
normal output is byte-identical.

## T2: `SyncDriver.write_off`, route, allowlist, `/tasks` thread

Files: both twins, `helao/deploy/hte/servers/action/sync_server.py`,
`helao/hexagon/tests/checklists/hte/_additions.json`, `test_sync_write_off.py`,
`helao/deploy/hte/tests/test_sync_server_recovery.py`, `test_native_sync_pins.py`.

Write the tests first, using a driver with `states_root` (as `_driver_with_journal` in
`test_sync_quarantine.py`) and capturing `LOGGER.alert`. Build the sequence the way
`test_no_burst_from_the_sequence_either` does (`test_sync_incomplete_process.py:89-90`),
because `make_exp_tree` creates no `-seq.yml`.

1. `test_write_off_ships_experiment_and_sequence`:
   - On an F3-parked exp, `await drv.write_off(exp, "estop", "op")` returns `ok`,
     `written off` and `groups {1:[2]}`. Then `drain`.
   - The exp `.prg` is synced and holds the `write_off` block (`at`, `operator`,
     `reason`, `groups`).
   - The sequence is re-queued and synced.
   - `drv.quarantined()` no longer lists the exp.
   - Exactly one alert fires, naming the yml, `op` and `estop`.

   Mutations:
   - Skip `enqueue_yml`: red.
   - Drop `pop("quarantine")`: enqueue is skipped, red.
2. `test_write_off_repushes_a_backlog_group_with_the_marker`:
   - Before parking, pre-seed `process_s3=[0,1]` and write a group-1 `-prc.yml` without
     the marker. This simulates a pre-F3 forced push.
   - Park the exp with a threshold strike, write it off, then drain.
   - The group-1 `-prc.yml` and the captured S3 body for its uuid both carry
     `missing_action_orders: [2]`.

   Mutation: skip removing the pidx from `process_s3`/`process_api`: red.
3. `test_write_off_refuses_strike_quarantine`:
   - Quarantine a complete-group exp through threshold strikes.
   - Expect `ok False`, and the error contains `/finish_yml`.
   - The `.prg` bytes are unchanged, and no ledger file exists.

   Mutation: trust the presence of `quarantine` instead of recomputing: red.
4. `test_write_off_refuses_an_incomplete_but_unparked_exp`:
   - Use the `_lost_order_2` shape with `drv.quarantine_strikes = 0`, so F3 logs but does
     not park.
   - Expect a refusal whose error contains "not in sync quarantine". No block is
     written.

   Mutation: delete step 5. The exp is then written off: red.
5. `test_write_off_refuses_bad_args_without_touching_disk`:
   - Each of these is refused: reason `"  "`, operator `""`, reason over 500 characters,
     a non-`-exp.yml` path, a path outside `root`.
   - An `-exp.yml` with no `.prg` is refused, and still has no `.prg` afterwards.

   Mutations:
   - Construct `Progress` before the `prg.exists()` check: red.
   - Drop the cap: red.
6. `test_write_off_is_idempotent`:
   - A second call while unsynced returns `requeued` with the first call's `at` and
     `operator`. The block bytes are unchanged, the ledger gains a `requeue` line, and no
     second alert fires.
   - A call after sync returns `already synced` and adds no ledger line.

   Mutation: rewrite the block on repeat: red.
7. `test_ledger_failure_writes_no_block`:
   - Monkeypatch `drv._append_write_off_ledger` to raise `OSError`.
   - The call returns `ok False` and does not raise. The `.prg` is still quarantined,
     with no block.

   Mutation: write the `.prg` before the ledger: red.
8. `test_reason_and_operator_are_one_line`:
   - Use reason `"a\n  quarantined_at: 2026"` and operator `" o\tp "`.
   - Expect stored `reason == "a quarantined_at: 2026"` and `operator == "o p"`.
   - Expect `_prg_is_quarantined` to be False on the written `.prg`.

   Mutation: remove the whitespace collapsing. The equality asserts go red.
9. Route test, in `test_sync_server_recovery.py`: a `TestClient` POST to `/write_off`
   with `yml_path='"<p>"'` awaits a stub `driver.write_off` with the stripped path,
   `reason` and `operator`, and returns its dict.

   Mutation: drop the strip: red.

Implementation follows spec §4.4-4.5:
- the blocking `_write_off`;
- `_append_write_off_ledger`, behind a module `threading.Lock`, writing
  `Path(states_root) / "sync_write_off.jsonl"` and skipped when `states_root` is falsy;
- the async `write_off`, using `AsyncExitStack` plus
  `_acquire_hierarchy_locks(stack, yml_path)`, with the tail outside the locks;
- the exact alert text from §4.5;
- the route;
- `running()` calls `quarantined()` through `asyncio.to_thread`, and its docstring is
  fixed;
- the `_additions.json` entry.

Add `"write_off"`, `"_write_off"` and `"_append_write_off_ledger"` to `SYNC_DRIVER_CORE`
in the pin test.

Verify: the T1 list, plus `helao/hexagon/tests/test_hte_route_checklist.py`,
`helao/deploy/hte/tests/test_sync_server_recovery.py` and
`black --check helao/core/drivers/data/sync_driver.py`.

The alert test `test_sync_incomplete_process.py::test_alert_names_the_causes_and_the_repark`
must stay green without being edited, because the new text keeps `write-off`.

Mutations for the gate:
- Delete the `_additions.json` entry: `test_hte_route_checklist.py` goes red.
- Delete the route but keep the entry: red, because the addition is now stale.

## T3: `helao/ui/shared/sync_quarantine.py` (offline)

Files: new `helao/ui/shared/sync_quarantine.py`, new
`helao/core/tests/test_sync_quarantine_page_logic.py`.

Write the tests first. Fake `async_private_dispatcher` by monkeypatching the module
attribute. No network.

1. `test_sync_target_resolves_sync_key`: a world with a `SYNC` host and port gives the
   tuple. No syncer gives `None`. A retired `DB`-only world gives `None` and does not
   raise.
   Mutation: let the `ValueError` escape: red.
2. `test_fetch_unreachable_is_unknown_not_empty`: the dispatcher raising, returning a
   non-`none` error code, or returning a body without `quarantined` all give `None`. A
   healthy body with `[]` gives `[]`.
   Mutation: return `[]` on error: red.
3. `test_incomplete_needs_experiment_and_hint`: `immediate True` with `kind experiment`
   gives True. Missing either gives False.
   Mutation: ignore `kind`: red.
4. `test_rows_shape_and_truncation`: each row is 7 strings, `last_error` is at most 200
   characters, and the dir name comes from `path`.
   Mutation: drop the truncation: red.
5. `test_is_armed`: the exact dir name plus a non-blank reason and operator gives True.
   Any one wrong gives False.
   Mutation: compare case-insensitively or by substring: red.
6. `test_mutating_calls_report_the_route_answer`:
   - `release` and `write_off` call the dispatcher with `retries=1` and the right
     `private_action` and params.
   - Route answer `ok True, status written off`: `(True, ...)`.
   - Route answer `status requeued`: `(True, "already written off at <at> by <op>; re-queued")`.
   - Route answer `ok False`: `(False, error)`.
   - The dispatcher raising or returning an error code: `(None, "sent, outcome unknown — refresh")`.

   Mutations:
   - Default retries: red.
   - Map a transport error to `False` or to `True`: red.

Verify: the new test file, and `helao/core/tests/test_palette.py`, whose sweeper also
scans the new module.

## T4: Reflex page, palette, app wiring

Files: new `helao/ui/reflex/sync_quarantine.py`, `helao/ui/reflex/app.py`,
`helao/ui/shared/palette.py`, `helao/core/tests/test_palette.py`, new
`helao/core/tests/test_reflex_sync_quarantine.py`,
`helao/core/tests/test_reflex_routes_e2e.py`.

Write the tests first:

1. `test_configure_enables_only_on_literal_true`: `"true"`, `1` and a missing key are
   disabled. `True` without a resolvable SYNC is disabled. `True` with SYNC is enabled.
   Mutation: use a truthiness check: red.
2. `test_page_renders_enabled_and_disabled`: `sync_quarantine_page()` builds both ways.
   This catches event-binding errors.
   Mutation: bind a handler with the wrong arity: red.
3. `test_refresh_unknown_vs_empty`: a fake `fetch` returning `None` gives the "unknown"
   status and no rows. Returning `[]` gives a "nothing quarantined" status.
   Mutation: use the same status for both: red.
4. `test_refresh_skips_while_busy_and_drops_a_stale_selection`:
   - While `busy`, refresh does not call `fetch`.
   - When the selected yml is missing from the new rows, `selected`, `confirm` and
     `armed` are cleared.

   Mutation: remove either guard: red. The pattern is
   `test_reflex_retire.py::test_set_uuid_and_confirm_are_no_ops_while_busy`.
5. `test_write_off_requires_armed_and_enabled`: when unarmed or disabled, the shared
   `write_off` is never called.
   Mutation: drop the armed re-check in the handler: red.
6. `test_actions_target_yml_not_index`: refresh reorders the rows between select and
   submit, and the call still carries the selected yml.
   Mutation: store a row index: red.
7. `test_release_and_write_off_share_one_lock`: while the module lock is held, both
   handlers report busy and call nothing.
   Mutation: give Release its own lock: red.
8. `test_status_shows_the_shared_message`: the shared call returns
   `(None, "sent, outcome unknown — refresh")`, and the status equals that text.
   Mutation: map `None` to "requeued" or to "failed": red.
9. `test_row_without_yml_has_no_actions`: render-level check, or check the row flag
   that drives the buttons.
   Mutation: drop the guard: red.
10. `test_every_foreach_var_carries_an_element_annotation`: a copy of the retire test.
11. e2e: `test_quarantine_route_is_the_real_page_and_its_handlers_register` in
    `test_reflex_routes_e2e.py`, following the retire test at L419.
12. Palette:
    - Add `TW["red-50"] = "#fef2f2"` and `REFLEX_PAGE_TINTS["/quarantine"] = "red-50"`.
    - Add rows `("slate-900","red-50"): 16.32` and `("slate-600","red-50"): 6.93` to
      `PAGE_TINT_TEXT_ROWS`, and `("slate-500","red-50"): 4.35` to
      `SLATE_500_ON_TINT_ROWS`.
    - Add `"red-50"` to the failing set, and rename that test and its docstring to "five
      of twelve".
    - These values were measured on 2026-10-15. If `_check` disagrees, report it rather
      than adjust the values.

Implementation follows spec §4.7:
- the page tint via `palette.reflex_page_class("/quarantine")`, through the existing
  `_page` helper;
- `rx.moment` at 60 s;
- a nav link;
- the route stays out of `CREDENTIAL_ROUTES`.

Verify: the new test file, `test_reflex_routes_e2e.py`, `test_palette.py`,
`test_reflex_retire.py`, `test_reflex_bundle.py` and `test_reflex_config.py`. A headless
check per the playwright-scratch-venv note is optional and not a gate.

## T5: docs

Files:
- `helao/core/drivers/data/CLAUDE.md`: append to the quarantine paragraph. Cover
  `/write_off`, the incomplete-group-only scope, the `.prg` block, the clearing of
  `process_s3`/`process_api`, the ledger, the marker and the `immediate` hint.
- `docs/superpowers/specs/2026-10-14-sync-quarantine-design.md`: add a §8 addendum.
  The write-off has shipped, and the Q6 premise is corrected: `_additions.json`
  allowlists new routes, so no re-freeze is needed.
- `docs/config-schema.md`: a `/quarantine` row in the pages table, a `sync_quarantine`
  row in the Reflex params table, and a checklist line.

Verify: `grep -rn` the new doc text for private deployment names and hostnames. There
must be none.

## Done when

- Every verify list above is green, with each file run as its own pytest process.
- Every listed mutation was applied once and turned its test red, reported per task.
- `git -C /mnt/STORAGE/repos/helao/fu-wo status --short` shows only the files named here.
