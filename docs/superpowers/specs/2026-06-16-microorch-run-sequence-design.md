# MicroOrch: run_sequence, yml persistence, loader wrapper, run tracking & zipping

Date: 2026-06-16
Status: Approved design, ready for implementation planning
File under change: `helao/core/runners/micro_orch.py` (primary), `helao/core/drivers/data/loaders/localfs.py` (loader zip support)

## Background

`MicroOrch` (`helao/core/runners/micro_orch.py`) is a lightweight, in-process
substitute for the full orchestrator service (`Orch` in
`helao/core/servers/orch.py`). It dispatches actions to action servers over
RPC without standing up a FastAPI server, sequence/experiment queues, or an
operator UI. It is meant to be driven directly from a self-contained Python
script so that the *result* of one action/experiment/sequence can be used as
the *argument* to the next without round-tripping through
`Orch.global_params`.

Today `MicroOrch` has `run_action` and `run_experiment`. It is missing:

1. A `run_sequence` method.
2. Persistence of finished `Experiment` / `Sequence` models to yml (Orch does
   this via `Base.write_exp` / `Base.write_seq`).
3. A convenient way to read back finished artifact data from within the
   driving script.
4. Tracking of what it has run, and a way to archive those artifacts.

## Goals

- Add `run_sequence`, mirroring `Orch`'s sequence-expansion semantics.
- Persist finished `Experiment` and `Sequence` models to yml with full
  fidelity to Orch's output (aggregated `samples_in`/`samples_out`/`files`).
- Wrap the output of `run_action` / `run_experiment` / `run_sequence` so the
  caller receives a loader-backed object for reading finished data, after the
  artifacts have landed in their finished location on disk.
- Track every `run_*` call so all produced artifacts can be zipped, preserving
  the directory structure relative to `RUNS_FINISHED`.
- Update `LocalLoader` to read zips produced by `MicroOrch`.

## Non-goals

- No S3 upload, metadata-DB registration, or `RUNS_SYNCED` promotion. The
  syncer (`HelaoSyncer`) is out of scope. `MicroOrch` writes directly to
  `RUNS_FINISHED`.
- No operator UI, no sequence/experiment queues.
- No change to action-server behavior. Action servers continue to write and
  promote their own `*-act.yml` + data files to `RUNS_FINISHED` (or
  `RUNS_DIAG` for manual actions).

## Key facts established during design

- `MicroOrch` does **not** inherit `Base`, so it has no `helaodirs`,
  `save_root`, `write_exp`/`write_seq`, or `_write_meta_atomic`. These must be
  reproduced locally.
- Premodel inheritance is `Action ⊂ Experiment ⊂ Sequence` (see
  `helao/helpers/premodels.py`). "Propagating identity from parent to child"
  therefore means copying the parent's fields onto the child object.
- `Sequence.init_seq` / `Experiment.init_exp` / `Action.init_act` lazily stamp
  timestamp, uuid, status, and output-dir. `init_act` auto-promotes an action
  to a *manual* run (synthetic seq/exp names, `manual_action=True`,
  `access="manual"`) when it has no parent seq/exp timestamps. Manual
  artifacts are written under `RUNS_DIAG` (see `Base.write_act`/`write_exp`).
- Output-dir layout:
  - sequence: `YY.WW/MMDD/HHMMSS__name__label[-plate-serial[-sampleno]]`
    (`Sequence.get_sequence_dir`)
  - experiment: `<sequence_dir>/YYMMDD.HHMMSS__experiment_name`
    (`Experiment.get_experiment_dir`)
  - action: `<experiment_dir>/{orch_submit_order}__{action_split}__{server}__{name}`
    (`Action.get_action_dir`)
- Orch builds a full-fidelity `ExperimentModel` by appending each finished
  action as `Action(**result_actiondict)` to `experiment.dispatched_actions`
  (`orch.py:1304-1305`); `Experiment.get_exp()` then folds those into
  aggregated samples/files. The dispatch reply dict from a `MicroOrch` action
  (the dict returned by `dispatch_action` / cached in `_latest`) is the same
  `as_dict()` shape, so `Action(**dump)` round-trips.
- Orch builds a full-fidelity `SequenceModel` by appending each finished
  experiment as `experiment.get_exp()` to `sequence.dispatched_experiments`;
  `Sequence.get_seq()` then populates `dispatched_experiments_abbr`.
- Sequence-library functions return `List[ShortExperimentModel]` (via
  `ExperimentPlanMaker`); each plan carries only `experiment_name`,
  `experiment_params`, and `from_global_exp_params` — **not** a callable. The
  orchestrator resolves the name against `experiment_lib`. `MicroOrch` needs
  the same name→callable mapping.
- yml write helpers: `yml_dumps` (`helao/helpers/yml_tools.py`). yml header
  dict is `{"file_type": "experiment"|"sequence"|"action"}` merged with the
  model's `clean_dict()`.
- `LocalLoader(data_path)` indexes a `RUNS_*` tree (auto-scanning sibling
  active/finished/synced/diag trees and the matching `PROCESSES` tree) or a
  `.zip`, exposing `get_act/get_exp/get_seq(index=..|path=..)` →
  `HelaoAction/HelaoExperiment/HelaoSequence`. The existing `.zip` support
  (produced by `file_utils.zip_dir` from the syncer) is **single-sequence**,
  rooted at the sequence dir, with the zip filename equal to the sequence dir
  name and `*-seq.yml` at the archive root.

## Assumptions

- All action servers run on the same host as `MicroOrch` **and share the same
  `root`** path (`world_cfg["root"]`). Finished action artifacts are therefore
  readable on the local filesystem under `root/RUNS_FINISHED/...` (or
  `root/RUNS_DIAG/...` for manual actions).

---

## Design

### Component 1 — On-disk identity propagation

So that the seq → exp → act directory nesting on disk matches Orch, identity
flows downward from sequence to experiment to action.

- **New** `_stage_experiment(exp: Experiment, order: int, sequence: Optional[Sequence])`:
  - If `sequence` is provided, copy its sequence identity onto `exp`
    (`sequence_uuid`, `sequence_timestamp`, `sequence_name`,
    `sequence_label`, `sequence_output_dir`, `sequence_params`,
    `manual_action`, etc.).
  - Else (standalone `run_experiment`): if `exp.sequence_timestamp is None`,
    synthesize a manual sequence on `exp` itself —
    `exp.sequence_name = f"seq--{exp.experiment_name}"`,
    `exp.sequence_label = "manual"`, `exp.manual_action = True`,
    `exp.access = "manual"`, then `exp.init_seq(time_offset=...)`.
  - Then `exp.init_exp(time_offset=...)` to stamp experiment uuid/timestamp/
    status and `experiment_output_dir`.
  - Set `exp.orch_*` identity as `_stage_action` does for actions.
- **Extend** `_stage_action(act, order)`: when an owning experiment exists,
  copy the experiment's seq + exp identity onto the action before
  `init_act` runs (`sequence_*`, `experiment_*`, `manual_action`, `access`),
  so the action nests under `experiment_output_dir` rather than promoting to
  its own manual seq/exp tree. The existing uuid/order/orch/server-address
  assignment is retained.

`run_experiment` and `run_sequence` pass the owning experiment context into
`_stage_action` (e.g. via a parameter or by staging the experiment first and
reading its fields).

### Component 2 — Full-parity experiment yml in `run_experiment`

- After each dispatched action reaches a terminal dump, build
  `Action(**terminal_dump)` and append it to
  `experiment.dispatched_actions` (mirrors `orch.py:1304-1305`).
- When `await_completion` is true and all actions are terminal:
  - Set `experiment.experiment_status = [HloStatus.finished]` and the finished
    timestamp.
  - Write the experiment yml (Component 3).
- `Experiment.get_exp()` folds `dispatched_actions` into aggregated
  `samples_in`/`samples_out`/`files` automatically.

### Component 3 — yml writers (direct to RUNS_FINISHED)

New private helpers on `MicroOrch` (no `Base` to inherit from):

- `_finished_root() -> str`: `os.path.join(world_cfg["root"], "RUNS_FINISHED")`.
  Raise a clear error if `world_cfg` has no `root`. A `manual_action` object's
  root is rewritten to `RUNS_DIAG` to match `Base` behavior.
- `_write_meta_atomic(output_file: str, output_str: str)`: ported from
  `Base._write_meta_atomic` (`base.py:880-904`) — write to a uniquely named
  temp file in the same directory via `aiofiles`, then `os.replace` for an
  atomic swap.
- `_write_exp(exp: Experiment)`: replicate `Base.write_exp` rooted at the
  finished root — `{"file_type": "experiment"}` + `exp.get_exp().clean_dict()`,
  serialized with `yml_dumps`, written to
  `<root>/<exp.get_experiment_dir()>/<ts>-exp.yml`.
- `_write_seq(seq: Sequence)`: replicate `Base.write_seq` rooted at the
  finished root — `{"file_type": "sequence"}` + `seq.get_seq().clean_dict()`,
  written to `<root>/<seq.get_sequence_dir()>/<ts>-seq.yml`.

Timestamp format matches Base: `strftime("%y%m%d.%H%M%S%f")`.

### Component 4 — `run_sequence`

```python
async def run_sequence(
    self,
    seq_func: Callable[..., List[ShortExperimentModel]],
    experiment_lib: Dict[str, Callable[..., Union[List[Action], Experiment]]],
    sequence: Optional[Sequence] = None,
    await_completion: bool = True,
    dispatch_timeout: float = 60.0,
    wait_timeout: Optional[float] = None,
    **seq_params: Any,
) -> Union["HelaoSequence", List[List[dict]]]:
```

- `seq_func`: a sequence-library callable returning `List[ShortExperimentModel]`
  (via `ExperimentPlanMaker`).
- `experiment_lib`: `{experiment_name: callable}` mapping used to resolve each
  planned experiment's `experiment_name` to its experiment function (mirrors
  `Orch.experiment_lib`).
- `sequence`: optional pre-built `Sequence`; a blank `Sequence()` is used if
  `None`. `init_seq` stamps uuid/timestamp/status/output-dir.
- Filter `seq_params` to `seq_func`'s signature (mirrors `run_experiment`'s
  `inspect.getfullargspec` filtering).
- For each planned experiment:
  1. Resolve `exp_func = experiment_lib[plan.experiment_name]`; raise a clear
     error on a missing key.
  2. Build an `Experiment` carrying the sequence identity plus
     `experiment_name` and `experiment_params` from the plan.
  3. Apply `plan.from_global_exp_params` (copy `self.global_params[k]` into
     `experiment.experiment_params[v]`; supports `v` as list or scalar) —
     mirrors Orch's experiment-level global mapping and the param hand-off the
     `TEST_consecutive_noblocking` sequence relies on.
  4. `await self.run_experiment(exp_func, experiment=exp, ...)`.
  5. Append `exp.get_exp()` to `sequence.dispatched_experiments`.
- On completion: set `sequence.sequence_status = [HloStatus.finished]` and the
  finished timestamp, then `_write_seq(sequence)`.
- Returns the loader-wrapped sequence (Component 5) when `await_completion`,
  else the list of per-experiment raw dump lists.

### Component 5 — Loader wrapper (pluggable, always-on)

- `__init__` gains:
  - `loader_factory: Callable[[str], Any] = LocalLoader` — default reads the
    local filesystem; a `HelaoLoader` adapter may be injected for S3/SQL.
  - `finished_timeout: float = 60.0`, `poll_interval: float = 0.5`.
- `_await_finished(rel_dir: str, suffix: str) -> str`: poll for
  `<root>/RUNS_FINISHED/<rel_dir>/*-<suffix>.yml`, **and** the `RUNS_DIAG`
  equivalent (manual actions/experiments land there), until one appears or
  `finished_timeout` elapses; return the matched yml path. Raise
  `TimeoutError` on expiry.
- `_load_finished(rel_dir, suffix)`: call `_await_finished`, then
  `loader_factory(yml_path).get_<act|exp|seq>(path=yml_path)`.
- Return types (per approved decision — **always wrap**):
  - `run_action` → `HelaoAction`
  - `run_experiment` → `HelaoExperiment`
  - `run_sequence` → `HelaoSequence`
  - Exception: when `await_completion=False`, there is no finished artifact to
    load, so the raw dump(s) are returned (existing shapes:
    `dict` / `List[dict]` / `List[List[dict]]`).

`run_action` standalone produces a manual action under `RUNS_DIAG`;
`_await_finished` checks both `RUNS_FINISHED` and `RUNS_DIAG`.

### Component 6 — Run tracking

`MicroOrch` accumulates a record per completed `run_*` call:

```python
RunRecord = {
    "type": "action" | "experiment" | "sequence",
    "uuid": UUID,
    "name": str,
    "state": "RUNS_FINISHED" | "RUNS_DIAG",   # DIAG for manual artifacts
    "rel_dir": str,    # output dir relative to the state root
    "yml_path": str,   # absolute path to the finished yml
}
```

- `self.runs: List[RunRecord] = []`, appended inside each `run_*` immediately
  after `_await_finished` confirms the artifact's location (so `rel_dir`,
  `state`, and `yml_path` are known).
- Records overlap hierarchically (a sequence dir contains its experiment and
  action dirs); the zipper dedups, so overlap is harmless.

### Component 7 — `zip_runs`

```python
def zip_runs(self, zip_path: str, include_diag: bool = True) -> str:
```

- For each tracked `RunRecord`, resolve its on-disk dir
  `os.path.join(root, state, rel_dir)` and collect every contained file
  (recursive).
- **Arcname = each file's path relative to its state root** (`RUNS_FINISHED`
  or `RUNS_DIAG`). Both states map onto the same relative seq/exp/act tree, so
  the archive reproduces the on-disk structure minus the `RUNS_*` prefix —
  i.e. structure relative to `RUNS_FINISHED`.
- **Dedup by arcname** — write each file once across overlapping records.
- Skip `.lock` files (matches `file_utils.zip_dir`).
- `include_diag=False` excludes `RUNS_DIAG` records.
- Returns `zip_path`.

### Component 8 — LocalLoader zip support for MicroOrch archives

The existing `LocalLoader` `.zip` path assumes a single-sequence archive whose
filename equals the sequence dir and whose `*-seq.yml` sits at the archive
root (`parse_seq_path` forces `yml_dir = basename(target)` for any `.zip`).
A `MicroOrch` zip is rooted at `RUNS_FINISHED` and may contain multiple
seq/exp/act trees, with `*-seq.yml` nested under `YY.WW/MMDD/<seq_dir>/`.

- **Fix `parse_seq_path`**: derive `yml_dir` from the entry's own in-zip
  dirname (`os.path.basename(os.path.dirname(ymlp))`) when non-empty; fall
  back to the zip basename only when the seq yml is at the archive root (the
  legacy single-sequence case). This handles both archive layouts.
- `parse_exp_path` / `parse_act_path` already use `dirname(ymlp)` and work on
  in-zip relative paths unchanged.
- `get_yml` / `get_hlo` zip branches index by the in-zip relative path and are
  unchanged.
- `get_bytes` zip branch currently assumes a single sequence
  (`self.sequences.iloc[0].sequence_dir`); refine it to match the requested
  file's own sequence dir so parquet/byte reads work in a multi-sequence
  archive. (Lower-risk refinement.)

---

## Risks / edge cases

- **Shared-root assumption**: if action servers use a different `root`, their
  finished action artifacts won't be found under `MicroOrch`'s root and
  `_await_finished` will time out. Documented assumption; surfaced as a clear
  `TimeoutError`.
- **Manual vs finished location**: standalone actions/experiments land in
  `RUNS_DIAG`; `_await_finished` and `zip_runs` both account for this.
- **`await_completion=False`** breaks the "always wrap" contract because no
  finished artifact exists yet; in that case raw dumps are returned and no
  `RunRecord` is added (nothing finished to track/zip).
- **Round-trip**: a `zip_runs` archive must load back through
  `LocalLoader(zip_path)` — covered by Component 8; should be exercised in a
  test under `helao/core/tests/`.

## Testing

No pytest harness exists; tests are standalone scripts under
`helao/core/tests/`. Suggested coverage (using the `test` deployment's
simulated action servers):

- `run_action` → returns `HelaoAction`, yml present in finished/diag tree.
- `run_experiment` → returns `HelaoExperiment`, exp.yml has aggregated
  samples/files matching dispatched actions.
- `run_sequence` (e.g. `TEST_consecutive_noblocking` + a `TEST_sub_*`
  experiment_lib) → returns `HelaoSequence`, seq.yml lists
  `dispatched_experiments_abbr`, global param hand-off works.
- `zip_runs` then `LocalLoader(zip)` round-trip: `get_seq/get_exp/get_act` and
  `get_hlo` all resolve.
