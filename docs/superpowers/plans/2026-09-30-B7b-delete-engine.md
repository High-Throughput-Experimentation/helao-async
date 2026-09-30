# B7b — Delete the legacy engine: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to carry this plan out task by task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete `helao/core/servers/` (the legacy engine) and everything that exists only because it exists, after first porting every test and golden master that still drives it onto the native hosts, so that nothing on disk or on the wire changes except the two exceptions the spec names.

**Architecture:** Five ordered commits on one branch, each with its own check. Commit 1 ports while the engine is still importable, so every port is compared byte for byte against a legacy capture taken on the same tree: the two golden masters move onto `OrchHost` and `ActionSession`/`ActionHost` with tracked native references, the member contracts are frozen to JSON, `harness/openapi_capture` learns bodies and enums, and the engine-importing tests are ported, moved or deleted. Commit 2 cuts the runtime paths (`makeActionApp` accepts native hosts only; the graft machinery, `makeOrchApp` and `sync_graft` go; `ws_frames` encodes the `orch_api` family through `OrchHost`'s own publishers; the ratchet allowlist empties). Commit 3 deletes the directory and its remaining pins and fixes stale text. Commit 4 adds the package-gone probe and re-freezes the orchestrator checklist exactly. Commit 5 dispositions the backlog.

**Tech Stack:** Python 3.14 (conda env `helao`), FastAPI, pytest (one file per process), `ast`, pyright (basic mode, authoritative), black 26.5.1.

**Spec:** `docs/superpowers/specs/2026-09-30-B7b-delete-engine-design.md` (user-approved, including every §12 default Q1–Q10). The plan argues from it. Where the plan departs from it, "Spec deviations and open questions" says so, with the measurement and a recommended default.

---

## Global Constraints (every task carries these)

- **Worktree and branch.** `<worktree>` = `/mnt/STORAGE/repos/helao/helao-b7b`, branch `feat/b7b-delete-engine`, starting HEAD `64f2cf15` (= `e60d800a` plus the spec commit; `git diff --stat e60d800a 64f2cf15` touches only the spec file). Recovery point: `freeze/pre-engine-delete_2609` = `e60d800a`.
- **Shell preamble.** Shell state does not persist between tool calls. Every Bash call in this plan starts with this line, verbatim:
  ```
  WT=/mnt/STORAGE/repos/helao/helao-b7b; X=/home/dan/.claude/jobs/290ccf4e/tmp/b7b/exec; MAIN=/mnt/STORAGE/repos/helao/helao-async; SMOKE=/home/dan/INST_hlo_hexsmoke
  ```
  `$WT` is the worktree, `$X` the execution scratch directory, `$SMOKE` the smoke root `goldenhex.yml` names (gate 7 only), `$MAIN` the main checkout (`<main-checkout>`), which is read-only for this plan except for the two `cp` sources in Task 0 and the `git archive` sources in Task 0 and gate 5.
- **Where writes may go.** Only inside `$WT` (tracked edits, plus the gitignored inputs Task 0 copies in) and `$X`. pytest's own temporary directories are allowed. Gate 7 writes the smoke root named in `goldenhex.yml`; the controller runs it.
- **Git.** Implementers run read-only git only, always as `git -C "$WT" ...`. Never `add`, `commit`, `push`, `stash`, `checkout`, `reset`, `branch`, `restore`, `rm`, `mv`, `apply` or `worktree`, in any repo. Delete and move files with plain `rm`/`mv`. Commits are made by the **main session (the controller)**, in the step titled "Controller commits"; an implementer never runs that step.
- **Python.** Always through conda, with the worktree forced onto `PYTHONPATH` (the env exports `PYTHONPATH=<main-checkout>`, spec §2.9):
  ```
  timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python <script or -m module>
  ```
  `timeout` goes outside `conda run` (measured: it kills the child python). Multi-line Python goes in a script file under `$X/` (`conda run python - <<EOF` runs nothing). pytest runs **one file per process**:
  ```
  timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -m pytest -q -p no:cacheprovider --color=no <one test file>
  ```
  The suites hang when collected as one session.
- **The `helao.__file__` guard.** Every check step that says "guard" runs, and requires the output `$WT/helao/__init__.py` (the worktree's `helao`, not the main checkout's):
  ```
  timeout 120 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -c "import helao; print(helao.__file__)"
  ```
- **Golden masters run from `$WT`.** `hlo_version` resolves through `git rev-parse` in the current directory (`helao/core/version.py`); `--cwd "$WT"` is mandatory for both golden masters, or every action scenario reads as DELTA (spec §2.4, §9).
- **The Bash tool's time cap (120 s default, 600 s maximum per call).** An inner `timeout 5400` does not raise it. Three rules follow:
  1. Anything that can run past about 100 s (every `run_tests.py` sweep, the unit-script sweep, the `live_group` suite, the private-copy sweep) is launched through `$X/bg.sh <name> <command…>` in a Bash call with **`run_in_background: true`**, and then waited for with `$X/wait.sh <name>` in a foreground call with the tool `timeout` set to `600000`. `wait.sh` prints `rc=<n>` when the job has finished, or `STILL-RUNNING` after about 9.5 minutes, in which case you call it again. The job's output is in `$X/<name>.txt`. Both scripts are created in Task 0 Step 0.2b. Steps that use them are marked **[background]**.
  2. Every other command that may take more than 100 s (pyright on many files, the golden masters' default modes, a pytest file with an inner `timeout 600`) is run with the tool `timeout` set to `600000`. Steps say **[tool timeout 600 s]**.
  3. A step never mutates a production file, runs something, and restores it inside one shell pipeline. It uses `$X/t0_mutate.py` (Task 0 Step 0.2b), which restores in `finally`, bounds each pytest run with `timeout=300`, and verifies each restored file by sha256. The private deployment copies are removed by a trap in `$X/t0_private_sweep.sh` and then again, in a separate call, by `$X/t0_private_remove.sh`, which also verifies they are gone.
- **Ports.** 8000–8003 and 8010, and their RPC siblings at +10000, must stay free. No task launches a server group except gate 7 (Task 16, controller). A red run that could reach a real dispatcher is wrapped in `timeout`.
- **Standalone scripts.** `helao/core/tests/unit_test_*.py`, `test_orch_dispatch_golden_master.py` and `test_active_golden_master.py` are `__main__` scripts; `run_tests.py` does not collect the first and reports the other two as `NOTESTS`. Run them directly with the python form above.
- **Public repo.** This plan and every tracked file and commit message: never name a private deployment (anything under `helao/deploy/` other than `hte`, `test`, `hexagon`). Say "a private deployment". The private-deployment copies of gate 5 and Task 0 are gitignored (`.gitignore:23`) and must **never** be present while a `git add` runs.
- **Escalate, don't choose.** If a command's output differs from the "Expected", or the task needs an edit it does not list, stop and report the exact output. Do not widen an edit, re-baseline a reference, or change an expected value. A golden-master delta other than the one Q1 allows stops the task (spec §4.1 step 6).
- **Edit only the files your task lists.** Parallel tasks (see each task's **Execution** note) touch disjoint files; no implementer commits, and no implementer runs `run_tests.py` while another task is editing the tree.
- **Formatting before commit.** Immediately before each `git add`, the controller runs black (the env's, 26.5.1) on the changed `.py` files that still exist; `pyproject.toml`'s `force-exclude` makes black skip the pinned files by itself:
  ```
  conda run -n helao --no-capture-output --cwd "$WT" black <changed .py files>
  ```
- **Commit trailer.** Every commit message ends with these two lines, after a blank line:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01NxxPoGvJmVh5T4xSpVejFF
  ```
- **The engine stays importable until Task 11.** Tasks 1–10 may import `helao.core.servers` in scratch comparison scripts under `$X`, never in a tracked file they create.

---

## Spec deviations and open questions (read before Task 0)

Each item gives the spec's claim, what the planning dry run measured on `64f2cf15`, and the default this plan takes. Items 1–10 change what the plan does relative to the spec; items 11–14 are spec facts that were wrong or incomplete but need no action beyond what the named task already does. The controller should confirm or overrule each default before dispatching the task named; items 1 and 10 are already settled by the user.

1. **User-approved (2026-09-30).** **The unified run layout has no `RUNS_FINISHED`/`RUNS_SYNCED` (gates 7 and 8).** Since `1df4ecf3` a sequence stays at `<root>/RUNS/<yyyy>/<mmdd>/<seq>/`; its `-seq.yml` carries `sequence_status: [finished]`, and `STATES/runstate_ORCH.jsonl` gets a `"kind":"sequence","state":"done"` line (measured on the smoke root B7a's gate left behind). **Decision (user-approved):** gates 7 and 8 pass on the sequence's `RUNS/…-seq.yml` (`sequence_status` finished) plus the run-state journal's `done` line. There is no SYNC `.prg` check.
2. **`openapi_capture`'s new fields break the parameter test in commit 1, not commit 4 (§4.1 step 9, §4.4, §8).** Landing the capture change makes `test_parameter_schemas_match_the_live_legacy_orchestrator` fail at once (measured `1 failed, 10 passed`): the live capture now records `ref`/`enum` on the three `checkcond` parameters, where the frozen file has `type: null`. **Default (Task 4, P-G.1):** commit 1 re-freezes `orch_openapi_legacy.json` in the new format from the in-process legacy `OrchAPI`. Safe because the in-process capture, projected back onto the old fields, equals the frozen launched-server file exactly (measured `equal_to_frozen=True`). Commit 4 then renames and re-freezes from `OrchHost` as the spec says, and its `cmp` against Task 4's native capture carries the legacy comparison forward. `body` also records `type` and `items` (P-G.2), without which `list` and `dict` bodies compare equal.
3. **One production edit in commit 1 that the spec does not list (Task 1, P-A.2).** Porting the dispatch golden master onto `OrchHost` raises its pyright errors from 24 to 29, because pyright types `ActionHost.aloop` as `None` (`action_host.py:192`). **Default:** annotate that line `self.aloop: asyncio.AbstractEventLoop | None = None`; no runtime effect, and seven other modules keep their counts (measured). The alternative is twelve `# pyright: ignore` lines in the harness.
4. **The DB endpoint-surface pin moves to a new file, and one more pin moves with it (Task 8, P-C.1/P-C.2; spec §5.3).** `test_native_sync_parity.py` has no host fixture and is module-skipped without an out-of-tree golden set, so a pin there would skip silently. Two of the five "graft rebinding only" `test_sync_graft` tests pin the `RecordingS3Client` injection, which nothing else pins. **Default:** a new `helao/hexagon/tests/test_db_endpoint_surface.py` holds both, parametrized over the `NativeSyncer` and the test deployment's `sim_db_server` `ActionHost` driver (only its own `startup_event` runs, so no port is bound).
5. **`unit_test_base_api` is move-and-delete, not delete (Task 6, P-F.1; spec §5.2).** The 24 native tests (count confirmed) miss four of its checks: the `ACTION_PARAM_KEYS` contents, the sync-wrapper branch of `action_route.py:148–155`, a new kwarg merging into an existing envelope, and the `ActiveParams.as_dict` round-trip. **Default:** move them as four small tests. Also in Task 6: `unit_test_config_seam` loses its `typed_server_cfg` check (no native member) and its missing-`run_type` check moves to `HelaoConfig.model_validate` (P-F.3); `unit_test_orch_queues` calls `run_queues` directly, because `OrchHost` has no `append_action`/`replace_action`/`supplement_error_action` delegators (P-F.5).
6. **`test_active_graft.py` outlives the old fixture by one commit (Task 5, P-E.3).** It imports `native_fixtures.make_base`, and 3 of its 5 tests fail once the fixture is rebuilt on `ActionHost` (measured). **Default:** commit 1 gives it a private verbatim copy of the legacy fixture; commit 2 deletes the file as planned. Also in Task 5: `empty_global_params_skips_dispatch` is already covered by `test_native_finalizer::test_finish_exports_global_params` and is not duplicated; `init_datafile`'s native twin gains three asserts to close a gap (P-E.5).
7. **The action golden master patches seven module globals, and its red run hangs without a bound (Task 2, P-B.3/P-B.4; §4.1 steps 4–5).** `adapters/legacy/clock.py:13` also binds `set_time`, and the fixture wires `LegacyClockAdapter`. With only the engine globals patched, scenarios 8 and 12 reach the real private dispatcher on `127.0.0.1:8000`, which retries for minutes. **Default:** a seven-entry `_PATCH_TARGETS` table, and a red-check script that bounds each scenario at 30 s (measured: 11 DELTA with `move_dir` 1→0 or 2→0, 2 HANG, so 13 of 13 red; native 0 of 13). The host is `ActionHost.__new__` plus an attribute block (P-B.1): real construction writes a `gethostname()` machine name into `-act.yml`, which is both a delta and a privacy leak.
8. **Commit 5's dispatch golden master only passes if the fixture's globstat lines and the feed leave together (§4.5).** Removing the fixture lines alone raises `AttributeError: 'OrchHost' object has no attribute 'globstat_q'` in every scenario that drains a second interrupt (`__new__` skips `__init__`). **Default:** Task 15 removes the feed in `wait_for_interrupt` first, then the fixture lines, in one commit.
9. **Commit 3's two tasks run docs first (ordering; spec silent).** `rm -rf helao/core/servers` would delete the traps doc. **Default:** Task 11 (docs, stale references, `mv` of `CLAUDE.md`) runs first on the commit-2 tree; Task 12 (deletion, test pins, `pyproject.toml`, black on the four collaborators) runs after it, so black formats the docstrings Task 11 edited.
10. **User-approved (2026-09-30).** **D-B7b.10's classification is wider than the spec's list (Task 11, P-I.1–P-I.4).** The spec's grep returns 384 hits in 113 files on `64f2cf15`, not "63 files" (the 63 came from the narrower pattern). Task 11 classifies every hit. It leaves `deploy/hte/servers/orchestrator/async_orch2.py:10`, which the spec lists as "known to change", because the line is past-tense provenance and sits in a deployment server module (§10). It leaves 12 stale hits in hte/test `servers/` modules for B7c (§10), and fixes 19 hits in 13 hte **driver** files and 3 in 2 test-deployment runners, which §10 does not cover. It also fixes the same stale "source-parity-pinned" paragraph in `data_stream.py:64` and `finalizer.py:63` that the spec names only for `data_file.py:67`, the five native-adapter docstrings that say the graft binds the collaborator, `ports/status.py:14`, `adapters/legacy/status.py:11–12`, an andor `CLAUDE.md` line, and root `CLAUDE.md:81`'s `enable_op` claim. Task 8 fixes `live_group.py` and `test_concurrency_live.py` docstrings (outside the grep, which excludes `/tests/`). Task 9 fixes the `_register_orch_ws_routes` docstring. **Decision (user-approved):** the 19 comment/docstring lines in the 13 hte driver files are rewritten in commit 3 (Task 11), and Task 11's AST check, which proves only docstrings, comments and the four named messages changed, stays.
11. **Corrections, no action needed.** `hexconfig.py` is `helao/hexagon/hexconfig.py` and the lines are 32–34. `_register_orch_ws_routes` spans `orch_host.py:1324–1384`. The fixture in `test_standalone_operator.py` is `_bare_orch` (l.26–50), not `_make_orch`. `native_fixtures.py`'s legacy uses are at l.19, 27, 30, 84 and 102. `pyproject.toml`'s comment is lines 30–57, not 28–57, and black reformats three of the four collaborators (`meta_writer.py` is unchanged). `error` under `helao/core/` is the module `error.py`. §2.4's two stale-baseline dispatch deltas also reorder blocks, not only flip fields; the old baseline is retired either way.
12. **The spec's command form is extended.** §4 gives `conda run -n helao env PYTHONPATH=<worktree> python`. The plan adds `--no-capture-output` (conda otherwise buffers output), `--cwd "$WT"` (the golden masters and `run_unit_tests.py` resolve `hlo_version` through `git rev-parse` in the current directory), and an outer `timeout` (measured: it kills the child). Whenever a command exits non-zero, `conda run` adds one `ERROR conda.cli.main_run … failed` line on stderr; expected outputs omit it.
13. **Two unit scripts run nothing as scripts.** `unit_test_dispatcher.py` and `unit_test_base_api.py` have no `__main__`, so a script sweep counts them as passing without running them. Task 6's `$X/t6_run_unit.py` calls the functions instead; Tasks 7 and 13 use it.
14. **Found, reported, not fixed (out of B7b's scope).** `OrchHost.add_split_sequences` is annotated `-> None` but returns the uuid list (`orch_host.py:292`; Task 6 carries one pyright ignore on the test line). After commit 2, `bind_base` on the native adapters has no production caller (its only one was `active_graft.py:68`); B7c should decide. `test_ws_consumer_parity.py`'s path constants are renamed `ACTION_HOST_PATH`/`ORCH_HOST_PATH` when they are re-pointed (Task 12), because keeping `BASE_API_PATH` for `action_host.py` would describe the new code through a deleted name.

Spec §12's Q1–Q10 are adopted as approved: Q1 (S7's one `intend_none` block) in Task 1, Q2 (scenario 5 without `set_error`) in Task 2, Q3 (tracked references) in Tasks 1 and 2, Q4 (`limit_vis` kept) needs no task, Q5 (`publish_globstat` deleted) and the globstat channel in Task 15, Q6 (`pyproject.toml`) in Task 12, Q7 (`goldenhex` smoke) in gate 7, Q8 (`_baseapi_system_surface.json` untouched) needs no task, Q9 (hook rename) in Task 8, Q10 (`/prepend_sequences`) recorded in the PR (Task 16).

---

## Execution order and parallelism

Subagents share one worktree and one git index. A task may run in parallel with another only when the two touch disjoint files, and no implementer ever commits. Commits happen in Tasks 7, 10, 13, 14 and 15, by the controller.

| wave | tasks | parallel? | notes |
|---|---|---|---|
| 0 | 0 | alone | baselines; nothing else runs during its sweeps |
| 1 | 1, 2, 3→4, 5, 6 | yes: five parallel lanes | Tasks 1, 2, 5 and 6 run in parallel with each other and with the lane that runs Task 3 then Task 4 (sequential: both write under `checklists/`). No wave-1 step mutates a production file: the two mutation probes that used to sit in Tasks 5 and 6 run in wave 1b. Task 2 Step 2.7 posts to port 8000 (keep it free). Tasks 5 and 6 both delete `unit_test_*` files, so nobody runs `run_unit_tests.py` until Task 7 |
| 1b + close | 7 | alone | dispatched only after all six wave-1 tasks report done. Steps 7.0a/7.0b run the mutation probes (formerly 5.9 and 6.7), then `run_unit_tests.py`, the commit-1 check, **commit 1** |
| 2 | 8, then 9, then 10 | no | Task 8's Step 8.12 mutates `orch_host.py`, which Task 9 edits; Task 10 is the check and **commit 2** |
| 3 | 11, then 12, then 13 | no | docs first (it moves `CLAUDE.md` out of the directory Task 12 deletes); Task 13 is the check and **commit 3** |
| 4 | 14 | no: part A, then part B | package-gone probe (ratchet file), then checklist re-freeze and mutation probes (surface test, checklists); **commit 4** |
| 5 | 15 | two parts, sequential | globstat deletion, then the dispatch golden master's fixture lines; full sweep; **commit 5** |
| gates | 16 | alone | gates 1–6 and 9 by an implementer, gate 7 and the push by the controller (the push only with user approval), gate 8 by the user |

## File Structure

| path | action | task | responsibility |
|---|---|---|---|
| `helao/core/tests/test_orch_dispatch_golden_master.py` | modify | 1, 15 | dispatch golden master drives `OrchHost`; reads `golden/dispatch/` |
| `helao/core/tests/golden/dispatch/*.jsonl` (9) | create | 1 | tracked native dispatch references (Q3) |
| `helao/hexagon/app/action_host.py` | modify | 1, 11, 15 | `aloop` annotation (1); docstrings (11); sleep comment (15) |
| `helao/core/tests/test_active_golden_master.py` | modify | 2 | action golden master drives `ActionSession` over `ActionHost` |
| `helao/core/tests/golden/action/*` (26) | create | 2 | tracked native action references (Q3) |
| `helao/hexagon/tests/checklists/base_member_surface.json` | create | 3 | frozen Base member surface (89) |
| `helao/hexagon/tests/checklists/orch_member_contract.json` | create | 3, 15 | frozen orchestrator contract (138; 137 after `globstat_q`) |
| `harness/openapi_capture.py` | modify | 4, 11 | `ref`/`enum`/`body` in the capture (4); docstring (11) |
| `helao/hexagon/tests/checklists/orch_openapi_legacy.json` | re-freeze, then delete | 4, 14 | legacy capture in the new format (4); replaced by `orch_openapi.json` (14) |
| `helao/hexagon/tests/checklists/orch_openapi.json` | create | 14 | native, exact orchestrator surface (77 routes) |
| `helao/hexagon/tests/native_fixtures.py` | rewrite | 5, 12 | fixture on `ActionHost`/`ActionSession`; parity helper deleted (12) |
| `helao/hexagon/tests/test_native_{artifact_store,data_file,data_sink,data_stream,finalizer,meta_writer}.py` | modify | 5, 12 | off the legacy fixture, moved checks (5); pins and legacy halves deleted (12) |
| `helao/core/tests/test_run_state_wiring.py`, `helao/hexagon/tests/test_estop_fixes.py` | modify | 5 | native finalizer; `orch_unpack` import |
| `helao/core/tests/unit_test_{active_data_file,active_data_stream,active_finalizer,base_meta_writer}.py` | delete | 5 | moved into native twins |
| `helao/core/tests/unit_test_{active_executor,base_api,base_endpoints}.py` | delete | 6 | moved into native twins |
| `helao/core/tests/unit_test_{base_live_buffer,base_status,config_seam,dispatcher,estop_sync,orch_lifecycle,orch_queues}.py` | modify | 6 | ported in place |
| `helao/core/tests/test_{orch_queue_paging,standalone_operator,analysis_recovery,upload_set}.py` | modify | 6 | shared-logic tests off the engine |
| `helao/hexagon/tests/test_{executor_runner,endpoint_manager,action_route,action_context}.py` | modify | 6 | receive moved checks |
| `run_unit_tests.py` | modify | 7 | 37 → 30 functions |
| `helao/hexagon/app/factory.py` | modify | 8 | `makeActionApp` native-only; `makeOrchApp` deleted |
| `helao/hexagon/app/dispatch_loop.py` | modify | 8 | graft classes deleted |
| `helao/hexagon/app/{active_graft,sync_graft}.py` | delete | 8 | graft machinery |
| `helao/deploy/hexagon/servers/action/sim_db_server.py` | rewrite | 8 | plain delegate |
| `helao/hexagon/adapters/legacy/health.py`, `helao/hexagon/hexconfig.py` | modify | 8 | stale text in code the task changes |
| `helao/hexagon/tests/test_{active_graft,sync_graft}.py` | delete | 8 | graft tests |
| `helao/hexagon/tests/test_db_endpoint_surface.py` | create | 8 | DB endpoint surface + S3 recorder pins |
| `helao/hexagon/tests/test_{db_shim,dispatch_loop,factory,vis_hexagon_producer_parity}.py`, `live_group.py`, `test_concurrency_live.py` | modify | 8 | trimmed / ported / docstrings |
| `helao/hexagon/tests/test_orch_host_surface.py` | modify | 8, 12, 14 | health test (8); legacy route reader deleted (12); exact frozen-surface tests (14) |
| `helao/hexagon/tests/test_engine_import_ratchet.py` | modify | 8, 12, 14 | allowlist emptied + factory probe (8); legacy probe deleted (12); package-gone test (14) |
| `helao/hexagon/app/orch_host.py` | modify | 9, 11, 15 | `orch_ws_publishers` (9); docstring (11); globstat deleted (15) |
| `harness/ws_frames.py` | modify | 9 | `orch_api` family through `orch_ws_publishers` |
| `helao/core/servers/CLAUDE.md` → `helao/hexagon/app/CLAUDE.md` | move | 11 | traps doc, retitled |
| `CLAUDE.md`, `helao/deploy/hte/drivers/spec/andor/CLAUDE.md` | modify | 11 | native hosts named |
| 38 `.py` files listed in Task 11 | modify (docstrings, 4 messages) | 11 | D-B7b.10 stale references |
| `helao/core/servers/` | delete | 12 | the engine |
| `pyproject.toml` | modify | 12 | `force-exclude` keeps only the `sync_driver` pair |
| `helao/hexagon/adapters/native/{data_file,data_stream,finalizer,meta_writer}.py` | modify | 11, 12 | docstrings (11); black (12) |
| `helao/hexagon/tests/test_{action_session_port,estop_finish_race,ws_consumer_parity}.py`, `helao/core/tests/test_{bokeh_theme,palette}.py` | modify | 12, 15 | engine self-tests and readers; `test_ws_consumer_parity` again in 15 |
| `helao/hexagon/tests/test_{action_host,orch_host}_member_coverage.py` | modify | 12 | read the frozen snapshots |
| `helao/hexagon/app/{orch_status_sync,orch_dispatch,ingestion}.py`, `helao/hexagon/ports/auxiliary.py` | modify | 15 (and 11 for `ingestion.py` lines 1–6) | globstat channel deleted |
| `helao/hexagon/tests/test_orch_stops_polling_on_shutdown.py`, `helao/core/tests/unit_test_orch_status_sync.py` | modify | 15 | globstat checks removed |

---

### Task 0: Baselines on `64f2cf15` (no commit)

**Files:** no tracked file. Creates `$X/` and its contents; copies three gitignored inputs into `$WT` (`pyrightconfig.json`, `.omc/artifacts/p5/baseline_S0/`, `.omc/artifacts/p6/baseline_S0a/`); temporarily copies the private deployments into `$WT/helao/deploy/` (gitignored) and removes them again.

**Interfaces:**
- Consumes: nothing.
- Produces, all under `$X/`: `t0_private_copy.sh`, `t0_private_remove.sh`, `t0_failset.sh`, `t0_unit_sweep.sh`, `t13_engine_refs.py` and its self-test, `t0_pyright_cmp.py`, `pyright_files_before.txt`, and the records `F0p.txt`, `F0.txt`, `run_tests_F0p.txt`, `run_tests_F0.txt`, `checklist_ids_before.txt`, `pyright_before.json`, `rut_before.txt`, `unit_before.txt`, `gm_dispatch_check_before.txt`, `gm_action_check_before.txt`, `ports_before.txt`. Every later check compares against these.

**Execution:** runs alone, first. Nothing else may run while the sweeps (0.6, 0.7) run.

- [ ] **Step 0.1: Confirm the starting point.**
```
git -C "$WT" rev-parse HEAD
git -C "$WT" branch --show-current
git -C "$WT" status --porcelain
git -C "$WT" diff --stat e60d800a HEAD
```
Expected: `64f2cf15…`, `feat/b7b-delete-engine`, no status output, and a diffstat naming only `docs/superpowers/specs/2026-09-30-B7b-delete-engine-design.md`. Anything else: STOP.

- [ ] **Step 0.2: Scratch, gitignored inputs, guard.**
```
mkdir -p "$X"
cp "$MAIN/pyrightconfig.json" "$WT/pyrightconfig.json"
mkdir -p "$WT/.omc/artifacts/p5" "$WT/.omc/artifacts/p6"
cp -r "$MAIN/.omc/artifacts/p5/baseline_S0" "$WT/.omc/artifacts/p5/"
cp -r "$MAIN/.omc/artifacts/p6/baseline_S0a" "$WT/.omc/artifacts/p6/"
git -C "$WT" status --porcelain
timeout 120 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -c "import helao; print(helao.__file__)"
```
Expected: no `git status` output (all three are ignored: `.gitignore:8`, `.gitignore:33`); then the worktree's `helao/__init__.py` (`$WT/helao/__init__.py`). The `.omc` copies exist only to record the pre-port golden-master state in Step 0.5; after Tasks 1 and 2 nothing reads them.

- [ ] **Step 0.2b: The three execution helpers every later task uses.** Create `$X/bg.sh`:
```bash
#!/bin/bash
# B7b: run a long command detached from the Bash tool's 600 s cap.
# Usage (Bash tool call with run_in_background: true):  bg.sh <name> <command> [args...]
# Output goes to $X/<name>.txt; "rc=<n>" goes to $X/<name>.done when the command ends.
X=/home/dan/.claude/jobs/290ccf4e/tmp/b7b/exec
name="$1"; shift
rm -f "$X/$name.done"
"$@" > "$X/$name.txt" 2>&1
echo "rc=$?" > "$X/$name.done"
```
Create `$X/wait.sh`:
```bash
#!/bin/bash
# B7b: wait (up to ~9.5 min per call) for a bg.sh job. Run with the tool timeout at 600000 ms.
# Prints the job's "rc=<n>" and exits 0, or prints STILL-RUNNING and exits 3 (call it again).
X=/home/dan/.claude/jobs/290ccf4e/tmp/b7b/exec
for i in $(seq 1 57); do
  [ -e "$X/$1.done" ] && { cat "$X/$1.done"; exit 0; }
  sleep 10
done
echo STILL-RUNNING; exit 3
```
Create `$X/t0_mutate.py`:
```python
"""B7b: mutate-and-observe probes with a guaranteed, verified restore.

Usage: python t0_mutate.py <probes.json>     (launch through bg.sh, in the background)
Each probe is an object with:
  "file"    repo-relative path of the production (or fixture) file to mutate
  "old"     exact text that must occur exactly once, and "new" its replacement; or
  "git_rev" a revision whose version of "file" replaces it wholesale
  "test"    pytest file or node id;  "k" optional -k expression
  "expect"  a substring that must appear in pytest's output
For each probe: sha256 the file, mutate it, run pytest (timeout=300 s), restore it
in `finally`, and verify the sha256. A probe is RED when pytest exits non-zero and
its output contains `expect`. SIGTERM/SIGINT/SIGHUP are turned into SystemExit, so a
kill from outside still runs the restore. Exit 0 only if every probe went RED and
every file was restored byte for byte.
"""

import hashlib
import json
import signal
import subprocess
import sys
from pathlib import Path

WT = Path("/mnt/STORAGE/repos/helao/helao-b7b")
for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
    signal.signal(sig, lambda *_: sys.exit(143))

probes = json.load(open(sys.argv[1], encoding="utf-8"))
bad = 0
for p in probes:
    path = WT / p["file"]
    orig = path.read_bytes()
    digest = hashlib.sha256(orig).hexdigest()
    if p.get("git_rev"):
        mutated = subprocess.run(
            ["git", "-C", str(WT), "show", f'{p["git_rev"]}:{p["file"]}'],
            capture_output=True, check=True,
        ).stdout
    else:
        text = orig.decode("utf-8")
        assert text.count(p["old"]) == 1, f'anchor not unique in {p["file"]}: {p["old"]!r}'
        mutated = text.replace(p["old"], p["new"]).encode("utf-8")
    assert mutated != orig, f'mutation is a no-op on {p["file"]}'
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--color=no", p["test"]]
    if p.get("k"):
        cmd += ["-k", p["k"]]
    try:
        path.write_bytes(mutated)
        try:
            proc = subprocess.run(cmd, cwd=WT, capture_output=True, text=True, timeout=300)
            rc, out = proc.returncode, proc.stdout + proc.stderr
        except subprocess.TimeoutExpired:
            rc, out = 124, "TIMEOUT"
    finally:
        path.write_bytes(orig)
    restored = hashlib.sha256(path.read_bytes()).hexdigest() == digest
    found = p["expect"] in out
    red = rc != 0 and found
    print(
        f'{"RED" if red else "NOT-RED"} rc={rc} {p["test"]} :: expect '
        f'{"found" if found else "MISSING"} :: {"RESTORED" if restored else "NOT-RESTORED"} {p["file"]}'
    )
    bad += (not red) + (not restored)
print("MUTATE-PASS" if not bad else "MUTATE-FAIL")
sys.exit(1 if bad else 0)
```
```
chmod +x "$X/bg.sh" "$X/wait.sh"
"$X/bg.sh" t0_helper_check echo helpers-ok; "$X/wait.sh" t0_helper_check; cat "$X/t0_helper_check.txt"
timeout 60 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -m py_compile "$X/t0_mutate.py" && echo MUTATE-HELPER-COMPILES
```
Expected: `rc=0`, `helpers-ok`, `MUTATE-HELPER-COMPILES`. (This one quick job may run in the foreground; every real use of `bg.sh` is a `run_in_background: true` call.)

- [ ] **Step 0.3: Ports free.**
```
timeout 60 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python helao/hexagon/tests/smoke/wait_ports_free.py --timeout 10 8000 8001 8002 8003 8010 > "$X/ports_before.txt" 2>&1; echo rc=$?
```
Expected: `rc=0` (the script also checks 18000–18003 and 18010).

- [ ] **Step 0.4: `run_unit_tests.py` and the standalone scripts.** Create `$X/t0_unit_sweep.sh`:
```bash
#!/bin/bash
# B7b: run every helao/core/tests/unit_test_*.py as a script; one "rc path" line each.
# Usage: t0_unit_sweep.sh <out_file>
WT=/mnt/STORAGE/repos/helao/helao-b7b
: > "$1"
for f in $(cd "$WT" && /bin/ls helao/core/tests/unit_test_*.py | sort); do
  timeout 300 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$f" > /dev/null 2>&1
  echo "$? $f" >> "$1"
done
```
```
chmod +x "$X/t0_unit_sweep.sh"
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python run_unit_tests.py > "$X/rut_before.txt" 2>&1; echo rc=$?
tail -1 "$X/rut_before.txt"
grep -c '^  [a-z_]*: PASS$' "$X/rut_before.txt"
```
**[background]** Launch (a `run_in_background: true` call; about 4 minutes):
```
"$X/bg.sh" unit_before_job "$X/t0_unit_sweep.sh" "$X/unit_before.txt"
```
Then, **[tool timeout 600 s]**:
```
"$X/wait.sh" unit_before_job
wc -l < "$X/unit_before.txt"
grep -v '^0 ' "$X/unit_before.txt"
```
Expected: `rc=0`, `overall: PASS`, `37` (spec §2.3's 37 functions; each prints one `  <name>: PASS` summary line). Then `rc=0` from `wait.sh`, `40`, and exactly one non-zero line, `1 helao/core/tests/unit_test_status_transitions.py` (measured in planning: it needs a gitignored `.omc/artifacts/p3a/` input and is red on `unstable` too; B7b neither copies nor fixes it). Two of the 40 (`unit_test_dispatcher.py`, `unit_test_base_api.py`) have no `__main__` and exit 0 without running anything; the sweep records exit codes only.

- [ ] **Step 0.5: Pre-port golden-master state (record only).**
```
timeout 900 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python helao/core/tests/test_orch_dispatch_golden_master.py --check > "$X/gm_dispatch_check_before.txt" 2>&1; echo rc=$?
grep -cE '^  PASS' "$X/gm_dispatch_check_before.txt"; grep -E '^  DELTA' "$X/gm_dispatch_check_before.txt" | awk '{print $2}'
timeout 900 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python helao/core/tests/test_active_golden_master.py --check > "$X/gm_action_check_before.txt" 2>&1; echo rc=$?
tail -3 "$X/gm_action_check_before.txt"
```
Expected: dispatch `rc=1`, `7`, then `2_every_action_start_condition:` and `7_returned_action_error_estop_loop:` (the two stale-baseline deltas of spec §2.4); action `rc=0` with 13 PASS. These records are evidence only: Tasks 1 and 2 replace both references with tracked native captures.

- [ ] **Step 0.6: F0p — the sweep with the private deployments copied in.** Create `$X/t0_private_copy.sh` (spec §7 gate 5, verbatim loop, plus a record of what was copied):
```bash
#!/bin/bash
# B7b: copy each private deployment into the worktree at its committed HEAD.
# Writes the copied directory names to $X/private_copied.txt (scratch only).
WT=/mnt/STORAGE/repos/helao/helao-b7b; X=/home/dan/.claude/jobs/290ccf4e/tmp/b7b/exec; MAIN=/mnt/STORAGE/repos/helao/helao-async
: > "$X/private_copied.txt"
for src in "$MAIN"/helao/deploy/*/; do
  d=$(basename "$src")
  case "$d" in hte|test|hexagon|__pycache__) continue ;; esac
  [ -d "$src/.git" ] || continue
  rm -rf "$WT/helao/deploy/$d" && mkdir "$WT/helao/deploy/$d"
  git -C "$src" archive HEAD | tar -x -C "$WT/helao/deploy/$d"
  echo "$d" >> "$X/private_copied.txt"
done
wc -l < "$X/private_copied.txt"
```
Create `$X/t0_private_remove.sh`:
```bash
#!/bin/bash
# B7b: remove exactly the private copies t0_private_copy.sh made, then prove the tree is clean.
WT=/mnt/STORAGE/repos/helao/helao-b7b; X=/home/dan/.claude/jobs/290ccf4e/tmp/b7b/exec
# Idempotent: safe to run again after the sweep wrapper's trap already ran it.
[ -e "$X/private_copied.txt" ] || : > "$X/private_copied.txt"
while read -r d; do
  case "$d" in ""|hte|test|hexagon|__pycache__|__init__.py) echo "refusing $d"; exit 2 ;; esac
  rm -rf "$WT/helao/deploy/$d"
done < "$X/private_copied.txt"
# The copies are gitignored (.gitignore:23), so `git status` cannot see them: check the paths.
left=$(/bin/ls -A "$WT/helao/deploy" | grep -v -x -e __init__.py -e __pycache__ -e hexagon -e hte -e test)
[ -z "$left" ] || { echo "LEFTOVER: $left"; exit 1; }
git -C "$WT" status --porcelain --ignored -- helao/deploy | grep -v '__pycache__' | grep '^!!' && { echo "IGNORED PATHS LEFT"; exit 1; }
echo PRIVATE-COPIES-REMOVED
```
Create `$X/t0_private_sweep.sh`, which removes the copies on every exit path:
```bash
#!/bin/bash
# B7b: copy the private deployments in, sweep, and ALWAYS remove the copies again.
# Usage (through bg.sh, in the background): t0_private_sweep.sh <run_tests output file>
WT=/mnt/STORAGE/repos/helao/helao-b7b; X=/home/dan/.claude/jobs/290ccf4e/tmp/b7b/exec
trap '"$X/t0_private_remove.sh" > "$X/private_remove_trap.txt" 2>&1' EXIT
trap 'exit 143' TERM INT HUP
"$X/t0_private_copy.sh" || exit 2
timeout 7200 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python run_tests.py > "$1" 2>&1
```
Create `$X/t0_failset.sh`:
```bash
#!/bin/bash
# B7b: extract the failing file set (FAIL and TIMEOUT) from a run_tests.py log, sorted.
# Usage: t0_failset.sh <run_tests log> <out file>
grep -E '^  (FAIL|TIMEOUT) +[^ ]+\.py ' "$1" | awk '{print $2}' | sort > "$2"
cat "$2"
```
```
chmod +x "$X/t0_private_copy.sh" "$X/t0_private_remove.sh" "$X/t0_private_sweep.sh" "$X/t0_failset.sh"
```
**[background]** Launch (a `run_in_background: true` call; about 12 minutes):
```
"$X/bg.sh" F0p_job "$X/t0_private_sweep.sh" "$X/run_tests_F0p.txt"
```
Wait, **[tool timeout 600 s]**, repeating while it prints `STILL-RUNNING`:
```
"$X/wait.sh" F0p_job
```
Then, in a **separate** call, remove the copies again (idempotent) and verify they are gone, and read the result:
```
"$X/t0_private_remove.sh"
cat "$X/private_remove_trap.txt"
head -3 "$X/F0p_job.txt"
tail -10 "$X/run_tests_F0p.txt"
"$X/t0_failset.sh" "$X/run_tests_F0p.txt" "$X/F0p.txt"
```
If the wrapper was killed or `wait.sh` never reports, run `"$X/t0_private_remove.sh"` anyway before anything else: it is the only thing that removes gitignored copies.
Expected (measured in planning on `64f2cf15`): `wait.sh` prints `rc=1` (the sweep's exit code); the remove script prints `PRIVATE-COPIES-REMOVED`, and so does the trap's record; `F0p_job.txt` starts with `4` (the number of copies made); the summary reads `===== 415 files in …s` (about 700 s), `PASS 387`, `ENV 2`, `NOTESTS 17`, `NOTATEST 1`, `FAIL 8`; `F0p.txt` holds 8 paths: the three of Step 0.7's F0, plus five test files inside private deployments (pre-existing failures of those repos' own tests in a copied tree; this plan does not name them). Record the numbers; gate 5 compares against this set, whatever it measures.

- [ ] **Step 0.7: F0 — the bare sweep.** **[background]** Launch (a `run_in_background: true` call; about 8 minutes):
```
"$X/bg.sh" run_tests_F0 timeout 5400 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python run_tests.py
```
Then, **[tool timeout 600 s]**, repeating while it prints `STILL-RUNNING`:
```
"$X/wait.sh" run_tests_F0
tail -10 "$X/run_tests_F0.txt"
"$X/t0_failset.sh" "$X/run_tests_F0.txt" "$X/F0.txt"
```
Expected `rc=1` from `wait.sh`, and the summary measured in planning on `64f2cf15`: `===== 306 files in …s` (about 460 s), `PASS 288`, `ENV 2`, `NOTESTS 13`, `FAIL 3`. `F0.txt` holds exactly:
```
harness/tests/test_freeze.py
harness/tests/test_hte_checklist.py
helao/hexagon/tests/test_hte_route_checklist.py
```
These are the checklist drift of spec §2.7 (Step 0.8 records the five IDs inside them). The sweep leaves an untracked directory named `C:\INST_hlo\DATA` at the worktree root (an hte test writes to its config's Windows-style root, which Linux treats as a relative path). It is gitignored (`.gitignore` pattern `C:*`) and harmless; `rm -rf "$WT/C:\INST_hlo\DATA"` after a sweep removes it. If the measured set differs, show the controller before any task compares against it: the measured set is the baseline.

- [ ] **Step 0.8: The five checklist IDs (spec §2.7).**
```
for f in harness/tests/test_hte_checklist.py helao/hexagon/tests/test_hte_route_checklist.py harness/tests/test_freeze.py; do timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -m pytest -q -p no:cacheprovider --color=no -rf "$f" 2>&1 | grep -E '^FAILED' | awk '{print $2}'; done | sort > "$X/checklist_ids_before.txt"
cat "$X/checklist_ids_before.txt"
```
Expected, exactly:
```
harness/tests/test_freeze.py::test_hte_freeze_is_clean_and_skips_nothing
harness/tests/test_hte_checklist.py::test_frozen_matches_regenerated[andor_server.py-ANDOR]
harness/tests/test_hte_checklist.py::test_frozen_matches_regenerated[biologic_server.py-BIOLOGIC]
harness/tests/test_hte_checklist.py::test_frozen_matches_regenerated[nidaqmx_server.py-NI]
helao/hexagon/tests/test_hte_route_checklist.py::test_module_matches_its_frozen_checklist[andor_server.py]
```

- [ ] **Step 0.9: Create the executable-reference sweep and its self-test** (from spec §4.3; Tasks 7, 12 and 13 run it).  Create `$X/t13_engine_refs.py` with exactly this content:

```python
"""B7b Task 13: no executable reference to the deleted engine (spec section 4.3).

Usage, from the repo root:  python t13_engine_refs.py [<root> [<file-list>]]
  <root>       repo root to read files from (default: the current directory)
  <file-list>  newline-separated repo-relative paths (default: `git ls-files '*.py'`)

Fails (exit 1) on any of:
  E1  an Import/ImportFrom of helao.core.servers or a submodule (relative
      spellings and `from helao.core import servers` included);
  E2  import_module / __import__ / find_spec whose first argument is a string
      constant starting with helao.core.servers, outside the ratchet (whose
      package-gone probe is the one allowed caller);
  E3  patch / setattr / delattr (mock.patch, monkeypatch.setattr/delattr)
      whose first argument is a string constant starting with helao.core.servers;
  M   any other string constant containing the dotted name, or any
      non-docstring string constant containing the path spelling
      (helao/core/servers or helao\\core\\servers: a source-path reader), in a
      file outside ALLOWED.
Docstrings that spell the engine as a path are provenance (D-B7b.10) and are
not reported. Tracked files missing from the working tree are skipped.
"""

import ast
import subprocess
import sys
from pathlib import Path

DOTTED = "helao.core.servers"
PATHS = ("helao/core/servers", "helao\\core\\servers")
RATCHET = "helao/hexagon/tests/test_engine_import_ratchet.py"

#: Spec section 2.2, last three rows: the ban lists, the ratchet, and the
#: enumerated provenance docstrings (left alone by D-B7b.10).
ALLOWED = frozenset(
    {
        # strings that ban the prefix
        "helao/hexagon/tests/test_boundaries.py",
        "helao/hexagon/tests/test_control_surface_port.py",
        "helao/hexagon/tests/test_external_composition_contract.py",
        "helao/hexagon/tests/test_hte_is_native.py",
        "helao/hexagon/tests/test_test_deployment_is_native.py",
        "helao/core/tests/test_ui_boundary.py",
        # the ratchet itself
        RATCHET,
        # provenance docstrings and comments
        "helao/core/drivers/data/analysis_layout.py",
        "helao/hexagon/adapters/native/__init__.py",
        "helao/hexagon/adapters/native/native_syncer.py",
        "helao/hexagon/adapters/native/sync_driver.py",
        "helao/hexagon/adapters/vis/browser_source.py",
        "helao/hexagon/adapters/vis/control_surface.py",
        "helao/hexagon/adapters/vis/param_store.py",
        "helao/hexagon/adapters/vis/spec_parser.py",
        "helao/hexagon/adapters/vis/ws_consumer.py",
        "helao/hexagon/ports/browser_source.py",
        "helao/hexagon/ports/control_surface.py",
        "helao/hexagon/ports/param_store.py",
        "helao/hexagon/ports/spec_parser.py",
        "helao/hexagon/domain/pal_reconciliation.py",
        "helao/hexagon/app/endpoint_overlay.py",
        "helao/deploy/hte/drivers/robot/pal_driver.py",
        "helao/deploy/hte/tests/test_kinesis_counts.py",
        "helao/hexagon/tests/test_galil_motion_counts.py",
        "helao/core/tests/test_active_golden_master.py",
    }
)

IMPORT_CALLS = {"import_module", "__import__", "find_spec"}
PATCH_CALLS = {"patch", "setattr", "delattr"}


def is_engine_module(name: str) -> bool:
    return name == DOTTED or name.startswith(DOTTED + ".")


def callee(node: ast.Call) -> str:
    f = node.func
    return f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")


def first_str(node: ast.Call):
    if node.args and isinstance(node.args[0], ast.Constant):
        v = node.args[0].value
        return v if isinstance(v, str) else None
    return None


def docstring_ids(tree: ast.AST) -> set[int]:
    kinds = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, kinds) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                out.add(id(first.value))
    return out


def scan(rel: str, source: str) -> tuple[list[str], list[str]]:
    """(executable references, other mentions), each as `rel:line kind detail`."""
    package = rel[: -len(".py")].split("/")[:-1]
    tree = ast.parse(source, filename=rel)
    execs, mentions, call_args = [], [], set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if is_engine_module(a.name):
                    execs.append(f"{rel}:{node.lineno} E1 import {a.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - (node.level - 1)]
                module = ".".join(base + ([node.module] if node.module else []))
            else:
                module = node.module or ""
            full = [module] + [f"{module}.{a.name}" for a in node.names]
            if any(is_engine_module(n) for n in full):
                execs.append(f"{rel}:{node.lineno} E1 from {module}")
        elif isinstance(node, ast.Call):
            s = first_str(node)
            if s is None or not s.startswith(DOTTED):
                continue
            name = callee(node)
            if name in IMPORT_CALLS:
                call_args.add(id(node.args[0]))
                if rel != RATCHET:
                    execs.append(f"{rel}:{node.lineno} E2 {name}({s!r})")
            elif name in PATCH_CALLS:
                call_args.add(id(node.args[0]))
                execs.append(f"{rel}:{node.lineno} E3 {name}({s!r})")
    docs = docstring_ids(tree)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if id(node) in call_args:
            continue
        dotted = DOTTED in node.value
        path = id(node) not in docs and any(p in node.value for p in PATHS)
        if dotted or path:
            mentions.append(f"{rel}:{node.lineno} {'M' if dotted else 'P'}")
    return execs, mentions


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    if len(sys.argv) > 2:
        rels = Path(sys.argv[2]).read_text(encoding="utf-8").split()
    else:
        rels = subprocess.run(
            ["git", "ls-files", "*.py"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
    rels = [r for r in rels if (root / r).exists()]
    assert len(rels) > 900, f"swept only {len(rels)} files; wrong root?"
    all_execs, outside = [], {}
    for rel in sorted(rels):
        execs, mentions = scan(rel, (root / rel).read_text(encoding="utf-8"))
        all_execs += execs
        if mentions and rel not in ALLOWED:
            outside[rel] = mentions
    print(f"swept {len(rels)} files")
    for line in all_execs:
        print("EXECUTABLE", line)
    for rel, sites in sorted(outside.items()):
        print("MENTION-OUTSIDE-ALLOWED", rel, " ".join(s.split(":", 1)[1] for s in sites))
    ok = not all_execs and not outside
    print("ENGINE-REFS CLEAN" if ok else "ENGINE-REFS FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
```

Create `$X/t13_engine_refs_selftest.py` with exactly this content:

```python
"""B7b Task 13: the sweep catches every kind it claims to (a vacuous sweep passes for free)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from t13_engine_refs import scan  # noqa: E402

REL = "helao/hexagon/tests/test_x.py"
MUST_FLAG = {
    "import helao.core.servers.base": "E1",
    "from helao.core.servers.orch import Orch": "E1",
    "from helao.core import servers": "E1",
    "def f():\n    from ...core.servers import orch": "E1",
    "import importlib\nimportlib.import_module('helao.core.servers.orch')": "E2",
    "__import__('helao.core.servers.base')": "E2",
    "import importlib.util as u\nu.find_spec('helao.core.servers')": "E2",
    "from unittest import mock\nmock.patch('helao.core.servers.base.move_dir')": "E3",
    "def t(monkeypatch):\n    monkeypatch.setattr('helao.core.servers.base.x', 1)": "E3",
    "def t(monkeypatch):\n    monkeypatch.delattr('helao.core.servers.base.x')": "E3",
}
for src, kind in MUST_FLAG.items():
    execs, _ = scan(REL, src)
    assert any(f" {kind} " in e for e in execs), f"missed {kind}: {src!r} -> {execs}"
_, m = scan(REL, "P = 'helao/core/servers/base.py'")
assert m and m[0].endswith(" P"), m
_, m = scan(REL, "X = 'helao.core.servers'")
assert m and m[0].endswith(" M"), m
_, m = scan(REL, '"""Moved from helao/core/servers/orch_api.py by B7a."""')
assert m == [], m
execs, _ = scan(
    "helao/hexagon/tests/test_engine_import_ratchet.py",
    "import importlib.util as u\nu.find_spec('helao.core.servers')",
)
assert execs == [], execs
execs, m = scan(REL, "import helao.core.serversx\nfrom helao.core.models import hlostatus")
assert execs == [] and m == [], (execs, m)
print("T13-SELFTEST PASS")
```

Run:
```
timeout 120 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t13_engine_refs_selftest.py"
```
Expected: `T13-SELFTEST PASS`.

Then record the sweep on the untouched tree (evidence only):
```
timeout 120 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t13_engine_refs_selftest.py"
timeout 300 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t13_engine_refs.py" > "$X/t0_refs.txt"; echo rc=$?
tail -1 "$X/t0_refs.txt"
```
Expected: `T13-SELFTEST PASS`; `rc=1`; `ENGINE-REFS FAIL` (the engine and its importers are all still here).

- [ ] **Step 0.10: pyright on every file B7b modifies and keeps.** Create `$X/pyright_files_before.txt` with exactly these 91 lines (every `.py` file that exists on `64f2cf15`, is modified by some task, and still exists at the end; files B7b deletes are not compared):
```
harness/endpoints.py
harness/openapi_capture.py
harness/ws_frames.py
helao/core/drivers/helao_driver.py
helao/core/rpc/zmq_rpc.py
helao/core/tests/test_active_golden_master.py
helao/core/tests/test_analysis_recovery.py
helao/core/tests/test_bokeh_theme.py
helao/core/tests/test_orch_dispatch_golden_master.py
helao/core/tests/test_orch_queue_paging.py
helao/core/tests/test_palette.py
helao/core/tests/test_run_state_wiring.py
helao/core/tests/test_standalone_operator.py
helao/core/tests/test_upload_set.py
helao/core/tests/unit_test_base_live_buffer.py
helao/core/tests/unit_test_base_status.py
helao/core/tests/unit_test_config_seam.py
helao/core/tests/unit_test_dispatcher.py
helao/core/tests/unit_test_estop_sync.py
helao/core/tests/unit_test_orch_lifecycle.py
helao/core/tests/unit_test_orch_queues.py
helao/core/tests/unit_test_orch_status_sync.py
helao/deploy/hexagon/servers/action/sim_db_server.py
helao/deploy/hexagon/servers/orchestrator/async_orch2.py
helao/deploy/hte/drivers/io/nidaqmx_driver.py
helao/deploy/hte/drivers/mfc/alicat_driver.py
helao/deploy/hte/drivers/motion/galil_motion_driver.py
helao/deploy/hte/drivers/pstat/biologic_backend.py
helao/deploy/hte/drivers/pstat/biologic_eclib2/driver.py
helao/deploy/hte/drivers/pstat/biologic_ole/driver.py
helao/deploy/hte/drivers/pstat/gamry/driver.py
helao/deploy/hte/drivers/pstat/gamry/sink.py
helao/deploy/hte/drivers/pump/legato_driver.py
helao/deploy/hte/drivers/sensor/sprintir_driver.py
helao/deploy/hte/drivers/spec/andor/driver.py
helao/deploy/hte/drivers/spec/spectral_products_driver.py
helao/deploy/hte/drivers/temperature_control/mecom_driver.py
helao/deploy/test/runners/simulatews_runner.py
helao/deploy/test/runners/test_runner.py
helao/helpers/bubble_detection.py
helao/helpers/dispatcher.py
helao/hexagon/adapters/legacy/health.py
helao/hexagon/adapters/legacy/status.py
helao/hexagon/adapters/native/artifact_store.py
helao/hexagon/adapters/native/data_file.py
helao/hexagon/adapters/native/data_stream.py
helao/hexagon/adapters/native/finalizer.py
helao/hexagon/adapters/native/galil_motion.py
helao/hexagon/adapters/native/galil_motion_native.py
helao/hexagon/adapters/native/meta_writer.py
helao/hexagon/adapters/native/ws_publish.py
helao/hexagon/app/action_host.py
helao/hexagon/app/dispatch_loop.py
helao/hexagon/app/factory.py
helao/hexagon/app/ingestion.py
helao/hexagon/app/orch_dispatch.py
helao/hexagon/app/orch_host.py
helao/hexagon/app/orch_payloads.py
helao/hexagon/app/orch_status_sync.py
helao/hexagon/app/orch_wait.py
helao/hexagon/hexconfig.py
helao/hexagon/ports/auxiliary.py
helao/hexagon/ports/status.py
helao/hexagon/tests/live_group.py
helao/hexagon/tests/native_fixtures.py
helao/hexagon/tests/test_action_context.py
helao/hexagon/tests/test_action_host_member_coverage.py
helao/hexagon/tests/test_action_route.py
helao/hexagon/tests/test_action_session_port.py
helao/hexagon/tests/test_concurrency_live.py
helao/hexagon/tests/test_db_shim.py
helao/hexagon/tests/test_dispatch_loop.py
helao/hexagon/tests/test_endpoint_manager.py
helao/hexagon/tests/test_engine_import_ratchet.py
helao/hexagon/tests/test_estop_finish_race.py
helao/hexagon/tests/test_estop_fixes.py
helao/hexagon/tests/test_executor_runner.py
helao/hexagon/tests/test_factory.py
helao/hexagon/tests/test_native_artifact_store.py
helao/hexagon/tests/test_native_data_file.py
helao/hexagon/tests/test_native_data_sink.py
helao/hexagon/tests/test_native_data_stream.py
helao/hexagon/tests/test_native_finalizer.py
helao/hexagon/tests/test_native_meta_writer.py
helao/hexagon/tests/test_orch_host_member_coverage.py
helao/hexagon/tests/test_orch_host_surface.py
helao/hexagon/tests/test_orch_stops_polling_on_shutdown.py
helao/hexagon/tests/test_vis_hexagon_producer_parity.py
helao/hexagon/tests/test_ws_consumer_parity.py
helao/ui/shared/operator/orch_backend.py
run_unit_tests.py
```
Create `$X/t0_pyright_cmp.py`:
```python
"""B7b gate 6: no changed file has more pyright errors than on 64f2cf15, and the run was not vacuous.

Usage: python t0_pyright_cmp.py <before.json> <after.json> <after file list> <before file list>
Every file in the after list must either be in the before list (compared per file)
or be a file B7b added (it must then have 0 errors). A modified file missing
from the before list is reported: the Task 0 list was incomplete.
"""

import json
import subprocess
import sys

WT = "/mnt/STORAGE/repos/helao/helao-b7b"
before = json.load(open(sys.argv[1], encoding="utf-8"))
after = json.load(open(sys.argv[2], encoding="utf-8"))
after_files = open(sys.argv[3], encoding="utf-8").read().split()
before_files = set(open(sys.argv[4], encoding="utf-8").read().split())
added = set(
    subprocess.run(
        ["git", "-C", WT, "diff", "--name-only", "--diff-filter=A", "64f2cf15", "HEAD", "--", "*.py"],
        capture_output=True, text=True, check=True,
    ).stdout.split()
)


def per_file(doc):
    counts = {}
    for diag in doc["generalDiagnostics"]:
        if diag["severity"] == "error":
            rel = diag["file"].split("/helao-b7b/", 1)[1]
            counts[rel] = counts.get(rel, 0) + 1
    return counts


analyzed = after["summary"]["filesAnalyzed"]
assert analyzed == len(after_files) > 0, f"pyright analyzed {analyzed}, expected {len(after_files)}"
b, a = per_file(before), per_file(after)
unlisted = sorted(f for f in after_files if f not in before_files and f not in added)
worse = {f: (b.get(f, 0), a.get(f, 0)) for f in after_files if f in before_files and a.get(f, 0) > b.get(f, 0)}
new_bad = {f: a[f] for f in after_files if f in added and a.get(f, 0)}
print(f"analyzed={analyzed} errors before={before['summary']['errorCount']} after={after['summary']['errorCount']}")
print(f"worse={worse} added_with_errors={new_bad} modified_but_not_in_task0_list={unlisted}")
sys.exit(1 if worse or new_bad or unlisted else 0)
```
Record the baseline, **[tool timeout 600 s]**:
```
cd "$WT" && PYTHONPATH="$WT" xargs -a "$X/pyright_files_before.txt" timeout 590 pyright --outputjson > "$X/pyright_before.json" 2>/dev/null; echo rc=$?
timeout 60 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -c "import json; s = json.load(open('$X/pyright_before.json'))['summary']; print(s['filesAnalyzed'], s['errorCount'])"
```
Expected: `rc=123` (xargs reports pyright's exit 1 as 123), then `91 426` (measured in planning). If the first number is not 91, pyright did not pick up `pyrightconfig.json` or analyzed nothing: STOP.

- [ ] **Step 0.11: Nothing to commit.** `git -C "$WT" status --porcelain` prints nothing: every input copied in is gitignored, and the private copies are gone.

---

### Task 1: The dispatch golden master drives `OrchHost`

**Files:**
- Modify: `helao/core/tests/test_orch_dispatch_golden_master.py` — module docstring (lines 1–96), imports (line 120, after line 124), reference constants (lines 128–131), `_make_orch` (lines 159–165, 263), the 17 `orch: Orch` annotations (lines 275–824), guard and message strings (lines 1457–1461, 1549, 1576–1578, 1619–1626, 1823–1826, 1835, 1852). Line numbers measured on `64f2cf15`.
- Modify: `helao/hexagon/app/action_host.py:192` — one annotation (Plan decision P-A.2).
- Create: `helao/core/tests/golden/dispatch/` — nine tracked `.jsonl` references (Q3).
- Scratch only: `$X/t1_capture.py`, `$X/t1_docstring.txt`, `$X/t1_port.py`, `$X/t1_compare.py`, `$X/t1_no_engine.py`; captures `$X/legacy_dispatch/`, `$X/legacy_dispatch_2/`, `$X/native_dispatch/`, `$X/native_dispatch_2/`.

**Interfaces:**
- Consumes: `OrchHost` (`helao/hexagon/app/orch_host.py`) with `_init_orch_collaborators(self) -> None` (line 232) and `_build_reducer(self) -> None` (line 1388); `PortWiring(logging=..., health=...)` (`helao/hexagon/app/wiring.py`); `LegacyLoggingAdapter()` (`helao/hexagon/adapters/legacy/logging_adapter.py`); `LegacyHealthAdapter()` (`helao/hexagon/adapters/legacy/health.py`). Task 0's `$X` directory.
- Produces: `helao/core/tests/test_orch_dispatch_golden_master.py` with no `helao.core.servers` import; `BASELINE_S0_DIR = Path(__file__).resolve().parent / "golden" / "dispatch"` (name kept, target changed); `_make_orch(tmp_root: Path) -> OrchHost`; `run_all_scenarios(base_dir: Path, tmp_root: Path) -> dict` and `run_check_mode() -> int` unchanged in signature. Tasks 7, 10, 13, 15 and 16 run `python helao/core/tests/test_orch_dispatch_golden_master.py --check` and expect `CHECK PASSED: all 9 scenarios byte-identical to $WT/helao/core/tests/golden/dispatch`. Task 15 part B removes `_make_orch`'s globstat lines.

**Execution:** Parallel-safe with Tasks 2–6: it touches only the two files above and the new `golden/dispatch/` directory, and no other commit-1 task edits `action_host.py` (Task 7 Step 7.0b mutates it briefly, after wave 1, and restores it). Step 1.2 (legacy capture) must run before Step 1.3 edits anything, and the whole task must finish before Task 8 (the engine must still be importable). Never commits; the controller commits in Task 7.

**Note on output:** whenever a command run through `conda run` exits non-zero, conda adds one `ERROR conda.cli.main_run:execute(…): … failed. (See above for error)` line on stderr. The expected outputs below omit it.

**Plan decisions (spec silent):**
- **P-A.1:** The attribute block in `_make_orch` is kept verbatim, as §4.1 step 3 says, including the three globstat lines. They cannot go in commit 1: measured, removing them while `OrchHost.wait_for_interrupt` still feeds `self.globstat_q` (`orch_host.py:1002`) makes every scenario that drains a second interrupt raise `AttributeError: 'OrchHost' object has no attribute 'globstat_q'` (both `--check` and default mode die). They leave in commit 5, together with the feed (fragment below).
- **P-A.2:** `action_host.py:192` gains an annotation: `self.aloop: asyncio.AbstractEventLoop | None = None`. Without it, pyright infers `aloop`'s declared type as `None` (the only other assignment, line 1275, sits in a nested startup function), and the ported harness's twelve `orch.aloop = asyncio.get_running_loop()` lines become errors. Measured: the harness goes from 24 pyright errors on `64f2cf15` to 29 after the port without P-A.2, and to 17 with it. `action_host.py`, `executor_runner.py`, `orch_estop.py`, `orch_lifecycle.py`, `orch_dispatch.py`, `action_session.py` and `orch_host.py` keep exactly their error counts (18/0/1/0/2/4/13). The annotation has no runtime effect. The alternative, twelve `# pyright: ignore` comments in the harness, suppresses a real typing defect in native code instead of fixing it.
- **P-A.3:** The one-time freeze is a guarded `cp` from `$X/native_dispatch/` into a `golden/dispatch/` that must not exist yet (Step 1.8). No `--freeze` mode is added to the harness, so the committed file has no code path that writes the tracked reference; the existing guard in `run_all_scenarios` (it refuses `base_dir == BASELINE_S0_DIR`) keeps pointing at the reference.
- **P-A.4:** The constant keeps the name `BASELINE_S0_DIR`, because §4.1 step 7 names it and `_diff_against_baseline_s0` / `MISSING_S0_REFERENCE` / `EXTRA_S0_REFERENCE` read it. Renaming is cosmetic churn.
- **P-A.5:** Default mode keeps writing its scratch traces to `.omc/artifacts/p5/baseline/` and `queues.pck` to `.omc/artifacts/p5/queues.pck`. Both are gitignored (`.gitignore:33`), so running it in the worktree leaves `git status --short` unchanged.

- [ ] **Step 1.1: Confirm the engine is present and nothing is modified yet.**

```
git -C "$WT" status --short -- helao/core/tests/test_orch_dispatch_golden_master.py helao/hexagon/app/action_host.py
test -e "$WT/helao/core/tests/golden/dispatch" && echo GOLDEN-EXISTS || echo GOLDEN-ABSENT
test -f "$WT/helao/core/servers/orch.py" && echo ENGINE-PRESENT
```
Expected: no output from `git status`, then `GOLDEN-ABSENT`, then `ENGINE-PRESENT`. If either file already shows as modified, STOP: the legacy capture must come from the unmodified harness.

- [ ] **Step 1.2: Capture the legacy references, twice, from the unmodified harness.** Create `$X/t1_capture.py`:

```python
"""B7b Task 1: capture the nine dispatch golden-master traces into a new directory.

Usage: python t1_capture.py <out_dir>
Imports the harness from PYTHONPATH (the worktree) and runs run_all_scenarios().
Refuses to write into an existing directory.
"""

import asyncio
import sys
import tempfile
from pathlib import Path

from helao.core.tests import test_orch_dispatch_golden_master as gm

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=False)
with tempfile.TemporaryDirectory() as tmp_root:
    asyncio.run(gm.run_all_scenarios(out, Path(tmp_root)))
print(f"captured {len(list(out.glob('*.jsonl')))} traces into {out}")
```

Run:
```
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t1_capture.py" "$X/legacy_dispatch"
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t1_capture.py" "$X/legacy_dispatch_2"
diff -r "$X/legacy_dispatch" "$X/legacy_dispatch_2" && echo LEGACY-DETERMINISTIC
```
Expected: `captured 9 traces into $X/legacy_dispatch`, `captured 9 traces into $X/legacy_dispatch_2`, `LEGACY-DETERMINISTIC`. Each capture takes about 5 s. (Measured in the planning dry run: these legacy traces differ from the retired `.omc/artifacts/p5/baseline_S0/` in scenarios 2 and 7 only, as §2.4 records.)

- [ ] **Step 1.3: Write the new module docstring.** Create `$X/t1_docstring.txt` with exactly this content (it becomes lines 1–112 of the harness):

```
"""Dispatch-decision golden-master harness for the native ``OrchHost``
orchestrator (CARDS P5 Stage S0 harness, re-pointed at native code by B7b).

Mirrors the PAL call-trace golden master
(``helao/deploy/hte/tests/test_pal_golden_master.py`` -- ``__new__`` bypass +
fakes + pinned/deterministic timing + recorded ordered JSON-lines trace +
double-capture determinism check) but targets the orchestrator's dispatch
state-machine instead of the PAL driver.

What is REAL (driven, unmodified, the shipped orchestrator code):

* ``OrchHost.dispatch_loop_task`` / ``loop_task_dispatch_sequence`` /
  ``loop_task_dispatch_experiment`` / ``loop_task_dispatch_action`` /
  ``wait_for_interrupt`` / the intent methods (``intend_skip`` /
  ``intend_stop`` / ``intend_estop`` / ``intend_none``) / the global-param
  fold-in and fold-out blocks / ``estop_loop`` / ``estop_actions`` /
  ``finish_active_experiment`` / ``finish_active_sequence`` /
  ``update_status`` / ``update_nonblocking`` / ``GlobalStatusModel``, and
  the seven collaborators plus the reducer runtime those methods delegate to.
* ``OrchHost`` is constructed via ``OrchHost.__new__`` + a minimal attribute
  fixture that bypasses ``__init__`` entirely (no FastAPI app, no disk I/O
  paths, no NTP), then ``_init_orch_collaborators()`` and ``_build_reducer()``
  over a ``PortWiring`` carrying ``LegacyLoggingAdapter`` and
  ``LegacyHealthAdapter`` -- the same bypass strategy the PAL harness uses
  for ``PAL``.

What is FAKED/STUBBED (the harness surface):

* ``async_action_dispatcher`` (module-global rebind on
  ``helao.helpers.dispatcher``) -- records every call as ``(server,
  action_name, ordered params, start_condition, submit_order)`` and returns a
  canned active/finished action dict per the scenario's script. For each
  successful blocking dispatch it also schedules a background "status ping"
  that drives the REAL ``OrchHost.update_status`` with a canned finished
  ``ActionServerModel`` a couple of event-loop ticks later -- this is what
  unblocks ``dispatch_loop_task``'s own ``action_history`` wait-loop and the
  ``ActionStartCondition`` wait predicates using the REAL status-ingestion
  code, without any real network I/O or real wall-clock waiting.
* ``async_private_dispatcher`` -- no-op recorder returning ``({}, none)``.
* ``HelaoSyncer.to_s3`` -- no-op recorder (``self.syncer.to_s3``).
* ``PLATE_API.has_access`` -- forced ``False`` for the harness's duration
  (module-global on ``helao.hexagon.app.orch_unpack``), so the plate-verification
  gate is a no-op in every scenario.
* ``move_dir`` (module-global rebind on ``helao.helpers.yml_tools``) --
  recording no-op (no real file moves).
* ``write_seq`` / ``write_exp`` / ``put_lbuf`` / ``put_lbuf_nowait`` --
  recording no-ops bound directly on the ``OrchHost`` instance (shadowing the
  host methods, which need real ``helaodirs``/disk paths this harness does
  not set up).

No production code is modified by this file.

Determinism notes: every trace entry is built from harness-controlled,
deterministic inputs (server/action names, scripted params, submit_order
counters, enum values). Real ``gen_uuid()``/``set_time()`` calls inside the
driven production code (e.g. stamping ``action_uuid``/``action_timestamp`` on
newly unpacked actions) are deliberately never captured verbatim into the
trace -- the harness only ever records fields it authored or that are
structurally deterministic (counts, enum names, ordered dict keys). This
avoids needing to patch ``gen_uuid``/``time.time`` globally the way the PAL
harness pins ``time.time``/``asyncio.sleep`` -- nothing genuinely random ever
reaches ``json.dumps``.

One genuine pre-existing quirk (not a harness bug, not to be fixed here):
``ActionStartCondition.wait_for_previous`` compares ``self.last_action_uuid``
(a bare *string*, stamped from the dispatcher's returned JSON dict) against
``self.globalstatusmodel.active_dict.keys()`` (*UUID* objects) -- the type
mismatch means this predicate can never observe a match and therefore never
actually blocks in the current code. Scenario 2 drives this branch and
records the (structurally guaranteed) immediate pass-through faithfully
rather than fabricating a block that cannot occur.

Provenance of the frozen reference (B7b, D-B7b.5). The nine traces under
``helao/core/tests/golden/dispatch/`` are native captures. Each was accepted
only after a byte comparison with a capture of the same scenario script
driving the legacy ``Orch`` (``helao/core/servers/orch.py``), taken on the
same commit while that engine still existed. Scenarios 1-6, 8 and 9 were
byte-identical. Scenario 7 differed by exactly one trace block, the
``{"event": "intent_call", "method": "intend_none"}`` entry: legacy
``Orch.estop_loop`` delegated to ``EstopController.estop_loop``, which calls
``intend_none()``, while ``OrchHost.estop_loop`` latches E-STOP through the
reducer and wakes ``interrupt_q`` directly (DD-5 item 6), so the spy on
``intend_none`` never fires. That one block is
the only accepted delta. The older ``.omc/artifacts/p5/baseline_S0/``
reference is retired: it predates the stop-requeue fix (scenario 2) and the
E-STOP-reaches-drivers change (scenario 7), and this file no longer reads it.

Run (conda env ``helao``; not a pytest module -- run as a script, from the
repo root, with the repo root on ``PYTHONPATH``)::

    conda run -n helao --no-capture-output python \\
        helao/core/tests/test_orch_dispatch_golden_master.py [--check]

Two modes:

* Default (no args) -- record/dev mode: runs the semantic
  ``_run_and_check`` assertions plus a byte-identical double-capture
  determinism check, and (re)writes scratch traces to
  ``.omc/artifacts/p5/baseline/<scenario>.jsonl`` (gitignored) for local
  inspection, plus a ``queues.pck`` export/import round-trip fixture at
  ``.omc/artifacts/p5/queues.pck``. This mode never touches
  ``golden/dispatch/``.
* ``--check`` -- the hard gate: captures all 9 scenarios to a temp dir and
  byte-diffs each against the FROZEN reference at
  ``helao/core/tests/golden/dispatch/``, printing per-scenario PASS/DELTA and
  exiting non-zero on any byte difference or missing/extra file. It never
  writes to ``golden/dispatch/``.

``golden/dispatch/`` is tracked and must never be regenerated to make a
change pass -- doing so would let a change silently redefine its own gate.
A deliberate behaviour change re-freezes it in its own commit, with the
argued trace diff in the commit message.
"""
```

- [ ] **Step 1.4: Apply the port.** Create `$X/t1_port.py`. Each replacement must match exactly once, so a drifted file stops the script before it writes anything:

```python
"""B7b Task 1: port the dispatch golden master from legacy Orch to OrchHost.

Usage: python t1_port.py <path to test_orch_dispatch_golden_master.py> <t1_docstring.txt>
Every replacement must match exactly once, or the script stops before writing.
"""

import re
import sys

p = sys.argv[1]
s = open(p, encoding="utf-8").read()
doc_end = s.index('"""\n', 3) + 4
newdoc = open(sys.argv[2], encoding="utf-8").read()
s = newdoc + s[doc_end:]
R = [
("from helao.core.servers.orch import Orch\n", ""),
("from helao.helpers.zdeque import zdeque\n",
 "from helao.helpers.zdeque import zdeque\n"
 "from helao.hexagon.adapters.legacy.health import LegacyHealthAdapter\n"
 "from helao.hexagon.adapters.legacy.logging_adapter import LegacyLoggingAdapter\n"
 "from helao.hexagon.app.orch_host import OrchHost\n"
 "from helao.hexagon.app.wiring import PortWiring\n"),
('''ARTIFACT_DIR = REPO_ROOT / ".omc" / "artifacts" / "p5"
# Frozen S0 reference (captured once, on unmodified orch.py). Never write to
# this directory outside of the one-time freeze step -- it is the hard gate
# every S1-S9 stage's `--check` run diffs against.
BASELINE_S0_DIR = ARTIFACT_DIR / "baseline_S0"
''',
'''# Scratch outputs of the default mode (gitignored).
ARTIFACT_DIR = REPO_ROOT / ".omc" / "artifacts" / "p5"
# Frozen, tracked reference (native captures, accepted by B7b against a legacy
# capture of the same script; see the module docstring). Never write to this
# directory from the harness -- it is the hard gate every `--check` run diffs
# against.
BASELINE_S0_DIR = Path(__file__).resolve().parent / "golden" / "dispatch"
'''),
("# Orch fixture construction (Base.__init__ bypass, mirrors PAL's PAL.__new__)",
 "# OrchHost fixture construction (__init__ bypass, mirrors PAL's PAL.__new__)"),
('''def _make_orch(tmp_root: Path) -> Orch:
    """Build a bare ``Orch`` with every attribute the dispatch cluster touches."""
    orch = Orch.__new__(Orch)
''',
'''def _make_orch(tmp_root: Path) -> OrchHost:
    """Build a bare ``OrchHost`` with every attribute the dispatch cluster touches."""
    orch = OrchHost.__new__(OrchHost)
'''),
('''    orch._init_collaborators()

    return orch
''',
'''    orch._init_orch_collaborators()
    orch.hexagon_wiring = PortWiring(
        logging=LegacyLoggingAdapter(), health=LegacyHealthAdapter()
    )
    orch._build_reducer()
    assert type(orch) is OrchHost

    return orch
'''),
('''    # Guard rail: nothing in this harness may write into the frozen S0
    # reference. It is captured exactly once (on unmodified orch.py) and
    # every subsequent run only ever reads it for comparison.
    assert base_dir.resolve() != BASELINE_S0_DIR.resolve(), (
        "refusing to write into the frozen baseline_S0/ reference; "
''',
'''    # Guard rail: nothing in this harness may write into the frozen
    # reference. Every run only ever reads it for comparison.
    assert base_dir.resolve() != BASELINE_S0_DIR.resolve(), (
        "refusing to write into the frozen golden/dispatch/ reference; "
'''),
("    # persist a canonical copy under the artifact dir for the S1-S9 gates\n",
 "    # persist a scratch copy under the (gitignored) artifact dir\n"),
('''    ``baseline_S0/`` reference. Returns a list of (scenario_name, status,
    detail) tuples; status is one of PASS / DELTA / MISSING_S0_REFERENCE.
    Also reports any extra ``*.jsonl`` files under baseline_S0/ that no
''',
'''    ``golden/dispatch/`` reference. Returns a list of (scenario_name, status,
    detail) tuples; status is one of PASS / DELTA / MISSING_S0_REFERENCE.
    Also reports any extra ``*.jsonl`` files under golden/dispatch/ that no
'''),
('''    """Hard gate for S1-S9: capture fresh traces to a throwaway temp dir
    (never overwriting baseline_S0/) and byte-diff every scenario against
    the frozen ``baseline_S0/`` reference. Returns a process exit code
''',
'''    """Hard gate: capture fresh traces to a throwaway temp dir
    (never overwriting golden/dispatch/) and byte-diff every scenario against
    the frozen ``golden/dispatch/`` reference. Returns a process exit code
'''),
('''        print(f"FATAL: frozen S0 reference dir missing: {BASELINE_S0_DIR}")''',
 '''        print(f"FATAL: frozen reference dir missing: {BASELINE_S0_DIR}")'''),
('''            "against the frozen .omc/artifacts/p5/baseline_S0/ reference. "
            "Never overwrites baseline_S0/. Exits non-zero on any "
            "divergence/missing/extra file. This is the mode run by "
            "every S1-S9 downstream stage."
''',
'''            "against the frozen helao/core/tests/golden/dispatch/ reference. "
            "Never overwrites golden/dispatch/. Exits non-zero on any "
            "divergence/missing/extra file."
'''),
("    # local inspection only; NEVER touches the frozen baseline_S0/ reference\n",
 "    # local inspection only; NEVER touches the frozen golden/dispatch/ reference\n"),
("(NOT the frozen gate -- see baseline_S0/, run with --check to verify against it)",
 "(NOT the frozen gate -- see golden/dispatch/, run with --check to verify against it)"),
]
for a, b in R:
    n = s.count(a)
    assert n == 1, (n, a[:60])
    s = s.replace(a, b)
s, k = re.subn(r"\borch: Orch\b", "orch: OrchHost", s)
assert k == 17, f"expected 17 `orch: Orch` annotations, found {k}"
open(p, "w", encoding="utf-8").write(s)
left = [l for l in s.splitlines() if re.search(r"\bOrch\b", l)]
print("annotation renames:", k, "remaining bare Orch lines:", len(left))
for l in left: print("   ", l)
```

Run it, then format:
```
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t1_port.py" "$WT/helao/core/tests/test_orch_dispatch_golden_master.py" "$X/t1_docstring.txt"
cd "$WT" && black -q helao/core/tests/test_orch_dispatch_golden_master.py
grep -n 'helao.core.servers' "$WT/helao/core/tests/test_orch_dispatch_golden_master.py"
```
Expected, from the script: `annotation renames: 17 remaining bare Orch lines: 2`, followed by the two docstring provenance lines (`driving the legacy ``Orch`` (``helao/core/servers/orch.py``), taken on the` and ``Orch.estop_loop`` delegated to ``EstopController.estop_loop``, which calls`). Black rewraps one signature, `make_fake_action_dispatcher(orch: OrchHost, trace: list, script: Optional[dict] = None)`, onto three lines. The `grep` prints exactly one line, the docstring's provenance mention (`driving the legacy ``Orch`` (``helao/core/servers/orch.py``), taken on the`). No import of the engine remains.

The fixture tail the script produces (lines 285–292 after black) is:
```python
    orch._init_orch_collaborators()
    orch.hexagon_wiring = PortWiring(
        logging=LegacyLoggingAdapter(), health=LegacyHealthAdapter()
    )
    orch._build_reducer()
    assert type(orch) is OrchHost

    return orch
```

- [ ] **Step 1.5: Annotate `aloop` (P-A.2).** In `helao/hexagon/app/action_host.py`, line 192, replace
```python
        self.aloop = None
```
with
```python
        self.aloop: asyncio.AbstractEventLoop | None = None
```
(`asyncio` is already imported there.) Check:
```
sed -n 192p "$WT/helao/hexagon/app/action_host.py"
```
Expected: `        self.aloop: asyncio.AbstractEventLoop | None = None`.

- [ ] **Step 1.6: With no reference yet, `--check` refuses to pass.**
```
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python helao/core/tests/test_orch_dispatch_golden_master.py --check; echo rc=$?
```
Expected: `FATAL: frozen reference dir missing: $WT/helao/core/tests/golden/dispatch`, then `rc=1`.

- [ ] **Step 1.7: Capture natively, twice, and compare against legacy (§4.1 step 6, Q1).** Create `$X/t1_compare.py`:

```python
"""B7b Task 1: compare native dispatch captures against legacy captures.

Usage: python t1_compare.py <legacy_dir> <native_dir>
Exit 0 only if scenarios 1-6, 8, 9 are byte-identical and scenario 7 differs
by exactly one {"event": "intent_call", "method": "intend_none"} block (Q1),
checked twice: as a line diff, and as "native trace == legacy trace with one
such element removed, every other key equal".
"""

import difflib
import json
import sys
from pathlib import Path

S7 = "7_returned_action_error_estop_loop.jsonl"
BLOCK = {"event": "intent_call", "method": "intend_none"}
EXPECTED_REMOVED = [
    '      "event": "intent_call",',
    '      "method": "intend_none"',
    "    },",
    "    {",
]

legacy, native = Path(sys.argv[1]), Path(sys.argv[2])
names = sorted(p.name for p in legacy.glob("*.jsonl"))
assert names == sorted(p.name for p in native.glob("*.jsonl")), "file sets differ"
assert len(names) == 9, f"expected 9 scenarios, found {len(names)}"
bad = []
for name in names:
    lb, nb = (legacy / name).read_bytes(), (native / name).read_bytes()
    if name != S7:
        print(f"  {'IDENTICAL' if lb == nb else 'DIFFERENT'}  {name}")
        if lb != nb:
            bad.append(name)
        continue
    diff = list(
        difflib.unified_diff(
            lb.decode().splitlines(), nb.decode().splitlines(), lineterm="", n=0
        )
    )
    body = [line for line in diff if not line.startswith(("---", "+++", "@@"))]
    added = [line[1:] for line in body if line.startswith("+")]
    removed = [line[1:] for line in body if line.startswith("-")]
    hunks = sum(1 for line in diff if line.startswith("@@"))
    lines_ok = hunks == 1 and added == [] and removed == EXPECTED_REMOVED
    ld, nd = json.loads(lb), json.loads(nb)
    lt, nt = ld.pop("trace"), nd.pop("trace")
    drops = [i for i, e in enumerate(lt) if e == BLOCK and lt[:i] + lt[i + 1 :] == nt]
    struct_ok = ld == nd and len(drops) >= 1
    print(
        f"  {'ONE-BLOCK' if lines_ok and struct_ok else 'DIFFERENT'}  {name}: "
        f"hunks={hunks} removed={len(removed)} added={len(added)} "
        f"dropped_trace_index={drops}"
    )
    if not (lines_ok and struct_ok):
        bad.append(name)
print("COMPARE PASS" if not bad else f"COMPARE FAIL: {bad}")
sys.exit(1 if bad else 0)
```

Run:
```
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t1_capture.py" "$X/native_dispatch"
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t1_capture.py" "$X/native_dispatch_2"
diff -r "$X/native_dispatch" "$X/native_dispatch_2" && echo NATIVE-DETERMINISTIC
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t1_compare.py" "$X/legacy_dispatch" "$X/native_dispatch" > "$X/t1_compare.txt"; echo rc=$?; cat "$X/t1_compare.txt"
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t1_compare.py" "$X/legacy_dispatch" "$X/legacy_dispatch_2" > "$X/t1_compare_selftest.txt"; echo selftest rc=$?
```
Expected: the two `captured 9 traces into …` lines, `NATIVE-DETERMINISTIC`, `rc=0`, then exactly (the content of `$X/t1_compare.txt`, which gate 2 re-reads):
```
  IDENTICAL  1_plain_two_experiment_sequence_no_wait.jsonl
  IDENTICAL  2_every_action_start_condition.jsonl
  IDENTICAL  3_to_global_params_list_and_dict_fold_in.jsonl
  IDENTICAL  4_loop_intent_stop_pending_requeue.jsonl
  IDENTICAL  5_loop_intent_skip.jsonl
  IDENTICAL  6_dispatch_failure_pause_requeue.jsonl
  ONE-BLOCK  7_returned_action_error_estop_loop.jsonl: hunks=1 removed=4 added=0 dropped_trace_index=[16]
  IDENTICAL  8_nonblocking_action_lifecycle.jsonl
  IDENTICAL  9_step_thru_flags.jsonl
COMPARE PASS
```
and `selftest rc=1`: legacy against legacy has no S7 delta, so the comparator cannot pass vacuously. The dropped element is the first of the legacy trace's two `intend_none` intent calls (indices 16 and 22), the one `EstopController.estop_loop` makes (`orch_estop.py:88`). Any other result is a delta that is not Q1's: STOP and escalate it. Do not re-baseline.

- [ ] **Step 1.8: Privacy-grep and freeze the native captures (Q3, P-A.3).**
```
grep -rlE "/home/|/mnt/|/tmp/" "$X/native_dispatch"; grep -rlw -e "$(hostname)" -e "$(id -un)" "$X/native_dispatch"; echo privacy-grep-done
test ! -e "$WT/helao/core/tests/golden/dispatch" && mkdir -p "$WT/helao/core/tests/golden/dispatch" && cp "$X/native_dispatch/"*.jsonl "$WT/helao/core/tests/golden/dispatch/" && echo FROZEN
find "$WT/helao/core/tests/golden/dispatch" -name '*.jsonl' | wc -l
git -C "$WT" check-ignore helao/core/tests/golden/dispatch/1_plain_two_experiment_sequence_no_wait.jsonl; echo ignore rc=$?
```
Expected: only `privacy-grep-done` (no file with a hit), `FROZEN`, `9`, `ignore rc=1` (not ignored, so it will be tracked). If `FROZEN` does not print, the directory already existed: STOP.

- [ ] **Step 1.9: `--check` and default mode pass natively (§4.1 check, first bullet).**
```
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python helao/core/tests/test_orch_dispatch_golden_master.py --check; echo rc=$?
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python helao/core/tests/test_orch_dispatch_golden_master.py > "$X/t1_default.txt" 2>&1; echo rc=$?
tail -4 "$X/t1_default.txt"
```
Expected: nine `  PASS   <scenario>` lines, `CHECK PASSED: all 9 scenarios byte-identical to $WT/helao/core/tests/golden/dispatch`, `rc=0` (about 5 s). Then `rc=0` (about 15 s) and:
```
ALL 9 SCENARIO CHECKS PASSED (1-9) + queues.pck fixture
Dev/record-mode scratch traces written to: $WT/.omc/artifacts/p5/baseline (NOT the frozen gate -- see golden/dispatch/, run with --check to verify against it)
DETERMINISM CHECK PASSED: two capture runs byte-identical for all 9 scenarios
ALL GOLDEN-MASTER HARNESS CHECKS PASSED
```
No semantic assertion in `_run_and_check` needs an edit: scenario 7's checks are `loop_state == "estopped"`, `estop_loop_called` and `estop_dispatch_count >= 1`, and none of them reads `intend_none`.

- [ ] **Step 1.10: No engine module is loaded by a native run (§4.1 check, last bullet).** Create `$X/t1_no_engine.py`:

```python
"""B7b Task 1: after a full native run of the dispatch golden master, no engine module is loaded."""

import asyncio
import sys
import tempfile
from pathlib import Path

from helao.core.tests import test_orch_dispatch_golden_master as gm

with tempfile.TemporaryDirectory() as out, tempfile.TemporaryDirectory() as tmp:
    asyncio.run(gm.run_all_scenarios(Path(out), Path(tmp)))
    asyncio.run(gm.capture_queues_pck_fixture(Path(tmp) / "pck"))
engine = sorted(m for m in sys.modules if m.startswith("helao.core.servers"))
print(f"engine modules after native run: {engine}")
sys.exit(1 if engine else 0)
```

```
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t1_no_engine.py"; echo rc=$?
```
Expected: `engine modules after native run: []`, `rc=0`. (Measured in the dry run against the unported harness, the same script lists `helao.core.servers`, `helao.core.servers.active_data_file`, … and exits 1, so the check is falsifiable.)

- [ ] **Step 1.11: pyright on the two changed files.**
```
cd "$WT" && timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" pyright --outputjson helao/core/tests/test_orch_dispatch_golden_master.py helao/hexagon/app/action_host.py > "$X/t1_pyright.json"; echo rc=$?
timeout 60 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -c "import json, collections; d = json.load(open('$X/t1_pyright.json')); print(d['summary']['filesAnalyzed'], sorted(collections.Counter(x['file'].rsplit('/', 1)[1] for x in d['generalDiagnostics'] if x['severity'] == 'error').items()))"
```
Expected: `rc=1` (errors exist before and after; conda also prints its `ERROR conda.cli.main_run … failed` line), then `2 [('action_host.py', 18), ('test_orch_dispatch_golden_master.py', 17)]`. Task 0 records 18 and 24 for these files; neither may rise.

- [ ] **Step 1.12: The worktree holds only this task's changes.**
```
git -C "$WT" status --short -- helao/core/tests helao/hexagon/app/action_host.py
```
Expected, exactly (other tasks' files may also appear if they ran in parallel, but none under these paths):
```
 M helao/core/tests/test_orch_dispatch_golden_master.py
 M helao/hexagon/app/action_host.py
?? helao/core/tests/golden/
```

**Files for the controller's commit:**
- `helao/core/tests/test_orch_dispatch_golden_master.py` (modified)
- `helao/hexagon/app/action_host.py` (modified, one line)
- `helao/core/tests/golden/dispatch/1_plain_two_experiment_sequence_no_wait.jsonl` … `9_step_thru_flags.jsonl` (9 added; `git add helao/core/tests/golden/dispatch`)

---

### Task 2: The action golden master drives `ActionSession` over an `ActionHost`

**Files:**
- Modify: `helao/core/tests/test_active_golden_master.py` (1,487 lines on `64f2cf15`):
  - lines 1–96: module docstring, replaced whole;
  - lines 109–123: import block;
  - lines 125–130: `REPO_ROOT` / `ARTIFACT_DIR` / `BASELINE_S0A_DIR`;
  - lines 493–619: the `Base` fixture section and `_PatchedBaseGlobals`, replaced whole;
  - lines 918–948: `_scenario_error_estop` (the Q2 edit, step 2.1);
  - 13 `_make_base(save_root, trace)` and 13 `Active(base, ` call sites, the `finish_all()` call (l.867), the `substitute()` call (l.899), and the annotations at l.668 and l.690;
  - comment/message lines 643, 710, 1101–1104, 1183–1184, 1331, 1349, 1375, 1381–1382, 1421, 1462, 1468–1469, 1474–1475.
- Create: `helao/core/tests/golden/action/` — 13 `<scenario>.trace.jsonl` + 13 `<scenario>.runs.norm` (26 files, 32,652 bytes measured).
- Scratch (never committed): `$X/t2_capture.py`, `$X/t2_compare.py`, `$X/t2_redcheck.py`, `$X/t2_no_engine.py`; captures `$X/legacy_action/`, `$X/legacy_action_2/`, `$X/native_action/`; records `$X/t2_q2_vs_omc.txt`, `$X/t2_red_legacy.txt`, `$X/t2_red_native.txt`, `$X/t2_native_vs_legacy.txt`.

**Interfaces:**
- Consumes: nothing from earlier tasks. Task 0's port check and the `helao.__file__` check.
- Produces (module `helao.core.tests.test_active_golden_master`; unchanged names keep their signatures):
  - `BASELINE_S0A_DIR: Path = Path(__file__).resolve().parent / "golden" / "action"`
  - `_make_host(save_root: Path, trace: list) -> ActionHost` (replaces `_make_base`)
  - `_PATCH_TARGETS: tuple[tuple[ModuleType, str], ...]` — the seven `(module, name)` pairs the patch rebinds; `_PatchedBaseGlobals(trace)` iterates it.
  - unchanged: `SCENARIOS`, `capture_all(tmp_root: Path) -> dict`, `_capture_scenario(name, tmp_root) -> tuple[str, str]`, `_compare_norm(name, ref_text, cur_text) -> list[str]`, `_write_baseline(target, captured)`, `run_freeze()`, `run_check()`, `run_determinism_selftest()`, CLI `--check` / `--freeze` / default.
  - Task 13 and gate 2 run `--check` against `golden/action/`; Task 12 deletes the engine, after which this file must still pass (measured: `--check` passes with `helao/core/servers` moved away).

**Execution:** Parallel-safe with Tasks 1, 3, 4, 5 and 6 (no wave-1 task mutates a production file; the two mutation probes run later, in Task 7 Steps 7.0a and 7.0b): it edits only `test_active_golden_master.py` and creates only `golden/action/`. It must not edit any production module; the legacy-versus-native comparison is only meaningful while `helao/core/servers/` and every `helao/hexagon/` module are at `64f2cf15`. The one production edit commit 1 makes, Task 1's annotation on `action_host.py:192`, has no runtime effect. Step 2.7 (the red-check) makes the real private dispatcher POST to `127.0.0.1:8000`, so it must not overlap anything that binds port 8000 (Task 16's launch smoke, `live_group` users). The implementer never runs `git add`/`commit`.

Plan decision P-B.1 (default; the spec allows either): the fixture is `ActionHost.__new__` plus an attribute block, not real construction. Real construction was measured to add four things the legacy reference never had, all under the snapshotted root or in the written YAML: a `gethostname()` machine name (host-dependent and a privacy leak into `-act.yml`), the run-root scaffold directories, a run-state journal (`STATES/`, appended by `record_active`) and a `LOGS/` file logger. Each would need an override after construction, and an override is a silent divergence; the attribute block is the same strategy as the legacy fixture and the dispatch golden master's `OrchHost.__new__`. The host's two ports are the production classes (`LegacyClockAdapter`, `NativeArtifactStoreAdapter`, as `factory.build_wiring` composes them).

Plan decision P-B.2 (default; spec silent): the scenarios keep their local names `base` and `active`; only the constructors change (`_make_host`, `ActionSession(base, ...)`). `ActionSession.base` is the host and the native collaborators call the session `self.active`, so the names stay accurate, and the diff stays mechanical.

Plan decision P-B.3 (default; extends spec §4.1 step 4): `_PATCH_TARGETS` has seven entries: the spec's five (`finalizer.move_dir`, `finalizer.async_private_dispatcher`, `finalizer.set_time`, `artifact_store.move_dir`, `action_host.async_private_dispatcher`) plus `premodels.set_time` and `adapters/legacy/clock.set_time`. The last is not in the spec: `LegacyClockAdapter` binds `set_time` at import (`adapters/legacy/clock.py:13`), and the fixture wires that clock. `async_copy` is dropped: `base.py:69` imports it and nothing uses it, and it appears in neither the old `.omc` reference nor the new captures (grep: 0 files).

Plan decision P-B.4 (default; spec silent on mechanics): the red-check is a scratch script that replaces `gm._PATCH_TARGETS` in-process and runs each scenario in its own event loop under a 30 s bound. A plain `--check` with the legacy patch list never returns: scenarios 8 and 12 export global params through the REAL private dispatcher to `127.0.0.1:8000`, which retries with 30/60/90 s back-off (measured: still retrying after 3 minutes). The red criterion is rc 1 with every non-hanging scenario DELTA and its `move_dir` count dropping to 0.

Plan decision P-B.5 (default; spec silent): the tracked reference is written by the harness's own `--freeze` (a fresh native capture, through the existing refuse-to-overwrite guard), not copied from scratch. The acceptance gate is then `t2_compare.py $X/legacy_action golden/action` = 13 PASS. `diff -r $X/native_action golden/action` is recorded too; it was empty in the dry run (captures are byte-stable), and a non-empty diff there with 13 PASS is not a failure, because `.hlo` data lines are compared as multisets.

- [ ] **Step 2.1: The Q2 edit — scenario 5 stops calling `set_error`.** In `helao/core/tests/test_active_golden_master.py`, inside `_scenario_error_estop` (l.918–948), replace

```python
        await active.set_error(ErrorCodes.critical_error)
        trace.append(
            {
                "event": "post_set_error",
                "action_status": _status_list(active.action),
                "error_code": _json_safe(active.action.error_code),
            }
        )
        active.set_estop()
```
with
```python
        active.set_estop()
```
Nothing else in the file changes in this step. `ErrorCodes` stays imported (the fake dispatcher uses it).

- [ ] **Step 2.2: Write the scratch tools.** Create `$X/t2_capture.py`:

```python
"""B7b Task 2: capture all 13 action golden-master scenarios into a NEW directory.

Usage: python t2_capture.py <out_dir>
Run from the worktree root (hlo_version resolves through `git rev-parse` in the
current directory). Writes <scenario>.trace.jsonl and <scenario>.runs.norm per
scenario, in the golden master's own formats, via its own _write_baseline.
"""

import asyncio
import sys
import tempfile
from pathlib import Path

import helao.core.tests.test_active_golden_master as gm

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=False)
with tempfile.TemporaryDirectory() as tmp_root:
    captured = asyncio.run(gm.capture_all(Path(tmp_root)))
gm._write_baseline(out, captured)
print(f"captured {len(captured)} scenarios into {out}")
```

Create `$X/t2_compare.py`:

```python
"""B7b Task 2: compare two action golden-master capture directories.

Usage: python t2_compare.py <reference_dir> <candidate_dir>
Uses the golden master's own rules: trace bytes exact; runs.norm manifest and
non-.hlo text exact; .hlo header exact plus per-key and whole-record value
multisets (_compare_norm). Prints PASS/DELTA per scenario; exit 1 on any DELTA,
missing or extra file.
"""

import sys
from pathlib import Path

import helao.core.tests.test_active_golden_master as gm

ref, cur = Path(sys.argv[1]), Path(sys.argv[2])
expected = {f"{n}.trace.jsonl" for n in gm.SCENARIOS} | {
    f"{n}.runs.norm" for n in gm.SCENARIOS
}
bad = False
for d in (ref, cur):
    names = {p.name for p in d.iterdir()}
    if names != expected:
        print(f"  FILESET  {d}: missing={sorted(expected - names)} extra={sorted(names - expected)}")
        bad = True
for name in gm.SCENARIOS:
    failures = []
    t_ref = (ref / f"{name}.trace.jsonl").read_text()
    t_cur = (cur / f"{name}.trace.jsonl").read_text()
    if t_ref != t_cur:
        failures.append(f"[{name} trace] byte diff")
    failures.extend(
        gm._compare_norm(
            name,
            (ref / f"{name}.runs.norm").read_text(),
            (cur / f"{name}.runs.norm").read_text(),
        )
    )
    if failures:
        bad = True
        print(f"  DELTA    {name}")
        for f in failures:
            print(f"             {f}")
    else:
        print(f"  PASS     {name}")
print("COMPARE FAILED" if bad else f"COMPARE PASSED: {len(gm.SCENARIOS)} scenarios")
sys.exit(1 if bad else 0)
```

Create `$X/t2_redcheck.py`:

```python
"""B7b Task 2 red-check: does the patch list intercept anything?

Usage: python t2_redcheck.py legacy|native <reference_dir>   (from the worktree root)

legacy: swap the golden master's _PATCH_TARGETS for the ENGINE module globals
        only (helao.core.servers.base, helao.core.servers.active_finalizer). The
        native session path never reads those, so the real move_dir, private
        dispatcher and wall clock run. The result must be RED.
native: _PATCH_TARGETS as committed. The result must be 13 PASS.

Each scenario runs in its own event loop under a 30 s bound, so a real
dispatcher retrying against an absent orchestrator reports HANG instead of
stalling the run. Comparison rules are the golden master's own (_compare_norm
plus exact trace bytes). Nothing is written to the tracked reference.
"""

import asyncio
import sys
import tempfile
from pathlib import Path

import helao.core.tests.test_active_golden_master as gm

mode, ref = sys.argv[1], Path(sys.argv[2])
if mode == "legacy":
    import helao.core.servers.active_finalizer as legacy_finalizer
    import helao.core.servers.base as legacy_base

    gm._PATCH_TARGETS = (
        (legacy_base, "move_dir"),
        (legacy_base, "async_private_dispatcher"),
        (legacy_base, "set_time"),
        (legacy_finalizer, "move_dir"),
        (legacy_finalizer, "async_private_dispatcher"),
        (legacy_finalizer, "set_time"),
    )
elif mode != "native":
    raise SystemExit(f"unknown mode {mode!r}")

red = 0
with tempfile.TemporaryDirectory() as tmp_root:
    for name in gm.SCENARIOS:
        try:
            trace, runs = asyncio.run(
                asyncio.wait_for(gm._capture_scenario(name, Path(tmp_root)), 30)
            )
        except TimeoutError:
            print(f"  HANG     {name}")
            red += 1
            continue
        failures = []
        ref_trace = (ref / f"{name}.trace.jsonl").read_text()
        if trace != ref_trace:
            failures.append(
                "trace byte diff; move_dir events"
                f" reference={ref_trace.count('\"move_dir\"')}"
                f" this run={trace.count('\"move_dir\"')}"
            )
        failures += gm._compare_norm(name, (ref / f"{name}.runs.norm").read_text(), runs)
        print(f"  {'DELTA' if failures else 'PASS '}    {name}")
        for f in failures:
            print(f"             {f}")
        red += bool(failures)
print(f"{mode}: {red} of {len(gm.SCENARIOS)} scenarios red")
sys.exit(1 if red else 0)
```

Create `$X/t2_no_engine.py`:

```python
"""B7b Task 2: a native run of the action golden master loads no engine module.

Usage: python t2_no_engine.py   (from the worktree root)
Runs all 13 scenarios in-process, then lists every loaded helao.core.servers*
module. Exit 1 if any is loaded.
"""

import asyncio
import sys
import tempfile
from pathlib import Path

import helao.core.tests.test_active_golden_master as gm

with tempfile.TemporaryDirectory() as tmp_root:
    captured = asyncio.run(gm.capture_all(Path(tmp_root)))
engine = sorted(m for m in sys.modules if m.startswith("helao.core.servers"))
print(f"scenarios run: {len(captured)}; engine modules loaded: {engine}")
sys.exit(1 if engine else 0)
```

- [ ] **Step 2.3: Capture the LEGACY reference twice (engine fixture, Q2 edit only).**

```
timeout 900 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t2_capture.py" "$X/legacy_action" 2>/dev/null
timeout 900 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t2_capture.py" "$X/legacy_action_2" 2>/dev/null
diff -r "$X/legacy_action" "$X/legacy_action_2" && echo LEGACY-DETERMINISTIC
/bin/ls "$X/legacy_action" | wc -l
git -C "$WT" status --short
```
Expected: `captured 13 scenarios into …/legacy_action`, the same for `legacy_action_2` (about 9 s each), `LEGACY-DETERMINISTIC`, `26`, and `git status` showing only ` M helao/core/tests/test_active_golden_master.py` (plus any other in-flight commit-1 task's files). If the two captures differ, STOP.

- [ ] **Step 2.4: Evidence that the Q2 edit changed scenario 5 only.** Compare the fresh legacy capture with the old gitignored reference, read-only from the main checkout:

```
timeout 300 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t2_compare.py" "$MAIN/.omc/artifacts/p6/baseline_S0a" "$X/legacy_action" > "$X/t2_q2_vs_omc.txt" 2>/dev/null; echo rc=$?
cat "$X/t2_q2_vs_omc.txt"
diff "$MAIN/.omc/artifacts/p6/baseline_S0a/5_error_estop.trace.jsonl" "$X/legacy_action/5_error_estop.trace.jsonl"
```
Expected: `rc=1`; 12 `PASS` lines and exactly one DELTA:
```
  DELTA    5_error_estop
             [5_error_estop trace] byte diff
             [5_error_estop text] RUNS_ACTIVE/None/0__0__ACTSRV__errst/<DIRTS:0>-act.yml
```
and the trace diff consists only of the removed `post_set_error` record (`"error_code": "critical_error"`) and two removed `"errored"` entries in the later `action_status` lists. Any other DELTA means the legacy harness drifted before the port: STOP and escalate.

- [ ] **Step 2.5: Port the harness to the native host.** Four edits, all in `helao/core/tests/test_active_golden_master.py`.

(a) Replace the module docstring, lines 1–96 (from the opening `"""Output golden-master harness for the legacy ``Active`` action wrapper` through its closing `"""`), with:

```python
"""Output golden master for the native action session.

Freezes the observable output of :class:`helao.hexagon.app.action_session.ActionSession`
over an :class:`helao.hexagon.app.action_host.ActionHost` -- the side-effect
trace and every file the session writes -- so any change to the native write
path that alters what lands on disk or on the status/data queues fails
``--check``. Test/harness code only: no production module is modified here.

Provenance. Until B7b this harness drove the legacy ``Active`` over a legacy
``Base`` (CARDS P6 S0a) against a gitignored ``.omc/`` reference. B7b re-pointed
it before deleting the engine. On the B7b commit, with the engine still
present, the same script was captured twice with the legacy fixture and twice
with this native one; each pair was byte-identical, and the native capture
matched the legacy one on all 13 scenarios under this file's own rules
(below). Only then was the native capture frozen as the tracked reference in
``golden/action/``. A red-check (patching the engine module globals instead of
the native ones) failed 13 of 13 scenarios, proving the patch list intercepts.
One scenario was edited first, on both sides: ``5_error_estop`` no longer calls
``set_error`` or records ``post_set_error``. ``set_error`` existed only on the
legacy ``Active`` and died with it; no native or deployment code calls it.

What is REAL (driven, unmodified):

* ``ActionSession.__init__`` / ``myinit`` / ``enqueue_data`` /
  ``enqueue_data_dflt`` / ``enqueue_data_nowait`` / ``log_data_task`` /
  ``write_file`` / ``split`` / ``set_estop`` / ``finish`` /
  ``send_nonblocking_status`` / ``start_executor`` / ``oneoff_executor``, and
  ``NativeActionFinalizer.substitute`` / ``finish_all`` (reached through
  ``session.action_finalizer``; the session exposes neither), with their
  transitive calls into the native data streamer, data-file writer, finalizer
  and meta writer, and into ``ActionHost.write_act`` / ``write_exp`` /
  ``write_seq`` / ``get_realtime`` / ``new_file_conn_key`` /
  ``dflt_file_conn_key``.
* The host's ports are the production composition's classes
  (``LegacyClockAdapter``, ``NativeArtifactStoreAdapter``), wired through a
  ``PortWiring``.
* ``ActionHost`` is built via ``ActionHost.__new__`` plus a minimal attribute
  fixture (``_make_host``), bypassing ``__init__`` -- the strategy the dispatch
  golden master uses for ``OrchHost``. Real construction would add a
  ``gethostname()`` machine name, scaffold directories, a run-state journal and
  a log file under the snapshotted root, none of which the reference has.

What is FAKED/STUBBED (the harness surface):

* ``status_q`` / ``data_q`` -- REAL ``MultisubscriberQueue`` subclasses
  (``_RecordingMSQ``) that additionally append a JSON-safe record of each
  ``put``/``put_nowait`` to the ordered side-effect trace. ``data_q`` still
  fans packets out to the REAL ``log_data_task`` subscriber (so .hlo files are
  written by production code); it only records data packets that actually
  carry data (``datamodel.data`` non-empty), because ``finish()``'s housekeeping
  "finished/empty" packets are emitted a nondeterministic number of times (its
  retry loop re-enqueues one until the data logger flips the stream status,
  which depends on event-loop scheduling relative to a real ``sleep(0.1)``).
  The .hlo file bytes remain the authoritative record of streamed data.
* ``move_dir`` / ``async_private_dispatcher`` / ``set_time`` -- recording
  no-ops or a fixed clock, rebound on every module in ``_PATCH_TARGETS``. Each
  of those binds the name at import, so patching only the helper module that
  defines it would intercept nothing.
* ``host.driver`` -- ``None`` (stored by the session but never exercised by the
  driven lifecycle).

Determinism. Two independent nondeterminism sources reach the output and are
handled as follows:

1. UUIDs, wall-clock timestamps, epoch-ns header stamps, and the git-SHA
   ``hlo_version`` token. ``split`` force-reinits a fresh action (new
   ``gen_uuid``), and HLO headers stamp ``epoch_ns`` from the clock port. Every
   captured artifact is therefore NORMALIZED with a P3-style scrubber: each
   distinct uuid/timestamp/epoch token is mapped to a stable per-run,
   per-artifact sequential placeholder (``<UUID:0>``, ``<ISOTS:0>``,
   ``<EPOCHNS:0>`` ...) by first-appearance order, and ``hlo_version`` /
   ``*codehash`` values are elided to fixed placeholders. Construction
   ids/timestamps are also seeded deterministically (``_mk_action``) for
   readability, but correctness depends only on structural stability.
2. Async flush/chunk boundaries in streamed ``.hlo`` data. ``--check`` compares
   ``.hlo`` files by (a) NORMALIZED header bytes (exact), (b) per-data-key VALUE
   MULTISETS of the JSON data lines, and (c) a WHOLE-RECORD MULTISET that
   explodes each parallel-list data line into position-paired per-index records
   -- never raw-line equality, so a chunk split at a different offset still
   compares equal. Non-``.hlo`` files (``-act.yml`` / ``-exp.yml`` /
   ``-seq.yml``) and the side-effect trace are compared as exact normalized
   bytes.

The ``hlo_version`` trap. ``hlo_version`` resolves through ``git rev-parse`` in
the CURRENT directory (``helao/core/version.py``). Run from anywhere that is
not a git checkout it comes back empty and drops out of every ``-act.yml`` and
``.hlo`` header, and all 13 scenarios report DELTA. Always run this file from
the repository root.

Reference: ``golden/action/`` (next to this file) holds one
``<scenario>.trace.jsonl`` (normalized side-effect trace) and one
``<scenario>.runs.norm`` (normalized snapshot of every file written under the
scenario's root) per scenario. ``run_freeze`` refuses to overwrite a non-empty
reference and ``_write_baseline`` asserts against it.

Run from the repository root, in the ``helao`` conda env::

    python helao/core/tests/test_active_golden_master.py            # determinism self-test
    python helao/core/tests/test_active_golden_master.py --check    # the gate
    python helao/core/tests/test_active_golden_master.py --freeze   # one-time; refuses if frozen

It does real (temp-dir) file I/O, so it is a standalone script: ``run_tests.py``
reports it as NOTESTS and ``run_unit_tests.py`` does not register it.
"""
```

(b) Replace the import block

```python
import helao.core.servers.active_finalizer as finalizer_module
import helao.core.servers.base as base_module
import helao.helpers.premodels as premodels_module
```
with
```python
import helao.helpers.premodels as premodels_module
import helao.hexagon.adapters.legacy.clock as clock_module
import helao.hexagon.adapters.native.artifact_store as artifact_store_module
import helao.hexagon.adapters.native.finalizer as finalizer_module
import helao.hexagon.app.action_host as action_host_module
```
delete the line `from helao.core.servers.base import Active, Base`, and after `from helao.helpers.premodels import Action` add
```python
from helao.hexagon.adapters.legacy.clock import LegacyClockAdapter
from helao.hexagon.adapters.native.artifact_store import NativeArtifactStoreAdapter
from helao.hexagon.app.action_host import ActionHost
from helao.hexagon.app.action_session import ActionSession
from helao.hexagon.app.wiring import PortWiring
```

(c) Replace
```python
REPO_ROOT = Path(__file__).resolve().parents[3]
ARTIFACT_DIR = REPO_ROOT / ".omc" / "artifacts" / "p6"
# Frozen S0a reference (captured once, on unmodified base.py). Never write here
# outside the one-time --freeze step -- it is the hard gate later P6 stages diff
# against.
BASELINE_S0A_DIR = ARTIFACT_DIR / "baseline_S0a"
```
with
```python
# Tracked native reference (B7b): frozen once with --freeze from a native
# capture that was first compared, scenario by scenario, against a legacy
# capture of the same script on the same commit. Never regenerate it to make a
# delta go away -- it is the hard gate.
BASELINE_S0A_DIR = Path(__file__).resolve().parent / "golden" / "action"
```

(d) Replace everything from the `# ----` rule above `# Base fixture (Base.__init__ bypass, mirrors P5's Orch.__new__)` (l.493) through the `        return False` that ends `_PatchedBaseGlobals.__exit__` (l.619) with:

```python
# ---------------------------------------------------------------------------
# host fixture (ActionHost.__init__ bypass, mirrors the dispatch golden
# master's OrchHost.__new__)
# ---------------------------------------------------------------------------


def _make_host(save_root: Path, trace: list) -> ActionHost:
    """Build a bare ``ActionHost`` with every attribute the session path touches.

    ``ActionHost.__init__`` is bypassed on purpose: real construction resolves
    the machine name from ``gethostname()``, creates the run-root scaffold
    directories and a run-state journal under ``root``, and starts a file logger
    there. The snapshot walks that same tree, so each of those would show up as
    a delta against the legacy reference, which never had them.
    """
    host = ActionHost.__new__(ActionHost)
    host.driver = None
    host.server = MachineModel(
        server_name=SERVER_NAME, machine_name=MACHINE, hostname="127.0.0.1", port=8000
    )
    host.world_cfg = {
        "dummy": False,
        "simulation": False,
        "root": str(save_root.parent),
    }
    host.ntp_offset = NTP_OFFSET
    host.helaodirs = SimpleNamespace(save_root=str(save_root))
    host.aloop = asyncio.get_running_loop()

    # The production composition's clock and artifact store (factory.py
    # build_wiring); the store is what hands each session its native
    # collaborators and the host its meta writer.
    clock = LegacyClockAdapter(NTP_OFFSET)
    store = NativeArtifactStoreAdapter(clock=clock)
    host.hexagon_wiring = PortWiring(clock=clock, artifact_store=store)
    host.meta_writer = store.meta_writer_for(host)

    host.status_q = _RecordingMSQ(_status_record, trace)
    host.data_q = _RecordingMSQ(_data_record, trace)
    host.status_clients = set()

    host.actives = {}
    host.history = DequeDict(maxlen=200)
    host.executors = {}
    host.local_action_task_queue = []
    host.prefinish_hooks = HookSet.empty()
    host.live_q = MultisubscriberQueue()
    host.live_buffer = {}
    return host


# ---------------------------------------------------------------------------
# module-global patches on the native modules that bind the seams at import
# ---------------------------------------------------------------------------

#: Every (module, name) the patch rebinds. Each native module below binds the
#: seam at import (``from ... import name``), so patching the defining helper
#: module alone would intercept nothing. Re-grep before editing:
#: ``grep -rn "import.*\(move_dir\|async_private_dispatcher\|set_time\)" helao/hexagon``.
_PATCH_TARGETS = (
    (finalizer_module, "move_dir"),
    (finalizer_module, "async_private_dispatcher"),
    (finalizer_module, "set_time"),
    (artifact_store_module, "move_dir"),
    (action_host_module, "async_private_dispatcher"),
    (clock_module, "set_time"),
    (premodels_module, "set_time"),
)


class _PatchedBaseGlobals:
    """Patch the disk/network/clock module-globals the session path calls."""

    def __init__(self, trace: list):
        self._trace = trace
        self._orig = {}

    def __enter__(self):
        def _fixed_set_time(offset: float = 0):
            return _FIXED_DT

        async def _fake_move_dir(hobj, base=None, retry_delay=5):
            self._trace.append(
                {
                    "event": "move_dir",
                    "action_uuid": str(getattr(hobj, "action_uuid", None)),
                }
            )
            return None

        async def _fake_private_dispatcher(
            server_key,
            host,
            port,
            private_action,
            params_dict=None,
            json_dict=None,
            **kwargs,
        ):
            self._trace.append(
                {
                    "event": "private_dispatch",
                    "action": private_action,
                    "json_keys": sorted((json_dict or {}).keys()),
                    # record the EXPORTED VALUES (not just key names) so the
                    # global-param fold-out is frozen by value, and the dict-form
                    # rename mapping (k1 -> k2) is observable (which OUTPUT key
                    # carries which value). JSON-safe + key-sorted for stable text.
                    "json_values": {
                        str(k): _json_safe(v)
                        for k, v in sorted((json_dict or {}).items())
                    },
                }
            )
            return {}, ErrorCodes.none

        fakes = {
            "move_dir": _fake_move_dir,
            "async_private_dispatcher": _fake_private_dispatcher,
            "set_time": _fixed_set_time,
        }
        for mod, name in _PATCH_TARGETS:
            self._orig[(mod, name)] = getattr(mod, name)
            setattr(mod, name, fakes[name])
        return self

    def __exit__(self, *exc):
        for (mod, name), val in self._orig.items():
            setattr(mod, name, val)
        return False

```

- [ ] **Step 2.6: The mechanical call-site and message edits.**

```
cd "$WT" && sed -i \
  -e 's/    base = _make_base(save_root, trace)/    base = _make_host(save_root, trace)/' \
  -e 's/active = Active(base, /active = ActionSession(base, /' \
  -e 's/        await active.finish_all()/        await active.action_finalizer.finish_all()/' \
  -e 's/        await active.substitute()/        await active.action_finalizer.substitute()/' \
  -e 's/^def _active_params(base: Base, /def _active_params(base: ActionHost, /' \
  -e 's/^async def _drain_data(active: Active, /async def _drain_data(active: ActionSession, /' \
  helao/core/tests/test_active_golden_master.py
grep -c '_make_host(save_root, trace)' "$WT/helao/core/tests/test_active_golden_master.py"
grep -c 'ActionSession(base, ' "$WT/helao/core/tests/test_active_golden_master.py"
```
Expected: `13`, then `13`. Then make these exact old→new replacements (each old string occurs once):

| old | new |
|---|---|
| ``    ``Active.__init__`` -> ``init_act`` promotes the action to a manual run.`` | ``    ``ActionSession.__init__`` -> ``init_act`` promotes the action to a manual run.`` |
| `# fake Executor (GAP#1: the Active lifecycle is executor-free in scenarios 1-9,` | `# fake Executor (GAP#1: the session lifecycle is executor-free in scenarios 1-9,` |
| `    # the whole run tree must be walked to capture every file Active produced.` | `    # the whole run tree must be walked to capture every file the session produced.` |
| `        "refusing to overwrite a non-empty frozen baseline_S0a/ reference; "` | `        "refusing to overwrite a non-empty frozen golden/action/ reference; "` |
| `        description="CARDS P6 S0a Active output golden-master harness."` | `        description="ActionSession output golden-master harness."` |
| `        print(f"CHECK FAILED: Active output diverged from {BASELINE_S0A_DIR}")` | `        print(f"CHECK FAILED: ActionSession output diverged from {BASELINE_S0A_DIR}")` |

and these multi-line ones:

```python
# old (_scenario_finish_late_data_drain docstring)
    entry and the finished-packet write-drain loop in ``_finish`` (roughly
    base.py:1618-1645 -- the retry+``sleep(0.1)`` that lets the threadpool file
    writes complete BEFORE the file connections are closed) never has anything to
    flush: its late-data-vs-file-close race is unobservable.
# new
    entry and the finished-packet write-drain loops in ``_finish``
    (``adapters/native/finalizer.py``, the two capped retry+``sleep(0.1)`` loops
    that let the threadpool file writes complete BEFORE the file connections are
    closed) never have anything to flush: the late-data-vs-file-close race is
    unobservable.
```
```python
# old (_scenario_nonblocking)
    # instance-attribute override shadows the (later delegator) Base method, so
    # this baseline is stable across the S2 extraction.
# new
    # instance-attribute override shadows the ActionHost method.
```
```python
# old (run_check docstring)
    """Hard gate: recapture every scenario and diff against the frozen S0a
    reference
# new
    """Hard gate: recapture every scenario and diff against the frozen
    reference
```
```python
# old (run_check)
        print(f"FATAL: frozen S0a reference missing/empty: {BASELINE_S0A_DIR}")
        print("run with --freeze first (on unmodified base.py).")
# new
        print(f"FATAL: frozen reference missing/empty: {BASELINE_S0A_DIR}")
        print("the reference is tracked in git; restore it, do not re-freeze.")
```
```python
# old (argparse --freeze help)
        help="One-time capture of the frozen .omc/artifacts/p6/baseline_S0a/ reference "
        "(refuses if it already exists).",
# new
        help="One-time capture of the tracked golden/action/ reference "
        "(refuses if it already exists).",
```
```python
# old (argparse --check help)
        help="Hard gate: diff freshly captured Active output against the frozen "
        "baseline_S0a/ reference. Exit non-zero on any divergence.",
# new
        help="Hard gate: diff freshly captured ActionSession output against the "
        "tracked golden/action/ reference. Exit non-zero on any divergence.",
```

Verify nothing engine-shaped is left, and the file is black-clean:
```
grep -nE 'helao\.core\.servers|_make_base|\bBase\b|Active\(|base_module|async_copy|\.omc/artifacts/p6' "$WT/helao/core/tests/test_active_golden_master.py"
black --check "$WT/helao/core/tests/test_active_golden_master.py"
```
Expected: exactly one grep hit, line 10 of the new docstring's provenance paragraph (it names the legacy ``Base``), which is kept on purpose; then `1 file would be left unchanged.`

- [ ] **Step 2.7: Red-check (spec §4.1 step 5).** Port 8000 must be free, because the legacy half POSTs to it:

```
timeout 30 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python helao/hexagon/tests/smoke/wait_ports_free.py --timeout 10 8000; echo ports rc=$?
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t2_redcheck.py" legacy "$X/legacy_action" > "$X/t2_red_legacy.txt" 2>/dev/null; echo legacy rc=$?
grep -vE 'text\]|manifest\]' "$X/t2_red_legacy.txt"
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t2_redcheck.py" native "$X/legacy_action" > "$X/t2_red_native.txt" 2>/dev/null; echo native rc=$?
tail -1 "$X/t2_red_native.txt"
git -C "$WT" status --short
```
Expected: `[wait_ports_free] ports free: [8000, 18000]`, `ports rc=0`. Then `legacy rc=1` after about 70 s, and:
```
  DELTA    1_basic_data_and_file
             trace byte diff; move_dir events reference=1 this run=0
  DELTA    2_save_data_false
             trace byte diff; move_dir events reference=1 this run=0
  DELTA    3_split_keep_active
             trace byte diff; move_dir events reference=2 this run=0
  DELTA    4_substitute
             trace byte diff; move_dir events reference=1 this run=0
  DELTA    5_error_estop
             trace byte diff; move_dir events reference=1 this run=0
  DELTA    6_manual_action
             trace byte diff; move_dir events reference=1 this run=0
  DELTA    7_multifile_aux_listen
             trace byte diff; move_dir events reference=1 this run=0
  HANG     8_finalizer_global_params
  DELTA    9_nonblocking_status
             trace byte diff; move_dir events reference=1 this run=0
  DELTA    10_executor_concurrent
             trace byte diff; move_dir events reference=1 this run=0
  DELTA    11_executor_oneoff
             trace byte diff; move_dir events reference=1 this run=0
  HANG     12_finalizer_global_params_dict
  DELTA    13_finish_late_data_drain
             trace byte diff; move_dir events reference=1 this run=0
legacy: 13 of 13 scenarios red
```
(`3_split_keep_active` and `6_manual_action` also print `text]`/`manifest]` lines, filtered above; scenario 6's manifest shows today's date in `RUNS_DIAG/`, because `set_time` is unpinned.) Then `native rc=0` and `native: 0 of 13 scenarios red`; `git status` listing no path outside Task 2's two (`test_active_golden_master.py`, `golden/`) other than files the other in-flight wave-1 tasks own. If the legacy half is not 13 of 13 red, or any non-hanging scenario keeps a non-zero `move_dir` count, the patch list intercepts something it should not — STOP. If the native half is not 0 of 13, STOP and escalate (spec §4.1 step 6: any delta stops the commit; it is not re-baselined).

- [ ] **Step 2.8: Compare native against legacy (spec §4.1 step 6), and check no engine module loads.**

```
timeout 900 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t2_capture.py" "$X/native_action" 2>/dev/null
timeout 300 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t2_compare.py" "$X/legacy_action" "$X/native_action" > "$X/t2_native_vs_legacy.txt" 2>/dev/null; echo compare rc=$?
cat "$X/t2_native_vs_legacy.txt"
diff -r "$X/legacy_action" "$X/native_action" && echo NATIVE-BYTE-IDENTICAL-TO-LEGACY
timeout 300 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t2_no_engine.py" 2>/dev/null; echo no-engine rc=$?
```
Expected: `captured 13 scenarios into …/native_action`; `compare rc=0` with 13 `PASS` lines and `COMPARE PASSED: 13 scenarios`; `NATIVE-BYTE-IDENTICAL-TO-LEGACY` (measured: every trace and every `.runs.norm` byte-identical, stronger than the multiset rule requires); `scenarios run: 13; engine modules loaded: []` and `no-engine rc=0`. Any DELTA is an escalation, not a re-baseline.

- [ ] **Step 2.9: Freeze the tracked reference (Q3) and prove it.**

```
timeout 300 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python helao/core/tests/test_active_golden_master.py --check 2>/dev/null; echo pre-freeze check rc=$?
timeout 300 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python helao/core/tests/test_active_golden_master.py --freeze 2>/dev/null; echo freeze rc=$?
/bin/ls "$WT/helao/core/tests/golden/action" | wc -l
{ grep -rlE "/home/|/mnt/|/tmp/" "$WT/helao/core/tests/golden/action"; grep -rlw -e "$(hostname)" -e "$(whoami)" "$WT/helao/core/tests/golden/action"; } | wc -l
timeout 300 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t2_compare.py" "$X/legacy_action" helao/core/tests/golden/action 2>/dev/null | tail -1
diff -r "$X/native_action" "$WT/helao/core/tests/golden/action" && echo FROZEN-EQUALS-COMPARED-CAPTURE
timeout 300 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python helao/core/tests/test_active_golden_master.py --freeze 2>/dev/null; echo refreeze rc=$?
```
Expected: `pre-freeze check rc=1` (prints `FATAL: frozen reference missing/empty: …/golden/action`); `freeze rc=0` with `FROZE 13 scenarios into …/golden/action` and 13 file-pair lines; `26`; `0` (no local path, host name or user name); `COMPARE PASSED: 13 scenarios`; `FROZEN-EQUALS-COMPARED-CAPTURE`; `refreeze rc=1` (prints `FATAL: frozen baseline already exists at …`), which proves the guard.

- [ ] **Step 2.10: The committed gate, its default mode, and the cwd trap.**

```
timeout 300 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python helao/core/tests/test_active_golden_master.py --check 2>/dev/null | tail -1; echo check rc=$?
timeout 300 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python helao/core/tests/test_active_golden_master.py 2>/dev/null | tail -1
timeout 300 conda run -n helao --no-capture-output --cwd /tmp env PYTHONPATH="$WT" python "$WT/helao/core/tests/test_active_golden_master.py" --check 2>/dev/null | grep -c '^  DELTA'
```
Expected: `CHECK PASSED: all 13 scenarios match …/helao/core/tests/golden/action` (about 10 s); `DETERMINISM SELF-TEST PASSED: 13 scenarios byte/multiset-stable 2x` (about 18 s); `13` — the `hlo_version` trap: from a directory that is not a git checkout every scenario is DELTA. (Ignore the `check rc` echo; it reports `tail`'s status. The pass line is the evidence.)

- [ ] **Step 2.11: pyright on the file.** Task 0 recorded this file at 4 errors on `64f2cf15` (`repl` redeclared at l.189, `app` and `helaodirs` assignments at l.501/511, `"None" is not awaitable` at l.1255).

```
cd "$WT" && timeout 300 pyright --outputjson helao/core/tests/test_active_golden_master.py > "$X/t2_pyright.json"; echo rc=$?
timeout 60 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -c "import json; d = json.load(open('$X/t2_pyright.json')); print(d['summary']['filesAnalyzed'], d['summary']['errorCount'])"
```
Expected: `rc=1`, then `1 4`, or `1 3` once Task 1's Step 1.5 annotation (`self.aloop: asyncio.AbstractEventLoop | None`) is in the tree, because that removes the `aloop` assignment error. The four are now `repl` (l.202), the `helaodirs` and `aloop` assignments in `_make_host`, and the same `"None" is not awaitable`. If the second number is above 4, STOP: storing the artifact store in a local `store` (as the block in step 2.5d does) is what keeps `meta_writer_for` off the `ArtifactStorePort` type.

**Files for the controller's commit:**
- modified: `helao/core/tests/test_active_golden_master.py`
- added: `helao/core/tests/golden/action/1_basic_data_and_file.runs.norm`, `…/1_basic_data_and_file.trace.jsonl`, and the same pair for `2_save_data_false`, `3_split_keep_active`, `4_substitute`, `5_error_estop`, `6_manual_action`, `7_multifile_aux_listen`, `8_finalizer_global_params`, `9_nonblocking_status`, `10_executor_concurrent`, `11_executor_oneoff`, `12_finalizer_global_params_dict`, `13_finish_late_data_drain` (26 files; `git -C "$WT" add helao/core/tests/golden/action` adds them all). Black does not touch `.jsonl`/`.norm` files; run it on the `.py` only.

---

### Task 3: Freeze the member-surface snapshots (D-B7b.7)

**Files:**
- Create: `helao/hexagon/tests/checklists/base_member_surface.json`
- Create: `helao/hexagon/tests/checklists/orch_member_contract.json`
- Test (unchanged, run only): `helao/hexagon/tests/test_action_host_member_coverage.py`, `helao/hexagon/tests/test_orch_host_member_coverage.py`

**Interfaces:**
- Consumes: `test_action_host_member_coverage._base_public_members() -> set[str]` and `test_orch_host_member_coverage.orch_contract() -> set[str]`, as they stand on `64f2cf15` (they read `helao/core/servers/base.py` and `orch_api.py`).
- Produces: two JSON files in the CONVENTIONS format `{"description": str, "members": [sorted unique str]}`, written as `json.dumps(obj, indent=2) + "\n"`. Task 12 reads `["members"]` from both. Task 15 removes `"globstat_q"` from `orch_member_contract.json`.

**Execution:** can run in parallel with Tasks 1, 2, 5 and 6. It writes only the two new JSON files, and it reads engine source, which no commit-1 task edits. Do not run it in parallel with Task 4: both touch `helao/hexagon/tests/checklists/`, although the files differ. No commit.

The test files stay unchanged in commit 1. Their readers move to the JSON in commit 3 (Task 12), once the engine they read is gone.

- [ ] **Step 3.1: Create `$X/t3_freeze_members.py`.**

```python
"""B7b Task 3: freeze the two member snapshots the coverage ratchets derive from engine source.

Run once, from the repo root, with the repo on PYTHONPATH, while helao/core/servers
still exists. Refuses to overwrite an existing snapshot.
"""

import hashlib
import json
import sys

from helao.hexagon.tests import test_action_host_member_coverage as act
from helao.hexagon.tests import test_orch_host_member_coverage as orc

OUT = act.REPO_ROOT / "helao/hexagon/tests/checklists"
SNAPSHOTS = {
    "base_member_surface.json": (
        "Base public members, contractual privates and self.x attributes, extracted"
        " by test_action_host_member_coverage._base_public_members from"
        " helao/core/servers/base.py on 64f2cf15, before B7b deleted the engine.",
        act._base_public_members(),
    ),
    "orch_member_contract.json": (
        "Orchestrator member contract (orch.<name> and self.orch.<name> in the 13"
        " consumer modules, orch_api included), extracted by"
        " test_orch_host_member_coverage.orch_contract on 64f2cf15, before B7b"
        " deleted the engine.",
        orc.orch_contract(),
    ),
}

existing = [name for name in SNAPSHOTS if (OUT / name).exists()]
if existing:
    sys.exit(f"REFUSING to overwrite existing snapshot(s): {existing}")
for name, (description, members) in SNAPSHOTS.items():
    ordered = sorted(members)
    doc = {"description": description, "members": ordered}
    (OUT / name).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    digest = hashlib.sha256("\n".join(ordered).encode()).hexdigest()[:16]
    print(f"{name} {len(ordered)} {digest}")
```

- [ ] **Step 3.2: Confirm the extraction still reads the engine, then freeze.**

```
git -C "$WT" ls-files helao/core/servers/base.py helao/core/servers/orch_api.py
timeout 300 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t3_freeze_members.py" 2>/dev/null | grep '\.json '
```
Expected: the two engine paths. Then exactly:
```
base_member_surface.json 89 fd5415eab1f1965e
orch_member_contract.json 138 1b29b926a9fc14ca
```
If either count or digest differs, STOP and report it. The spec's numbers are 89 and 138; the `test_orch_host_member_coverage` docstring's "136" is stale.

- [ ] **Step 3.3: The guard refuses a second freeze.**

```
timeout 300 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t3_freeze_members.py" 2>&1 | grep REFUSING
```
Expected: `REFUSING to overwrite existing snapshot(s): ['base_member_surface.json', 'orch_member_contract.json']`.

- [ ] **Step 3.4: The ratchets still pass unchanged.**

```
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -m pytest -q -p no:cacheprovider --color=no helao/hexagon/tests/test_action_host_member_coverage.py 2>&1 | tail -1
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -m pytest -q -p no:cacheprovider --color=no helao/hexagon/tests/test_orch_host_member_coverage.py 2>&1 | tail -1
```
Expected: `4 passed…`, then `5 passed…`.

**Files for the controller's commit:** `helao/hexagon/tests/checklists/base_member_surface.json` (new), `helao/hexagon/tests/checklists/orch_member_contract.json` (new).

---

### Task 4: `openapi_capture` sees request bodies and enums; legacy and native surfaces compared (spec §4.1 step 9, §8)

Plan decisions for this task and for its commit-3/commit-4 follow-ups (spec silent; defaults):

- **P-G.1: commit 1 re-freezes `orch_openapi_legacy.json` in the new capture format, from an in-process legacy `OrchAPI`.** Landing the §8 capture change in commit 1 (spec §4.1 step 9) makes `test_parameter_schemas_match_the_live_legacy_orchestrator` fail right away. The live capture now records `ref`/`enum` and the component `type` on the three `checkcond` parameters. The frozen file recorded `type: null` there. Measured: `1 failed, 10 passed`. The file cannot stay as it is, and a test that compares only the old keys would be a one-commit hack. The measurement that makes a re-freeze safe: the in-process legacy capture, projected back onto the old fields, equals the frozen launched-server file exactly (`equal_to_frozen=True`, 74 routes). So the re-frozen file is still a legacy capture, with more fields. Commit 1 changes no test code.
- **P-G.2: `body` carries two keys the spec's format does not list.** `"type"` is the body schema's type. `"items"` is present only when the body is an array. Without them, `/drop_experiment_inds` (an inline `list[int]` body) and `/update_global_params` (an inline `dict` body) would both reduce to `properties: []`, and would compare equal to any other propertyless body.
- **P-G.3: body properties do not record `default`, as the spec's format says.** The dry run compared the body-property defaults of legacy and native separately: 0 differences on all 20 body routes. So nothing is being hidden.
- **P-G.4: an `anyOf`-with-`$ref` parameter keeps its `anyOf` type.** It gains `ref`/`enum`, but its `type` is replaced by the component's only where the old capture recorded `None`, which is what spec §8 says. The case does not occur today: all 3 `$ref` parameters are direct refs.
- **P-G.5: `test_orch_host_member_coverage` gains a floor on the live walk alone (`> 90`).** Once the frozen JSON is unioned in, the existing `> 130` floor passes even if the AST walk returns nothing. The live walk measures 103 on `64f2cf15` and 96 after Task 8 removes the graft (simulated).
- **P-G.6: `CONTRACTUAL_PRIVATE` is deleted from `test_action_host_member_coverage.py` in commit 3.** Its only reader was the `base.py` walk. Its three names are in the frozen JSON, and the rewritten `_base_public_members` docstring keeps the reason they matter.

**Files:**
- Modify: `harness/openapi_capture.py:27-80`, which is `normalize` and `_params`. `_ref_name`, `_describe` and `_body` are new and go between them. `_any_of_type`, `capture` and `capture_to_file` are unchanged.
- Modify (re-freeze, content only): `helao/hexagon/tests/checklists/orch_openapi_legacy.json` (P-G.1)
- Test (unchanged, run only): `helao/hexagon/tests/test_orch_host_surface.py`, `helao/hexagon/tests/test_action_host_surface.py`, `helao/hexagon/tests/test_ws_simulator_port.py`

**Interfaces:**
- Consumes: `helao.hexagon.tests.test_orch_host_surface._host() -> OrchHost`. It sets `config_loader.CONFIG` to an ORCH+SIM config. It also consumes `helao.core.servers.orch_api.OrchAPI(server_key, server_title, description, version)`.
- Produces:
  - `openapi_capture.normalize(doc) -> {"routes": [...]}`. Every route has `path`, `method`, `tags` and `params`. A route that declares a request body also has `"body": {"required": bool, "type": str | list | None, "properties": [[name, {"type": ..., "ref"?: str, "enum"?: list}] sorted by name], "required_props": [sorted str], "items"?: {...}}`.
  - A parameter whose schema is a `$ref` (directly or in one `anyOf` arm) gains `"ref": <component name>`, takes the component's `"type"` where it was `None`, and gains `"enum": sorted(members, key=str)` when the component has one.
  - Scratch evidence for Task 14: `$X/t4_legacy_surface.json`, `$X/t4_native_surface.json` and `$X/t4_orch_openapi_legacy.64f2cf15.json`.

**Execution:** can run in parallel with Tasks 1, 2, 5 and 6. It touches `harness/openapi_capture.py` and one checklist JSON, and nothing else. Run it after Task 3 has finished (Tasks 3 and 4 are sequential; both write under `checklists/`). No commit.

- [ ] **Step 4.1: Keep the launched-server checklist as scratch evidence.**

```
mkdir -p "$X"
cp "$WT/helao/hexagon/tests/checklists/orch_openapi_legacy.json" "$X/t4_orch_openapi_legacy.64f2cf15.json"
sha256sum "$X/t4_orch_openapi_legacy.64f2cf15.json" | cut -c1-16
```
Expected: the file is 16725 bytes. Record the printed hash in the Task 7 report.

- [ ] **Step 4.2: Replace `normalize` and `_params` in `harness/openapi_capture.py`.** Replace everything from `def normalize(` up to, but not including, `def _any_of_type(`, with exactly this:

```python
def normalize(doc: dict[str, Any]) -> dict[str, Any]:
    """Reduce an OpenAPI document to a sorted, comparable route list.

    Args:
        doc: A parsed ``openapi.json`` document.

    Returns:
        ``{"routes": [{"path", "method", "tags", "params"[, "body"]}, ...]}``
        sorted by ``(path, method)`` with tags sorted, so two captures of the
        same server compare equal regardless of dict ordering. ``body`` is
        present only on a route that declares a request body.
    """
    schemas = (doc.get("components") or {}).get("schemas") or {}
    routes = []
    for path, ops in (doc.get("paths") or {}).items():
        for method, op in ops.items():
            route = {
                "path": path,
                "method": method.lower(),
                "tags": sorted((op or {}).get("tags") or []),
                "params": _params(op or {}, schemas),
            }
            body = _body(op or {}, schemas)
            if body is not None:
                route["body"] = body
            routes.append(route)
    routes.sort(key=lambda r: (r["path"], r["method"]))
    return {"routes": routes}


def _ref_name(schema: dict[str, Any]) -> Any:
    """The component a schema points at, directly or through one ``anyOf`` arm.

    ``Optional[SomeEnum]`` renders as ``anyOf: [{$ref}, {type: null}]`` and a
    bare enum parameter as ``{$ref}``; both name the component that holds the
    members a caller may send.
    """
    for variant in (schema, *(schema.get("anyOf") or [])):
        if "$ref" in variant:
            return variant["$ref"].rsplit("/", 1)[-1]
    return None


def _describe(schema: dict[str, Any], schemas: dict[str, Any]) -> dict[str, Any]:
    """``type``, plus ``ref`` and ``enum`` when the schema points at a component.

    A ``$ref`` schema has no ``type`` of its own, so before this every enum
    parameter recorded ``type: null`` and two different enums compared equal.
    The component's name is kept because FastAPI takes it from the Python
    class name, which is part of the contract; the enum members are what a
    caller actually sends.
    """
    out = {"type": schema.get("type") or _any_of_type(schema)}
    ref = _ref_name(schema)
    if ref is not None:
        component = schemas.get(ref) or {}
        out["ref"] = ref
        if out["type"] is None:
            out["type"] = component.get("type")
        if "enum" in component:
            out["enum"] = sorted(component["enum"], key=str)
    return out


def _body(op: dict[str, Any], schemas: dict[str, Any]) -> Any:
    """A route's request body, resolved one level into its component.

    Returns None for a route without one, so those routes keep their shape.
    The body component's own name is NOT recorded: FastAPI derives it from the
    handler's function name (``Body_<func>_<path>_post``), which differs
    between two correct implementations for the same reason ``title`` does.
    """
    request_body = op.get("requestBody")
    if not request_body:
        return None
    content = request_body.get("content") or {}
    schema = (next(iter(content.values()), None) or {}).get("schema") or {}
    ref = _ref_name(schema)
    target = (schemas.get(ref) or {}) if ref is not None else schema
    body = {
        "required": bool(request_body.get("required", False)),
        "type": target.get("type") or _any_of_type(target),
        "properties": sorted(
            (
                [name, _describe(prop, schemas)]
                for name, prop in (target.get("properties") or {}).items()
            ),
            key=lambda pair: pair[0],
        ),
        "required_props": sorted(target.get("required") or []),
    }
    if "items" in target:
        body["items"] = _describe(target["items"], schemas)
    return body


def _params(op: dict[str, Any], schemas: dict[str, Any]) -> list[dict[str, Any]]:
    """The query/path parameters a route accepts, reduced to what callers see.

    Paths and methods alone are too weak a gate for a host replacement: a
    route can be present with the right tag and still reject every request
    its predecessor accepted, because a parameter was renamed, lost its
    default, or changed type. That is invisible to a path-set comparison
    and immediate to a caller.

    Only ``name``/``in``/``required``/``type``/``default`` are kept, plus
    ``ref``/``enum`` for a parameter whose schema is a component
    (:func:`_describe`). The full JSON Schema carries generated ``title``
    strings derived from the handler's own function name, which differ
    between two correct implementations and would make every route diff.
    """
    out = []
    for prm in op.get("parameters") or []:
        schema = prm.get("schema") or {}
        entry = {
            "name": prm.get("name"),
            "in": prm.get("in"),
            "required": bool(prm.get("required", False)),
            **_describe(schema, schemas),
        }
        if "default" in schema:
            entry["default"] = schema["default"]
        out.append(entry)
    out.sort(key=lambda p: (str(p["in"]), str(p["name"])))
    return out
```

Then run the check below. It proves the new fields reach the gate, because the frozen file lacks them.

```
black -q "$WT/harness/openapi_capture.py" && git -C "$WT" diff --stat -- harness/openapi_capture.py
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -m pytest -q -p no:cacheprovider --color=no helao/hexagon/tests/test_orch_host_surface.py 2>&1 | grep -E '^FAILED|passed|failed'
```
Expected: `harness/openapi_capture.py | ...` changed. Then exactly one `FAILED helao/hexagon/tests/test_orch_host_surface.py::test_parameter_schemas_match_the_live_legacy_orchestrator` and `1 failed, 10 passed…`.

- [ ] **Step 4.3: Create `$X/t4_surface_compare.py`.**

```python
"""B7b Task 4: legacy OrchAPI vs native OrchHost surface, params AND body, per route.

Usage: python t4_surface_compare.py <out_dir>
Run from the repo root with the repo on PYTHONPATH, while helao/core/servers exists.
Writes <out_dir>/t4_legacy_surface.json and <out_dir>/t4_native_surface.json.
Exit 0 only if every route both hosts serve has equal params and equal body.
"""

import json
import sys
from pathlib import Path

from harness import openapi_capture
from helao.hexagon.tests.test_orch_host_surface import _host

out_dir = Path(sys.argv[1])
native_doc = _host().openapi()  # sets config_loader.CONFIG; legacy reads the same one

from helao.core.servers.orch_api import OrchAPI  # noqa: E402  (engine, on purpose)

legacy_doc = OrchAPI("ORCH", "ORCH", "b7b", 3.0).openapi()

legacy = openapi_capture.normalize(legacy_doc)
native = openapi_capture.normalize(native_doc)
for name, doc in (("legacy", legacy), ("native", native)):
    path = out_dir / f"t4_{name}_surface.json"
    path.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")

lk = {(r["path"], r["method"]): r for r in legacy["routes"]}
nk = {(r["path"], r["method"]): r for r in native["routes"]}
shared = sorted(set(lk) & set(nk))
deltas = []
for key in shared:
    for field in ("params", "body"):
        if lk[key].get(field) != nk[key].get(field):
            deltas.append((key, field, lk[key].get(field), nk[key].get(field)))
n_body = sum(1 for k in shared if "body" in lk[k])
n_ref = sum(1 for k in shared for p in lk[k]["params"] if "ref" in p)
print(
    f"T4 legacy={len(lk)} native={len(nk)} shared={len(shared)}"
    f" legacy_only={sorted(set(lk) - set(nk))}"
    f" native_only={sorted(set(nk) - set(lk))}"
    f" shared_with_body={n_body} ref_params={n_ref} deltas={len(deltas)}"
)
for key, field, old, new in deltas:
    print(f"T4 DELTA {key} {field}\n  legacy={json.dumps(old)}\n  native={json.dumps(new)}")
sys.exit(1 if deltas else 0)
```

- [ ] **Step 4.4: Run the comparison (spec §4.1 step 9).**

```
timeout 300 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t4_surface_compare.py" "$X" > "$X/t4_compare.log" 2>&1; echo rc=$?
grep -E '^T4|^  (legacy|native)=' "$X/t4_compare.log"
```
Expected: `rc=0`, then exactly this one line:
```
T4 legacy=74 native=77 shared=74 legacy_only=[] native_only=[('/get_config', 'post'), ('/hotreload_busy', 'post'), ('/resend_active', 'post')] shared_with_body=20 ref_params=3 deltas=0
```
**Escalation stop:** any `T4 DELTA` line, any `legacy_only` entry, or a non-zero rc stops Task 4. Report the lines verbatim. Do not edit the capture or either host to make them go away. There are two known divergences outside the normalize, and this step does not test them: `/prepend_sequences`' response shape (Q10), and the three routes `OrchHost` adds (§2.7). Both are recorded in the PR.

- [ ] **Step 4.5: Prove the in-process legacy capture is the launched-server capture, plus the new fields.** Create `$X/t4_old_projection.py`:

```python
"""B7b Task 4: prove the new-format legacy capture, projected back onto the OLD
capture's fields, equals the frozen launched-server checklist byte for byte.

Usage: python t4_old_projection.py <t4_legacy_surface.json> <orch_openapi_legacy.json>
"""

import json
import sys

new = json.load(open(sys.argv[1], encoding="utf-8"))
old = json.load(open(sys.argv[2], encoding="utf-8"))


def project(route):
    params = []
    for prm in route["params"]:
        entry = {k: prm[k] for k in ("name", "in", "required", "type", "default") if k in prm}
        if "ref" in prm:
            entry["type"] = None  # the old capture could not see through a $ref
        params.append(entry)
    return {"method": route["method"], "params": params, "path": route["path"], "tags": route["tags"]}


projected = {"routes": [project(r) for r in new["routes"]]}
same = projected == old
print(f"T4-PROJECTION routes={len(new['routes'])} equal_to_frozen={same}")
sys.exit(0 if same else 1)
```

```
timeout 120 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t4_old_projection.py" "$X/t4_legacy_surface.json" "$X/t4_orch_openapi_legacy.64f2cf15.json"
```
Expected: `T4-PROJECTION routes=74 equal_to_frozen=True`. If it prints `False`, STOP: the in-process legacy capture is not the launched one, and P-G.1 does not hold.

- [ ] **Step 4.6: Re-freeze the legacy checklist in the new format (P-G.1), and check determinism.**

```
cp "$X/t4_legacy_surface.json" "$WT/helao/hexagon/tests/checklists/orch_openapi_legacy.json"
mkdir -p "$X/t4_rerun"
timeout 300 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t4_surface_compare.py" "$X/t4_rerun" 2>/dev/null | grep -c 'deltas=0'
cmp "$X/t4_rerun/t4_legacy_surface.json" "$WT/helao/hexagon/tests/checklists/orch_openapi_legacy.json" && echo LEGACY-DETERMINISTIC
cmp "$X/t4_rerun/t4_native_surface.json" "$X/t4_native_surface.json" && echo NATIVE-DETERMINISTIC
sha256sum "$WT/helao/hexagon/tests/checklists/orch_openapi_legacy.json" "$X/t4_native_surface.json" | cut -c1-16
```
Expected: `1`, `LEGACY-DETERMINISTIC`, `NATIVE-DETERMINISTIC`, then `972dc000882418d2` and `f333cd8cb74ec5dc`. The re-frozen file is 21275 bytes.

- [ ] **Step 4.7: The three capture users pass.**

```
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -m pytest -q -p no:cacheprovider --color=no helao/hexagon/tests/test_orch_host_surface.py 2>&1 | tail -1
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -m pytest -q -p no:cacheprovider --color=no helao/hexagon/tests/test_action_host_surface.py 2>&1 | tail -1
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -m pytest -q -p no:cacheprovider --color=no helao/hexagon/tests/test_ws_simulator_port.py 2>&1 | tail -1
```
Expected: `11 passed…`, `8 passed…`, `5 passed…`.

**Files for the controller's commit:** `harness/openapi_capture.py`, `helao/hexagon/tests/checklists/orch_openapi_legacy.json`.

---

### Task 5: `native_fixtures` on `ActionHost`; the native tests leave the legacy fixture; four `unit_test_*` moved and deleted

**Files:**
- Modify (full rewrite): `helao/hexagon/tests/native_fixtures.py` (115 lines on `64f2cf15`; legacy `Base`/`Active` at l.19, 27, 30, 84, 102)
- Modify: `helao/hexagon/tests/test_native_data_file.py`, `test_native_data_sink.py`, `test_native_data_stream.py`, `test_native_finalizer.py`, `test_native_meta_writer.py` (all under `helao/hexagon/tests/`)
- Modify: `helao/hexagon/tests/test_active_graft.py:29` (takes a private copy of the legacy fixture for the one commit it outlives it; commit 2 deletes the file)
- Modify: `helao/core/tests/test_run_state_wiring.py:317-353`
- Modify: `helao/hexagon/tests/test_estop_fixes.py:385, 402, 419, 546, 569`
- Unchanged but re-run: `helao/hexagon/tests/test_native_artifact_store.py`
- Delete: `helao/core/tests/unit_test_active_data_file.py`, `unit_test_active_data_stream.py`, `unit_test_active_finalizer.py`, `unit_test_base_meta_writer.py`
- Scratch: `$X/t5_tests.patch`, `$X/t5_engine_refs.py`, `$X/t5_fixture_engine_free.py`, `$X/t5_*.txt`

**Interfaces:**
- Consumes: `ActionHost` (`helao/hexagon/app/action_host.py`), `ActionSession(host, activeparams)` (`app/action_session.py:55`), `PortWiring(clock=..., artifact_store=...)` (`app/wiring.py:75`), `LegacyClockAdapter(offset_s)` (`adapters/legacy/clock.py:18`), `NativeArtifactStoreAdapter(config=None, clock=None)`; `helao.hexagon.app.orch_unpack.seq_unpacker` (the object `helao.core.servers.orch_unpack` re-exports; same function).
- Produces (kept names, new types; Task 12 and every `test_native_*` rely on them):
  - `native_fixtures.make_base(save_root: str) -> ActionHost` — `ActionHost.__new__` plus an attribute block; `meta_writer` is a `NativeMetaFileWriter`, `aloop` is `None`, `run_journal` is `None`.
  - `native_fixtures.mk_action(**overrides) -> Action` — unchanged.
  - `native_fixtures.mk_active(base, json_data_keys=None, action=None) -> tuple[ActionSession, UUID]` — not registered in `base.actives`.
  - `native_fixtures._make_active_for_journal(tmp_path, manual_action: bool = False) -> tuple[ActionHost, ActionSession]` — moved from `unit_test_active_finalizer`; must be called with a running event loop.
  - `native_fixtures.assert_source_parity(native_cls, legacy_cls, methods)` — unchanged; Task 12 deletes it.
  - The four moved `unit_test_*` files no longer exist. `run_unit_tests.py` still imports them until Task 7 removes these eight lines (Task 7 applies them; this task does not edit `run_unit_tests.py`):
    ```
    21: from helao.core.tests.unit_test_active_data_file import active_data_file_unit_test
    22: from helao.core.tests.unit_test_active_data_stream import active_data_stream_unit_test
    24: from helao.core.tests.unit_test_active_finalizer import active_finalizer_unit_test
    31: from helao.core.tests.unit_test_base_meta_writer import base_meta_writer_unit_test
    94:     ("base_meta_writer", base_meta_writer_unit_test),
    95:     ("active_data_file", active_data_file_unit_test),
    96:     ("active_data_stream", active_data_stream_unit_test),
    98:     ("active_finalizer", active_finalizer_unit_test),
    ```
    Between Task 5 and Task 7, `run_unit_tests.py` fails at import. Do not run it in between.

**Execution:** Parallel-safe with Tasks 1, 2, 3, 4 and 6: the file sets are disjoint. Task 6 also deletes `unit_test_*` files, so neither task may run `run_unit_tests.py`; Task 7 edits and runs it. This task mutates no production file (its probes run later, in Task 7 Step 7.0a). Must not touch `run_unit_tests.py`, `test_action_session_port.py`, `test_estop_finish_race.py`, or any `helao/core/servers/` file. Must not commit.

**Plan decisions (spec silent):**
- **P-E.1 — `__new__` plus an attribute block, not real construction.** §4.1 step 4 allows either for the action golden master; for this fixture the spec says only "rebuilt on `ActionHost` and `ActionSession`". `make_base(save_root)` is called with `save_root` set both to `tmp_path` and to `tmp_path / "RUNS_ACTIVE"`, and some tests assert on the exact directory under it. Real construction derives `save_root` from `root` and creates the run tree, so it would change what those tests see. The bypass keeps the legacy fixture's contract (same attribute block, same `save_root`), and `test_action_session_port::test_a_session_can_actually_be_constructed` already covers real construction.
- **P-E.2 — the "swap under test" lines are deleted, not left as no-ops.** `ActionSession` builds the native collaborators itself (`action_session.py:95-104`), so `active.data_stream = NativeDataStreamer(active)` would replace a native streamer with another one. Each helper now asserts `isinstance(...)` instead. That turns the old swap into a check that the session really is native, and the comments that said "mini-graft" or "the swap under test" go with it.
- **P-E.3 — `test_active_graft.py` gets a private copy of the legacy fixture.** The spec leaves this file for commit 2 (§5.3) and says it "dies" (§2.5). It imports `make_base` from `native_fixtures` (l.29), however. Once the fixture is rebuilt, 3 of its 5 tests fail with `'ActionHost' object has no attribute 'contain_action'` (measured). Commit 1 must be green, and moving the deletion into commit 1 would change the spec's commit boundaries. So the old 20-line fixture moves verbatim into that file.
- **P-E.4 — `ActionSession` lacks `substitute` and `finish_all`,** so two tests call `active.action_finalizer.substitute()` and `.finish_all()`. §4.1 step 4 prescribes the same thing for the golden master.
- **P-E.5 — `init_datafile` partial coverage is closed in place.** The unit check `init_datafile` also asserted `file_type`, `action_uuid` and header content. `test_init_datafile_autogen_filename` asserted none of those, so three asserts are added there, which D-B7b.6 requires before the unit check can be deleted.

**Check-to-test mapping (D-B7b.6).** Every check in the four deleted files is listed below with the native test that now covers it, or with the reason it was engine-internal.

| unit check | covered by (after Task 5) |
|---|---|
| `active_data_file::collaborator_wired` | engine wiring: legacy `Active` built its own `DataFileWriter`. Native: `test_action_session_port::test_a_session_can_actually_be_constructed` (collaborators non-None), and `test_native_data_file._native_active` now asserts `isinstance(active.data_file_writer, NativeDataFileWriter)` |
| `active_data_file::init_datafile` | `test_native_data_file::test_init_datafile_autogen_filename` (+3 asserts, P-E.5) |
| `active_data_file::init_datafile_explicit_filename_aux` | **moved**: `test_native_data_file::test_init_datafile_explicit_filename_aux` |
| `active_data_file::finish_hlo_header` | `test_native_data_file::test_finish_hlo_header_stamps_only_unset` |
| `active_data_file::write_file` | `test_native_data_file::test_write_file_one_shot_layout_and_gate` |
| `active_data_file::write_file_nowait` | `test_native_data_file::test_write_file_nowait_matches_async_layout` |
| `active_data_file::resolve_output_path_save_data_false` | **moved**: `test_native_data_file::test_resolve_output_path_save_data_false` |
| `active_data_file::track_file` | **moved**: `test_native_data_file::test_track_file_outside_the_output_dir_records_its_basename` |
| `active_data_stream::collaborator_wired` | engine wiring (as above); `test_native_data_stream._native_active` asserts both collaborators are native |
| `active_data_stream::realtime_forwarding` | **moved**: `test_native_data_stream::test_realtime_forwarding` |
| `active_data_stream::add_new_listen_uuid_mutates_active` | **moved**: `test_native_data_stream::test_add_new_listen_uuid_mutates_the_session` |
| `active_data_stream::assemble_and_build_package` | **moved**: `test_native_data_stream::test_assemble_and_build_package` |
| `active_data_stream::enqueue_drains_and_writes` | `test_native_data_stream::test_drain_loop_lazy_open_separator_and_rows` (rows on disk, counters), plus `test_native_data_sink::test_enqueue_members_bump_active_counter` (the `enqueue_data_dflt` path) |
| `active_data_stream::enqueue_nowait_counts` | **moved** into `test_native_data_stream::test_enqueue_counts_only_data_bearing` (two lines: nowait with empty data does not count) |
| `active_data_stream::save_data_false_no_write` | `test_native_data_stream::test_save_data_false_no_logger` (no subscription, so nothing can be written) |
| `active_finalizer::collaborator_wired` | engine wiring. It pinned the P6 extraction's cache-nothing split between `Active` and `ActionFinalizer`; the session holds that state by construction (`action_session.py:64-78`) |
| `active_finalizer::finish_drains_late_data` | `test_native_finalizer::test_finish_join_drain_close_chain` |
| `active_finalizer::split_keep_active_then_finish_all` | **moved**: `test_native_finalizer::test_split_keep_active_then_finish_all_finishes_the_chain` |
| `active_finalizer::substitute_closes_open_files` | `test_native_finalizer::test_substitute_closes_open_streams` |
| `active_finalizer::delegators_forward` | engine delegation: `Active`'s eight finalizer delegators. The session's four delegators (`split`/`finish`/`_finish`/`finish_manual_action`) are exercised by every `test_native_finalizer` test that calls them |
| `active_finalizer::empty_global_params_skips_dispatch` | **already covered**: the second half of `test_native_finalizer::test_finish_exports_global_params` (`to_global_params=["missing_key"]` → no dispatch). Not duplicated; see the spec correction in the handback |
| `base_meta_writer::new_file_conn_key` | `test_native_meta_writer::test_conn_keys_md5` |
| `base_meta_writer::dflt_file_conn_key` | `test_native_meta_writer::test_conn_keys_md5` (`6adf97f8…` is `md5("None")`) |
| `base_meta_writer::write_meta_atomic` | `test_native_meta_writer::test_write_meta_atomic_tmp_shape` |
| `base_meta_writer::write_act` | `test_native_meta_writer::test_write_act_layout` |
| `base_meta_writer::write_act_save_act_false` | **moved**: `test_native_meta_writer::test_write_act_save_act_false_writes_nothing` |
| `base_meta_writer::write_exp` | `test_native_meta_writer::test_write_exp_and_seq` |
| `base_meta_writer::write_seq` | `test_native_meta_writer::test_write_exp_and_seq` |

- [ ] **Step 5.1: Record the before-counts.**

```
for f in helao/hexagon/tests/test_native_artifact_store.py helao/hexagon/tests/test_native_data_file.py helao/hexagon/tests/test_native_data_sink.py helao/hexagon/tests/test_native_data_stream.py helao/hexagon/tests/test_native_finalizer.py helao/hexagon/tests/test_native_meta_writer.py helao/core/tests/test_run_state_wiring.py helao/hexagon/tests/test_estop_fixes.py helao/hexagon/tests/test_active_graft.py; do printf '%s ' "$f"; timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -m pytest -q -p no:cacheprovider --color=no -W ignore "$f" 2>&1 | tail -1; done | tee "$X/t5_before.txt"
```
Expected (counts measured on `64f2cf15`; timings vary):
```
helao/hexagon/tests/test_native_artifact_store.py 6 passed …
helao/hexagon/tests/test_native_data_file.py 9 passed …
helao/hexagon/tests/test_native_data_sink.py 5 passed …
helao/hexagon/tests/test_native_data_stream.py 5 passed …
helao/hexagon/tests/test_native_finalizer.py 6 passed …
helao/hexagon/tests/test_native_meta_writer.py 6 passed …
helao/core/tests/test_run_state_wiring.py 15 passed …
helao/hexagon/tests/test_estop_fixes.py 38 passed …
helao/hexagon/tests/test_active_graft.py 5 passed …
```

- [ ] **Step 5.2: Rewrite `helao/hexagon/tests/native_fixtures.py`.** Replace the whole file with:

```python
"""Shared fixtures for the native-adapter tests.

A bare ``ActionHost`` built with ``ActionHost.__new__`` (no FastAPI app, no
routes, no NTP, no WebSockets), populated with every attribute an
``ActionSession`` and its native write collaborators touch, and an
``ActionSession`` over it. The session constructs the native collaborators
itself, so no test swaps one in.

Tests layer — may import anything (boundary rule)."""

import inspect
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from helao.core.hooks import HookSet
from helao.core.models.file import FileConnParams, HloFileGroup
from helao.core.models.machine import MachineModel
from helao.helpers.active_params import ActiveParams
from helao.helpers.dequedict import DequeDict
from helao.helpers.multisubscriber_queue import MultisubscriberQueue
from helao.helpers.premodels import Action
from helao.hexagon.adapters.legacy.clock import LegacyClockAdapter
from helao.hexagon.adapters.native.artifact_store import NativeArtifactStoreAdapter
from helao.hexagon.app.action_host import ActionHost
from helao.hexagon.app.action_session import ActionSession
from helao.hexagon.app.wiring import PortWiring

FIXED_DT = datetime(2026, 1, 2, 3, 4, 5, 678901)


def make_base(save_root: str) -> ActionHost:
    """Bare ``ActionHost`` with every attribute session construction + the
    write path (myinit/log_data_task/finish/meta writers) touches."""
    host = ActionHost.__new__(ActionHost)
    store = NativeArtifactStoreAdapter(config=None, clock=None)
    host.hexagon_wiring = PortWiring(
        clock=LegacyClockAdapter(0.0), artifact_store=store
    )
    host.server_key = "ACTSRV"
    host.driver = None
    host.server = MachineModel(
        server_name="ACTSRV",
        machine_name="test-machine",
        hostname="127.0.0.1",
        port=8000,
    )
    host.world_cfg = {"dummy": False, "simulation": False}
    host.ntp_offset = 0.0
    host.helaodirs = SimpleNamespace(save_root=save_root)  # type: ignore[reportAttributeAccessIssue]
    host.run_journal = None
    host.aloop = None
    host.status_q = MultisubscriberQueue()
    host.data_q = MultisubscriberQueue()
    host.live_q = MultisubscriberQueue()
    host.live_buffer = {}
    host.status_clients = set()
    host.actives = {}
    host.history = DequeDict(maxlen=200)
    host.executors = {}
    host.local_action_task_queue = []
    host.prefinish_hooks = HookSet.empty()
    host.meta_writer = store.meta_writer_for(host)
    return host


def mk_action(**overrides) -> Action:
    """Deterministic non-manual Action with data saving enabled."""
    kwargs = dict(
        action_name="nutest",
        action_abbr="nute",
        orch_key="ORCH",
        orch_host="127.0.0.1",
        orch_port=8001,
        action_uuid=UUID("00000000-0000-0000-0000-0000000000a1"),
        action_timestamp=FIXED_DT,
        sequence_uuid=UUID("00000000-0000-0000-0000-0000000000b1"),
        sequence_name="seq_nu",
        sequence_label="p2b1",
        sequence_timestamp=FIXED_DT,
        experiment_uuid=UUID("00000000-0000-0000-0000-0000000000c1"),
        experiment_name="exp_nu",
        experiment_timestamp=FIXED_DT,
        save_data=True,
    )
    kwargs.update(overrides)
    action = Action(**kwargs)  # type: ignore[reportArgumentType]
    # Mirrors what session construction does to every action before it
    # reaches the write path (`action.init_act(...)`, which cascades into
    # `init_seq`/`init_exp` when needed): populate sequence/experiment/action
    # output dirs. sequence_timestamp/experiment_timestamp/action_timestamp
    # are already fixed above, so this only fills the *_output_dir fields
    # deterministically -- it never re-stamps the fixed timestamps.
    action.init_seq()
    action.init_exp()
    action.init_act()
    return action


def mk_active(base: ActionHost, json_data_keys=None, action=None):
    """``ActionSession`` + its default file-conn key. Not registered in
    ``base.actives``; tests that need that register it themselves."""
    if action is None:
        action = mk_action()
    dflt = base.dflt_file_conn_key()
    ap = ActiveParams(
        action=action,
        file_conn_params_dict={
            dflt: FileConnParams(
                file_conn_key=dflt,
                json_data_keys=json_data_keys or ["t_s", "value"],
                file_type="nu__test_file",
                file_group=HloFileGroup.helao_files,
            )
        },
        aux_listen_uuids=[],
    )
    return ActionSession(base, ap), dflt


def _make_active_for_journal(tmp_path, manual_action: bool = False):
    """A session on a real ``RunStateJournal``, rooted at ``tmp_path``.

    ``make_base`` gives the finish path every attribute it touches but no
    station root, so it has no journal. ``test_run_state_wiring.py`` drives
    the real ``move_dir`` through ``finish`` to assert the journal drains.
    Call it from a running event loop: the finalizer schedules ``move_dir``
    on ``base.aloop``, and with ``aloop`` unset that raises inside a caught
    block and the eviction silently never runs.
    """
    import asyncio

    from helao.helpers.run_state import RunStateJournal

    save_root = Path(tmp_path) / "RUNS"
    save_root.mkdir(parents=True, exist_ok=True)
    base = make_base(str(save_root))
    base.world_cfg = {"dummy": False, "simulation": False, "root": str(tmp_path)}
    base.helaodirs = SimpleNamespace(  # type: ignore[reportAttributeAccessIssue]
        root=str(tmp_path),
        save_root=str(save_root),
        states_root=str(Path(tmp_path) / "STATES"),
    )
    base.run_journal = RunStateJournal(base.helaodirs.states_root, "SIM")
    base.aloop = asyncio.get_running_loop()  # type: ignore[reportAttributeAccessIssue]
    action = mk_action(manual_action=manual_action, save_act=True)
    session, _ = mk_active(base, json_data_keys=["t", "v"], action=action)
    return base, session


def assert_source_parity(native_cls, legacy_cls, methods):
    """Byte-parity pin: each relocated method's source must be identical to
    its legacy counterpart (methods contain no class-name references, so
    straight equality holds for a verbatim copy)."""
    diffs = []
    for name in methods:
        n_src = inspect.getsource(getattr(native_cls, name))
        l_src = inspect.getsource(getattr(legacy_cls, name))
        if n_src != l_src:
            diffs.append(name)
    assert not diffs, f"native methods drifted from legacy source: {diffs}"
```

- [ ] **Step 5.3: Red run: the unchanged tests over the rebuilt fixture.** This proves the fixture change reaches them.

```
for f in helao/hexagon/tests/test_native_finalizer.py helao/hexagon/tests/test_active_graft.py; do timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -m pytest -q -p no:cacheprovider --color=no -W ignore "$f" 2>&1 | grep -E '^(FAILED|E +AttributeError)|passed|failed' | sort -u; done
```
Expected:
```
E       AttributeError: 'ActionSession' object has no attribute 'substitute'
FAILED helao/hexagon/tests/test_native_finalizer.py::test_substitute_closes_open_streams
1 failed, 5 passed …
E       AttributeError: 'ActionHost' object has no attribute 'contain_action'
FAILED helao/hexagon/tests/test_active_graft.py::test_close_restores_originals
FAILED helao/hexagon/tests/test_active_graft.py::test_duplicate_uuid_substitutes_prior_active
FAILED helao/hexagon/tests/test_active_graft.py::test_honesty_tripwire_native_collaborators_carry_traffic
3 failed, 2 passed …
```
The other four `test_native_*` files already pass over the new fixture: artifact_store 6, data_file 9, data_sink 5, data_stream 5, meta_writer 6.

- [ ] **Step 5.4: Write the test patch.** Create `$X/t5_tests.patch` with the Write tool, with exactly this content. It was generated against `64f2cf15` and applied cleanly to a fresh `git archive` of it.

```diff
--- a/helao/hexagon/tests/test_native_data_file.py
+++ b/helao/hexagon/tests/test_native_data_file.py
@@ -9,6 +9,7 @@
 import pytest
 
 from helao.core.models.file import HloFileGroup
+from helao.helpers.premodels import Action
 from helao.core.servers.active_data_file import DataFileWriter
 from helao.hexagon.adapters.native.data_file import NativeDataFileWriter
 from helao.hexagon.tests.native_fixtures import (
@@ -40,7 +41,7 @@
     active, dflt = mk_active(
         base, action=mk_action(**action_over) if action_over else None
     )
-    active.data_file_writer = NativeDataFileWriter(active)  # type: ignore[reportAttributeAccessIssue]  # the swap under test
+    assert isinstance(active.data_file_writer, NativeDataFileWriter)
     return base, active, dflt
 
 
@@ -61,7 +62,10 @@
         == f"{a.action_abbr}-{a.orch_submit_order}.{a.action_order}.{a.action_retry}.{a.action_split}__0.hlo"
     )
     assert header.endswith("\n")
+    assert "a: 1" in header
     assert file_info.data_keys == ["t_s"]
+    assert file_info.file_type == "nu__test_file"
+    assert file_info.action_uuid == a.action_uuid
 
 
 def test_init_datafile_empty_header_variants(tmp_path):
@@ -177,3 +181,47 @@
     )
     assert path is not None and os.path.isfile(path)
     assert os.path.basename(os.path.dirname(path)) == "subdir"
+
+
+def test_init_datafile_explicit_filename_aux(tmp_path):
+    """Moved from unit_test_active_data_file: an explicit filename is used as
+    given, an empty header stays empty, and the sample label is recorded."""
+    _, active, _ = _native_active(tmp_path)
+    header, file_info = active.init_datafile(
+        header=None,
+        file_type="df__aux",
+        json_data_keys=None,
+        file_sample_label="label-1",
+        filename="explicit.csv",
+        file_group=HloFileGroup.aux_files,
+    )
+    assert file_info.file_name == "explicit.csv"
+    assert header == ""
+    assert list(file_info.sample) == ["label-1"]
+
+
+def test_resolve_output_path_save_data_false(tmp_path):
+    """Moved from unit_test_active_data_file: save_data=False resolves to None."""
+    _, active, _ = _native_active(tmp_path)
+    result = active._resolve_output_path(
+        file_type="df__blob",
+        filename="whatever.txt",
+        file_group=HloFileGroup.aux_files,
+        header=None,
+        file_sample_label=None,
+        json_data_keys=None,
+        action=Action(action_name="x", save_data=False),
+    )
+    assert result is None
+
+
+@pytest.mark.asyncio
+async def test_track_file_outside_the_output_dir_records_its_basename(tmp_path):
+    """Moved from unit_test_active_data_file: a file outside the action's
+    output dir is recorded under its basename."""
+    _, active, _ = _native_active(tmp_path)
+    outside = tmp_path / "elsewhere" / "aux_data.dat"
+    outside.parent.mkdir()
+    outside.write_text("payload")
+    await active.track_file("df__aux", str(outside), [])
+    assert any(fi.file_name == "aux_data.dat" for fi in active.action.files)
--- a/helao/hexagon/tests/test_native_data_sink.py
+++ b/helao/hexagon/tests/test_native_data_sink.py
@@ -1,7 +1,7 @@
 """NativeDataSinkAdapter (P2b-1): DataSinkPort over the native write bodies.
-Q2 (binding): append_sample / set_estop stay LEGACY-delegated (pure model
-mutations + status_q puts — P2a owns the status plane); split routes to the
-native finalizer; lbuf members route via active.base (sanctioned)."""
+Q2 (binding): append_sample / set_estop delegate to the ActionSession (pure
+model mutations + status_q puts — P2a owns the status plane); split routes to
+the native finalizer; lbuf members route via active.base (sanctioned)."""
 
 import pytest
 
@@ -9,10 +9,7 @@
 from helao.core.models.hlostatus import HloStatus
 from helao.core.models.sample import LiquidSample, SampleInheritance
 from helao.hexagon.adapters.errors import UnwiredPortError
-from helao.hexagon.adapters.native.data_file import NativeDataFileWriter
 from helao.hexagon.adapters.native.data_sink import NativeDataSinkAdapter
-from helao.hexagon.adapters.native.data_stream import NativeDataStreamer
-from helao.hexagon.adapters.native.finalizer import NativeActionFinalizer
 from helao.hexagon.ports.data_sink import DataSinkPort
 from helao.hexagon.tests.native_fixtures import make_base, mk_active
 
@@ -20,9 +17,6 @@
 def _bound(tmp_path):
     base = make_base(str(tmp_path / "RUNS_ACTIVE"))
     active, dflt = mk_active(base)
-    active.data_stream = NativeDataStreamer(active)  # type: ignore[reportAttributeAccessIssue]
-    active.data_file_writer = NativeDataFileWriter(active)  # type: ignore[reportAttributeAccessIssue]
-    active.action_finalizer = NativeActionFinalizer(active)  # type: ignore[reportAttributeAccessIssue]
     return base, active, dflt, NativeDataSinkAdapter().for_action(active)
 
 
@@ -60,7 +54,7 @@
 
 
 @pytest.mark.asyncio
-async def test_q2_members_delegate_to_legacy_active(tmp_path):
+async def test_q2_members_delegate_to_the_session(tmp_path):
     base, active, dflt, sink = _bound(tmp_path)
     sample = LiquidSample(
         sample_no=1,
@@ -68,7 +62,7 @@
         inheritance=SampleInheritance.allow_both,
     )
     await sink.append_sample([sample], IO="in")
-    # legacy Active.append_sample ran: sample recorded with defaults filled
+    # ActionSession.append_sample ran: sample recorded with defaults filled
     # (MultisubscriberQueue has no qsize; its put with no subscribers is a
     # drop, so the status broadcast is asserted via the sample side effects)
     assert active.action.samples_in
--- a/helao/hexagon/tests/test_native_data_stream.py
+++ b/helao/hexagon/tests/test_native_data_stream.py
@@ -7,11 +7,11 @@
 
 import asyncio
 import os
-from uuid import uuid4
+from uuid import UUID, uuid4
 
 import pytest
 
-from helao.core.models.data import DataModel
+from helao.core.models.data import DataModel, DataPackageModel
 from helao.core.models.hlostatus import HloStatus
 from helao.core.servers.active_data_stream import DataStreamer
 from helao.hexagon.adapters.native.data_file import NativeDataFileWriter
@@ -42,10 +42,10 @@
 def _native_active(tmp_path):
     base = make_base(str(tmp_path / "RUNS_ACTIVE"))
     active, dflt = mk_active(base)
-    # mini-graft: both write collaborators native (the drain loop hops
-    # active.log_data_set_output_file -> data_file_writer)
-    active.data_stream = NativeDataStreamer(active)  # type: ignore[reportAttributeAccessIssue]  # the swap under test
-    active.data_file_writer = NativeDataFileWriter(active)  # type: ignore[reportAttributeAccessIssue]  # the swap under test
+    # both write collaborators are native by construction (the drain loop
+    # hops active.log_data_set_output_file -> data_file_writer)
+    assert isinstance(active.data_stream, NativeDataStreamer)
+    assert isinstance(active.data_file_writer, NativeDataFileWriter)
     return base, active, dflt
 
 
@@ -56,6 +56,10 @@
     await active.enqueue_data(DataModel(data={}, errors=[], status=HloStatus.finished))
     active.enqueue_data_nowait(DataModel(data={dflt: {"t_s": 2}}, errors=[]))
     assert active.num_data_queued == 2  # empty-data packet doesn't count
+    # moved from unit_test_active_data_stream (enqueue_nowait_counts): the
+    # nowait path skips an empty-data packet too
+    active.enqueue_data_nowait(DataModel(data={}, errors=[]))
+    assert active.num_data_queued == 2
 
 
 @pytest.mark.asyncio
@@ -129,6 +133,45 @@
     base = make_base(str(tmp_path / "RUNS_ACTIVE"))
     active, _ = mk_active(base)
     active.action.save_data = False
-    active.data_stream = NativeDataStreamer(active)  # type: ignore[reportAttributeAccessIssue]  # the swap under test
     await active.log_data_task()  # returns immediately, no subscription
     assert len(base.data_q.subscribers) == 0
+
+
+@pytest.mark.asyncio
+async def test_realtime_forwarding(tmp_path):
+    """Moved from unit_test_active_data_stream: offset 0 + explicit epoch_ns
+    passes straight through both realtime forms."""
+    _, active, _ = _native_active(tmp_path)
+    assert active.get_realtime_nowait(epoch_ns=123456789) == 123456789
+    assert await active.get_realtime(epoch_ns=123456789) == 123456789
+
+
+def test_add_new_listen_uuid_mutates_the_session(tmp_path):
+    """Moved from unit_test_active_data_stream: listen_uuids lives on the
+    session (seeded with the action uuid at construction) and the streamer
+    mutates that same list."""
+    _, active, _ = _native_active(tmp_path)
+    before = list(active.listen_uuids)
+    new = UUID("00000000-0000-0000-0000-0000000000ff")
+    active.add_new_listen_uuid(new)
+    assert active.action.action_uuid in before
+    assert new in active.listen_uuids
+    assert active.data_stream.active.listen_uuids is active.listen_uuids
+
+
+def test_assemble_and_build_package(tmp_path):
+    """Moved from unit_test_active_data_stream."""
+    _, active, dflt = _native_active(tmp_path)
+    dm = DataModel(
+        data={dflt: {"t_s": 1, "value": 2}}, errors=[], status=HloStatus.active
+    )
+    pkg = active.assemble_data_msg(datamodel=dm)
+    assert isinstance(pkg, DataPackageModel)
+    assert pkg.action_uuid == active.action.action_uuid
+    assert pkg.action_name == active.action.action_name
+    built, has_data = active._build_data_package(dm)
+    _, empty_has = active._build_data_package(
+        DataModel(data={}, errors=[], status=HloStatus.active)
+    )
+    assert isinstance(built, DataPackageModel)
+    assert has_data is True and empty_has is False
--- a/helao/hexagon/tests/test_native_finalizer.py
+++ b/helao/hexagon/tests/test_native_finalizer.py
@@ -1,7 +1,7 @@
 """NativeActionFinalizer (P2b-1): verbatim re-body of legacy ActionFinalizer
 (helao/core/servers/active_finalizer.py) — the ce846da1 join-drain-close
 chain. Source-parity pin + behavior on real tmp trees with a full native
-collaborator set (mini-graft): finish drains queued data BEFORE closing
+collaborator set: finish drains queued data BEFORE closing
 handles, closes every file, cancels data_logger, writes the final -act.yml,
 schedules move_dir (manual included -- it is the journal eviction
 point), pops base.actives into history;
@@ -19,9 +19,8 @@
 import helao.hexagon.adapters.native.finalizer as native_finalizer_mod
 from helao.core.error import ErrorCodes
 from helao.core.models.data import DataModel
+from helao.core.models.hlostatus import HloStatus
 from helao.core.servers.active_finalizer import ActionFinalizer
-from helao.hexagon.adapters.native.data_file import NativeDataFileWriter
-from helao.hexagon.adapters.native.data_stream import NativeDataStreamer
 from helao.hexagon.adapters.native.finalizer import NativeActionFinalizer
 from helao.hexagon.adapters.native.meta_writer import NativeMetaFileWriter
 from helao.hexagon.tests.native_fixtures import make_base, mk_action, mk_active
@@ -46,15 +45,13 @@
 
 
 def _grafted_active(tmp_path, **action_over):
-    """Full mini-graft: all three per-Active collaborators + meta writer
-    native, base.actives registration, data_logger running."""
+    """A session over a bare host (native collaborators and meta writer by
+    construction), registered in base.actives, data_logger running."""
     base = make_base(str(tmp_path / "RUNS_ACTIVE"))
-    base.meta_writer = NativeMetaFileWriter(base)  # type: ignore[reportAttributeAccessIssue]
     action = mk_action(**action_over) if action_over else None
     active, dflt = mk_active(base, action=action)
-    active.data_stream = NativeDataStreamer(active)  # type: ignore[reportAttributeAccessIssue]  # the swap under test
-    active.data_file_writer = NativeDataFileWriter(active)  # type: ignore[reportAttributeAccessIssue]  # the swap under test
-    active.action_finalizer = NativeActionFinalizer(active)  # type: ignore[reportAttributeAccessIssue]  # the swap under test
+    assert isinstance(active.action_finalizer, NativeActionFinalizer)
+    assert isinstance(base.meta_writer, NativeMetaFileWriter)
     action_uuid = active.action.action_uuid
     assert action_uuid is not None
     base.actives[action_uuid] = active
@@ -146,7 +143,7 @@
     await active.enqueue_data(DataModel(data={dflt: {"t_s": 1}}, errors=[]))
     await asyncio.sleep(0.1)
     assert active.file_conn_dict[dflt].file is not None
-    await active.substitute()
+    await active.action_finalizer.substitute()  # ActionSession has no substitute
     # aiofiles handle closed: writing now raises ValueError on closed file
     with pytest.raises(ValueError):
         await active.file_conn_dict[dflt].file.write("x")
@@ -178,6 +175,52 @@
 
 
 @pytest.mark.asyncio
+async def test_split_keep_active_then_finish_all_finishes_the_chain(
+    tmp_path, monkeypatch
+):
+    """Moved from unit_test_active_finalizer (split_keep_active_then_finish_all):
+    split(uuid_list=[]) forks a child with fresh file conns and marks the
+    parent split but leaves it open; finish_all then finishes both, and a row
+    streamed to the child's new conn lands on disk."""
+
+    async def fake_move_dir(action, base=None):
+        pass
+
+    monkeypatch.setattr(native_finalizer_mod, "move_dir", fake_move_dir)
+    base, active, dflt = _grafted_active(tmp_path)
+    await _start_logger(base, active)
+    await active.enqueue_data(DataModel(data={dflt: {"t_s": 0}}, errors=[]))
+    await asyncio.sleep(0.1)
+    parent_uuid = active.action.action_uuid
+
+    new_keys = await active.split(uuid_list=[])
+    assert active.action.action_uuid != parent_uuid
+    assert len(active.action_list) == 2
+    parent = active.action_list[1]
+    assert parent.action_uuid == parent_uuid
+    assert HloStatus.split in parent.action_status
+    assert HloStatus.finished not in parent.action_status
+    assert new_keys and all(k in active.file_conn_dict for k in new_keys)
+
+    await active.enqueue_data(DataModel(data={new_keys[0]: {"t_s": 999}}, errors=[]))
+    await asyncio.sleep(0.1)
+    await active.action_finalizer.finish_all()  # ActionSession has no finish_all
+    await asyncio.sleep(0.1)
+    assert all(HloStatus.finished in a.action_status for a in active.action_list)
+    rows = []
+    for dirpath, _dirs, files in os.walk(str(base.helaodirs.save_root)):
+        for fn in files:
+            if fn.endswith(".hlo"):
+                rows += (
+                    open(os.path.join(dirpath, fn))
+                    .read()
+                    .split("%%\n", 1)[1]
+                    .splitlines()
+                )
+    assert '{"t_s":999}' in rows
+
+
+@pytest.mark.asyncio
 async def test_manual_action_calls_move_dir_and_writes_exp_seq(tmp_path, monkeypatch):
     """A manual action must still reach ``move_dir`` -- that is where the
     producing server evicts its own journal entry (plan A34, D-C). The
--- a/helao/hexagon/tests/test_native_meta_writer.py
+++ b/helao/hexagon/tests/test_native_meta_writer.py
@@ -34,7 +34,7 @@
 
 
 def _swap(base, tmp_path):
-    base.meta_writer = NativeMetaFileWriter(base)  # type: ignore[reportAttributeAccessIssue]
+    assert isinstance(base.meta_writer, NativeMetaFileWriter)  # native by construction
     return base
 
 
@@ -54,6 +54,16 @@
 
 
 @pytest.mark.asyncio
+async def test_write_act_save_act_false_writes_nothing(tmp_path):
+    """Moved from unit_test_base_meta_writer (write_act_save_act_false)."""
+    save_root = str(tmp_path / "RUNS_ACTIVE")
+    base = _swap(make_base(save_root), tmp_path)
+    action = mk_action(save_act=False)
+    await base.write_act(action)
+    assert not os.path.exists(os.path.join(save_root, str(action.action_output_dir)))
+
+
+@pytest.mark.asyncio
 async def test_write_meta_atomic_tmp_shape(tmp_path):
     """Atomic write goes through a short .<hex>.tmp sibling then os.replace
     (base_meta_writer.py:76-79)."""
--- a/helao/hexagon/tests/test_active_graft.py
+++ b/helao/hexagon/tests/test_active_graft.py
@@ -26,7 +26,39 @@
 from helao.hexagon.adapters.native.meta_writer import NativeMetaFileWriter
 from helao.hexagon.app.active_graft import ActiveWriteGraft, graft_active_write_path
 from helao.hexagon.app.wiring import PortWiring
-from helao.hexagon.tests.native_fixtures import make_base, mk_action
+from helao.hexagon.tests.native_fixtures import mk_action
+
+
+def make_base(save_root: str) -> Base:
+    """The legacy bare-``Base`` fixture ``native_fixtures`` provided before
+    B7b rebuilt it on ``ActionHost``. Kept here, verbatim, for the one commit
+    this file outlives it: B7b commit 2 deletes the graft and this file."""
+    from types import SimpleNamespace
+
+    from helao.core.hooks import HookSet
+    from helao.core.models.machine import MachineModel
+    from helao.helpers.multisubscriber_queue import MultisubscriberQueue
+
+    base = Base.__new__(Base)
+    base.app = SimpleNamespace(driver=None)  # type: ignore[reportAttributeAccessIssue]
+    base.server = MachineModel(
+        server_name="ACTSRV",
+        machine_name="test-machine",
+        hostname="127.0.0.1",
+        port=8000,
+    )
+    base.world_cfg = {"dummy": False, "simulation": False}
+    base.ntp_offset = 0.0
+    base.helaodirs = SimpleNamespace(save_root=save_root)  # type: ignore[reportAttributeAccessIssue]
+    base.status_q = MultisubscriberQueue()
+    base.data_q = MultisubscriberQueue()
+    base.actives = {}
+    base.history = {}  # type: ignore[reportAttributeAccessIssue]
+    base.local_action_task_queue = []
+    base.prefinish_hooks = HookSet.empty()
+    base._init_collaborators()
+    return base
+
 
 # ---------------------------------------------------------------------------
 # drift pin (Q1): the graft reproduces this body verbatim (+ swap lines).
--- a/helao/core/tests/test_run_state_wiring.py
+++ b/helao/core/tests/test_run_state_wiring.py
@@ -316,26 +316,23 @@
     """
     import asyncio
 
-    import helao.core.servers.active_finalizer as finalizer_module
-    import helao.core.servers.base as base_module
+    import helao.hexagon.adapters.native.finalizer as finalizer_module
     from helao.core.error import ErrorCodes
-    from helao.core.tests.unit_test_active_finalizer import _make_active_for_journal
+    from helao.hexagon.tests.native_fixtures import _make_active_for_journal
 
     base, active = _make_active_for_journal(tmp_path, manual_action=True)
+    journal = base.run_journal
+    assert journal is not None
 
     async def _noop_dispatch(*args, **kwargs):
         return {}, ErrorCodes.none
 
-    orig = (
-        base_module.async_private_dispatcher,
-        finalizer_module.async_private_dispatcher,
-    )
-    base_module.async_private_dispatcher = _noop_dispatch
+    orig = finalizer_module.async_private_dispatcher
     finalizer_module.async_private_dispatcher = _noop_dispatch
     try:
         await active.myinit()
         await asyncio.sleep(0.02)
-        assert set(base.run_journal.working_set()) == {
+        assert set(journal.working_set()) == {
             str(active.action.action_uuid)
         }, "the action was never journalled active; the test proves nothing"
 
@@ -343,16 +340,13 @@
         # move_dir is scheduled fire-and-forget by _finish
         for _ in range(100):
             await asyncio.sleep(0.01)
-            if base.run_journal.working_set() == {}:
+            if journal.working_set() == {}:
                 break
     finally:
-        (
-            base_module.async_private_dispatcher,
-            finalizer_module.async_private_dispatcher,
-        ) = orig
+        finalizer_module.async_private_dispatcher = orig
 
     assert (
-        base.run_journal.working_set() == {}
+        journal.working_set() == {}
     ), "a manual action stayed active in the journal after it finished"
 
 
```

- [ ] **Step 5.5: Apply it.**

```
patch -p1 -d "$WT" --dry-run < "$X/t5_tests.patch" && patch -p1 -d "$WT" < "$X/t5_tests.patch"
```
Expected: seven `checking file …` lines, then seven `patching file …` lines: `test_native_data_file.py`, `test_native_data_sink.py`, `test_native_data_stream.py`, `test_native_finalizer.py`, `test_native_meta_writer.py`, `test_active_graft.py`, `helao/core/tests/test_run_state_wiring.py`. No `FAILED`/`Hunk` lines. If the dry run reports a failed hunk, STOP: a file differs from `64f2cf15`.

- [ ] **Step 5.6: Point `test_estop_fixes.py`'s five `seq_unpacker` imports at their real home.**

```
sed -i 's/from helao.core.servers.orch_unpack import seq_unpacker/from helao.hexagon.app.orch_unpack import seq_unpacker/' "$WT/helao/hexagon/tests/test_estop_fixes.py"
grep -c 'from helao.hexagon.app.orch_unpack import seq_unpacker' "$WT/helao/hexagon/tests/test_estop_fixes.py"
grep -c 'helao.core.servers' "$WT/helao/hexagon/tests/test_estop_fixes.py"
```
Expected: `5`, then `0`. (`helao/core/servers/orch_unpack.py` re-exports the same function object, so the behaviour is unchanged.)

- [ ] **Step 5.7: Delete the four moved unit scripts.**

```
rm "$WT/helao/core/tests/unit_test_active_data_file.py" "$WT/helao/core/tests/unit_test_active_data_stream.py" "$WT/helao/core/tests/unit_test_active_finalizer.py" "$WT/helao/core/tests/unit_test_base_meta_writer.py"
git -C "$WT" grep -n -E '^\s*(from|import) .*unit_test_(active_data_file|active_data_stream|active_finalizer|base_meta_writer)' -- '*.py'
```
Expected: exactly the four `run_unit_tests.py` import lines (21, 22, 24, 31). Task 7 removes them. Any other import hit means a caller was missed: STOP. (The grep matches import statements only. The "Moved from unit_test_…" docstrings and comments this task adds to four `test_native_*.py` files, and `unit_test_active_executor.py`'s docstring until Task 6 deletes that file, are expected and are not matched.)

- [ ] **Step 5.8: Run every touched file.**

```
for f in helao/hexagon/tests/test_native_artifact_store.py helao/hexagon/tests/test_native_data_file.py helao/hexagon/tests/test_native_data_sink.py helao/hexagon/tests/test_native_data_stream.py helao/hexagon/tests/test_native_finalizer.py helao/hexagon/tests/test_native_meta_writer.py helao/core/tests/test_run_state_wiring.py helao/hexagon/tests/test_estop_fixes.py helao/hexagon/tests/test_active_graft.py; do printf '%s ' "$f"; timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -m pytest -q -p no:cacheprovider --color=no -W ignore "$f" 2>&1 | tail -1; done | tee "$X/t5_after.txt"
```
Expected:
```
helao/hexagon/tests/test_native_artifact_store.py 6 passed …
helao/hexagon/tests/test_native_data_file.py 12 passed …
helao/hexagon/tests/test_native_data_sink.py 5 passed …
helao/hexagon/tests/test_native_data_stream.py 8 passed …
helao/hexagon/tests/test_native_finalizer.py 7 passed …
helao/hexagon/tests/test_native_meta_writer.py 7 passed …
helao/core/tests/test_run_state_wiring.py 15 passed …
helao/hexagon/tests/test_estop_fixes.py 38 passed …
helao/hexagon/tests/test_active_graft.py 5 passed …
```
The deltas account for the moves: data_file +3, data_stream +3 (the fourth moved check is two lines in an existing test), finalizer +1, meta_writer +1.

- [ ] **Step 5.9: (moved)** The mutate-and-observe probes for this task's moved checks run in Task 7 Step 7.0a, alone, after every wave-1 task has finished, so no parallel task ever sees a mutated production file.

- [ ] **Step 5.10: The fixture is engine-free; the only engine imports left are the ones Task 12 deletes.** Create `$X/t5_engine_refs.py`:

```python
"""B7b Task 5: engine imports left in the files Task 5 touches (Import/ImportFrom only).

Usage: python t5_engine_refs.py <repo root>
Prints one "<file>:<line> <module>" per import of helao.core.servers.
"""

import ast
import sys
from pathlib import Path

FILES = [
    "helao/hexagon/tests/native_fixtures.py",
    "helao/hexagon/tests/test_native_artifact_store.py",
    "helao/hexagon/tests/test_native_data_file.py",
    "helao/hexagon/tests/test_native_data_sink.py",
    "helao/hexagon/tests/test_native_data_stream.py",
    "helao/hexagon/tests/test_native_finalizer.py",
    "helao/hexagon/tests/test_native_meta_writer.py",
    "helao/core/tests/test_run_state_wiring.py",
    "helao/hexagon/tests/test_estop_fixes.py",
]
root = Path(sys.argv[1])
for rel in FILES:
    tree = ast.parse((root / rel).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        for name in names:
            if name.startswith("helao.core.servers"):
                print(f"{rel}:{node.lineno} {name}")
```

Create `$X/t5_fixture_engine_free.py`:

```python
"""B7b Task 5: importing the rebuilt fixture and building a session loads no engine module."""

import asyncio
import sys
import tempfile

from helao.hexagon.tests import native_fixtures as nf

with tempfile.TemporaryDirectory() as tmp:
    host = nf.make_base(tmp)
    session, _ = nf.mk_active(host)


async def _journal():
    with tempfile.TemporaryDirectory() as tmp:
        nf._make_active_for_journal(tmp, manual_action=True)


asyncio.run(_journal())
engine = sorted(m for m in sys.modules if m.startswith("helao.core.servers"))
print(type(host).__name__, type(session).__name__, "engine modules:", engine)
sys.exit(1 if engine else 0)
```

```
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t5_engine_refs.py" "$WT"
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t5_fixture_engine_free.py" 2>/dev/null | tail -1
```
Expected, exactly these six lines. They are the four parity pins and the two legacy halves, all deleted by Task 12:
```
helao/hexagon/tests/test_native_artifact_store.py:28 helao.core.servers.base
helao/hexagon/tests/test_native_data_file.py:13 helao.core.servers.active_data_file
helao/hexagon/tests/test_native_data_sink.py:24 helao.core.servers.base
helao/hexagon/tests/test_native_data_stream.py:16 helao.core.servers.active_data_stream
helao/hexagon/tests/test_native_finalizer.py:23 helao.core.servers.active_finalizer
helao/hexagon/tests/test_native_meta_writer.py:13 helao.core.servers.base_meta_writer
```
then `ActionHost ActionSession engine modules: []`. (`test_active_graft.py` still imports the engine; commit 2 deletes it.)

- [ ] **Step 5.11: pyright, no file worse than Task 0.** This needs `pyrightconfig.json` in the worktree (Task 0 copies it).

```
cd "$WT" && timeout 600 pyright --outputjson helao/hexagon/tests/native_fixtures.py helao/hexagon/tests/test_native_artifact_store.py helao/hexagon/tests/test_native_data_file.py helao/hexagon/tests/test_native_data_sink.py helao/hexagon/tests/test_native_data_stream.py helao/hexagon/tests/test_native_finalizer.py helao/hexagon/tests/test_native_meta_writer.py helao/core/tests/test_run_state_wiring.py helao/hexagon/tests/test_estop_fixes.py helao/hexagon/tests/test_active_graft.py > "$X/t5_pyright.json"; echo rc=$?
```
Create `$X/t5_pyright_counts.py`:

```python
"""B7b Task 5: files analyzed, and error count per file, from a pyright --outputjson file."""

import collections
import json
import os
import sys

doc = json.load(open(sys.argv[1], encoding="utf-8"))
per = collections.Counter()
for diag in doc["generalDiagnostics"]:
    if diag["severity"] == "error":
        per[os.path.relpath(diag["file"])] += 1  # relative to --cwd "$WT"
print("analyzed", doc["summary"]["filesAnalyzed"])
for path, n in sorted(per.items()):
    print(n, path)
```

```
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t5_pyright_counts.py" "$X/t5_pyright.json"
```
Expected: `analyzed 10`. The files with errors are the ones below, and every other file has none. If `analyzed` is not 10, the run is vacuous: STOP. Measured per-file error counts, `64f2cf15` → after Task 5:

| file | before | after |
|---|---|---|
| `native_fixtures.py` | 0 | 0 |
| `test_native_artifact_store.py` | 0 | 0 |
| `test_native_data_file.py` | 1 | 0 |
| `test_native_data_sink.py` | 0 | 0 |
| `test_native_data_stream.py` | 1 | 0 |
| `test_native_finalizer.py` | 6 | 4 |
| `test_native_meta_writer.py` | 1 | 0 |
| `test_run_state_wiring.py` | 2 | 2 |
| `test_estop_fixes.py` | 32 | 32 |
| `test_active_graft.py` | 9 | 0 |

Two of the fixture's lines carry `# type: ignore[reportAttributeAccessIssue]`, and `test_run_state_wiring` narrows `base.run_journal` into a local `journal`. Both are there because `ActionHost` types `aloop`/`run_journal` as `Optional`. Without them the port adds 5 errors (measured), so do not remove them.

**Files for the controller's commit (commit 1):**
- Modified: `helao/hexagon/tests/native_fixtures.py`, `helao/hexagon/tests/test_native_data_file.py`, `helao/hexagon/tests/test_native_data_sink.py`, `helao/hexagon/tests/test_native_data_stream.py`, `helao/hexagon/tests/test_native_finalizer.py`, `helao/hexagon/tests/test_native_meta_writer.py`, `helao/hexagon/tests/test_active_graft.py`, `helao/core/tests/test_run_state_wiring.py`, `helao/hexagon/tests/test_estop_fixes.py`
- Deleted: `helao/core/tests/unit_test_active_data_file.py`, `helao/core/tests/unit_test_active_data_stream.py`, `helao/core/tests/unit_test_active_finalizer.py`, `helao/core/tests/unit_test_base_meta_writer.py`
- Plus, from Task 7: the eight `run_unit_tests.py` lines listed under Interfaces.
- All of these are `black`-clean as written (checked). `black` leaves every one unchanged.

---

### Task 6: The remaining `unit_test_*` engine importers, and four shared-logic tests, move onto native hosts

Spec: D-B7b.6; §5.1 rows `test_orch_queue_paging`, `test_standalone_operator`, `test_analysis_recovery`, `test_upload_set`; §5.2 rows `active_executor`, `base_api`, `base_endpoints`, `base_live_buffer`, `base_status`, `config_seam`, `dispatcher`, `estop_sync`, `orch_lifecycle`, `orch_queues`.

**Files:**
- Modify (in place, by `$X/t6_port_edits.py`, Step 6.2):
  - `helao/core/tests/test_standalone_operator.py:26-50` (`_bare_orch`), `:111-127`, `:482`, `:523-545`, `:549-567` (deleted test), `:978`, `:1721` (`__main__` call)
  - `helao/core/tests/test_orch_queue_paging.py:18`, `:66`, `:69`
  - `helao/core/tests/test_upload_set.py:6`
  - `helao/core/tests/test_analysis_recovery.py:966-972`
  - `helao/core/tests/unit_test_dispatcher.py:18`, `:43`, `:53`, `:217-219`, `:228-245`, `:287`
  - `helao/core/tests/unit_test_base_live_buffer.py:1-47`, `:124-129`, `:185-186`
  - `helao/core/tests/unit_test_estop_sync.py:5-15`, `:30-35`, `:50`, `:113-127`, `:180`
  - `helao/core/tests/unit_test_orch_lifecycle.py:1-18`, `:40-51`, `:95`, `:188`
  - `helao/core/tests/unit_test_orch_queues.py:1-17`, `:34-46`, `:77`, `:89`, `:221-271`, `:316-329`, `:392-394`
  - `helao/hexagon/tests/test_executor_runner.py:8`, `:75` (fixture typing)
- Rewrite (full content, Step 6.3): `helao/core/tests/unit_test_base_status.py`, `helao/core/tests/unit_test_config_seam.py`
- Append (Step 6.4): `helao/hexagon/tests/test_executor_runner.py`, `helao/hexagon/tests/test_endpoint_manager.py`, `helao/hexagon/tests/test_action_route.py`, `helao/hexagon/tests/test_action_context.py`
- Delete (Step 6.5): `helao/core/tests/unit_test_active_executor.py`, `helao/core/tests/unit_test_base_api.py`, `helao/core/tests/unit_test_base_endpoints.py`
- Scratch (not tracked): `$X/t6_port_edits.py`, `$X/t6_run_unit.py`, `$X/t6_pyright_files.txt`, `$X/t6_*` logs

**Interfaces:**
- Consumes: nothing from Tasks 1–5. Every native symbol used already exists on `64f2cf15`: `OrchHost.__new__` + `OrchHost._init_orch_collaborators()` (`orch_host.py:232`), `ActionHost` (`action_host.py:116`), `action_route.wrap_action_endpoint(fn, host)` (`action_route.py:115`), `action_context.build_action` / `ActionContext`, `orch_payloads._histories_payload` / `_history_page_payload` / `_status_summary_payload` / `_step_flags_payload` / `_set_step_flag` / `_queue_counts` / `_queue_object_payload`, `helao.helpers.file_utils._relative_file_name` (`file_utils.py:33`), `action_host.ACTION_PARAM_KEYS` (`action_host.py:74`), `endpoint_manager.async_action_dispatcher` (bound at import, `endpoint_manager.py:36`), `LegacyClockAdapter(offset_s)`, `PortWiring(...)`.
- Produces:
  - `$X/t6_run_unit.py <stem> [<stem> ...]` — imports `helao.core.tests.unit_test_<stem>` and calls `<stem>_unit_test()`; prints `UNIT <stem>: PASS|FAIL` per stem and `UNIT-SUMMARY <n> passed, <m> failed`; exits 1 on any FAIL. Task 7 reuses it.
  - The seven ported `unit_test_*` modules keep their function names (`base_live_buffer_unit_test`, `base_status_unit_test`, `config_seam_unit_test`, `dispatcher_unit_test`, `estop_sync_unit_test`, `orch_lifecycle_unit_test`, `orch_queues_unit_test`), so `run_unit_tests.py` imports them unchanged.
  - For Task 7: the exact `run_unit_tests.py` lines this task's deletions orphan (listed at the end of this task). Task 6 does **not** edit `run_unit_tests.py`.

**Execution:** can run in parallel with Tasks 1, 2, 3, 4 and 5. It mutates no production file (its probes run in Task 7 Step 7.0b). It touches only the files listed above; it must not touch `run_unit_tests.py`, `helao/hexagon/tests/native_fixtures.py`, any `helao/hexagon/tests/test_native_*.py`, `unit_test_active_data_file.py`, `unit_test_active_data_stream.py`, `unit_test_active_finalizer.py`, `unit_test_base_meta_writer.py` or `test_run_state_wiring.py` (Task 5 owns those). No commit: Task 7 commits commit 1.

#### Check-to-test mapping (D-B7b.6)

Every check in the three deleted files, and every check the in-place ports drop, is listed with the native test that covers it after this task, or the reason it is engine-internal.

`unit_test_active_executor.py` (move-and-delete → `helao/hexagon/tests/test_executor_runner.py`):

| legacy check | covered after Task 6 by |
|---|---|
| `collaborator_wired` | engine wiring: `Active.__init__` building an `ExecutorRunner` back-reference. Native construction is `ActionSession`'s, exercised end to end by the action golden master (Task 2) |
| `start_executor_to_completion` | **moved**: `test_start_executor_schedules_the_loop_and_its_done_callback_fires` |
| `oneoff_executor` | **moved**: `test_a_oneoff_executor_runs_exec_and_post_with_no_poll_loop` |
| `stop_action_task_manual_stop` | existing `test_stop_action_task_ends_the_poll_loop` (poll stops after two, `_manual_stop` fires) |
| `delegators_forward` | engine delegation (`Active` → `executor_runner` forwarders) |

`unit_test_base_api.py` (spec: delete; this plan: move-and-delete, Plan decision P-F.1):

| legacy check | covered after Task 6 by |
|---|---|
| `ACTION_PARAM_KEYS` includes 8 envelope keys | **moved**: `test_action_route.py::test_the_envelope_keys_are_split_from_action_params` (native list, `action_host.py:74`) |
| `_build_action_from_kwargs` returns the passed Action | `test_action_context.py::test_an_orchestrator_envelope_is_used_as_the_base_action` |
| extra kwargs fold into `action_params` | `test_action_context.py::test_loose_kwargs_fold_into_action_params` |
| existing `action_params` not clobbered | `test_action_context.py::test_an_envelope_value_wins_over_a_loose_kwarg` |
| a new kwarg merges into the envelope | **moved**: `test_action_context.py::test_a_loose_kwarg_absent_from_the_envelope_is_merged_into_it` |
| missing Action → blank Action | `test_action_context.py::test_a_missing_envelope_yields_a_blank_action_without_raising` |
| blank fallback absorbs kwargs | `test_action_context.py::test_loose_kwargs_fold_into_action_params` |
| wrapper preserves signature + adds `action_version` | `test_action_route.py::test_action_and_version_are_synthesized_when_absent`, `::test_an_inline_action_parameter_is_not_duplicated` |
| sync wrapper returns its native result; context set in the call | **moved**: `test_action_route.py::test_a_sync_handler_is_wrapped_synchronously_and_gets_its_context` (the native sync branch, `action_route.py:148-155`, had no test) |
| async wrapper returns its awaited result; context set | `test_action_route.py::test_the_wrapper_injects_a_context_carrying_the_request_action` |
| `ACTION_CTX` reset after the call (sync and async) | engine-internal: the `ContextVar` plumbing. Native passes the context as the `ctx` argument; there is nothing to reset |
| fn defaults folded into `action_params` | `test_action_context.py::test_defaults_not_supplied_by_the_caller_are_recorded`, `::test_collect_default_params_reads_the_signature` |
| supplied kwarg beats the fn default | `test_action_route.py::test_the_wrapper_injects_a_context_carrying_the_request_action` (`duration=7.0` over the `-1` default) |
| `ActiveParams.action` is the original; `as_dict` round-trips `file_conn_params_dict` | **moved**: `test_action_context.py::test_active_params_round_trips_its_file_conn_params` (`ActiveParams` is `helao.helpers`, not engine) |

`unit_test_base_endpoints.py` (move-and-delete → `helao/hexagon/tests/test_endpoint_manager.py`, onto `app/endpoint_manager.py`):

| legacy check | covered after Task 6 by |
|---|---|
| `get_endpoint_urls` path/name/params | `test_endpoint_urls_carry_the_params_shape` |
| `endpoint_queues_init` | `test_a_queue_is_created_per_action_endpoint` |
| `init_endpoint_status` registers prefix endpoints, sets `fast_urls`, builds queues | `test_action_endpoints_are_registered_for_status_monitoring`, `test_private_routes_are_not_registered_as_endpoints`, `test_a_queue_is_created_per_action_endpoint`, `test_endpoint_urls_carry_the_params_shape` |
| `init_endpoint_status_dyn_endpoints_called` | **moved**: `test_init_endpoint_status_awaits_the_dyn_endpoints_callback` |
| `dyn_endpoints_init` | **moved**: `test_dyn_endpoints_init_schedules_the_endpoint_scan` |
| `process_endpoint_queue_success` | **moved**: `test_a_queued_endpoint_action_is_redispatched_no_wait_and_drained` |
| `process_endpoint_queue_requeues_on_failure` | `test_a_failed_redispatch_requeues_rather_than_dropping` |
| `process_unified_queue` | **moved**: `test_the_unified_queue_is_redispatched_and_drained` |

Checks the in-place ports drop:

| file | dropped check | reason |
|---|---|---|
| `unit_test_base_status.py` | `_ws_relay` accept/subscribe/relay | engine relay (spec §5.2); native WS encoding is pinned by `harness/tests/test_ws_frames.py` and D-B7b.4 |
| `unit_test_config_seam.py` | `typed_server_cfg.host` matches the dict | legacy config wrapper; `ActionHost` has none, and `test_action_host_member_coverage.py:70-71` lists `typed_cfg`/`typed_server_cfg` as deliberate exclusions |
| `unit_test_config_seam.py` | `Base(app=stub)` raises `ValueError` without `run_type` | **retargeted, not dropped**: `ActionHost` does not re-validate (`run_type` becomes `None`, `action_host.py:216`); `fast_launcher.py:81` validates through `read_validated_config` before any app is built, so the check now calls `HelaoConfig.model_validate` (Plan decision P-F.3) |
| `unit_test_orch_queues.py` | `live_buffer_mgr`/`status_broadcaster` on the orch | legacy `Base` collaborators; `OrchHost` has neither. The check now asserts the seven `_init_orch_collaborators` members plus `finalize_lock` |
| `test_standalone_operator.py` | `test_prepend_sequences_helper` | spec §5.1: `_prepend_sequences` exists only in `orch_api`; `OrchHost`'s route takes a typed `list[Sequence]` body, whose coercion is FastAPI's |

#### Plan decisions (spec silent)

- **P-F.1 (default; spec says "delete"):** `unit_test_base_api.py` is move-and-delete. Measured: the 24 native tests (14 in `test_action_context.py`, 10 in `test_action_route.py`, the spec's count is right) do not cover four of its checks: the `ACTION_PARAM_KEYS` contents, the sync wrapper branch, a new kwarg merging into an envelope, and the `ActiveParams.as_dict` round-trip. D-B7b.6 forbids dropping them. They move as four small tests.
- **P-F.2 (default):** `unit_test_dispatcher.py`'s RPC check calls `wrap_action_endpoint(acquire_like, None)`. `build_action` returns before `_apply_host_context` when `host is None` (`action_context.py:160-161`), so the check stays about the transport. Host-derived fields are `test_action_context.py`'s job.
- **P-F.3 (default):** `unit_test_config_seam.py` builds both hosts with an explicit stub `PortWiring`. `ActionHost(helao_cfg=...)` without `wiring=` still calls `build_wiring`, which reads the global `CONFIG` (`factory.py:56-57`). The "injected path" check is therefore meaningful only with the wiring seam held fixed. The missing-`run_type` check moves to `HelaoConfig.model_validate` (table above).
- **P-F.4 (default):** `ActionHost` fixtures here use `ActionHost.__new__` plus the attributes the method under test touches (`unit_test_base_live_buffer.py`, `unit_test_base_status.py`), matching the legacy `Base.__new__` bypass they replace. The two that exercise construction itself (`unit_test_config_seam.py`, `test_analysis_recovery.py`) build a real host. The `endpoint_manager` and `action_route` tests reuse each file's existing `_host()`.
- **P-F.5 (default):** `unit_test_orch_queues.py` calls `orch.run_queues.append_action` / `.replace_action` / `.supplement_error_action` directly. `OrchHost` has no such delegators (legacy `Orch` had them, `orch.py:796`), no native code calls them on the host, and the test's subject is `RunQueues`.
- **P-F.6 (default):** two pyright suppressions in `test_standalone_operator.py`, both on test-only lines: `# type: ignore[assignment]` on the `_GSM()` stub assignment (`:978` on `64f2cf15`), and `# pyright: ignore[reportArgumentType]` on `len(uuids)` (`:482`), because `OrchHost.add_split_sequences` is annotated `-> None` (`orch_host.py:292`) but returns the uuid list. The annotation bug is reported, not fixed: B7b edits no native signature for it.

- [ ] **Step 6.1: Record the pre-port counts** (the tree is still `64f2cf15` for these files).

```
for f in helao/core/tests/test_orch_queue_paging.py helao/core/tests/test_standalone_operator.py helao/core/tests/test_analysis_recovery.py helao/core/tests/test_upload_set.py helao/hexagon/tests/test_executor_runner.py helao/hexagon/tests/test_endpoint_manager.py helao/hexagon/tests/test_action_route.py helao/hexagon/tests/test_action_context.py; do printf '%s: ' "$f"; timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -m pytest -q -p no:cacheprovider --color=no "$f" 2>&1 | tail -1; done | tee "$X/t6_counts_before.txt"
```
Expected (warning counts and timings vary; the pass counts must match):
```
helao/core/tests/test_orch_queue_paging.py: 13 passed
helao/core/tests/test_standalone_operator.py: 60 passed
helao/core/tests/test_analysis_recovery.py: 51 passed
helao/core/tests/test_upload_set.py: 11 passed
helao/hexagon/tests/test_executor_runner.py: 6 passed
helao/hexagon/tests/test_endpoint_manager.py: 6 passed
helao/hexagon/tests/test_action_route.py: 10 passed
helao/hexagon/tests/test_action_context.py: 14 passed
```

Create `$X/t6_run_unit.py`:

```python
"""Run named run_unit_tests-style functions; exit 1 unless every one returns True.

Usage: python t6_run_unit.py <stem> [<stem> ...]
<stem> is the part after ``unit_test_`` (e.g. ``dispatcher``); the function
called is ``helao.core.tests.unit_test_<stem>.<stem>_unit_test``. Calling the
function, not the file, matters: some unit_test_* modules have no
``__main__`` block, so running them as a script exits 0 having run nothing.
"""

import importlib
import sys

failed = []
for stem in sys.argv[1:]:
    mod = importlib.import_module(f"helao.core.tests.unit_test_{stem}")
    ok = getattr(mod, f"{stem}_unit_test")()
    print(f"UNIT {stem}: {'PASS' if ok else 'FAIL'}")
    if not ok:
        failed.append(stem)
print(f"UNIT-SUMMARY {len(sys.argv) - 1 - len(failed)} passed, {len(failed)} failed")
sys.exit(1 if failed else 0)
```

```
timeout 900 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t6_run_unit.py" base_live_buffer base_status config_seam dispatcher estop_sync orch_lifecycle orch_queues active_executor base_api base_endpoints > "$X/t6_unit_before.log" 2>&1; echo rc=$?
grep -E '^UNIT' "$X/t6_unit_before.log"
for s in base_live_buffer base_status config_seam dispatcher estop_sync orch_lifecycle orch_queues; do printf '%s ' "$s"; grep -cE "^$s test [0-9]+ passed" "$X/t6_unit_before.log"; done
```
Expected: `rc=0`; ten `UNIT <stem>: PASS` lines and `UNIT-SUMMARY 10 passed, 0 failed`; then the per-module check counts `base_live_buffer 5`, `base_status 5`, `config_seam 9`, `dispatcher 26`, `estop_sync 11`, `orch_lifecycle 5`, `orch_queues 7`.

**Why a runner and not `python helao/core/tests/unit_test_<x>.py`:** `unit_test_dispatcher.py` and `unit_test_base_api.py` have no `__main__` block. Run as scripts they exit 0 having executed nothing. Always call the function.

- [ ] **Step 6.2: Apply the in-place ports.** Create `$X/t6_port_edits.py`:

```python
"""B7b Task 6: in-place ports of ten test files off the legacy engine.

Usage: python t6_port_edits.py <repo root>
Every replacement asserts its exact occurrence count first, so a file that has
drifted from 64f2cf15 stops the script instead of being half-edited.
"""

import sys
from pathlib import Path

ROOT = Path(sys.argv[1])


def edit(rel: str, pairs: list) -> None:
    path = ROOT / rel
    text = path.read_text(encoding="utf-8")
    for old, new, count in pairs:
        found = text.count(old)
        assert found == count, f"{rel}: expected {count} of {old[:60]!r}, found {found}"
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")
    print(f"edited {rel}")


# -- helao/core/tests/test_standalone_operator.py ------------------------------
edit(
    "helao/core/tests/test_standalone_operator.py",
    [
        (
            '''def _bare_orch():
    """A real ``Orch`` with ``__init__`` bypassed but its collaborators wired.

    ``Orch.__init__`` does far more than these tests need (config, network,
    queue files), so they build the object with ``__new__`` and set only the
    attributes under test.

    The CARDS P5 decomposition moved the queue-CRUD and run-id bodies out of
    ``Orch`` into the ``RunQueues`` collaborator, which ``__init__`` assigns at
    orch.py:209 -- the one line ``__new__`` skips. Every ``Orch.__new__`` test
    therefore started failing with ``'Orch' object has no attribute
    'run_queues'`` even though production is fine. Wiring it here (rather than
    at each of the eight call sites) is deliberate: the duplicated
    hand-construction is exactly why all of them rotted together.

    Sufficient because RunQueues holds only the back-reference and resolves
    orch state at call time -- never caching a deque or attribute -- so the
    per-test attribute assignments that follow still take effect.
    """
    from helao.core.servers.orch import Orch
    from helao.hexagon.app.orch_queues import RunQueues

    orch = Orch.__new__(Orch)
''',
            '''def _bare_orch():
    """A real ``OrchHost`` with ``__init__`` bypassed but ``RunQueues`` wired.

    ``OrchHost.__init__`` does far more than these tests need (config, network,
    queue files), so they build the object with ``__new__`` and set only the
    attributes under test.

    The queue-CRUD and run-id bodies live in the ``RunQueues`` collaborator,
    which ``_init_orch_collaborators`` assigns -- a step ``__new__`` skips.
    Wiring it here (rather than at each call site) is deliberate: the
    duplicated hand-construction is exactly why all of them once rotted
    together.

    Sufficient because RunQueues holds only the back-reference and resolves
    orch state at call time -- never caching a deque or attribute -- so the
    per-test attribute assignments that follow still take effect.
    """
    from helao.hexagon.app.orch_host import OrchHost
    from helao.hexagon.app.orch_queues import RunQueues

    orch = OrchHost.__new__(OrchHost)
''',
            1,
        ),
        (
            "    from helao.core.servers import orch_api\n",
            "    from helao.hexagon.app import orch_payloads\n",
            3,
        ),
        ("orch_api._", "orch_payloads._", 9),
        (
            '''def test_prepend_sequences_helper():
    from helao.hexagon.app import orch_payloads

    class _O(_FakeOrch):
        async def prepend_sequences(self, sequences):
            self.prepended = sequences
            return ["u1", "u2"]

    orch = _O()
    uuids = asyncio.run(orch_payloads._prepend_sequences(orch, [{}, {}]))
    assert uuids == ["u1", "u2"]
    assert len(orch.prepended) == 2
    # dict inputs are coerced to Sequence instances
    from helao.helpers.premodels import Sequence

    assert all(isinstance(s, Sequence) for s in orch.prepended)
    print("test_prepend_sequences_helper PASS")


''',
            "",
            1,
        ),
        ("    test_prepend_sequences_helper()\n", "", 1),
        (
            "    orch.globalstatusmodel = _GSM()\n",
            "    orch.globalstatusmodel = _GSM()  # type: ignore[assignment]\n",
            1,
        ),
        (
            "    assert len(uuids) == 3, uuids\n",
            "    # OrchHost.add_split_sequences is annotated -> None but returns the uuids\n"
            "    assert len(uuids) == 3, uuids  # pyright: ignore[reportArgumentType]\n",
            1,
        ),
    ],
)

# -- helao/core/tests/test_orch_queue_paging.py --------------------------------
edit(
    "helao/core/tests/test_orch_queue_paging.py",
    [
        (
            "from helao.core.servers.orch_api import _histories_payload, _history_page_payload\n",
            "from helao.hexagon.app.orch_payloads import _histories_payload, _history_page_payload\n",
            1,
        ),
        (
            "    from helao.core.servers.orch import Orch\n",
            "    from helao.hexagon.app.orch_host import OrchHost\n",
            1,
        ),
        ("    for owner in (Orch, RunQueues):\n", "    for owner in (OrchHost, RunQueues):\n", 1),
    ],
)

# -- helao/core/tests/test_upload_set.py ---------------------------------------
edit(
    "helao/core/tests/test_upload_set.py",
    [
        (
            "from helao.core.servers.active_data_file import _relative_file_name\n",
            "from helao.helpers.file_utils import _relative_file_name\n",
            1,
        ),
    ],
)

# -- helao/core/tests/test_analysis_recovery.py --------------------------------
edit(
    "helao/core/tests/test_analysis_recovery.py",
    [
        (
            '''    # set difference against ``BaseAPI``'s own surface so the assertion stays
    # exact -- ``/list_executors`` and friends come from BaseAPI, not from here.
    from helao.core.servers.base_api import BaseAPI

    baseline = {
        getattr(route, "path", "")
        for route in BaseAPI(''',
            '''    # set difference against a bare ``ActionHost``'s own surface so the assertion
    # stays exact -- ``/list_executors`` and friends come from ActionHost, not
    # from here.
    from helao.hexagon.app.action_host import ActionHost

    baseline = {
        getattr(route, "path", "")
        for route in ActionHost(''',
            1,
        ),
    ],
)

# -- helao/core/tests/unit_test_dispatcher.py ----------------------------------
edit(
    "helao/core/tests/unit_test_dispatcher.py",
    [
        (
            "  ``ACTION_CTX``/``action_params`` are asserted to be populated server-side",
            "  the injected ``ctx``/``action_params`` are asserted to be populated server-side",
            1,
        ),
        ("from helao.core.servers.base_api import ACTION_CTX, wrap_action_endpoint\n", "", 1),
        (
            "from helao.helpers.premodels import Action\n",
            "from helao.helpers.premodels import Action\n"
            "from helao.hexagon.app.action_context import ActionContext\n"
            "from helao.hexagon.app.action_route import wrap_action_endpoint\n",
            1,
        ),
        (
            '''    * ``ACTION_CTX`` was populated with the REAL action (not a blank
      ``Action()``) and ``action.action_params`` reached the handler --
      the mechanism ``_build_action_from_kwargs`` implements.''',
            '''    * The injected ``ctx`` carries the REAL action (not a blank
      ``Action()``) and ``action.action_params`` reached the handler --
      the mechanism ``action_context.build_action`` implements.''',
            1,
        ),
        (
            '''    async def acquire_like(
        external_trigger: bool = True,
        duration: float = 10.0,
        timeout: float = 5000,
    ) -> dict:
        ctx = ACTION_CTX.get()
        captured["ctx_is_none"] = ctx is None''',
            '''    async def acquire_like(
        ctx: ActionContext,
        external_trigger: bool = True,
        duration: float = 10.0,
        timeout: float = 5000,
    ) -> dict:
        captured["ctx_is_none"] = ctx is None''',
            1,
        ),
        (
            '''    # Mirrors ActionAPIRoute.__init__: a tags=["action"] endpoint is wrapped
    # with wrap_action_endpoint before it is ever registered anywhere --
    # including into the RPC dispatcher's method table.
    wrapped = wrap_action_endpoint(acquire_like)''',
            '''    # Mirrors ActionRoute.__init__: a tags=["action"] endpoint is wrapped
    # with wrap_action_endpoint before it is ever registered anywhere --
    # including into the RPC dispatcher's method table. host=None: this check
    # is about the transport; host-derived fields are test_action_context's.
    wrapped = wrap_action_endpoint(acquire_like, None)''',
            1,
        ),
        (
            '            "ACTION_CTX was populated with the real Action, not left as None",',
            '            "the injected ctx carried the real Action, not None",',
            1,
        ),
    ],
)

# -- helao/core/tests/unit_test_base_live_buffer.py ----------------------------
edit(
    "helao/core/tests/unit_test_base_live_buffer.py",
    [
        (
            '''"""Unit tests for the ``LiveBuffer`` collaborator extracted from ``Base``
(CARDS P6, Stage S1): the live-buffer cluster (``live_buffer_task``/
``_stamp_lbuf_dict``/``put_lbuf``/``put_lbuf_nowait``/``get_lbuf``/
``get_realtime``/``get_realtime_nowait``).

``test_active_golden_master.py --check`` drives ``Base.get_realtime``/
``get_realtime_nowait`` (via ``Active``'s forwarders) but never exercises
``put_lbuf``/``get_lbuf``/``live_buffer_task`` -- those are normally
executor-driven (a driver's poller pushes readings into the live buffer).
This module is the S1-specific behavior-preservation gate for that surface.

Mirrors the ``Base.__new__`` bypass fixture used by
``test_active_golden_master.py``'s ``_make_base``: a bare ``Base`` built
without ``Base.__init__`` (no FastAPI app, no disk I/O, no NTP), populated
only with the attributes ``LiveBuffer`` methods touch, then
``_init_collaborators()`` is called so ``base.live_buffer_mgr`` exists exactly
as it would after the real ``__init__``.
''',
            '''"""Unit tests for ``ActionHost``'s live-buffer surface (``live_buffer_task``/
``_stamp_lbuf_dict``/``put_lbuf``/``put_lbuf_nowait``/``get_lbuf``/
``get_realtime``/``get_realtime_nowait``).

The action golden master drives ``get_realtime``/``get_realtime_nowait`` but
never ``put_lbuf``/``get_lbuf``/``live_buffer_task`` -- those are normally
executor-driven (a driver's poller pushes readings into the live buffer).
This module is the gate for that surface. Ported from the legacy ``Base``
fixture by B7b.

A bare ``ActionHost`` built with ``__new__`` (no FastAPI app, no disk I/O, no
NTP), populated only with the attributes these methods touch. The clock is
the production ``LegacyClockAdapter``: ``get_realtime_nowait`` reads its time
and offset through the clock port, not a cached ``ntp_offset``.
''',
            1,
        ),
        (
            '''import asyncio
import traceback

from helao.core.models.machine import MachineModel
from helao.core.servers.base import Base
from helao.core.tests._test_utils import TestReporter
from helao.helpers.multisubscriber_queue import MultisubscriberQueue
''',
            '''import asyncio
import traceback

from helao.core.models.machine import MachineModel
from helao.core.tests._test_utils import TestReporter
from helao.helpers.multisubscriber_queue import MultisubscriberQueue
from helao.hexagon.adapters.legacy.clock import LegacyClockAdapter
from helao.hexagon.app.action_host import ActionHost
from helao.hexagon.app.wiring import PortWiring
''',
            1,
        ),
        (
            '''def _make_base() -> Base:
    """Build a bare ``Base`` with every attribute ``LiveBuffer`` methods touch."""
    base = Base.__new__(Base)
    base.server = MachineModel(
        server_name=SERVER_NAME, machine_name=MACHINE, hostname="127.0.0.1", port=8000
    )
    base.ntp_offset = 0.0
    base.live_q = MultisubscriberQueue()
    base.live_buffer = {}
    base._init_collaborators()
    return base
''',
            '''def _make_base(offset_s: float = 0.0) -> ActionHost:
    """Build a bare ``ActionHost`` with every attribute the live-buffer methods touch."""
    base = ActionHost.__new__(ActionHost)
    base.server = MachineModel(
        server_name=SERVER_NAME, machine_name=MACHINE, hostname="127.0.0.1", port=8000
    )
    base.hexagon_wiring = PortWiring(clock=LegacyClockAdapter(offset_s))
    base.live_q = MultisubscriberQueue()
    base.live_buffer = {}
    return base
''',
            1,
        ),
        (
            '''    # offset=None defaults to base.ntp_offset
    base.ntp_offset = 3.0
    default_offset_ok = base.get_realtime_nowait(epoch_ns=1000) == 1000 + int(3.0 * 1e9)

    # no epoch_ns -> real wall-clock via Timer, should be a plausible epoch-ns value
    base.ntp_offset = 0.0
    now_ns = base.get_realtime_nowait()''',
            '''    # offset=None defaults to the clock port's offset
    offset_base = _make_base(3.0)
    default_offset_ok = offset_base.get_realtime_nowait(epoch_ns=1000) == 1000 + int(
        3.0 * 1e9
    )

    # no epoch_ns -> the clock port's wall clock, a plausible epoch-ns value
    now_ns = base.get_realtime_nowait()''',
            1,
        ),
        (
            '''        "epoch_ns passthrough, explicit offset, default-to-ntp_offset, and "
        "Timer-derived wall clock all compute the expected nanosecond value",''',
            '''        "epoch_ns passthrough, explicit offset, default-to-clock-offset, and "
        "clock-port wall clock all compute the expected nanosecond value",''',
            1,
        ),
    ],
)

# -- helao/core/tests/unit_test_estop_sync.py ----------------------------------
edit(
    "helao/core/tests/unit_test_estop_sync.py",
    [
        (
            "  1. Base.estop_actives finalizes only actions that were actually in-flight\n"
            "     (appending HloStatus.estopped and calling the active's finish path); an idle\n",
            "  1. ActionHost.estop_actives finalizes only actions that were actually in-flight\n"
            "     (appending HloStatus.estopped and calling the session's finish path); an idle\n",
            1,
        ),
        (
            "Hermetic: no AWS/API configured; no network. Base.estop_actives is exercised\n"
            "against a lightweight fake so no full server needs to be constructed.\n",
            "Hermetic: no AWS/API configured; no network. ActionHost.estop_actives is exercised\n"
            "against a lightweight fake so no full server needs to be constructed.\n"
            "Ported from legacy ``Base.estop_actives`` by B7b.\n",
            1,
        ),
        (
            "from helao.core.servers.base import Base\n"
            "from helao.core.tests._test_utils import TestReporter\n"
            "from helao.helpers.yml_tools import yml_dumps\n",
            "from helao.core.tests._test_utils import TestReporter\n"
            "from helao.helpers.yml_tools import yml_dumps\n"
            "from helao.hexagon.app.action_host import ActionHost\n",
            1,
        ),
        (
            "# ---- fakes for Base.estop_actives (avoids constructing a full server) --------",
            "# ---- fakes for ActionHost.estop_actives (avoids constructing a full server) --",
            1,
        ),
        # native estop_actives awaits session.finish(), not finish_all()
        ("    async def finish_all(self):\n", "    async def finish(self):\n", 1),
        (
            "    # --- 1. Base.estop_actives ------------------------------------------------\n"
            '    out["estop_actives_idle_empty"] = (await Base.estop_actives(_FakeBase({}))) == []\n',
            "    # --- 1. ActionHost.estop_actives ------------------------------------------\n"
            '    out["estop_actives_idle_empty"] = (\n'
            "        await ActionHost.estop_actives(_FakeBase({}))\n"
            "    ) == []\n",
            1,
        ),
        ("await Base.estop_actives(", "await ActionHost.estop_actives(", 2),
        (
            'reporter.section("Base.estop_actives finalizes only in-flight actions")',
            'reporter.section("ActionHost.estop_actives finalizes only in-flight actions")',
            1,
        ),
    ],
)

# -- helao/core/tests/unit_test_orch_lifecycle.py ------------------------------
edit(
    "helao/core/tests/unit_test_orch_lifecycle.py",
    [
        (
            '''"""Unit tests for the ``RunLifecycle`` collaborator extracted from ``Orch``
(CARDS P5, Stage S6): active-sequence/experiment close-out cluster.''',
            '''"""Unit tests for the ``RunLifecycle`` collaborator (CARDS P5, Stage S6):
active-sequence/experiment close-out cluster, driven through ``OrchHost``.''',
            1,
        ),
        (
            '''Mirrors the ``Orch.__new__`` bypass fixture used by
``test_orch_dispatch_golden_master.py``'s ``_make_orch`` (and the S3/S4/S5
sibling unit tests): a bare ``Orch`` built without ``Base.__init__`` (no
FastAPI app, no disk I/O, no NTP), populated only with the attributes
``RunLifecycle`` methods touch, then ``_init_collaborators()`` is called so
``orch.run_lifecycle`` exists exactly as it would after the real ``__init__``.''',
            '''Mirrors the ``OrchHost.__new__`` bypass fixture used by
``test_orch_dispatch_golden_master.py``'s ``_make_orch``: a bare ``OrchHost``
built without ``__init__`` (no FastAPI app, no disk I/O, no NTP), populated
only with the attributes ``RunLifecycle`` methods touch, then
``_init_orch_collaborators()`` is called so ``orch.run_lifecycle`` exists
exactly as it would after the real ``__init__``. (Ported from the legacy
``Orch`` fixture by B7b.)''',
            1,
        ),
        ("from helao.core.servers.orch import Orch\n", "", 1),
        (
            "from helao.helpers.premodels import Experiment, Sequence\n",
            "from helao.helpers.premodels import Experiment, Sequence\n"
            "from helao.hexagon.app.orch_host import OrchHost\n",
            1,
        ),
        (
            '''def _make_orch() -> Orch:
    """Build a bare ``Orch`` with every attribute ``RunLifecycle`` methods touch."""
    orch = Orch.__new__(Orch)''',
            '''def _make_orch() -> tuple[OrchHost, dict]:
    """Build a bare ``OrchHost`` with every attribute ``RunLifecycle`` methods touch."""
    orch = OrchHost.__new__(OrchHost)''',
            1,
        ),
        ("    orch._init_collaborators()\n", "    orch._init_orch_collaborators()\n", 1),
        (
            "        # Orch delegator -> RunLifecycle",
            "        # OrchHost delegator -> RunLifecycle",
            1,
        ),
    ],
)

# -- helao/core/tests/unit_test_orch_queues.py ---------------------------------
edit(
    "helao/core/tests/unit_test_orch_queues.py",
    [
        (
            '''"""Unit tests for the ``RunQueues`` collaborator extracted from ``Orch``
(CARDS P5, Stage S5): queue CRUD + uuid tracking cluster ("cluster A").''',
            '''"""Unit tests for the ``RunQueues`` collaborator (CARDS P5, Stage S5): queue
CRUD + uuid tracking cluster ("cluster A"), driven through ``OrchHost``.''',
            1,
        ),
        (
            '''Mirrors the ``Orch.__new__`` bypass fixture used by
``test_orch_dispatch_golden_master.py``'s ``_make_orch`` (and the S3/S4
sibling unit tests): a bare ``Orch`` built without ``Base.__init__`` (no
FastAPI app, no disk I/O, no NTP), populated only with the attributes
``RunQueues`` methods touch, then ``_init_collaborators()`` is called so
``orch.run_queues`` exists exactly as it would after the real ``__init__``.''',
            '''Mirrors the ``OrchHost.__new__`` bypass fixture used by
``test_orch_dispatch_golden_master.py``'s ``_make_orch``: a bare ``OrchHost``
built without ``__init__`` (no FastAPI app, no disk I/O, no NTP), populated
only with the attributes ``RunQueues`` methods touch, then
``_init_orch_collaborators()`` is called so ``orch.run_queues`` exists exactly
as it would after the real ``__init__``. (Ported from the legacy ``Orch``
fixture by B7b.)''',
            1,
        ),
        ("from helao.core.servers.orch import Orch\n", "", 1),
        (
            "from helao.helpers.zdeque import zdeque\n",
            "from helao.helpers.zdeque import zdeque\n"
            "from helao.hexagon.app.orch_host import OrchHost\n",
            1,
        ),
        (
            '''def _make_orch() -> Orch:
    """Build a bare ``Orch`` with every attribute ``RunQueues`` methods touch."""
    orch = Orch.__new__(Orch)''',
            '''def _make_orch() -> OrchHost:
    """Build a bare ``OrchHost`` with every attribute ``RunQueues`` methods touch."""
    orch = OrchHost.__new__(OrchHost)''',
            1,
        ),
        ("    orch._init_collaborators()\n", "    orch._init_orch_collaborators()\n", 1),
        ("def _mk_action(orch: Orch, ", "def _mk_action(orch: OrchHost, ", 1),
        # OrchHost has no append/replace/supplement delegators (legacy Orch
        # did); the subject is RunQueues, so the checks call it directly.
        ("    orch.append_action(", "    orch.run_queues.append_action(", 5),
        ("    orch.replace_action(", "    orch.run_queues.replace_action(", 1),
        ("    orch.supplement_error_action(", "    orch.run_queues.supplement_error_action(", 1),
        (
            '''def _check_base_collaborator_seam() -> bool:
    """Regression: Orch._init_collaborators must call super() so the Base
    collaborators (live_buffer_mgr, status_broadcaster; CARDS P6) exist on
    Orch instances -- otherwise every inherited status/live delegator raises
    AttributeError at Orch.myinit (found in P6-S2 review)."""
    orch = _make_orch()
    return all(
        hasattr(orch, a)
        for a in (
            "live_buffer_mgr",
            "status_broadcaster",
            "queue_persister",
            "status_ingester",
            "run_queues",
            "dispatch_runner",
        )
    )''',
            '''def _check_base_collaborator_seam() -> bool:
    """Regression: ``OrchHost._init_orch_collaborators`` must build every
    collaborator the host delegates to (and the finalize lock RunLifecycle and
    EstopController share) -- a missing one is an AttributeError on the first
    delegated call, not at construction."""
    orch = _make_orch()
    return all(
        hasattr(orch, a)
        for a in (
            "finalize_lock",
            "queue_persister",
            "server_monitor",
            "status_ingester",
            "run_queues",
            "run_lifecycle",
            "dispatch_runner",
            "estop_controller",
        )
    )''',
            1,
        ),
        (
            '''    reporter.section("Base collaborator seam")
    reporter.check(
        "Orch._init_collaborators calls super() -> Base live_buffer_mgr/status_broadcaster built on Orch",''',
            '''    reporter.section("OrchHost collaborator seam")
    reporter.check(
        "OrchHost._init_orch_collaborators builds all seven collaborators and the finalize lock",''',
            1,
        ),
    ],
)

# -- helao/hexagon/tests/test_executor_runner.py (fixture typing only) ---------
edit(
    "helao/hexagon/tests/test_executor_runner.py",
    [
        ("import asyncio\n\nimport pytest\n", "import asyncio\nfrom uuid import UUID\n\nimport pytest\n", 1),
        (
            "        self.action_task = None\n",
            "        self.action_task: asyncio.Task | None = None\n",
            1,
        ),
    ],
)
```

```
timeout 120 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t6_port_edits.py" "$WT"
```
Expected, exactly ten lines:
```
edited helao/core/tests/test_standalone_operator.py
edited helao/core/tests/test_orch_queue_paging.py
edited helao/core/tests/test_upload_set.py
edited helao/core/tests/test_analysis_recovery.py
edited helao/core/tests/unit_test_dispatcher.py
edited helao/core/tests/unit_test_base_live_buffer.py
edited helao/core/tests/unit_test_estop_sync.py
edited helao/core/tests/unit_test_orch_lifecycle.py
edited helao/core/tests/unit_test_orch_queues.py
edited helao/hexagon/tests/test_executor_runner.py
```
An `AssertionError: <file>: expected N of ...` means that file differs from `64f2cf15`. STOP and report it; do not adjust the count. (Files before the failing one have been written; the failing file and every later one have not.)

- [ ] **Step 6.3: Rewrite the two ports whose shape changes.** Replace the whole of `helao/core/tests/unit_test_base_status.py` with:

```python
"""Unit tests for ``ActionHost``'s status-broadcast surface
(``send_statuspackage``/``send_nbstatuspackage``/``attach_client``/
``detach_client``/``replace_status``).

The action golden master drives the non-blocking sender path but never the
remote-subscriber registry or ``replace_status`` directly -- those are
normally orchestrator-driven. This module is the gate for that surface.
Ported from the legacy ``Base``/``StatusBroadcaster`` fixture by B7b; the
legacy ``_ws_relay`` check went with the engine, because the native WS
encoding is pinned by ``harness/tests/test_ws_frames.py``.

A bare ``ActionHost`` built with ``__new__`` (no FastAPI app, no disk I/O, no
NTP), populated only with the attributes these methods touch.

Hermetic: the private dispatcher (network RPC) is monkeypatched in the
``action_host`` module namespace, which binds it at import, with a recording
fake; no disk I/O.
"""

__all__ = ["base_status_unit_test"]

import asyncio
import traceback

import helao.hexagon.app.action_host as action_host_module
from helao.core.error import ErrorCodes
from helao.core.models.hlostatus import HloStatus
from helao.core.models.machine import MachineModel
from helao.core.models.server import ActionServerModel
from helao.core.tests._test_utils import TestReporter
from helao.helpers.premodels import Action
from helao.hexagon.app.action_host import ActionHost

SERVER_NAME = "STATSRV"
MACHINE = "test-machine"


def _make_base() -> ActionHost:
    """Build a bare ``ActionHost`` with every attribute the status methods touch."""
    base = ActionHost.__new__(ActionHost)
    base.server = MachineModel(
        server_name=SERVER_NAME, machine_name=MACHINE, hostname="127.0.0.1", port=8000
    )
    base.server_cfg = {"host": "127.0.0.1", "port": 8000}
    base.actionservermodel = ActionServerModel(action_server=base.server)
    base.actionservermodel.init_endpoints()
    base.status_clients = set()
    return base


class _PatchDispatcher:
    """Swap ``action_host.async_private_dispatcher`` for *fake* inside the block."""

    def __init__(self, fake):
        self._fake = fake

    def __enter__(self):
        self._orig = action_host_module.async_private_dispatcher
        action_host_module.async_private_dispatcher = self._fake
        return self

    def __exit__(self, *exc):
        action_host_module.async_private_dispatcher = self._orig
        return False


# ---------------------------------------------------------------------------
# send_statuspackage / send_nbstatuspackage
# ---------------------------------------------------------------------------


async def _check_send_statuspackage() -> bool:
    calls: list = []

    async def _fake_dispatch(
        server_key, host, port, private_action, params_dict=None, json_dict=None, **kw
    ):
        calls.append(
            {
                "server_key": server_key,
                "host": host,
                "port": port,
                "private_action": private_action,
                "params_dict": params_dict,
                "json_dict": json_dict,
            }
        )
        return {"ok": True}, ErrorCodes.none

    with _PatchDispatcher(_fake_dispatch):
        base = _make_base()
        resp, ec = await base.send_statuspackage(
            "CLIENT", "10.0.0.1", 9100, action_name=None
        )

    call = calls[-1]
    return (
        resp == {"ok": True}
        and ec == ErrorCodes.none
        and call["server_key"] == "CLIENT"
        and call["host"] == "10.0.0.1"
        and call["port"] == 9100
        and call["private_action"] == "update_status"
        # action_name None -> regular_task true
        and call["params_dict"] == {"regular_task": "true"}
        and "actionservermodel" in call["json_dict"]
    )


async def _check_send_nbstatuspackage() -> bool:
    calls: list = []

    async def _fake_dispatch(
        server_key, host, port, private_action, params_dict=None, json_dict=None, **kw
    ):
        calls.append(
            {
                "private_action": private_action,
                "params_dict": params_dict,
                "json_dict": json_dict,
            }
        )
        return {"success": True}, ErrorCodes.none

    with _PatchDispatcher(_fake_dispatch):
        base = _make_base()
        actionmodel = Action(action_name="nbtest").get_act()
        resp, ec = await base.send_nbstatuspackage(
            "CLIENT", "10.0.0.1", 9100, actionmodel
        )

    call = calls[-1]
    return (
        resp == {"success": True}
        and ec == ErrorCodes.none
        and call["private_action"] == "update_nonblocking"
        # server host/port come from base.server_cfg
        and call["params_dict"] == {"server_host": "127.0.0.1", "server_port": 8000}
        and "actionmodel" in call["json_dict"]
    )


# ---------------------------------------------------------------------------
# attach_client / detach_client (status_clients mutation)
# ---------------------------------------------------------------------------


async def _check_attach_detach() -> bool:
    calls: list = []

    async def _fake_dispatch(*a, **kw):
        calls.append(kw)
        return {"ok": True}, ErrorCodes.none

    with _PatchDispatcher(_fake_dispatch):
        base = _make_base()
        combo = ("CLIENT", "10.0.0.1", 9100)

        empty_before = len(base.status_clients) == 0
        ok = await base.attach_client("CLIENT", "10.0.0.1", 9100)
        added = combo in base.status_clients and ok is True
        dispatched_initial = len(calls) >= 1  # initial snapshot pushed

        await base.detach_client("CLIENT", "10.0.0.1", 9100)
        removed = combo not in base.status_clients

        # detaching a non-subscriber is a harmless no-op
        await base.detach_client("NOSUCH", "0.0.0.0", 1)
        noop_ok = combo not in base.status_clients

    return empty_before and added and dispatched_initial and removed and noop_ok


# ---------------------------------------------------------------------------
# replace_status (guarded status-list mutation)
# ---------------------------------------------------------------------------


def _check_replace_status() -> bool:
    base = _make_base()
    # present -> swapped in place
    status_list = [HloStatus.active]
    base.replace_status(status_list, HloStatus.active, HloStatus.finished)
    swapped = status_list == [HloStatus.finished]

    # absent old_status -> appended
    status_list2 = [HloStatus.active]
    base.replace_status(status_list2, HloStatus.errored, HloStatus.estopped)
    appended = HloStatus.estopped in status_list2

    return swapped and appended


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------


async def _run_checks() -> dict:
    return {
        "send_statuspackage": await _check_send_statuspackage(),
        "send_nbstatuspackage": await _check_send_nbstatuspackage(),
        "attach_detach": await _check_attach_detach(),
        "replace_status": _check_replace_status(),
    }


def base_status_unit_test() -> bool:
    reporter = TestReporter("base_status")
    try:
        res = asyncio.run(_run_checks())
    except Exception as exc:  # noqa: BLE001
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        print(repr(exc), tb)
        return False

    reporter.section("send_statuspackage / send_nbstatuspackage")
    reporter.check(
        "send_statuspackage builds the actionservermodel json_dict and dispatches "
        "'update_status' with regular_task=true to the target client",
        lambda: res["send_statuspackage"],
    )
    reporter.check(
        "send_nbstatuspackage builds the actionmodel json_dict + server host/port "
        "params and dispatches 'update_nonblocking'",
        lambda: res["send_nbstatuspackage"],
    )

    reporter.section("attach_client / detach_client")
    reporter.check(
        "attach_client adds the combo key to status_clients and pushes an initial "
        "snapshot; detach_client removes it and no-ops on a missing key",
        lambda: res["attach_detach"],
    )

    reporter.section("replace_status")
    reporter.check(
        "replace_status swaps an existing status in place and appends a missing one",
        lambda: res["replace_status"],
    )

    return reporter.success()


if __name__ == "__main__":
    import sys

    sys.exit(0 if base_status_unit_test() else 1)
```

Replace the whole of `helao/core/tests/unit_test_config_seam.py` with:

```python
"""Verify the typed-config injection seam on ``ActionHost``/``HelaoFastAPI``/``HelaoBokehAPI``.

``ActionHost`` takes ``helao_cfg`` (the same seam ``HelaoFastAPI`` offers) so a
test can build a host without a launched config. The ports are passed as
stubs: ``build_wiring`` reads the global ``CONFIG`` by design, and this module
checks the config seam, not the wiring one. Ported from the legacy
``Base(app=stub)`` fixture by B7b.

Covers:
- Default path (global ``CONFIG``) and injected path (``helao_cfg=``) produce
  identical orch topology and ``run_type`` results, matching inline dict
  navigation.
- ``world_cfg`` remains the same dict object that was injected (deployment
  code contract; the dict is not replaced by a typed view).
- A config missing ``run_type`` fails ``HelaoConfig`` validation with a
  ``ValueError``. The native host does not re-validate; ``fast_launcher``
  validates through ``read_validated_config`` before any app is built, so the
  check sits on that seam.
- ``HelaoFastAPI``/``HelaoBokehAPI`` accept an injected ``helao_cfg`` and use
  it instead of ``config_loader.CONFIG``.
"""

__all__ = ["config_seam_unit_test"]

import os
import tempfile
from types import SimpleNamespace
from typing import Any

from helao.core.tests._test_utils import TestReporter
from helao.helpers import config_loader
from helao.helpers.config_loader import HelaoConfig, read_validated_config
from helao.helpers.server_api import HelaoBokehAPI, HelaoFastAPI
from helao.hexagon.app.action_host import ActionHost
from helao.hexagon.app.wiring import PortWiring

SERVER_KEY = "CPSIM"


def _repo_root() -> str:
    here = os.path.abspath(__file__)
    return os.path.abspath(os.path.join(here, "..", "..", "..", ".."))


def _demo0_path() -> str:
    return os.path.join(_repo_root(), "helao", "deploy", "test", "configs", "demo0.yml")


class _Stub:
    """A port that only answers ``meta_writer_for``; anything else is a test bug."""

    def meta_writer_for(self, base):
        return object()

    def __getattr__(self, name):
        raise AssertionError(f"port member {name!r} used unexpectedly")


def _stub() -> Any:
    # typed Any: one stub stands in for every port Protocol
    return _Stub()


def _wiring() -> PortWiring:
    return PortWiring(
        config=_stub(),
        logging=_stub(),
        clock=_stub(),
        transport=_stub(),
        state_persistence=_stub(),
        status=_stub(),
        health=_stub(),
        artifact_store=_stub(),
        data_sink=_stub(),
    )


def _host(helao_cfg=None) -> ActionHost:
    return ActionHost(
        server_key=SERVER_KEY,
        server_title=SERVER_KEY,
        description="config seam",
        version=1.0,
        wiring=_wiring(),
        helao_cfg=helao_cfg,
    )


def config_seam_unit_test() -> bool:
    reporter = TestReporter("config_seam")

    config_dict, _validated = read_validated_config(_demo0_path())
    config_dict["root"] = tempfile.mkdtemp(prefix="config_seam_")

    # Inline dict navigation, computed independently for comparison.
    orch_keys = [
        k
        for k, d in config_dict.get("servers", {}).items()
        if d["group"] == "orchestrator"
    ]
    orch_key = orch_keys[0]
    orch_host = config_dict["servers"][orch_key]["host"]
    orch_port = config_dict["servers"][orch_key]["port"]
    run_type = config_dict["run_type"].lower()

    saved_config = config_loader.CONFIG
    try:
        config_loader.CONFIG = config_dict
        h1 = _host()
        config_loader.CONFIG = None
        h2 = _host(helao_cfg=config_dict)
    finally:
        config_loader.CONFIG = saved_config

    reporter.check(
        "default and injected paths agree on orch_key",
        lambda: h1.orch_key == h2.orch_key == orch_key,
    )
    reporter.check(
        "default and injected paths agree on orch_host",
        lambda: h1.orch_host == h2.orch_host == orch_host,
    )
    reporter.check(
        "default and injected paths agree on orch_port",
        lambda: h1.orch_port == h2.orch_port == orch_port,
    )
    reporter.check(
        "default and injected paths agree on run_type",
        lambda: h1.run_type == h2.run_type == run_type,
    )
    reporter.check(
        "world_cfg is the same object as the injected helao_cfg",
        lambda: h2.world_cfg is config_dict,
    )

    # Negative: missing run_type must raise ValueError (ValidationError wrap).
    bad_config = dict(config_dict)
    bad_config.pop("run_type", None)

    def _missing_run_type_raises() -> bool:
        try:
            HelaoConfig.model_validate(bad_config)
        except ValueError:
            return True
        return False

    reporter.check("missing run_type raises ValueError", _missing_run_type_raises)

    # HelaoFastAPI / HelaoBokehAPI: injected helao_cfg used instead of
    # config_loader.CONFIG. Save/restore module-level CONFIG around the check.
    saved_config = config_loader.CONFIG
    try:
        config_loader.CONFIG = None

        doc_stub = SimpleNamespace(title=None)
        bokeh_app = HelaoBokehAPI("ORCH", doc=doc_stub, helao_cfg=config_dict)
        reporter.check(
            "HelaoBokehAPI uses injected helao_cfg over config_loader.CONFIG",
            lambda: bokeh_app.helao_cfg is config_dict,
        )

        fast_app = HelaoFastAPI("ORCH", helao_cfg=config_dict)
        reporter.check(
            "HelaoFastAPI uses injected helao_cfg over config_loader.CONFIG",
            lambda: fast_app.helao_cfg is config_dict,
        )
    finally:
        config_loader.CONFIG = saved_config

    return reporter.success()


if __name__ == "__main__":
    raise SystemExit(0 if config_seam_unit_test() else 1)
```

- [ ] **Step 6.4: Append the moved checks to their native twins.** Append each block verbatim to the end of the named file (the file ends with a newline; each block starts with two blank lines).

`helao/hexagon/tests/test_executor_runner.py` (Step 6.2 already added `from uuid import UUID` and typed `_Session.action_task`):

```python


# -- moved from helao/core/tests/unit_test_active_executor.py (B7b) ----------


class _DataRecorder(_Recorder):
    """A _Recorder whose exec, poll and post phases each return one data row,
    and which records whether the loop flag was up while ``_exec`` ran."""

    seen_running = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # a data row is keyed by file_conn_key, which DataModel types as a UUID
        self.active.action.file_conn_keys = [UUID(int=1)]

    async def _exec(self):
        await super()._exec()
        self.seen_running = self.active.action_loop_running
        return {"error": ErrorCodes.none, "data": {"t": 0}}

    async def _poll(self):
        result = await super()._poll()
        result["data"] = {"t": len(self.calls)}
        return result

    async def _post_exec(self):
        await super()._post_exec()
        return {"error": ErrorCodes.none, "data": {"t": -1}}


class _LoopHost(_Host):
    def __init__(self):
        super().__init__()
        self.aloop = asyncio.get_running_loop()


class _CallbackSession(_Session):
    """A _Session on a host with a running loop, recording done-callbacks."""

    def __init__(self):
        super().__init__()
        self.base = _LoopHost()
        self.fired: list = []

    def executor_done_callback(self, futr):
        self.fired.append(futr)


@pytest.mark.asyncio
async def test_start_executor_schedules_the_loop_and_its_done_callback_fires():
    """start_executor only schedules the loop; the task then holds the loop flag
    while it works, enqueues one row per phase, and fires the done-callback."""
    s = _CallbackSession()
    ex = _DataRecorder(active=s, oneoff=False, poll_rate=0.001, polls=3)

    returned = s.runner.start_executor(ex)
    assert returned == {"action_uuid": "uuid-1"}
    assert ex.calls == [], "start_executor ran the loop inline"

    task = s.action_task
    assert task is not None
    await task
    await asyncio.sleep(0)
    assert ex.seen_running is True
    assert s.action_loop_running is False
    assert s.manual_stop is False
    assert len(s.enqueued) == 5  # exec + 3 polls + post
    assert s.fired == [task]


@pytest.mark.asyncio
async def test_a_oneoff_executor_runs_exec_and_post_with_no_poll_loop():
    s = _Session()
    ex = _DataRecorder(active=s, oneoff=True, poll_rate=0.001)
    returned = await s.runner.oneoff_executor(ex)
    assert returned is s.action
    assert ex.calls == ["pre", "exec", "post"]
    assert ex.seen_running is True
    assert s.action_loop_running is False
    assert len(s.enqueued) == 2  # exec + post
```

`helao/hexagon/tests/test_endpoint_manager.py`:

```python


# -- moved from helao/core/tests/unit_test_base_endpoints.py (B7b) -----------


@pytest.mark.asyncio
async def test_init_endpoint_status_awaits_the_dyn_endpoints_callback() -> None:
    """Late routes register before the endpoint scan, or they are never monitored."""
    host = _host()
    calls = []

    async def _dyn(app):
        calls.append(app)

    await host.init_endpoint_status(dyn_endpoints=_dyn)
    assert calls == [host]


@pytest.mark.asyncio
async def test_dyn_endpoints_init_schedules_the_endpoint_scan() -> None:
    """The startup hook only schedules the scan; it must still run to completion."""
    host = _host()

    @host.action()
    async def acquire_data(ctx: ActionContext):
        return None

    assert host.endpoint_queues == {}
    host.dyn_endpoints_init()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert "acquire_data" in host.endpoint_queues


@pytest.mark.asyncio
async def test_a_queued_endpoint_action_is_redispatched_no_wait_and_drained(
    monkeypatch,
) -> None:
    """no_wait stops the redispatch queueing behind itself; queued_launch lets the
    middleware pass it through instead of queueing it a second time."""
    from helao.core.models.action import ActionModel
    from helao.core.models.action_start_condition import ActionStartCondition
    from helao.helpers.zdeque import zdeque
    from helao.hexagon.app import endpoint_manager

    host = _host()
    calls = []

    async def _fake_dispatch(world_cfg, qact, qpars):
        calls.append((world_cfg, qact, qpars))
        return {"ok": True}, None

    monkeypatch.setattr(endpoint_manager, "async_action_dispatcher", _fake_dispatch)
    host.endpoint_queues["acquire_data"] = zdeque([(_QueuedAct(), {"p": 1})])
    await host.process_endpoint_queue(ActionModel(action_name="acquire_data"))
    assert len(calls) == 1
    world_cfg, qact, qpars = calls[0]
    assert world_cfg is host.world_cfg
    assert qact.action_name == "acquire_data"
    assert qact.start_condition == ActionStartCondition.no_wait
    assert qact.action_params.get("queued_launch") is True
    assert qpars == {"p": 1}
    assert len(host.endpoint_queues["acquire_data"]) == 0


@pytest.mark.asyncio
async def test_the_unified_queue_is_redispatched_and_drained(monkeypatch) -> None:
    from helao.helpers.zdeque import zdeque
    from helao.hexagon.app import endpoint_manager

    host = _host()
    calls = []

    async def _fake_dispatch(world_cfg, qact, qpars):
        calls.append(qact.action_name)
        return {"ok": True}, None

    monkeypatch.setattr(endpoint_manager, "async_action_dispatcher", _fake_dispatch)
    host.local_action_queue = zdeque([(_QueuedAct(), {})])
    await host.process_unified_queue()
    assert calls == ["acquire_data"]
    assert len(host.local_action_queue) == 0
```

`helao/hexagon/tests/test_action_route.py`:

```python


# -- moved from helao/core/tests/unit_test_base_api.py (B7b) -----------------


def test_a_sync_handler_is_wrapped_synchronously_and_gets_its_context() -> None:
    """The wrapper keeps a sync endpoint sync; awaiting its result would 500."""
    seen = {}

    def handler(ctx: ActionContext, payload: str = "p"):
        seen["ctx"] = ctx
        return payload

    wrapped = wrap_action_endpoint(handler, _host())
    assert not inspect.iscoroutinefunction(wrapped)
    assert wrapped(payload="hello", action_version=1) == "hello"
    assert seen["ctx"].action.action_params["payload"] == "hello"


def test_the_envelope_keys_are_split_from_action_params() -> None:
    """The queuing middleware rebuilds a queued action from query params; a key
    missing here lands in action_params instead of on the Action."""
    from helao.hexagon.app.action_host import ACTION_PARAM_KEYS

    for key in (
        "start_condition",
        "from_global_act_params",
        "to_global_params",
        "manual_action",
        "process_finish",
        "save_act",
        "save_data",
        "campaign_uuid",
    ):
        assert key in ACTION_PARAM_KEYS, key
```

`helao/hexagon/tests/test_action_context.py`:

```python


# -- moved from helao/core/tests/unit_test_base_api.py (B7b) -----------------


def test_active_params_round_trips_its_file_conn_params() -> None:
    from helao.core.models.file import FileConnParams
    from helao.core.models.machine import MachineModel
    from helao.helpers.active_params import ActiveParams
    from helao.helpers.premodels import Action as PremodelAction

    action = PremodelAction(
        action_name="do_stuff", action_server=MachineModel(server_name="S")
    )
    action.init_act()
    key = action.action_uuid
    assert key is not None, "init_act did not mint an action_uuid"
    ap = ActiveParams(
        action=action,
        file_conn_params_dict={
            key: FileConnParams(file_conn_key=key, json_data_keys=["t_s", "v"])
        },
    )
    assert ap.action is action
    (entry,) = ap.as_dict()["file_conn_params_dict"].values()
    assert entry["json_data_keys"] == ["t_s", "v"]


def test_a_loose_kwarg_absent_from_the_envelope_is_merged_into_it() -> None:
    """The envelope wins a conflict, but must not swallow a new parameter."""
    envelope = Action(action_name="x")
    envelope.action_params["duration"] = 9.0
    got = build_action({"action": envelope, "rate": 0.5}, {}, None)
    assert got is envelope
    assert got.action_params == {"duration": 9.0, "rate": 0.5}
```

- [ ] **Step 6.5: Delete the three move-and-delete files.**

```
rm "$WT/helao/core/tests/unit_test_active_executor.py" "$WT/helao/core/tests/unit_test_base_api.py" "$WT/helao/core/tests/unit_test_base_endpoints.py"
/usr/bin/grep -rn 'unit_test_active_executor\|unit_test_base_api\|unit_test_base_endpoints' "$WT" --include='*.py' | /usr/bin/grep -v '/\.claude/'
```
Expected: exactly the three `run_unit_tests.py` import lines (23, 28, 29), the four `# -- moved from helao/core/tests/unit_test_...` comment lines Step 6.4 added (`test_action_context.py`, `test_executor_runner.py`, `test_action_route.py`, `test_endpoint_manager.py`), and `helao/core/tests/unit_test_active_finalizer.py:26` (a docstring) unless Task 5 has already deleted that file. Nothing else. `run_unit_tests.py` is Task 7's.

- [ ] **Step 6.6: Every touched file passes.**

```
for f in helao/core/tests/test_orch_queue_paging.py helao/core/tests/test_standalone_operator.py helao/core/tests/test_analysis_recovery.py helao/core/tests/test_upload_set.py helao/hexagon/tests/test_executor_runner.py helao/hexagon/tests/test_endpoint_manager.py helao/hexagon/tests/test_action_route.py helao/hexagon/tests/test_action_context.py; do printf '%s: ' "$f"; timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -m pytest -q -p no:cacheprovider --color=no "$f" 2>&1 | tail -1; done | tee "$X/t6_counts_after.txt"
timeout 900 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t6_run_unit.py" base_live_buffer base_status config_seam dispatcher estop_sync orch_lifecycle orch_queues > "$X/t6_unit_after.log" 2>&1; echo rc=$?
grep -E '^UNIT' "$X/t6_unit_after.log"
for s in base_live_buffer base_status config_seam dispatcher estop_sync orch_lifecycle orch_queues; do printf '%s ' "$s"; grep -cE "^$s test [0-9]+ passed" "$X/t6_unit_after.log"; done
```
Expected pass counts (measured in the planning dry run):
```
helao/core/tests/test_orch_queue_paging.py: 13 passed
helao/core/tests/test_standalone_operator.py: 59 passed
helao/core/tests/test_analysis_recovery.py: 51 passed
helao/core/tests/test_upload_set.py: 11 passed
helao/hexagon/tests/test_executor_runner.py: 8 passed
helao/hexagon/tests/test_endpoint_manager.py: 10 passed
helao/hexagon/tests/test_action_route.py: 12 passed
helao/hexagon/tests/test_action_context.py: 16 passed
```
`test_standalone_operator` is one fewer (the deleted `test_prepend_sequences_helper`); the four twins gain 2 + 4 + 2 + 2. Then `rc=0`, seven `UNIT ...: PASS` lines, `UNIT-SUMMARY 7 passed, 0 failed`, and check counts `base_live_buffer 5`, `base_status 4`, `config_seam 8`, `dispatcher 26`, `estop_sync 11`, `orch_lifecycle 5`, `orch_queues 7` (base_status loses `_ws_relay`, config_seam loses `typed_server_cfg`; both per the mapping above). The `orch_lifecycle` log contains two `pre-finish hook 'boom' failed` ERROR/ALERT lines; those are the check's deliberate failing hook, and they appear on `64f2cf15` too.

- [ ] **Step 6.7: (moved)** The mutate-and-observe probes for this task's moved checks run in Task 7 Step 7.0b, alone, after every wave-1 task has finished.

- [ ] **Step 6.8: No touched file imports the engine.**

```
/usr/bin/grep -n 'helao\.core\.servers\|from helao.core import servers' "$WT/helao/core/tests/test_orch_queue_paging.py" "$WT/helao/core/tests/test_standalone_operator.py" "$WT/helao/core/tests/test_analysis_recovery.py" "$WT/helao/core/tests/test_upload_set.py" "$WT/helao/core/tests/unit_test_base_live_buffer.py" "$WT/helao/core/tests/unit_test_base_status.py" "$WT/helao/core/tests/unit_test_config_seam.py" "$WT/helao/core/tests/unit_test_dispatcher.py" "$WT/helao/core/tests/unit_test_estop_sync.py" "$WT/helao/core/tests/unit_test_orch_lifecycle.py" "$WT/helao/core/tests/unit_test_orch_queues.py" "$WT/helao/hexagon/tests/test_executor_runner.py" "$WT/helao/hexagon/tests/test_endpoint_manager.py" "$WT/helao/hexagon/tests/test_action_route.py" "$WT/helao/hexagon/tests/test_action_context.py"; echo grep-rc=$?
```
Expected: no lines, `grep-rc=1`. (Measured in the dry run as well: with `helao/core/servers` moved out of a scratch copy after these edits, all eight pytest files and all seven unit functions still pass with the same counts. That run is not repeated here because the worktree keeps the engine until commit 3.)

- [ ] **Step 6.9: pyright, no new errors per file.** Create `$X/t6_pyright_files.txt` with exactly these 16 lines:

```
helao/core/tests/test_orch_queue_paging.py
helao/core/tests/test_standalone_operator.py
helao/core/tests/test_analysis_recovery.py
helao/core/tests/test_upload_set.py
helao/hexagon/tests/test_executor_runner.py
helao/hexagon/tests/test_endpoint_manager.py
helao/hexagon/tests/test_action_route.py
helao/hexagon/tests/test_action_context.py
helao/core/tests/unit_test_base_live_buffer.py
helao/core/tests/unit_test_base_status.py
helao/core/tests/unit_test_config_seam.py
helao/core/tests/unit_test_dispatcher.py
helao/core/tests/unit_test_estop_sync.py
helao/core/tests/unit_test_orch_lifecycle.py
helao/core/tests/unit_test_orch_queues.py
run_unit_tests.py
```

```
cd "$WT" && xargs -a "$X/t6_pyright_files.txt" timeout 600 pyright --outputjson > "$X/t6_pyright_after.json" 2>/dev/null; echo rc=$?
timeout 60 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -c "import collections, json; d = json.load(open('$X/t6_pyright_after.json')); c = collections.Counter(x['file'].split('/helao-b7b/', 1)[1] for x in d['generalDiagnostics'] if x['severity'] == 'error'); print(d['summary']['filesAnalyzed'], d['summary']['errorCount']); [print(k, v) for k, v in sorted(c.items())]"
```
Expected: `rc=123` (xargs reports pyright's non-zero exit as 123), then `16 91` and exactly:
```
helao/core/tests/test_standalone_operator.py 54
helao/core/tests/unit_test_base_status.py 1
helao/core/tests/unit_test_estop_sync.py 4
helao/core/tests/unit_test_orch_lifecycle.py 9
helao/core/tests/unit_test_orch_queues.py 3
helao/hexagon/tests/test_action_context.py 1
helao/hexagon/tests/test_action_route.py 11
helao/hexagon/tests/test_endpoint_manager.py 8
```
Measured on `64f2cf15` over the same 16 paths: `16 106`, per file `test_standalone_operator 55`, `unit_test_base_status 2`, `unit_test_config_seam 5`, `unit_test_estop_sync 4`, `unit_test_orch_lifecycle 13`, `unit_test_orch_queues 7`, `test_action_context 1`, `test_action_route 11`, `test_endpoint_manager 8`. No file goes up. If `filesAnalyzed` is not 16, the pass is vacuous: STOP. (`run_unit_tests.py` is in the list because Task 7 edits it; it has 0 errors before and after.)

- [ ] **Step 6.10: black-stable.** The controller runs black before committing; this confirms it will change nothing.

```
cd "$WT" && xargs -a "$X/t6_pyright_files.txt" black --check 2>&1 | tail -1
```
Expected: `16 files would be left unchanged.`

**For Task 7 (not applied here):** Step 6.5's deletions orphan exactly these six lines of `run_unit_tests.py` on `64f2cf15`, which Task 7 removes:
```
from helao.core.tests.unit_test_active_executor import active_executor_unit_test
from helao.core.tests.unit_test_base_api import base_api_unit_test
from helao.core.tests.unit_test_base_endpoints import base_endpoints_unit_test
    ("base_api", base_api_unit_test),
    ("active_executor", active_executor_unit_test),
    ("base_endpoints", base_endpoints_unit_test),
```
(lines 23, 28, 29, 73, 97, 99). Measured in the dry run: with those six removed, `run_unit_tests.py` runs 34 functions and exits 0. With Task 5's four files removed too, it runs **30**, as spec §5.2 says. `run_unit_tests.py` must run with the current directory at `$WT`: from a directory that is not a git checkout, `action_experiment_sequence`, `artifact_generation` and `extra_models` FAIL (the same `hlo_version` trap spec §2.4 records for the action golden master).

**Files for the controller's commit:**
- modified: `helao/core/tests/test_standalone_operator.py`, `helao/core/tests/test_orch_queue_paging.py`, `helao/core/tests/test_upload_set.py`, `helao/core/tests/test_analysis_recovery.py`, `helao/core/tests/unit_test_dispatcher.py`, `helao/core/tests/unit_test_base_live_buffer.py`, `helao/core/tests/unit_test_base_status.py`, `helao/core/tests/unit_test_config_seam.py`, `helao/core/tests/unit_test_estop_sync.py`, `helao/core/tests/unit_test_orch_lifecycle.py`, `helao/core/tests/unit_test_orch_queues.py`, `helao/hexagon/tests/test_executor_runner.py`, `helao/hexagon/tests/test_endpoint_manager.py`, `helao/hexagon/tests/test_action_route.py`, `helao/hexagon/tests/test_action_context.py`
- deleted: `helao/core/tests/unit_test_active_executor.py`, `helao/core/tests/unit_test_base_api.py`, `helao/core/tests/unit_test_base_endpoints.py`

---

### Task 7: Commit 1 closes — `run_unit_tests.py`, the commit-1 check, the controller commit

**Files:**
- Modify: `run_unit_tests.py` — delete 14 lines on `64f2cf15`: 21, 22, 23, 24, 28, 29, 31 (imports) and 73, 94, 95, 96, 97, 98, 99 (`TESTS` entries).
- Scratch: `$X/t7_rut_edit.py`, `$X/rut_c1.txt`, `$X/unit_c1.txt`, `$X/run_tests_c1.txt`, `$X/F1.txt`, `$X/t7_refs.txt`.

**Interfaces:**
- Consumes: Tasks 1–6 complete (their "Files for the controller's commit" lists); Task 0's `t0_unit_sweep.sh`, `t0_failset.sh`, `t13_engine_refs.py`, `F0.txt`, `unit_before.txt`; Task 6's `$X/t6_run_unit.py`.
- Produces: commit 1 on `feat/b7b-delete-engine`. `run_unit_tests.py` imports 30 functions.

**Execution:** runs alone, after Tasks 1–6 have all finished (wave 1b: the controller dispatches it only when all six have reported done, so nothing else is running). Steps 7.0a–7.8 are an implementer's; Step 7.9 is the controller's.

- [ ] **Step 7.0a: Mutate and observe Task 5's moved checks (moved here from Step 5.9).** A moved test that cannot go red has lost the unit check it replaces. Create `$X/t7_probes_task5.json` with exactly this content:
```json
[
  {"file": "helao/hexagon/adapters/native/finalizer.py",
   "old": "        await self.active.finish(finish_uuid_list=None)\n", "new": "        return None\n",
   "test": "helao/hexagon/tests/test_native_finalizer.py::test_split_keep_active_then_finish_all_finishes_the_chain",
   "expect": "1 failed"},
  {"file": "helao/hexagon/adapters/native/meta_writer.py",
   "old": "        if action.save_act:\n", "new": "        if True:\n",
   "test": "helao/hexagon/tests/test_native_meta_writer.py::test_write_act_save_act_false_writes_nothing",
   "expect": "1 failed"},
  {"file": "helao/hexagon/adapters/native/data_stream.py",
   "old": "        self.active.listen_uuids.append(new_uuid)\n", "new": "        pass\n",
   "test": "helao/hexagon/tests/test_native_data_stream.py::test_add_new_listen_uuid_mutates_the_session",
   "expect": "1 failed"},
  {"file": "helao/hexagon/tests/native_fixtures.py",
   "old": "    base.aloop = asyncio.get_running_loop()  # type: ignore[reportAttributeAccessIssue]\n", "new": "",
   "test": "helao/core/tests/test_run_state_wiring.py::test_a_manual_action_is_evicted_from_the_journal_when_it_finishes",
   "expect": "1 failed"}
]
```
**[background]** Launch (a `run_in_background: true` call):
```
"$X/bg.sh" t7_mutate_task5 timeout 1500 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t0_mutate.py" "$X/t7_probes_task5.json"
```
Then, **[tool timeout 600 s]**:
```
"$X/wait.sh" t7_mutate_task5
cat "$X/t7_mutate_task5.txt"
```
Expected: `rc=0`, then four lines `RED rc=1 <test> :: expect found :: RESTORED <file>` in the order above, and `MUTATE-PASS`. The fourth probe also pins Task 5's `aloop` finding: without a loop on the host the journal eviction silently never runs. Any `NOT-RED` means a moved test intercepts nothing; any `NOT-RESTORED` means a file differs from its pre-probe bytes: STOP either way.

- [ ] **Step 7.0b: Mutate and observe Task 6's moved checks (moved here from Step 6.7).** Create `$X/t7_probes_task6.json` with exactly this content:
```json
[
  {"file": "helao/hexagon/app/endpoint_manager.py",
   "old": "            qact.action_params[\"queued_launch\"] = True", "new": "            pass",
   "test": "helao/hexagon/tests/test_endpoint_manager.py",
   "expect": "FAILED helao/hexagon/tests/test_endpoint_manager.py::test_a_queued_endpoint_action_is_redispatched_no_wait_and_drained"},
  {"file": "helao/hexagon/app/executor_runner.py",
   "old": "        if not executor.oneoff:", "new": "        if True:",
   "test": "helao/hexagon/tests/test_executor_runner.py",
   "expect": "FAILED helao/hexagon/tests/test_executor_runner.py::test_a_oneoff_executor_runs_exec_and_post_with_no_poll_loop"},
  {"file": "helao/hexagon/app/action_host.py",
   "old": "    \"save_act\",\n    \"save_data\",\n", "new": "    \"save_act\",\n",
   "test": "helao/hexagon/tests/test_action_route.py",
   "expect": "FAILED helao/hexagon/tests/test_action_route.py::test_the_envelope_keys_are_split_from_action_params"}
]
```
**[background]** Launch:
```
"$X/bg.sh" t7_mutate_task6 timeout 1200 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t0_mutate.py" "$X/t7_probes_task6.json"
```
Then, **[tool timeout 600 s]**:
```
"$X/wait.sh" t7_mutate_task6
cat "$X/t7_mutate_task6.txt"
git -C "$WT" diff --stat -- helao/hexagon/app/endpoint_manager.py helao/hexagon/app/executor_runner.py
git -C "$WT" diff -- helao/hexagon/app/action_host.py | grep -c '^[-+] '
```
Expected: `rc=0`; three `RED … :: expect found :: RESTORED …` lines and `MUTATE-PASS`; no `diff --stat` output (those two files are untouched by commit 1); `2` (the only change left in `action_host.py` is Task 1 Step 1.5's one-line annotation: one `-` and one `+` line). The sha256 check inside the helper is the restore proof; the last two commands confirm that nothing else changed.

- [ ] **Step 7.1: Remove the seven deleted scripts from `run_unit_tests.py`.** Create `$X/t7_rut_edit.py`:

```python
"""B7b Task 7: drop the 14 run_unit_tests.py lines whose unit_test_* files Tasks 5 and 6 deleted.

Usage: python t7_rut_edit.py <path to run_unit_tests.py>
Each line must occur exactly once, or nothing is written.
"""

import sys

GONE = [
    "from helao.core.tests.unit_test_active_data_file import active_data_file_unit_test\n",
    "from helao.core.tests.unit_test_active_data_stream import active_data_stream_unit_test\n",
    "from helao.core.tests.unit_test_active_executor import active_executor_unit_test\n",
    "from helao.core.tests.unit_test_active_finalizer import active_finalizer_unit_test\n",
    "from helao.core.tests.unit_test_base_api import base_api_unit_test\n",
    "from helao.core.tests.unit_test_base_endpoints import base_endpoints_unit_test\n",
    "from helao.core.tests.unit_test_base_meta_writer import base_meta_writer_unit_test\n",
    '    ("base_api", base_api_unit_test),\n',
    '    ("base_meta_writer", base_meta_writer_unit_test),\n',
    '    ("active_data_file", active_data_file_unit_test),\n',
    '    ("active_data_stream", active_data_stream_unit_test),\n',
    '    ("active_executor", active_executor_unit_test),\n',
    '    ("active_finalizer", active_finalizer_unit_test),\n',
    '    ("base_endpoints", base_endpoints_unit_test),\n',
]
path = sys.argv[1]
lines = open(path, encoding="utf-8").readlines()
for g in GONE:
    n = lines.count(g)
    assert n == 1, f"{n} x {g!r}"
kept = [line for line in lines if line not in GONE]
open(path, "w", encoding="utf-8").writelines(kept)
print(f"removed {len(lines) - len(kept)} lines")
```

```
timeout 60 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t7_rut_edit.py" "$WT/run_unit_tests.py"
grep -c 'unit_test_active_\|unit_test_base_api\|unit_test_base_endpoints\|unit_test_base_meta_writer' "$WT/run_unit_tests.py"
```
Expected: `removed 14 lines`, then `0`.

- [ ] **Step 7.2: `run_unit_tests.py` passes with 30 functions.**
```
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python run_unit_tests.py > "$X/rut_c1.txt" 2>&1; echo rc=$?
grep -c '^  [a-z_]*: PASS$' "$X/rut_c1.txt"; tail -1 "$X/rut_c1.txt"
```
Expected: `rc=0`, `30`, `overall: PASS`. (Run from `$WT`: from a directory that is not a git checkout, three unrelated functions fail on the `hlo_version` trap.)

- [ ] **Step 7.3: The standalone scripts: same result as Task 0, less the seven deleted files.**
**[background]** Launch:
```
"$X/bg.sh" unit_c1_job "$X/t0_unit_sweep.sh" "$X/unit_c1.txt"
```
Then, **[tool timeout 600 s]**:
```
"$X/wait.sh" unit_c1_job
grep -v -E 'unit_test_(active_data_file|active_data_stream|active_executor|active_finalizer|base_api|base_endpoints|base_meta_writer)\.py$' "$X/unit_before.txt" | diff - "$X/unit_c1.txt" && echo UNIT-SCRIPTS-UNCHANGED
timeout 900 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t6_run_unit.py" base_live_buffer base_status config_seam dispatcher estop_sync orch_lifecycle orch_queues 2>/dev/null | tail -1
```
Expected: `rc=0`; `UNIT-SCRIPTS-UNCHANGED`; `UNIT-SUMMARY 7 passed, 0 failed`. (The script sweep alone is not evidence for `unit_test_dispatcher.py`, which has no `__main__` and exits 0 without running anything; the function runner is.)

- [ ] **Step 7.4: Both golden masters, both modes.**
```
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python helao/core/tests/test_orch_dispatch_golden_master.py --check 2>/dev/null | tail -1
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python helao/core/tests/test_orch_dispatch_golden_master.py 2>/dev/null | tail -1
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python helao/core/tests/test_active_golden_master.py --check 2>/dev/null | tail -1
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python helao/core/tests/test_active_golden_master.py 2>/dev/null | tail -1
/bin/ls "$X/t2_red_legacy.txt" "$X/t2_red_native.txt" "$X/t2_native_vs_legacy.txt" "$X/t4_compare.log"
grep -c 'COMPARE PASS' "$X/t2_native_vs_legacy.txt"
```
Expected: `CHECK PASSED: all 9 scenarios byte-identical to $WT/helao/core/tests/golden/dispatch` (printed as the absolute path); `ALL GOLDEN-MASTER HARNESS CHECKS PASSED`; `CHECK PASSED: all 13 scenarios match $WT/helao/core/tests/golden/action` (printed as the absolute path); `DETERMINISM SELF-TEST PASSED: 13 scenarios byte/multiset-stable 2x`; the four evidence files listed; `1`. The red-check record (`t2_red_legacy.txt`, "13 of 13 scenarios red") was produced before the native run passed, as §4.1 step 5 requires.

- [ ] **Step 7.5: Only the files commit 2 or commit 3 removes still reference the engine.**
```
timeout 300 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t13_engine_refs.py" > "$X/t7_refs.txt"; echo rc=$?
grep -E '^(EXECUTABLE|MENTION-OUTSIDE-ALLOWED)' "$X/t7_refs.txt" | awk '{print $2}' | cut -d: -f1 | sort -u | grep -v '^helao/core/servers/'
```
Expected: `rc=1`, then (the engine's own modules, which import each other, are filtered out) only paths from this list (commit 2 deletes or trims the first five, commit 3 the rest):
```
harness/ws_frames.py
helao/core/tests/test_bokeh_theme.py
helao/core/tests/test_palette.py
helao/hexagon/app/active_graft.py
helao/hexagon/app/factory.py
helao/hexagon/tests/test_action_host_member_coverage.py
helao/hexagon/tests/test_action_session_port.py
helao/hexagon/tests/test_active_graft.py
helao/hexagon/tests/test_estop_finish_race.py
helao/hexagon/tests/test_factory.py
helao/hexagon/tests/test_native_artifact_store.py
helao/hexagon/tests/test_native_data_file.py
helao/hexagon/tests/test_native_data_sink.py
helao/hexagon/tests/test_native_data_stream.py
helao/hexagon/tests/test_native_finalizer.py
helao/hexagon/tests/test_native_meta_writer.py
helao/hexagon/tests/test_orch_host_member_coverage.py
helao/hexagon/tests/test_orch_host_surface.py
helao/hexagon/tests/test_ws_consumer_parity.py
```
Any other path means a commit-1 task left an engine reference: STOP and report it.

- [ ] **Step 7.6: Guard, and the full sweep against F0 (~8 minutes).**
```
timeout 120 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -c "import helao; print(helao.__file__)"
```
**[background]** Launch:
```
"$X/bg.sh" run_tests_c1 timeout 5400 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python run_tests.py
```
Then, **[tool timeout 600 s]**, repeating while it prints `STILL-RUNNING`:
```
"$X/wait.sh" run_tests_c1
tail -8 "$X/run_tests_c1.txt"
"$X/t0_failset.sh" "$X/run_tests_c1.txt" "$X/F1.txt" > /dev/null
comm -13 "$X/F0.txt" "$X/F1.txt"; echo new-failures-listed-above
```
Expected: the worktree path; `rc=1` (F0 is not empty); the summary; then nothing before `new-failures-listed-above`. A file that fails now and did not fail in F0 blocks the commit, even if no task touched it.

- [ ] **Step 7.7: The tree holds commit 1 and nothing else.**
```
git -C "$WT" status --short | LC_ALL=C sort
```
Expected, exactly (byte order):
```
 D helao/core/tests/unit_test_active_data_file.py
 D helao/core/tests/unit_test_active_data_stream.py
 D helao/core/tests/unit_test_active_executor.py
 D helao/core/tests/unit_test_active_finalizer.py
 D helao/core/tests/unit_test_base_api.py
 D helao/core/tests/unit_test_base_endpoints.py
 D helao/core/tests/unit_test_base_meta_writer.py
 M harness/openapi_capture.py
 M helao/core/tests/test_active_golden_master.py
 M helao/core/tests/test_analysis_recovery.py
 M helao/core/tests/test_orch_dispatch_golden_master.py
 M helao/core/tests/test_orch_queue_paging.py
 M helao/core/tests/test_run_state_wiring.py
 M helao/core/tests/test_standalone_operator.py
 M helao/core/tests/test_upload_set.py
 M helao/core/tests/unit_test_base_live_buffer.py
 M helao/core/tests/unit_test_base_status.py
 M helao/core/tests/unit_test_config_seam.py
 M helao/core/tests/unit_test_dispatcher.py
 M helao/core/tests/unit_test_estop_sync.py
 M helao/core/tests/unit_test_orch_lifecycle.py
 M helao/core/tests/unit_test_orch_queues.py
 M helao/hexagon/app/action_host.py
 M helao/hexagon/tests/checklists/orch_openapi_legacy.json
 M helao/hexagon/tests/native_fixtures.py
 M helao/hexagon/tests/test_action_context.py
 M helao/hexagon/tests/test_action_route.py
 M helao/hexagon/tests/test_active_graft.py
 M helao/hexagon/tests/test_endpoint_manager.py
 M helao/hexagon/tests/test_estop_fixes.py
 M helao/hexagon/tests/test_executor_runner.py
 M helao/hexagon/tests/test_native_data_file.py
 M helao/hexagon/tests/test_native_data_sink.py
 M helao/hexagon/tests/test_native_data_stream.py
 M helao/hexagon/tests/test_native_finalizer.py
 M helao/hexagon/tests/test_native_meta_writer.py
 M run_unit_tests.py
?? helao/core/tests/golden/
?? helao/hexagon/tests/checklists/base_member_surface.json
?? helao/hexagon/tests/checklists/orch_member_contract.json
```
No private-deployment directory may be present. They are gitignored, so `git status` cannot show them; check the paths: `/bin/ls -A "$WT/helao/deploy" | grep -v -x __pycache__ | paste -sd' '` must print `__init__.py hexagon hte test`. Anything else: STOP.

- [ ] **Step 7.8: Report.** Hand the controller: the outputs of 7.2–7.7, Task 1's `t1_compare` output (S7 one-block delta), Task 2's `t2_red_legacy.txt` summary line and `t2_native_vs_legacy.txt`, Task 4's `T4 …` line and `T4-PROJECTION` line, and Task 3's two digests.

- [ ] **Step 7.9: Controller commits (commit 1).**
```
cd "$WT" && conda run -n helao --no-capture-output --cwd "$WT" black harness/openapi_capture.py helao/core/tests/test_active_golden_master.py helao/core/tests/test_analysis_recovery.py helao/core/tests/test_orch_dispatch_golden_master.py helao/core/tests/test_orch_queue_paging.py helao/core/tests/test_run_state_wiring.py helao/core/tests/test_standalone_operator.py helao/core/tests/test_upload_set.py helao/core/tests/unit_test_base_live_buffer.py helao/core/tests/unit_test_base_status.py helao/core/tests/unit_test_config_seam.py helao/core/tests/unit_test_dispatcher.py helao/core/tests/unit_test_estop_sync.py helao/core/tests/unit_test_orch_lifecycle.py helao/core/tests/unit_test_orch_queues.py helao/hexagon/app/action_host.py helao/hexagon/tests/native_fixtures.py helao/hexagon/tests/test_action_context.py helao/hexagon/tests/test_action_route.py helao/hexagon/tests/test_active_graft.py helao/hexagon/tests/test_endpoint_manager.py helao/hexagon/tests/test_estop_fixes.py helao/hexagon/tests/test_executor_runner.py helao/hexagon/tests/test_native_data_file.py helao/hexagon/tests/test_native_data_sink.py helao/hexagon/tests/test_native_data_stream.py helao/hexagon/tests/test_native_finalizer.py helao/hexagon/tests/test_native_meta_writer.py run_unit_tests.py
git -C "$WT" status --short | grep -c .
git -C "$WT" add -A -- harness/openapi_capture.py helao/core/tests/test_active_golden_master.py helao/core/tests/test_analysis_recovery.py helao/core/tests/test_orch_dispatch_golden_master.py helao/core/tests/test_orch_queue_paging.py helao/core/tests/test_run_state_wiring.py helao/core/tests/test_standalone_operator.py helao/core/tests/test_upload_set.py helao/core/tests/unit_test_base_live_buffer.py helao/core/tests/unit_test_base_status.py helao/core/tests/unit_test_config_seam.py helao/core/tests/unit_test_dispatcher.py helao/core/tests/unit_test_estop_sync.py helao/core/tests/unit_test_orch_lifecycle.py helao/core/tests/unit_test_orch_queues.py helao/core/tests/unit_test_active_data_file.py helao/core/tests/unit_test_active_data_stream.py helao/core/tests/unit_test_active_executor.py helao/core/tests/unit_test_active_finalizer.py helao/core/tests/unit_test_base_api.py helao/core/tests/unit_test_base_endpoints.py helao/core/tests/unit_test_base_meta_writer.py helao/core/tests/golden helao/hexagon/app/action_host.py helao/hexagon/tests/checklists/orch_openapi_legacy.json helao/hexagon/tests/checklists/base_member_surface.json helao/hexagon/tests/checklists/orch_member_contract.json helao/hexagon/tests/native_fixtures.py helao/hexagon/tests/test_action_context.py helao/hexagon/tests/test_action_route.py helao/hexagon/tests/test_active_graft.py helao/hexagon/tests/test_endpoint_manager.py helao/hexagon/tests/test_estop_fixes.py helao/hexagon/tests/test_executor_runner.py helao/hexagon/tests/test_native_data_file.py helao/hexagon/tests/test_native_data_sink.py helao/hexagon/tests/test_native_data_stream.py helao/hexagon/tests/test_native_finalizer.py helao/hexagon/tests/test_native_meta_writer.py run_unit_tests.py
git -C "$WT" status --short
```
Black must report every file unchanged (the implementers already ran it); if it reformats anything, re-run Steps 7.2–7.4 before adding. The `grep -c .` before `add` prints `40` (Step 7.7's list). After `add`, `git status --short` shows every line staged (first column `M`, `D` or `A`) and nothing unstaged or untracked. Then:
```
git -C "$WT" commit -F - <<'EOF'
test(b7b): port the golden masters and engine-importing tests to native hosts

Commit 1 of B7b (spec 2026-09-30-B7b-delete-engine-design.md, section 4.1).
The engine is still present, so every port is compared with legacy output:

- dispatch golden master drives OrchHost; 8 of 9 traces byte-identical to a
  legacy capture on this tree, S7 differs only by the intend_none block (Q1);
  native references tracked under helao/core/tests/golden/dispatch/
- action golden master drives ActionSession over ActionHost; 13 of 13 match
  the legacy capture (red-check: patching only the engine globals turned all
  13 red); set_error step removed from scenario 5 on both sides (Q2);
  references tracked under helao/core/tests/golden/action/
- member contracts frozen: base_member_surface.json (89),
  orch_member_contract.json (138)
- openapi_capture records request bodies and enum refs; legacy OrchAPI and
  OrchHost equal on params and bodies for all 74 shared routes; the legacy
  checklist is re-frozen in the new format
- native_fixtures on ActionHost/ActionSession; 7 unit_test_* engine importers
  moved into their native twins and deleted, 7 ported in place;
  run_unit_tests.py now runs 30 functions

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01NxxPoGvJmVh5T4xSpVejFF
EOF
git -C "$WT" status --short; git -C "$WT" log --oneline -1
```
Expected: no status output; the new commit on top.

---

### Task 8: `makeActionApp` accepts native hosts only; the graft machinery is deleted

Commit 2, first of two tasks (Task 9 is the `ws_frames` re-encode; Task 10 closes the commit).

**Files** (line numbers measured on `64f2cf15`):
- Modify: `helao/hexagon/app/factory.py:1-166` (module docstring 1-11; imports 28-35; `_is_native_host` docstring 41-50; `build_wiring` comment 72; delete `makeOrchApp` 78-118; rewrite `makeActionApp` 121-166)
- Modify: `helao/hexagon/app/dispatch_loop.py:1-48` (docstring, imports, `__all__`) and delete `:155-268` (`HexagonGraft`, `graft_hexagon_loop`)
- Modify: `helao/hexagon/adapters/legacy/health.py:11,35` (docstring and message named `graft_hexagon_loop`)
- Modify: `helao/hexagon/hexconfig.py:32-34` (docstring said the orchestrator shim calls `makeOrchApp`)
- Delete: `helao/hexagon/app/active_graft.py`, `helao/hexagon/app/sync_graft.py`
- Rewrite: `helao/deploy/hexagon/servers/action/sim_db_server.py` (35 lines → the 13-line delegate its siblings are)
- Delete: `helao/hexagon/tests/test_active_graft.py`, `helao/hexagon/tests/test_sync_graft.py`
- Create: `helao/hexagon/tests/test_db_endpoint_surface.py`
- Rewrite: `helao/hexagon/tests/test_db_shim.py` (3 tests → 1)
- Modify: `helao/hexagon/tests/test_dispatch_loop.py:1-3,11-15,142-254`
- Modify: `helao/hexagon/tests/test_factory.py:1-5,92-112,125-143,304,375-427,432-439`
- Modify: `helao/hexagon/tests/test_orch_host_surface.py` (insert one test before `test_estop_wakes_the_interrupt_queue` at 252; delete `test_a_native_orch_host_is_not_grafted` 269-277)
- Modify: `helao/hexagon/tests/test_vis_hexagon_producer_parity.py:528-593` (`test_no_hexagon_orch_ws_producer_exists`)
- Modify: `helao/hexagon/tests/test_engine_import_ratchet.py:7-21,44-52,139-150,162-169`
- Modify: `helao/hexagon/tests/live_group.py:4-14`, `helao/hexagon/tests/test_concurrency_live.py:2` (docstrings only; both live files are outside the D-B7b.10 grep because it excludes `/tests/`, so this task owns them)

**Interfaces:**
- Consumes: the commit-1 tree. Nothing from Task 9.
- Produces:
  - `helao.hexagon.app.factory.__all__ == ["build_wiring", "makeActionApp", "makeVisApp"]`; `makeOrchApp` no longer exists.
  - `makeActionApp(server_key: str, legacy_module: str)` (no return annotation; it returns the `ActionHost` that `legacy_module.makeApp` built). Raises `TypeError(f"{legacy_module}.makeApp returned {type(app).__name__}, not an ActionHost")` at build time. Sets `app.hexagon_wiring` and `app.hexagon_ws_bridge = None`, and registers exactly one startup hook, `_hexagon_ws_bridge_startup`, and no shutdown hook. The attribute `hexagon_active_graft` no longer exists.
  - `helao.hexagon.app.dispatch_loop.__all__ == ["HexDispatchLoop", "HexRuntime"]`.
  - The ratchet: no `ALLOWLIST`; `test_nothing_outside_the_engine_imports_it` asserts `offenders() == {}`; the `native` probe builds a third host, `"makeActionApp"`. The `legacy` probe and `test_every_legacy_route_is_built_by_action_api_route` stay (Task 12 deletes them).
  - New test ids for later tasks: `test_orch_host_surface::test_the_host_binds_its_health_adapter_and_starts_no_legacy_heartbeat`, `test_db_endpoint_surface::test_the_driver_exposes_the_db_endpoint_surface[NativeSyncer|ActionHost]`, `test_db_endpoint_surface::test_the_action_host_driver_records_s3_only_when_asked[True|False]`, `test_factory::test_make_action_app_refuses_a_module_that_is_not_native`, `test_factory::test_make_action_app_registers_the_ws_bridge_hook`.

**Execution:** starts after the commit-1 commit (Task 7). Runs alone; Task 9 starts after it finishes, because Step 8.12 temporarily mutates `helao/hexagon/app/orch_host.py` (through `$X/t0_mutate.py`, which restores it), and Task 9 edits that file. This task must not touch `harness/ws_frames.py` or the ws_frames tests, and apart from Step 8.12's restored mutation it does not edit `orch_host.py`. Never commits; the controller commits Tasks 8 and 9 together in Task 10. Until Task 9 lands, the ratchet's static test fails on exactly `harness/ws_frames.py:88` (Step 8.11 expects that).

**Plan decision P-C.1 (deviation from §5.3; spec wrong on the target file):** §5.3 moves `test_native_driver_exposes_db_endpoint_surface` into `test_native_sync_parity.py` and builds the `NativeSyncer` "against that file's existing host fixture". That file has no host fixture (only an `_hd()` helper), and it carries a module-level `pytestmark = skipif(not GOLDEN.is_dir())` on an out-of-tree golden set, so a pin placed there silently skips on any machine without the goldens. **Default:** a new file, `helao/hexagon/tests/test_db_endpoint_surface.py`, with the same assertions parametrized over the two drivers §5.3 names.

**Plan decision P-C.2 (default; spec silent, and §5.3 under-classifies two tests):** §5.3 calls the five other `test_sync_graft` tests "graft rebinding only". Two of them, `test_graft_injects_recording_s3_when_s3_record` and `test_graft_leaves_s3_none_without_s3_record`, pin the `RecordingS3Client` injection that the graft copied from `SimHelaoSyncer.__init__` (`helao/deploy/test/servers/action/sim_db_server.py:82-86`). No other test pins that injection. **Default:** move it too, onto the driver the endpoints now resolve: `test_the_action_host_driver_records_s3_only_when_asked`, parametrized over `s3_record` True/False.

**Plan decision P-C.3 (default; spec silent):** the `ActionHost` driver case runs only the host's own `startup_event` handler (found by name in `app.router.on_startup`), not the whole startup list. The full list also runs `HelaoFastAPI`'s RPC hook, which binds a ZMQ socket on `port + 10000`. Measured: `startup_event` alone builds `SimHelaoSyncer` on `app.driver`, writes only under `tmp_path` (`FAULTS/`), and `await app.shutdown()` plus `teardown_driver` leave no pending task.

**Check-to-test mapping (D-B7b.6)** for the checks this task deletes:

| deleted test | disposition |
|---|---|
| `test_active_graft.py`, all 5 tests | engine-internal: every test builds a legacy `Base`/`Active` and checks what the graft rebinds on it. The subject is deleted. |
| `test_sync_graft::test_graft_rebinds_driver_and_cancels_legacy_loops` | engine-internal: graft rebinding and orphan-loop cancellation; nothing rebinds `app.driver` any more. |
| `test_sync_graft::test_graft_injects_recording_s3_when_s3_record`, `::test_graft_leaves_s3_none_without_s3_record` | moved: `test_db_endpoint_surface::test_the_action_host_driver_records_s3_only_when_asked[True|False]` (P-C.2). |
| `test_sync_graft::test_native_driver_exposes_db_endpoint_surface` | moved: `test_db_endpoint_surface::test_the_driver_exposes_the_db_endpoint_surface[NativeSyncer|ActionHost]` (P-C.1). |
| `test_sync_graft::test_graft_close_restores_original_driver`, `::test_graft_fails_loud_without_live_legacy_driver` | engine-internal: graft handle lifecycle and its startup-order guard. |
| `test_db_shim::test_db_shim_wraps_legacy_and_registers_sync_hook_last` | rewritten as `test_db_shim_is_a_plain_make_action_app_delegate` (same route assertions, plus "no hook of its own"). |
| `test_db_shim::test_db_shim_startup_hook_calls_graft_with_base_params`, `::test_db_shim_shutdown_hook_closes_graft` | engine-internal: the hooks they call are deleted. |
| `test_dispatch_loop::test_graft_rebinds_control_methods`, `::test_graft_rebinds_status_ingestion_endpoints` | engine-internal (instance rebinding); the native control methods are covered by `test_orch_host_surface::test_the_host_owns_the_reducer_rather_than_being_grafted`, and ingestion by `test_ingestion` (21 tests, which import `HexDispatchLoop`/`HexRuntime` from this module). |
| `test_dispatch_loop::test_graft_swaps_heartbeat_task_when_health_wired` | moved: `test_orch_host_surface::test_the_host_binds_its_health_adapter_and_starts_no_legacy_heartbeat`. |
| `test_dispatch_loop::test_graft_without_health_skips_monitor` | no native case: `health` is in `ORCH_REQUIRED` and `OrchHost.__init__` calls `require(*ORCH_REQUIRED)` (`orch_host.py:93`); covered by `test_adapter_health::test_orch_required_includes_health_and_wiring_has_slot` (l.16). |
| `test_factory::test_make_orch_app_constructs_with_graft_hooks` | engine-internal: builds a legacy `OrchAPI`. The orchestrator route surface is gated by `test_orch_host_surface`'s checklist tests. |
| `test_orch_host_surface::test_a_native_orch_host_is_not_grafted` | its subject, `makeOrchApp`, is deleted; `test_factory::test_launcher_shims_delegate` now asserts it is gone. |
| `test_engine_import_ratchet::test_every_allowlisted_file_still_imports_the_engine` | the allowlist is empty; the static test's `offenders() == {}` is stricter. |

- [ ] **Step 8.1: Confirm the starting point.**

```
git -C "$WT" status --short
git -C "$WT" log --oneline -1
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -c "import helao; print(helao.__file__)"
```
Expected: no status output; the commit-1 commit on top; a path under `$WT`.

- [ ] **Step 8.2: Make the ratchet's native probe build a `makeActionApp` composition (the failing half first).** In `helao/hexagon/tests/test_engine_import_ratchet.py`, apply this hunk to `_PROBE` (the `native` branch) and nothing else yet:

```diff
--- a/helao/hexagon/tests/test_engine_import_ratchet.py
+++ b/helao/hexagon/tests/test_engine_import_ratchet.py
@@ -161,11 +161,18 @@
 config_loader.CONFIG = cfg
 if sys.argv[2] == "native":
     from helao.hexagon.app.action_host import ActionHost
+    from helao.hexagon.app.factory import makeActionApp
     from helao.hexagon.app.orch_host import OrchHost
 
     hosts = {
         "ActionHost": ActionHost("SIM", "SIM", "ratchet", 1.0, helao_cfg=cfg),
         "OrchHost": OrchHost("ORCH", "ORCH", "ratchet", version=3.0, helao_cfg=cfg),
+        # B7b: the composition every `deployment: hexagon` action server is
+        # built through. Until B7b it imported active_graft, and with it
+        # twelve engine modules, though no target needed the graft.
+        "makeActionApp": makeActionApp(
+            "SIM", "helao.deploy.test.servers.action.ws_simulator"
+        ),
     }
 else:
     from helao.core.servers.base_api import BaseAPI
```

Create `$X/t8_probe.py`:

```python
"""B7b Task 8: the ratchet's native runtime probe, engine modules per run."""

from helao.hexagon.tests.test_engine_import_ratchet import _probe

report = _probe("native")
print(len(report["engine_modules"]), sorted(report["hosts"]))
```

- [ ] **Step 8.3: Run the probe against the unmodified factory. It must report engine modules.**

```
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t8_probe.py" 2>/dev/null | tail -1 | tee "$X/t8_probe_before.txt"
```
Expected (measured): `12 ['ActionHost', 'OrchHost', 'makeActionApp']`. The 12 are `helao.core.servers` plus `active_data_file`, `active_data_stream`, `active_executor`, `active_finalizer`, `base`, `base_action_queue`, `base_endpoints`, `base_live_buffer`, `base_meta_writer`, `base_primitives`, `base_status`, all pulled in by `factory.py:122`'s `active_graft` import. If the number is 0, the case is vacuous: STOP.

- [ ] **Step 8.4: Rewrite the top of `factory.py`.** Replace lines 1-166 (everything above `def makeVisApp(`, keeping the two blank lines before it) with exactly this block. `makeVisApp` and `_refresh_loaded_modules` are unchanged.

```python
"""Hexagon composition root (spec §4.5).

The ONLY layer that constructs FastAPI objects and wires adapters into
ports. Fail loud (F2b): build_wiring raises without an installed CONFIG;
each makeApp requires its composition's consumed port set BEFORE building
the app — a missing adapter aborts startup, never a silent fake. The
co-located RPC mirror (spec §7.1) is inherited from HelaoFastAPI's startup
hook (ROUTER on http_port+10000, configured-host bind with 0.0.0.0
fallback). Launcher routing: the helao/deploy/hexagon/ action and visualizer
shims call makeActionApp / makeVisApp via the per-server
`deployment: hexagon` config key — zero launcher edits, per-config atomic
cut-over/rollback. The orchestrator shims construct an OrchHost directly and
do not come through here.

makeActionApp composes native hosts only: the module it names must return an
ActionHost from makeApp, and anything else is refused when the app is built
(B7b, D-B7b.2)."""

import os
from importlib import import_module

from helao.helpers import helao_logging as logging
from helao.hexagon.adapters.errors import UnwiredPortError
from helao.hexagon.adapters.legacy.clock import LegacyClockAdapter
from helao.hexagon.adapters.legacy.config import from_global_config
from helao.hexagon.adapters.legacy.health import LegacyHealthAdapter
from helao.hexagon.adapters.legacy.logging_adapter import LegacyLoggingAdapter
from helao.hexagon.adapters.legacy.state_persistence import QueuePckStore
from helao.hexagon.adapters.legacy.status import DispatcherStatusAdapter
from helao.hexagon.adapters.legacy.transport import LegacyTransportAdapter
from helao.hexagon.adapters.native.artifact_store import NativeArtifactStoreAdapter
from helao.hexagon.adapters.native.data_sink import NativeDataSinkAdapter
from helao.hexagon.adapters.native.ws_publish import WsPublishBridge
from helao.hexagon.app.wiring import (
    ACTION_REQUIRED,
    VIS_REQUIRED,
    PortWiring,
)

__all__ = ["build_wiring", "makeActionApp", "makeVisApp"]

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


def _is_native_host(app) -> bool:
    """True when ``app`` is a native host (an ``ActionHost`` or a subclass).

    ``makeActionApp`` refuses anything else at build time. ``OrchHost``
    subclasses ``ActionHost``, so it passes too.

    Imported inside the function: ``action_host`` imports this module's
    siblings, and a module-level import here closes that cycle.
    """
    from helao.hexagon.app.action_host import ActionHost

    return isinstance(app, ActionHost)


def build_wiring(server_key: str) -> PortWiring:
    config = from_global_config()  # raises when CONFIG is not installed
    root = config.root()  # KeyError -> loud, like helao_dirs
    log_root = os.path.join(root, "LOGS")
    scfg = config.server_cfg(server_key)  # KeyError -> loud, like the launcher
    clock = LegacyClockAdapter.from_offset_file(log_root)
    return PortWiring(
        config=config,
        logging=LegacyLoggingAdapter(),
        clock=clock,
        transport=LegacyTransportAdapter(config),
        state_persistence=QueuePckStore(root),
        status=DispatcherStatusAdapter(
            server_key, own_host=scfg["host"], own_port=scfg["port"]
        ),
        health=LegacyHealthAdapter(),
        # P2b-1 native write runtime; ActionHost binds itself to it
        # (artifact_store.meta_writer_for(host)) when it is constructed.
        artifact_store=NativeArtifactStoreAdapter(config=config, clock=clock),
        data_sink=NativeDataSinkAdapter(),
    )


def makeActionApp(server_key: str, legacy_module: str):
    """Build ``legacy_module.makeApp(server_key)`` under a composed wiring.

    The module must return a native host. The check runs here, while the app
    is being built, rather than in the startup event: a failure there reaches
    uvicorn only as ``SystemExit(3)``, so the server never binds and nothing
    names the module. ``legacy_module`` keeps its name until B7c.
    """
    wiring = build_wiring(server_key)
    wiring.require(*ACTION_REQUIRED)
    app = import_module(legacy_module).makeApp(server_key)
    if not _is_native_host(app):
        raise TypeError(
            f"{legacy_module}.makeApp returned {type(app).__name__}, not an ActionHost"
        )
    app.hexagon_wiring = wiring
    app.hexagon_ws_bridge = None

    # Registered AFTER ActionHost's own startup handler (Starlette preserves
    # registration order), so the host's fan-out queues are live when the
    # bridge is bound to them.
    @app.on_event("startup")
    async def _hexagon_ws_bridge_startup():
        # P2b-2 (D3): the WS publish bridge publishes onto the host's fan-out
        # queues. ACTION apps only: an OrchHost serves its own /ws_* relays.
        if not isinstance(wiring.status, DispatcherStatusAdapter):
            raise UnwiredPortError(
                "WS publish bridge requires DispatcherStatusAdapter status wiring"
            )
        status_adapter = wiring.status
        bridge = WsPublishBridge(app.base.status_q, app.base.data_q, app.base.live_q)
        status_adapter.bind_publish_bridge(bridge)
        app.hexagon_ws_bridge = bridge

    return app
```

Removed with the code: the `ORCH_REQUIRED` import (only `makeOrchApp` used it), the startup log line `"<key>: native ActionHost, skipping the active write graft"` (the one log-visible change the spec names in §1), `_hexagon_active_graft_shutdown`, and the two `type: ignore[attr-defined]` lines in `makeOrchApp`.

- [ ] **Step 8.5: Cut the graft out of `dispatch_loop.py`.** Delete from the two blank lines before `@dataclass` (line 155) to the end of the file (line 268; `HexagonGraft` and `graft_hexagon_loop`), so the file ends with `HexDispatchLoop._run_started_phase`. Then replace lines 1-48 (docstring, imports, `LOGGER`, `_POLICY`, `__all__`) with exactly:

```python
"""Single-drainer dispatch loop (spec §4.5, KEEP #2/#3).

ONE long-lived asyncio task parked on an Event owns every queue-draining
command (DispatchHeadAction / FinishThenDispatch* / CloseOut* arise only
from LoopIterate, which only this task feeds): double-drain (F2b) is
structurally impossible. Control events run at their trigger site through
the same pure reducer (DD-3): E-STOP is concurrent with the loop, and the
marked commands' live re-checks are the race guard. In-process self-ops
(KEEP #3): nothing here ever dispatches an RPC/HTTP request to its own
server — every effect is a direct method call on the ``OrchHost`` that
builds this runtime (``OrchHost._build_reducer``)."""

import asyncio
from dataclasses import replace

from helao.hexagon.app.orch_effects import (
    OrchCommandRunner,
    _LazyServerLogger,
    apply_state_delta,
    derive_state,
)
from helao.hexagon.domain.dispatch_policy import DispatchPolicy, ExitLoop
from helao.hexagon.domain.models import ErrorCodes
from helao.hexagon.domain.orchestration import (
    CreateDispatchLoopTask,
    DriverHealthUnrecovered,
    Event,
    LoopIterate,
    RetryDriverHealth,
    UncaughtLoopException,
    WaitAllActionsIdle,
    step,
)

LOGGER = _LazyServerLogger()  # see orch_effects.py for the call-time-resolution
_POLICY = DispatchPolicy()

__all__ = ["HexDispatchLoop", "HexRuntime"]
```

The imports removed are exactly those only the graft used: `Callable`, `dataclass`, `field`, `Optional`, `HexHealthMonitor`, `HexStatusIngestion`, `PortWiring`, `LoopStatus`, `ClearErrorRequested`, `ClearEstopRequested`, `EstopRequested`, `SkipRequested`, `StartRequested`, `StopRequested`. The file drops from 268 to 145 lines. `orch_host.py:1404` and `test_ingestion.py:334` import only `HexDispatchLoop`/`HexRuntime`.

- [ ] **Step 8.6: Delete the two graft modules and reduce the DB shim.**

```
rm "$WT/helao/hexagon/app/active_graft.py" "$WT/helao/hexagon/app/sync_graft.py"
rm "$WT/helao/hexagon/tests/test_active_graft.py" "$WT/helao/hexagon/tests/test_sync_graft.py"
```

Replace the whole of `helao/deploy/hexagon/servers/action/sim_db_server.py` with the same delegate as its sibling `ws_simulator.py` (same docstring shape, same three-line body):

```python
"""Hexagon-composed sim DB server: wraps the test deployment's real
sim_db_server makeApp through the hexagon factory (fail-loud wiring +
co-located RPC via HelaoFastAPI)."""

from helao.hexagon.app.factory import makeActionApp

__all__ = ["makeApp"]

LEGACY_MODULE = "helao.deploy.test.servers.action.sim_db_server"


def makeApp(server_key):
    return makeActionApp(server_key, LEGACY_MODULE)
```

- [ ] **Step 8.7: Fix the two stale descriptions in files this task already changes the behaviour of.**

```diff
--- a/helao/hexagon/adapters/legacy/health.py
+++ b/helao/hexagon/adapters/legacy/health.py
@@ -8,7 +8,7 @@
 and unchanged). ``ping_action_servers``/``status_summary`` need the live
 ``Orch``'s ``ServerMonitor`` and ``status_summary`` attribute, which do not
 exist at ``build_wiring`` time — the adapter is constructed unbound and
-``graft_hexagon_loop`` binds the orch at startup (fail loud before that;
+``OrchHost._build_reducer`` binds the host to it (fail loud before that;
 same late-binding rationale as ``_LazyServerLogger``). ``status_summary``
 values on the orch are ``(status_str, driver_status)`` tuples; the port
 wants the driver status string ('unknown' gates dispatch), so the adapter
@@ -32,7 +32,7 @@
         if self._orch is None:
             raise RuntimeError(
                 "LegacyHealthAdapter is not bound to a live Orch yet "
-                "(graft_hexagon_loop binds it at startup)"
+                "(OrchHost._build_reducer binds it at construction)"
             )
         return self._orch
 
--- a/helao/hexagon/hexconfig.py
+++ b/helao/hexagon/hexconfig.py
@@ -29,8 +29,8 @@
   `deployment: hexagon`, and a `legacy_module:` naming the real target. This is
   the only route available to a deployment whose name may not appear in this
   public repo, and it is equally correct for public ones.
-* An `orchestrator` entry needs no legacy target at all -- its shim calls
-  `makeOrchApp`, which is core rather than deployment-specific -- so it gains
+* An `orchestrator` entry needs no legacy target at all -- its shim builds
+  an `OrchHost`, which is core rather than deployment-specific -- so it gains
   only `deployment: hexagon`.
 * A `reflex:` value names a *bundle*, not a module, so it likewise gains only
   `deployment: hexagon`; the launcher routes it through
```

- [ ] **Step 8.8: Replace the graft tests.** Create `helao/hexagon/tests/test_db_endpoint_surface.py`:

```python
"""The DB endpoint surface, pinned on both drivers that can serve it (B7b).

Moved from ``test_sync_graft.test_native_driver_exposes_db_endpoint_surface``
when the sync graft was deleted (D-B7b.6). The test deployment's
``sim_db_server`` endpoints resolve ``app.driver`` at call time, so these
attributes are the endpoint contract: ``enqueue_yml``, ``list_pending``,
``finish_pending`` (with the ``actions_first`` keyword the harness posts),
``reset_sync``, ``running_tasks`` and ``task_queue``. ``progress`` is
deliberately absent on both (its assignment is commented out), so
``/current_progress`` raising AttributeError is pre-existing behaviour, pinned
here so nobody "fixes" it by accident.

Two drivers: the ``NativeSyncer`` the graft used to bind, and the
``SimHelaoSyncer`` the ``ActionHost`` builds in its own startup event, which is
what the endpoints resolve now that nothing rebinds ``app.driver``. The
recorder injection the graft replicated is pinned on the latter as well.
"""

import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from helao.core.models.helaodirs import HelaoDirs
from helao.core.models.run_dir import RunDir
from helao.hexagon.tests.sync_fixtures import teardown_driver

PARAMS = {"aws_bucket": "helao-sim", "max_tasks": 1}


@pytest.fixture(autouse=True)
def _hermetic_aws(monkeypatch):
    monkeypatch.delenv("AWS_CONFIG_PATH", raising=False)


async def _native_syncer(tmp_path, monkeypatch):
    from helao.hexagon.adapters.native.native_syncer import NativeSyncer

    host = SimpleNamespace(
        server_cfg={"params": dict(PARAMS)},
        world_cfg={"servers": {"SYNC": {"params": dict(PARAMS)}}},
        helaodirs=HelaoDirs(
            root=Path(tmp_path),
            save_root=Path(tmp_path) / RunDir.ACTIVE.value,
            process_root=Path(tmp_path) / "PROCESSES",
        ),
    )
    drv = NativeSyncer(host)  # type: ignore[arg-type]  # duck-typed SyncerHost

    async def _teardown():
        await teardown_driver(drv)

    return drv, _teardown


async def _action_host_driver(tmp_path, monkeypatch, params=None):
    """Run only ActionHost's own startup handler: it builds the driver.

    The full startup list also binds the co-located RPC socket, which this
    test does not need and must not hold.
    """
    from helao.deploy.test.servers.action.sim_db_server import makeApp
    from helao.helpers import config_loader

    (tmp_path / "LOGS").mkdir()
    monkeypatch.setattr(
        config_loader,
        "CONFIG",
        {
            "root": str(tmp_path),
            "dummy": True,
            "simulation": True,
            "servers": {
                "SYNC": {
                    "host": "127.0.0.1",
                    "port": 8910,
                    "group": "action",
                    "fast": "sim_db_server",
                    "params": dict(PARAMS if params is None else params),
                }
            },
        },
    )
    app = makeApp("SYNC")
    (startup,) = [h for h in app.router.on_startup if h.__name__ == "startup_event"]
    startup()
    drv = app.driver

    async def _teardown():
        await teardown_driver(drv)
        await app.shutdown()

    return drv, _teardown


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "build", [_native_syncer, _action_host_driver], ids=["NativeSyncer", "ActionHost"]
)
async def test_the_driver_exposes_the_db_endpoint_surface(build, tmp_path, monkeypatch):
    drv, teardown = await build(tmp_path, monkeypatch)
    try:
        for attr in (
            "enqueue_yml",
            "list_pending",
            "finish_pending",
            "reset_sync",
            "running_tasks",
            "task_queue",
        ):
            assert hasattr(drv, attr), attr
        assert "actions_first" in inspect.signature(drv.finish_pending).parameters
        assert drv.task_queue.qsize() == 0
        assert drv.running_tasks == {}
        assert not hasattr(drv, "progress")
    finally:
        await teardown()


@pytest.mark.asyncio
@pytest.mark.parametrize("s3_record", [True, False])
async def test_the_action_host_driver_records_s3_only_when_asked(
    s3_record, tmp_path, monkeypatch
):
    """The graft used to replicate SimHelaoSyncer's recorder injection; the
    driver the endpoints now resolve must do it itself (sim_db_server.py:82-86).
    """
    from helao.deploy.test.servers.action.sim_db_server import RecordingS3Client

    params = dict(PARAMS, s3_record=True) if s3_record else dict(PARAMS)
    drv, teardown = await _action_host_driver(tmp_path, monkeypatch, params)
    try:
        if s3_record:
            assert isinstance(drv.s3, RecordingS3Client)
            assert drv.s3.sim_root == Path(tmp_path) / "S3_SIM"
        else:
            assert not isinstance(drv.s3, RecordingS3Client)
    finally:
        await teardown()
```

Replace the whole of `helao/hexagon/tests/test_db_shim.py` with:

```python
"""The hexagon sim_db_server shim is a plain makeActionApp delegate (B7b).

It used to register a sync-graft startup hook that swapped app.driver for a
NativeSyncer. The graft is gone: the test deployment's sim_db_server builds an
ActionHost whose driver the DB endpoints use directly, so the shim is the same
delegate as its siblings. The DB endpoint surface itself is pinned by
test_db_endpoint_surface."""

import pytest


def _world(tmp_path):
    return {
        "root": str(tmp_path),
        "dummy": True,
        "simulation": True,
        "servers": {
            "SYNC": {
                "host": "127.0.0.1",
                "port": 8910,
                "group": "action",
                "fast": "sim_db_server",
                "params": {"aws_bucket": "helao-sim", "s3_record": True},
            },
        },
    }


@pytest.fixture()
def installed_config(tmp_path, monkeypatch):
    from helao.helpers import config_loader

    world = _world(tmp_path)
    (tmp_path / "LOGS").mkdir()
    monkeypatch.setattr(config_loader, "CONFIG", world)
    return world


def test_db_shim_is_a_plain_make_action_app_delegate(installed_config):
    from helao.deploy.hexagon.servers.action import sim_db_server as shim
    from helao.hexagon.app.action_host import ActionHost

    assert shim.LEGACY_MODULE == "helao.deploy.test.servers.action.sim_db_server"
    app = shim.makeApp("SYNC")
    assert isinstance(app, ActionHost)
    assert app.hexagon_wiring is not None  # set only by makeActionApp
    routes = {r.path for r in app.routes}  # type: ignore[attr-defined]
    # the real DB surface survived the wrap
    for path in ("/finish_yml", "/finish_pending", "/tasks", "/n_queue"):
        assert path in routes, path
    startup_names = [h.__name__ for h in app.router.on_startup]
    shutdown_names = [h.__name__ for h in app.router.on_shutdown]
    # makeActionApp's bridge hook is the last one registered: the shim adds none
    assert startup_names[-1] == "_hexagon_ws_bridge_startup"
    assert not any("sync_graft" in name for name in startup_names + shutdown_names)
```

Apply these edits (each hunk's `-`/`+` lines are the exact old/new text; context lines are unchanged):

```diff
--- a/helao/hexagon/tests/test_dispatch_loop.py
+++ b/helao/hexagon/tests/test_dispatch_loop.py
@@ -1,6 +1,6 @@
 """Single-drainer loop: park/unpark, ladder-to-park mini-run, refusals,
-estop funnel + race seed (DD-3), graft rebinding. Uses the Task 8 stub orch
-extended with a scripted dispatch that drains its own queues."""
+estop funnel + race seed (DD-3), driver-health exhaustion. Uses the Task 8
+stub orch extended with a scripted dispatch that drains its own queues."""
 
 import asyncio
 from typing import Optional
@@ -8,11 +8,7 @@
 import pytest
 
 from helao.core.error import ErrorCodes
-from helao.hexagon.app.dispatch_loop import (
-    HexDispatchLoop,
-    HexRuntime,
-    graft_hexagon_loop,
-)
+from helao.hexagon.app.dispatch_loop import HexDispatchLoop, HexRuntime
 from helao.hexagon.app.orch_effects import OrchCommandRunner
 from helao.hexagon.app.wiring import PortWiring
 from helao.hexagon.domain.models import LoopStatus
@@ -140,120 +136,6 @@
 
 
 @pytest.mark.asyncio
-async def test_graft_rebinds_control_methods():
-    orch = _ScriptedOrch(n_acts=1)
-
-    async def _noop():  # legacy originals to capture
-        return None
-
-    for name in (
-        "start",
-        "start_loop",
-        "stop",
-        "skip",
-        "estop_loop",
-        "clear_estop",
-        "clear_error",
-    ):
-        setattr(orch, name, _noop)
-    graft = graft_hexagon_loop(orch, PortWiring(logging=_AlertSpy()))
-    try:
-        assert set(graft.originals) == {
-            "start",
-            "start_loop",
-            "stop",
-            "skip",
-            "estop_loop",
-            "clear_estop",
-            "clear_error",
-            # P2a DD-2: ingestion rebind set grafted onto the same originals
-            # dict; this stub never defined them, so both capture None
-            # (tolerant getattr(..., None) — see graft_hexagon_loop).
-            "update_status",
-            "update_nonblocking",
-        }
-        await orch.start()  # type: ignore[attr-defined]  # rebound by the graft
-        for _ in range(200):
-            if not orch.action_dq:
-                break
-            await asyncio.sleep(0.01)
-        assert not orch.action_dq
-        assert orch.current_stop_message == ""  # legacy start() clears banner
-        # skip while parked mirrors legacy: clears action_dq only
-        orch.action_dq = ["x"]
-        await orch.skip()  # type: ignore[attr-defined]  # rebound by the graft
-        assert orch.action_dq == []
-    finally:
-        await graft.loop.close()
-
-
-@pytest.mark.asyncio
-async def test_graft_rebinds_status_ingestion_endpoints():
-    """P2a: graft_hexagon_loop extends the instance-rebind set with
-    update_status/update_nonblocking (DD-2 atomic hand-off)."""
-    orch = _ScriptedOrch()
-    graft = graft_hexagon_loop(orch, PortWiring(logging=_AlertSpy()))
-    assert graft.ingestion is not None
-    assert (
-        orch.update_status.__func__  # type: ignore[attr-defined]  # rebound by the graft
-        is type(graft.ingestion).update_status
-    )
-    assert (
-        orch.update_nonblocking.__func__  # type: ignore[attr-defined]  # rebound by the graft
-        is type(graft.ingestion).update_nonblocking
-    )
-    assert "update_status" in graft.originals
-    await graft.close()
-
-
-@pytest.mark.asyncio
-async def test_graft_swaps_heartbeat_task_when_health_wired():
-    class _FakeHealth:
-        def __init__(self):
-            self.bound = None
-
-        def bind_orch(self, orch):
-            self.bound = orch
-
-        async def endpoints_available(self, urls):
-            return [(u, True) for u in urls]
-
-        async def ping_action_servers(self):
-            return {}
-
-        def status_summary(self):
-            return {}
-
-    async def _forever():
-        await asyncio.sleep(3600)
-
-    orch = _ScriptedOrch()
-    orch.heartbeat_interval = 3600  # type: ignore[attr-defined]
-    orch.ignore_heartbeats = []  # type: ignore[attr-defined]
-    orch.heartbeat_monitor = (  # type: ignore[attr-defined]
-        asyncio.get_running_loop().create_task(_forever())
-    )
-    health = _FakeHealth()
-    graft = graft_hexagon_loop(orch, PortWiring(logging=_AlertSpy(), health=health))
-    await asyncio.sleep(0.05)
-    assert health.bound is orch
-    assert (
-        orch.heartbeat_monitor.cancelled()  # type: ignore[attr-defined]
-        or orch.heartbeat_monitor.done()  # type: ignore[attr-defined]
-    )
-    assert graft.health_monitor is not None
-    await graft.close()
-
-
-@pytest.mark.asyncio
-async def test_graft_without_health_skips_monitor():
-    orch = _ScriptedOrch()
-    graft = graft_hexagon_loop(orch, PortWiring(logging=_AlertSpy()))
-    assert graft.health_monitor is None
-    await graft.close()
-
-
-@pytest.mark.asyncio
 async def test_driver_health_exhaustion_feeds_unrecovered_event(monkeypatch):
     """P2a: RetryDriverHealth exhaustion now constructs the
     DriverHealthUnrecovered event (same stop-message wording via the
```

```diff
--- a/helao/hexagon/tests/test_factory.py
+++ b/helao/hexagon/tests/test_factory.py
@@ -1,8 +1,7 @@
-"""Composition factory: fail-loud wiring, OrchAPI construction with graft
-hooks, action-app wrap, vis deferral, launcher shim delegation. Construction
-level only — full lifecycle is the Task 11 launched smoke."""
+"""Composition factory: fail-loud wiring, the native-only action-app wrap and
+its WS bridge hook, vis deferral, launcher shim delegation. Construction level
+only — full lifecycle is the Task 11 launched smoke."""
 
-import inspect
 import os
 
 import pytest
@@ -89,28 +88,6 @@
     w.require("config", "logging", "clock", "transport", "state_persistence")
 
 
-def test_make_orch_app_constructs_with_graft_hooks(installed_config):
-    from helao.core.servers.orch_api import OrchAPI
-    from helao.hexagon.app.factory import makeOrchApp
-
-    app = makeOrchApp("ORCH")
-    assert isinstance(app, OrchAPI)
-    assert app.hexagon_wiring is not None  # type: ignore[attr-defined]
-    routes = {r.path for r in app.routes}  # type: ignore[attr-defined]
-    # BaseAPI/OrchAPI system surface present (spec §8.2 spot checks)
-    for path in (
-        "/start",
-        "/stop",
-        "/estop_orch",
-        "/clear_estop",
-        "/append_sequence",
-        "/global_status",
-        "/update_status",
-    ):
-        assert path in routes, path
-    assert app.rpc_dispatcher is not None  # co-located RPC registry exists
-
-
 def test_orchestrator_exposes_loaded_modules(installed_config):
     """An orchestrator must answer /loaded_modules, like every other `fast:` server.
 
@@ -122,25 +99,19 @@
     process is running the hexagon shim or the legacy module, because neither
     launcher logs the deployment when a config sets it explicitly.
 
-    `OrchAPI` is a sibling of `BaseAPI`, not a subclass, so this is asserted on
-    a real constructed app rather than on the shared registrar -- a registrar
-    test would still pass if `OrchAPI` stopped calling it.
+    Asserted on the app the orchestrator shim really builds (an ``OrchHost``),
+    not on the shared registrar: a registrar test would still pass if the host
+    stopped calling it.
     """
-    from helao.core.servers.base_api import BaseAPI
-    from helao.hexagon.app.factory import makeOrchApp
+    from helao.deploy.hexagon.servers.orchestrator.async_orch2 import makeApp
 
-    app = makeOrchApp("ORCH")
+    app = makeApp("ORCH")
     routes = {r.path for r in app.routes}  # type: ignore[attr-defined]
     assert "/loaded_modules" in routes
 
-    # Registered exactly once. It used to live on BaseAPI's __init__ as well;
-    # hoisting it to the shared registrar without removing that would leave two
-    # handlers on one path, where FastAPI silently serves the first.
+    # Registered exactly once: a second handler on one path is accepted
+    # silently by FastAPI, which then serves the first.
     assert [r.path for r in app.routes].count("/loaded_modules") == 1  # type: ignore[attr-defined]
-    assert not any(
-        "/loaded_modules" in line
-        for line in inspect.getsource(BaseAPI.__init__).splitlines()
-    ), "duplicate /loaded_modules registration reintroduced on BaseAPI.__init__"
 
     # The payload is the watcher's contract: {abs repo .py path: sha1}. An empty
     # dict would satisfy a presence-only check while mapping nothing.
@@ -301,7 +272,8 @@
     # scoped to makeApp, not the module: the docstring names makeOrchApp
     # precisely to explain why it is no longer called.
     assert "makeOrchApp" not in inspect.getsource(orch_shim.makeApp)
-    assert callable(factory.makeOrchApp)  # still there for unported compositions
+    # B7b deleted makeOrchApp outright: no composition grafts a legacy Orch.
+    assert not hasattr(factory, "makeOrchApp")
 
 
 def test_build_wiring_status_port_carries_own_identity(installed_config):
@@ -372,52 +344,55 @@
     w.require(*ACTION_REQUIRED)  # fail-loud stays satisfiable
 
 
-def test_make_action_app_registers_graft_hooks(installed_config):
+def test_make_action_app_registers_the_ws_bridge_hook(installed_config):
     from helao.hexagon.app.factory import makeActionApp
 
     app = makeActionApp("SIM", "helao.deploy.test.servers.action.ws_simulator")
     assert app.hexagon_wiring.artifact_store is not None
-    assert app.hexagon_active_graft is None  # applied at startup, not build
+    assert not hasattr(app, "hexagon_active_graft")
     startup_names = [h.__name__ for h in app.router.on_startup]
     shutdown_names = [h.__name__ for h in app.router.on_shutdown]
-    assert "_hexagon_active_graft_startup" in startup_names
-    assert "_hexagon_active_graft_shutdown" in shutdown_names
-    # ours must be registered AFTER the legacy BaseAPI startup that creates
-    # app.base (Starlette preserves registration order)
-    assert startup_names[-1] == "_hexagon_active_graft_startup"
+    # ours must be registered AFTER ActionHost's own startup handler
+    # (Starlette preserves registration order)
+    assert startup_names[-1] == "_hexagon_ws_bridge_startup"
+    assert not any("graft" in name for name in startup_names + shutdown_names)
 
 
-@pytest.mark.asyncio
-async def test_action_app_startup_binds_ws_publish_bridge(
+def test_make_action_app_refuses_a_module_that_is_not_native(
     installed_config, monkeypatch
 ):
-    """P2b-2 D3: the existing _hexagon_active_graft_startup hook constructs
-    WsPublishBridge over the live base's queues and binds it into the status
-    adapter (ACTION apps only; makeOrchApp is untouched, Q1)."""
-    import helao.hexagon.app.active_graft as active_graft_mod
-    from helao.hexagon.adapters.native.ws_publish import WsPublishBridge
-    from helao.hexagon.app.factory import makeActionApp
+    """D-B7b.2: a non-ActionHost is refused while the app is built, naming the
+    module, instead of failing inside the startup event as SystemExit(3)."""
+    from types import SimpleNamespace
 
-    class _StubGraft:
-        def close(self):
-            pass
+    from fastapi import FastAPI
+
+    from helao.hexagon.app import factory
 
-    # isolate the bind from the P2b-1 write graft (its own tests cover it)
     monkeypatch.setattr(
-        active_graft_mod,
-        "graft_active_write_path",
-        lambda base, wiring: _StubGraft(),
+        factory,
+        "import_module",
+        lambda name: SimpleNamespace(makeApp=lambda server_key: FastAPI()),
+    )
+    with pytest.raises(TypeError) as ei:
+        factory.makeActionApp("SIM", "some.legacy.module")
+    assert str(ei.value) == (
+        "some.legacy.module.makeApp returned FastAPI, not an ActionHost"
     )
+
+
+@pytest.mark.asyncio
+async def test_action_app_startup_binds_ws_publish_bridge(installed_config):
+    """P2b-2 D3: the _hexagon_ws_bridge_startup hook constructs WsPublishBridge
+    over the host's own fan-out queues and binds it into the status adapter
+    (ACTION apps only; an OrchHost serves its own relays)."""
+    from helao.hexagon.adapters.native.ws_publish import WsPublishBridge
+    from helao.hexagon.app.factory import makeActionApp
+
     app = makeActionApp("SIM", "helao.deploy.test.servers.action.ws_simulator")
     assert app.hexagon_ws_bridge is None  # bound at startup, not at build
-    # No injected `base` any more: makeActionApp returns an ActionHost, which
-    # owns the three fan-out queues itself and answers to `app.base is app`.
-    # Assigning one here raised AttributeError once `base` became a read-only
-    # property, and the assertions below read the real queues regardless.
     hook = [
-        h
-        for h in app.router.on_startup
-        if h.__name__ == "_hexagon_active_graft_startup"
+        h for h in app.router.on_startup if h.__name__ == "_hexagon_ws_bridge_startup"
     ][0]
     await hook()
     assert isinstance(app.hexagon_ws_bridge, WsPublishBridge)
@@ -431,12 +406,11 @@
 async def test_status_adapter_unbound_is_fail_loud(installed_config):
     """Controller hardening 3 (Q1/D3 underpinning): a DispatcherStatusAdapter
     is unbound by default and stays fail-loud (UnwiredPortError on
-    publish_status). This is what makes "makeOrchApp never binds" SAFE — only
-    makeActionApp's startup hook binds the bridge (see
-    test_action_app_startup_binds_ws_publish_bridge); makeOrchApp adds no bind
-    call, verified by code review, so an orch composition's status adapter
-    keeps this default-unbound fail-loud behavior. (Bare-adapter check; not a
-    makeOrchApp integration test.)"""
+    publish_status). Only makeActionApp's startup hook binds the bridge (see
+    test_action_app_startup_binds_ws_publish_bridge); the composed orchestrator
+    side is pinned by
+    test_vis_hexagon_producer_parity::test_no_hexagon_orch_ws_producer_exists.
+    (Bare-adapter check.)"""
     from helao.hexagon.adapters.errors import UnwiredPortError
     from helao.hexagon.adapters.legacy.status import DispatcherStatusAdapter
 
```

```diff
--- a/helao/hexagon/tests/test_orch_host_surface.py
+++ b/helao/hexagon/tests/test_orch_host_surface.py
@@ -249,6 +249,25 @@
         assert "_hex_runtime" in src, f"{method.__name__} bypasses the reducer"
 
 
+def test_the_host_binds_its_health_adapter_and_starts_no_legacy_heartbeat():
+    """OrchHost binds its own health adapter; no graft does it any more.
+
+    Moved from test_dispatch_loop's graft health test (B7b, D-B7b.6). The graft
+    used to bind the adapter to a legacy Orch and cancel that Orch's heartbeat
+    task. The host now binds the adapter to itself in ``_build_reducer``,
+    builds the hexagon health monitor, and never creates the legacy heartbeat
+    task at all. The no-health case has no native form: ``health`` is in
+    ORCH_REQUIRED, so OrchHost cannot be built without it
+    (test_adapter_health::test_orch_required_includes_health_and_wiring_has_slot).
+    """
+    from helao.hexagon.app.ingestion import HexHealthMonitor
+
+    host = _host()
+    assert host.hexagon_wiring.health._orch is host  # type: ignore[attr-defined]
+    assert isinstance(host._hex_health, HexHealthMonitor)
+    assert host.heartbeat_monitor is None
+
+
 def test_estop_wakes_the_interrupt_queue():
     """DD-5 item 6, and it is not decorative.
 
@@ -264,14 +283,3 @@
 
     src = inspect.getsource(OrchHost.estop_loop)
     assert "interrupt_q.put" in src, "estop_loop must wake the interrupt queue"
-
-
-def test_a_native_orch_host_is_not_grafted():
-    """Two dispatch loops on one set of queues would break the
-    single-drainer property the reducer exists to guarantee."""
-    import inspect
-
-    from helao.hexagon.app import factory
-
-    src = inspect.getsource(factory.makeOrchApp)
-    assert "_is_native_host" in src, "makeOrchApp must skip the graft for a native host"
```

```diff
--- a/helao/hexagon/tests/test_vis_hexagon_producer_parity.py
+++ b/helao/hexagon/tests/test_vis_hexagon_producer_parity.py
@@ -529,29 +529,27 @@
 async def test_no_hexagon_orch_ws_producer_exists(tmp_path, monkeypatch):
     """THE RESIDUAL for Amendment 1 gate item 1, pinned rather than papered over.
 
-    ``ws_publish.py`` concedes it in prose ("orch WS stays on legacy relays,
-    Q1"); this is the executable form. A hexagon-composed ORCHESTRATOR has a
-    status adapter with no publish bridge bound, so every ``publish_*`` on it
-    raises. Its ``/ws_status`` and ``/ws_data`` therefore have no hexagon
-    producer at all -- they are served by the untouched legacy
-    ``StatusBroadcaster._ws_relay``, which sends a DIFFERENT payload shape
-    (dicts, not models) from the one the action-server bridge sends.
+    The orchestrator the shim builds (an ``OrchHost``) has a status adapter
+    with no publish bridge bound, so every ``publish_*`` on it raises. Its
+    ``/ws_status`` and ``/ws_data`` are served by the host's own relays
+    (``OrchHost._register_orch_ws_routes``), which send a DIFFERENT payload
+    shape (dicts, not models) from the one the action-server bridge sends.
 
     ``test_factory.test_status_adapter_unbound_is_fail_loud`` asserts this of a
-    bare adapter and says in its own docstring that the makeOrchApp side is
-    "verified by code review"; this closes that with the composed app.
+    bare adapter; this closes it with the composed app.
 
     The day a hexagon orch producer lands, this test fails -- deliberately.
-    Binding a bridge in ``makeOrchApp`` breaks the two assertions below, and
-    that failure is the signal to re-run the orch half of gate item 1 (the
+    Binding a bridge on the orchestrator breaks the assertions below, and that
+    failure is the signal to re-run the orch half of gate item 1 (the
     consumers of the dict shape -- ``RemoteBackend._ws_loop`` and every
     ``/ws_status`` subscriber -- have never been conformance-tested against a
     model-shaped frame).
     """
+    from helao.deploy.hexagon.servers.orchestrator.async_orch2 import makeApp
     from helao.helpers import config_loader
     from helao.hexagon.adapters.errors import UnwiredPortError
     from helao.hexagon.adapters.legacy.status import DispatcherStatusAdapter
-    from helao.hexagon.app import factory
+    from helao.hexagon.app import factory, orch_host
 
     (tmp_path / "LOGS").mkdir()
     monkeypatch.setattr(
@@ -573,8 +571,8 @@
         },
     )
 
-    app = factory.makeOrchApp("ORCH")
-    status = app.hexagon_wiring.status  # type: ignore[attr-defined]
+    app = makeApp("ORCH")
+    status = app.hexagon_wiring.status
     assert isinstance(status, DispatcherStatusAdapter)
     assert status._publish_bridge is None, (
         "a hexagon orch composition now binds a WS publish bridge -- the orch "
@@ -582,14 +580,13 @@
     )
     assert not hasattr(
         app, "hexagon_ws_bridge"
-    ), "makeOrchApp now carries a ws bridge attribute; see this test's docstring"
+    ), "the orchestrator now carries a ws bridge attribute; see this test's docstring"
     with pytest.raises(UnwiredPortError):
         await status.publish_status(wf.build_status_payload().as_dict())
 
     # And the source-level twin, so the hole is visible without constructing an
-    # app: the ONLY bind_publish_bridge call site in the composition root is in
-    # makeActionApp.
-    assert "bind_publish_bridge" not in inspect.getsource(factory.makeOrchApp)
+    # app: the ONLY bind_publish_bridge call site is in makeActionApp.
+    assert "bind_publish_bridge" not in inspect.getsource(orch_host)
     assert "bind_publish_bridge" in inspect.getsource(factory.makeActionApp)
 
 
```

```diff
--- a/helao/hexagon/tests/live_group.py
+++ b/helao/hexagon/tests/live_group.py
@@ -1,16 +1,18 @@
 """In-process REAL-transport hexagon group for §10.3 precise-interleaving
 items (P1b2b: items 1, 3, 5).
 
-Boots the REAL makeOrchApp/makeActionApp compositions under uvicorn inside
-the test's event loop — real HTTP routes registered through the real
-registration code, and the co-located ZMQ RPC mirrors HelaoFastAPI
+Boots the REAL compositions under uvicorn inside the test's event loop: the
+OrchHost the orchestrator shim builds, the SIM through makeActionApp, and the
+test deployment's sim_db_server — real HTTP routes registered through the
+real registration code, and the co-located ZMQ RPC mirrors HelaoFastAPI
 auto-registers on http_port+10000 (§10.1 fixture-fidelity; boot pattern
-proven by test_adapter_transport.py). Race injection happens via
-app.hexagon_graft.runtime.handle(event) from a concurrent task (DD-3).
+proven by test_adapter_transport.py). Race injection happens via the host's
+own reducer runtime, orch_app._hex_runtime.handle(event), from a concurrent
+task (DD-3).
 
-NOT a stub orch: the orchestrator is the real legacy Orch wrapped by the
-P1b1 graft; the SIM is the real ws_simulator makeApp, and DB is the real
-legacy sim_db_server (its syncer is on the ORCH finish path). Single
+NOT a stub orch: the orchestrator is the real native OrchHost; the SIM is the
+real ws_simulator makeApp, and DB is the real sim_db_server (its syncer is on
+the ORCH finish path). Single
 process == shared CONFIG dict + logging singleton (a documented deviation
 from launched groups; items 2/4/6/7 run against a real launched group
 instead).
--- a/helao/hexagon/tests/test_concurrency_live.py
+++ b/helao/hexagon/tests/test_concurrency_live.py
@@ -1,5 +1,5 @@
 """§10.3 mandatory concurrency suite — in-process real-transport items
-(1, 3, 5). Real hexagon ORCH (makeOrchApp graft) + real SIM (ws_simulator)
+(1, 3, 5). Real hexagon ORCH (native OrchHost) + real SIM (ws_simulator)
 over real ZMQ RPC + HTTP; races injected via HexRuntime.handle from
 concurrent tasks (DD-3). Launched-group items (2, 4, 6, 7) live in
 helao/hexagon/tests/smoke/conc_items.py."""
```

- [ ] **Step 8.9: Empty the ratchet allowlist.** Apply the remaining hunks to `helao/hexagon/tests/test_engine_import_ratchet.py`:

```diff
--- a/helao/hexagon/tests/test_engine_import_ratchet.py
+++ b/helao/hexagon/tests/test_engine_import_ratchet.py
@@ -7,18 +7,18 @@
 Static half. Every tracked ``.py`` outside the engine and outside tests is
 parsed, and any ``import``/``from`` that names ``helao.core.servers`` -- at
 module top, in a function body, or under ``TYPE_CHECKING`` -- is an offender.
-Three files may keep importing it, and only until B7b deletes them: the graft
-machinery and the harness encoder that produces the legacy bytes the parity
-tests compare against. The allowlist is shrink-only: an entry that stops
-importing the engine fails, so B7b cannot leave a stale one behind.
-
-Runtime half. A fresh interpreter constructs an ``ActionHost`` and an
-``OrchHost`` under the ``goldenhex`` server entries and must end with no
-``helao.core.servers`` module loaded. A subprocess, because this pytest
-process may already hold the engine through other imports. On 415c0bb2 the
-import-time count was 2 and the construction-time count 17: a helper that
-imports the engine lazily is an importer even when no static read of the
-hosts finds it.
+There is no allowlist: B7b deleted the graft machinery and re-pointed the
+harness encoder, the last three files B7a allowed.
+
+Runtime half. A fresh interpreter constructs an ``ActionHost``, an
+``OrchHost`` and a ``makeActionApp`` composition under the ``goldenhex``
+server entries and must end with no ``helao.core.servers`` module loaded. A
+subprocess, because this pytest process may already hold the engine through
+other imports. On 415c0bb2 the import-time count was 2 and the
+construction-time count 17; on e60d800a ``makeActionApp`` alone still loaded
+12, through its unconditional ``active_graft`` import. A helper that imports
+the engine lazily is an importer even when no static read of the hosts finds
+it.
 
 The route-class tests pin D-B7a.4. ``HelaoFastAPI`` no longer installs
 ``ActionAPIRoute``, so each host installs its own route class before its first
@@ -41,16 +41,6 @@
 ENGINE: Final[str] = "helao.core.servers"
 CONFIG: Final[Path] = REPO_ROOT / "helao/deploy/test/configs/goldenhex.yml"
 
-#: B7b's files, and nothing else: B7b deletes the graft (active_graft.py,
-#: factory.py's makeOrchApp) and re-baselines the harness (ws_frames.py).
-ALLOWLIST: Final[frozenset[str]] = frozenset(
-    {
-        "harness/ws_frames.py",
-        "helao/hexagon/app/active_graft.py",
-        "helao/hexagon/app/factory.py",
-    }
-)
-
 
 def _is_engine(name: str) -> bool:
     return name == ENGINE or name.startswith(ENGINE + ".")
@@ -136,18 +126,9 @@
     assert len(files) > 500, f"swept only {len(files)} files"
 
 
-def test_every_allowlisted_file_still_imports_the_engine() -> None:
-    """Shrink-only: an entry whose file stopped importing the engine is stale."""
-    found = offenders()
-    stale = sorted(rel for rel in ALLOWLIST if rel not in found)
-    assert (
-        stale == []
-    ), f"delete these from ALLOWLIST, they no longer import it: {stale}"
-
-
 def test_nothing_outside_the_engine_imports_it() -> None:
-    extra = {rel: sites for rel, sites in offenders().items() if rel not in ALLOWLIST}
-    assert extra == {}, f"engine imports outside helao/core/servers/: {extra}"
+    found = offenders()
+    assert found == {}, f"engine imports outside helao/core/servers/: {found}"
 
 
 _PROBE: Final[str] = r"""
```

- [ ] **Step 8.10: The probe now reports no engine module.**

```
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t8_probe.py" 2>/dev/null | tail -1 | tee "$X/t8_probe_after.txt"
```
Expected (measured): `0 ['ActionHost', 'OrchHost', 'makeActionApp']`.

- [ ] **Step 8.11: Run every file this task touches, plus the native-deployment pins, one pytest process each.**

```
for f in helao/hexagon/tests/test_factory.py helao/hexagon/tests/test_db_shim.py helao/hexagon/tests/test_db_endpoint_surface.py helao/hexagon/tests/test_dispatch_loop.py helao/hexagon/tests/test_orch_host_surface.py helao/hexagon/tests/test_vis_hexagon_producer_parity.py helao/hexagon/tests/test_adapter_health.py helao/hexagon/tests/test_ingestion.py helao/hexagon/tests/test_hte_is_native.py helao/hexagon/tests/test_test_deployment_is_native.py helao/hexagon/tests/test_db_gate_config.py helao/hexagon/tests/test_native_sync_parity.py helao/hexagon/tests/test_engine_import_ratchet.py; do
  echo "$f :: $(timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -m pytest -q -p no:cacheprovider --color=no "$f" 2>&1 | grep -E '^[0-9]+ (passed|failed)')"
done
```
Expected (measured on a dry run of this task alone):
```
helao/hexagon/tests/test_factory.py :: 17 passed
helao/hexagon/tests/test_db_shim.py :: 1 passed
helao/hexagon/tests/test_db_endpoint_surface.py :: 4 passed
helao/hexagon/tests/test_dispatch_loop.py :: 4 passed
helao/hexagon/tests/test_orch_host_surface.py :: 11 passed
helao/hexagon/tests/test_vis_hexagon_producer_parity.py :: 16 passed
helao/hexagon/tests/test_adapter_health.py :: 5 passed
helao/hexagon/tests/test_ingestion.py :: 21 passed
helao/hexagon/tests/test_hte_is_native.py :: 8 passed
helao/hexagon/tests/test_test_deployment_is_native.py :: 3 passed
helao/hexagon/tests/test_db_gate_config.py :: 9 passed
helao/hexagon/tests/test_native_sync_parity.py :: 3 passed
helao/hexagon/tests/test_engine_import_ratchet.py :: 1 failed, 5 passed
```
(each line also carries a warnings count and a time.) The one ratchet failure must be exactly `engine imports outside helao/core/servers/: {'harness/ws_frames.py': ['harness/ws_frames.py:88']}`, which Task 9 removes; once Task 9 has landed the line reads `6 passed`. Any other failure: STOP. Before this task the counts were `test_factory` 17, `test_db_shim` 3, `test_dispatch_loop` 8, `test_orch_host_surface` 11, ratchet 7; `test_native_sync_parity` skips (does not fail) on a machine without the GM-1 golden set, which is why P-C.1 keeps the moved pin out of it.

- [ ] **Step 8.12: Prove the new health test can fail.** Replace the line `            bind(self)` in `OrchHost._build_reducer` (`helao/hexagon/app/orch_host.py`, the line after `        if bind is not None:`, near line 1416) with `            pass`, run the test, and restore, through the Task 0 helper. Create `$X/t8_probes.json` with exactly this content:
```json
[
  {"file": "helao/hexagon/app/orch_host.py",
   "old": "            bind(self)\n", "new": "            pass\n",
   "test": "helao/hexagon/tests/test_orch_host_surface.py", "k": "health",
   "expect": "1 failed"}
]
```
**[tool timeout 600 s]** (one probe, well under the cap):
```
timeout 400 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t0_mutate.py" "$X/t8_probes.json"
git -C "$WT" diff --quiet -- helao/hexagon/app/orch_host.py && echo ORCH_HOST_UNCHANGED
```
Expected (measured): `RED rc=1 helao/hexagon/tests/test_orch_host_surface.py :: expect found :: RESTORED helao/hexagon/app/orch_host.py`, `MUTATE-PASS`, `ORCH_HOST_UNCHANGED` (Task 9 has not started, so `orch_host.py` has no other edit yet).

- [ ] **Step 8.13: Nothing in the parent still reads a deleted name, outside the provenance docstrings Task 11 classifies.**

```
git -C "$WT" grep --untracked -n -E 'makeOrchApp|graft_hexagon_loop|HexagonGraft|active_graft|sync_graft|hexagon_active_graft|graft_native_sync|graft_active_write_path|NativeSyncGraft|_hexagon_graft_startup' -- '*.py' '*.yml' '*.bat' '*.sh' '*.toml' '*.json' | cut -d: -f1 | sort | uniq -c
```
Expected (measured; `--untracked` makes `git grep` include the new, not-yet-added test file, and the deleted files have dropped out):
```
      2 helao/deploy/hexagon/servers/orchestrator/async_orch2.py
      1 helao/deploy/hte/servers/orchestrator/async_orch2.py
      1 helao/hexagon/adapters/native/artifact_store.py
      1 helao/hexagon/adapters/native/data_file.py
      1 helao/hexagon/adapters/native/data_stream.py
      1 helao/hexagon/adapters/native/finalizer.py
      1 helao/hexagon/adapters/native/meta_writer.py
      1 helao/hexagon/app/ingestion.py
      1 helao/hexagon/app/orch_host.py
      1 helao/hexagon/tests/live_group.py
      1 helao/hexagon/tests/test_db_endpoint_surface.py
      1 helao/hexagon/tests/test_db_shim.py
      2 helao/hexagon/tests/test_engine_import_ratchet.py
      7 helao/hexagon/tests/test_factory.py
```
Every non-test hit is a docstring, and each is Task 11's to classify under D-B7b.10: the two orchestrator shims (`deploy/hexagon/.../async_orch2.py:5,12`, of which line 12 "`makeOrchApp` is left in place and still grafts" describes current behaviour and must change; `deploy/hte/.../async_orch2.py:10` is provenance), `ingestion.py:5` (current behaviour, on the spec's list), `orch_host.py:1391` (provenance), and the five `adapters/native/*` module docstrings, which say the graft binds the collaborator "between `Active.__init__` and `myinit()`" (current behaviour through a deleted symbol; not on the spec's known list). The test hits are the new tests' own history notes and assertions, plus `live_group.py:159`, a provenance comment. Any hit outside this list: STOP.

- [ ] **Step 8.14: No private deployment reads a name this task deletes.** Counts only; the directory names are not written anywhere.

```
for d in "$MAIN"/helao/deploy/*/; do n=$(basename "$d"); case "$n" in hte|test|hexagon|__pycache__) continue;; esac; [ -d "$d/.git" ] || continue; /usr/bin/grep -rlE 'hexagon_active_graft|_hexagon_active_graft_(startup|shutdown)|makeOrchApp|sync_graft|graft_native_sync|active_graft|graft_hexagon_loop|HexagonGraft|hexagon_graft' "$d" --exclude-dir=notes --exclude-dir=.git --exclude-dir=__pycache__ | wc -l; done
```
Expected (measured): four lines, each `0`.

- [ ] **Step 8.15: pyright on this task's files, for the commit-2 comparison.** Task 10 runs the combined gate; this records Task 8's share. With the Task 0 `pyrightconfig.json` in place:

```
printf '%s\n' helao/hexagon/app/factory.py helao/hexagon/app/dispatch_loop.py helao/hexagon/adapters/legacy/health.py helao/hexagon/hexconfig.py helao/deploy/hexagon/servers/action/sim_db_server.py helao/hexagon/tests/test_factory.py helao/hexagon/tests/test_db_shim.py helao/hexagon/tests/test_db_endpoint_surface.py helao/hexagon/tests/test_dispatch_loop.py helao/hexagon/tests/test_orch_host_surface.py helao/hexagon/tests/test_vis_hexagon_producer_parity.py helao/hexagon/tests/test_engine_import_ratchet.py helao/hexagon/tests/live_group.py helao/hexagon/tests/test_concurrency_live.py > "$X/t8_pyright_files.txt"
cd "$WT" && xargs -a "$X/t8_pyright_files.txt" timeout 600 pyright --outputjson > "$X/t8_pyright.json"; echo rc=$?
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -c "import json; d = json.load(open('$X/t8_pyright.json')); print(d['summary']['filesAnalyzed'], d['summary']['errorCount'])"
```
Expected (measured): `rc=123` (xargs reports pyright's non-zero exit as 123), then `14 3`. All three errors are pre-existing, in `test_orch_host_surface.py` (lines 80, 83, 84, inside `_legacy_orch_api_routes`, which Task 12 deletes); the same 13 files had 3 errors on `64f2cf15` (the new test file adds none). If `filesAnalyzed` is not 14, the run is vacuous: STOP.

**Files for the controller's commit:**
- modified: `helao/hexagon/app/factory.py`, `helao/hexagon/app/dispatch_loop.py`, `helao/hexagon/adapters/legacy/health.py`, `helao/hexagon/hexconfig.py`, `helao/deploy/hexagon/servers/action/sim_db_server.py`, `helao/hexagon/tests/test_db_shim.py`, `helao/hexagon/tests/test_dispatch_loop.py`, `helao/hexagon/tests/test_factory.py`, `helao/hexagon/tests/test_orch_host_surface.py`, `helao/hexagon/tests/test_vis_hexagon_producer_parity.py`, `helao/hexagon/tests/test_engine_import_ratchet.py`, `helao/hexagon/tests/live_group.py`, `helao/hexagon/tests/test_concurrency_live.py`
- added: `helao/hexagon/tests/test_db_endpoint_surface.py`
- deleted: `helao/hexagon/app/active_graft.py`, `helao/hexagon/app/sync_graft.py`, `helao/hexagon/tests/test_active_graft.py`, `helao/hexagon/tests/test_sync_graft.py`
- black: every modified or added `.py` above (none is in `pyproject.toml`'s `force-exclude`); measured black-stable as written.
- Commit-2 check items this task supplies to Task 10: the six `live_group` users are `test_live_group`, `test_concurrency_live`, `test_no_wait_overlap_live`, `test_stop_requeues_pending_action_live`, `test_estop_reaches_drivers_live`, `test_orch_legacy_parity_live` (not run by this task; they bind 8101/8102/8110 and must not share a run with another live suite).

---

### Task 9: `harness/ws_frames`'s `orch_api` family encodes through `OrchHost`'s own publishers (D-B7b.4)

**Files:**
- Modify: `helao/hexagon/app/orch_host.py` — imports (l.38–41), `__all__` (l.59), new module-level `orch_ws_publishers` after `__all__`, publisher block inside `_register_orch_ws_routes` (l.1353–1359; the method spans l.1324–1384 on `64f2cf15`).
- Modify: `harness/ws_frames.py` — module docstring (l.1–43), engine import (l.88), `FakeWebSocket` docstring (l.184–186), `_FakeBase` (l.201–208, deleted), `encode_orch_api` (l.271–309, replaced).
- Create (scratch, not committed): `$X/t9_ws_frames_legacy.py`, `$X/t9_ws_bytes.py`, `$X/t9_ws_weight.py`.

**Interfaces:**
- Consumes: nothing from earlier tasks. The legacy `helao/core/servers/base_status.py` must still exist (it does until Task 12); Step 9.4 is the last point at which it can be run.
- Produces:
  - `helao.hexagon.app.orch_host.orch_ws_publishers(status_q: MultisubscriberQueue, data_q: MultisubscriberQueue, live_q: MultisubscriberQueue) -> tuple[WsPublisher, WsPublisher, WsPublisher]` — `(status, data, live)`; status and data use `lambda m: m.as_dict()`, live the identity default. Exported in `orch_host.__all__`.
  - `OrchHost.status_publisher` / `.data_publisher` / `.live_publisher` unchanged in name and behaviour (they are now the tuple `orch_ws_publishers` returns).
  - `harness.ws_frames` public surface unchanged: `__all__`, `CHANNELS`, `FAMILIES == ("base_api", "orch_api")`, `PRODUCERS`, every `build_*_payload`, every sentinel constant, `encode_base_api`, `encode_orch_api(channel, payload=None) -> bytes`, `encode_hexagon`, `frame`, `roundtrip`, `replay_server`, `decode_via_*`. Removed (private, no reader outside the file, grep-checked in the parent and every private deployment): `_FakeBase`, the module-level `StatusBroadcaster` name.

**Execution:** Runs after Task 8, not beside it: Task 8's Step 8.12 temporarily mutates `orch_host.py` and restores it with a `git diff --quiet` check, which this task's edits would break. The file sets are otherwise disjoint. Must not touch `test_engine_import_ratchet.py`. After Task 8 the ratchet's static test fails on exactly `harness/ws_frames.py:88`; this task removes that import, and Task 10 runs the ratchet after both tasks. Do not commit.

- [ ] **Step 9.1: Save the pre-B7b harness for the byte comparison.**

```
mkdir -p "$X"
git -C "$WT" show 64f2cf15:harness/ws_frames.py > "$X/t9_ws_frames_legacy.py"
grep -c 'from helao.core.servers.base_status import StatusBroadcaster' "$X/t9_ws_frames_legacy.py"
```
Expected: `1`.

- [ ] **Step 9.2: Add `orch_ws_publishers` to `orch_host.py` and build the routes' publishers with it.**

Edit 1 — imports. Old:
```python
from helao.helpers.server_keys import resolve_sync_server_key
from helao.helpers.zdeque import zdeque
```
New:
```python
from helao.helpers.server_keys import resolve_sync_server_key
from helao.helpers.ws_utils import WsPublisher
from helao.helpers.zdeque import zdeque
```

Edit 2 — `__all__` and the new function. Old:
```python
__all__ = ["OrchHost"]
```
New:
```python
__all__ = ["OrchHost", "orch_ws_publishers"]


def orch_ws_publishers(
    status_q: MultisubscriberQueue,
    data_q: MultisubscriberQueue,
    live_q: MultisubscriberQueue,
) -> tuple[WsPublisher, WsPublisher, WsPublisher]:
    """The ORCH family's three WS publishers, in ``(status, data, live)`` order.

    Status and data pickle ``msg.as_dict()``; the live buffer is dict-native
    and is pickled as-is. ``OrchHost._register_orch_ws_routes`` serves its
    routes from these, and ``harness.ws_frames.encode_orch_api`` encodes the
    ``orch_api`` fixture family through the same function, so the harness
    cannot drift from the host.
    """
    return (
        WsPublisher(status_q, lambda m: m.as_dict()),
        WsPublisher(data_q, lambda m: m.as_dict()),
        WsPublisher(live_q),
    )
```

Edit 3 — inside `_register_orch_ws_routes`. Old:
```python
        from fastapi import WebSocketDisconnect

        from helao.helpers.ws_utils import WsPublisher

        # as_dict for status and data; the live buffer is dict-native and
        # legacy passes use_as_dict=False for it.
        self.status_publisher = WsPublisher(self.status_q, lambda m: m.as_dict())
        self.data_publisher = WsPublisher(self.data_q, lambda m: m.as_dict())
        self.live_publisher = WsPublisher(self.live_q)
```
New:
```python
        from fastapi import WebSocketDisconnect

        (
            self.status_publisher,
            self.data_publisher,
            self.live_publisher,
        ) = orch_ws_publishers(self.status_q, self.data_q, self.live_q)
```

The inner `_stream(publisher: WsPublisher, ...)` annotation now resolves to the module-level import.

Edit 4 — the method's docstring, which describes the ORCH family through the engine relay this task stops using (D-B7b.10; Task 12's classification leaves this docstring to this task). Old:
```python
        This is the one family difference no surface gate can see:
        WebSockets do not appear in ``openapi.json`` at all, so the 74-route
        diff that covers every parameter schema says nothing here.

        The two families genuinely differ on the wire. ``base_api`` streams
        through ``WsPublisher``, whose default ``xform_func`` is the
        IDENTITY -- it pickles the model object. ``orch_api`` streams
        through ``Base._ws_relay``, which pickles ``msg.as_dict()`` for
        status and data, and the raw message for the live buffer
        (``use_as_dict=False``). So on ``/ws_status`` the action family
        delivers an ``ActionModel`` and the orchestrator a plain dict.
```
New:
```python
        This is the one family difference no surface gate can see:
        WebSockets do not appear in ``openapi.json`` at all, so the route
        diff that covers every parameter schema says nothing here.

        The two families genuinely differ on the wire. ``base_api`` streams
        through ``WsPublisher``, whose default ``xform_func`` is the
        IDENTITY -- it pickles the model object. ``orch_api`` streams
        through the publishers :func:`orch_ws_publishers` builds, which
        pickle ``msg.as_dict()`` for status and data, and the raw message for
        the live buffer -- the bytes the legacy ``Base._ws_relay`` sent,
        compared byte for byte by B7b. So on ``/ws_status`` the action family
        delivers an ``ActionModel`` and the orchestrator a plain dict.
```

- [ ] **Step 9.3: Re-point `encode_orch_api` and drop the engine from `harness/ws_frames.py`.**

Edit 1 — replace the module docstring (lines 1–43, from the opening `"""Canonical wire frames` through the closing `"""` before `from __future__ import annotations`) with:
```python
"""Canonical wire frames for HELAO's two WS producer families (P7-UI, P7b).

Six WS routes, two producer families, different payload types under the same
route names (measured, see docs/superpowers/plans/2026-08-05-P7-UI-both-stacks.md
§P7b):

- ``base_api`` family: every action server (``ActionHost._register_websockets``)
  serves ``/ws_status`` / ``/ws_data`` / ``/ws_live`` over
  ``WsPublisher.broadcast`` with the identity ``xform_func``, which pickles
  the message object as-is -- status carries an ``ActionModel``, data a
  ``DataPackageModel``, live a plain dict.
- ``orch_api`` family: the orchestrator (``OrchHost._register_orch_ws_routes``)
  replaces those three routes with the publishers
  :func:`~helao.hexagon.app.orch_host.orch_ws_publishers` builds, which call
  ``msg.as_dict()`` before pickling for status/data (live stays a dict
  either way).

The family names are the legacy hosts' (``BaseAPI`` and its sibling
``OrchAPI``). Both were deleted by B7b; before that, B7b compared the
``orch_api`` encoder here byte for byte against the legacy
``StatusBroadcaster._ws_relay`` on all three channels.

A third *producer* -- not a third encoder family -- is
:func:`encode_hexagon`: the hexagon composition's own publish path,
``DispatcherStatusAdapter.publish_*`` -> ``WsPublishBridge`` -> the host's
fan-out queue -> the same ``WsPublisher.broadcast``. It is deliberately NOT a
member of :data:`FAMILIES`, because it introduces no encoder of its own: the
whole point of the bridge (``adapters/native/ws_publish.py``) is that frame
bytes keep coming off the ``base_api`` family's encoder. What it does
introduce is a *dict-typed port boundary* -- ``StatusPort.publish_*`` takes
dicts, and the bridge ``model_validate``s each one back to its channel's wire
type -- so a frame produced this way has passed through one extra
lossy-looking hop that the direct path does not have. :data:`PRODUCERS` is
the full set every :func:`frame` caller may name.

Frames here are produced by driving the REAL production coroutine --
``WsPublisher.broadcast``, with the ``xform_func`` each host installs --
against a :class:`FakeWebSocket` that only fakes the transport
(``accept``/``send_bytes``); the ``pyzstd.compress(pickle.dumps(...))`` (or
``msg.as_dict()`` then the same) encode step is the actual production code
path, not a hand-rolled copy (the dd31c36f trap this repo has hit before,
see ``helao/hexagon/tests/test_ws_publish_bridge.py``). Decoding is likewise
driven through the real :class:`~helao.helpers.ws_utils.WsSubscriber` /
:class:`~helao.helpers.ws_utils.WsSyncClient`, via a tiny replay server
(:func:`replay_server`) that serves pre-computed frame bytes over an actual
WebSocket connection -- the only way to exercise those classes' real
``pickle.loads(pyzstd.decompress(...))`` decode step without copying it.
"""
```

Edit 2 — delete this line (l.88), and nothing else in the import block (`MultisubscriberQueue` stays: `_drain_one`, `encode_base_api`, `encode_orch_api` and `encode_hexagon` use it):
```python
from helao.core.servers.base_status import StatusBroadcaster
```

Edit 3 — `FakeWebSocket` docstring. Old:
```python
    Not a network socket -- it exists so :class:`WsPublisher.broadcast` and
    :class:`StatusBroadcaster`'s relay methods can run to completion and
    perform their real ``pyzstd.compress(pickle.dumps(...))`` encode step
    against something matching the tiny subset of the FastAPI ``WebSocket``
```
New:
```python
    Not a network socket -- it exists so :class:`WsPublisher.broadcast` can
    run to completion and perform its real
    ``pyzstd.compress(pickle.dumps(...))`` encode step
    against something matching the tiny subset of the FastAPI ``WebSocket``
```

Edit 4 — delete the whole `_FakeBase` class (from `class _FakeBase:` through `self.live_q = MultisubscriberQueue()`) and one of the two blank-line pairs around it, so `FakeWebSocket` and `_drain_one` stay separated by exactly two blank lines.

Edit 5 — replace the whole `encode_orch_api` function (from `async def encode_orch_api(` through its `return await _drain_one(queue, relay_coro, payload)`) with:
```python
async def encode_orch_api(channel: str, payload: Any = None) -> bytes:
    """Encode one frame through the orchestrator's own WS publishers.

    Drives ``publisher.broadcast`` for the publisher
    :func:`~helao.hexagon.app.orch_host.orch_ws_publishers` builds for
    ``channel`` -- the same function ``OrchHost`` serves ``/ws_status``,
    ``/ws_data`` and ``/ws_live`` from.

    Args:
        channel: One of :data:`CHANNELS`.
        payload: Override payload; defaults to the canonical fixture for
            ``channel``.

    Returns:
        The exact bytes the orchestrator would send over the wire
        (``msg.as_dict()`` for status/data, the dict as-is for live).
    """
    if channel not in CHANNELS:
        raise ValueError(f"unknown channel {channel!r}")
    # Imported here so importing this harness does not load the orchestrator.
    from helao.hexagon.app.orch_host import orch_ws_publishers

    if payload is None:
        payload = _PAYLOAD_BUILDERS[channel]()
    queue = MultisubscriberQueue()
    publisher = orch_ws_publishers(queue, queue, queue)[CHANNELS.index(channel)]
    return await _drain_one(queue, publisher.broadcast, payload)
```
One queue serves all three slots, as `encode_hexagon` already does: only `channel`'s publisher is driven. `CHANNELS` is `("ws_status", "ws_data", "ws_live")`, the same order as the tuple.

Then:
```
grep -n 'StatusBroadcaster\|_FakeBase\|helao.core.servers' "$WT/harness/ws_frames.py"
black --check "$WT/harness/ws_frames.py" "$WT/helao/hexagon/app/orch_host.py"
```
Expected: exactly one grep line, the provenance sentence in the new docstring:
```
21:``StatusBroadcaster._ws_relay`` on all three channels.
```
then `All done!` / `2 files would be left unchanged.`

- [ ] **Step 9.4: The last legacy anchor for the `orch_api` family: byte comparison against `StatusBroadcaster._ws_relay`, all three channels (engine still present).**

Create `$X/t9_ws_bytes.py`:
```python
"""B7b Task 9: the new orch_api encoder emits the legacy relay's exact bytes.

Usage: python t9_ws_bytes.py <path to ws_frames.py as of 64f2cf15>

Loads the pre-B7b harness (whose encode_orch_api drives the legacy
StatusBroadcaster._ws_relay) beside the current harness.ws_frames (which
drives OrchHost's orch_ws_publishers), feeds both the SAME payload object
per channel in one process, and requires byte equality. Exit 0 only if
all three channels match and the legacy module really was the relay path.
"""

import asyncio
import importlib.util
import sys

import harness.ws_frames as new

spec = importlib.util.spec_from_file_location("ws_frames_legacy", sys.argv[1])
old = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)
assert hasattr(old, "StatusBroadcaster"), "old harness is not the legacy relay path"
assert not hasattr(new, "StatusBroadcaster"), "new harness still imports the engine"


async def main() -> int:
    bad = 0
    for channel in new.CHANNELS:
        payload = new._PAYLOAD_BUILDERS[channel]()
        a = await old.encode_orch_api(channel, payload)
        b = await new.encode_orch_api(channel, payload)
        same = a == b
        bad += not same
        print(f"{channel}: legacy={len(a)}B native={len(b)}B identical={same}")
    # Non-vacuity: the comparison can fail. The action family pickles the
    # ActionModel object itself, so its status frame must differ.
    payload = new._PAYLOAD_BUILDERS["ws_status"]()
    control = await new.encode_base_api("ws_status", payload)
    differs = control != await old.encode_orch_api("ws_status", payload)
    print(f"control: base_api ws_status differs from legacy orch_api = {differs}")
    return bad + (not differs)


bad = asyncio.run(main())
print("ORCH-API BYTES IDENTICAL" if not bad else f"ORCH-API BYTES DIFFER on {bad}")
sys.exit(1 if bad else 0)
```

The payload object is built once per channel and handed to both encoders, because `ws_frames.ACTION_UUID` is `uuid4()` at import and `build_data_payload` draws a fresh `uuid4()` file key per call, so two separately built payloads never share bytes.

```
timeout 300 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t9_ws_bytes.py" "$X/t9_ws_frames_legacy.py" > "$X/t9_ws_bytes.txt" 2>/dev/null; echo rc=$?
cat "$X/t9_ws_bytes.txt"
```
Expected `rc=0`, then (byte counts for `ws_data` vary by a few bytes between runs with the random file uuid, measured 255 and 257; the other two are fixed):
```
ws_status: legacy=618B native=618B identical=True
ws_data: legacy=255B native=255B identical=True
ws_live: legacy=77B native=77B identical=True
control: base_api ws_status differs from legacy orch_api = True
ORCH-API BYTES IDENTICAL
```
Keep `$X/t9_ws_bytes.txt`: it is the PR's evidence that the `orch_api` family is unchanged on the wire. After this commit, `test_vis_hexagon_producer_parity`'s orch-versus-hexagon checks compare native with native, and `test_ws_frames` / `test_status_consumer_faces` pin decoded shape, not bytes (no frozen frame bytes are committed; spec D-B7b.4). Any `identical=False` stops the task: report the output, do not change the encoder to match.

- [ ] **Step 9.5: Import weight (spec §9) and no engine at encode time.**

Create `$X/t9_ws_weight.py`:
```python
"""B7b Task 9: importing harness.ws_frames stays light; encoding loads no engine."""

import asyncio
import sys

import harness.ws_frames as wf

print("orch_host after import:", "helao.hexagon.app.orch_host" in sys.modules)
for channel in wf.CHANNELS:
    asyncio.run(wf.encode_orch_api(channel))
print("orch_host after encode:", "helao.hexagon.app.orch_host" in sys.modules)
engine = sorted(m for m in sys.modules if m.startswith("helao.core.servers"))
print("engine modules after encode:", engine)
sys.exit(0 if not engine else 1)
```
```
timeout 300 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t9_ws_weight.py" 2>/dev/null; echo rc=$?
```
Expected:
```
orch_host after import: False
orch_host after encode: True
engine modules after encode: []
rc=0
```
(Measured falsifiable: on the unmodified `64f2cf15` tree the same script prints `orch_host after encode: False` and `engine modules after encode: ['helao.core.servers', 'helao.core.servers.base_status']`, rc=1.)

- [ ] **Step 9.6: The `orch_api`/`base_api` consumers pass.**

Run each file in its own process:
```
for f in helao/hexagon/tests/test_ws_frames.py helao/hexagon/tests/test_ws_consumer_parity.py helao/hexagon/tests/test_status_consumer_faces.py helao/hexagon/tests/test_vis_hexagon_producer_parity.py helao/hexagon/tests/test_orch_host_surface.py helao/deploy/hte/tests/test_vis_ws_parity.py helao/deploy/test/tests/test_vis_ws_parity.py; do echo "== $f"; timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -m pytest -q -p no:cacheprovider --color=no "$f" 2>&1 | tail -1; done
```
Expected, measured on `64f2cf15` + this task alone:
```
== helao/hexagon/tests/test_ws_frames.py
14 passed
== helao/hexagon/tests/test_ws_consumer_parity.py
5 passed
== helao/hexagon/tests/test_status_consumer_faces.py
11 passed
== helao/hexagon/tests/test_vis_hexagon_producer_parity.py
16 passed
== helao/hexagon/tests/test_orch_host_surface.py
11 passed
== helao/deploy/hte/tests/test_vis_ws_parity.py
11 passed
== helao/deploy/test/tests/test_vis_ws_parity.py
7 passed
```
(each line followed by `, N warnings in …s`). `test_orch_host_surface.py` includes `test_the_ws_routes_use_the_ORCH_family_encoding_not_the_action_one`, which still passes because the `as_dict` lambda lives in each publisher's `xform_func`. Task 8 has already landed in the tree, so these are the counts measured with Task 8 and this task applied together: Task 8 ports one test in `test_vis_hexagon_producer_parity.py` and deletes one and adds one in `test_orch_host_surface.py`, which leaves both counts unchanged. The requirement is 0 failed. The one private-deployment test that imports `harness.ws_frames` (base_api family only) was measured green against this change in the planning dry run (1 passed); gate 5 re-runs it against the branch.

- [ ] **Step 9.7: pyright on the two changed files.** `pyrightconfig.json` must be present in `$WT` (Task 0 copies it).
```
cd "$WT" && pyright --outputjson harness/ws_frames.py helao/hexagon/app/orch_host.py > "$X/t9_pyright.json"; echo rc=$?
timeout 60 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -c "import json; s = json.load(open('$X/t9_pyright.json'))['summary']; print(s['filesAnalyzed'], s['errorCount'])"
```
Expected: `rc=1`, then `2 13` — the same count as Task 0 records for these two files on `64f2cf15` (all 13 are pre-existing in `orch_host.py`, now 21 lines lower; `ws_frames.py` has 0 before and after). If `filesAnalyzed` is not 2, the run is vacuous: STOP.

**Files for the controller's commit:**
- `helao/hexagon/app/orch_host.py` (modified)
- `harness/ws_frames.py` (modified)

---

### Task 10: Commit 2 closes — the commit-2 check and the controller commit

**Files:** none edited. Scratch: `$X/run_tests_c2.txt`, `$X/F2.txt`, `$X/t10_live.txt`.

**Interfaces:**
- Consumes: Tasks 8 and 9 complete; Task 9's `$X/t9_ws_bytes.txt`; Task 0's `F0.txt`, `t0_failset.sh`.
- Produces: commit 2.

**Execution:** runs alone, after Task 9. Step 10.6 is the controller's.

- [ ] **Step 10.1: The ratchet is green in both halves, with the factory case.**
```
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -m pytest -q -p no:cacheprovider --color=no helao/hexagon/tests/test_engine_import_ratchet.py 2>&1 | tail -1
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t8_probe.py" 2>/dev/null | tail -1
grep -c 'ORCH-API BYTES IDENTICAL' "$X/t9_ws_bytes.txt"
```
Expected: `6 passed …`; `0 ['ActionHost', 'OrchHost', 'makeActionApp']`; `1` (the last legacy anchor for the `orch_api` family, recorded while the engine was present).

- [ ] **Step 10.2: Every §5.3 file and every `ws_frames` consumer passes, one process each.**
```
for f in helao/hexagon/tests/test_factory.py helao/hexagon/tests/test_db_shim.py helao/hexagon/tests/test_db_endpoint_surface.py helao/hexagon/tests/test_dispatch_loop.py helao/hexagon/tests/test_orch_host_surface.py helao/hexagon/tests/test_vis_hexagon_producer_parity.py helao/hexagon/tests/test_adapter_health.py helao/hexagon/tests/test_hte_is_native.py helao/hexagon/tests/test_test_deployment_is_native.py helao/hexagon/tests/test_db_gate_config.py helao/hexagon/tests/test_ws_frames.py helao/hexagon/tests/test_ws_consumer_parity.py helao/hexagon/tests/test_status_consumer_faces.py helao/deploy/hte/tests/test_vis_ws_parity.py helao/deploy/test/tests/test_vis_ws_parity.py; do echo "$f :: $(timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -m pytest -q -p no:cacheprovider --color=no "$f" 2>&1 | grep -oE '^[0-9]+ (passed|failed).*' | cut -d, -f1)"; done
```
Expected (measured in the planning dry runs of Tasks 8 and 9):
```
helao/hexagon/tests/test_factory.py :: 17 passed
helao/hexagon/tests/test_db_shim.py :: 1 passed
helao/hexagon/tests/test_db_endpoint_surface.py :: 4 passed
helao/hexagon/tests/test_dispatch_loop.py :: 4 passed
helao/hexagon/tests/test_orch_host_surface.py :: 11 passed
helao/hexagon/tests/test_vis_hexagon_producer_parity.py :: 16 passed
helao/hexagon/tests/test_adapter_health.py :: 5 passed
helao/hexagon/tests/test_hte_is_native.py :: 8 passed
helao/hexagon/tests/test_test_deployment_is_native.py :: 3 passed
helao/hexagon/tests/test_db_gate_config.py :: 9 passed
helao/hexagon/tests/test_ws_frames.py :: 14 passed
helao/hexagon/tests/test_ws_consumer_parity.py :: 5 passed
helao/hexagon/tests/test_status_consumer_faces.py :: 11 passed
helao/deploy/hte/tests/test_vis_ws_parity.py :: 11 passed
helao/deploy/test/tests/test_vis_ws_parity.py :: 7 passed
```

- [ ] **Step 10.3: `live_group`'s six users pass (the only Linux coverage of `makeActionApp` under uvicorn, §2.3).** They bind 8101/8102/8110 and their RPC siblings, so run them one at a time and nothing else meanwhile.
```
timeout 60 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python helao/hexagon/tests/smoke/wait_ports_free.py --timeout 10 8101 8102 8110; echo ports rc=$?
```
Create `$X/t10_live.sh`:
```bash
#!/bin/bash
# B7b Task 10: the six live_group users, one pytest process each, sequentially.
WT=/mnt/STORAGE/repos/helao/helao-b7b
for f in test_live_group test_concurrency_live test_no_wait_overlap_live test_stop_requeues_pending_action_live test_estop_reaches_drivers_live test_orch_legacy_parity_live; do
  echo "$f :: $(timeout 900 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -m pytest -q -p no:cacheprovider --color=no "helao/hexagon/tests/$f.py" 2>&1 | grep -oE '^[0-9]+ (passed|failed).*' | cut -d, -f1)"
done
```
**[background]** Launch:
```
chmod +x "$X/t10_live.sh"; "$X/bg.sh" t10_live "$X/t10_live.sh"
```
Then, **[tool timeout 600 s]**:
```
"$X/wait.sh" t10_live
cat "$X/t10_live.txt"
```
Expected: `ports rc=0`; `rc=0` from `wait.sh`; then exactly (the same counts the F0 sweep records for these files on `64f2cf15`, measured in planning):
```
test_live_group :: 1 passed
test_concurrency_live :: 6 passed
test_no_wait_overlap_live :: 1 passed
test_stop_requeues_pending_action_live :: 1 passed
test_estop_reaches_drivers_live :: 2 passed
test_orch_legacy_parity_live :: 2 passed
```

- [ ] **Step 10.4: The golden masters and `run_unit_tests.py` are untouched by commit 2.**
```
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python helao/core/tests/test_orch_dispatch_golden_master.py --check 2>/dev/null | tail -1
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python helao/core/tests/test_active_golden_master.py --check 2>/dev/null | tail -1
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python run_unit_tests.py 2>&1 | tail -1
```
Expected: the two `CHECK PASSED` lines of Step 7.4, and `overall: PASS`.

- [ ] **Step 10.5: Guard, full sweep against F0, and the tree.**
```
timeout 120 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -c "import helao; print(helao.__file__)"
```
**[background]** Launch:
```
"$X/bg.sh" run_tests_c2 timeout 5400 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python run_tests.py
```
Then, **[tool timeout 600 s]**, repeating while it prints `STILL-RUNNING`:
```
"$X/wait.sh" run_tests_c2
"$X/t0_failset.sh" "$X/run_tests_c2.txt" "$X/F2.txt" > /dev/null
comm -13 "$X/F0.txt" "$X/F2.txt"; echo new-failures-listed-above
git -C "$WT" status --short | LC_ALL=C sort
```
Expected: the worktree path; `rc=1`; nothing before `new-failures-listed-above` (the four deleted test files simply drop out of the sweep); then exactly:
```
 D helao/hexagon/app/active_graft.py
 D helao/hexagon/app/sync_graft.py
 D helao/hexagon/tests/test_active_graft.py
 D helao/hexagon/tests/test_sync_graft.py
 M harness/ws_frames.py
 M helao/deploy/hexagon/servers/action/sim_db_server.py
 M helao/hexagon/adapters/legacy/health.py
 M helao/hexagon/app/dispatch_loop.py
 M helao/hexagon/app/factory.py
 M helao/hexagon/app/orch_host.py
 M helao/hexagon/hexconfig.py
 M helao/hexagon/tests/live_group.py
 M helao/hexagon/tests/test_concurrency_live.py
 M helao/hexagon/tests/test_db_shim.py
 M helao/hexagon/tests/test_dispatch_loop.py
 M helao/hexagon/tests/test_engine_import_ratchet.py
 M helao/hexagon/tests/test_factory.py
 M helao/hexagon/tests/test_orch_host_surface.py
 M helao/hexagon/tests/test_vis_hexagon_producer_parity.py
?? helao/hexagon/tests/test_db_endpoint_surface.py
```

- [ ] **Step 10.6: Controller commits (commit 2).**
```
cd "$WT" && conda run -n helao --no-capture-output --cwd "$WT" black harness/ws_frames.py helao/deploy/hexagon/servers/action/sim_db_server.py helao/hexagon/adapters/legacy/health.py helao/hexagon/app/dispatch_loop.py helao/hexagon/app/factory.py helao/hexagon/app/orch_host.py helao/hexagon/hexconfig.py helao/hexagon/tests/live_group.py helao/hexagon/tests/test_concurrency_live.py helao/hexagon/tests/test_db_shim.py helao/hexagon/tests/test_dispatch_loop.py helao/hexagon/tests/test_engine_import_ratchet.py helao/hexagon/tests/test_factory.py helao/hexagon/tests/test_orch_host_surface.py helao/hexagon/tests/test_vis_hexagon_producer_parity.py helao/hexagon/tests/test_db_endpoint_surface.py
git -C "$WT" add -A -- helao/hexagon/app/active_graft.py helao/hexagon/app/sync_graft.py helao/hexagon/tests/test_active_graft.py helao/hexagon/tests/test_sync_graft.py harness/ws_frames.py helao/deploy/hexagon/servers/action/sim_db_server.py helao/hexagon/adapters/legacy/health.py helao/hexagon/app/dispatch_loop.py helao/hexagon/app/factory.py helao/hexagon/app/orch_host.py helao/hexagon/hexconfig.py helao/hexagon/tests/live_group.py helao/hexagon/tests/test_concurrency_live.py helao/hexagon/tests/test_db_shim.py helao/hexagon/tests/test_dispatch_loop.py helao/hexagon/tests/test_engine_import_ratchet.py helao/hexagon/tests/test_factory.py helao/hexagon/tests/test_orch_host_surface.py helao/hexagon/tests/test_vis_hexagon_producer_parity.py helao/hexagon/tests/test_db_endpoint_surface.py
git -C "$WT" status --short
git -C "$WT" commit -F - <<'EOF'
refactor(b7b): makeActionApp accepts native hosts only; delete the graft machinery

Commit 2 of B7b (spec section 4.2, D-B7b.2-4):

- makeActionApp no longer imports active_graft; a module whose makeApp does
  not return an ActionHost is refused at build time with a TypeError naming
  it. Startup hook renamed _hexagon_ws_bridge_startup. The startup log line
  "native ActionHost, skipping the active write graft" is gone with the
  branch it reported.
- deleted: makeOrchApp, HexagonGraft/graft_hexagon_loop, active_graft.py,
  sync_graft.py; the hexagon sim_db_server shim is a plain delegate
- harness/ws_frames encodes the orch_api family through OrchHost's own
  orch_ws_publishers; byte-identical to the legacy StatusBroadcaster relay on
  all three channels (the last legacy anchor for that family)
- engine-import ratchet: allowlist emptied; the native probe now also builds
  a makeActionApp composition (12 engine modules before, 0 after)
- graft tests deleted or moved: DB endpoint surface and S3 recorder pins now
  in test_db_endpoint_surface.py; OrchHost health binding pinned in
  test_orch_host_surface

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01NxxPoGvJmVh5T4xSpVejFF
EOF
git -C "$WT" status --short; git -C "$WT" log --oneline -1
```
Expected: black leaves all 16 files unchanged; after `add`, 20 staged lines and nothing else; after the commit, no status output.

---

### Task 11: The traps doc moves, root `CLAUDE.md` names the native hosts, and stale references are fixed (D-B7b.8, D-B7b.10)

**Plan decisions (spec silent or self-contradictory; defaults):**

- **P-I.1 (default; the spec contradicts itself).** D-B7b.10 lists `deploy/hte/servers/orchestrator/async_orch2.py:10` as "known to change". Measured, that line is past-tense provenance ("B5: this used to build a legacy ``OrchAPI``, which constructed an ``Orch`` and let ``makeOrchApp`` graft the hexagon reducer over it"), which is the rule's own example of what to leave. It is also a deployment server module, and §10 rules those out. **Default: leave it.** Every hit in the rest of that docstring is past tense too.
- **P-I.2 (default; the spec is silent).** The rule is applied to every tracked non-test `.py` hit, drivers and runners included. The exception is deployment *server* modules under `helao/deploy/{hte,test}/servers/`, because of §10. Those 12 hits are stale, for example the test sims' "Wires X into a :class:`BaseAPI`". They are listed in the table as "leave: deployment server module (spec §10); stale, listed for B7c", and are not edited. The hte **driver** hits (19, in 13 files) and the test **runner** hits (3) are fixed, because §10 does not cover drivers or runners. Every claim was checked against `ActionHost`: `/estop` + `estop_actives` (`action_host.py:819, 1222`); `shutdown()` calling `driver.shutdown`/`async_shutdown` through `getattr` (`action_host.py:1329–1370`); the poller built with `server_cfg.get("polling_time", 0.1)` (`action_host.py:1297`); no `.connect()` call anywhere in `action_host.py`; `self.poller._base_hook = self` (`action_host.py:1301`); `class OrchHost(ActionHost)` (`orch_host.py:62`).
- **P-I.3 (default; the spec is silent).** A sentence that is not itself a grep hit is fixed together with the hit when it states the same stale claim. There are three cases: the three "source-parity-pinned by ``test_native_*.py``" sentences (their pins die in Task 12), `adapters/legacy/status.py:11–12` ("Orch compositions … stay on legacy Base relays"), and `ports/status.py:14` (``_ws_relay``).
- **P-I.4 (default; the spec is silent).** Two CLAUDE.md lines outside D-B7b.8's list are fixed. `helao/deploy/hte/drivers/spec/andor/CLAUDE.md:35` says "`base_api` names the driver namedtuple field"; today `ActionHost` does, at `action_host.py:1286`. And root `CLAUDE.md:81`'s "can host a Bokeh operator page (`enable_op: true` …)" is corrected while that line is being rewritten anyway, because `config_loader.py:188` documents `enable_op` as deprecated and ignored. No other tracked CLAUDE.md names an engine path, apart from the two files this task edits.
- **P-I.5 (default; the spec is silent).** `orch_host.py:1331–1335` (the `_register_orch_ws_routes` docstring: "``orch_api`` streams through ``Base._ws_relay``") describes the function Task 9 rewrites, so **Task 9 owns that docstring**, not this task. This task does not edit it, and the table marks it that way.
- **P-I.6 (default; coordination).** `ingestion.py`'s docstring is split between two tasks. Task 11 fixes lines 1–6 (the `graft_hexagon_loop` sentence, and the path `helao/core/servers/orch_status_sync.py`, which is wrong: the module lives at `helao/hexagon/app/orch_status_sync.py`). Task 15 fixes lines 22–25 (the globstat and `clear_nonblocking` sentences).
- **P-I.7 (default; ordering).** Task 11 runs **first** in commit 3, before Task 12's `rm -rf helao/core/servers`, because it moves `CLAUDE.md` out of that directory with a plain `mv`.
- **P-I.8 (default; the spec is silent).** Task 15's new route test imports `_host` from `test_orch_host_surface`, which is the existing precedent at `test_orch_queue_roundtrip.py:18`. That gives it a constructed `OrchHost` without binding a port.

**Spec facts re-measured for this task and Task 15:**

| spec claim | measured on `64f2cf15` |
|

**Files:**
- Move (plain `mv`, content intact except line 1): `helao/core/servers/CLAUDE.md` → `helao/hexagon/app/CLAUDE.md`
- Modify: `CLAUDE.md:69, 80, 81, 85`; `helao/deploy/hte/drivers/spec/andor/CLAUDE.md:35`
- Modify (docstrings and comments only, proven by `t11_ast_check.py`): `harness/endpoints.py:11`, `harness/openapi_capture.py:4–5`, `helao/core/drivers/helao_driver.py:166–167`, `helao/core/rpc/zmq_rpc.py:3`, `helao/helpers/dispatcher.py:135`, `helao/helpers/bubble_detection.py:8`, `helao/hexagon/adapters/legacy/status.py:11–12, 67–71`, `helao/hexagon/adapters/native/artifact_store.py:8–12, 50, 52, 91–92`, `helao/hexagon/adapters/native/data_file.py:10–12, 16–19, 66–70`, `helao/hexagon/adapters/native/data_stream.py:12–14, 18–23, 63–67`, `helao/hexagon/adapters/native/finalizer.py:12–14, 21–23, 62–66`, `helao/hexagon/adapters/native/meta_writer.py:8–10, 13–18`, `helao/hexagon/adapters/native/ws_publish.py:4–7`, `helao/hexagon/adapters/native/galil_motion.py:32, 38, 173`, `helao/hexagon/adapters/native/galil_motion_native.py:78`, `helao/hexagon/app/action_host.py:4–5, 29–30, 271, 1024–1025`, `helao/hexagon/app/orch_host.py:572–573`, `helao/hexagon/app/orch_payloads.py:3–8`, `helao/hexagon/app/orch_wait.py:5–6`, `helao/hexagon/app/ingestion.py:1–6`, `helao/hexagon/ports/status.py:14–17`, `helao/ui/shared/operator/orch_backend.py:4–5, 171`, `helao/deploy/hexagon/servers/orchestrator/async_orch2.py:11–14`, and 19 comment/docstring hits in 13 hte driver files and 3 in 2 test-deployment runners (listed in the script)
- Modify (runtime message text): `helao/hexagon/adapters/legacy/status.py:145–163` (three `UnwiredPortError` messages), `helao/hexagon/adapters/native/artifact_store.py:77–80` (one)

**Interfaces:**
- Consumes: the commit-2 tree (Task 10's commit). Nothing from Task 12; this task runs **before** it (P-I.7).
- Produces: `helao/hexagon/app/CLAUDE.md`, which Task 12 must not delete. Task 13's executable-reference sweep sees no new engine import from this task: the proof is that `t11_ast_check.py` reports that only strings changed.

**Execution:** Runs first in commit 3, before Task 12, and sequentially. It touches no file that Task 12 edits except the four native adapters (`data_file`, `data_stream`, `finalizer`, `meta_writer`). Task 12 changes their `pyproject.toml` exclusion and runs black on them, so Task 12 must start after this task finishes. Do not commit.

- [ ] **Step 11.1: Move the traps doc and retitle it.**

```
mkdir -p "$X"
mv "$WT/helao/core/servers/CLAUDE.md" "$WT/helao/hexagon/app/CLAUDE.md"
git -C "$WT" status --short -- helao/core/servers/CLAUDE.md helao/hexagon/app/CLAUDE.md
```
Expected:
```
 D helao/core/servers/CLAUDE.md
?? helao/hexagon/app/CLAUDE.md
```

- [ ] **Step 11.2: Write `$X/t11_claude_md.py`** (exact content):

```python
"""B7b Task 11: retitle the moved traps doc and point the root CLAUDE.md at the native hosts.

Usage: python t11_claude_md.py <repo root>
Run after `mv helao/core/servers/CLAUDE.md helao/hexagon/app/CLAUDE.md`.
Every (path, old, new) must match exactly once; otherwise nothing is written.
"""

import sys
from pathlib import Path

ROOT = Path(sys.argv[1])

EDITS = [
    ("helao/hexagon/app/CLAUDE.md",
     "# helao/core/servers — dispatch loop traps\n",
     "# helao/hexagon/app — dispatch loop and host traps\n"),
    ("CLAUDE.md",
     "- `helao/core/` — framework that doesn't depend on a specific instrument deployment: "
     "base FastAPI/Bokeh server classes (`servers/base.py`, `servers/base_api.py`, "
     "`servers/orch.py`, `servers/vis.py`), pydantic models for "
     "`Action`/`Experiment`/`Sequence`/`Sample`/etc. (`models/`), the abstract driver contract "
     "(`drivers/helao_driver.py` — `HelaoDriver`, `DriverPoller`, `DriverResponse`, "
     "`DriverStatus`), the data syncer (`drivers/data/sync_driver.py`), and the in-process "
     "\"micro-orchestrator\" runners (`runners/`, see `runners/runner.md`).\n",
     "- `helao/core/` — framework that doesn't depend on a specific instrument deployment: "
     "pydantic models for `Action`/`Experiment`/`Sequence`/`Sample`/etc. (`models/`), the "
     "abstract driver contract (`drivers/helao_driver.py` — `HelaoDriver`, `DriverPoller`, "
     "`DriverResponse`, `DriverStatus`), the data syncer (`drivers/data/sync_driver.py`), the "
     "ZeroMQ RPC layer (`rpc/`), the error codes (`error.py`), the finish-hook extension point "
     "(`hooks/`), and the in-process \"micro-orchestrator\" runners (`runners/`, see "
     "`runners/runner.md`). The server hosts are not here: they live in `helao/hexagon/app/` "
     "(`action_host.py`, `orch_host.py`).\n"),
    ("CLAUDE.md",
     "They build on `helao.core.servers.base_api.BaseAPI`, which wires in the `Base` class "
     "from `core/servers/base.py` (status WS, action lifecycle, hlo file output, NTP-synced "
     "clock, etc.).\n",
     "Each module's `makeApp` returns an `ActionHost` (`helao/hexagon/app/action_host.py`), "
     "which is the FastAPI app itself (status WS, action lifecycle, hlo file output, "
     "NTP-synced clock, etc.).\n"),
    ("CLAUDE.md",
     "- **orchestrator servers** (`group: orchestrator`, usually `async_orch2.py`) — extend "
     "`Base` via `core/servers/orch.py`'s `Orch`. They own the sequence/experiment/action "
     "deques, dispatch actions to action servers over HTTP, react to status updates, and can "
     "host a Bokeh \"operator\" page (`enable_op: true`, `bokeh_port: <port>`).\n",
     "- **orchestrator servers** (`group: orchestrator`, usually `async_orch2.py`) — build an "
     "`OrchHost` (`helao/hexagon/app/orch_host.py`), a subclass of `ActionHost`. They own the "
     "sequence/experiment/action deques, dispatch actions to action servers over HTTP, and "
     "react to status updates. The operator UI runs as a separate `group: operator` server "
     "(`enable_op` is deprecated and ignored).\n"),
    ("CLAUDE.md",
     "All four are in `helao/core/servers/CLAUDE.md`; read it before editing `orch.py` or the "
     "dispatch path.\n",
     "All four are in `helao/hexagon/app/CLAUDE.md`; read it before editing `orch_host.py`, "
     "`orch_effects.py` or `orch_dispatch.py`.\n"),
    ("helao/deploy/hte/drivers/spec/andor/CLAUDE.md",
     "- **`base_api` names the driver namedtuple field from the class name**, so\n",
     "- **`ActionHost` names the driver namedtuple field from the class name**, so\n"),
]


def main() -> int:
    texts, bad = {}, []
    for rel, old, new in EDITS:
        text = texts.get(rel)
        if text is None:
            text = (ROOT / rel).read_text(encoding="utf-8")
        n = text.count(old)
        if n != 1:
            bad.append(f"{rel}: expected 1 match, found {n}: {old[:70]!r}")
            continue
        texts[rel] = text.replace(old, new)
    if bad:
        print("\n".join(bad))
        print("NOTHING WRITTEN")
        return 1
    for rel, text in texts.items():
        (ROOT / rel).write_text(text, encoding="utf-8")
    print(f"applied {len(EDITS)} edits to {len(texts)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Apply it, then check that only line 1 of the moved file changed and that root `CLAUDE.md` names no engine path:
```
timeout 120 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t11_claude_md.py" "$WT"
diff <(git -C "$WT" show HEAD:helao/core/servers/CLAUDE.md | tail -n +2) <(tail -n +2 "$WT/helao/hexagon/app/CLAUDE.md") && echo BODY-IDENTICAL
head -1 "$WT/helao/hexagon/app/CLAUDE.md"
grep -c -E 'core/servers|base_api|BaseAPI|orch\.py' "$WT/CLAUDE.md"
```
Expected (measured):
```
applied 6 edits to 3 files
BODY-IDENTICAL
# helao/hexagon/app — dispatch loop and host traps
0
```
The old title line was `# helao/core/servers — dispatch loop traps`. If the script prints `NOTHING WRITTEN`, STOP and report its output: a line it expects has changed since `64f2cf15`.

- [ ] **Step 11.3: Write `$X/t11_stale_refs.py`** (exact content). Every row was classified from the D-B7b.10 grep; the table under Step 11.6 gives the class of every hit.

```python
"""B7b Task 11: fix the stale references D-B7b.10 classifies as "fix".

Usage: python t11_stale_refs.py <repo root>
Every (path, old, new) must match exactly once; otherwise nothing is written.
DOC edits change only comments/docstrings (t11_ast_check.py proves it);
MSG edits change the text of a runtime error message.
"""

import sys
from pathlib import Path

ROOT = Path(sys.argv[1])

DOC = [
    # -- harness --
    ("harness/endpoints.py",
     "routes registered dynamically at runtime (BaseAPI system surface,",
     "routes registered dynamically at runtime (ActionHost system surface,"),
    ("harness/openapi_capture.py",
     "decorators on a module's own functions; it cannot see the routes ``BaseAPI``/\n"
     "``Base`` register at runtime,",
     "decorators on a module's own functions; it cannot see the routes ``ActionHost``/\n"
     "``OrchHost`` register at runtime,"),
    # -- helao/core, helao/helpers --
    ("helao/core/drivers/helao_driver.py",
     "    # the owning Base (set by BaseAPI after construction); Any avoids a\n"
     "    # core->servers import cycle and keeps `await _base_hook.put_lbuf(...)` typed\n",
     "    # the owning host (ActionHost sets it after construction); Any avoids a\n"
     "    # core->hexagon import cycle and keeps `await _base_hook.put_lbuf(...)` typed\n"),
    ("helao/core/rpc/zmq_rpc.py",
     "Each ``BaseAPI`` / ``OrchAPI`` instance binds a ``zmq.ROUTER`` socket on",
     "Each ``HelaoFastAPI`` app (``ActionHost`` / ``OrchHost``) binds a ``zmq.ROUTER`` socket on"),
    ("helao/helpers/dispatcher.py",
     "    :class:`BaseAPI`; the RPC fast path bypasses that middleware and",
     "    :class:`ActionHost`; the RPC fast path bypasses that middleware and"),
    ("helao/helpers/bubble_detection.py",
     "import helao_logging as logging  # get LOGGER from BaseAPI instance",
     "import helao_logging as logging  # LOGGER is set by fast_launcher"),
    # -- helao/hexagon/adapters --
    ("helao/hexagon/adapters/legacy/status.py",
     "binding they raise UnwiredPortError loudly. Orch compositions never bind\n"
     "the bridge — their live WS channels stay on legacy Base relays (Q1).\n",
     "binding they raise UnwiredPortError loudly. ``OrchHost`` never binds the\n"
     "bridge — it publishes its three WS channels through its own\n"
     "``WsPublisher``s (Q1).\n"),
    ("helao/hexagon/adapters/legacy/status.py",
     '        """Late-bind the WS publish bridge (P2b-2 D3): the fan-out queues\n'
     "        live on the legacy Base, which only exists once the app has started,\n"
     "        so makeActionApp's startup hook constructs the bridge and binds it\n"
     "        here (mirror of the P2b-1 NativeArtifactStoreAdapter.bind_base\n"
     '        pattern)."""\n',
     '        """Late-bind the WS publish bridge (P2b-2 D3): the fan-out queues\n'
     "        live on the ``ActionHost`` that ``makeApp`` returns, so\n"
     "        makeActionApp's startup hook constructs the bridge over them and\n"
     '        binds it here."""\n'),
    ("helao/hexagon/adapters/native/artifact_store.py",
     "time — no live ``Base`` exists yet; ``bind_base`` is called by the active\n"
     "graft at startup (the late-binding pattern the status adapter documents for\n"
     "its queues). It is also the composition's collaborator FACTORY:\n"
     "``graft_active_write_path`` obtains the per-Active native collaborators via\n"
     "``collaborators_for`` and the per-Base meta writer via ``meta_writer_for``,\n",
     "time — no live host exists yet; ``bind_base`` late-binds one (only tests\n"
     "call it since B7b deleted the active graft). It is also the composition's\n"
     "collaborator FACTORY: ``ActionSession`` obtains its native collaborators via\n"
     "``collaborators_for`` and ``ActionHost`` its meta writer via\n"
     "``meta_writer_for``,\n"),
    ("helao/hexagon/adapters/native/artifact_store.py",
     "    # --- graft-time binding + collaborator factory ---\n",
     "    # --- late binding + collaborator factory ---\n"),
    ("helao/hexagon/adapters/native/artifact_store.py",
     '        """Late base binding (graft startup); build_wiring has no Base yet."""\n',
     '        """Late base binding; build_wiring has no host yet."""\n'),
    ("helao/hexagon/adapters/native/artifact_store.py",
     "    # --- meta ymls (native bodies, resolved through the bound base's\n"
     "    # meta_writer — the graft has already swapped it native) ---\n",
     "    # --- meta ymls (native bodies, resolved through the bound base's\n"
     "    # meta_writer, which is native) ---\n"),
    ("helao/hexagon/adapters/native/data_file.py",
     "byte-identical to legacy (source-parity-pinned by\n"
     "``test_native_data_file.py``); only this docstring, the class name, and\n"
     "``__all__`` differ.\n",
     "byte-identical to legacy (source-parity-pinned by\n"
     "``test_native_data_file.py`` until B7b deleted the engine); only this\n"
     "docstring, the class name, and ``__all__`` differed.\n"),
    ("helao/hexagon/adapters/native/data_file.py",
     "(cache-nothing rule). Swapped in for ``active.data_file_writer`` by\n"
     "``graft_active_write_path`` between ``Active.__init__`` and ``myinit()``;\n"
     "the ``Active`` delegators (``base.py:1208-1299,1432-1455``) resolve the\n"
     "attribute at call time, so the swap reroutes every file-init/one-shot call.\n",
     "(cache-nothing rule). ``ActionSession`` constructs it as its\n"
     "``data_file_writer`` (``NativeArtifactStoreAdapter.collaborators_for``).\n"),
    ("helao/hexagon/adapters/native/data_file.py",
     "    ``__init__`` parameter: ``__init__`` is byte-pinned against its legacy twin\n"
     "    by ``assert_source_parity`` (see ``native_fixtures``), and an annotation in\n"
     "    the signature would change ``inspect.getsource(__init__)`` and break the\n"
     "    pin. A class-level annotation gives static checking without touching the\n"
     "    pinned method source.\n",
     "    ``__init__`` parameter: until B7b deleted the engine, ``__init__`` was\n"
     "    byte-pinned against its legacy twin, and an annotation in the signature\n"
     "    would have changed ``inspect.getsource(__init__)`` and broken the pin. A\n"
     "    class-level annotation gives static checking without touching the method\n"
     "    source.\n"),
    ("helao/hexagon/adapters/native/data_stream.py",
     "legacy (source-parity-pinned by ``test_native_data_stream.py``); only this\n"
     "docstring, the class name, and ``__all__`` differ.\n",
     "legacy (source-parity-pinned by ``test_native_data_stream.py`` until B7b\n"
     "deleted the engine); only this docstring, the class name, and ``__all__``\n"
     "differed.\n"),
    ("helao/hexagon/adapters/native/data_stream.py",
     "call time (cache-nothing rule -- the ce846da1 failure class). Swapped in for\n"
     "``active.data_stream`` by ``graft_active_write_path`` between\n"
     "``Active.__init__`` and ``myinit()`` -- BEFORE ``myinit`` creates the\n"
     "``data_logger`` task (``base.py:1014``), so the drain loop only ever runs\n"
     "native code. Cross-collaborator hops stay routed through the ``Active``\n",
     "call time (cache-nothing rule -- the ce846da1 failure class).\n"
     "``ActionSession`` constructs it as its ``data_stream``\n"
     "(``NativeArtifactStoreAdapter.collaborators_for``) before the\n"
     "``data_logger`` task exists, so the drain loop only ever runs native code.\n"
     "Cross-collaborator hops stay routed through the session\n"),
    ("helao/hexagon/adapters/native/data_stream.py",
     "    ``__init__`` parameter: ``__init__`` is byte-pinned against its legacy twin\n"
     "    by ``assert_source_parity`` (see ``native_fixtures``), and an annotation in\n"
     "    the signature would change ``inspect.getsource(__init__)`` and break the\n"
     "    pin. A class-level annotation gives static checking without touching the\n"
     "    pinned method source.\n",
     "    ``__init__`` parameter: until B7b deleted the engine, ``__init__`` was\n"
     "    byte-pinned against its legacy twin, and an annotation in the signature\n"
     "    would have changed ``inspect.getsource(__init__)`` and broken the pin. A\n"
     "    class-level annotation gives static checking without touching the method\n"
     "    source.\n"),
    ("helao/hexagon/adapters/native/finalizer.py",
     "(source-parity-pinned by ``test_native_finalizer.py``); only this docstring,\n"
     "the class name, and ``__all__`` differ.\n",
     "(source-parity-pinned by ``test_native_finalizer.py`` until B7b deleted the\n"
     "engine); only this docstring, the class name, and ``__all__`` differed.\n"),
    ("helao/hexagon/adapters/native/finalizer.py",
     "leaked handle -> WinError 32 -> permanent promotion failure). Swapped in for\n"
     "``active.action_finalizer`` by ``graft_active_write_path`` between\n"
     "``Active.__init__`` and ``myinit()``.\n",
     "leaked handle -> WinError 32 -> permanent promotion failure).\n"
     "``ActionSession`` constructs it as its ``action_finalizer``\n"
     "(``NativeArtifactStoreAdapter.collaborators_for``).\n"),
    ("helao/hexagon/adapters/native/finalizer.py",
     "    ``__init__`` parameter: ``__init__`` is byte-pinned against its legacy twin\n"
     "    by ``assert_source_parity`` (see ``native_fixtures``), and an annotation in\n"
     "    the signature would change ``inspect.getsource(__init__)`` and break the\n"
     "    pin. A class-level annotation gives static checking without touching the\n"
     "    pinned method source.\n",
     "    ``__init__`` parameter: until B7b deleted the engine, ``__init__`` was\n"
     "    byte-pinned against its legacy twin, and an annotation in the signature\n"
     "    would have changed ``inspect.getsource(__init__)`` and broken the pin. A\n"
     "    class-level annotation gives static checking without touching the method\n"
     "    source.\n"),
    ("helao/hexagon/adapters/native/meta_writer.py",
     "helpers. Method bodies are byte-identical to legacy (source-parity-pinned by\n"
     "``test_native_meta_writer.py``); only this docstring, the class name, and\n"
     "``__all__`` differ.\n",
     "helpers. Method bodies are byte-identical to legacy (source-parity-pinned by\n"
     "``test_native_meta_writer.py`` until B7b deleted the engine); only this\n"
     "docstring, the class name, and ``__all__`` differed.\n"),
    ("helao/hexagon/adapters/native/meta_writer.py",
     "it at call time (cache-nothing rule). Installed per-Base by\n"
     "``helao.hexagon.app.active_graft.graft_active_write_path`` as a drop-in for\n"
     "``base.meta_writer`` -- the ``Base`` delegators (``base.py:666-716``) resolve\n"
     "``self.meta_writer`` at call time, so the swap reroutes ``write_act``/\n"
     "``write_exp``/``write_seq``/``_write_meta_atomic``/``new_file_conn_key``/\n"
     "``dflt_file_conn_key`` in one assignment.\n",
     "it at call time (cache-nothing rule). ``ActionHost`` constructs it as its\n"
     "``meta_writer`` (``NativeArtifactStoreAdapter.meta_writer_for``).\n"),
    ("helao/hexagon/adapters/native/ws_publish.py",
     "by putting each payload onto the composition's legacy fan-out queues\n"
     "(base.status_q / data_q / live_q) — the queues the legacy-hosted\n"
     "WsPublisher routes (/ws_status /ws_data /ws_live, base_api.py:677-708)\n"
     "broadcast from.",
     "by putting each payload onto the host's fan-out queues\n"
     "(``ActionHost.status_q`` / ``data_q`` / ``live_q``) — the queues its\n"
     "WsPublisher routes (/ws_status /ws_data /ws_live,\n"
     "``ActionHost._register_websockets``) broadcast from."),
    ("helao/hexagon/adapters/native/galil_motion.py",
     "- ``shutdown`` await seam: ``base_api.py``'s shutdown handler calls\n",
     "- ``shutdown`` await seam: ``ActionHost.shutdown`` calls\n"),
    ("helao/hexagon/adapters/native/galil_motion.py",
     "  family (expose ``async_shutdown``, or make ``base_api`` await a coroutine\n",
     "  family (expose ``async_shutdown``, or make ``ActionHost`` await a coroutine\n"),
    ("helao/hexagon/adapters/native/galil_motion.py",
     "        estop-flag bookkeeping stays owned by ``base_api.py``'s ``/estop``.\n",
     "        estop-flag bookkeeping stays owned by ``ActionHost``'s ``/estop``.\n"),
    ("helao/hexagon/adapters/native/galil_motion_native.py",
     "    ``driver_classes=[NativeGalilMotion]`` (BaseAPI calls ``(config=...)``); the\n",
     "    ``driver_classes=[NativeGalilMotion]`` (ActionHost calls ``(config=...)``); the\n"),
    # -- helao/hexagon/app --
    ("helao/hexagon/app/action_host.py",
     "Where the graft imports a legacy module and rebinds methods onto the ``Base`` it\n"
     "constructs, an ``ActionHost`` *is* the server.\n",
     "Where the graft imported a legacy module and rebound methods onto the ``Base``\n"
     "it constructed, an ``ActionHost`` *is* the server.\n"),
    ("helao/hexagon/app/action_host.py",
     "``BoundActionRoute`` bound to itself; legacy ``BaseAPI``/``OrchAPI`` install\n"
     "``ActionAPIRoute``.\n",
     "``BoundActionRoute`` bound to itself; legacy ``BaseAPI``/``OrchAPI`` installed\n"
     "``ActionAPIRoute`` until B7b deleted them.\n"),
    ("helao/hexagon/app/action_host.py",
     "        #: ONE registry, on the host. The status *port* adapter keeps its own\n"
     "        #: client list for the graft compositions; routing the host's\n",
     "        #: ONE registry, on the host. The status *port* adapter keeps its own\n"
     "        #: client list for the makeActionApp compositions; routing the host's\n"),
    ("helao/hexagon/app/action_host.py",
     "        ws_data, a ``{datalab: (value, epoch)}`` dict on ws_live. ``OrchAPI``\n"
     "        puts dicts under the same three names;",
     "        ws_data, a ``{datalab: (value, epoch)}`` dict on ws_live. ``OrchHost``\n"
     "        puts dicts under the same three names;"),
    ("helao/hexagon/app/orch_host.py",
     "        and ``orch_payloads`` is the one implementation -- legacy\n"
     "        ``orch_api`` re-exports it.\n",
     "        and ``orch_payloads`` is the one implementation.\n"),
    ("helao/hexagon/app/orch_payloads.py",
     "Moved verbatim from ``helao/core/servers/orch_api.py`` by B7a. Each takes the\n"
     "orchestrator -- ``OrchHost`` natively, legacy ``Orch`` through ``orch_api``'s\n"
     "re-export -- and reads its queues, histories, ``status_summary`` and\n"
     "``step_thru_*`` flags at call time. They shape what the Bokeh and Reflex\n"
     "operators parse, so there is one implementation, here; ``orch_api`` re-exports\n"
     "these names until B7b deletes it.\n",
     "Moved verbatim from ``helao/core/servers/orch_api.py`` by B7a. Each takes the\n"
     "orchestrator (``OrchHost``) and reads its queues, histories,\n"
     "``status_summary`` and ``step_thru_*`` flags at call time. They shape what\n"
     "the Bokeh and Reflex operators parse, so there is one implementation, here.\n"),
    ("helao/hexagon/app/orch_wait.py",
     "endpoints with :class:`checkcond`; ``orch_api`` re-exports both names for the\n"
     "legacy ``OrchAPI`` until B7b deletes it.\n",
     "endpoints with :class:`checkcond`.\n"),
    ("helao/hexagon/app/ingestion.py",
     '"""Hexagon status ingestion (P2a): native replacement for the legacy\n'
     "``StatusIngester`` short-circuit (helao/core/servers/orch_status_sync.py).\n"
     "\n"
     "``HexStatusIngestion.update_status``/``update_nonblocking`` own the endpoint\n"
     "bodies once ``graft_hexagon_loop`` rebinds them onto the live legacy ``Orch``\n"
     "(instance rebind — the sanctioned wrap seam; NO legacy source edit). The\n",
     '"""Hexagon status ingestion (P2a): native replacement for the legacy\n'
     "``StatusIngester`` short-circuit (helao/hexagon/app/orch_status_sync.py).\n"
     "\n"
     "``HexStatusIngestion.update_status``/``update_nonblocking`` own the endpoint\n"
     "bodies: ``OrchHost``'s ``/update_status`` and ``/update_nonblocking`` routes\n"
     "call them (``graft_hexagon_loop`` rebound them onto a legacy ``Orch`` until\n"
     "B7b deleted it). The\n"),
    # -- helao/hexagon/ports --
    ("helao/hexagon/ports/status.py",
     "2. ``relay_pickle_stream`` -- remote subscribers read the ``_ws_relay``\n"
     "   zstd-compressed-pickle streams. Same transport decode as (1); a *different\n"
     "   producer*, so the same route name carries a plain dict here and a typed\n"
     "   model there (``OrchAPI`` is a sibling of ``BaseAPI``, not a subclass).\n",
     "2. ``relay_pickle_stream`` -- remote subscribers read the orchestrator's\n"
     "   zstd-compressed-pickle streams. Same transport decode as (1); a *different\n"
     "   producer*, so the same route name carries a plain dict here and a typed\n"
     "   model there (``OrchHost``'s publishers apply ``as_dict``; ``ActionHost``'s\n"
     "   do not).\n"),
    # -- helao/ui --
    ("helao/ui/shared/operator/orch_backend.py",
     ":class:`RemoteBackend` drives a remote orchestrator over OrchAPI HTTP/RPC\n"
     "endpoints and the Base status WebSocket.\n",
     ":class:`RemoteBackend` drives a remote orchestrator (``OrchHost``) over its\n"
     "HTTP/RPC endpoints and its status WebSocket.\n"),
    ("helao/ui/shared/operator/orch_backend.py",
     '    """Backend that drives a remote orchestrator over OrchAPI endpoints.\n',
     '    """Backend that drives a remote orchestrator over its HTTP endpoints.\n'),
    # -- hexagon orchestrator shim (spec's known list) --
    ("helao/deploy/hexagon/servers/orchestrator/async_orch2.py",
     "\n"
     "``makeOrchApp`` is left in place and still grafts, for any composition that\n"
     "has not moved. It skips the graft when handed a native host, so the two\n"
     "cannot both drive one set of queues.\n",
     "\n"
     "``makeOrchApp`` and the graft it drove were deleted by B7b.\n"),
    # -- hte drivers (not server modules; spec §10 does not cover them) --
    ("helao/deploy/hte/drivers/io/nidaqmx_driver.py",
     "        # DriverPoller._base_hook wiring in base_api.py); used only for the\n",
     "        # DriverPoller._base_hook wiring in action_host.py); used only for the\n"),
    ("helao/deploy/hte/drivers/io/nidaqmx_driver.py",
     "        framework (`base_api.py`'s `/estop` endpoint and `estop_actives()`),\n",
     "        framework (`ActionHost`'s `/estop` endpoint and `estop_actives()`),\n"),
    ("helao/deploy/hte/drivers/mfc/alicat_driver.py",
     "        # Open the Alicat serial connections at construction. BaseAPI builds the\n"
     "        # AliCatMFCPoller immediately after the driver and the poller AUTO-STARTS\n"
     "        # its poll loop in __init__ -- but BaseAPI never calls connect(), so\n",
     "        # Open the Alicat serial connections at construction. ActionHost builds\n"
     "        # the AliCatMFCPoller immediately after the driver and the poller\n"
     "        # AUTO-STARTS its poll loop in __init__ -- but ActionHost never calls\n"
     "        # connect(), so\n"),
    ("helao/deploy/hte/drivers/motion/galil_motion_driver.py",
     "        `getattr` (`base_api.py`'s `shutdown_event`) regardless of\n",
     "        `getattr` (`ActionHost.shutdown`) regardless of\n"),
    ("helao/deploy/hte/drivers/motion/galil_motion_driver.py",
     "        owned by the action-server framework (`base_api.py`'s `/estop`\n",
     "        owned by the action-server framework (`ActionHost`'s `/estop`\n"),
    ("helao/deploy/hte/drivers/motion/galil_motion_driver.py",
     "                `base_api.py`'s `/estop` endpoint, which calls this hook\n",
     "                `ActionHost`'s `/estop` endpoint, which calls this hook\n"),
    ("helao/deploy/hte/drivers/pstat/biologic_backend.py",
     '        """Stop everything and disconnect. Called by ``BaseAPI`` at exit."""\n',
     '        """Stop everything and disconnect. Called by ``ActionHost`` at exit."""\n'),
    ("helao/deploy/hte/drivers/pstat/biologic_eclib2/driver.py",
     "        Called by ``BaseAPI`` at server exit.",
     "        Called by ``ActionHost`` at server exit."),
    ("helao/deploy/hte/drivers/pstat/biologic_ole/driver.py",
     "        ``BaseAPI`` constructs drivers before the server is serving,",
     "        ``ActionHost`` constructs drivers before the server is serving,"),
    ("helao/deploy/hte/drivers/pstat/biologic_ole/driver.py",
     '        """Stop every running channel, clean up, disconnect. Called by BaseAPI."""\n',
     '        """Stop every running channel, clean up, disconnect. Called by ActionHost."""\n'),
    ("helao/deploy/hte/drivers/pstat/gamry/driver.py",
     "        Invoked by ``BaseAPI`` when the action server is shutting down.\n",
     "        Invoked by ``ActionHost`` when the action server is shutting down.\n"),
    ("helao/deploy/hte/drivers/pstat/gamry/sink.py",
     "import helao_logging as logging  # get LOGGER from BaseAPI instance",
     "import helao_logging as logging  # LOGGER is set by fast_launcher"),
    ("helao/deploy/hte/drivers/pump/legato_driver.py",
     "        # Open the serial connection now. BaseAPI never calls connect(), and\n",
     "        # Open the serial connection now. ActionHost never calls connect(), and\n"),
    ("helao/deploy/hte/drivers/sensor/sprintir_driver.py",
     "        # Open the serial port at construction. BaseAPI builds the DriverPoller\n"
     "        # (SprintIRPoller) immediately after the driver and the poller AUTO-STARTS\n"
     "        # its poll loop in __init__ -- but BaseAPI never calls connect(), so\n",
     "        # Open the serial port at construction. ActionHost builds the\n"
     "        # DriverPoller (SprintIRPoller) immediately after the driver and the\n"
     "        # poller AUTO-STARTS its poll loop in __init__ -- but ActionHost never\n"
     "        # calls connect(), so\n"),
    ("helao/deploy/hte/drivers/spec/andor/driver.py",
     '        """BaseAPI shutdown hook; disconnects the camera."""\n',
     '        """ActionHost shutdown hook; disconnects the camera."""\n'),
    ("helao/deploy/hte/drivers/spec/spectral_products_driver.py",
     "        framework (``base_api.py``'s ``/estop`` endpoint), not the driver.\n",
     "        framework (``ActionHost``'s ``/estop`` endpoint), not the driver.\n"),
    ("helao/deploy/hte/drivers/temperature_control/mecom_driver.py",
     "    sleep). ``BaseAPI`` constructs this poller with\n",
     "    sleep). ``ActionHost`` constructs this poller with\n"),
    # -- test deployment runners (not server modules) --
    ("helao/deploy/test/runners/simulatews_runner.py",
     "by ``ORCH`` itself (``OrchAPI`` inherits ``BaseAPI``, so the orchestrator\n",
     "by ``ORCH`` itself (``OrchHost`` subclasses ``ActionHost``, so the orchestrator\n"),
    ("helao/deploy/test/runners/test_runner.py",
     "``add_global_param``, ``conditional_stop``). Because ``OrchAPI`` inherits\n"
     "``BaseAPI``, the running orchestrator exposes those as ordinary RPC action\n",
     "``add_global_param``, ``conditional_stop``). Because ``OrchHost`` subclasses\n"
     "``ActionHost``, the running orchestrator exposes those as ordinary RPC action\n"),
]

MSG = [
    ("helao/hexagon/adapters/legacy/status.py",
     '                "publish_status before bind_publish_bridge (bound at "\n'
     '                "makeActionApp startup; orch compositions stay on legacy WS)"\n',
     '                "publish_status before bind_publish_bridge (bound at "\n'
     '                "makeActionApp startup; OrchHost publishes on its own WS)"\n'),
    ("helao/hexagon/adapters/legacy/status.py",
     '                "publish_data before bind_publish_bridge (bound at "\n'
     '                "makeActionApp startup; orch compositions stay on legacy WS)"\n',
     '                "publish_data before bind_publish_bridge (bound at "\n'
     '                "makeActionApp startup; OrchHost publishes on its own WS)"\n'),
    ("helao/hexagon/adapters/legacy/status.py",
     '                "publish_live before bind_publish_bridge (bound at "\n'
     '                "makeActionApp startup; orch compositions stay on legacy WS)"\n',
     '                "publish_live before bind_publish_bridge (bound at "\n'
     '                "makeActionApp startup; OrchHost publishes on its own WS)"\n'),
    ("helao/hexagon/adapters/native/artifact_store.py",
     '                "meta members need a bound Base; the active graft calls "\n'
     '                "bind_base(base) at startup"\n',
     '                "meta members need a bound base; call bind_base(base) "\n'
     '                "before using them"\n'),
]


def main() -> int:
    texts, bad = {}, []
    for rel, old, new in DOC + MSG:
        text = texts.get(rel)
        if text is None:
            text = (ROOT / rel).read_text(encoding="utf-8")
        n = text.count(old)
        if n != 1:
            bad.append(f"{rel}: expected 1 match, found {n}: {old[:70]!r}")
            continue
        texts[rel] = text.replace(old, new)
    if bad:
        print("\n".join(bad))
        print("NOTHING WRITTEN")
        return 1
    for rel, text in texts.items():
        (ROOT / rel).write_text(text, encoding="utf-8")
    print(f"applied {len(DOC)} doc + {len(MSG)} message edits to {len(texts)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 11.4: Write `$X/t11_ast_check.py`** (exact content). It proves that the `DOC` edits changed only docstrings and comments, and that the only non-docstring strings that changed are the four `MSG` messages.

```python
"""B7b Task 11: prove the stale-reference edits changed only docstrings, comments
and the four named error messages.

Usage: python t11_ast_check.py <repo root> <ref>
<ref> is a git revision to compare against (the plan passes HEAD). In a tree that is
not a git checkout, pass a directory instead and the old text is read from it.
Exit 0 only if every edited .py file has the same AST once docstrings are removed,
and the non-docstring string constants that differ are exactly the expected four.
"""

import ast
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from t11_stale_refs import DOC, MSG  # noqa: E402

ROOT = Path(sys.argv[1])
REF = sys.argv[2]

EXPECTED_NEW_MESSAGES = {
    "publish_status before bind_publish_bridge (bound at makeActionApp startup; OrchHost publishes on its own WS)",
    "publish_data before bind_publish_bridge (bound at makeActionApp startup; OrchHost publishes on its own WS)",
    "publish_live before bind_publish_bridge (bound at makeActionApp startup; OrchHost publishes on its own WS)",
    "meta members need a bound base; call bind_base(base) before using them",
}


def old_text(rel: str) -> str:
    if Path(REF).is_dir():
        return (Path(REF) / rel).read_text(encoding="utf-8")
    return subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{REF}:{rel}"],
        capture_output=True, text=True, check=True,
    ).stdout


def strip_docstrings(tree: ast.AST) -> ast.AST:
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if (
            isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            node.body = body[1:] or [ast.Pass()]
    return tree


def strings(tree: ast.AST) -> list:
    return [
        n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]


def blanked(tree: ast.AST) -> str:
    """The AST with every string constant emptied: equal iff only strings differ."""
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            n.value = ""
    return ast.dump(tree)


bad, new_msgs = [], set()
for rel in sorted({rel for rel, _, _ in DOC + MSG}):
    before = strip_docstrings(ast.parse(old_text(rel)))
    after = strip_docstrings(ast.parse((ROOT / rel).read_text(encoding="utf-8")))
    if ast.dump(before) == ast.dump(after):
        continue
    gone = set(strings(before)) - set(strings(after))
    added = set(strings(after)) - set(strings(before))
    new_msgs |= added
    if blanked(before) != blanked(after) or not added <= EXPECTED_NEW_MESSAGES:
        bad.append(f"{rel}: code changed (strings removed {sorted(gone)}, added {sorted(added)})")

if new_msgs != EXPECTED_NEW_MESSAGES:
    bad.append(f"message set differs: {sorted(new_msgs ^ EXPECTED_NEW_MESSAGES)}")
print("\n".join(bad) if bad else "DOCS-AND-4-MESSAGES-ONLY")
sys.exit(1 if bad else 0)
```

- [ ] **Step 11.5: Apply and prove.**

```
timeout 120 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t11_stale_refs.py" "$WT"
timeout 120 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t11_ast_check.py" "$WT" HEAD
```
Expected (measured):
```
applied 59 doc + 4 message edits to 38 files
DOCS-AND-4-MESSAGES-ONLY
```
The check was falsified in the dry run. Run against a tree that also carried Task 15's code deletions in `orch_host.py`, it printed `helao/hexagon/app/orch_host.py: code changed (strings removed [], added [])` and exited 1. A `NOTHING WRITTEN` from the first command means a matched line changed in commits 1–2. The likeliest case is `harness/openapi_capture.py`'s docstring, if Task 4 rewrote it. STOP and report; do not widen the match.

No changed message is asserted anywhere. `grep -rn` over every `tests/` directory and the `.omc` golden baselines for `legacy WS`, `active graft calls`, `source-parity-pinned`, `Swapped in for` and `OrchAPI HTTP` returned nothing on `64f2cf15`.

- [ ] **Step 11.6: The classification record.** Nothing to run. This table is the D-B7b.10 record for the PR. It covers every hit of the spec's grep on `64f2cf15`: 384 hits in 113 files. Files deleted or rewritten by another task are one row each; every other hit has its own row. "FIX (Task 11)" rows are the ones Steps 11.2–11.5 change.

| hit | text | class |
|---|---|---|
| `helao/deploy/hexagon/servers/action/sim_db_server.py` (12 hits) | whole file | Task 8 rewrites |
| `helao/hexagon/adapters/legacy/health.py` (2 hits) | whole file | Task 8 rewrites |
| `helao/hexagon/app/dispatch_loop.py` (11 hits) | whole file | Task 8 rewrites |
| `helao/hexagon/app/factory.py` (25 hits) | whole file | Task 8 rewrites |
| `helao/hexagon/hexconfig.py` (10 hits) | whole file | Task 8 rewrites |
| `harness/ws_frames.py` (18 hits) | whole file | Task 9 rewrites |
| `helao/core/servers/active_data_file.py` (1 hit) | whole file | deleted (Task 12 `rm -rf`) |
| `helao/core/servers/active_data_stream.py` (4 hits) | whole file | deleted (Task 12 `rm -rf`) |
| `helao/core/servers/base.py` (4 hits) | whole file | deleted (Task 12 `rm -rf`) |
| `helao/core/servers/base_action_queue.py` (1 hit) | whole file | deleted (Task 12 `rm -rf`) |
| `helao/core/servers/base_api.py` (6 hits) | whole file | deleted (Task 12 `rm -rf`) |
| `helao/core/servers/base_endpoints.py` (6 hits) | whole file | deleted (Task 12 `rm -rf`) |
| `helao/core/servers/base_live_buffer.py` (4 hits) | whole file | deleted (Task 12 `rm -rf`) |
| `helao/core/servers/base_meta_writer.py` (2 hits) | whole file | deleted (Task 12 `rm -rf`) |
| `helao/core/servers/base_status.py` (7 hits) | whole file | deleted (Task 12 `rm -rf`) |
| `helao/core/servers/orch.py` (15 hits) | whole file | deleted (Task 12 `rm -rf`) |
| `helao/core/servers/orch_api.py` (5 hits) | whole file | deleted (Task 12 `rm -rf`) |
| `helao/hexagon/app/active_graft.py` (13 hits) | whole file | deleted (Task 8) |
| `helao/hexagon/app/sync_graft.py` (14 hits) | whole file | deleted (Task 8) |
| `helao/deploy/hexagon/servers/action/HTEdata_server.py` (1 hit) | whole file | leave: B7c shim / `graft` config shape |
| `helao/deploy/hexagon/servers/action/analysis_server.py` (1 hit) | whole file | leave: B7c shim / `graft` config shape |
| `helao/deploy/hexagon/servers/action/andor_server.py` (1 hit) | whole file | leave: B7c shim / `graft` config shape |
| `helao/deploy/hexagon/servers/action/biologic_server.py` (1 hit) | whole file | leave: B7c shim / `graft` config shape |
| `helao/deploy/hexagon/servers/action/calc_server.py` (1 hit) | whole file | leave: B7c shim / `graft` config shape |
| `helao/deploy/hexagon/servers/action/cam_server.py` (1 hit) | whole file | leave: B7c shim / `graft` config shape |
| `helao/deploy/hexagon/servers/action/co2sensor_server.py` (1 hit) | whole file | leave: B7c shim / `graft` config shape |
| `helao/deploy/hexagon/servers/action/diapump_server.py` (1 hit) | whole file | leave: B7c shim / `graft` config shape |
| `helao/deploy/hexagon/servers/action/galil_io.py` (1 hit) | whole file | leave: B7c shim / `graft` config shape |
| `helao/deploy/hexagon/servers/action/galil_motion.py` (1 hit) | whole file | leave: B7c shim / `graft` config shape |
| `helao/deploy/hexagon/servers/action/gamry_server2.py` (1 hit) | whole file | leave: B7c shim / `graft` config shape |
| `helao/deploy/hexagon/servers/action/graft.py` (10 hits) | whole file | leave: B7c shim / `graft` config shape |
| `helao/deploy/hexagon/servers/action/kinesis_server.py` (1 hit) | whole file | leave: B7c shim / `graft` config shape |
| `helao/deploy/hexagon/servers/action/mfc_server.py` (1 hit) | whole file | leave: B7c shim / `graft` config shape |
| `helao/deploy/hexagon/servers/action/nidaqmx_server.py` (1 hit) | whole file | leave: B7c shim / `graft` config shape |
| `helao/deploy/hexagon/servers/action/o2sensor_server.py` (1 hit) | whole file | leave: B7c shim / `graft` config shape |
| `helao/deploy/hexagon/servers/action/pal_server.py` (1 hit) | whole file | leave: B7c shim / `graft` config shape |
| `helao/deploy/hexagon/servers/action/pdu_server.py` (1 hit) | whole file | leave: B7c shim / `graft` config shape |
| `helao/deploy/hexagon/servers/action/power_supply_server.py` (1 hit) | whole file | leave: B7c shim / `graft` config shape |
| `helao/deploy/hexagon/servers/action/sample_server.py` (1 hit) | whole file | leave: B7c shim / `graft` config shape |
| `helao/deploy/hexagon/servers/action/spec_server.py` (1 hit) | whole file | leave: B7c shim / `graft` config shape |
| `helao/deploy/hexagon/servers/action/sync_server.py` (1 hit) | whole file | leave: B7c shim / `graft` config shape |
| `helao/deploy/hexagon/servers/action/syringe_server.py` (1 hit) | whole file | leave: B7c shim / `graft` config shape |
| `helao/deploy/hexagon/servers/action/tec_server.py` (1 hit) | whole file | leave: B7c shim / `graft` config shape |
| `helao/deploy/hexagon/servers/operator/graft.py` (9 hits) | whole file | leave: B7c shim / `graft` config shape |
| `helao/deploy/hexagon/servers/orchestrator/async_orch2.py` (2 hits) | whole file | leave: B7c shim / `graft` config shape |
| `helao/deploy/hexagon/servers/visualizer/graft.py` (9 hits) | whole file | leave: B7c shim / `graft` config shape |
| `harness/endpoints.py:11` | ``{?}``; routes registered dynamically at runtime (BaseAPI system surface, | FIX (Task 11) |
| `harness/openapi_capture.py:4` | decorators on a module's own functions; it cannot see the routes ``BaseAPI``/ | FIX (Task 11) |
| `helao/core/drivers/data/analysis_driver.py:16` | :func:`resolve_analyses_package`, which survives a hexagon graft (see its | leave: `graft` names the surviving config shape (B7c renames) |
| `helao/core/drivers/data/analysis_driver.py:186` | — the graft would lose every ``analyze_*`` route. The graft nevertheless | leave: `graft` names the surviving config shape (B7c renames) |
| `helao/core/drivers/data/analysis_driver.py:189` | 1. the deployment owning ``legacy_module`` (the ``fast: graft`` shape, where | leave: `graft` names the surviving config shape (B7c renames) |
| `helao/core/drivers/data/analysis_driver.py:286` | `hexagon graft.` | leave: `graft` names the surviving config shape (B7c renames) |
| `helao/core/drivers/helao_driver.py:166` | `# the owning Base (set by BaseAPI after construction); Any avoids a` | FIX (Task 11) |
| `helao/core/rpc/zmq_rpc.py:3` | Each ``BaseAPI`` / ``OrchAPI`` instance binds a ``zmq.ROUTER`` socket on | FIX (Task 11) |
| `helao/deploy/hexagon/servers/orchestrator/async_orch2.py:12` | ``makeOrchApp`` is left in place and still grafts, for any composition that | FIX (Task 11) |
| `helao/deploy/hexagon/servers/orchestrator/async_orch2.py:13` | `has not moved. It skips the graft when handed a native host, so the two` | FIX (Task 11) |
| `helao/deploy/hte/configs/adss3_hex.py:16` | route through the generic graft (``<code key>: graft`` plus a | leave: `graft` names the surviving config shape (B7c renames) |
| `helao/deploy/hte/configs/anec_hex.py:16` | route through the generic graft (``<code key>: graft`` plus a | leave: `graft` names the surviving config shape (B7c renames) |
| `helao/deploy/hte/configs/ccsi2_hex.py:16` | route through the generic graft (``<code key>: graft`` plus a | leave: `graft` names the surviving config shape (B7c renames) |
| `helao/deploy/hte/configs/clad_hex.py:16` | route through the generic graft (``<code key>: graft`` plus a | leave: `graft` names the surviving config shape (B7c renames) |
| `helao/deploy/hte/configs/eche10_hex.py:16` | route through the generic graft (``<code key>: graft`` plus a | leave: `graft` names the surviving config shape (B7c renames) |
| `helao/deploy/hte/configs/ecms3_hex.py:16` | route through the generic graft (``<code key>: graft`` plus a | leave: `graft` names the surviving config shape (B7c renames) |
| `helao/deploy/hte/configs/hispec_hex.py:16` | route through the generic graft (``<code key>: graft`` plus a | leave: `graft` names the surviving config shape (B7c renames) |
| `helao/deploy/hte/drivers/io/nidaqmx_driver.py:105` | `# DriverPoller._base_hook wiring in base_api.py); used only for the` | FIX (Task 11) |
| `helao/deploy/hte/drivers/io/nidaqmx_driver.py:835` | framework (`base_api.py`'s `/estop` endpoint and `estop_actives()`), | FIX (Task 11) |
| `helao/deploy/hte/drivers/mfc/alicat_driver.py:81` | `# Open the Alicat serial connections at construction. BaseAPI builds the` | FIX (Task 11) |
| `helao/deploy/hte/drivers/mfc/alicat_driver.py:83` | `# its poll loop in __init__ -- but BaseAPI never calls connect(), so` | FIX (Task 11) |
| `helao/deploy/hte/drivers/motion/galil_motion_driver.py:345` | `getattr` (`base_api.py`'s `shutdown_event`) regardless of | FIX (Task 11) |
| `helao/deploy/hte/drivers/motion/galil_motion_driver.py:1044` | owned by the action-server framework (`base_api.py`'s `/estop` | FIX (Task 11) |
| `helao/deploy/hte/drivers/motion/galil_motion_driver.py:1075` | `base_api.py`'s `/estop` endpoint, which calls this hook | FIX (Task 11) |
| `helao/deploy/hte/drivers/pstat/biologic_backend.py:68` | """Stop everything and disconnect. Called by ``BaseAPI`` at exit.""" | FIX (Task 11) |
| `helao/deploy/hte/drivers/pstat/biologic_eclib2/driver.py:255` | Called by ``BaseAPI`` at server exit. Returns None, matching the | FIX (Task 11) |
| `helao/deploy/hte/drivers/pstat/biologic_ole/driver.py:97` | ``BaseAPI`` constructs drivers before the server is serving, and the | FIX (Task 11) |
| `helao/deploy/hte/drivers/pstat/biologic_ole/driver.py:768` | `"""Stop every running channel, clean up, disconnect. Called by BaseAPI."""` | FIX (Task 11) |
| `helao/deploy/hte/drivers/pstat/gamry/driver.py:680` | Invoked by ``BaseAPI`` when the action server is shutting down. | FIX (Task 11) |
| `helao/deploy/hte/drivers/pstat/gamry/sink.py:12` | `from helao.helpers import helao_logging as logging  # get LOGGER from BaseAPI...` | FIX (Task 11) |
| `helao/deploy/hte/drivers/pump/legato_driver.py:132` | `# Open the serial connection now. BaseAPI never calls connect(), and` | FIX (Task 11) |
| `helao/deploy/hte/drivers/sensor/sprintir_driver.py:70` | `# Open the serial port at construction. BaseAPI builds the DriverPoller` | FIX (Task 11) |
| `helao/deploy/hte/drivers/sensor/sprintir_driver.py:72` | `# its poll loop in __init__ -- but BaseAPI never calls connect(), so` | FIX (Task 11) |
| `helao/deploy/hte/drivers/spec/andor/driver.py:1076` | `"""BaseAPI shutdown hook; disconnects the camera."""` | FIX (Task 11) |
| `helao/deploy/hte/drivers/spec/spectral_products_driver.py:451` | framework (``base_api.py``'s ``/estop`` endpoint), not the driver. | FIX (Task 11) |
| `helao/deploy/hte/drivers/temperature_control/mecom_driver.py:268` | sleep). ``BaseAPI`` constructs this poller with | FIX (Task 11) |
| `helao/deploy/hte/servers/action/andor_server.py:577` | existing station config needs no edit. Note that ``base_api`` names the | leave: deployment server module (spec §10); stale, listed for B7c |
| `helao/deploy/hte/servers/action/biologic_server.py:1059` | #: Which backend this app was built for. `base_api` names the driver | leave: deployment server module (spec §10); stale, listed for B7c |
| `helao/deploy/hte/servers/action/galil_motion.py:83` | in ``base_api.py``, without its single-endpoint narrowing: a panel command | leave: deployment server module (spec §10); stale, listed for B7c |
| `helao/deploy/hte/servers/action/kinesis_server.py:39` | in ``base_api.py``, without its single-endpoint narrowing: a panel command | leave: deployment server module (spec §10); stale, listed for B7c |
| `helao/deploy/hte/servers/action/kinesis_server.py:302` | # ``BaseAPI``, which did not carry the Optional, so B5's retype is what | leave: provenance |
| `helao/deploy/hte/servers/orchestrator/async_orch2.py:9` | B5: this used to build a legacy ``OrchAPI``, which constructed an ``Orch`` and | leave: provenance |
| `helao/deploy/hte/servers/orchestrator/async_orch2.py:10` | let ``makeOrchApp`` graft the hexagon reducer over it. B3b gave the reducer a | leave: provenance |
| `helao/deploy/hte/servers/orchestrator/async_orch2.py:38` | # No ``driver_classes``: OrchHost does not take it. The legacy OrchAPI did, | leave: provenance |
| `helao/deploy/test/configs/test_hex.py:16` | route through the generic graft (``<code key>: graft`` plus a | leave: `graft` names the surviving config shape (B7c renames) |
| `helao/deploy/test/runners/simulatews_runner.py:8` | by ``ORCH`` itself (``OrchAPI`` inherits ``BaseAPI``, so the orchestrator | FIX (Task 11) |
| `helao/deploy/test/runners/test_runner.py:4` | ``add_global_param``, ``conditional_stop``). Because ``OrchAPI`` inherits | FIX (Task 11) |
| `helao/deploy/test/runners/test_runner.py:5` | ``BaseAPI``, the running orchestrator exposes those as ordinary RPC action | FIX (Task 11) |
| `helao/deploy/test/servers/action/archive_simulator.py:204` | Wires :class:`ArchiveSim` into a :class:`BaseAPI` and registers private | leave: deployment server module (spec §10); stale, listed for B7c |
| `helao/deploy/test/servers/action/control_sim.py:169` | real ``BaseAPI``. That property is the one row 15 rests on and it is a | leave: deployment server module (spec §10); stale, listed for B7c |
| `helao/deploy/test/servers/action/control_sim.py:176` | ``driver`` attribute -- a ``BaseAPI`` in production, a recording | leave: deployment server module (spec §10); stale, listed for B7c |
| `helao/deploy/test/servers/action/control_sim.py:297` | # Through ``dyn_endpoints``, not inline after the constructor: ``BaseAPI`` | leave: deployment server module (spec §10); stale, listed for B7c |
| `helao/deploy/test/servers/action/cpsim_server.py:26` | Wires :class:`CPSim` into a :class:`BaseAPI` and registers actions: | leave: deployment server module (spec §10); stale, listed for B7c |
| `helao/deploy/test/servers/action/gpsim_server.py:26` | Wires :class:`GPSim` into a :class:`BaseAPI` and exposes actions | leave: deployment server module (spec §10); stale, listed for B7c |
| `helao/deploy/test/servers/action/motion_simulator.py:118` | Wires :class:`MotionSim` into a :class:`BaseAPI` and exposes | leave: deployment server module (spec §10); stale, listed for B7c |
| `helao/deploy/test/servers/action/pstat_simulator.py:89` | Wires :class:`PstatSim` into a :class:`BaseAPI` and registers the | leave: deployment server module (spec §10); stale, listed for B7c |
| `helao/helpers/bubble_detection.py:8` | `from helao.helpers import helao_logging as logging  # get LOGGER from BaseAPI...` | FIX (Task 11) |
| `helao/helpers/dispatcher.py:135` | :class:`BaseAPI`; the RPC fast path bypasses that middleware and | FIX (Task 11) |
| `helao/hexagon/adapters/legacy/status.py:15` | endpoint (helao/core/servers/orch_api.py) takes ``server_host``/``server_port`` | leave: provenance |
| `helao/hexagon/adapters/native/artifact_store.py:9` | `graft at startup (the late-binding pattern the status adapter documents for` | FIX (Task 11) |
| `helao/hexagon/adapters/native/artifact_store.py:11` | ``graft_active_write_path`` obtains the per-Active native collaborators via | FIX (Task 11) |
| `helao/hexagon/adapters/native/artifact_store.py:50` | `# --- graft-time binding + collaborator factory ---` | FIX (Task 11) |
| `helao/hexagon/adapters/native/artifact_store.py:52` | `"""Late base binding (graft startup); build_wiring has no Base yet."""` | FIX (Task 11) |
| `helao/hexagon/adapters/native/artifact_store.py:78` | `"meta members need a bound Base; the active graft calls "` | FIX (Task 11) |
| `helao/hexagon/adapters/native/artifact_store.py:92` | `# meta_writer — the graft has already swapped it native) ---` | FIX (Task 11) |
| `helao/hexagon/adapters/native/data_file.py:17` | ``graft_active_write_path`` between ``Active.__init__`` and ``myinit()``; | FIX (Task 11) |
| `helao/hexagon/adapters/native/data_file.py:67` | by ``assert_source_parity`` (see ``native_fixtures``), and an annotation in | FIX (Task 11) |
| `helao/hexagon/adapters/native/data_sink.py:15` | while legacy BaseAPI hosts). The lbuf members route via ``active.base`` — | leave: provenance |
| `helao/hexagon/adapters/native/data_stream.py:19` | ``active.data_stream`` by ``graft_active_write_path`` between | FIX (Task 11) |
| `helao/hexagon/adapters/native/data_stream.py:64` | by ``assert_source_parity`` (see ``native_fixtures``), and an annotation in | FIX (Task 11) |
| `helao/hexagon/adapters/native/finalizer.py:22` | ``active.action_finalizer`` by ``graft_active_write_path`` between | FIX (Task 11) |
| `helao/hexagon/adapters/native/finalizer.py:63` | by ``assert_source_parity`` (see ``native_fixtures``), and an annotation in | FIX (Task 11) |
| `helao/hexagon/adapters/native/galil_motion.py:25` | - **Not runtime-wired.** The P3 graft-wrap path keeps ``app.driver`` pointed at | leave: `graft` names the surviving config shape (B7c renames) |
| `helao/hexagon/adapters/native/galil_motion.py:32` | - ``shutdown`` await seam: ``base_api.py``'s shutdown handler calls | FIX (Task 11) |
| `helao/hexagon/adapters/native/galil_motion.py:38` | family (expose ``async_shutdown``, or make ``base_api`` await a coroutine | FIX (Task 11) |
| `helao/hexagon/adapters/native/galil_motion.py:173` | estop-flag bookkeeping stays owned by ``base_api.py``'s ``/estop``. | FIX (Task 11) |
| `helao/hexagon/adapters/native/galil_motion_native.py:78` | ``driver_classes=[NativeGalilMotion]`` (BaseAPI calls ``(config=...)``); the | FIX (Task 11) |
| `helao/hexagon/adapters/native/meta_writer.py:14` | ``helao.hexagon.app.active_graft.graft_active_write_path`` as a drop-in for | FIX (Task 11) |
| `helao/hexagon/adapters/native/ws_publish.py:6` | `WsPublisher routes (/ws_status /ws_data /ws_live, base_api.py:677-708)` | FIX (Task 11) |
| `helao/hexagon/app/action_context.py:5` | ``base_api.py:92``); that is why ``Base.setup_and_contain_action()`` takes no | leave: provenance |
| `helao/hexagon/app/action_context.py:21` | ``base_api._build_action_from_kwargs`` and the code-identity block of | leave: provenance |
| `helao/hexagon/app/action_context.py:46` | #: Same spelling as legacy ``base_api.ACTION_VERSION_ATTR`` -- D-B1.2 keeps the | leave: provenance |
| `helao/hexagon/app/action_host.py:3` | Replaces ``BaseAPI``/``Base`` as the object a deployment action module builds. | leave: provenance |
| `helao/hexagon/app/action_host.py:4` | Where the graft imports a legacy module and rebinds methods onto the ``Base`` it | FIX (Task 11) |
| `helao/hexagon/app/action_host.py:29` | ``BoundActionRoute`` bound to itself; legacy ``BaseAPI``/``OrchAPI`` install | FIX (Task 11) |
| `helao/hexagon/app/action_host.py:100` | Constructor arity matches ``BaseAPI.__init__`` deliberately — that part of | leave: provenance |
| `helao/hexagon/app/action_host.py:271` | `#: client list for the graft compositions; routing the host's` | FIX (Task 11) |
| `helao/hexagon/app/action_host.py:1022` | Encodings are the ``BaseAPI`` family's and are frozen (Amendment 2 §3): | leave: provenance |
| `helao/hexagon/app/action_host.py:1024` | ws_data, a ``{datalab: (value, epoch)}`` dict on ws_live. ``OrchAPI`` | FIX (Task 11) |
| `helao/hexagon/app/action_host.py:1161` | ``base_api._register_utility_endpoints``: the host must not import the | leave: provenance |
| `helao/hexagon/app/action_session.py:11` | `its own collaborators and the graft then swaps them for native ones between` | leave: provenance |
| `helao/hexagon/app/ingestion.py:5` | bodies once ``graft_hexagon_loop`` rebinds them onto the live legacy ``Orch`` | FIX (Task 11) |
| `helao/hexagon/app/ingestion.py:23` | ``globstat_q`` stays on the legacy broadcaster (``ws_globstat``/ | Task 15 (globstat channel) |
| `helao/hexagon/app/ingestion.py:24` | ``globstat_broadcast_task`` are NOT rebound). ``clear_nonblocking`` is NOT | Task 15 (globstat channel) |
| `helao/hexagon/app/orch_dispatch.py:41` | - ``globstat_q`` -- written by ``StatusIngester``; drained by its own | Task 15 (globstat channel) |
| `helao/hexagon/app/orch_dispatch.py:51` | remains on ``Orch``, cluster B); it never touches ``globstat_q`` directly -- | Task 15 (globstat channel) |
| `helao/hexagon/app/orch_host.py:3` | Legacy's shape is ``OrchAPI(HelaoFastAPI)`` holding ``self.orch = | leave: provenance |
| `helao/hexagon/app/orch_host.py:4` | Orch(Base)``. Two objects, and the API layer is a SIBLING of ``BaseAPI`` | leave: provenance |
| `helao/hexagon/app/orch_host.py:13` | are ``self``: ``orch_api`` reaches ``self.orch.<member>`` at 60 sites and | leave: provenance |
| `helao/hexagon/app/orch_host.py:129` | `# Legacy never hit this because OrchAPI constructs Orch INSIDE its` | leave: provenance |
| `helao/hexagon/app/orch_host.py:173` | `self.globstat_broadcaster = None` | Task 15 (globstat channel) |
| `helao/hexagon/app/orch_host.py:179` | `self.globstat_q = MultisubscriberQueue()` | Task 15 (globstat channel) |
| `helao/hexagon/app/orch_host.py:180` | `self.globstat_clients = set()` | Task 15 (globstat channel) |
| `helao/hexagon/app/orch_host.py:431` | Eight of ``orch_api``'s private routes -- /get_status, | leave: provenance |
| `helao/hexagon/app/orch_host.py:573` | ``orch_api`` re-exports it. | FIX (Task 11) |
| `helao/hexagon/app/orch_host.py:862` | measured case: ``BaseAPI`` declares ``executor_id: str`` (required), | leave: provenance |
| `helao/hexagon/app/orch_host.py:863` | ``OrchAPI`` declares ``executor_id: str = ""`` and returns an error | leave: provenance |
| `helao/hexagon/app/orch_host.py:956` | `async def globstat_broadcast_task(self):` | Task 15 (globstat channel) |
| `helao/hexagon/app/orch_host.py:957` | `"""Drain globstat_q so subscribers can read eagerly."""` | Task 15 (globstat channel) |
| `helao/hexagon/app/orch_host.py:958` | `return await self.status_ingester.globstat_broadcast_task()` | Task 15 (globstat channel) |
| `helao/hexagon/app/orch_host.py:960` | `async def ws_globstat(self, websocket):` | Task 15 (globstat channel) |
| `helao/hexagon/app/orch_host.py:965` | `return await self.status_ingester.ws_globstat(websocket)` | Task 15 (globstat channel) |
| `helao/hexagon/app/orch_host.py:969` | `reducer runs, exactly as the graft superseded it."""` | leave: provenance |
| `helao/hexagon/app/orch_host.py:1002` | `await self.globstat_q.put(interrupt.as_json())` | Task 15 (globstat channel) |
| `helao/hexagon/app/orch_host.py:1073` | `from the legacy collaborators and orch_api, and orch_effects only` | leave: provenance |
| `helao/hexagon/app/orch_host.py:1123` | Bodies ported from ``orch_api`` unchanged apart from the back | leave: provenance |
| `helao/hexagon/app/orch_host.py:1331` | The two families genuinely differ on the wire. ``base_api`` streams | Task 9 (docstring of the function it rewrites) |
| `helao/hexagon/app/orch_host.py:1333` | IDENTITY -- it pickles the model object. ``orch_api`` streams | Task 9 (docstring of the function it rewrites) |
| `helao/hexagon/app/orch_host.py:1391` | ``graft_hexagon_loop`` built exactly this and then REBOUND nine | leave: provenance |
| `helao/hexagon/app/orch_host.py:1394` | `written against the runtime directly and the graft is retired in` | leave: provenance |
| `helao/hexagon/app/orch_host.py:1429` | `as the graft superseded it.` | leave: provenance |
| `helao/hexagon/app/orch_host.py:1439` | `self.globstat_broadcaster = asyncio.create_task(` | Task 15 (globstat channel) |
| `helao/hexagon/app/orch_host.py:1440` | `self.globstat_broadcast_task()` | Task 15 (globstat channel) |
| `helao/hexagon/app/orch_host.py:1491` | `self.globstat_broadcaster,` | Task 15 (globstat channel) |
| `helao/hexagon/app/orch_payloads.py:3` | Moved verbatim from ``helao/core/servers/orch_api.py`` by B7a. Each takes the | leave: provenance |
| `helao/hexagon/app/orch_payloads.py:4` | orchestrator -- ``OrchHost`` natively, legacy ``Orch`` through ``orch_api``'s | FIX (Task 11) |
| `helao/hexagon/app/orch_payloads.py:7` | operators parse, so there is one implementation, here; ``orch_api`` re-exports | FIX (Task 11) |
| `helao/hexagon/app/orch_status_sync.py:5` | ``Orch.ws_globstat``/``Orch.globstat_broadcast_task`` implement the | Task 15 (globstat channel) |
| `helao/hexagon/app/orch_status_sync.py:9` | status over the ``globstat_q``/websocket fan-out to the Bokeh operator UI. | Task 15 (globstat channel) |
| `helao/hexagon/app/orch_status_sync.py:16` | ``active_experiment``/``active_sequence``, ``interrupt_q`` and ``globstat_q`` | Task 15 (globstat channel) |
| `helao/hexagon/app/orch_status_sync.py:30` | - ``globstat_q`` -- written by ``StatusIngester``; drained by its own | Task 15 (globstat channel) |
| `helao/hexagon/app/orch_status_sync.py:38` | cluster B, not yet extracted); ``globstat_q`` is only read/drained here | Task 15 (globstat channel) |
| `helao/hexagon/app/orch_status_sync.py:39` | (``ws_globstat`` subscribes, ``globstat_broadcast_task`` drains) -- it is | Task 15 (globstat channel) |
| `helao/hexagon/app/orch_status_sync.py:46` | ``asyncio.create_task(self.globstat_broadcast_task())`` via the thin | Task 15 (globstat channel) |
| `helao/hexagon/app/orch_status_sync.py:294` | `# await orch.globstat_q.put(orch.globalstatusmodel.as_json())` | Task 15 (globstat channel) |
| `helao/hexagon/app/orch_status_sync.py:298` | `async def ws_globstat(self, websocket: WebSocket):` | Task 15 (globstat channel) |
| `helao/hexagon/app/orch_status_sync.py:303` | `gs_sub = orch.globstat_q.subscribe()` | Task 15 (globstat channel) |
| `helao/hexagon/app/orch_status_sync.py:305` | `async for globstat_msg in gs_sub:` | Task 15 (globstat channel) |
| `helao/hexagon/app/orch_status_sync.py:306` | `await websocket.send_text(json.dumps(globstat_msg.as_dict()))` | Task 15 (globstat channel) |
| `helao/hexagon/app/orch_status_sync.py:312` | `if gs_sub in orch.globstat_q.subscribers:` | Task 15 (globstat channel) |
| `helao/hexagon/app/orch_status_sync.py:313` | `orch.globstat_q.remove(gs_sub)` | Task 15 (globstat channel) |
| `helao/hexagon/app/orch_status_sync.py:315` | `async def globstat_broadcast_task(self):` | Task 15 (globstat channel) |
| `helao/hexagon/app/orch_status_sync.py:316` | """Drain ``globstat_q`` indefinitely so subscribers can read messages eagerly... | Task 15 (globstat channel) |
| `helao/hexagon/app/orch_status_sync.py:318` | `async for _ in orch.globstat_q.subscribe():` | Task 15 (globstat channel) |
| `helao/hexagon/app/orch_wait.py:3` | Moved verbatim from ``helao/core/servers/orch_api.py`` by B7a. ``OrchHost`` | leave: provenance |
| `helao/hexagon/app/orch_wait.py:5` | endpoints with :class:`checkcond`; ``orch_api`` re-exports both names for the | FIX (Task 11) |
| `helao/hexagon/app/orch_wait.py:6` | legacy ``OrchAPI`` until B7b deletes it. | FIX (Task 11) |
| `helao/hexagon/app/reflex_host.py:5` | `point at a graft. Routing is by environment variable instead` | leave: `graft` names the surviving config shape (B7c renames) |
| `helao/hexagon/ports/auxiliary.py:70` | `"""Live buffer put, globstat/WS relay, LOGGER.alert."""` | Task 15 (globstat channel) |
| `helao/hexagon/ports/auxiliary.py:74` | `async def publish_globstat(self, payload: dict) -> None: ...` | Task 15 (globstat channel) |
| `helao/hexagon/ports/status.py:18` | model there (``OrchAPI`` is a sibling of ``BaseAPI``, not a subclass). | FIX (Task 11) |
| `helao/hexagon/ports/status.py:111` | base_api family delivers an ``ActionModel`` and the orch_api family a | leave: provenance |
| `helao/hexagon/preflight.py:14` | a server on the GENERIC `graft` shim declares a `legacy_module:` that | leave: `graft` names the surviving config shape (B7c renames) |
| `helao/hexagon/preflight.py:15` | `resolves to a module on disk (the graft names nothing itself, so without` | leave: `graft` names the surviving config shape (B7c renames) |
| `helao/hexagon/preflight.py:101` | Normally the `fast`/`bokeh` module basename, but a `fast: graft` server | leave: `graft` names the surviving config shape (B7c renames) |
| `helao/hexagon/preflight.py:102` | `(the generic config-driven hexagon graft, helao/deploy/hexagon/servers/` | leave: `graft` names the surviving config shape (B7c renames) |
| `helao/hexagon/preflight.py:103` | action/graft.py) wraps the module named by its top-level `legacy_module:` | leave: `graft` names the surviving config shape (B7c renames) |
| `helao/hexagon/preflight.py:105` | `generic shim name "graft".` | leave: `graft` names the surviving config shape (B7c renames) |
| `helao/hexagon/preflight.py:108` | `if module == "graft":` | leave: `graft` names the surviving config shape (B7c renames) |
| `helao/hexagon/preflight.py:240` | `if module == "graft":` | leave: `graft` names the surviving config shape (B7c renames) |
| `helao/hexagon/preflight.py:255` | What is checked is therefore the facade itself. As with a ``graft`` | leave: `graft` names the surviving config shape (B7c renames) |
| `helao/hexagon/preflight.py:294` | """Checks specific to a generic ``graft`` shim (`fast:`/`bokeh: graft`). | leave: `graft` names the surviving config shape (B7c renames) |
| `helao/hexagon/preflight.py:296` | `A graft shim names NOTHING — that indirection is what lets a PRIVATE` | leave: `graft` names the surviving config shape (B7c renames) |
| `helao/hexagon/preflight.py:312` | f"{key}: `{code_key}: graft` declares no `legacy_module:` — add a " | leave: `graft` names the surviving config shape (B7c renames) |
| `helao/hexagon/preflight.py:333` | A `graft` server states its target outright in `legacy_module:`; anything | leave: `graft` names the surviving config shape (B7c renames) |
| `helao/hexagon/preflight.py:338` | `if _server_module(server) == "graft":` | leave: `graft` names the surviving config shape (B7c renames) |
| `helao/hexagon/preflight.py:374` | `# graft another deployment's server without a DUPLICATE of that` | leave: `graft` names the surviving config shape (B7c renames) |
| `helao/ui/shared/operator/orch_backend.py:4` | :class:`RemoteBackend` drives a remote orchestrator over OrchAPI HTTP/RPC | FIX (Task 11) |
| `helao/ui/shared/operator/orch_backend.py:171` | `"""Backend that drives a remote orchestrator over OrchAPI endpoints.` | FIX (Task 11) |
| `run_browser_parity.py:61` | `#: is that the graft moves the hosting and changes nothing rendered, so the` | leave: provenance |
| `run_unit_tests.py:73` | `("base_api", base_api_unit_test),` | Task 7 removes the entry |

- [ ] **Step 11.7: Tests whose subject this task touches still pass** (the engine is still present at this point):

```
for t in helao/hexagon/tests/test_native_data_file.py helao/hexagon/tests/test_native_data_stream.py helao/hexagon/tests/test_native_finalizer.py helao/hexagon/tests/test_native_meta_writer.py helao/hexagon/tests/test_native_artifact_store.py helao/hexagon/tests/test_ws_publish_bridge.py helao/hexagon/tests/test_ports_import.py helao/hexagon/tests/test_boundaries.py; do printf '%s: ' "$t"; timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -m pytest -q -p no:cacheprovider --color=no "$t" 2>&1 | tail -1; done
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -m pytest -q -p no:cacheprovider --color=no harness/tests/test_hte_checklist.py 2>&1 | grep -E '^FAILED'
```
Expected: every line ends in `passed` with no `failed`. The `test_native_*` pins still pass, because they compare method source and this task edits only module and class docstrings. Measured on `64f2cf15` + Task 11, with the engine present: `9 passed`, `5 passed`, `6 passed`, `6 passed`, `6 passed`, `2 passed`, `3 passed`, `14 passed`. After Task 5 the counts are whatever Task 5 left, still with 0 failed. The checklist test prints exactly the three known IDs (`andor_server.py-ANDOR`, `biologic_server.py-BIOLOGIC`, `nidaqmx_server.py-NI`), because docstrings do not reach the AST route extraction.

**Files for the controller's commit:** (commit 3, together with Tasks 12 and 13; this task runs first)
- deleted: `helao/core/servers/CLAUDE.md` (Task 12's `rm -rf` then removes the rest of the directory)
- added: `helao/hexagon/app/CLAUDE.md`
- modified: `CLAUDE.md`, `helao/deploy/hte/drivers/spec/andor/CLAUDE.md`, and the 38 `.py` files named in `$X/t11_stale_refs.py`:
```
harness/endpoints.py
harness/openapi_capture.py
helao/core/drivers/helao_driver.py
helao/core/rpc/zmq_rpc.py
helao/deploy/hexagon/servers/orchestrator/async_orch2.py
helao/deploy/hte/drivers/io/nidaqmx_driver.py
helao/deploy/hte/drivers/mfc/alicat_driver.py
helao/deploy/hte/drivers/motion/galil_motion_driver.py
helao/deploy/hte/drivers/pstat/biologic_backend.py
helao/deploy/hte/drivers/pstat/biologic_eclib2/driver.py
helao/deploy/hte/drivers/pstat/biologic_ole/driver.py
helao/deploy/hte/drivers/pstat/gamry/driver.py
helao/deploy/hte/drivers/pstat/gamry/sink.py
helao/deploy/hte/drivers/pump/legato_driver.py
helao/deploy/hte/drivers/sensor/sprintir_driver.py
helao/deploy/hte/drivers/spec/andor/driver.py
helao/deploy/hte/drivers/spec/spectral_products_driver.py
helao/deploy/hte/drivers/temperature_control/mecom_driver.py
helao/deploy/test/runners/simulatews_runner.py
helao/deploy/test/runners/test_runner.py
helao/helpers/bubble_detection.py
helao/helpers/dispatcher.py
helao/hexagon/adapters/legacy/status.py
helao/hexagon/adapters/native/artifact_store.py
helao/hexagon/adapters/native/data_file.py
helao/hexagon/adapters/native/data_stream.py
helao/hexagon/adapters/native/finalizer.py
helao/hexagon/adapters/native/galil_motion.py
helao/hexagon/adapters/native/galil_motion_native.py
helao/hexagon/adapters/native/meta_writer.py
helao/hexagon/adapters/native/ws_publish.py
helao/hexagon/app/action_host.py
helao/hexagon/app/ingestion.py
helao/hexagon/app/orch_host.py
helao/hexagon/app/orch_payloads.py
helao/hexagon/app/orch_wait.py
helao/hexagon/ports/status.py
helao/ui/shared/operator/orch_backend.py
```
black: 34 of the 38 are black-clean as edited (measured). The other 4 (`adapters/native/{data_file,data_stream,finalizer,meta_writer}.py`) are force-excluded until Task 12 removes the exclusion and runs black on them.

---

### Task 12: Delete the engine, its self-tests, the legacy probe, and the engine readers

**Plan decisions (spec silent; defaults):**

- **P-H.1 (default; spec silent): `CLAUDE.md` is moved by Task 11, which runs before this task.** `rm -rf helao/core/servers` would delete `helao/core/servers/CLAUDE.md`. Task 11 Step 11.1 moves it to `helao/hexagon/app/CLAUDE.md` with a plain `mv` and changes only its title line (D-B7b.8); Step 12.3 here only confirms the move happened before anything is deleted.
- **P-H.2 (default; spec silent): the ratchet's probe loses its mode argument.** Once the `legacy` branch goes, the `if sys.argv[2] == "native":` test selects nothing. Task 12 deletes it and dedents the native body. `_probe(mode: str)` becomes `_probe()`, and the `native` fixture calls `_probe()`. Every later command that called `_probe("native")` (for example, Task 16 gate 1) must call `_probe()`. Task 8 adds its `makeActionApp` case as a third entry in the native `hosts` dict (Step 8.2), so after this task the probe has one mode and needs no argument.
- **P-H.3 (default; spec silent): the Task 13 sweep treats the path spelling as a reference only outside docstrings.** Spec §4.3 bans executable references and allows string mentions of `helao.core.servers` only in the §2.2 files. §2.2 measured the dotted name. The six source-path readers of §2.2 spell the engine as a path (`helao/core/servers/...`), so a dotted-only sweep would pass while one of them was still reading engine source. The sweep therefore also reports any **non-docstring** string constant that contains `helao/core/servers` or `helao\core\servers`. Path spellings inside docstrings are provenance ("moved from `helao/core/servers/orch_api.py` by B7a"), and the dry run found them in 13 files outside §2.2 (for example `app/orch_payloads.py`, `app/orch_wait.py`, `domain/queue_policy.py`), so they are not reported. D-B7b.10 leaves them alone.
- **P-H.4 (default; spec silent): the black reformat of the four native collaborators lands in commit 3, run by the implementer in Step 12.12.** Its proof is `ast.dump` equality of each file before and after, and the controller's pre-commit `black` pass then finds nothing left to do on them.

**Spec facts re-verified:**

- **Q6 says the `pyproject.toml` comment is "at lines 28–57". It is lines 30–57.** Lines 21–29 are the `[tool.black]` header and the `target-version` comment and value, and they stay. The `force-exclude` value is line 58, and the engine is named at lines 32 and 58, as §2.2 says.
- **Q6's black run changes three of the four files, not four.** In the planning dry run, with the new `force-exclude`, the helao env's `black 26.5.1` leaves `meta_writer.py` unchanged. It removes one trailing blank line from `data_file.py`, rewraps 32 lines of `data_stream.py`, and rewraps 24 lines of `finalizer.py`. `ast.dump` is equal before and after for all four files.
- Both sides of the `sync_driver` pair still fail `black --check` once they are no longer excluded. So the rewritten comment's "the legacy side is NOT black-formatted" holds.
- Verified exact: 18 tracked files and 6,578 `.py` lines under `helao/core/servers/`. `test_action_session_port.py:80` defines `test_the_legacy_active_satisfies_the_port`, and its import is at l.86. `test_estop_finish_race.py:26` holds the `Orch` import, and `FLAVOURS` is at l.86–89. `test_ws_consumer_parity.py:37–38`, `test_bokeh_theme.py:555` and `test_palette.py:1785` are as §5.5 says. In the ratchet, `ENGINE` is at l.41, the detector fixtures at l.121–131, `_PROBE` at l.153, and `ActionAPIRoute` at l.238.
- The §5.5 claim is measured. `harness.endpoints.extract_routes` finds `/ws_status`, `/ws_data` and `/ws_live` in both `helao/hexagon/app/orch_host.py` (64 routes) and `helao/hexagon/app/action_host.py` (20 routes), and `/ws_globstat` in neither. `test_ws_consumer_parity.py` passes (5 tests) with the native paths.
- Removing the engine glob from `test_bokeh_theme.py` and `test_palette.py` affects no floor. After `rm -rf` the glob is empty anyway. `test_bokeh_theme.py` passes 48 and `test_palette.py` passes 183 on the post-`rm` tree.
- No tracked `.py` makes an `importlib.import_module`, `__import__`, `find_spec`, `mock.patch`, `monkeypatch.setattr` or `monkeypatch.delattr` call with a string argument naming the engine. The only engine references are `Import`/`ImportFrom` statements, which confirms §2.2.
- The worktree already holds an untracked `helao/core/servers/__pycache__/`, as §2.1 predicts. The `rm -rf` in Step 12.4 removes it.

**Cross-check (planning dry run): every executable engine reference, and the task that removes it**

The dry run swept the 1,025 tracked `.py` files, less the 17 engine modules, so 1,008 files, after `rm -rf helao/core/servers`. **No hit is unowned.**

| task | executable references (file:line) |
|

**Files:**
- Verify only: `helao/core/servers/CLAUDE.md` is already at `helao/hexagon/app/CLAUDE.md` (Task 11 moved it)
- Delete: `helao/core/servers/` (17 tracked `.py` files, plus the untracked `__pycache__/`)
- Modify: `helao/hexagon/tests/test_action_session_port.py:80-94` (delete one test)
- Modify: `helao/hexagon/tests/test_estop_finish_race.py:9-10, 26, 87`
- Modify: `helao/hexagon/tests/test_engine_import_ratchet.py` (`_PROBE` body, `_probe`, the `legacy` fixture, `test_every_legacy_route_is_built_by_action_api_route`)
- Modify: `helao/hexagon/tests/test_ws_consumer_parity.py:37-38, 181, 186-189`
- Modify: `helao/core/tests/test_bokeh_theme.py:555`, `helao/core/tests/test_palette.py:1785` (one line each)
- Modify: `pyproject.toml:30-58`
- Reformat (black, layout only): `helao/hexagon/adapters/native/{data_file,data_stream,finalizer}.py` (`meta_writer.py` is measured unchanged)
- Also applied in this task: the commit-3 fragments of Task 5 (parity pins, `native_fixtures.assert_source_parity`, the legacy halves in `test_native_artifact_store`/`test_native_data_sink`) and of Tasks 3–4 (the member-coverage readers, and `test_orch_host_surface`'s `_legacy_orch_api_routes`). Those steps are written in those tasks' drafts and are placed between Steps 12.10 and 12.12 below.
- Scratch: `$X/t12_astcmp.py`, `$X/t12_native_before/` (the sweep scripts come from Task 0 Step 0.9)

**Interfaces:**
- Consumes: Tasks 1–10 committed (commit 1 and commit 2). The ratchet as Task 8 left it: no `ALLOWLIST`, `test_nothing_outside_the_engine_imports_it` asserting `offenders() == {}`, and the `makeActionApp` case inside the native probe.
- Produces:
  - `test_engine_import_ratchet._probe() -> dict`, with no arguments (P-H.2), and the module fixture `native`;
  - `helao/hexagon/app/CLAUDE.md`, which Task 11 edits.

**Execution:** runs alone, after Task 11 (which runs first in commit 3, on the commit-2 tree) and before Task 13. It deletes a directory that every other test imports until now, so nothing may run in parallel with it. Do not commit.

- [ ] **Step 12.1: Re-run the sweep's self-test.** Task 0 Step 0.9 created `$X/t13_engine_refs.py` and `$X/t13_engine_refs_selftest.py`.
```
timeout 120 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t13_engine_refs_selftest.py"
```
Expected: `T13-SELFTEST PASS`.

- [ ] **Step 12.2: Entry check. Commits 1 and 2 left only this task's engine references.** The engine is still present at this point.
```
git -C "$WT" status --short
timeout 300 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t13_engine_refs.py" > "$X/t12_entry_refs.txt"; echo rc=$?
grep -E '^(EXECUTABLE|MENTION-OUTSIDE-ALLOWED)' "$X/t12_entry_refs.txt" | awk '{print $2}' | cut -d: -f1 | sort -u | grep -v '^helao/core/servers/'
```
Expected: `git status` lists only Task 11's changes (` D helao/core/servers/CLAUDE.md`, `?? helao/hexagon/app/CLAUDE.md`, ` M CLAUDE.md`, ` M helao/deploy/hte/drivers/spec/andor/CLAUDE.md` and the 38 ` M` `.py` files Task 11 names); then `rc=1`; then **only** paths from this list, each at most once:
```
helao/core/tests/test_bokeh_theme.py
helao/core/tests/test_palette.py
helao/hexagon/tests/native_fixtures.py
helao/hexagon/tests/test_action_host_member_coverage.py
helao/hexagon/tests/test_action_session_port.py
helao/hexagon/tests/test_estop_finish_race.py
helao/hexagon/tests/test_native_artifact_store.py
helao/hexagon/tests/test_native_data_file.py
helao/hexagon/tests/test_native_data_sink.py
helao/hexagon/tests/test_native_data_stream.py
helao/hexagon/tests/test_native_finalizer.py
helao/hexagon/tests/test_native_meta_writer.py
helao/hexagon/tests/test_orch_host_member_coverage.py
helao/hexagon/tests/test_orch_host_surface.py
helao/hexagon/tests/test_ws_consumer_parity.py
```
Any other path means a commit-1 or commit-2 task left an engine reference behind. STOP and report it. Do not fix it here. Some listed paths may be absent, because Task 5 may have already removed its own imports.

- [ ] **Step 12.3: The traps doc is already out of the directory (P-H.1).**
```
test ! -e "$WT/helao/core/servers/CLAUDE.md" && test -f "$WT/helao/hexagon/app/CLAUDE.md" && echo CLAUDE-MD-MOVED
diff <(git -C "$WT" show HEAD:helao/core/servers/CLAUDE.md | tail -n +2) <(tail -n +2 "$WT/helao/hexagon/app/CLAUDE.md") && echo CLAUDE-MD-BODY-INTACT
```
Expected: `CLAUDE-MD-MOVED`, `CLAUDE-MD-BODY-INTACT`. If the first is missing, Task 11 has not run: STOP, because the `rm -rf` below would destroy the doc.

- [ ] **Step 12.4: Delete the engine, `__pycache__` included (D-B7b.9).**
```
rm -rf "$WT/helao/core/servers"
test -e "$WT/helao/core/servers" && echo STILL-THERE || echo ENGINE-DIR-GONE
git -C "$WT" status --short -- helao/core/servers | grep -c '^ D '
git -C "$WT" status --short -- helao/hexagon/app/CLAUDE.md
```
Expected: `ENGINE-DIR-GONE`; `18` (the 17 modules and the moved `CLAUDE.md`); `?? helao/hexagon/app/CLAUDE.md`.

- [ ] **Step 12.5: `test_action_session_port.py`: delete the legacy-Active test (§5.4).** Delete this block, including the two blank lines after it:

```python
def test_the_legacy_active_satisfies_the_port() -> None:
    """The collaborators must keep working against a grafted legacy Active.

    Until B7 the graft is what production runs, so re-pointing the collaborators
    at the Protocol must not break the object they are bound to today.
    """
    from helao.core.servers.base import Active

    missing = [m for m in _protocol_members() if not hasattr(Active, m)]
    # Instance attributes set in __init__ are not class attributes; only the
    # methods are checkable this way, which is what matters for the binding.
    missing = [m for m in missing if callable(getattr(ActionSessionPort, m, None))]
    assert missing == [], f"legacy Active lacks port members: {missing}"


```

It is an engine self-test. Its subject, the legacy `Active`, no longer exists. `test_action_session_implements_every_port_method` in the same file keeps the native half.

- [ ] **Step 12.6: `test_estop_finish_race.py`: only the hexagon flavour stays (§5.4).** Make three edits.

Replace the docstring's last paragraph:
```
Both orchestrators route through ``RunLifecycle`` / ``EstopController``, so each
test runs against the legacy ``Orch`` and the hexagon ``OrchHost``.
```
with:
```
The tests drive the hexagon ``OrchHost`` through ``RunLifecycle`` /
``EstopController``. Until B7b each one also ran against the legacy ``Orch``,
which B7b deleted.
```
Delete the line `from helao.core.servers.orch import Orch`. From `FLAVOURS`, delete the line `    pytest.param(Orch, "_init_collaborators", id="legacy"),`. `FLAVOURS` keeps its single `hexagon` entry, and the `@pytest.mark.parametrize("cls,init", FLAVOURS)` decorators stay unchanged.

- [ ] **Step 12.7: The ratchet loses its `legacy` probe (§5.4, P-H.2).** In `helao/hexagon/tests/test_engine_import_ratchet.py`, work inside the `_PROBE` string. Delete the line `if sys.argv[2] == "native":`, and dedent that branch's body by four spaces, including any lines Task 8 added to it. Then delete the whole `else:` branch that follows it:
```
else:
    from helao.core.servers.base_api import BaseAPI
    from helao.core.servers.orch_api import OrchAPI

    hosts = {
        "BaseAPI": BaseAPI("SIM", "SIM", "ratchet", 1.0),
        "OrchAPI": OrchAPI("ORCH", "ORCH", "ratchet", 3.0),
    }
```
On `64f2cf15` the result reads as follows. Task 8's third host entry sits inside the same dict:
```
from helao.hexagon.app.action_host import ActionHost
from helao.hexagon.app.orch_host import OrchHost

hosts = {
    "ActionHost": ActionHost("SIM", "SIM", "ratchet", 1.0, helao_cfg=cfg),
    "OrchHost": OrchHost("ORCH", "ORCH", "ratchet", version=3.0, helao_cfg=cfg),
}
```
In `_probe`, replace:
```python
def _probe(mode: str) -> dict:
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE, str(CONFIG), mode],
```
with:
```python
def _probe() -> dict:
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE, str(CONFIG)],
```
and replace `), f"{mode} probe failed (rc={proc.returncode}):\n{proc.stderr[-4000:]}"` with `), f"native probe failed (rc={proc.returncode}):\n{proc.stderr[-4000:]}"`.

Replace the two fixtures:
```python
def native() -> dict:
    return _probe("native")


@pytest.fixture(scope="module")
def legacy() -> dict:
    return _probe("legacy")
```
with:
```python
def native() -> dict:
    return _probe()
```
Delete the last test, and the two blank lines before it, so that the file ends with the preceding test's last line and one newline:
```python


def test_every_legacy_route_is_built_by_action_api_route(legacy) -> None:
    for name, host in legacy["hosts"].items():
        assert host["installed"] == "helao.core.servers.base_api.ActionAPIRoute", (
            name,
            host["installed"],
        )
        assert host["api_routes"] > 0 and host["wrong_class"] == [], (name, host)
```

- [ ] **Step 12.8: `test_ws_consumer_parity.py` reads the native hosts (§5.5).** Replace:
```python
BASE_API_PATH = Path("helao/core/servers/base_api.py")
ORCH_API_PATH = Path("helao/core/servers/orch_api.py")
```
with:
```python
ACTION_HOST_PATH = Path("helao/hexagon/app/action_host.py")
ORCH_HOST_PATH = Path("helao/hexagon/app/orch_host.py")
```
In `test_ws_globstat_is_dead`, replace the first docstring line `"""No route registration for /ws_globstat exists on either API class --` with `"""No route registration for /ws_globstat exists on either native host --`. Then replace:
```python
    base_routes = extract_routes(BASE_API_PATH)
    orch_routes = extract_routes(ORCH_API_PATH)
    assert base_routes, "extractor found nothing in base_api.py -- inert glob?"
    assert orch_routes, "extractor found nothing in orch_api.py -- inert glob?"
```
with:
```python
    base_routes = extract_routes(ACTION_HOST_PATH)
    orch_routes = extract_routes(ORCH_HOST_PATH)
    assert base_routes, "extractor found nothing in action_host.py -- inert glob?"
    assert orch_routes, "extractor found nothing in orch_host.py -- inert glob?"
```
Task 15 rewrites this test into `test_ws_globstat_channel_is_gone` against the names above.

- [ ] **Step 12.9: Drop the engine glob from the two AST sweeps (§5.5).** Delete this line from `helao/core/tests/test_bokeh_theme.py` (l.555):
```
            *repo_root.glob("helao/core/servers/**/*.py"),
```
and this line from `helao/core/tests/test_palette.py` (l.1785):
```
            *REPO_ROOT.glob("helao/core/servers/**/*.py"),
```

- [ ] **Step 12.10: `pyproject.toml` (Q6).** Replace lines 30–57, the comment block that starts `# Five native re-body modules` and ends `# assert_region_holds_no_imports fails loud if that stops being true.`, and line 58, the `force-exclude` value, with exactly:
```
# One native re-body module under helao/hexagon/adapters/native/ is a
# VERBATIM, byte-identical copy of legacy code: sync_driver.py is the P2c
# re-body of helao/core/drivers/data/sync_driver.py (D1), pinned per-method by
# inspect.getsource source-parity tests (sync_fixtures.assert_source_parity).
# The legacy side is NOT black-formatted at line-length 88, so running black
# on either side of the pair would reformat it and break the byte-identity.
# BOTH SIDES are excluded: the invariant is "never reformatted", not
# "currently matches black's output", and a future black release can change
# its mind about either file. Every other native adapter, including its
# hand-written NativeSyncAdapter sibling (sync_adapter.py), is black-enforced
# like the rest of the repo. (No other black config: line length stays the
# default 88.)
#
# Until B7b this list also held four CARDS-P6 write collaborators
# (meta_writer, data_file, data_stream, finalizer) and their legacy twins
# under helao/core/servers/. B7b deleted the twins with the engine, and their
# source-parity pins with them, so those four are black-formatted now.
#
# Import SORTING is a different matter and is deliberately NOT excluded:
# `ruff check --select I` only moves import statements, which for this pair
# sit above the pinned region. sync_fixtures' assert_region_holds_no_imports
# fails loud if that stops being true.
force-exclude = 'helao/(hexagon/adapters/native/sync_driver|core/drivers/data/sync_driver)\.py'
```
Lines 1–29 (`[project]`, and `[tool.black]` through `target-version = ["py312"]`) are unchanged.

- [ ] **Step 12.11: Apply the commit-3 fragments of Task 5 and of Tasks 3–4**, exactly as Steps 12.E1–12.E3 and 12.G1–12.G5 directly below give them. They cover the parity pins, `native_fixtures.assert_source_parity`, the legacy conformance halves, the two member-coverage readers, and `test_orch_host_surface`'s `_legacy_orch_api_routes`. The black run in Step 12.12 requires Task 5's pins to be gone first.

#### Step 12.11, part A: the parity pins and the legacy conformance halves go (Steps 12.E1–12.E3)

It runs after `rm -rf helao/core/servers` has been done, or before it; the edits do not depend on the order.

Files:
- Modify: `helao/hexagon/tests/native_fixtures.py` (delete `import inspect` and `assert_source_parity`)
- Modify: `helao/hexagon/tests/test_native_data_file.py`, `test_native_data_stream.py`, `test_native_finalizer.py`, `test_native_meta_writer.py` (delete the legacy import, `METHODS` and `test_source_parity_with_legacy`; the docstring stops claiming a parity pin)
- Modify: `helao/hexagon/tests/test_native_artifact_store.py`, `test_native_data_sink.py` (`test_port_conformance_and_no_base_inheritance` → `test_port_conformance`, conformance half only)

**Plan decision P-E.6 (spec silent):** the conformance test is renamed to `test_port_conformance`. Its old name promises a `Base` check that no longer exists. The docstrings keep their provenance ("verbatim re-body of legacy X (path)"), add "deleted by B7b", and drop "Source-parity pin"; that phrase describes a check that no longer runs (D-B7b.10).

- [ ] **Step 12.E1: Write `$X/t12_native_tests.patch`** with the Write tool, with exactly this content. It applies on top of Task 5's result, and was verified against it.

```diff
--- a/helao/hexagon/tests/native_fixtures.py
+++ b/helao/hexagon/tests/native_fixtures.py
@@ -8,7 +8,6 @@
 
 Tests layer — may import anything (boundary rule)."""
 
-import inspect
 from datetime import datetime
 from pathlib import Path
 from types import SimpleNamespace
@@ -147,16 +146,3 @@
     action = mk_action(manual_action=manual_action, save_act=True)
     session, _ = mk_active(base, json_data_keys=["t", "v"], action=action)
     return base, session
-
-
-def assert_source_parity(native_cls, legacy_cls, methods):
-    """Byte-parity pin: each relocated method's source must be identical to
-    its legacy counterpart (methods contain no class-name references, so
-    straight equality holds for a verbatim copy)."""
-    diffs = []
-    for name in methods:
-        n_src = inspect.getsource(getattr(native_cls, name))
-        l_src = inspect.getsource(getattr(legacy_cls, name))
-        if n_src != l_src:
-            diffs.append(name)
-    assert not diffs, f"native methods drifted from legacy source: {diffs}"
--- a/helao/hexagon/tests/test_native_artifact_store.py
+++ b/helao/hexagon/tests/test_native_artifact_store.py
@@ -24,12 +24,9 @@
     return NativeArtifactStoreAdapter(config=None, clock=None)
 
 
-def test_port_conformance_and_no_base_inheritance():
-    from helao.core.servers.base import Base
-
+def test_port_conformance():
     store = _store()
     assert isinstance(store, ArtifactStorePort)  # runtime_checkable Protocol
-    assert not isinstance(store, Base)
 
 
 def test_factory_members(tmp_path):
--- a/helao/hexagon/tests/test_native_data_file.py
+++ b/helao/hexagon/tests/test_native_data_file.py
@@ -1,5 +1,5 @@
 """NativeDataFileWriter (P2b-1): verbatim re-body of legacy DataFileWriter
-(helao/core/servers/active_data_file.py). Source-parity pin + real-tmp-tree
+(helao/core/servers/active_data_file.py, deleted by B7b). Real-tmp-tree
 behavior checks for the §5.4 quirks: w+ truncate-on-create, filename autogen
 format, one-shot a+ header+%%+payload, save_data gate, posix
 PureWindowsPath+.strip("\\\\") path quirk, FileInfo recording."""
@@ -10,30 +10,8 @@
 
 from helao.core.models.file import HloFileGroup
 from helao.helpers.premodels import Action
-from helao.core.servers.active_data_file import DataFileWriter
 from helao.hexagon.adapters.native.data_file import NativeDataFileWriter
-from helao.hexagon.tests.native_fixtures import (
-    assert_source_parity,
-    make_base,
-    mk_action,
-    mk_active,
-)
-
-METHODS = [
-    "__init__",
-    "update_act_file",
-    "init_datafile",
-    "finish_hlo_header",
-    "log_data_set_output_file",
-    "_resolve_output_path",
-    "write_file",
-    "write_file_nowait",
-    "track_file",
-]
-
-
-def test_source_parity_with_legacy():
-    assert_source_parity(NativeDataFileWriter, DataFileWriter, METHODS)
+from helao.hexagon.tests.native_fixtures import make_base, mk_action, mk_active
 
 
 def _native_active(tmp_path, **action_over):
--- a/helao/hexagon/tests/test_native_data_sink.py
+++ b/helao/hexagon/tests/test_native_data_sink.py
@@ -20,12 +20,9 @@
     return base, active, dflt, NativeDataSinkAdapter().for_action(active)
 
 
-def test_port_conformance_and_no_base_inheritance():
-    from helao.core.servers.base import Base
-
+def test_port_conformance():
     sink = NativeDataSinkAdapter()
     assert isinstance(sink, DataSinkPort)
-    assert not isinstance(sink, Base)
 
 
 def test_unbound_raises():
--- a/helao/hexagon/tests/test_native_data_stream.py
+++ b/helao/hexagon/tests/test_native_data_stream.py
@@ -1,5 +1,5 @@
 """NativeDataStreamer (P2b-1): verbatim re-body of legacy DataStreamer
-(helao/core/servers/active_data_stream.py). Source-parity pin + drain-loop
+(helao/core/servers/active_data_stream.py, deleted by B7b). Drain-loop
 behavior on a real MultisubscriberQueue + tmp tree: lazy open on first
 matching packet, json_data_keys inference, %% exactly once, non-serializable
 -> error line, string payload raw, listen_uuids filter, queued/written
@@ -13,31 +13,10 @@
 
 from helao.core.models.data import DataModel, DataPackageModel
 from helao.core.models.hlostatus import HloStatus
-from helao.core.servers.active_data_stream import DataStreamer
 from helao.hexagon.adapters.native.data_file import NativeDataFileWriter
 from helao.hexagon.adapters.native.data_stream import NativeDataStreamer
 from helao.hexagon.tests.native_fixtures import make_base, mk_active
 
-METHODS = [
-    "__init__",
-    "get_realtime",
-    "get_realtime_nowait",
-    "write_live_data",
-    "enqueue_data_dflt",
-    "_build_data_package",
-    "enqueue_data",
-    "enqueue_data_nowait",
-    "assemble_data_msg",
-    "add_new_listen_uuid",
-    "log_data_task",
-]
-
-
-def test_source_parity_with_legacy():
-    from helao.hexagon.tests.native_fixtures import assert_source_parity
-
-    assert_source_parity(NativeDataStreamer, DataStreamer, METHODS)
-
 
 def _native_active(tmp_path):
     base = make_base(str(tmp_path / "RUNS_ACTIVE"))
--- a/helao/hexagon/tests/test_native_finalizer.py
+++ b/helao/hexagon/tests/test_native_finalizer.py
@@ -1,6 +1,6 @@
 """NativeActionFinalizer (P2b-1): verbatim re-body of legacy ActionFinalizer
-(helao/core/servers/active_finalizer.py) — the ce846da1 join-drain-close
-chain. Source-parity pin + behavior on real tmp trees with a full native
+(helao/core/servers/active_finalizer.py, deleted by B7b) — the ce846da1
+join-drain-close chain. Behavior on real tmp trees with a full native
 collaborator set: finish drains queued data BEFORE closing
 handles, closes every file, cancels data_logger, writes the final -act.yml,
 schedules move_dir (manual included -- it is the journal eviction
@@ -20,29 +20,10 @@
 from helao.core.error import ErrorCodes
 from helao.core.models.data import DataModel
 from helao.core.models.hlostatus import HloStatus
-from helao.core.servers.active_finalizer import ActionFinalizer
 from helao.hexagon.adapters.native.finalizer import NativeActionFinalizer
 from helao.hexagon.adapters.native.meta_writer import NativeMetaFileWriter
 from helao.hexagon.tests.native_fixtures import make_base, mk_action, mk_active
 
-METHODS = [
-    "__init__",
-    "split_and_keep_active",
-    "split_and_finish_prev_uuids",
-    "finish_all",
-    "split",
-    "substitute",
-    "finish",
-    "_finish",
-    "finish_manual_action",
-]
-
-
-def test_source_parity_with_legacy():
-    from helao.hexagon.tests.native_fixtures import assert_source_parity
-
-    assert_source_parity(NativeActionFinalizer, ActionFinalizer, METHODS)
-
 
 def _grafted_active(tmp_path, **action_over):
     """A session over a bare host (native collaborators and meta writer by
--- a/helao/hexagon/tests/test_native_meta_writer.py
+++ b/helao/hexagon/tests/test_native_meta_writer.py
@@ -1,5 +1,5 @@
 """NativeMetaFileWriter (P2b-1): verbatim re-body of legacy MetaFileWriter
-(helao/core/servers/base_meta_writer.py). Source-parity-pinned + behavior
+(helao/core/servers/base_meta_writer.py, deleted by B7b). Behavior
 checks on a real tmp tree (atomic tmp+os.replace, trailing newline,
 file_type first key, RUNS_ACTIVE->RUNS_DIAG manual swap, md5 conn keys)."""
 
@@ -10,27 +10,8 @@
 import pytest
 
 from helao.core.models.run_dir import RunDir
-from helao.core.servers.base_meta_writer import MetaFileWriter
 from helao.hexagon.adapters.native.meta_writer import NativeMetaFileWriter
-from helao.hexagon.tests.native_fixtures import (
-    assert_source_parity,
-    make_base,
-    mk_action,
-)
-
-METHODS = [
-    "__init__",
-    "_write_meta_atomic",
-    "write_act",
-    "write_exp",
-    "write_seq",
-    "new_file_conn_key",
-    "dflt_file_conn_key",
-]
-
-
-def test_source_parity_with_legacy():
-    assert_source_parity(NativeMetaFileWriter, MetaFileWriter, METHODS)
+from helao.hexagon.tests.native_fixtures import make_base, mk_action
 
 
 def _swap(base, tmp_path):
```

- [ ] **Step 12.E2: Apply it.**

```
patch -p1 -d "$WT" --dry-run < "$X/t12_native_tests.patch" && patch -p1 -d "$WT" < "$X/t12_native_tests.patch"
```
Expected: seven `checking file helao/hexagon/tests/…` lines, then seven `patching file …` lines (`native_fixtures.py` and the six `test_native_*`), and no failed hunk.

- [ ] **Step 12.E3: Run the touched files with the engine gone.** This was measured with `helao/core/servers/` deleted from a copy of the tree.

```
for f in helao/hexagon/tests/test_native_artifact_store.py helao/hexagon/tests/test_native_data_file.py helao/hexagon/tests/test_native_data_sink.py helao/hexagon/tests/test_native_data_stream.py helao/hexagon/tests/test_native_finalizer.py helao/hexagon/tests/test_native_meta_writer.py helao/core/tests/test_run_state_wiring.py helao/hexagon/tests/test_estop_fixes.py; do printf '%s ' "$f"; timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -m pytest -q -p no:cacheprovider --color=no -W ignore "$f" 2>&1 | tail -1; done
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t5_engine_refs.py" "$WT"; echo refs-rc=$?
```
Expected: `6`, `11`, `5`, `7`, `6`, `6`, `15`, `38` passed, in that order. Each file with a pin loses exactly its `test_source_parity_with_legacy`. Then no reference lines and `refs-rc=0`. pyright on the same eight files plus `native_fixtures.py` (files analyzed 9): `test_native_finalizer.py` 4, `test_run_state_wiring.py` 2, `test_estop_fixes.py` 32, every other file 0.

**Files for the controller's commit (commit 3, this fragment):** `helao/hexagon/tests/native_fixtures.py`, `helao/hexagon/tests/test_native_artifact_store.py`, `helao/hexagon/tests/test_native_data_file.py`, `helao/hexagon/tests/test_native_data_sink.py`, `helao/hexagon/tests/test_native_data_stream.py`, `helao/hexagon/tests/test_native_finalizer.py`, `helao/hexagon/tests/test_native_meta_writer.py`. All of them are `black`-clean after the patch (checked).

**Hand-offs to other tasks (not this fragment's edits):**
- `helao/hexagon/adapters/native/data_file.py:67`, `data_stream.py:64` and `finalizer.py:63` each carry the same docstring paragraph, which describes current behaviour through the pin: "``__init__`` is byte-pinned against its legacy twin by ``assert_source_parity`` (see ``native_fixtures``), and an annotation in the signature would change ``inspect.getsource(__init__)`` and break the pin. A class-level annotation gives static checking without touching the pinned method source." After this fragment, the pin and the helper no longer exist. The spec (D-B7b.10) lists only `data_file.py:67`, but the other two need the same fix (Task 11).
- After this fragment, the provenance strings `helao/core/servers/<module>.py` stay in the four module docstrings of the `test_native_*` files. They are slash paths, not dotted module names. Task 13's string sweep must either not match slash paths or list these four files as provenance.

#### Step 12.11, part B: the member-coverage readers and the orchestrator-surface reader (Steps 12.G1–12.G5)

These are commit-3 edits. Apply them after `rm -rf helao/core/servers`. They compose with Task 8, which deleted `test_a_native_orch_host_is_not_grafted` from `test_orch_host_surface.py` and added `test_the_host_binds_its_health_adapter_and_starts_no_legacy_heartbeat` there. The fragment touches neither of those tests.

Files:
- Modify: `helao/hexagon/tests/test_action_host_member_coverage.py`: the module docstring (lines 23-24), imports and `BASE_PY` (29-34), `CONTRACTUAL_PRIVATE` and `_base_public_members` (99-134)
- Modify: `helao/hexagon/tests/test_orch_host_member_coverage.py`: the module docstring (line 22), imports and `SEARCH_DIRS` (29-46), `CONSUMERS` (line 70), `orch_contract` (74-90), and `test_the_contract_extraction_is_not_vacuous` (185-190)
- Modify: `helao/hexagon/tests/test_orch_host_surface.py`: delete `_legacy_orch_api_routes` and `test_every_orch_api_route_exists_on_the_host` (lines 53-100 on `64f2cf15`)

**Interfaces:**
- Consumes: Task 3's two JSON files (`["members"]`).
- Produces:
  - `test_orch_host_member_coverage.orch_contract() -> set[str]`, which is the frozen members ∪ `live_contract()`;
  - the new `test_orch_host_member_coverage.live_contract() -> set[str]`, the AST walk over `helao/hexagon/app` only;
  - `FROZEN_CONTRACT: Path`;
  - `test_action_host_member_coverage.BASE_SURFACE: Path`, which replaces `BASE_PY`;
  - `NOT_YET_PORTED` and `DELIBERATELY_ABSENT`, both unchanged. `test_orch_host_surface.py` still imports `NOT_YET_PORTED`.

- [ ] **Step 12.G1: `test_action_host_member_coverage.py`.** Make these three edits.

Edit 1, the module docstring. Old:
```
The test fails when the gap **grows** — a new ``Base`` member, or a host member
removed — rather than while it merely persists. A test that is permanently red
teaches people to ignore it; this repo already has one such case in
``test_palette``'s stale "EXPECTED TO FAIL" docstring.
```
New:
```
The test fails when the gap **grows** — a host member removed — rather than
while it merely persists. ``Base`` itself is gone (B7b deleted the engine); its
member surface was frozen first, into ``checklists/base_member_surface.json``,
and that snapshot shrinks only when a member is retired on purpose. A test
that is permanently red teaches people to ignore it; this repo already has
one such case in ``test_palette``'s stale "EXPECTED TO FAIL" docstring.
```

Edit 2, the imports and the path. Old:
```python
import ast
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
BASE_PY: Final[Path] = REPO_ROOT / "helao/core/servers/base.py"
```
New:
```python
import ast
import json
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
BASE_SURFACE: Final[Path] = (
    REPO_ROOT / "helao/hexagon/tests/checklists/base_member_surface.json"
)
```

Edit 3. Delete the whole `CONTRACTUAL_PRIVATE` block, from the `#: Underscore-prefixed ``Base`` members…` comment to its closing `)`, and replace the whole `def _base_public_members()` function with:
```python
def _base_public_members() -> set[str]:
    """Every public method, contractual private, and ``self.x`` on ``Base``.

    Read from the snapshot B7b froze from ``helao/core/servers/base.py``
    before deleting it. The contractual privates (``_write_meta_atomic``,
    ``_dispatch_queued_action``, ``_ws_relay``) are in it: a collaborator
    calls them back through ``self.base.<name>``, and missing
    ``_write_meta_atomic`` once made every ``write_act`` fail silently.
    """
    return set(json.loads(BASE_SURFACE.read_text(encoding="utf-8"))["members"])
```
`import ast` stays, because `_self_assigned` uses it. The four tests keep their names and bodies, and the `> 60` floor now runs against the snapshot.

- [ ] **Step 12.G2: `test_orch_host_member_coverage.py`.** Make these four edits.

Edit 1, the module docstring. Old:
```
the authority; the spec's number is the stale one.
```
New:
```
the authority; the spec's number is the stale one. By B7b it had grown
to 138, and B7b froze that set into ``checklists/orch_member_contract.json``
before deleting the engine, whose ``orch_api`` supplied 35 of them.
```

Edit 2, from `import ast` through the closing `)` of `SEARCH_DIRS`. Old:
```python
import ast
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]

#: Where a consumer module may live. B3a MOVES four of them from the first
#: directory to the second, and the contract must not notice.
#:
#: It did notice, once. With only ``helao/core/servers`` listed, moving
#: orch_queues/orch_persist/orch_estop/orch_lifecycle dropped the measured
#: contract from 136 members to 115 -- the ratchet quietly got weaker at
#: exactly the moment work progressed, and 21 members it was tracking
#: turned into "already done" without anyone implementing them.
SEARCH_DIRS: Final[tuple[Path, ...]] = (
    REPO_ROOT / "helao/core/servers",
    REPO_ROOT / "helao/hexagon/app",
)
```
New:
```python
import ast
import json
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]

#: Where a consumer module lives. Until B7b this also listed
#: ``helao/core/servers``, and the contract must not notice its deletion.
#:
#: It did notice, once. With only ``helao/core/servers`` listed, moving
#: orch_queues/orch_persist/orch_estop/orch_lifecycle dropped the measured
#: contract from 136 members to 115 -- the ratchet quietly got weaker at
#: exactly the moment work progressed, and 21 members it was tracking
#: turned into "already done" without anyone implementing them. Deleting
#: the engine would have done the same to 35 members, which is why the
#: contract measured with it present is frozen in FROZEN_CONTRACT.
SEARCH_DIRS: Final[tuple[Path, ...]] = (REPO_ROOT / "helao/hexagon/app",)

#: The 138-member contract B7b measured while ``orch_api`` and the engine
#: collaborators still existed. It shrinks only when a member is retired on
#: purpose; the live extraction below can add to it but never subtract.
FROZEN_CONTRACT: Final[Path] = (
    REPO_ROOT / "helao/hexagon/tests/checklists/orch_member_contract.json"
)
```

Edit 3, the end of `CONSUMERS` and the head of `orch_contract`. Old:
```python
    "orch_global_params",
    "orch_unpack",
    "orch_api",
)


def orch_contract() -> set[str]:
    """Every ``Orch`` member a collaborator or the API layer reaches for.

    Two shapes, because the collaborators alias the back-reference before
    use (``orch = self.orch`` appears 21 times in orch_dispatch alone):
    ``orch.<name>`` and ``self.orch.<name>``.
    """
    found: set[str] = set()
    for mod in CONSUMERS:
        path = next(
            (d / f"{mod}.py" for d in SEARCH_DIRS if (d / f"{mod}.py").exists()), None
        )
        assert path is not None, (
            f"consumer module {mod!r} found in neither {SEARCH_DIRS[0]} nor "
            f"{SEARCH_DIRS[1]}. Skipping it silently would shrink the contract "
            "and weaken this ratchet, which is the one failure it cannot afford."
        )
```
New. The rest of the old function body, from `tree = ast.parse(...)` to `return found`, stays as it is and now belongs to `live_contract`:
```python
    "orch_global_params",
    "orch_unpack",
)


def orch_contract() -> set[str]:
    """The frozen B7b contract, plus anything the native consumers now reach for."""
    frozen = json.loads(FROZEN_CONTRACT.read_text(encoding="utf-8"))["members"]
    return set(frozen) | live_contract()


def live_contract() -> set[str]:
    """Every orchestrator member the native consumer modules reach for today.

    Two shapes, because the collaborators alias the back-reference before
    use (``orch = self.orch`` appears 21 times in orch_dispatch alone):
    ``orch.<name>`` and ``self.orch.<name>``.
    """
    found: set[str] = set()
    for mod in CONSUMERS:
        path = next(
            (d / f"{mod}.py" for d in SEARCH_DIRS if (d / f"{mod}.py").exists()), None
        )
        assert path is not None, (
            f"consumer module {mod!r} not found in {SEARCH_DIRS}. Skipping it "
            "silently would shrink the contract and weaken this ratchet, which "
            "is the one failure it cannot afford."
        )
```

Edit 4, the non-vacuity test (P-G.5). Old:
```python
    for known in ("action_dq", "globalstatusmodel", "_ensure_run_id", "add_sequence"):
        assert known in contract, f"{known} missing from the extraction"
```
New:
```python
    for known in ("action_dq", "globalstatusmodel", "_ensure_run_id", "add_sequence"):
        assert known in contract, f"{known} missing from the extraction"
    # The frozen half alone would clear the floor above, so the live walk
    # needs its own: 103 members when B7b froze, 96 once it removed the graft.
    live = live_contract()
    assert len(live) > 90, f"only {len(live)} live members found; walk is inert"
```

- [ ] **Step 12.G3: `test_orch_host_surface.py`.** Delete the function `_legacy_orch_api_routes` and the function `test_every_orch_api_route_exists_on_the_host`. Delete from the line `def _legacy_orch_api_routes() -> set[str]:` up to, but not including, `def test_estop_is_registered_exactly_once():`. Nothing else in the file uses either name (grep: 0 hits). Leave `import json`, `import tempfile` and `from pathlib import Path` in place, because `CHECKLIST` still uses `Path`.

- [ ] **Step 12.G4: Run the three files and measure the contract.** Create `$X/t12_counts.py`:

```python
"""B7b Task 12: member-contract sizes once the engine is gone."""

import json

from helao.hexagon.tests import test_action_host_member_coverage as act
from helao.hexagon.tests import test_orch_host_member_coverage as orc

frozen = set(json.loads(orc.FROZEN_CONTRACT.read_text(encoding="utf-8"))["members"])
print(
    f"T11 base={len(act._base_public_members())}"
    f" orch_contract={len(orc.orch_contract())} live={len(orc.live_contract())}"
    f" live_not_frozen={sorted(orc.live_contract() - frozen)}"
)
```

```
for f in helao/hexagon/tests/test_action_host_member_coverage.py helao/hexagon/tests/test_orch_host_member_coverage.py helao/hexagon/tests/test_orch_host_surface.py; do timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -m pytest -q -p no:cacheprovider --color=no "$f" 2>&1 | tail -1; done
timeout 120 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t12_counts.py" 2>/dev/null | grep '^T11'
```
Expected: `4 passed…`, `5 passed…`, `10 passed…`, then `T11 base=89 orch_contract=138 live=96 live_not_frozen=[]`.

About `live=96`: measured on `64f2cf15`, with `HexagonGraft`/`graft_hexagon_loop` removed from the walk, the live walk gives 96. The seven members it loses are `clear_error`, `clear_estop`, `skip`, `start`, `start_loop`, `update_nonblocking` and `update_status`; the frozen half keeps all of them. Without the engine present and before Task 8, it measured 103. If Task 8 changed another consumer module and the number differs, it must still be > 90, `orch_contract` must be 138, and `live_not_frozen` must be `[]`. Anything else: STOP.

The `10 passed` for the surface file is 11 (commit 1), minus the not-grafted test Task 8 deleted, plus the health test Task 8 added, minus the one this fragment deletes.

- [ ] **Step 12.G5: Red-check: the snapshots are load-bearing.** Add a member that no host has to each JSON; each ratchet must fail; the helper restores both files. Create `$X/t12_probes_members.json` with exactly this content:
```json
[
  {"file": "helao/hexagon/tests/checklists/base_member_surface.json",
   "old": "  \"members\": [\n", "new": "  \"members\": [\n    \"zz_b7b_red_probe\",\n",
   "test": "helao/hexagon/tests/test_action_host_member_coverage.py",
   "expect": "FAILED helao/hexagon/tests/test_action_host_member_coverage.py::test_no_new_gap_has_opened_in_the_host"},
  {"file": "helao/hexagon/tests/checklists/orch_member_contract.json",
   "old": "  \"members\": [\n", "new": "  \"members\": [\n    \"zz_b7b_red_probe\",\n",
   "test": "helao/hexagon/tests/test_orch_host_member_coverage.py",
   "expect": "FAILED helao/hexagon/tests/test_orch_host_member_coverage.py::test_no_new_gap_has_opened_in_the_host"}
]
```
**[tool timeout 600 s]**:
```
timeout 580 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t0_mutate.py" "$X/t12_probes_members.json"
git -C "$WT" diff --stat -- helao/hexagon/tests/checklists/base_member_surface.json helao/hexagon/tests/checklists/orch_member_contract.json
```
Expected: two `RED rc=1 … :: expect found :: RESTORED …` lines and `MUTATE-PASS` (measured in the planning dry run: `1 failed, 3 passed` and `1 failed, 4 passed`); then nothing from `diff --stat`, because both files are back to their committed content.

**Files for the controller's commit (commit 3, with the rest of Task 12):** `helao/hexagon/tests/test_action_host_member_coverage.py`, `helao/hexagon/tests/test_orch_host_member_coverage.py`, `helao/hexagon/tests/test_orch_host_surface.py`.

#### Step 12.12 onward

- [ ] **Step 12.12: Black the four collaborators whose twins died (Q6, P-H.4).** Create `$X/t12_astcmp.py`:
```python
"""B7b Task 12: exit 1 unless each named file's ast.dump is equal in <before_dir> and <after_dir>.

Usage: python t12_astcmp.py <before_dir> <after_dir> <stem> [<stem> ...]
"""

import ast
import sys

before, after, stems = sys.argv[1], sys.argv[2], sys.argv[3:]


def dump(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return ast.dump(ast.parse(fh.read()))


bad = [s for s in stems if dump(f"{before}/{s}.py") != dump(f"{after}/{s}.py")]
print("AST-EQUAL" if not bad else f"AST DIFFERS: {bad}")
sys.exit(1 if bad else 0)
```
Then:
```
rm -rf "$X/t12_native_before" && mkdir -p "$X/t12_native_before"
cp "$WT"/helao/hexagon/adapters/native/{meta_writer,data_file,data_stream,finalizer}.py "$X/t12_native_before/"
timeout 300 conda run -n helao --no-capture-output --cwd "$WT" black helao/hexagon/adapters/native/meta_writer.py helao/hexagon/adapters/native/data_file.py helao/hexagon/adapters/native/data_stream.py helao/hexagon/adapters/native/finalizer.py
timeout 120 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t12_astcmp.py" "$X/t12_native_before" "$WT/helao/hexagon/adapters/native" meta_writer data_file data_stream finalizer
```
Expected: black reports `3 files reformatted, 1 file left unchanged.`, measured on `64f2cf15` plus Step 12.10. If Task 5 edited one of these four files, the count may differ, but `meta_writer.py` has nothing for black to change. Then `AST-EQUAL`. If black reports `No Python files are present to be formatted`, `pyproject.toml` still excludes them: STOP.

- [ ] **Step 12.13: Run the touched tests, one per process.**
```
for f in helao/hexagon/tests/test_action_session_port.py helao/hexagon/tests/test_estop_finish_race.py helao/hexagon/tests/test_ws_consumer_parity.py helao/core/tests/test_bokeh_theme.py helao/core/tests/test_palette.py helao/hexagon/tests/test_engine_import_ratchet.py; do echo "== $f"; timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -m pytest -q -p no:cacheprovider --color=no "$f" 2>&1 | tail -1; done
```
Expected (measured in the planning dry run, with the engine removed):
- `test_action_session_port.py`: `9 passed`, where `64f2cf15` had 10;
- `test_estop_finish_race.py`: `7 passed`, where it had 14;
- `test_ws_consumer_parity.py`: `5 passed`. That count was measured with the native paths. On this tree it also needs Task 9's engine-free `harness/ws_frames.py`;
- `test_bokeh_theme.py`: `48 passed`;
- `test_palette.py`: `183 passed`;
- `test_engine_import_ratchet.py`: `5 passed`. Task 8 and Task 9 left it at 6; `test_every_legacy_route_is_built_by_action_api_route` is gone.

Also run the Task 5 and Tasks 3–4 files named in Step 12.11, with the counts their fragments give. Any `ModuleNotFoundError: No module named 'helao.core.servers'` means an engine reference survived: STOP.

- [ ] **Step 12.14: The worktree holds only this task's changes.**
```
git -C "$WT" status --short | grep -v -E '^ D helao/core/servers/| M helao/hexagon/tests/(test_action_session_port|test_estop_finish_race|test_engine_import_ratchet|test_ws_consumer_parity)\.py$| M helao/core/tests/(test_bokeh_theme|test_palette)\.py$| M pyproject\.toml$| M helao/hexagon/adapters/native/(data_file|data_stream|finalizer)\.py$|^\?\? helao/hexagon/app/CLAUDE\.md$'
```
Expected: only the files the Step 12.11 fragments name, plus Task 11's files (its two `CLAUDE.md` edits and its 38 `.py` files; `data_file.py`, `data_stream.py` and `finalizer.py` are in both lists). Anything else: STOP.

**Files for the controller's commit** (commit 3, together with Tasks 11 and 13):
- deleted: `helao/core/servers/` (all 18 tracked paths). Stage the deletions with `git -C "$WT" add -A helao/core/servers`;
- modified: `helao/hexagon/tests/test_action_session_port.py`, `helao/hexagon/tests/test_estop_finish_race.py`, `helao/hexagon/tests/test_engine_import_ratchet.py`, `helao/hexagon/tests/test_ws_consumer_parity.py`, `helao/core/tests/test_bokeh_theme.py`, `helao/core/tests/test_palette.py`, `pyproject.toml`, `helao/hexagon/adapters/native/data_file.py`, `helao/hexagon/adapters/native/data_stream.py`, `helao/hexagon/adapters/native/finalizer.py`;
- plus the files of the Step 12.11 fragments.
- `black` before `git add`: all modified `.py` above. The four native collaborators are no longer force-excluded, and Step 12.12 already formatted them.

---

### Task 13: Commit 3 closes — no executable engine reference anywhere; the controller commit

**Files:** none edited. Scratch: `$X/t13_refs.txt`, `$X/run_tests_c3.txt`, `$X/F3.txt`, `$X/rut_c3.txt`, `$X/unit_c3.txt`.

**Interfaces:**
- Consumes: Tasks 11 and 12 complete; `$X/t13_engine_refs.py` and its self-test (Task 0 Step 0.9).
- Produces: commit 3. After it, `git ls-files helao/core/servers` is empty.

**Execution:** runs alone, after Task 12. Step 13.6 is the controller's.

- [ ] **Step 13.1: The executable-reference sweep is clean (spec §4.3 check).**
```
timeout 120 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t13_engine_refs_selftest.py"
timeout 300 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t13_engine_refs.py" | tee "$X/t13_refs.txt"; echo rc=$?
test -e "$WT/helao/core/servers" && echo ENGINE-DIR-PRESENT || echo ENGINE-DIR-GONE
```
Expected: `T13-SELFTEST PASS`; `swept <N> files` with N > 900, then `ENGINE-REFS CLEAN`, `rc=0`; `ENGINE-DIR-GONE`. Any `EXECUTABLE` or `MENTION-OUTSIDE-ALLOWED` line blocks the commit. (The sweep cannot see code inside a string constant; the one such case, the ratchet's `_PROBE` legacy branch, was deleted in Step 12.7, and `grep -c 'helao.core.servers.base_api' "$WT/helao/hexagon/tests/test_engine_import_ratchet.py"` must print `0`.)

- [ ] **Step 13.2: `run_unit_tests.py` and the standalone scripts, with the engine gone.**
```
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python run_unit_tests.py > "$X/rut_c3.txt" 2>&1; echo rc=$?
grep -c '^  [a-z_]*: PASS$' "$X/rut_c3.txt"; tail -1 "$X/rut_c3.txt"
```
**[background]** Launch `"$X/bg.sh" unit_c3_job "$X/t0_unit_sweep.sh" "$X/unit_c3.txt"`; then, **[tool timeout 600 s]**:
```
"$X/wait.sh" unit_c3_job
diff "$X/unit_c1.txt" "$X/unit_c3.txt" && echo UNIT-SCRIPTS-UNCHANGED
```
Expected: `rc=0`, `30`, `overall: PASS`; `rc=0` from `wait.sh`, `UNIT-SCRIPTS-UNCHANGED`.

- [ ] **Step 13.3: Both golden masters pass against their commit-1 references, which have not changed.**
```
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python helao/core/tests/test_orch_dispatch_golden_master.py --check 2>/dev/null | tail -1
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python helao/core/tests/test_active_golden_master.py --check 2>/dev/null | tail -1
git -C "$WT" diff --quiet HEAD~1 -- helao/core/tests/golden && git -C "$WT" diff --quiet -- helao/core/tests/golden && echo GOLDEN-UNCHANGED-SINCE-COMMIT-1
```
Expected: the two `CHECK PASSED` lines of Step 7.4; `GOLDEN-UNCHANGED-SINCE-COMMIT-1` (`HEAD~1` is commit 1 at this point).

- [ ] **Step 13.4: Guard and the full sweep against F0.**
```
timeout 120 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -c "import helao; print(helao.__file__)"
```
**[background]** Launch `"$X/bg.sh" run_tests_c3 timeout 5400 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python run_tests.py`; then, **[tool timeout 600 s]**, repeating while it prints `STILL-RUNNING`:
```
"$X/wait.sh" run_tests_c3
"$X/t0_failset.sh" "$X/run_tests_c3.txt" "$X/F3.txt" > /dev/null
comm -13 "$X/F0.txt" "$X/F3.txt"; echo new-failures-listed-above
grep -c 'ModuleNotFoundError' "$X/run_tests_c3.txt"
```
Expected: the worktree path; `rc=1`; nothing before `new-failures-listed-above`; `0`.

- [ ] **Step 13.5: The tree.**
```
git -C "$WT" status --short | grep -v '^ D helao/core/servers/' | LC_ALL=C sort > "$X/t13_status.txt"
git -C "$WT" status --short | grep -c '^ D helao/core/servers/'
wc -l < "$X/t13_status.txt"
```
Expected: `18` deleted engine paths; then the rest is Task 11's and Task 12's files exactly: `?? helao/hexagon/app/CLAUDE.md`, ` M CLAUDE.md`, ` M helao/deploy/hte/drivers/spec/andor/CLAUDE.md`, ` M pyproject.toml`, Task 11's 38 `.py` files, and Task 12's test files (`test_action_session_port.py`, `test_estop_finish_race.py`, `test_engine_import_ratchet.py`, `test_ws_consumer_parity.py`, `test_bokeh_theme.py`, `test_palette.py`, `native_fixtures.py`, the six `test_native_*.py`, `test_action_host_member_coverage.py`, `test_orch_host_member_coverage.py`, `test_orch_host_surface.py`), with `adapters/native/{data_file,data_stream,finalizer,meta_writer}.py` counted once. `wc -l` prints `58` (1 untracked doc + 2 `CLAUDE.md` edits + `pyproject.toml` + 38 + 16 test files). Any path in `$X/t13_status.txt` not named in Task 11 or Task 12 is a STOP.

- [ ] **Step 13.6: Controller commits (commit 3).** Stage by pathspec, so the deletions under `helao/core/servers` are included and nothing else slips in:
```
cd "$WT" && git -C "$WT" status --short | grep -E '^( M|\?\?) .*\.py$' | awk '{print $2}' > "$X/t13_black.txt"
xargs -a "$X/t13_black.txt" conda run -n helao --no-capture-output --cwd "$WT" black
git -C "$WT" add -A -- helao/core/servers helao/hexagon/app/CLAUDE.md CLAUDE.md helao/deploy/hte/drivers/spec/andor/CLAUDE.md pyproject.toml $(cat "$X/t13_black.txt")
git -C "$WT" status --short | grep -v '^[MDA] ' ; echo unstaged-listed-above
git -C "$WT" commit -F - <<'EOF'
refactor(b7b): delete the legacy engine (helao/core/servers)

Commit 3 of B7b (spec section 4.3):

- helao/core/servers/ removed, __pycache__ included; its traps doc moved to
  helao/hexagon/app/CLAUDE.md ("dispatch loop and host traps"); root
  CLAUDE.md describes ActionHost and OrchHost
- engine self-tests, the four source-parity pins, the legacy halves of two
  conformance tests and the ratchet's legacy probe deleted
- member-coverage ratchets read the frozen JSON snapshots; the WS consumer
  parity test reads the native hosts; the two palette/theme sweeps drop the
  engine glob
- pyproject force-exclude keeps only the sync_driver pair; the four P6
  collaborators are black-formatted (ast.dump unchanged)
- stale docstrings and messages that described current behaviour through
  deleted symbols fixed (D-B7b.10); provenance left alone

Every checkout that pulls this needs, once, from the repo root:
  rm -rf helao/core/servers        (Linux)
  rmdir /s /q helao\core\servers   (Windows cmd)
because git leaves the untracked __pycache__ behind.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01NxxPoGvJmVh5T4xSpVejFF
EOF
git -C "$WT" status --short; git -C "$WT" ls-files helao/core/servers | wc -l
```
Expected: black reports the formatted state (the four collaborators were already formatted in Step 12.12; everything else unchanged); nothing before `unstaged-listed-above`; after the commit, no status output and `0`.

---

### Task 14: Commit 4 — the package-gone probe, and the orchestrator checklist becomes native and exact

**Files:**
- Modify: `helao/hexagon/tests/test_engine_import_ratchet.py` (part A)
- Create: `helao/hexagon/tests/checklists/orch_openapi.json`; Delete: `helao/hexagon/tests/checklists/orch_openapi_legacy.json`; Modify: `helao/hexagon/tests/test_orch_host_surface.py` (part B)

**Interfaces:**
- Consumes: commit 3; Task 4's `$X/t4_native_surface.json`; the ratchet as Task 12 left it (`_probe()` with no argument).
- Produces: `test_the_engine_package_cannot_be_imported`; `test_orch_host_surface.CHECKLIST` pointing at `orch_openapi.json`; the tests `test_the_route_surface_matches_the_frozen_orchestrator_surface` and `test_parameter_schemas_match_the_frozen_orchestrator_surface`.

**Execution:** after Task 13's commit, alone. Part A first, then part B: part B's mutation probes (Steps 14.G3–14.G4) edit `orch_wait.py` and `orch_host.py`, which part A's ratchet probe imports. The drift record (spec §4.4 third bullet) needs no step: the five checklist IDs stay exactly as Task 0 recorded them, and gate 3 checks that. Step 14.c3 is the controller's.

#### Part A: the ratchet proves the package cannot be imported (D-B7b.9)

**Files:**
- Modify: `helao/hexagon/tests/test_engine_import_ratchet.py` (append one probe string and one test at end of file)

**Interfaces:**
- Consumes: the ratchet as Task 12 left it, with module-level `REPO_ROOT`, `os`, `subprocess`, `sys`, `json` and `Final` already imported.
- Produces: `test_the_engine_package_cannot_be_imported`. It is the one caller of `find_spec("helao.core.servers")` that `$X/t13_engine_refs.py` exempts.

**Execution:** part A runs first, then part B (part B's probes mutate `orch_host.py`, which this part's ratchet probe imports). Do not commit.

- [ ] **Step 14.a1: Append to the end of `helao/hexagon/tests/test_engine_import_ratchet.py`**, after two blank lines:

```python
_GONE_PROBE: Final[str] = r"""
import importlib.util, json
spec = importlib.util.find_spec("helao.core.servers")
try:
    import helao.core.servers.base  # noqa: F401
    base = "imported"
except ModuleNotFoundError:
    base = "ModuleNotFoundError"
where = None if spec is None else sorted(spec.submodule_search_locations or [spec.origin])
print("B7B-GONE " + json.dumps({"spec": where, "base": base}))
"""


def test_the_engine_package_cannot_be_imported() -> None:
    """D-B7b.9: B7b deleted ``helao/core/servers/``, and it must stay unimportable.

    ``helao/core/`` has no ``__init__.py`` and ``__pycache__`` is gitignored, so
    a ``git pull`` that deletes the tracked files leaves the directory behind
    on every checkout that ever ran the engine. While it exists,
    ``import helao.core.servers`` succeeds as a namespace package. Nothing
    imports it, so at runtime that is harmless, but it is exactly the silent
    import this ratchet exists to rule out. A fresh interpreter, because this
    pytest process may have imported anything.
    """
    proc = subprocess.run(
        [sys.executable, "-c", _GONE_PROBE],
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        capture_output=True,
        text=True,
        timeout=60,
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("B7B-GONE ")]
    assert (
        proc.returncode == 0 and len(lines) == 1
    ), f"probe failed (rc={proc.returncode}):\n{proc.stderr[-4000:]}"
    report = json.loads(lines[0][len("B7B-GONE ") :])
    assert report["spec"] is None, (
        f"helao.core.servers still resolves, to {report['spec']}. The engine's "
        "tracked files are gone, but git leaves the untracked __pycache__ "
        "directory behind, and a leftover helao/core/servers/ imports as a "
        "namespace package. Remove it once in this checkout, from the repo "
        "root: `rm -rf helao/core/servers` (Linux) or "
        "`rmdir /s /q helao\\core\\servers` (Windows cmd)."
    )
    assert report["base"] == "ModuleNotFoundError", report
```

`REPO_ROOT` is the ratchet's existing `Path(__file__).resolve().parents[3]`. The child is `sys.executable`, which is the `helao` env's interpreter under `conda run`. Its `PYTHONPATH` is replaced with the repo root alone, so the env's baked-in main-checkout path cannot leak in (§2.9). Black-clean as written (measured).

- [ ] **Step 14.a2: Red, then green. The probe fails on a stale `__pycache__` and names the fix.**
```
mkdir -p "$WT/helao/core/servers/__pycache__" && : > "$WT/helao/core/servers/__pycache__/base.cpython-314.pyc"
timeout 300 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -m pytest -q -p no:cacheprovider --color=no helao/hexagon/tests/test_engine_import_ratchet.py -k cannot_be_imported > "$X/t14_gone_red.txt" 2>&1; echo rc=$?
grep -c 'still resolves' "$X/t14_gone_red.txt"; grep -c 'rmdir /s /q helao' "$X/t14_gone_red.txt"; tail -1 "$X/t14_gone_red.txt"
rm -rf "$WT/helao/core/servers"
timeout 300 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -m pytest -q -p no:cacheprovider --color=no helao/hexagon/tests/test_engine_import_ratchet.py -k cannot_be_imported 2>&1 | tail -1
git -C "$WT" status --short -- helao/core/servers
```
Expected (measured): `rc=1`; `1` or more for each `grep -c`; `1 failed, <k> deselected …`; then `1 passed, <k> deselected …`. The final `git status` prints nothing, because the stale directory is untracked, gitignored and removed.

- [ ] **Step 14.a3: The whole ratchet passes.**
```
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -m pytest -q -p no:cacheprovider --color=no helao/hexagon/tests/test_engine_import_ratchet.py 2>&1 | tail -1
```
Expected: `6 passed` (Task 12's 5, plus this test).

**Files for the controller's commit** (commit 4, with Task 14's checklist part): `helao/hexagon/tests/test_engine_import_ratchet.py`.

#### Part B: re-freeze the orchestrator surface from `OrchHost`; the tests become exact (spec §4.4, §8)

**Files:**
- Create: `helao/hexagon/tests/checklists/orch_openapi.json` (77 routes)
- Delete: `helao/hexagon/tests/checklists/orch_openapi_legacy.json`
- Modify: `helao/hexagon/tests/test_orch_host_surface.py`, changing `CHECKLIST` and the two tests below it: `test_the_route_surface_matches_the_live_legacy_orchestrator` and `test_parameter_schemas_match_the_live_legacy_orchestrator`

**Interfaces:**
- Consumes:
  - Task 4's `openapi_capture.normalize`;
  - `$X/t4_native_surface.json`, the native capture Task 4 compared against legacy;
  - `test_orch_host_surface._host()`.
- Produces:
  - `test_orch_host_surface.CHECKLIST`, which now points at `checklists/orch_openapi.json`;
  - the tests `test_the_route_surface_matches_the_frozen_orchestrator_surface` and `test_parameter_schemas_match_the_frozen_orchestrator_surface`.

**Execution:** after part A of this task. No commit.

- [ ] **Step 14.G1: Create `$X/t14_freeze_orch_surface.py`, then freeze.**

```python
"""B7b Task 14: freeze the native orchestrator surface to checklists/orch_openapi.json.

Run once, from the repo root, with the repo on PYTHONPATH. Refuses to overwrite.
The format is harness.openapi_capture.capture_to_file's (indent=1, sort_keys).
"""

import json
import sys

from harness import openapi_capture
from helao.hexagon.tests import test_orch_host_surface as surface

target = surface.Path(surface.__file__).resolve().parent / "checklists/orch_openapi.json"
if target.exists():
    sys.exit(f"REFUSING to overwrite {target.name}")
captured = openapi_capture.normalize(surface._host().openapi())
with open(target, "w", encoding="utf-8") as fh:
    json.dump(captured, fh, indent=1, sort_keys=True)
    fh.write("\n")
routes = captured["routes"]
print(
    f"T14 routes={len(routes)} with_body={sum('body' in r for r in routes)}"
    f" ref_params={sum('ref' in p for r in routes for p in r['params'])}"
)
```

```
timeout 120 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t14_freeze_orch_surface.py" 2>/dev/null | grep '^T14'
timeout 120 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t14_freeze_orch_surface.py" 2>&1 | grep REFUSING
cmp "$WT/helao/hexagon/tests/checklists/orch_openapi.json" "$X/t4_native_surface.json" && echo SAME-AS-TASK4-NATIVE
rm "$WT/helao/hexagon/tests/checklists/orch_openapi_legacy.json"
```
Expected: `T14 routes=77 with_body=20 ref_params=3`, then `REFUSING to overwrite orch_openapi.json`, then `SAME-AS-TASK4-NATIVE`.

The `cmp` is what makes this more than a native self-snapshot. The file is byte-identical to the native capture whose params and bodies Task 4 showed equal to legacy on all 74 shared routes, taken on the same commit that legacy was measured on. If `cmp` differs, STOP: something between commit 1 and commit 4 changed the orchestrator surface, and the change needs its own review.

- [ ] **Step 14.G2: Point the tests at the new file and make them exact.** In `helao/hexagon/tests/test_orch_host_surface.py`, make two edits.

Old:
```python
CHECKLIST = (
    Path(__file__).resolve().parents[1] / "tests/checklists/orch_openapi_legacy.json"
)
```
New:
```python
#: Frozen from a live OrchHost by B7b (77 routes). Its params and bodies on
#: the 74 routes legacy OrchAPI also served were first shown equal to an
#: in-process OrchAPI capture while the engine still existed, and legacy's
#: own capture matched the launched-server checklist this file replaced.
CHECKLIST = Path(__file__).resolve().parents[1] / "tests/checklists/orch_openapi.json"
```

Then replace both whole functions, `test_the_route_surface_matches_the_live_legacy_orchestrator` and `test_parameter_schemas_match_the_live_legacy_orchestrator`, with:
```python
def test_the_route_surface_matches_the_frozen_orchestrator_surface():
    """Exact both ways: no frozen route missing, no unfrozen route added.

    Captured live, not hand-written: B1 measured its hand-written surface
    checklist stale, 9 routes listed with 5 marked GET where the live
    server had 19, every one POST. An added route is a surface change too,
    and the legacy-era version of this test could not see one.

    WebSockets are absent from openapi.json entirely, so this says nothing
    about ws_status/ws_data/ws_live; test_ws_consumer_parity covers those.
    """
    from harness import openapi_capture

    frozen = _by_key(json.loads(CHECKLIST.read_text(encoding="utf-8")))
    current = _by_key(openapi_capture.normalize(_host().openapi()))

    missing = sorted(k for k in frozen if k not in current)
    extra = sorted(k for k in current if k not in frozen)
    assert missing == [], f"frozen routes OrchHost no longer serves: {missing}"
    assert extra == [], f"routes OrchHost serves that are not frozen: {extra}"


def test_parameter_schemas_match_the_frozen_orchestrator_surface():
    """A route can be present, correctly tagged, and still reject every
    request its predecessor accepted -- a renamed parameter, a lost
    default, a changed type, a renamed enum member, a renamed body field.
    None of that shows in a path-set diff."""
    from harness import openapi_capture

    frozen = _by_key(json.loads(CHECKLIST.read_text(encoding="utf-8")))
    current = _by_key(openapi_capture.normalize(_host().openapi()))

    drifted = {
        key: {
            field: {"frozen": frozen[key].get(field), "host": current[key].get(field)}
            for field in ("params", "body")
            if frozen[key].get(field) != current[key].get(field)
        }
        for key in frozen
        if key in current and key[0] not in STUB_ROUTES
    }
    drifted = {key: fields for key, fields in drifted.items() if fields}
    assert drifted == {}, f"schema drift on {len(drifted)} route(s): {drifted}"
```

```
black -q "$WT/helao/hexagon/tests/test_orch_host_surface.py"
grep -c 'orch_openapi_legacy\|live_legacy_orchestrator' "$WT/helao/hexagon/tests/test_orch_host_surface.py"
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -m pytest -q -p no:cacheprovider --color=no helao/hexagon/tests/test_orch_host_surface.py 2>&1 | tail -1
```
Expected: `0`, then `10 passed…`.

- [ ] **Step 14.G3: Mutation probe 1: an enum member a route parameter references.** `checkcond` (`helao/hexagon/app/orch_wait.py:67-74`) is the `$ref` behind `check_condition`, `stop_condition` and `skip_condition` on `/ORCH/conditional_exp`, `/ORCH/conditional_stop` and `/ORCH/conditional_skip`. Renaming a member's value changes what a caller must send; before Task 4 the capture recorded these parameters as `type: null` and could not see it.

- [ ] **Step 14.G4: Mutation probe 2: a property of one route's request body.** Give `/update_status`'s embedded body field an alias. The handler is in `OrchHost._register_orch_routes` (the line `actionservermodel: ActionServerModel = Body({}, embed=True),`). The alias renames the body property a caller posts, `actionservermodel` becomes `action_server_model`, without touching the handler's code. Before Task 4, request bodies were never compared.

Both probes run through the Task 0 helper, which restores each file and verifies it by sha256. Create `$X/t14_probes.json` with exactly this content:
```json
[
  {"file": "helao/hexagon/app/orch_wait.py",
   "old": "    isnot = \"isnot\"\n", "new": "    isnot = \"is_not\"\n",
   "test": "helao/hexagon/tests/test_orch_host_surface.py",
   "expect": "schema drift on 3 route(s)"},
  {"file": "helao/hexagon/app/orch_host.py",
   "old": "            actionservermodel: ActionServerModel = Body({}, embed=True),\n",
   "new": "            actionservermodel: ActionServerModel = Body({}, embed=True, alias=\"action_server_model\"),\n",
   "test": "helao/hexagon/tests/test_orch_host_surface.py",
   "expect": "schema drift on 1 route(s)"}
]
```
**[tool timeout 600 s]**:
```
timeout 580 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t0_mutate.py" "$X/t14_probes.json"
git -C "$WT" status --short -- helao/hexagon/app
```
Expected: `RED rc=1 helao/hexagon/tests/test_orch_host_surface.py :: expect found :: RESTORED helao/hexagon/app/orch_wait.py`, then the same with `RESTORED helao/hexagon/app/orch_host.py`, then `MUTATE-PASS` (measured in the planning dry run: each probe gives `1 failed, 9 passed`, failing `test_parameter_schemas_match_the_frozen_orchestrator_surface`); then nothing from `git status` (both files are committed and restored). If the helper stops on `anchor not unique`, the line has moved or changed: report it as it currently reads.

- [ ] **Step 14.G5: Green again after both reverts.**

```
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -m pytest -q -p no:cacheprovider --color=no helao/hexagon/tests/test_orch_host_surface.py 2>&1 | tail -1
git -C "$WT" status --short -- helao/hexagon/app/
```
Expected: `10 passed…`. The `status` prints nothing.

**Files for the controller's commit (commit 4):** `helao/hexagon/tests/checklists/orch_openapi.json` (new), `helao/hexagon/tests/checklists/orch_openapi_legacy.json` (deleted), `helao/hexagon/tests/test_orch_host_surface.py`.

#### Closing commit 4

- [ ] **Step 14.c1: The commit-4 check (spec §4.4).**
```
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -m pytest -q -p no:cacheprovider --color=no helao/hexagon/tests/test_engine_import_ratchet.py 2>&1 | tail -1
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -m pytest -q -p no:cacheprovider --color=no helao/hexagon/tests/test_orch_host_surface.py 2>&1 | tail -1
/bin/ls "$X/t14_gone_red.txt"
timeout 120 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -c "import helao; print(helao.__file__)"
```
**[background]** Launch `"$X/bg.sh" run_tests_c4 timeout 5400 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python run_tests.py`; then, **[tool timeout 600 s]**, repeating while it prints `STILL-RUNNING`:
```
"$X/wait.sh" run_tests_c4
"$X/t0_failset.sh" "$X/run_tests_c4.txt" "$X/F4.txt" > /dev/null
comm -13 "$X/F0.txt" "$X/F4.txt"; echo new-failures-listed-above
git -C "$WT" status --short | LC_ALL=C sort
```
Expected: `6 passed …`; `10 passed …`; the red record listed; the worktree path; `rc=1`; nothing before `new-failures-listed-above`; then exactly:
```
 D helao/hexagon/tests/checklists/orch_openapi_legacy.json
 M helao/hexagon/tests/test_engine_import_ratchet.py
 M helao/hexagon/tests/test_orch_host_surface.py
?? helao/hexagon/tests/checklists/orch_openapi.json
```
Both mutation probes (Steps 14.G3, 14.G4) must have gone RED and been restored (`MUTATE-PASS`); `git -C "$WT" status --short -- helao/hexagon/app` prints nothing.

- [ ] **Step 14.c2: Report.** Hand the controller Step 14.a2's red/green lines, the helper output of Steps 14.G3/14.G4, Step 14.G1's `SAME-AS-TASK4-NATIVE`, and Step 14.c1's output.

- [ ] **Step 14.c3: Controller commits (commit 4).**
```
cd "$WT" && conda run -n helao --no-capture-output --cwd "$WT" black helao/hexagon/tests/test_engine_import_ratchet.py helao/hexagon/tests/test_orch_host_surface.py
git -C "$WT" add -A -- helao/hexagon/tests/test_engine_import_ratchet.py helao/hexagon/tests/test_orch_host_surface.py helao/hexagon/tests/checklists/orch_openapi.json helao/hexagon/tests/checklists/orch_openapi_legacy.json
git -C "$WT" status --short
git -C "$WT" commit -F - <<'MSG'
test(b7b): package-gone ratchet probe; exact native orchestrator checklist

Commit 4 of B7b (spec section 4.4, section 8, D-B7b.9):

- the ratchet asserts, in a fresh interpreter, that helao.core.servers has no
  spec and helao.core.servers.base raises ModuleNotFoundError; its failure
  names the stale __pycache__ cause and the one-line fix for Linux and
  Windows
- orch_openapi_legacy.json replaced by orch_openapi.json, frozen from a live
  OrchHost (77 routes); byte-identical to the native capture commit 1
  compared with legacy OrchAPI on params and bodies
- the surface tests are exact both ways (no missing, no extra route) and
  compare params and request bodies; two mutation probes (an enum member,
  a body property) fail the gate
- the five known hte checklist drift IDs are unchanged, not re-frozen

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01NxxPoGvJmVh5T4xSpVejFF
MSG
git -C "$WT" status --short; git -C "$WT" log --oneline -1
```
Expected: black leaves both files unchanged; four staged lines; after the commit, no status output.

---

### Task 15: The globstat channel is deleted, and the pacing-sleep comment says why the sleep stays (spec §6.1, §6.4, Q5)

**Files:**
- Modify: `helao/hexagon/app/orch_host.py` (attributes l.173, 179–180; methods l.956–965; feed l.1002; task start l.1439–1441; cancel l.1491, all as `64f2cf15` numbers. Edits are matched by text, not by line)
- Modify: `helao/hexagon/app/orch_status_sync.py` (docstring l.1–11, 16, 30–31, 38–41, 45–48; imports l.51–56; commented put l.294; methods l.298–319)
- Modify: `helao/hexagon/app/orch_dispatch.py:41–42, 51–53` (docstring)
- Modify: `helao/hexagon/app/ingestion.py:22–25` (docstring)
- Modify: `helao/hexagon/ports/auxiliary.py:70, 74` (`NotifyPort.publish_globstat` deleted, Q5)
- Modify: `helao/hexagon/app/action_host.py:759–762` (comment only; the `time.sleep(0.3)` at 763 stays)
- Modify: `helao/hexagon/tests/test_orch_stops_polling_on_shutdown.py:38`
- Rewrite: `helao/core/tests/unit_test_orch_status_sync.py` (225 → 95 lines)
- Modify: `helao/hexagon/tests/test_ws_consumer_parity.py` (`test_ws_globstat_is_dead` → `test_ws_globstat_channel_is_gone`)
- Modify: `helao/hexagon/tests/checklists/orch_member_contract.json` (`globstat_q` retired; 138 → 137)
- Modify (part B): `helao/core/tests/test_orch_dispatch_golden_master.py` (the fixture's three globstat lines and its `MultisubscriberQueue` import)

**Interfaces:**
- Consumes: `helao/hexagon/tests/checklists/orch_member_contract.json` from Task 3, in the format `{"description": str, "members": [sorted str]}` written with `json.dumps(obj, indent=2) + "\n"`. The constants `ACTION_HOST_PATH`/`ORCH_HOST_PATH` in `test_ws_consumer_parity.py`, as Task 12 Step 12.8 renamed and re-pointed them (at `helao/hexagon/app/action_host.py` and `helao/hexagon/app/orch_host.py`). `_host()` in `helao/hexagon/tests/test_orch_host_surface.py`.
- Produces: `OrchHost`, `StatusIngester` and `NotifyPort` without any `globstat*` member, and `ActionHost.log_status_task`'s comment. Nothing later depends on them.

**Execution:** Sequential, after commit 4. Part A (Steps 15.1–15.8) first, then part B (Steps 15.a–15.b), because the golden master's fixture lines can only go once `OrchHost.wait_for_interrupt` no longer feeds `globstat_q` (Spec deviation 8). Step 15.c2 is the controller's. Do not commit.

#### Part A: the globstat channel and the sleep comment

- [ ] **Step 15.1: Write `$X/t15_apply.py`** (exact content):

```python
"""B7b Task 15: delete the globstat channel and rewrite the pacing-sleep comment.

Usage: python t15_apply.py <repo root>
Every (path, old, new) must match exactly once; otherwise nothing is written.
"""

import sys
from pathlib import Path

ROOT = Path(sys.argv[1])

EDITS = [
    # ---- orch_host.py: attributes, methods, feed, task, cancel ----
    # (The MultisubscriberQueue import stays: since Task 9 it also annotates
    # orch_ws_publishers.)
    (
        "helao/hexagon/app/orch_host.py",
        "        self.status_subscriber = None\n"
        "        self.globstat_broadcaster = None\n"
        "        self.heartbeat_monitor = None\n",
        "        self.status_subscriber = None\n"
        "        self.heartbeat_monitor = None\n",
    ),
    (
        "helao/hexagon/app/orch_host.py",
        "        self.last_wait_ts = 0\n"
        "        self.globstat_q = MultisubscriberQueue()\n"
        "        self.globstat_clients = set()\n",
        "        self.last_wait_ts = 0\n",
    ),
    (
        "helao/hexagon/app/orch_host.py",
        "    async def globstat_broadcast_task(self):\n"
        '        """Drain globstat_q so subscribers can read eagerly."""\n'
        "        return await self.status_ingester.globstat_broadcast_task()\n"
        "\n"
        "    async def ws_globstat(self, websocket):\n"
        '        """Stream global status. NOT registered as a route -- no decorator\n'
        "        for it exists anywhere in the tree, on legacy or here. It is the\n"
        "        dead sender already recorded in the post-parity backlog, and\n"
        '        reproducing legacy means not inventing a route legacy never served."""\n'
        "        return await self.status_ingester.ws_globstat(websocket)\n"
        "\n",
        "",
    ),
    (
        "helao/hexagon/app/orch_host.py",
        "            if isinstance(interrupt, GlobalStatusModel):\n"
        "                self.incoming = interrupt\n"
        "                await self.globstat_q.put(interrupt.as_json())\n",
        "            if isinstance(interrupt, GlobalStatusModel):\n"
        "                self.incoming = interrupt\n",
    ),
    (
        "helao/hexagon/app/orch_host.py",
        "            self.status_subscriber = asyncio.create_task(self.subscribe_all())\n"
        "            self.globstat_broadcaster = asyncio.create_task(\n"
        "                self.globstat_broadcast_task()\n"
        "            )\n",
        "            self.status_subscriber = asyncio.create_task(self.subscribe_all())\n",
    ),
    (
        "helao/hexagon/app/orch_host.py",
        "            self.status_subscriber,\n"
        "            self.globstat_broadcaster,\n"
        "            self.driver_monitor,\n",
        "            self.status_subscriber,\n"
        "            self.driver_monitor,\n",
    ),
    # ---- orch_status_sync.py: imports, commented put, two methods, docstring ----
    (
        "helao/hexagon/app/orch_status_sync.py",
        "import asyncio\nimport json\nimport traceback\nfrom typing import Optional\n\n"
        "from fastapi import WebSocket\n\n",
        "from typing import Optional\n\n",
    ),
    (
        "helao/hexagon/app/orch_status_sync.py",
        "            await orch.interrupt_q.put(orch.globalstatusmodel)\n"
        "            # await orch.globstat_q.put(orch.globalstatusmodel.as_json())\n",
        "            await orch.interrupt_q.put(orch.globalstatusmodel)\n",
    ),
    (
        "helao/hexagon/app/orch_status_sync.py",
        "\n"
        "    async def ws_globstat(self, websocket: WebSocket):\n"
        '        """Stream global status updates over ``websocket`` until the client disconnects."""\n'
        "        orch = self.orch\n"
        '        LOGGER.info("got new global status subscriber")\n'
        "        await websocket.accept()\n"
        "        gs_sub = orch.globstat_q.subscribe()\n"
        "        try:\n"
        "            async for globstat_msg in gs_sub:\n"
        "                await websocket.send_text(json.dumps(globstat_msg.as_dict()))\n"
        "        except Exception as e:\n"
        '            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))\n'
        "            LOGGER.warning(\n"
        '                f"Data websocket client {websocket.client[0]}:{websocket.client[1]} disconnected. {repr(e), tb,}"\n'
        "            )\n"
        "            if gs_sub in orch.globstat_q.subscribers:\n"
        "                orch.globstat_q.remove(gs_sub)\n"
        "\n"
        "    async def globstat_broadcast_task(self):\n"
        '        """Drain ``globstat_q`` indefinitely so subscribers can read messages eagerly."""\n'
        "        orch = self.orch\n"
        "        async for _ in orch.globstat_q.subscribe():\n"
        "            await asyncio.sleep(0.01)\n",
        "",
    ),
    (
        "helao/hexagon/app/orch_status_sync.py",
        '"""Status ingestion + WS broadcast collaborator extracted from ``Orch`` (CARDS\n'
        "P5, Stage S4).\n"
        "\n"
        "``Orch.update_status``/``Orch.update_nonblocking``/``Orch.clear_nonblocking``/\n"
        "``Orch.ws_globstat``/``Orch.globstat_broadcast_task`` implement the\n"
        "orchestrator's status-ingestion \"cluster C\": merging every reported\n"
        "``ActionServerModel`` into the ``GlobalStatusModel``, tracking non-blocking\n"
        "executors, reacting to e-stop/error conditions, and streaming the resulting\n"
        "status over the ``globstat_q``/websocket fan-out to the Bokeh operator UI.\n"
        "This module moves those five method bodies into a ``StatusIngester``\n"
        "collaborator that ``Orch`` delegates to.\n",
        '"""Status ingestion collaborator extracted from ``Orch`` (CARDS P5, Stage S4).\n'
        "\n"
        "``Orch.update_status``/``Orch.update_nonblocking``/``Orch.clear_nonblocking``\n"
        "implement the orchestrator's status-ingestion \"cluster C\": merging every\n"
        "reported ``ActionServerModel`` into the ``GlobalStatusModel``, tracking\n"
        "non-blocking executors, and reacting to e-stop/error conditions. This module\n"
        "moves those method bodies into a ``StatusIngester`` collaborator that the\n"
        "orchestrator delegates to. (It also held ``ws_globstat`` and\n"
        "``globstat_broadcast_task``, a ``/ws_globstat`` sender that never had a\n"
        "route; B7b deleted both with ``globstat_q``.)\n",
    ),
    (
        "helao/hexagon/app/orch_status_sync.py",
        "``active_experiment``/``active_sequence``, ``interrupt_q`` and ``globstat_q``\n"
        "through it at call time,",
        "``active_experiment``/``active_sequence`` and ``interrupt_q``\n"
        "through it at call time,",
    ),
    (
        "helao/hexagon/app/orch_status_sync.py",
        "- ``interrupt_q`` -- written by ``StatusIngester`` / ``ServerMonitor`` /\n"
        "  e-stop; read by ``DispatchRunner``.\n"
        "- ``globstat_q`` -- written by ``StatusIngester``; drained by its own\n"
        "  broadcast task.\n",
        "- ``interrupt_q`` -- written by ``StatusIngester`` / ``ServerMonitor`` /\n"
        "  e-stop; read by ``DispatchRunner``.\n",
    ),
    (
        "helao/hexagon/app/orch_status_sync.py",
        "cluster B, not yet extracted); ``globstat_q`` is only read/drained here\n"
        "(``ws_globstat`` subscribes, ``globstat_broadcast_task`` drains) -- it is\n"
        "also written by ``wait_for_interrupt`` as it forwards queued\n"
        "``GlobalStatusModel``s. ``update_status`` can trigger ``orch.estop_loop``\n",
        "cluster B, not yet extracted). ``update_status`` can trigger ``orch.estop_loop``\n",
    ),
    (
        "helao/hexagon/app/orch_status_sync.py",
        "\n"
        "Task-creation semantics are unchanged: ``Orch.myinit`` still does\n"
        "``asyncio.create_task(self.globstat_broadcast_task())`` via the thin\n"
        "delegator on ``Orch`` -- this module only relocates the method bodies, not\n"
        "when/where the background task is started.\n",
        "",
    ),
    # ---- orch_dispatch.py docstring ----
    (
        "helao/hexagon/app/orch_dispatch.py",
        "- ``interrupt_q`` -- written by ``StatusIngester`` / ``ServerMonitor`` /\n"
        "  e-stop; read by ``DispatchRunner``.\n"
        "- ``globstat_q`` -- written by ``StatusIngester``; drained by its own\n"
        "  broadcast task.\n",
        "- ``interrupt_q`` -- written by ``StatusIngester`` / ``ServerMonitor`` /\n"
        "  e-stop; read by ``DispatchRunner``.\n",
    ),
    (
        "helao/hexagon/app/orch_dispatch.py",
        "remains on ``Orch``, cluster B); it never touches ``globstat_q`` directly --\n"
        "that queue is owned end-to-end by ``StatusIngester`` in\n"
        "``orch_status_sync.py``.\n",
        "remains on ``Orch``, cluster B).\n",
    ),
    # ---- ingestion.py docstring (the globstat sentences only) ----
    (
        "helao/hexagon/app/ingestion.py",
        "unconditional trailing ``globalstatusmodel`` put) and by the health monitor;\n"
        "``globstat_q`` stays on the legacy broadcaster (``ws_globstat``/\n"
        "``globstat_broadcast_task`` are NOT rebound). ``clear_nonblocking`` is NOT\n"
        "rebound either — its wire behavior is untouched.\n",
        "unconditional trailing ``globalstatusmodel`` put) and by the health monitor.\n"
        "``clear_nonblocking`` stays on ``StatusIngester``; its wire behavior is\n"
        "untouched.\n",
    ),
    # ---- the port member nobody implements or calls (Q5) ----
    (
        "helao/hexagon/ports/auxiliary.py",
        '    """Live buffer put, globstat/WS relay, LOGGER.alert."""\n'
        "\n"
        "    def put_lbuf_nowait(self, payload: dict) -> None: ...\n"
        "\n"
        "    async def publish_globstat(self, payload: dict) -> None: ...\n",
        '    """Live buffer put, LOGGER.alert."""\n'
        "\n"
        "    def put_lbuf_nowait(self, payload: dict) -> None: ...\n",
    ),
    # ---- §6.4: the pacing sleep stays; its comment says why ----
    (
        "helao/hexagon/app/action_host.py",
        "                    # Blocking, and deliberately so until parity is signed\n"
        "                    # off: legacy paces subscribers with time.sleep here, and\n"
        "                    # swapping in asyncio.sleep reorders this loop against\n"
        "                    # every other coroutine on the server.\n",
        "                    # Blocking, deliberately, and deferred past B7: this is\n"
        "                    # the pacing legacy used, and asyncio.sleep would reorder\n"
        "                    # this loop against every other coroutine on the server.\n"
        "                    # That is a behaviour change with its own station check,\n"
        "                    # not part of deleting the engine.\n",
    ),
    # ---- tests ----
    (
        "helao/hexagon/tests/test_orch_stops_polling_on_shutdown.py",
        "        self.status_subscriber = None\n"
        "        self.globstat_broadcaster = None\n"
        "        self.driver_monitor = None\n",
        "        self.status_subscriber = None\n"
        "        self.driver_monitor = None\n",
    ),
]


def main() -> int:
    texts = {}
    bad = []
    for rel, old, new in EDITS:
        path = ROOT / rel
        text = texts.get(rel)
        if text is None:
            text = path.read_text(encoding="utf-8")
        n = text.count(old)
        if n != 1:
            bad.append(f"{rel}: expected 1 match, found {n}: {old[:60]!r}")
            continue
        texts[rel] = text.replace(old, new)
    if bad:
        print("\n".join(bad))
        print("NOTHING WRITTEN")
        return 1
    for rel, text in texts.items():
        (ROOT / rel).write_text(text, encoding="utf-8")
    print(f"applied {len(EDITS)} edits to {len(texts)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

```
timeout 120 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t15_apply.py" "$WT"
```
Expected (measured): `applied 21 edits to 7 files`. `NOTHING WRITTEN` means a matched block changed after `64f2cf15`. That is most likely `orch_host.py`'s startup or shutdown block, if Task 9 moved it. STOP and report the printed mismatch.

- [ ] **Step 15.2: Rewrite `helao/core/tests/unit_test_orch_status_sync.py`** with this exact content. `clear_nonblocking` stays, and the two globstat checks go. `run_unit_tests.py` needs no edit, because the function name `orch_status_sync_unit_test` is unchanged.

```python
"""Unit tests for the ``StatusIngester`` collaborator extracted from ``Orch``
(CARDS P5, Stage S4): the status-ingestion cluster.

``update_status``/``update_nonblocking`` are already exercised (byte-for-byte,
via the fake-dispatcher status-ping mechanism) by
``test_orch_dispatch_golden_master.py --check``, so this module covers the
cluster-C member that harness does *not* drive:

  1. ``clear_nonblocking`` sends ``stop_executor`` to every tracked
     non-blocking executor (in order) and returns the collected
     ``(response, error_code)`` tuples.

B7b deleted ``ws_globstat`` and ``globstat_broadcast_task`` with the
``globstat_q`` they served (a ``/ws_globstat`` sender that never had a route),
and with them this module's two checks of those methods.

Hermetic: a fake orch and a patched ``async_private_dispatcher`` (no network),
mirroring ``unit_test_orch_monitor``'s fake-``Base`` pattern.
"""

__all__ = ["orch_status_sync_unit_test"]

import asyncio
import traceback

from helao.core.error import ErrorCodes
from helao.hexagon.app import orch_status_sync as oss
from helao.core.tests._test_utils import TestReporter


class _FakeOrch:
    def __init__(self, nonblocking=None):
        self.nonblocking = nonblocking or []


async def _check_clear_nonblocking() -> bool:
    orch = _FakeOrch(
        nonblocking=[
            ("SRV1", "exec-1", "127.0.0.1", 8001),
            ("SRV2", "exec-2", "127.0.0.1", 8002),
        ]
    )
    calls = []

    async def _fake_dispatcher(**kwargs):
        calls.append(kwargs)
        if kwargs["server_key"] == "SRV2":
            return None, ErrorCodes.http
        return {"stopped": True}, ErrorCodes.none

    orig = oss.async_private_dispatcher
    oss.async_private_dispatcher = _fake_dispatcher
    try:
        ingester = oss.StatusIngester(orch)
        resp_tups = await ingester.clear_nonblocking()
    finally:
        oss.async_private_dispatcher = orig

    return (
        [c["server_key"] for c in calls] == ["SRV1", "SRV2"]
        and calls[0]["private_action"] == "stop_executor"
        and calls[0]["params_dict"] == {"executor_id": "exec-1"}
        and calls[1]["params_dict"] == {"executor_id": "exec-2"}
        and resp_tups == [({"stopped": True}, ErrorCodes.none), (None, ErrorCodes.http)]
    )


async def _run_checks() -> dict:
    return {
        "clear_nonblocking": await _check_clear_nonblocking(),
    }


def orch_status_sync_unit_test() -> bool:
    reporter = TestReporter("orch_status_sync")
    try:
        res = asyncio.run(_run_checks())
    except Exception as exc:  # noqa: BLE001
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        print(repr(exc), tb)
        return False

    reporter.section("clear_nonblocking")
    reporter.check(
        "dispatches stop_executor per tracked executor, in order, and collects responses",
        lambda: res["clear_nonblocking"],
    )

    return reporter.success()


if __name__ == "__main__":
    import sys

    sys.exit(0 if orch_status_sync_unit_test() else 1)
```

- [ ] **Step 15.3: Replace `test_ws_globstat_is_dead` in `helao/hexagon/tests/test_ws_consumer_parity.py`.** Delete everything from the line `def test_ws_globstat_is_dead():` up to, but not including, the line `def test_operator_ws_face_is_shape_blind():`, and put this text in its place (it ends with two blank lines):

```python
def test_ws_globstat_channel_is_gone():
    """No /ws_globstat route exists on either host, and the sender that fed it
    is deleted (B7b, spec §6.1). The route half uses the repo's own static AST
    route extractor (harness.endpoints), not a hand-rolled grep, so a future
    route addition is exactly as visible here as to the endpoint-parity
    checklist that tool already gates."""
    from helao.hexagon.app.orch_host import OrchHost
    from helao.hexagon.app.orch_status_sync import StatusIngester
    from helao.hexagon.tests.test_orch_host_surface import _host

    base_routes = extract_routes(ACTION_HOST_PATH)
    orch_routes = extract_routes(ORCH_HOST_PATH)
    assert base_routes, f"extractor found nothing in {ACTION_HOST_PATH} -- inert glob?"
    assert orch_routes, f"extractor found nothing in {ORCH_HOST_PATH} -- inert glob?"

    base_paths = {r["path"] for r in base_routes}
    orch_paths = {r["path"] for r in orch_routes}
    # The three routes that DO carry a live producer, as a sanity check that
    # the extractor is actually seeing each file's websocket decorators.
    for expected in ("/ws_status", "/ws_data", "/ws_live"):
        assert expected in base_paths, (expected, base_paths)
        assert expected in orch_paths, (expected, orch_paths)

    assert "/ws_globstat" not in base_paths
    assert "/ws_globstat" not in orch_paths

    # The sender is gone, not merely unrouted.
    assert not hasattr(OrchHost, "ws_globstat")
    assert not hasattr(OrchHost, "globstat_broadcast_task")
    assert not hasattr(StatusIngester, "ws_globstat")
    assert not hasattr(StatusIngester, "globstat_broadcast_task")
    assert not hasattr(_host(), "globstat_q")


```

The replacement is defined by the two anchor lines, so it does not depend on the text Task 12 left inside the old function.

- [ ] **Step 15.4: Retire `globstat_q` from the frozen contract.** Write `$X/t15_retire_globstat_q.py` (exact content):

```python
"""B7b Task 15: retire ``globstat_q`` from the frozen orchestrator member contract.

Usage: python t15_retire_globstat_q.py <path to orch_member_contract.json>
Rewrites the file with the same dumps settings Task 3 froze it with.
"""

import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
doc = json.loads(path.read_text(encoding="utf-8"))
before = len(doc["members"])
assert "globstat_q" in doc["members"], "globstat_q is not in the frozen contract"
doc["members"] = sorted(m for m in doc["members"] if m != "globstat_q")
path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
print(f"members {before} -> {len(doc['members'])}")
```

```
timeout 60 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t15_retire_globstat_q.py" "$WT/helao/hexagon/tests/checklists/orch_member_contract.json"
git -C "$WT" diff --stat -- helao/hexagon/tests/checklists/orch_member_contract.json
```
Expected: `members 138 -> 137`, then ` ... | 1 -` (one deleted line). A second run fails its assert, which is the guard against applying it twice (measured).

- [ ] **Step 15.5: No globstat code is left.**

```
git -C "$WT" grep -n globstat -- '*.py'
```
Expected: exactly these hits, all prose or negative assertions:
```
helao/core/tests/unit_test_orch_status_sync.py:13:B7b deleted ``ws_globstat`` and ``globstat_broadcast_task`` with the
helao/core/tests/unit_test_orch_status_sync.py:14:``globstat_q`` they served (a ``/ws_globstat`` sender that never had a
helao/hexagon/app/orch_status_sync.py:8:orchestrator delegates to. (It also held ``ws_globstat`` and
helao/hexagon/app/orch_status_sync.py:9:``globstat_broadcast_task``, a ``/ws_globstat`` sender that never had a
helao/hexagon/app/orch_status_sync.py:10:route; B7b deleted both with ``globstat_q``.)
helao/hexagon/tests/test_ws_consumer_parity.py:15:4. `/ws_globstat` has no route registration on either API class (Corrections
helao/hexagon/tests/test_ws_consumer_parity.py:180:def test_ws_globstat_channel_is_gone():
helao/hexagon/tests/test_ws_consumer_parity.py:181:    """No /ws_globstat route exists on either host, and the sender that fed it
helao/hexagon/tests/test_ws_consumer_parity.py:203:    assert "/ws_globstat" not in base_paths
helao/hexagon/tests/test_ws_consumer_parity.py:204:    assert "/ws_globstat" not in orch_paths
helao/hexagon/tests/test_ws_consumer_parity.py:207:    assert not hasattr(OrchHost, "ws_globstat")
helao/hexagon/tests/test_ws_consumer_parity.py:208:    assert not hasattr(OrchHost, "globstat_broadcast_task")
helao/hexagon/tests/test_ws_consumer_parity.py:209:    assert not hasattr(StatusIngester, "ws_globstat")
helao/hexagon/tests/test_ws_consumer_parity.py:210:    assert not hasattr(StatusIngester, "globstat_broadcast_task")
helao/hexagon/tests/test_ws_consumer_parity.py:211:    assert not hasattr(_host(), "globstat_q")
```
The `test_ws_consumer_parity.py` line numbers hold only if Task 12 left the lines above the function at their `64f2cf15` count. The texts must match. Any hit in `test_orch_dispatch_golden_master.py` means part B of this task has not run yet.

- [ ] **Step 15.6: Red-check the new route test.** Swap in the pre-edit host (`HEAD`'s `orch_host.py`), run the one test, and restore, through the Task 0 helper. Create `$X/t15_probes.json` with exactly this content:
```json
[
  {"file": "helao/hexagon/app/orch_host.py", "git_rev": "HEAD",
   "test": "helao/hexagon/tests/test_ws_consumer_parity.py", "k": "globstat",
   "expect": "hasattr(<class 'helao.hexagon.app.orch_host.OrchHost'>, 'ws_globstat')"}
]
```
**[tool timeout 600 s]**:
```
timeout 400 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t0_mutate.py" "$X/t15_probes.json"
git -C "$WT" diff --quiet HEAD -- helao/hexagon/app/orch_host.py && echo EDITS-LOST || echo EDITS-STILL-PRESENT
```
Expected (measured in the planning dry run: `1 failed, 4 deselected`, with `E  +  where True = hasattr(<class 'helao.hexagon.app.orch_host.OrchHost'>, 'ws_globstat')`): `RED rc=1 helao/hexagon/tests/test_ws_consumer_parity.py :: expect found :: RESTORED helao/hexagon/app/orch_host.py`, `MUTATE-PASS`, then `EDITS-STILL-PRESENT` (Step 15.1's edits survived the probe).

- [ ] **Step 15.7: The §4.5 check.**

```
for t in helao/hexagon/tests/test_ws_consumer_parity.py helao/hexagon/tests/test_orch_stops_polling_on_shutdown.py helao/hexagon/tests/test_orch_host_member_coverage.py helao/hexagon/tests/test_action_host_member_coverage.py helao/hexagon/tests/test_orch_host_surface.py helao/hexagon/tests/test_ports_import.py; do printf '%s: ' "$t"; timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -m pytest -q -p no:cacheprovider --color=no "$t" 2>&1 | tail -1; done
timeout 300 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python helao/core/tests/unit_test_orch_status_sync.py > "$X/t15_unit.txt" 2>&1; echo "unit rc=$?"
grep 'test 1 passed' "$X/t15_unit.txt"
```
Expected: every pytest line ends in `passed` with no `failed`. Measured: `test_ws_consumer_parity` 5 passed (the renamed test replaces the old one), `test_orch_stops_polling_on_shutdown` 2 passed, and `test_ports_import` 3 passed. The member-coverage and surface counts are whatever Tasks 3, 4, 8, 11 and 14 left, still with 0 failed. The measured case is the dry run with the engine removed and the JSON reader simulated: frozen 137 ∪ live 102 = 137, and no unaccounted member. Then `unit rc=0` and `orch_status_sync test 1 passed. dispatches stop_executor per tracked executor, in order, and collects responses`. The dispatch golden master `--check` gate for this commit belongs to part B of this task.

- [ ] **Step 15.8: pyright shows no new errors on the six edited modules.**

```
cd "$WT" && PYTHONPATH="$WT" timeout 600 pyright --outputjson helao/hexagon/app/orch_host.py helao/hexagon/app/orch_status_sync.py helao/hexagon/app/orch_dispatch.py helao/hexagon/app/ingestion.py helao/hexagon/ports/auxiliary.py helao/hexagon/app/action_host.py > "$X/t15_pyright.json"; timeout 60 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -c "import json; d = json.load(open('$X/t15_pyright.json')); print(d['summary']['filesAnalyzed'], d['summary']['errorCount'])"
```
Expected: `6 N`, where N is at most the Task 0 figure for these six files minus 2. Measured on `64f2cf15`: 37 before and 35 after, with `orch_status_sync.py` going from 4 to 2. A first number other than 6 is a vacuous run: STOP.

**Files for the controller's commit:** (commit 5, with part B)
- modified: `helao/hexagon/app/orch_host.py`, `helao/hexagon/app/orch_status_sync.py`, `helao/hexagon/app/orch_dispatch.py`, `helao/hexagon/app/ingestion.py`, `helao/hexagon/ports/auxiliary.py`, `helao/hexagon/app/action_host.py`, `helao/hexagon/tests/test_orch_stops_polling_on_shutdown.py`, `helao/core/tests/unit_test_orch_status_sync.py`, `helao/hexagon/tests/test_ws_consumer_parity.py`, `helao/hexagon/tests/checklists/orch_member_contract.json`
- black: all nine `.py` files are black-clean as edited (measured). The JSON is not black's.

#### Part B: the dispatch golden master drops its globstat fixture (after part A's `orch_host.py` edits)

This lands in Task 15, **in the same commit as, and after,** the removal of `await self.globstat_q.put(interrupt.as_json())` from `OrchHost.wait_for_interrupt` (`orch_host.py:1002` on `64f2cf15`). Measured: removing the fixture lines first makes `--check` and default mode die with `AttributeError: 'OrchHost' object has no attribute 'globstat_q'`, because `OrchHost.__new__` never runs the `__init__` that sets it and several scenarios drain more than one interrupt. With the feed line gone, the fixture lines are dead and all nine traces stay byte-identical: no trace records the feed.

**Files:** Modify `helao/core/tests/test_orch_dispatch_golden_master.py` — after Task 1 and black, line 138 (import), line 264, lines 272–273.

- [ ] **Step 15.a:** Delete these four lines, and nothing else:
```python
from helao.helpers.multisubscriber_queue import MultisubscriberQueue
```
```python
    orch.globstat_broadcaster = None
```
```python
    orch.globstat_q = MultisubscriberQueue()
    orch.globstat_clients = set()
```
The import has no other user in the file once the fixture lines go.

- [ ] **Step 15.b:**
```
grep -c 'globstat\|MultisubscriberQueue' "$WT/helao/core/tests/test_orch_dispatch_golden_master.py"
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python helao/core/tests/test_orch_dispatch_golden_master.py --check; echo rc=$?
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python helao/core/tests/test_orch_dispatch_golden_master.py > "$X/t15_gm_default.txt" 2>&1; echo rc=$?; tail -1 "$X/t15_gm_default.txt"
```
Expected: `0`; nine `PASS` lines, `CHECK PASSED: all 9 scenarios byte-identical to $WT/helao/core/tests/golden/dispatch`, `rc=0`; `rc=0`, `ALL GOLDEN-MASTER HARNESS CHECKS PASSED`. (Measured in the dry run with only the `orch_host.py:1002` feed line removed from `OrchHost`.)

**Files for the controller's commit (Task 15 adds this to its list):** `helao/core/tests/test_orch_dispatch_golden_master.py`.

#### Closing commit 5

- [ ] **Step 15.c1: The commit-5 check (spec §4.5).**
```
for t in helao/hexagon/tests/test_ws_consumer_parity.py helao/hexagon/tests/test_orch_stops_polling_on_shutdown.py helao/hexagon/tests/test_orch_host_member_coverage.py helao/hexagon/tests/test_action_host_member_coverage.py; do printf '%s: ' "$t"; timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -m pytest -q -p no:cacheprovider --color=no "$t" 2>&1 | tail -1; done
timeout 900 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t6_run_unit.py" orch_status_sync 2>/dev/null | tail -1
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python helao/core/tests/test_orch_dispatch_golden_master.py --check 2>/dev/null | tail -1
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python run_unit_tests.py 2>&1 | tail -1
timeout 120 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -c "import helao; print(helao.__file__)"
git -C "$WT" status --short | LC_ALL=C sort
```
Expected: `5 passed`, `2 passed`, `5 passed`, `4 passed` (each followed by warnings and time); `UNIT-SUMMARY 1 passed, 0 failed`; `CHECK PASSED: all 9 scenarios byte-identical to …/golden/dispatch` (the feed wrote to a queue no trace records); `overall: PASS`; the worktree's `helao/__init__.py`; then exactly:
```
 M helao/core/tests/test_orch_dispatch_golden_master.py
 M helao/core/tests/unit_test_orch_status_sync.py
 M helao/hexagon/app/action_host.py
 M helao/hexagon/app/ingestion.py
 M helao/hexagon/app/orch_dispatch.py
 M helao/hexagon/app/orch_host.py
 M helao/hexagon/app/orch_status_sync.py
 M helao/hexagon/ports/auxiliary.py
 M helao/hexagon/tests/checklists/orch_member_contract.json
 M helao/hexagon/tests/test_orch_stops_polling_on_shutdown.py
 M helao/hexagon/tests/test_ws_consumer_parity.py
```
- [ ] **Step 15.c1b: The full sweep against F0, before the commit.** Commit 5 deletes a `Protocol` member and edits six production modules, so a break in an untouched fake or conformance test must be caught before the commit, not after it. **[background]** Launch:
```
"$X/bg.sh" run_tests_c5 timeout 5400 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python run_tests.py
```
Then, **[tool timeout 600 s]**, repeating while it prints `STILL-RUNNING`:
```
"$X/wait.sh" run_tests_c5
tail -8 "$X/run_tests_c5.txt"
"$X/t0_failset.sh" "$X/run_tests_c5.txt" "$X/F5.txt" > /dev/null
comm -13 "$X/F0.txt" "$X/F5.txt"; echo new-failures-listed-above
```
Expected: `rc=1`; the summary; nothing before `new-failures-listed-above`.

- [ ] **Step 15.c2: Controller commits (commit 5).**
```
cd "$WT" && conda run -n helao --no-capture-output --cwd "$WT" black helao/core/tests/test_orch_dispatch_golden_master.py helao/core/tests/unit_test_orch_status_sync.py helao/hexagon/app/action_host.py helao/hexagon/app/ingestion.py helao/hexagon/app/orch_dispatch.py helao/hexagon/app/orch_host.py helao/hexagon/app/orch_status_sync.py helao/hexagon/ports/auxiliary.py helao/hexagon/tests/test_orch_stops_polling_on_shutdown.py helao/hexagon/tests/test_ws_consumer_parity.py
git -C "$WT" add -A -- helao/core/tests/test_orch_dispatch_golden_master.py helao/core/tests/unit_test_orch_status_sync.py helao/hexagon/app/action_host.py helao/hexagon/app/ingestion.py helao/hexagon/app/orch_dispatch.py helao/hexagon/app/orch_host.py helao/hexagon/app/orch_status_sync.py helao/hexagon/ports/auxiliary.py helao/hexagon/tests/checklists/orch_member_contract.json helao/hexagon/tests/test_orch_stops_polling_on_shutdown.py helao/hexagon/tests/test_ws_consumer_parity.py
git -C "$WT" status --short
git -C "$WT" commit -F - <<'MSG'
refactor(b7b): delete the routeless /ws_globstat channel; defer the pacing sleep

Commit 5 of B7b (spec section 6):

- /ws_globstat never had a route on either host; its sender is deleted:
  OrchHost's globstat attributes, methods, feed, task and cancel,
  StatusIngester.ws_globstat/globstat_broadcast_task, and
  NotifyPort.publish_globstat (Q5). globstat_q is retired from the frozen
  member contract (138 -> 137). Nothing on the wire changes.
- params.limit_vis is kept: it is live in a private deployment's station
  config (Q4)
- the 0.3 s blocking sleep in ActionHost.log_status_task and the
  finish-drain window stay; the sleep's comment now says why it is deferred
  past B7

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01NxxPoGvJmVh5T4xSpVejFF
MSG
git -C "$WT" status --short; git -C "$WT" log --oneline -1
```
Expected: black leaves all ten `.py` files unchanged; eleven staged lines; after the commit, no status output. Then run Task 16.

---

### Task 16: Gates (spec §7), on the branch head after commit 5

**Files:** none edited. Gate 5 temporarily copies the private deployments into `$WT/helao/deploy/` and removes them; gate 7 writes the smoke root named in `goldenhex.yml` (controller only).

**Interfaces:**
- Consumes: commits 1–5; every Task 0 record.
- Produces: the gate record the controller pastes into the PR.

**Execution:** runs alone. Gates 1–6 and 9 can be run by an implementer; gate 7 and the push (Step 16.7b, only with the user's approval) by the controller; gate 8 by the user, on the station (the section "Gate 8 — station launch" at the end of this plan is written to be pasted to the user as it stands).

- [ ] **Step 16.1 — Gate 1: the ratchet.**
```
git -C "$WT" status --porcelain
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -m pytest -q -p no:cacheprovider --color=no -v helao/hexagon/tests/test_engine_import_ratchet.py 2>&1 | grep -E 'PASSED|FAILED|passed|failed'
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -c "from helao.hexagon.tests.test_engine_import_ratchet import offenders, _probe; r = _probe(); print(offenders(), r['engine_modules'], sorted(r['hosts']))" 2>/dev/null
timeout 60 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -c "import importlib.util as u; print(u.find_spec('helao.core.servers'))"
```
Expected: no status output; six `PASSED` lines (including `test_nothing_outside_the_engine_imports_it` and `test_the_engine_package_cannot_be_imported`) and `6 passed`; `{} [] ['ActionHost', 'OrchHost', 'makeActionApp']`; `None`. (`_probe()` takes no argument after Step 12.7.)

- [ ] **Step 16.2 — Gate 2: golden masters.**
```
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python helao/core/tests/test_orch_dispatch_golden_master.py --check 2>/dev/null | tail -1
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python helao/core/tests/test_orch_dispatch_golden_master.py 2>/dev/null | tail -1
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python helao/core/tests/test_active_golden_master.py --check 2>/dev/null | tail -1
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python helao/core/tests/test_active_golden_master.py 2>/dev/null | tail -1
git -C "$WT" log --oneline -- helao/core/tests/golden | wc -l
tail -2 "$X/t1_compare.txt"; tail -1 "$X/t2_red_legacy.txt"; tail -1 "$X/t2_native_vs_legacy.txt"
```
Expected: `CHECK PASSED: all 9 scenarios byte-identical to …/golden/dispatch`; `ALL GOLDEN-MASTER HARNESS CHECKS PASSED`; `CHECK PASSED: all 13 scenarios match …/golden/action`; `DETERMINISM SELF-TEST PASSED: 13 scenarios byte/multiset-stable 2x`; `1` (the references were written once, in commit 1, and never again); the last two lines of Task 1's record, `  IDENTICAL  9_step_thru_flags.jsonl` and `COMPARE PASS` (the S7 line above them reads `ONE-BLOCK`, Q1); `legacy: 13 of 13 scenarios red`; `COMPARE PASSED: 13 scenarios`.

- [ ] **Step 16.3 — Gate 3: checklists.**
```
for f in harness/tests/test_hte_checklist.py helao/hexagon/tests/test_hte_route_checklist.py harness/tests/test_freeze.py; do timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -m pytest -q -p no:cacheprovider --color=no -rf "$f" 2>&1 | grep -E '^FAILED' | awk '{print $2}'; done | sort > "$X/checklist_ids_after.txt"
diff "$X/checklist_ids_before.txt" "$X/checklist_ids_after.txt" && echo CHECKLIST-IDS-UNCHANGED
for f in helao/hexagon/tests/test_orch_host_surface.py helao/hexagon/tests/test_action_host_surface.py; do timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -m pytest -q -p no:cacheprovider --color=no "$f" 2>&1 | tail -1; done
```
Expected: `CHECKLIST-IDS-UNCHANGED` (the five IDs of spec §2.7, recorded in Task 0 Step 0.8; nothing re-freezes the hte checklists to hide them); `10 passed …`; `8 passed …`.

- [ ] **Step 16.4 — Gate 4: the full sweep in the bare worktree (~8 minutes).** First confirm no private copy is present (they are gitignored, so check the paths):
```
/bin/ls -A "$WT/helao/deploy" | grep -v -x __pycache__ | paste -sd' '
```
Expected: `__init__.py hexagon hte test`. **[background]** Launch:
```
"$X/bg.sh" run_tests_final timeout 5400 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python run_tests.py
```
Then, **[tool timeout 600 s]**, repeating while it prints `STILL-RUNNING`:
```
"$X/wait.sh" run_tests_final
tail -8 "$X/run_tests_final.txt"
"$X/t0_failset.sh" "$X/run_tests_final.txt" "$X/F_final.txt"
diff "$X/F0.txt" "$X/F_final.txt" && echo FAIL-SET-EQUALS-F0
grep -E '^  NOTESTS ' "$X/run_tests_F0.txt" | awk '{print $2}' | sort > "$X/notests_F0.txt"
grep -E '^  NOTESTS ' "$X/run_tests_final.txt" | awk '{print $2}' | sort > "$X/notests_final.txt"
diff "$X/notests_F0.txt" "$X/notests_final.txt" && echo NOTESTS-SET-UNCHANGED
grep -E 'test_db_endpoint_surface' "$X/run_tests_final.txt"
```
Expected: `rc=1`; the summary (`306` files less the two deleted test files, `test_active_graft.py` and `test_sync_graft.py`, plus the one added: `===== 305 files`; `run_tests.py` does not collect `unit_test_*.py`); `F_final.txt` equal to `F0.txt` (the three checklist files), `FAIL-SET-EQUALS-F0`; `NOTESTS-SET-UNCHANGED` (no test file silently stopped collecting tests); `PASS     helao/hexagon/tests/test_db_endpoint_surface.py  4 passed`. `ENV` is not a failure. Any new or renamed test file must pass.

- [ ] **Step 16.5 — Gate 5: private deployments against the branch.** Task 0's `t0_private_sweep.sh` copies each private deployment in at its committed `HEAD`, sweeps, and removes the copies from an `EXIT` trap. **[background]** Launch:
```
"$X/bg.sh" F_final_p_job "$X/t0_private_sweep.sh" "$X/run_tests_final_p.txt"
```
Then, **[tool timeout 600 s]**, repeating while it prints `STILL-RUNNING`:
```
"$X/wait.sh" F_final_p_job
```
Then, in a **separate** call (the cleanup must not depend on the sweep's call surviving), remove the copies again, verify they are gone, and compare:
```
"$X/t0_private_remove.sh"
cat "$X/private_remove_trap.txt"
/bin/ls -A "$WT/helao/deploy" | grep -v -x __pycache__ | paste -sd' '
git -C "$WT" status --short
head -1 "$X/F_final_p_job.txt"
"$X/t0_failset.sh" "$X/run_tests_final_p.txt" "$X/F_final_p.txt"
diff "$X/F0p.txt" "$X/F_final_p.txt" && echo PRIVATE-FAIL-SET-EQUALS-F0p
```
Expected: `rc=1` from `wait.sh`; `PRIVATE-COPIES-REMOVED` twice (the separate call and the trap's record); `__init__.py hexagon hte test`; no `git status` output; `4` (copies made); the 8 failing paths; `PRIVATE-FAIL-SET-EQUALS-F0p` (Task 0 Step 0.6's set, less any file B7b deleted). **Cleanup is not optional:** if the job was killed, or `wait.sh` never reports, run `"$X/t0_private_remove.sh"` before anything else. It deletes exactly the directories listed in `$X/private_copied.txt`, then checks the gitignored paths directly (`git status` cannot see them) and fails on any leftover. The copies must never be present while a `git add` runs.

- [ ] **Step 16.6 — Gate 6: `run_unit_tests.py` and pyright.** **[tool timeout 600 s]**
```
timeout 600 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python run_unit_tests.py 2>&1 | tail -1
git -C "$WT" diff --name-only --diff-filter=AM 64f2cf15 HEAD -- '*.py' > "$X/pyright_files_after.txt"; wc -l < "$X/pyright_files_after.txt"
cd "$WT" && PYTHONPATH="$WT" xargs -a "$X/pyright_files_after.txt" timeout 590 pyright --outputjson > "$X/pyright_after.json" 2>/dev/null; echo rc=$?
timeout 60 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python "$X/t0_pyright_cmp.py" "$X/pyright_before.json" "$X/pyright_after.json" "$X/pyright_files_after.txt" "$X/pyright_files_before.txt"; echo cmp rc=$?
```
Expected: `overall: PASS`; `92` (the 91 files of Task 0 plus `test_db_endpoint_surface.py`); `rc=123`; `analyzed=92 …`, `worse={} added_with_errors={} modified_but_not_in_task0_list=[]`, `cmp rc=0`. If `analyzed` differs from the file count, the pass is vacuous: STOP.

- [ ] **Step 16.7 — Gate 7 (controller): `goldenhex` launch smoke with clean teardown.** It writes the config's root, `$SMOKE`, outside the worktree, so the controller runs it; any existing root is moved aside, never deleted.
```
timeout 60 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python helao/hexagon/tests/smoke/wait_ports_free.py --timeout 10 8001 8002 8010; echo ports rc=$?
test -e $SMOKE && mv "$SMOKE" "$SMOKE.pre-b7b-$(date +%Y%m%d%H%M%S)"; echo root-ready
```
Expected: `ports rc=0`, `root-ready`. Start the launcher with the Bash tool's `run_in_background: true` (the servers die with the launcher, `PR_SET_PDEATHSIG`, so it must outlive the tool call):
```
date +%s > "$X/smoke_t0"; exec conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python launch.py goldenhex < /dev/null > "$X/smoke_launch.log" 2>&1
```
Then wait for all three servers (up to 120 s):
```
for i in $(seq 1 60); do timeout 20 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -c "import urllib.request; [urllib.request.urlopen(f'http://127.0.0.1:{p}/openapi.json', timeout=3).read() for p in (8001, 8002, 8010)]" 2>/dev/null && { echo ALL-BOUND; break; }; sleep 2; done
grep -c 'overall: PASS' "$X/smoke_launch.log"
```
Expected: `ALL-BOUND`; `1` (`goldenhex` has `run_unit_tests: true`, so `launch.py` ran `run_unit_tests.py` first and it passed). Run one `goldenhex` sequence end to end through the capture rig:
```
timeout 900 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python -m harness.capture --scenario GM-1 --root $SMOKE --out "$X/smoke_gm1" --config-prefix goldenhex > "$X/smoke_capture.log" 2>&1; echo capture rc=$?
find $SMOKE/RUNS -name '*-seq.yml' | head -3
grep -h -A1 '^sequence_status:' $(find $SMOKE/RUNS -name '*-seq.yml') | grep -c -- '- finished'
grep -c '"kind":"sequence","state":"done"' $SMOKE/STATES/runstate_ORCH.jsonl
```
Expected: `capture rc=0`; at least one `RUNS/<yyyy>/<mmdd>/<seq>/…-seq.yml` path (the unified run layout; there is no `RUNS_FINISHED` or `RUNS_SYNCED` directory any more, see Spec deviation 1); `1` or more; `1` or more. Make sure at least 90 s have passed since `smoke_t0`, then check that no child exited early:
```
echo elapsed=$(( $(date +%s) - $(cat "$X/smoke_t0") ))
grep -c 'exited on its own' "$X/smoke_launch.log"
```
Expected: `elapsed` ≥ 90 (wait the difference first if not); `0`. Tear down through `teardown_group()`, the path CTRL-x uses:
```
pgrep -f '^python launch\.py goldenhex$' | tee "$X/smoke_launch.pid" | wc -l
kill -TERM $(cat "$X/smoke_launch.pid")
for i in $(seq 1 60); do kill -0 $(cat "$X/smoke_launch.pid") 2>/dev/null || { echo LAUNCHER-EXITED; break; }; sleep 2; done
test -e $SMOKE/STATES/pids_goldenhex_.pck && echo PID-PICKLE-LEFT || echo PID-PICKLE-CLEARED
timeout 60 conda run -n helao --no-capture-output --cwd "$WT" env PYTHONPATH="$WT" python helao/hexagon/tests/smoke/wait_ports_free.py --timeout 30 8001 8002 8010; echo ports-after rc=$?
```
Expected: `1` (exactly one launcher process; SIGTERM goes to it directly, not to the `conda run` wrapper), `LAUNCHER-EXITED`, `PID-PICKLE-CLEARED`, `ports-after rc=0`. The background tool call then ends on its own. If the pickle is left or a port stays bound, run `helao/hexagon/tests/smoke/kill_group.py $SMOKE goldenhex` and record gate 7 as FAILED. This smoke does not reach `makeActionApp` (spec §2.3, Q7): gate 4's `live_group` users and gate 8 cover that.

- [ ] **Step 16.7b — Controller: push the branch, only after the user approves the push.** Gate 8 runs on a station that fetches from `origin`, and nothing earlier pushes. Pushing is an outward-facing action: ask the user first, and do not push without an explicit yes.
```
git -C "$WT" status --porcelain
git -C "$WT" rev-parse HEAD
git -C "$WT" push -u origin feat/b7b-delete-engine
git -C "$WT" ls-remote origin refs/heads/feat/b7b-delete-engine
```
Expected: no status output; the head SHA; the push succeeds; `ls-remote` prints the same SHA. Record that SHA: it is the one gate 8 must run on.

- [ ] **Step 16.8 — Gate 8 (user): one hexagon station launch before merge.** After Step 16.7b, the controller pastes the section "Gate 8 — station launch" (end of this plan) to the user, together with the pushed SHA, and records the user's report in the PR. B7b does not merge without it.

- [ ] **Step 16.9 — Gate 9: black.** Already run before every `git add`. As a final check:
```
cd "$WT" && git -C "$WT" diff --name-only --diff-filter=AM 64f2cf15 HEAD -- '*.py' | xargs conda run -n helao --no-capture-output --cwd "$WT" black --check; echo black rc=$?
```
Expected: `black rc=0` (black skips the force-excluded `sync_driver` pair by itself).

- [ ] **Step 16.10: PR record.** The controller puts into the PR description:
  - the Task 0 baselines (F0, F0p, pyright 91/426) and the gate 4/5/6 results;
  - Task 1's S7 one-block record (Q1), Task 2's red-check and 13/13 comparison, Task 4's `T4 … deltas=0` and `T4-PROJECTION … equal_to_frozen=True`, Task 9's `ORCH-API BYTES IDENTICAL`;
  - the five checklist drift IDs, unchanged (spec §2.7);
  - Q10: `/prepend_sequences` answers `{"sequence_uuids": [...]}` on legacy and a bare list on `OrchHost`, unchanged by B7b; and the three routes `OrchHost` adds (`/get_config`, `/hotreload_busy`, `/resend_active`);
  - the two named visible changes: the startup log line `"<key>: native ActionHost, skipping the active write graft"` is gone, and the routeless `/ws_globstat` sender is deleted;
  - the one-time cleanup every checkout needs after pulling: `rm -rf helao/core/servers` (Linux) or `rmdir /s /q helao\core\servers` (Windows `cmd`), because git leaves the untracked `__pycache__` behind; the main checkout included;
  - gate 7's result and the user's gate 8 report;
  - the recovery point: `freeze/pre-engine-delete_2609` (`e60d800a`).

---

## Gate 8 — station launch, user-run (paste this section to the user)

**What this proves.** The first hardware launch of B7b's changed `makeActionApp` path. With the engine directory removed from the station checkout, any engine import anywhere in the launched group is a startup `ModuleNotFoundError`, so "every server binds" is the evidence. `/loaded_modules` is **not** evidence (spec §7 gate 8): once the directory is gone it can never name an engine file.

**Where.** The eche10 Windows station, in its parent `helao-async` checkout, in a `cmd` window (not PowerShell: `rmdir /s /q` is a `cmd` built-in). The station's private deployment repositories, if any, are not touched and do not move.

**Before you start.** The station is idle: no sequence running, no group launched. Note the current branch so you can return to it.

1. Confirm a clean tree and record where you are:
   ```
   cd <station helao-async checkout>
   git status --short --branch
   git rev-parse HEAD
   ```
   `git status` must list no modified or untracked tracked-path files. Write the HEAD down in the sign-off table.
2. Fetch and switch to the branch under test:
   ```
   git fetch origin
   git checkout feat/b7b-delete-engine
   git pull
   git rev-parse HEAD
   ```
   The HEAD must equal the SHA the controller gives you with this section (the one it pushed).
3. Remove the engine directory git leaves behind (untracked `__pycache__` survives the checkout and would let `helao.core.servers` import as a namespace package):
   ```
   rmdir /s /q helao\core\servers
   call conda activate helao
   python -c "import importlib.util as u; print(u.find_spec('helao.core.servers'))"
   ```
   The last command must print exactly `None`. (If `rmdir` says the path is not found, the directory was already gone; that is fine.)
4. Resolve the config without launching:
   ```
   python -m helao.hexagon.preflight helao/deploy/hte/configs/eche10_hex.py
   ```
   Expect no findings.
5. Launch, with hot reload off so the watcher cannot restart anything mid-check:
   ```
   python launch.py eche10_hex --no-hot-reload
   ```
   Every server must bind. Watch the launcher console for 90 seconds after the last server reports ready: no line `Server '<key>' exited on its own` may appear. A server that dies in a startup event shows up as uvicorn `SystemExit(3)`; B7b's build-time `TypeError` names the module instead (`<module>.makeApp returned <type>, not an ActionHost`). Either one is a FAIL: stop, copy the console text and that server's log from `C:\INST_hlo\DATA\LOGS\<server>\`.
6. From the operator UI, run one short sequence (the station smoke sequence used for the eche10 golden diff is fine). Let it finish and let SYNC go idle. The sequence has finished when both of these hold (unified run layout; there is no `RUNS_FINISHED` directory any more):
   - `C:\INST_hlo\DATA\RUNS\<yyyy>\<mmdd>\<seq dir>\*-seq.yml` contains `sequence_status:` followed by `- finished`;
   - `C:\INST_hlo\DATA\STATES\runstate_ORCH.jsonl` has a line for that sequence's uuid with `"kind":"sequence","state":"done"`.
7. Tear down with `CTRL-x` in the launcher console. Every server must exit and the launcher must return to the prompt. Then confirm nothing is left listening:
   ```
   python helao\hexagon\tests\smoke\wait_ports_free.py --timeout 30 8001 5002 8003 5003 8004 8005 8008 8011 5001 5005 8010 8013 8015 5110 5111
   echo rc=%ERRORLEVEL%
   ```
   These are the ports `eche10.yml` assigns (the script also checks each one's RPC sibling at +10000). Expected `rc=0`; `rc=2` names the port still held.
8. Return the station to its previous branch (from step 1) unless the controller says otherwise:
   ```
   git checkout <branch from step 1>
   ```
   Checking out the old branch restores the tracked `helao\core\servers` files, because they are tracked there.

**Report back:** the two HEADs (steps 1 and 2), the `find_spec` output (step 3), preflight findings (step 4), PASS/FAIL for "every server bound, none exited within 90 s" (step 5), the finished sequence's directory name (step 6), and whether `CTRL-x` tore down cleanly (step 7). The controller records these in the PR before merge.

**If it breaks after merge** (not part of this gate): a station that fails on a post-B7b `unstable` resets its parent checkout to `freeze/pre-engine-delete_2609` (`git checkout freeze/pre-engine-delete_2609`) and relaunches; its private deployment repositories stay where they are.
