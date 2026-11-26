# Record schema slimming, inputs-only `action_params`, hook provenance

Date: 2026-11-24. Status: approved design, pending implementation plan.

Private deployments are named by alias only (this repo is public): Deployment-A,
Deployment-C, Deployment-E. `hte` and `test` keep their names.

## 1. Purpose

Sequence and experiment records are slow to fetch, parse and verify from S3. The
cost is list attributes that copy what other records already hold. This spec
covers three independent parts, each shippable on its own:

1. **List attributes to plan sidecars.** Drop the `planned_*` and
   `dispatched_*_abbr` lists from sequence and experiment records. Replace them
   with compact uuid lists and a write-once plan sidecar.
2. **`action_params` holds inputs only.** Values an action produces go to
   `action_output`, never back into `action_params`.
3. **Hook provenance.** Act, exp and seq metadata name the pre-finish and
   post-finish hooks that applied to them.

Success:

- A sequence record's size no longer grows with its experiment count.
- `action_params` in a new `-act` record equals what the action was dispatched with.
- Every record shows which hooks touched it.

## 2. Evidence

All measurements were read-only, on the archive host's `RUNS` tree: all 599
sequence dirs, 29,376 experiment records and 35,011 process records. Byte shares
are of compact JSON per top-level key.

| record | largest fields | notes |
|---|---|---|
| seq | `planned_experiments` 93%, `sequence_params` 7% | XRFS seq records up to 0.88 MB; one legacy record 7.3 MB |
| seq, inside each planned entry | `experiment_params` 87%, `experiment_output_dir` 8% | each entry repeats its own `-exp` record |
| exp | `experiment_params` 46%, `planned_actions` 23%, `dispatched_actions_abbr` 7.5% | max 30 KB |
| prc | `process_params` 36%, `files` 33%, `dispatched_actions_abbr` 12% | max 10 KB |

- That tree holds only converter output, so `dispatched_experiments_abbr` was
  empty in all 599 records. Orchestrated sequences fill it at finish
  (`Sequence.get_seq`) with the same `ShortExperimentModel` shape. Their records
  are therefore about twice the size measured.
- Orchestrated `planned_actions` entries are full `Action` dumps.
  `ActionPlanMaker.add` builds each one from `Experiment.as_dict()`, and
  `ExperimentModel.planned_actions` is an untyped `list`. Station exp records
  are larger than the 30 KB measured here.
- `helao/helpers/run_state.py:310` documents production sequence records of
  427k to 560k lines.
- No code in any repo reads seq `planned_experiments`, seq
  `dispatched_experiments_abbr`, exp `planned_actions` or exp
  `dispatched_actions_abbr` back from a stored record. All uses are of the
  in-memory runtime models.
- Process `dispatched_actions_abbr` has about 10 stored-record readers (loaders,
  analyses, repair scripts). It is out of scope.
- The API links processes to sequences. It ingests no experiment schema.
- `s3_upload` pushes the full `clean_dict` of each record to
  `<kind>/{uuid}.json`. Sequences and experiments upload no files, only meta.

## 3. Part 1: list attributes to plan sidecars

### 3.1 Record schema

`SequenceModel`:

- The record omits `planned_experiments` and `dispatched_experiments_abbr`.
- New `experiment_list: list[UUID]` holds the dispatched experiment uuids in
  dispatch order. `Sequence.get_seq()` fills it from `dispatched_experiments`.
  When that is empty it falls back to the uuids of a `dispatched_experiments_abbr`
  set directly on the runtime model. Deployment-C converters set the
  abbreviated list directly, and their records reach disk through
  `PostHocRunWriter` and `MetaWriter.write_seq`, so they need no change.

`ExperimentModel`:

- The record omits `planned_actions` and `dispatched_actions_abbr`.
- New `action_list: list[UUID]` holds the dispatched action uuids in dispatch
  order, including split and retried actions. `Experiment.get_exp()` fills it
  from the folded `dispatched_actions_abbr`, which covers both the orchestrator
  (folded from `dispatched_actions`) and converters (set directly).

The omitted fields stay on the models, for three reasons:

- `ShortSequenceModel.planned_experiments` is the operator-to-orchestrator input
  contract.
- The orchestrator, the queue pickle, the operator UIs and `MicroOrch` read
  these fields in memory.
- `get_exp()` still folds `dispatched_actions` into samples and files.

Old records and S3 objects still validate, because the fields still exist on the
models.

### 3.2 One write path for records

- Each model gets a class-level exclude set and one
  `record_dict(strip_private=False)` method. It returns
  `clean_dict(strip_private)` minus that set. Each writer keeps the
  `strip_private` value it passes today: local records keep `_`-prefixed keys,
  and S3 pushes strip them.
- These writers switch to `record_dict()`:
  - `MetaWriter.write_seq` and `MetaWriter.write_exp`, which also serve
    Deployment-C converters through `PostHocRunWriter`
  - the meta push in `helao/core/hooks/builtin/s3_upload.py`
  - the initial sequence and experiment S3 uploads in `orch_dispatch.py`
  - `MicroOrch` record writes
- `clean_dict` itself is unchanged. HTTP and WebSocket transport and the queue
  endpoints still carry the full lists.

### 3.3 Plan sidecars

Files:

- `<ts>-seq.plan.json` sits beside `-seq.json`. `<ts>-exp.plan.json` sits beside
  `-exp.json`.
- `meta_kind()` returns `None` for these names: the text before `.json` ends in
  `seq.plan`, which is not in `META_KINDS`. Record globs therefore never match
  them.
- Envelope:
  `{"file_type": "sequence_plan" | "experiment_plan", "<kind>_uuid": ..., "planned": [...]}`.
- The sidecar's name is appended to the record's `aux_files`.

Entries (one small pydantic model per entry type, used only by the writer):

- Sequence plan entry: `order`, `experiment_name`, `experiment_comment`,
  `orch_key`, `orch_host`, `orch_port`, `data_request_id`,
  `from_global_exp_params`. No `experiment_params`, no `experiment_output_dir`.
  Experiment uuids are not assigned until dispatch, so entries carry none.
- Experiment plan entry: `action_uuid`, `action_order`, `action_name`,
  `action_server.server_name`, `start_condition`, `process_finish`. No
  `action_params`. Action uuids exist once actions are staged, so a plan can be
  diffed against `action_list`.

When written:

- Write once. An existing plan file is never overwritten, so a `--restore`
  resume keeps the original intent.
- Sequence plan: when `planned_experiments` settles in `orch_dispatch.py`
  (around line 826), before the first `write_seq`.
- Experiment plan: after `unpack_experiment` stages the actions (around line
  680), once action uuids are assigned.
- `MicroOrch` writes plans through the same helper.
- Deployment-C converters write no plan. Their plan always equals what ran.
- Operator queue edits after the start (`orch_dispatch.py:829-848`) are not
  captured. The plan records initial intent; `experiment_list` and `action_list`
  record what ran.

Writer:

- One `MetaWriter.write_plan(...)`. It uses `_write_meta_atomic`, so the
  `staging_path` rule holds.
- The output is hashed with `log_artifact_hashes`, as
  `helao/core/tests/test_artifact_hash_gate.py` requires.
- SYNC never parses a plan sidecar. `zip_dir` carries it into the sequence
  archive.

S3:

- `s3_upload` also pushes each `aux_files` entry ending in `.plan.json`, to
  `sequence/{uuid}.plan.json` or `experiment/{uuid}.plan.json`.
- This happens before the meta push. A failed push raises like a failed meta
  push, so the record stays unsynced.

## 4. Part 2: `action_params` holds inputs only

### 4.1 Rule

A key written to `action_params` after the action session opens belongs in
`action_output`. "After" covers `_pre_exec`, the executor body, `_post_exec` and
pre-finish hooks.

These writes stay in `action_params`, because they are input normalization done
before the session opens:

- admission and endpoint defaults
- technique parameters computed before the executor
- name aliasing for driver calls
- offline converter record building

### 4.2 One write path: `set_output`

Today nothing populates `action_output` except `action_host.py:1518`
(`error_message`). This spec adds one write path, and every output write goes
through it. No other code writes `action_output` directly.

`ActionModel.set_output(**values) -> None` is the only writer of
`action_output`. It merges `values` into the dict and never raises. It exists
on the model because two writers hold an `Action` with no session:

- the startup reconcile at `action_host.py:1518`;
- the Deployment-E spectrometer endpoint, which records `int_time_ignored`
  before `ctx.begin()`, by design, so that a setup failure answers with no
  artifacts.

`ActionSession.set_output(**values) -> None` is what code inside a running
action calls:

- It delegates to `self.action.set_output`. `self.action` is always the
  session's running split: a split (`action_finalizer.split`) re-initializes it
  in place and keeps a deep copy of the previous split in `action_list`.
- It logs a `WARNING` naming the keys when `self.action` already carries
  `HloStatus.finished`. The record may already be written, so the value may be
  lost. A session-level "finish entered" flag is not used:
  `split_and_finish_prev_uuids` calls `finish()` for earlier splits while the
  running split continues, so such a flag would warn on legitimate writes.

Call sites:

- Every output site inside a run already holds `self.active` or receives
  `active`. That includes drivers called from `_post_exec` and
  `orch_host.add_global_param`. A write becomes
  `self.active.set_output(total_scc=...)`.
- The Deployment-E alias pattern (`p = ...action_params; p[k] = v`) becomes a
  `set_output` call per write. A key the same function reads back afterwards is
  read from a local variable.
- The two session-less writers call `action.set_output(...)`.

Out of scope: a typed output model per action, and routing outputs through
`DriverResponse.data`. Both would redesign every driver, and nothing reads them.

### 4.3 Sites that move

Key names do not change, including the `_`-prefixed keys used by
`to_global_params`. Each listed write becomes a `set_output` call.

- `hte`:
  - `calc_server.py:261,312`
  - `andor_server.py:224,392`
  - `sample_server.py:124,594-596,625,841,930`
  - `syringe_server.py:117`
  - `gamry_server2.py:393,408`
  - `biologic_server.py:325,340`
  - `spec_server.py:294,379,380`
  - `alicat_driver.py:593,752,916`
  - `sprintir_driver.py:305`
  - `xafs_server.py:106,231,235,240,335,347,350,357,393`
  - `galil_motion.py:493,511,558`
- Deployment-E: the spectrometer server's run outputs (counters, `applied_*`,
  calibration results, trigger handoff state, `error_detail`,
  `stopped_executors`, the store-dark update). This includes writes made through
  a local `p = ...action_params` alias, which a plain search misses.
- Deployment-A: potentiostat `*__mean_final`, `hardware_stopped_condition`,
  `has_bubble` and `activated`; motion `returned_positions`; DI server latest
  sample; mux valve resolved identifiers.
- `test`:
  - `cpsim_server.py:100,114`
  - `cpsim_driver.py:226`
  - `gpsim_server.py:92,113`
- Core: `orch_host.py:726` (`add_global_param`).

### 4.4 Rulings on ambiguous sites

| site | ruling |
|---|---|
| `orch_host.py:726` `add_global_param` | move to `action_output`: the value is published, not consumed |
| `hte` `spec_server.py:372` `int_time_ms` | stop overwriting the input. The calibrated value is already in `calibrated_int_time_ms` |
| `hte` `galil_motion.py:349,617` `d_mm/axis/mode/transformation` | stays as input normalization. `motor_move` reads these as its inputs |
| Deployment-A mux valve `valve_number/valve_name/mux_id` | resolved values go to `action_output` under the same names. The requested input is left untouched |
| Deployment-E trigger handoff initial value | moves to `action_output`, so the key's whole lifecycle is in one dict |
| Deployment-E `int_time_ignored` | moves to `action_output` |

### 4.5 `to_global_params`

- One helper, `resolve_global_exports` in `helao/helpers/global_exports.py`,
  resolves each key from `action_output` first, then `action_params`. It lives
  in `helao/helpers` because `MicroOrch` (in `helao/core`) imports nothing from
  `helao/hexagon`.
- Three call sites use it: the orchestrator fold, `finalizer.py:280` and
  `MicroOrch._capture_to_global`. This removes the two duplicate copies.
- The output-first order is required. `calc_server.py` reads
  `min_offset_ocv` and `CP_Ewe_V__mean_final` as inputs and writes results under
  the same names (exported at `HISPEC_exp.py:629,904`). Params-first would
  export the stale input.

### 4.6 Readers of stored records

These two readers check `action_output` first, then fall back to `action_params`,
because old records keep the keys in params:

- the Deployment-E batch processor that reads `trigger_handoff` and
  `first_trigger_epoch_s` from `-act` records
- the Deployment-C XAFS analysis, which reads `scan_state` from `-act` records

Tests that assert these keys in `action_params` are updated to assert them in
`action_output`.

Note, not fixed here: the same Deployment-E processor reads
`first_frame_epoch_s`, which no code writes.

### 4.7 Regression guard

- `ExecutorRunner.action_loop_task` snapshots `action_params` (keys and values)
  onto the session just before `executor._pre_exec()`. It does not snapshot at
  session open: input normalization often runs in the endpoint body right after
  `ctx.begin()` (`biologic_server.py:428-430`, `gamry_server2.py:1147`,
  `galil_io.py:102-104`, `nidaqmx_server.py:143-146`, `galil_motion.py:341-349`),
  and a snapshot there would warn on every such action.
- The finalizer diffs `action_params` against the snapshot after pre-finish
  hooks have run. It logs one `WARNING` naming every added or changed key.
- Actions with no executor have no snapshot and are not guarded. That is the
  known ceiling: a new executor-less endpoint that writes an output into
  `action_params` goes unwarned. Their existing output sites still move to
  `set_output` in this work.
- The guard warns only. It never moves keys and never raises.
- The warning text points to `set_output`, so whoever reads the log knows the fix.

## 5. Part 3: hook provenance

### 5.1 Pre-finish

- New `prefinish_hooks: list[str]` on `ActionModel`, `ExperimentModel` and
  `SequenceModel`.
- `run_prefinish` (`helao/core/hooks/prefinish.py`) appends the hook name before
  running each hook. A failed hook is therefore listed too, and its error stays
  in `prefinish_errors`.
- The name recorded is the config key: a builtin alias or the legacy
  post-processor module name.
- The default is `[]`. `clean_dict` drops it, so a record without hooks is
  byte-identical to today.
- `prefinish_hooks` joins `_RUNTIME_ACTION_FIELDS` in `orch_persist.py`, so a
  re-run copy starts clean.
- All callers route through `run_prefinish`: `finalizer.py:374`,
  `orch_lifecycle.py:107,184` and `micro_orch.py:1268,1288`.

### 5.2 Post-finish

- New `postfinish_hooks: list[str]` on the same three models.
- `s3_upload` sets it on the outgoing meta only. The value is the names from
  `syncer.postfinish[level].select(name)`, in chain order. It is set before
  `MOD_MAP[...]` validation, so the model keeps it.
- The local record is never changed. This honours the post-finish contract in
  `helao/core/hooks/__init__.py`.
- The field names the selected chain, not confirmed completions. Each hook's
  outcome stays in the `.prg` `hooks:` block.
- Process records are out of scope: their meta goes through `sync_process`, not
  the chain.

## 6. Rollout

Delivery:

- Part 1 changes the parent repo and the Deployment-C converters.
- Part 2 changes the parent repo first, then `hte`, Deployment-E, Deployment-A,
  `test`, and the Deployment-C analysis reader.
- Part 3 changes the parent repo only.
- Each part gets one commit set per repo.

Order and mixed versions:

- The parent goes first. The output-first helper works with old action servers,
  which keep keys in params and so hit the fallback.
- One hazard: a new action server with an old orchestrator. The old fold reads
  params first, so the `calc_server` keys would export the stale input.
- Rule: update a station's orchestrator and action servers together. This
  matches the existing `dispatch_id` rollout note in `helao/hexagon/app/CLAUDE.md`.
- The archive host pulls default branches automatically, so a push is a deploy.
  Pushes wait for owner approval, repo by repo.

Compatibility:

- Old records and S3 objects are untouched. No backfill.
- `hlo_version` marks records written in the new shape.
- The `run_state.py:310` comment about 400k-line sequence records is updated.

## 7. Testing

Every new test gets a mutation check: revert the change it guards and confirm
the test fails.

Part 1:

- `record_dict` omits the four lists. `clean_dict` still carries them.
- `experiment_list` and `action_list` follow dispatch order, including split and
  retried uuids.
- Plan entries contain no `experiment_params`, `experiment_output_dir` or
  `action_params`.
- A plan is written once, and a second write (a restore) leaves the file
  unchanged.
- `meta_kind("<ts>-seq.plan.json")` is `None`.
- `s3_upload` pushes the plan keys (with `to_s3` mocked).
- A sequence record's size stays flat as its planned experiment count grows.
- Live simulated group from the `test` deployment: records and sidecars are on
  disk with the expected fields.

Part 2:

- The helper prefers `action_output` when a key is in both dicts.
- The guard warns on an added key and on a changed key, and stays silent when
  nothing changed or when the action had no executor.
- The snapshot is taken at executor start: a key written after `ctx.begin()`
  but before the executor runs is in the snapshot and is not warned on.
- `ActionSession.set_output` merges into the running split's `action_output`.
  After a split, the previous split's copy does not receive the write.
- `ActionSession.set_output` on an action already marked finished logs a
  `WARNING` naming the keys and does not raise.
- No non-test code writes `action_output` directly. A source sweep test fails
  on any `action_output[...] =`, `action_output.update(` or reassignment of
  `.action_output` outside `ActionModel.set_output`.
- Driver tests are updated to the new location.
- Both stored-record readers handle old and new record shapes.

Part 3:

- `run_prefinish` records a hook that fails.
- `s3_upload` stamps the selected chain on the S3 meta.
- The local record is byte-identical before and after the post-finish chain.

Gate: a full `run_tests.py` sweep across the parent and every deployment,
compared with the current baseline.

Acceptance: for one real station sequence, report the byte size of
`sequence/{uuid}.json` before and after, in the PR.
