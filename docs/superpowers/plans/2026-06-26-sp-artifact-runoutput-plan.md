# Plan — SP-ARTIFACT run-artifact output wiring

Executes `docs/superpowers/specs/2026-06-26-framework-run-artifact-output-wiring.md`.
Branch: `feat/framework-scaffold`. Env: `conda run -n helao`. Suite baseline: 1589 passed / 28 skipped.

## Background (read before any task)

Framework servers write run artifacts to a throwaway tempdir with uuid meta names
(`{uuid}.act`) that the framework's own syncer (which scans `*-act.yml`) never
picks up, and the finish-relocate jumps straight to `RUNS_SYNCED`, bypassing the
syncer's `RUNS_FINISHED` input. Legacy data lifecycle (the target):

```
write  -> <root>/RUNS_ACTIVE/<nested>/<ts>-{act,exp,seq}.yml + <name>-<conn>.hlo
finish -> move <root>/RUNS_ACTIVE/<nested> -> <root>/RUNS_FINISHED/<nested>
          (manual_action -> RUNS_DIAG, never synced)
sync   -> syncer watches RUNS_FINISHED, ships, moves -> RUNS_SYNCED
```

Already correct, DO NOT change: HLO byte layout + name `<action_name>-<file_conn_key>.hlo`
(`domain/action_session.py:346`); nested path math `%y.%U/<date>/<seq>/<exp>/<act>`
(`domain/lifecycle.py:43-101`); `adapters/fs_storage.py` atomic write_meta + 2/4/2 YAML.

## Global Constraints (bind every task — copy verbatim into reviewer prompts)

1. **Rooting:** `FsStorage.save_root` MUST be the config `root` (the PARENT of the
   `RUNS_*` dirs), NOT `<root>/RUNS_ACTIVE`. Tempdir fallback ONLY when the config
   has no `root` key. An explicit `save_root=` constructor arg still wins (tests).
2. **Run-kind prefix:** every meta/HLO relpath is `<RUN_KIND>/<output_dir>/<leaf>`
   where `RUN_KIND` = `RUNS_DIAG` when `action.manual_action` else `RUNS_ACTIVE`.
   The `lifecycle` path math stays prefix-free; the prefix is applied at the
   storage-facing layer via the shared helpers from Task 1.
3. **Meta filenames (legacy parity, exact):**
   - action: `<action_timestamp.strftime('%y%m%d.%H%M%S%f')>-act.yml`
   - experiment: `<experiment_timestamp...>-exp.yml`
   - sequence: `<sequence_timestamp...>-seq.yml`
   (NOT `{uuid}.act` / `{uuid}-exp.yml`.)
4. **Meta content (legacy parity):** the YAML doc is the object's clean dict with a
   leading `{"file_type": "action"|"experiment"|"sequence"}` key (mirror
   `core/servers/base.py:907-970`). Use the existing run-model `.as_dict()` /
   clean-dict path; prepend the `file_type` key.
5. **Finish relocate:** non-manual finish moves `RUNS_ACTIVE/<out_dir>` ->
   `RUNS_FINISHED/<out_dir>` (NOT `RUNS_SYNCED`). Manual actions are NOT relocated
   (they live under `RUNS_DIAG`). Failure is logged + swallowed (finish never crashes).
6. **No double log-zip:** if `helao_dirs` is called from the Base, call it WITHOUT
   `server_name` (the launcher already rotates logs), or otherwise guard against
   re-zipping logs on Base construction.
7. **Backward-compat:** in-process runners / tests that pass an explicit `save_root`
   keep working. The `test` deployment must still launch.
8. Full framework suite green (`conda run -n helao python -m pytest helao/framework/tests/ -W ignore -q -p no:cacheprovider`) at every task.

## Task 1 — domain meta helpers + action_session parity

**Files:** `helao/framework/domain/lifecycle.py` (add pure helpers),
`helao/framework/domain/action_session.py` (consume them).

Add to `lifecycle.py` (pure, no I/O), and export in `__all__`:
- `run_kind(action) -> str`: `"RUNS_DIAG" if action.manual_action else "RUNS_ACTIVE"`.
- `action_meta_relpath(action) -> str`: `<run_kind>/<action_output_dir>/<act_ts>-act.yml`.
- `experiment_meta_relpath(action) -> str`: `<run_kind>/<experiment_output_dir>/<exp_ts>-exp.yml`.
- `sequence_meta_relpath(action) -> str`: `<run_kind>/<sequence_output_dir>/<seq_ts>-seq.yml`.
- `hlo_relpath(action, leaf) -> str`: `<run_kind>/<action_output_dir>/<leaf>`.
- `meta_doc(kind, body_dict) -> dict`: returns `{"file_type": kind, **body_dict}`.
- `finished_relpath(out_dir) -> str` and the active->finished mapping helper:
  given an `action_output_dir`, return `RUNS_ACTIVE/<out_dir>` and
  `RUNS_FINISHED/<out_dir>` (for the relocate).

Rewire `action_session.py`:
- `_meta_relpath` -> `lifecycle.action_meta_relpath(self.action)`; content via
  `meta_doc("action", <clean action dict>)`.
- manual exp/seq writes (`myinit` ~:161-171 and finish ~:828-832) -> use
  `experiment_meta_relpath`/`sequence_meta_relpath` + `meta_doc(...)`.
- `_hlo_relpath` (:346) -> `lifecycle.hlo_relpath(action, "<name>-<conn>.hlo")`
  (keep the leaf filename; only add the run-kind prefix).
- aux-file relocate dst (:318,:334) -> run-kind-prefixed action_output_dir.
- `_relocate_run_dir` (:864-882): map `RUNS_ACTIVE/<out_dir>` ->
  `RUNS_FINISHED/<out_dir>`; skip for manual actions. Drop `_SYNCED_ROOT`.

**TDD:** real `FsStorage(save_root=<tmp>)`, drive a non-manual action through
init+data+finish; assert: `<tmp>/RUNS_ACTIVE/<nested>/<ts>-act.yml` exists with a
leading `file_type: action` and the `.hlo`; after finish the tree is under
`<tmp>/RUNS_FINISHED/<nested>` and absent from `RUNS_ACTIVE`. A manual action lands
under `RUNS_DIAG` and is not relocated. Update any existing test that pinned the old
`{uuid}.act` names (they were wrong per the spec).

## Task 2 — app rooting (base_api + factory + orch save_root)

**Files:** `helao/framework/app/base_api.py`, `helao/framework/app/factory.py`,
`helao/framework/app/orch_api.py`.

- `FrameworkBase.__init__`: when `world_cfg` has `root`, set
  `self.helaodirs = helao_dirs(world_cfg)` (no `server_name`) and let the app layer
  root storage at `world_cfg["root"]`. When no `root`, `helaodirs=None` (current).
- `BaseAPI.__init__` (:1199) and `factory.makeApp`/`makeActionApp` (:121,:170):
  when `save_root` arg is None, derive it from the loaded config `root`
  (`world_cfg["root"]`); tempdir ONLY when there's no `root`. Explicit arg wins.
- `orch_api` makeOrchApp save_root (:1078-1090): same — config `root`, drop the
  `RUNS_HLO/<server_key>` subpath (orch meta uses the run-kind-prefixed relpaths now).

**TDD:** build an action app and an orch app from a config dict carrying
`root=<tmp>` (no explicit save_root); assert `app.state.base.storage.save_root ==
<tmp>` and `helaodirs.save_root == <tmp>/RUNS_ACTIVE`. With no `root`, assert a
tempdir is used (current behavior preserved). Assert no `*.txt` log is zipped by
Base construction (constraint 6).

## Task 3 — orch exp/seq meta-WRITE parity (write only; relocation is Task 5)

**Files:** `helao/framework/app/orch_api.py` (consumes Task 1 helpers, duck-typed).

The Task 1 helpers `experiment_meta_relpath`/`sequence_meta_relpath`/`run_kind`/
`meta_doc` read only `.manual_action`, `.{experiment,sequence}_timestamp`,
`.{experiment,sequence}_output_dir` — all present on `RunExperiment`/`RunSequence`,
so they apply DUCK-TYPED to the exp/seq objects in `OrchState`.

- `PersistMeta` (`:250-252`): resolve the object from state by kind
  (`kind=="seq"` -> `state.active_sequence`; `kind=="exp"` ->
  `state.active_experiment`); write via `sequence_meta_relpath(obj)` /
  `experiment_meta_relpath(obj)` with `meta_doc("sequence"/"experiment", cmd.payload)`.
  Drop the flat `{uuid}-{kind}.yml`.
- FinishExperiment (`:296-299`): write `experiment_meta_relpath(state.active_experiment
  or state.last_experiment)` + `meta_doc("experiment", _finish_exp_payload(state))`.
- FinishSequence (`:301-304`): write `sequence_meta_relpath(state.active_sequence
  or state.last_sequence)` + `meta_doc("sequence", _finish_seq_payload(state))`.
- PersistMeta and Finish* MUST resolve to the SAME relpath for a given object so the
  finish write overwrites the dispatch-time write (both nested + timestamp stem).
- Do NOT change relocation here. (Action-leaf relocation already lands in Task 1;
  exp/seq relocation + NOSYNC is Task 5.)

**TDD:** drive PersistMeta(kind="seq"/"exp") and FinishExperiment/FinishSequence
through `execute_commands` with a real `FsStorage(save_root=<tmp>)` and an OrchState
carrying populated active_sequence/active_experiment; assert
`<tmp>/RUNS_ACTIVE/<seq_dir>/<exp_dir>/<exp_ts>-exp.yml` and
`<tmp>/RUNS_ACTIVE/<seq_dir>/<seq_ts>-seq.yml` exist with leading `file_type`. Update
the existing `test_app_orch_api.py:374,386` tests that pin the old `{uuid}-exp.yml`.

## Task 4 — controller integration observation (not a subagent task)

Done by the controller after Tasks 1-3:
1. Live `test`-deploy run with `root=<clean tmp>`; observe the on-disk tree.
   ASSERT (the user-observable goal): artifacts now EXIST under `<root>/RUNS_ACTIVE`
   with legacy names (`*-seq.yml`/`*-exp.yml`/`*-act.yml`/`*.hlo`) in the correct
   nested layout, plus action-leaf dirs promoted to `RUNS_FINISHED` (Task 1).
2. RECORD the actual end-state (which files land in ACTIVE vs FINISHED) to design
   Task 5 against reality, not speculation.
3. Diff a sample meta file vs a legacy `test` run (content modulo uuid/timestamp).

## Task 5 — orch dispatch-stamping + relocation parity (scoped from Task 4 observation)

**Task 4 observed:** action write+relocate WORKS (`RUNS_ACTIVE/<nested>/<ts>-act.yml`
+ `<name>-<conn>.hlo`, `file_type: action` leading; leaf dir promoted to
`RUNS_FINISHED`; empty `RUNS_ACTIVE` parent dirs remain — syncer prunes). Two gaps
remain, both orch-side:

**5a. Stamp seq + exp + staged-action output-dirs/timestamps at dispatch.**
`domain/orchestration.py` `dispatch_sequence` (~:1100-1146) and `dispatch_experiment`
(~:1182-1235) stamp uuids/timestamps but NOT output_dirs. Three stamps needed:
- `dispatch_sequence`: after `sequence_timestamp` is set, set
  `seq.sequence_output_dir = seq.get_sequence_dir()` if None.
- `dispatch_experiment`: thread `exp.sequence_output_dir =
  state.active_sequence.sequence_output_dir` (+ sequence_timestamp/name/label as
  needed), then after `experiment_timestamp` set, `exp.experiment_output_dir =
  exp.get_experiment_dir()` if None.
- `dispatch_experiment` STAGED ACTIONS (~:1223-1230): the action server's
  `_get_action` does NOT call `init_act` or compute `action_output_dir`, so each
  staged `act` must arrive fully stamped or it writes to `RUNS_ACTIVE/None/...`
  (the old obs-789 bug). For each `act`: thread parent identity from seq+exp
  (sequence_timestamp, sequence_output_dir, sequence_uuid, experiment_timestamp,
  experiment_output_dir, experiment_uuid, names/label) and set
  `act.action_timestamp` (keep injected `now` if already set) and
  `act.action_output_dir = lifecycle.action_output_dir(act)` (needs
  `act.action_server.server_name`, orch_submit_order — set by the loop). DO NOT call
  `act.init_act()` (it uses internal set_time/gen_uuid and would break the
  deterministic injected now/uuid the tests rely on); stamp fields directly.
This makes Task 3's nested exp/seq write AND the action-server nested write fire.
TDD: drive dispatch_sequence/dispatch_experiment with expand_result; assert the
seq, exp, and each staged action carry non-None nested output_dirs (no `None/`
segment), and that the deterministic action_uuid/now stamping is preserved.

**5b. Relocate exp/seq on finish (port `move_dir`, unify with action).**
Port `helpers/yml_tools.py:132` `move_dir` file-granular promotion as ONE storage
mechanism used for action/exp/seq finishes: copy the object's files
`RUNS_ACTIVE/<dir>` -> `RUNS_FINISHED/<dir>` (`.hlo` -> `RUNS_NOSYNC` when
`sync_data=False`), then remove source. Reconcile with Task 1's action-leaf
relocate (replace `relocate_dir`-to-FINISHED with the unified mechanism — one path,
not two). Manual -> `RUNS_DIAG` (no FINISHED). Wire exp/seq relocation into the
FinishExperiment/FinishSequence handlers (emit/execute the move after the meta
write). May add a small storage move primitive (port + FsStorage + fakes) — decide
in implementation; keep the ports contract clean. Failure logged + swallowed.
TDD: full seq->exp->act tree ends under `RUNS_FINISHED` with legacy names; manual
under `RUNS_DIAG`; `sync_data=False` `.hlo` under `RUNS_NOSYNC`.

**5c. Sync pickup (controller verification after 5a/5b).**
Confirm the framework `HelaoSyncer` (`app/sync_driver.py`) enqueues the produced
`RUNS_FINISHED` tree (its `list_pending` scans `*-act/-exp/-seq.yml`, now matching).
Full framework suite green. Then a real legacy-vs-framework on-disk diff is the
acceptance artifact (spec §6).
