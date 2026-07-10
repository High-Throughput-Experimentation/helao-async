# CARDS Refactor — P3: Domain Integrity + Alignment

> Derived from `CARDS_AUDIT.md` Part 1 (Domain Integrity findings) and Part 3 ("Domain Integrity is the
> biggest whole-system re-rating; the untyped param contract is the root cause"), and the
> `CARDS_REFACTOR_PLAN.md` §4 P3 sketch. Branch: `feat/cards-refactor` on parent + nested lila/mea/priv
> (`lila_gl` excluded). Increments 1 (RunDir enum) and 2 (duplication kill) are committed and pushed.
>
> **Risk class: MEDIUM** — touches core models + config. **Hard constraint:** all serialized shapes
> (-act/-exp/-seq/-prc.yml, HLO headers, status-dict payloads, wire JSON, YAML config shape) stay
> byte-identical, proven by capture/compare, **except** the lila `stop_ce_pump` fix, which is an explicit
> behavior fix. All validation on the `test` deployment sims on Linux; zero live-hardware behavior change
> on hte. Test gate: `conda run -n helao python run_unit_tests.py`. Python via `conda run -n helao`.

---

## 1. Decision: split P3 into sub-increments; 3a = guarded lifecycle

P3 as sketched bundles four core-sensitive changes (lifecycle, config injection, sample Union,
typed params). Each has a different blast radius and a different proof obligation; landing them in one
increment makes the capture/compare diff un-attributable and the rollback all-or-nothing. **P3 is split
into five sub-increments, ordered by leverage × safety. Only 3a is fully detailed here; 3b–3e are
sketched and get their own detail passes after 3a lands.**

| Sub | Name | CARDS card(s) | Audit evidence | Risk | Why this position |
|-----|------|---------------|----------------|------|-------------------|
| **3a** | **Guarded lifecycle transitions** (+ bundled lila `stop_ce_pump` fix) | **Domain Integrity** (Part 1 §Domain: "lifecycle = unguarded `List[HloStatus]`… transitions via scattered `.append()`"; Part 3 fix #2) | action.py:126, experiment.py:112, sequence.py:101; call-site inventory §2.3 | **Low-medium** — additive methods only; field stays `List[HloStatus]`; provably zero serialized-shape change | Highest Domain-Integrity leverage per unit risk. Pure centralization: adds transition methods and routes every existing mutation through them. The serialized field shape is untouched by construction (methods never appear in pydantic dumps/schema). Creates the single chokepoint 3e's enforcement and P5's Orch split will consume. |
| 3b | Typed config injection | **Alignment** + Domain Integrity (Part 1: `HelaoConfig`/`ServerConfig` "exist but under-used" config_loader.py:150-192; `world_cfg["servers"][key]["host"]` base.py:148; `set_global` flag config_loader.py:129; global `CONFIG` Munch) | Same | Medium — `Base.__init__` is imported by every server | Isolated from the models, so it can't contaminate 3a's capture/compare. Needs 3a's end-to-end harness already proven. |
| 3c | Discriminated sample `Union` | Domain Integrity (Part 1: "Sample `Union` (action.py:142) not discriminated; untyped `SampleModel` fallback catches anything") | Same | Medium — changes *validation* routing for ambiguous payloads even when output shape is identical | Validation-behavior sensitive: a discriminator can reject payloads the `SampleModel` fallback silently accepted. Needs a corpus replay (validate historical -act.yml sample blocks) before flipping — that corpus tooling is built on 3a/3b's harness. |
| 3d | Typed `action_params` — `test` deployment first | Domain Integrity (Part 3: "untyped param contract *forces* stringly-typed deployment code"; test `check_condition:485` string-keyed dispatch) | Same | Medium — touches experiment-authoring layer; pattern must be right before hte copies it | Last because it is the pattern-setter for every deployment: get the sim proving ground right, then Part-3's "deployments heal by following the corrected pattern" does the rest. Fixes gpsim `check_condition` string dispatch as the pilot. Sims stay bare helpers — no ABC-ification (P4 boundary). |
| 3e | Flip lifecycle guards from log-only to enforcing | Domain Integrity | 3a telemetry | Low (after soak) | 3a ships observability-only guards; 3e turns on enforcement once test + hte logs show zero violations over a soak window. Deliberately deferred so 3a stays byte-identical. |

**Why 3a and not config injection first:** config injection (3b) changes `Base.__init__`, the constructor
of every FastAPI server in the fleet — its blast radius is horizontal (every process) while its
Domain-Integrity payoff is indirect. The lifecycle wrapper's blast radius is exactly the 25 mutation
sites inventoried below, its payoff is the audit's #2 core fix, and its no-op proof is mechanical.
The `stop_ce_pump` fix rides along in 3a because it is self-contained, nested-repo-isolated (lila only),
and already evidence-cleared (§2.6).

---

## 2. SUB-INCREMENT 3a — full detail

### 2.1 Scope statement (decisive, single option)

Add guarded lifecycle-transition methods to the three status-bearing core models and route **every**
in-repo mutation of `action_status` / `experiment_status` / `sequence_status` through them. Guards are
**log-only in 3a** (WARNING on duplicate-append and on `active`+`finished` coexistence — the audit's
canonical contradictory state); the mutation performed is byte-for-byte what the old inline code did.
Enforcement (raising) is 3e, after soak. The serialized field shape stays `List[HloStatus]` on the wire,
in -act/-exp/-seq.yml, and in HLO output — methods on a pydantic model do not appear in `model_dump()`,
`model_json_schema()`, or YAML emission.

Bundled second task: fix lila `SDC_seq.py` `stop_ce_pump: bool = "True"` → `= True` at **both** sites
(lines 2252 **and** 2521 — the audit lists one; grep found two). This is the increment's only
behavior-visible change (serialized param value `'True'` → `true`), pre-cleared by the consumer sweep
in §2.6.

**Explicit non-goals / exclusions (do not touch):**
- **Sample status lifecycle** (`SampleModel.status: List[SampleStatus]`) — different field, different
  enum. Its mutation sites (core/models/sample.py:196,206; hte archive_driver.py ×10; hte
  pal_driver.py:1660,1662) are out of scope; logged as an open question for 3c (sample work) / P4
  (those drivers get rewritten anyway).
- **priv converter constructor kwargs** (`action_status=[HloStatus.finished]` etc., 18 sites across
  `helao/deploy/priv/scripts/*/converters.py`, `convert_icpms_csv.py`) — these are model *construction*,
  not lifecycle *transition*; constructing a model in a terminal state is legitimate and unchanged.
- **Local variables named `*_status`** that are not model fields: `ret_status.append(...)` in
  galil_motion_driver.py:926-944 and lila thorlabs_kinesis.py:1288-1294 (plain lists of strings).
- **Mock-class field initialization in tests**: unit_test_estop_sync.py:39 (`self.action_status = [...]`
  inside a fake), hte sprintir_tests.py:115,142,171,192 (`mock_action.action_status = []`).
- No dedup, no reordering, no removal of existing `if X not in` guards at call sites — every routed site
  performs the identical list operation it performed before.
- No enum changes, no model field changes, no `Optional`-tightening (all-`Optional` models are a
  separate audit finding, not 3a).
- dbpack (frozen), `deploy/lila_gl/**`, `deploy/mea/notes/**` — excluded as in P1/P2.
- mea has **zero** in-scope status-mutation sites (verified by grep 2026-07-10) — no mea commit in 3a.

### 2.2 The transformation

**New module `helao/core/models/status_transitions.py`** (task T1). Free functions carry the semantics;
model methods are thin named delegates. Free functions exist because two call sites (`Base.replace_status`
and orch's `_mark_estopped` closure) operate on a bare `status_list` reference, not on the model:

```python
"""Guarded lifecycle transitions for HELAO status lists.

3a policy: guards LOG ONLY (never raise, never alter the mutation) so serialized
output is byte-identical to the historical inline list ops. Enforcement is a
later increment (3e) gated on soak telemetry from these warnings.
"""

__all__ = ["guarded_append", "guarded_replace", "guarded_reset"]

import logging
from typing import List, Sequence

from helao.core.models.hlostatus import HloStatus

_LOGGER = logging.getLogger(__name__)  # stdlib on purpose: core/models stays infra-import-free


def _warn_contradiction(status_list: List[HloStatus], owner: str) -> None:
    if HloStatus.active in status_list and HloStatus.finished in status_list:
        _LOGGER.warning("contradictory lifecycle state (active+finished) on %s: %s", owner, status_list)


def guarded_append(status_list: List[HloStatus], new_status: HloStatus, *, owner: str = "?") -> None:
    """Append exactly as legacy inline `.append()` did; warn on duplicate/contradiction."""
    if new_status in status_list:
        _LOGGER.warning("duplicate status append %s on %s: %s", new_status, owner, status_list)
    status_list.append(new_status)          # unconditional — byte-identical to legacy
    _warn_contradiction(status_list, owner)


def guarded_replace(status_list: List[HloStatus], old_status: HloStatus,
                    new_status: HloStatus, *, owner: str = "?") -> None:
    """Exact semantics of Base.replace_status (base.py:997): swap in place, else append."""
    if old_status in status_list:
        status_list[status_list.index(old_status)] = new_status
    else:
        status_list.append(new_status)
    _warn_contradiction(status_list, owner)


def guarded_reset(status_list: List[HloStatus], new_statuses: Sequence[HloStatus], *, owner: str = "?") -> None:
    """Wholesale re-init, in place (equivalent to legacy `x.field = [s]` for all consumers)."""
    status_list[:] = list(new_statuses)
```

**Model methods** (task T1) — three named methods per model, defined directly on each class so the
`Action(Experiment, ActionModel)` diamond (premodels.py:305) composes them all onto `Action` without
any field-name-guessing mixin:

- `ActionModel` (core/models/action.py): `append_action_status(s)`, `replace_action_status(old, new)`,
  `reset_action_status(*statuses)` — each delegates to the free function with
  `owner=f"action {self.action_uuid}/{self.action_name}"`.
- `ExperimentModel` (core/models/experiment.py): `append_experiment_status` / `replace_experiment_status`
  / `reset_experiment_status`.
- `SequenceModel` (core/models/sequence.py): `append_sequence_status` / `replace_sequence_status`
  / `reset_sequence_status`.

`Base.replace_status` (base.py:997) is **kept** as a delegating shim over `guarded_replace` (docstring
gains a "prefer the model methods" note). It has zero deployment callers (verified: only base.py:2072,
orch.py:1645/2228/2317), but private deployments outside this workspace may call it — the shim keeps the
signature stable.

**Preserved oddity (do not "fix"):** `Active.set_error` (base.py:1441) appends `HloStatus.errored` to
`action.experiment_status` — not `action_status`. This is live behavior (Action has the field via the
premodels diamond) and error status *is* consumed downstream via `action.error_code`, so silently
retargeting the append would change -act.yml/status payload bytes. 3a routes it **verbatim** as
`action.append_experiment_status(HloStatus.errored)` with a `# NOTE: appends to experiment_status —
historical behavior, see open-questions` comment. Filed as an open question (§4).

### 2.3 Mutation call-site inventory and routing (verified by grep, 2026-07-10)

Parent repo — core:

| File:line | Current code | Routed to |
|---|---|---|
| helpers/premodels.py:114 | `self.sequence_status = [HloStatus.active]` (init_seq, inside `if force or not …` guard — keep guard) | `self.reset_sequence_status(HloStatus.active)` |
| helpers/premodels.py:184 | `self.experiment_status = [HloStatus.active]` (init_exp) | `self.reset_experiment_status(HloStatus.active)` |
| helpers/premodels.py:368 | `self.action_status = [HloStatus.active]` (init_act) | `self.reset_action_status(HloStatus.active)` |
| core/servers/base.py:997 | `def replace_status(...)` body | delegate to `guarded_replace` (shim kept) |
| core/servers/base.py:1280 | `exp.experiment_status = [HloStatus.active]` | `exp.reset_experiment_status(HloStatus.active)` |
| core/servers/base.py:1281 | `exp.sequence_status = [HloStatus.active]` | `exp.reset_sequence_status(HloStatus.active)` |
| core/servers/base.py:1430 | `action.action_status.append(HloStatus.estopped)` (set_estop) | `action.append_action_status(HloStatus.estopped)` |
| core/servers/base.py:1441 | `action.experiment_status.append(HloStatus.errored)` (set_error — **oddity, preserve target field**) | `action.append_experiment_status(HloStatus.errored)` + NOTE comment |
| core/servers/base.py:1933 | `self.action.action_status.append(HloStatus.split)` | `self.action.append_action_status(HloStatus.split)` |
| core/servers/base.py:2072-2076 | `self.base.replace_status(status_list=action.action_status, active→finished)` | `action.replace_action_status(HloStatus.active, HloStatus.finished)` |
| core/servers/base.py:2081 | `action.action_status.append(HloStatus.errored)` (inside existing `if errored not in` — keep the outer guard) | `action.append_action_status(HloStatus.errored)` |
| core/servers/base.py:2334 | `exp.experiment_status = [HloStatus.finished]` | `exp.reset_experiment_status(HloStatus.finished)` |
| core/servers/base.py:2335 | `exp.sequence_status = [HloStatus.finished]` | `exp.reset_sequence_status(HloStatus.finished)` |
| core/servers/orch.py:1644-1651 | `_mark_estopped(status_list)` closure: `self.replace_status(...)` + guarded `.append(estopped)` | closure body → `guarded_replace(status_list, active, finished, owner=…)` + keep `if estopped not in` + `guarded_append(status_list, estopped, owner=…)` (bare-list context — free functions) |
| core/servers/orch.py:2228-2232 | `self.replace_status(status_list=self.active_sequence.sequence_status, active→finished)` | `self.active_sequence.replace_sequence_status(HloStatus.active, HloStatus.finished)` |
| core/servers/orch.py:2317-2321 | same for `active_experiment.experiment_status` | `self.active_experiment.replace_experiment_status(HloStatus.active, HloStatus.finished)` |
| core/runners/micro_orch.py:548 | `experiment.experiment_status = [HloStatus.finished]` | `experiment.reset_experiment_status(HloStatus.finished)` |
| core/runners/micro_orch.py:632 | same | same |
| core/runners/micro_orch.py:683 | same | same |
| core/runners/micro_orch.py:776 | `sequence.sequence_status = [HloStatus.finished]` | `sequence.reset_sequence_status(HloStatus.finished)` |
| core/tests/unit_test_estop_sync.py:48 | `action.action_status.append(HloStatus.estopped)` | `action.append_action_status(HloStatus.estopped)` |
| core/tests/unit_test_orch_status.py:83 | `act_active.action_status.append(HloStatus.finished)` | `act_active.append_action_status(HloStatus.finished)` (deliberate-contradiction test may now log a WARNING — harmless, assert nothing about logs) |
| core/tests/unit_test_orch_status.py:169 | `new_act.action_status.append(HloStatus.finished)` | `new_act.append_action_status(HloStatus.finished)` |

Parent repo — hte deployment (py_compile-gated; Windows-only imports possible):

| File:line | Current code | Routed to |
|---|---|---|
| deploy/hte/servers/action/pdu_server.py:66 | `active.action.action_status.append(HloStatus.errored)` | `active.action.append_action_status(HloStatus.errored)` |
| deploy/hte/servers/action/pdu_server.py:91 | same | same |
| deploy/hte/drivers/spec/spectral_products_driver.py:152 | `self.active.action.action_status.append(HloStatus.estopped)` | `self.active.action.append_action_status(HloStatus.estopped)` |
| deploy/hte/drivers/sensor/sprintir_driver.py:205 | same | same |

These four hte sites are estop/error paths only — no nominal-run control-flow change, and the routed call
performs the identical append. No hte launch is required or performed.

Nested repos: **lila** — zero status-mutation sites (only the `stop_ce_pump` task, §2.6). **mea** — zero
sites. **priv** — constructor kwargs only (excluded, §2.1). So 3a commits land in parent + lila only.

### 2.4 Proof that the serialized shape is unchanged (three layers)

1. **Model-layer byte proof** (new standalone test, T1:
   `helao/core/tests/unit_test_status_transitions.py`):
   - For each primitive: build two identical model instances, apply the legacy inline op to one and the
     guarded method to the other, assert `yml_dumps(a.model_dump()) == yml_dumps(b.model_dump())` and
     `a.model_dump_json() == b.model_dump_json()`. Parametrize across all `HloStatus` members and across
     start states `[]`, `[active]`, `[active, errored]`, duplicate-append, replace-when-missing
     (append fallback path of `guarded_replace`).
   - Schema freeze: `ActionModel.model_json_schema()` / `ExperimentModel…` / `SequenceModel…` captured
     before T1 (in T0) and asserted equal after — proves methods add nothing to the schema and the field
     is still `array of HloStatus`.
2. **Suite gate:** `conda run -n helao python run_unit_tests.py` exits 0, plus every core standalone test
   touched (unit_test_estop_sync, unit_test_orch_status, unit_test_micro_orch, unit_test_sync_*) re-run
   and passing.
3. **Whole-system capture/compare** (T0 baseline, T8 comparison): launch the `test` deployment on Linux,
   run a sim sequence end-to-end, and diff the normalized RUNS trees pre- vs post-change (§2.5).

### 2.5 Behavior-equivalence harness (exact commands)

Artifacts live in `.omc/artifacts/p3a/` (operational, not committed to `helao/`):

- `demo0_linux.yml` — copy of `helao/deploy/test/configs/demo0.yml` with: `root: /tmp/hlo_p3a`
  (baseline run) / re-pointed to `/tmp/hlo_p3a_post` for the comparison run; `launch_browser: false`
  everywhere; OPERATOR + ACTVIS + GPVIS server entries removed (only ORCH, CPSIM, GPSIM needed —
  fewer processes, no browser). `read_config` accepts a full path, so this file does not need to live
  under `helao/deploy/*/configs/`. GPSIM `random_seed: 9999` and CPSIM `plate_id: 2750` kept for
  determinism.
- `enqueue_oersim.py` — builds the `OERSIM_activelearn` sequence exactly the way the operator does
  (mirror `helao/core/servers/operator/helao_operator.py:136` / `operator/orch_backend.py:243`:
  construct `premodels.Sequence` for `OERSIM_activelearn` with library-default params), then
  `POST http://127.0.0.1:8001/append_sequence` (endpoint: `core/servers/orch_api.py:406`), then
  `POST /start`; polls the orch until `sequence_status` contains `finished`. The sequence's
  `check_condition` stop rule (`max_iters`) guarantees termination.
- `normalize_runs_tree.py` — walks a RUNS tree and emits a normalized snapshot: (a) file *contents* with
  UUIDs (hex-8-4-4-4-12), ISO-8601 timestamps, `epoch_ns`/epoch floats, and ntp-offset values replaced by
  fixed placeholders in order of first appearance (so cross-references still match positionally);
  (b) file/dir *names* with date/time segments placeholder-replaced the same way; (c) a sorted manifest of
  relative paths. `*_codehash` fields are **not** normalized — 3a never edits the test deployment's
  experiment/sequence/server-endpoint source, so codehashes must match exactly (free integrity check).

```bash
# T0 — BASELINE (run BEFORE any 3a code change, on current feat/cards-refactor HEAD)
conda run -n helao python run_unit_tests.py
conda run -n helao python launch.py /mnt/STORAGE/repos/helao/helao-async/.omc/artifacts/p3a/demo0_linux.yml nolive   # background
conda run -n helao python .omc/artifacts/p3a/enqueue_oersim.py            # waits for finished
# CTRL-x the group (or POST /shutdown per server), then:
conda run -n helao python .omc/artifacts/p3a/normalize_runs_tree.py /tmp/hlo_p3a  > .omc/artifacts/p3a/baseline.norm
conda run -n helao python -c "import json; from helao.core.models.action import ActionModel; from helao.core.models.experiment import ExperimentModel; from helao.core.models.sequence import SequenceModel; open('.omc/artifacts/p3a/schema_baseline.json','w').write(json.dumps([ActionModel.model_json_schema(), ExperimentModel.model_json_schema(), SequenceModel.model_json_schema()], indent=1, sort_keys=True, default=str))"

# T8 — COMPARE (after all routing tasks, same machine)
conda run -n helao python run_unit_tests.py
# repeat the identical launch/enqueue/shutdown with root=/tmp/hlo_p3a_post
conda run -n helao python .omc/artifacts/p3a/normalize_runs_tree.py /tmp/hlo_p3a_post > .omc/artifacts/p3a/post.norm
diff .omc/artifacts/p3a/baseline.norm .omc/artifacts/p3a/post.norm        # MUST be empty
# schema re-dump with the same command and diff vs schema_baseline.json    # MUST be empty
```

If the sim's data files prove nondeterministic despite the fixed seed (e.g. wall-clock-dependent sample
counts in a polled hlo), the fallback rule is: manifest + all yml files must diff clean; hlo **headers**
must diff clean; hlo data-row-count deltas are investigated individually and accepted only with a written
cause (timing) in the T8 report. Do not weaken the yml criterion under any circumstances.

### 2.6 Bundled task: lila `stop_ce_pump: bool = "True"` fix

Evidence collected 2026-07-10:
- **Two** defect sites, not one: `helao/deploy/lila/sequences/SDC_seq.py:2252` and `:2521`
  (`stop_ce_pump: bool = "True"`). Both functions' docstrings even note "the default is the string
  `"True"`" (SDC_seq.py:2299, 2570) — update those two docstring lines too.
- The param flows only as `"stop_ce_pump": stop_ce_pump` into experiment params (SDC_seq.py:2376, 2425,
  2479, …) and is consumed exclusively by truthiness in the experiment layer: `if stop_ce_pump:` at
  SDC_exp.py:440, 1184, 1299. `grep -rn '== *"True"'` over lila returns only the two docstrings — **no
  consumer string-matches "True"**, closing the open-questions carry-over.
- Runtime behavior is therefore identical (`"True"` and `True` are both truthy). The *serialized* param
  value in -seq/-exp yml changes from `'True'` to `true` — this is the intended, declared behavior fix
  and the only serialized delta 3a is allowed to produce. It also fixes the operator-UI rendering of the
  default (bool params render as toggles, string defaults as text).
- Every other `stop_ce_pump` default in lila is already a real bool (`= True` at SDC_exp.py:378, 534, …;
  SDC_seq literal dict values are real bools) — only the two sites change.

### 2.7 Task table

Executor model: Sonnet. Group A tasks are file-disjoint and run as concurrent executors. Every task's
gate includes `conda run -n helao python run_unit_tests.py` exit 0 ("suite gate") and a
no-stray-diff check (`git diff` shows only the routed substitutions + import additions — no whitespace
or logic churn).

| ID | Title | Repo | Files (exclusive ownership) | Depends | Group | Verification |
|----|-------|------|------------------------------|---------|-------|--------------|
| T0 | Baseline capture (pre-change) + harness scripts | parent (artifacts only) | `.omc/artifacts/p3a/{demo0_linux.yml,enqueue_oersim.py,normalize_runs_tree.py,baseline.norm,schema_baseline.json}` | — | serial-pre | Baseline sim run reaches `sequence_status: finished`; `baseline.norm` non-empty; re-running normalize on the same tree is idempotent (self-diff empty); schema JSON written. **No file under `helao/` may be modified.** |
| T1 | `status_transitions.py` + 9 model methods + equivalence unit test | parent | `helao/core/models/status_transitions.py` (new), `helao/core/models/{action,experiment,sequence}.py`, `helao/core/tests/unit_test_status_transitions.py` (new) | T0 | serial-pre | New test passes: byte-equal dumps for every primitive × status × start-state, schema equals `schema_baseline.json`; suite gate; `conda run -n helao python -c "from helao.helpers.premodels import Action; a=Action(); a.append_action_status; a.append_experiment_status; a.reset_sequence_status"` exits 0 (diamond composition). |
| T2 | Route base.py sites (8 sites + shim) | parent | `helao/core/servers/base.py` | T1 | A | Import smoke `python -c "import helao.core.servers.base"`; suite gate; grep-zero for raw mutations in file (§2.8 pattern); base.py:1441 still targets `experiment_status` with the NOTE comment; `Base.replace_status` still exists with same signature. |
| T3 | Route orch.py sites (3 sites) | parent | `helao/core/servers/orch.py` | T1 | A | Import smoke `python -c "import helao.core.servers.orch"`; suite gate; grep-zero in file; `_mark_estopped`'s `if estopped not in` guard retained. |
| T4 | Route premodels + micro_orch (7 sites) | parent | `helao/helpers/premodels.py`, `helao/core/runners/micro_orch.py` | T1 | A | Import smoke both modules; run `conda run -n helao python helao/core/tests/unit_test_micro_orch.py` (passes pre-change on this branch → must pass after); suite gate; grep-zero. |
| T5 | Route hte estop/error sites (4 sites) | parent | `helao/deploy/hte/servers/action/pdu_server.py`, `helao/deploy/hte/drivers/spec/spectral_products_driver.py`, `helao/deploy/hte/drivers/sensor/sprintir_driver.py` | T1 | A | `conda run -n helao python -m py_compile` each file (Windows-only imports — do not "fix" unrelated import errors); suite gate; grep-zero. |
| T6 | Route core standalone tests (3 sites) | parent | `helao/core/tests/unit_test_estop_sync.py`, `helao/core/tests/unit_test_orch_status.py` | T1 | A | Run both standalone scripts — pass; suite gate; grep-zero. |
| T7 | lila `stop_ce_pump` fix (2 sites + 2 docstrings) | **lila (nested)** | `helao/deploy/lila/sequences/SDC_seq.py` | — (independent of T1) | A | `py_compile` the file; `grep -n 'bool = "True"' …/SDC_seq.py` empty; `grep -rn '== *"True"' helao/deploy/lila/` returns only nothing (docstrings updated); `python -c "import inspect,…; assert signature default is True"` for both functions; suite gate. Commit **inside** `helao/deploy/lila` (invisible to parent git). |
| T8 | Verification sweep + capture/compare + commits + push | all | — | T2–T7 | serial-post | §2.8 below. |

**T8 sweep (all must pass):**
```bash
conda run -n helao python run_unit_tests.py
conda run -n helao python helao/core/tests/unit_test_status_transitions.py
conda run -n helao python helao/core/tests/unit_test_micro_orch.py
conda run -n helao python helao/core/tests/unit_test_estop_sync.py
conda run -n helao python helao/core/tests/unit_test_orch_status.py
# grep-zero: no raw lifecycle mutations remain outside the allow-list
grep -rnE --include='*.py' \
  '\.(action_status|experiment_status|sequence_status)\s*(\.append|\.remove|\.extend|\.insert|\.clear|=\s*\[)' helao/ \
  | grep -vE 'status_transitions\.py|deploy/lila_gl/|deploy/mea/notes/|deploy/priv/|unit_test_estop_sync\.py:39|sprintir_tests\.py'
# expected: empty (priv = constructor kwargs; the two test hits = mock init, allow-listed)
# end-to-end capture/compare per §2.5 — diff of normalized trees EMPTY; schema diff EMPTY
```
Then commits: **parent** (one commit: T1–T6 + T8 artifacts referenced in message, on
`feat/cards-refactor`) and **lila** (one commit for T7, from inside `helao/deploy/lila`). Push both
(per-increment push policy, as done for Increments 1–2). Commit messages state the byte-identical proof
result and, for lila, the declared `'True'`→`true` serialized delta.

### 2.8 Risk and rollback

- **Byte-identity by construction:** every routed site performs the same list operation; guards only log.
  The three-layer proof (§2.4) catches any slip. The single riskiest spot is base.py:1441's oddity — the
  routing preserves the (probably wrong) target field on purpose; changing it is a logged open question.
- **Log noise:** `logging.getLogger("helao.core.models.status_transitions")` warnings surface via the
  root/lastResort handler even in processes that only configure helao loggers — acceptable (WARNING-level,
  contradiction/duplicate only). If a server's log discipline objects, the logger name gives a one-line
  suppression knob. Deliberately NOT using `helao_logging.make_logger` — core/models stays free of infra
  imports (audit's "pydantic-pure models" strength must be preserved).
- **Shared-file contention:** base.py and orch.py are the repo's hottest files; T2/T3 own them
  exclusively and nothing else in 3a touches them. Rebase `feat/cards-refactor` on `unstable` before T8
  if hotfixes landed mid-flight, then re-run the T8 sweep.
- **hte exposure:** four estop/error-path sites, py_compile-gated, semantically identical appends; no hte
  launch, no config change, no driver logic change. The hot-reload watcher only affects running groups on
  their deployed branch (not `feat/cards-refactor`).
- **Sim nondeterminism:** mitigated by fixed seeds (GPSIM 9999) and the normalizer; escalation rule in
  §2.5 keeps the yml criterion absolute.
- **Rollback:** one commit per repo. Parent revert is self-contained (new module + methods are additive;
  routed sites revert with the commit). The lila commit is independent (no parent-code dependency) and
  reverts alone. No cross-repo ordering constraint in either direction for 3a.

---

## 3. Sketches — 3b, 3c, 3d, 3e (each gets its own detail pass after 3a lands)

### 3b — Typed config injection (Alignment + Domain Integrity)
- Make `load_global_config` validation unconditional; then split the `set_global` control-coupling flag
  (config_loader.py:129) into two named functions (`read_validated_config()` pure /
  `install_global_config()` explicit) — audit Clarity finding "flag flips a pure read into a global
  mutation".
- Thread `HelaoConfig`/`ServerConfig` (config_loader.py:150-192) through `Base.__init__` as an optional
  injected parameter defaulting to the current global lookup — the injection seam that begins retiring
  the `CONFIG` Munch. Replace deep dict navigation (`world_cfg["servers"][key]["host"]`, base.py:148 and
  siblings) with typed attribute access; keep `world_cfg` dict attribute as a shim view so deployment
  code that reads `self.base.world_cfg[...]` is untouched in 3b.
- Constraint: YAML config shape unchanged; every server in every deployment must still construct. Gate:
  suite + import-smoke of all `test` deployment `makeApp`s + the §2.5 end-to-end harness re-run
  (now a reusable asset).
- Extra proving step: validate **every** tracked config (`helao/deploy/{hte,test}/configs/*.yml`) against
  `HelaoConfig` in a standalone test before making validation unconditional — any config that fails today
  is a pre-existing latent break that must be fixed-or-waived first.

### 3c — Discriminated sample `Union` (Domain Integrity)
- Add `Field(discriminator="sample_type")` to the `samples_in`/`samples_out` unions (action.py:142 and
  the twins in experiment.py/sequence.py). Sample subtypes already pin `sample_type` via `Literal`
  (audit: "sample subtypes pin discriminator via Literal") — the blocker is the untyped `SampleModel`
  fallback member, which a discriminated union cannot keep. Plan: corpus-replay historical -act.yml
  sample blocks (RUNS_SYNCED archives + test tree) through the discriminated model to prove the fallback
  is never exercised, or type the fallback as an explicit `Literal`-tagged catch-all before flipping.
- Sample-status lifecycle appends (excluded from 3a) get their guarded wrapper here.
- Risk: validation-behavior change even with identical output shape → corpus replay is the gate.

### 3d — Typed `action_params`, `test` deployment first (Domain Integrity)
- Pilot: replace gpsim's string-keyed `check_condition` dispatch (test gpsim_driver.py:485, audit:
  "KeyErrors on invalid value") with a `StrEnum` + typed param model for the OERSIM experiments; pattern:
  per-experiment pydantic param models whose `.model_dump()` feeds `apm.add` unchanged (wire shape =
  same dict).
- Sims stay bare helpers — no `HelaoDriver` ABC (standing decision; P4 boundary).
- Success = the pattern doc + one fully-typed experiment library (OERSIM_exp) with byte-identical -act
  params on the §2.5 harness; hte/lila/mea adoption is deliberately deferred to post-P3 follow-ups
  (mea `wait_for_temperature` schema divergence is the known blocker there — open question).

### 3e — Flip lifecycle guards to enforcing (Domain Integrity)
- Precondition: soak window (≥2 weeks of `test` + hte production logs after 3a merges to a deployed
  branch) with zero `status_transitions` WARNINGs, or each warning triaged.
- Change: `guarded_append` duplicate → skip (dedup) and contradiction → raise (or dedup+repair, decided
  from telemetry); resolve the base.py:1441 `set_error` field-target question with the hte owner in the
  same increment (both are behavior-visible, so they ship together with their own capture/compare).

---

## 4. Open questions (appended to `.omc/plans/open-questions.md`)

- [ ] base.py:1441 `Active.set_error` appends `errored` to `action.experiment_status`, not
      `action_status` — latent bug or intended propagation? Preserved verbatim in 3a; fixing changes
      -act.yml/status bytes → decide with hte owner in 3e.
- [ ] 3e enforcement flip: soak-window length and which logs count (test-only vs test+hte production).
- [ ] Sample-status lifecycle (`SampleModel.status`, sample.py:196/206 + hte archive/pal appends):
      wrap in 3c alongside the discriminator, or fold into P4's driver rewrites?
- [ ] 3b: do any tracked hte/test configs fail `HelaoConfig` validation today? (Must be answered before
      unconditional validation.)
- [ ] mea `wait_for_temperature` payload divergence (targets+success_count vs flat setpoint) — carry-over;
      blocks extending 3d's typed params to mea.
