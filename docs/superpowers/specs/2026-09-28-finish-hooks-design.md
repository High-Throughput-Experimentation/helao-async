# Config-defined pre-finish and post-finish hooks

Date: 2026-09-28
Status: design approved, plan not yet written
Builds on: `2026-09-25-runs-layout-and-state-journal-design.md` (single RUNS tree, records finish and sync in place, `.prg` as sync receipt)
Supersedes: `hlo_postprocess_libs`, `exp_postprocess_libs`, `seq_postprocess_libs`, `auto_analyze_sequences` (kept as aliases)

## 1. Problem

Work that happens around a record's "finished" transition is spread across four
unrelated mechanisms, each with its own config key, contract, owner, and failure
behaviour:

| Mechanism | Config | Runs in | Contract | Failure |
|---|---|---|---|---|
| `.hlo` post-processing | `hlo_postprocess_libs` on an action server entry | action server finalizer (`adapters/native/finalizer.py:394-406`) | `HloPostProcessor.process() -> list[FileInfo]` | swallowed |
| experiment meta post-processing | `exp_postprocess_libs` on the orch entry | `orch_lifecycle.finish_active_experiment:166-175` | `MetaProcessor.process()` mutates in place | swallowed |
| sequence meta post-processing | `seq_postprocess_libs` on the orch entry | `orch_lifecycle.finish_active_sequence:79-88` | same | swallowed |
| S3 upload, `.hlo`→`.hlo.json` | none (hard-wired) | SYNC `sync_yml` | inline code | record stays unsynced, retried |
| auto-analysis | `auto_analyze_sequences` in SYNC `params` | SYNC `sync_yml`, sequences only | HTTP dispatch to one endpoint | logged |

Adding a new step — uploading to alternative storage, pushing to an external
API — means editing `sync_yml`. The ordering of the existing steps is implicit,
and in one place wrong: an experiment's `finished` status is put on the lbuf
(`orch_lifecycle.py:139`) *before* its post-processors run (`:166`), while an
action and a sequence both run post-processing first.

`MicroOrch` (`helao/core/runners/micro_orch.py`) bypasses all of it at the
experiment and sequence level: it writes its own exp/seq ymls, runs no
post-processors, and never calls `finish_yml`, so SYNC never learns of those
records (and defers their actions forever, waiting for a parent yml it was
never handed). It also still writes to `RUNS_FINISHED`/`RUNS_DIAG`
(`_finished_root`, `:891`), which the RUNS unification retired
(`run_dir.py:46`: "Nothing writes these"), so its experiments land in a
different tree from their own actions.

## 2. Decisions

| # | Decision |
|---|---|
| D1 | Two phases. **Pre-finish** runs in the server that owns the record (action server for actions, orchestrator or `MicroOrch` for experiments and sequences), in order, before the final yml is written and before `finished` is emitted; it may change the record. **Post-finish** runs in SYNC after the record is finished; it may not change the record. |
| D2 | Pre-finish config is a dict on the owning server's entry: hook name → list of record names it applies to. Post-finish config is `postfinish_hooks` at the **top level** of the SYNC entry, with three sub-dicts: `action`, `experiment`, `sequence`, each of the same shape. |
| D3 | Dict key order is execution order. `"*"` in the list means every record. A value may instead be a mapping `name: args` for hooks that need per-name arguments. |
| D4 | S3 upload and auto-analysis become ordinary post-finish hooks (`s3_upload`, `dispatch_analysis`). If `postfinish_hooks` is absent, SYNC uses a default chain equivalent to today's behaviour. A config that defines `postfinish_hooks` owns the whole chain and must list `s3_upload` itself. |
| D5 | Post-finish failure semantics are declared by the hook class (`blocking` attribute), not the config. A blocking failure stops the chain and keeps the record unsynced; a non-blocking failure is recorded and the chain continues. "Synced" means every blocking hook succeeded. |
| D6 | A pre-finish failure is logged with an alert, recorded on the record in `prefinish_errors`, and does not stop the chain or the finish. |
| D7 | One hook contract (`FinishHook`) for both phases. Existing `HloPostProcessor` and `MetaProcessor` classes run unchanged through adapters. |
| D8 | `MicroOrch` is in scope: fixed roots, pre-finish hooks at experiment and sequence level, and `finish_yml` so post-finish applies to its records. |
| D9 | Analyses stay dispatched to the analysis server as action endpoints (so they remain manually re-runnable); `dispatch_analysis` passes a path, not an object. |

## 3. Config surface

```yaml
servers:
  SPEC_R:
    group: action
    fast: spec_server
    prefinish_hooks:
      hispec_process_all: [acquire_spec_adv, acquire_spec_extrig]
      hlo_to_csv: ["*"]

  ORCH:
    group: orchestrator
    fast: async_orch2
    prefinish_experiment_hooks:
      append_params: [SOME_experiment]
    prefinish_sequence_hooks:
      append_ref_vshe: ["*"]

  SYNC:
    group: action
    fast: sync_server
    postfinish_hooks:
      action:
        s3_upload: ["*"]
      experiment:
        s3_upload: ["*"]
      sequence:
        s3_upload: ["*"]
        dispatch_analysis:
          SOME_sequence: {server_key: ANA, endpoint: analyze_something, params: {}}
    params: {...}
```

Matching keys: `action_name` for actions, `experiment_name` for experiments,
`sequence_name` for sequences.

### 3.1 Aliases

| Old key | Translated to |
|---|---|
| `hlo_postprocess_libs: [a, b]` | `prefinish_hooks: {a: ["*"], b: ["*"]}` |
| `exp_postprocess_libs: [a]` | `prefinish_experiment_hooks: {a: ["*"]}` |
| `seq_postprocess_libs: [a]` | `prefinish_sequence_hooks: {a: ["*"]}` |
| SYNC `params.auto_analyze_sequences: {seq: {...}}` | `postfinish_hooks.sequence.dispatch_analysis: {seq: {...}}` (added to the default chain) |

Each alias logs one deprecation warning at startup. A server entry that sets
both an old key and its replacement is refused at startup, naming both keys.

### 3.2 Default post-finish chain

When `postfinish_hooks` is absent:

```yaml
action:     {s3_upload: ["*"]}
experiment: {s3_upload: ["*"]}
sequence:   {s3_upload: ["*"], dispatch_analysis: <from auto_analyze_sequences, if present>}
```

### 3.3 Validation

At server startup (action server, orchestrator, SYNC; `MicroOrch.start()`):
every hook name resolves to a class (§4.3), every value is a list of strings
or a mapping of string → mapping, and `postfinish_hooks` has no keys other
than `action`/`experiment`/`sequence`. Any violation raises and names the
offending key; a bad hook config never degrades silently to "no hooks".

## 4. Hook contract

### 4.1 `FinishHook`

New module `helao/core/hooks/__init__.py`:

```python
class FinishHook(ABC):
    blocking: bool = True      # consulted for post-finish only (D5)

    @abstractmethod
    async def run(self, ctx) -> None:
        """Raise to signal failure."""
```

A hook that does blocking I/O or CPU work wraps it in `asyncio.to_thread`
itself. Hook instances are created once per server at startup and reused.

### 4.2 Contexts

```python
@dataclass
class PrefinishContext:
    record: Action | Experiment | Sequence   # live model; hooks may mutate
    record_dir: Path
    server: Any                              # ActionHost / Base / Orch / MicroOrch
    args: dict | None                        # per-name args, or None

@dataclass
class PostfinishContext:
    yml: HelaoYml
    data: HelaoData                          # the finished record
    prg: Progress                            # read-only for the hook
    syncer: HelaoSyncer                      # S3 client, dispatcher, config
    args: dict | None
```

A post-finish hook's only persistent state is its own entry in `prg.dict["hooks"]`,
which the runner writes, not the hook.

### 4.3 Loading

`import_postprocessors` (`action_host.py:441-510`, legacy `base.py:827`)
becomes `import_hooks`, with the same resolution order:

1. built-ins in `helao/core/hooks/builtin/<name>.py`;
2. an existing `.py` path;
3. `helao/deploy/<CONFIG deployment>/processors/<name>.py`;
4. `helao/deploy/hte/processors/<name>.py`;
5. any `helao/deploy/*/processors/<name>.py`.

The module's class named `Hook` (new) or `PostProcess` (existing) is used.
A `FinishHook` subclass is used directly; an `HloPostProcessor` or
`MetaProcessor` subclass is wrapped (§4.4); anything else is a startup error.
A single loader is shared by the action host, both orchestrators, `MicroOrch`,
and both SYNC drivers.

### 4.4 Adapters for existing processors

- `HloPostProcessorHook(cls)`: `await asyncio.to_thread(cls(ctx.record, save_root).process)`,
  result assigned to `ctx.record.files`. Action level only.
- `MetaProcessorHook(cls)`: `await asyncio.to_thread(cls(ctx.record, ctx.server).process)`.
  Experiment and sequence level (and action level, which it never supported
  but costs nothing).

The seven existing processor classes (five `HloPostProcessor`, two
`MetaProcessor`, across the public and private deployments) need no edits.

## 5. Pre-finish flow

A shared runner, `run_prefinish(hooks, record, name, record_dir, server)`:

1. Select the hooks whose list contains `name` or `"*"`, in config order.
2. Run each one. On exception: `LOGGER.alert` with the hook name, record name
   and uuid; append `{"hook", "error", "ts"}` to `record.prefinish_errors`;
   continue with the next hook.
3. Return. The caller then writes the final yml and emits `finished`.

No timeout (unchanged from today; a hung hook shows as an action that never
finishes).

### 5.1 Call sites

| Level | Where | Replaces |
|---|---|---|
| action | `finalizer.py` `_finish`, after file handles close, before `write_act` (current `:394-406`); legacy twin `active_finalizer.py` | the `hlo_postprocess_libs` loop |
| experiment | `orch_lifecycle.finish_active_experiment` | `:166-175`; **and** `put_lbuf(finished)` at `:139` moves to after the hooks, before `write_exp` |
| sequence | `orch_lifecycle.finish_active_sequence` | `:79-88` (order already correct) |
| experiment | `MicroOrch.run_experiment`, before each `_write_exp` of a finished experiment | nothing (new) |
| sequence | `MicroOrch.run_sequence`, before `_write_seq` | nothing (new) |

Only the current split of a split action is processed, as today. Manual
actions run hooks too; matching is by name.

### 5.2 `prefinish_errors`

New field `prefinish_errors: list[dict] = []` on `ActionModel`,
`ExperimentModel`, `SequenceModel`. `clean_dict` omits it when empty, so
existing ymls are byte-identical. It reaches S3 through the normal meta upload.
Readers that validate with a strict schema would see a new key; none are known.

## 6. Post-finish flow (SYNC)

Both `helao/core/drivers/data/sync_driver.py` (live on every station, including
`*_hex` groups) and `helao/hexagon/adapters/native/sync_driver.py` (source-parity
pinned) receive the same change.

### 6.1 Split of `sync_yml`

**Core** (stays in `sync_yml`): the complete-`.prg` skip; the still-active gate;
deferring an action whose parent yml is missing; re-queueing unsynced children
and lowering the parent's rank; hierarchy locks; merging `files_pending`;
`reconcile_processes` and writing local `-prc.yml` files; then the chain
(§6.2); then, if the chain reports synced, `synced: true`, the `DONE` journal
entry, `.lock` removal, the unregistered-file warning, and re-queueing the
parent.

**`s3_upload`** (built-in, `blocking = True`): today's S3 calls moved verbatim —
file uploads (`.hlo` → `.hlo.json` under 1 GB, parquet above), `files_s3`
bookkeeping and the `files` rename in the uploaded meta, process json uploads at
the levels they happen today, the `MOD_MAP` meta patch, the meta json upload, and
the `s3`/`api` flags. It keeps writing `files_s3`, `process_s3` and `s3`, so a
partially uploaded record resumes where it stopped.

**`dispatch_analysis`** (built-in, `blocking = False`): today's auto-analysis.
`args` = `{server_key, endpoint, params}`. Dispatches with
`{"sequence_path": <seq dir>, "params": params}` at sequence level and
`{"experiment_path": <exp dir>, "params": params}` at experiment level (the
directory is stable now that nothing zips). No existing analysis endpoint takes
`experiment_path`; an endpoint configured at experiment level must accept it.

### 6.2 Chain execution

`.prg` gains:

```yaml
hooks:
  s3_upload: {state: done, ts: 2026-09-28T14:39:43}
  push_api:  {state: failed, ts: ..., error: "..."}
synced: true
```

Per record, per `sync_yml` pass, for each matching hook in config order:

- `state: done` → skip.
- non-blocking and `state: failed` → skip (not retried automatically; clearing
  the entry re-arms it).
- run it:
  - success → `state: done`, written atomically (`Progress.write_dict`);
  - blocking failure → `state: failed` with the error; stop the chain;
    `sync_yml` returns False, and the record takes the existing retry path of
    a failed S3 upload; the next pass re-runs this hook;
  - non-blocking failure → `state: failed` with the error, `LOGGER.alert`,
    continue.

The chain reports synced when every blocking hook in it is `done`.

### 6.3 Completeness

`run_state._prg_is_complete` and SYNC's own already-synced check accept either
`synced: true` or the legacy `s3: true` + `api: true`. Records synced before this
change are complete and never run hooks.

## 7. MicroOrch

1. `_finished_root` is replaced by `run_root(root)` / `diag_root(root)` from
   `run_dir.py`, so experiment and sequence ymls land beside their actions.
2. `_write_meta_atomic` uses `replace_when_free` (`helpers/file_utils.py`).
3. Pre-finish hooks for experiments and sequences come from the world config's
   orchestrator entry (`prefinish_experiment_hooks`, `prefinish_sequence_hooks`,
   plus the aliases), overridable by constructor keywords of the same names.
   Validated in `start()`.
4. After writing a finished experiment or sequence yml, `MicroOrch` calls
   `yml_finisher` (the same `finish_yml` POST the orchestrator's `move_dir`
   makes) when the world config has a SYNC server; a no-op otherwise, exactly
   as `resolve_sync_server_key` returning `None` is today.
5. `_candidate_yml` / `_load_finished` read from the new roots (they currently
   look under `RUNS_FINISHED`/`RUNS_DIAG`).

## 8. Testing

Every new test is checked by reverting the code it covers and watching it fail.

- **Config**: each alias translates correctly; old + new key together refused;
  unknown hook, bad value shape, and stray `postfinish_hooks` keys fail at
  startup naming the key; `"*"` and exact-name matching.
- **Loader**: built-in, path, and deployment-directory resolution; `Hook` and
  `PostProcess` class names; a non-hook class is refused; all seven existing
  processors import and wrap.
- **Pre-finish**: config order; a raising hook records `prefinish_errors`, alerts,
  and the record still finishes; `HloPostProcessor` adapter replaces `files`;
  experiment `finished` is emitted after hooks (the reordering).
- **Post-finish**, parametrized over the legacy and native SYNC drivers like the
  existing sync tests (`helao/hexagon/tests/sync_fixtures.py`):
  - the default chain produces the same S3 keys, `.prg` fields and meta json as
    today (golden);
  - blocking failure stops the chain, record stays unsynced, retry resumes at the
    failed hook, earlier `done` hooks do not re-run;
  - non-blocking failure is marked `failed` and does not block `synced`, the
    `DONE` journal entry, or the parent;
  - `dispatch_analysis` sends what `auto_analyze_sequences` sends today;
  - a legacy-complete `.prg` (`s3` + `api`) runs nothing.
- **MicroOrch**: exp/seq ymls land under `RUNS/%Y/%m%d` beside their actions;
  exp/seq pre-finish hooks run; `finish_yml` is posted when a SYNC server is
  configured and not otherwise; read-back finds the new locations.
- `run_tests.py` over the sync, finalizer, orchestrator-lifecycle and runner
  suites, and every deployment's tests.

### 8.1 Station gate

Before merge, one full sequence on a UV-Vis station running auto-analysis:
identical S3 objects to a pre-change run of the same sequence, `.prg` carries
`hooks` and `synced`, and the analysis dispatches. CSV export confirmed on a
spectroscopy station using `hlo_postprocess_libs` if one is available.

## 9. Migration

No config edits are required: the aliases cover every live use, and an absent
`postfinish_hooks` reproduces today's chain. New configs should use the new
keys; `helao/core/drivers/data/CLAUDE.md` gets a short pointer to this spec.

## 10. Out of scope

- An endpoint to re-run a failed non-blocking hook (clear the `.prg` entry).
- Pre-finish timeouts.
- Any alternative-storage or external-API hook implementation; the contract
  allows them, none is built.
- Retiring the operator-triggered `*_postseq` analysis sequences.
- Quarantine for records that keep failing a blocking hook (deferred with
  the `RUNS_FAILED` / strike-count idea).
- `ports/sync.py` beyond correcting its stale docstring (it still describes
  move-to-SYNCED and zipping).
