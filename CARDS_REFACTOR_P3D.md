# CARDS Refactor — P3 sub-increment 3d: Typed action params pilot on `test` (Domain Integrity)

> Derived from `CARDS_AUDIT.md` Part 1 Domain Integrity + Part 3 ("the core's untyped param contract
> *forces* stringly-typed deployment code"; test `check_condition:485` — "stop condition as raw string
> dispatched through string-keyed dict; KeyErrors on invalid value (should be enum)") and
> `CARDS_REFACTOR_P3.md` §3d sketch. Methodology: the declared-deltas rigor of `CARDS_REFACTOR_P3C.md`
> §3 (exhaustive delta enumeration; anything else in a diff is a defect; capture-per-delta commits).
> Branch: `feat/cards-refactor`, entry HEAD `b6235127` (clean tree, verified 2026-07-10). Parent repo
> only — the `test` deployment lives in the parent; **no nested-repo commits in 3d**; hte/Deployment-A/Deployment-B/Deployment-C
> experiment/param code is untouched (their typing is deferred post-P3; Deployment-B `wait_for_temperature`
> schema divergence is the known blocker there).
>
> **Risk class: LOW-MEDIUM** — sims only, no hardware, no core-model change; but it is the
> **pattern-setter** every deployment will copy, so the wire-equivalence proof must be airtight.
> Hard constraints: -act/-exp/-seq.yml params byte-identical except the deltas declared in §3;
> typed models serialize to the exact dict literal-dict authoring produces today; sims stay bare
> helpers — **no `HelaoDriver` ABC** (standing decision, P4 boundary). Gates: param-dump equivalence
> unit test + `conda run -n helao python run_unit_tests.py` + e2e scrubbed-diff & data-multiset
> compare (§4). Python via `conda run -n helao` (3.12 → `enum.StrEnum` available; pydantic 2.13.4).

---

## 1. Decisions (made, not asked — each backed by evidence collected 2026-07-10)

### D1 — Pilot scope: the `check_condition` StopCondition enum + typed param models for the four OERSIM experiments and the one OERSIM sequence. Nothing else.

This is the minimal set that is end-to-end (sequence → experiment → authored action params → driver
dispatch) and exactly what the audit named. **In scope:** `OERSIM_seq.py` (1 sequence),
`OERSIM_exp.py` (4 experiments), `gpsim_driver.py` `check_condition` (the string-keyed dispatch),
plus one new pydantic-only module holding the enum + models. **Out of scope, deliberately:**
`TEST_exp.py` / `TEST_seq.py` / `simulatews_exp.py` (they add breadth, not new pattern content),
`cpsim_driver.py` / other sim drivers (no string-keyed dispatch finding), `gpsim_server.py` endpoint
annotations (see D5), and every non-`test` deployment. A pilot proves a pattern; typing every test
experiment before the pattern has survived one e2e gate is the over-planning failure mode. Empty
authored dicts (`{}` — e.g. every `apm.add` in `OERSIM_sub_measure_CP`) stay `{}`: there is nothing
to type, and a zero-field model would be ceremony.

### D2 — The typo is real, load-bearing evidence, and gets FIXED as its own declared, capture-isolated delta

Discovery (grep + wire capture, 2026-07-10): `OERSIM_exp.py:133` authors the key **`"stop_condtion"`**
(missing "i") into the `check_condition` action params, while the driver reads
`params["stop_condition"]` (`gpsim_driver.py:503`). It works today only by accident of a masking
chain: `base_api.py:154-169` backfills any endpoint-signature default missing from `action_params`,
and the `check_condition` endpoint declares `stop_condition: str = "max_iters"`
(`gpsim_server.py:134`). Proof on the wire — the 3c post-capture `.omc/artifacts/p3/p3c_post.norm:952-964`
shows the executed action carrying **both** keys:

```yaml
action_params:
  stop_condtion: max_iters      # authored (typo) — dead key, never read
  thresh_value: 10
  repeat_experiment_name: OERSIM_sub_activelearn
  repeat_experiment_params: {init_random_points: 5, stop_condition: max_iters, thresh_value: 10}
  plate_id: 2750                # from_global injected
  orch_key: ORCH / orch_host / orch_port
  stop_condition: max_iters     # endpoint-default backfill — what the driver actually reads
  action_version: 1
```

**Consequence: the user-authored `stop_condition` value has NEVER reached the driver.** Anyone
requesting `"max_ei"`/`"max_stdev"`/`"none"` through the sequence silently ran `"max_iters"`. This is
the exact bug class typed params exist to kill (a `model_config extra="forbid"` model would have
rejected the key at authoring time), which makes it the strongest possible pilot evidence — and makes
"preserve the typo byte-identically via a serialization alias" (the only way to satisfy a literal
zero-delta reading) self-defeating: it would enshrine the defect inside the typed model that exists
to prevent it. **Decision:** fix the typo as its own commit with its own e2e capture (3d-T1), so the
key-rename delta is enumerated in isolation before any typed-model change, exactly like 3a handled
Deployment-A `stop_ce_pump`. The harness runs on default params (`max_iters`), where old backfilled value ==
new authored value, so the T1 delta is a pure key rename + disappearance of the backfill line — no
run-behavior change in the gate itself. Sequence-level spelling was always correct
(`OERSIM_seq.py:41`, `multi_orch_demo_helper.py:41`), so nothing outside `OERSIM_exp.py:133` changes.

### D3 — `check_condition` StrEnum is a bugfix-with-declared-delta, not a silent behavior change

Accepted values stay byte-identical: `StopCondition` is a `StrEnum` with exactly the four historical
strings `"none" | "max_iters" | "max_stdev" | "max_ei"` (source of truth for the set:
`gpsim_driver.py:514-527` `repeat_map` keys, `OERSIM_exp.py:95` comment, `gpsim_server.py:134`
default). The only behavior change is the **unknown-value path**: today an invalid value that reaches
the driver dies as `KeyError: 'bogus'` at `repeat_map[stop_condition]` (`gpsim_driver.py:528`); after
3d it raises `ValueError("invalid stop_condition 'bogus'; valid: none, max_iters, max_stdev,
max_ei")` from a pure helper — and, one layer earlier, pydantic `ValidationError` at experiment
authoring time. Declared as delta §3.2 (same class as 3a's `stop_ce_pump`: an error-path improvement
on a value no valid caller produces). Note the pre-fix reality is even worse than the audit stated:
because of the D2 typo, an invalid *authored* value never even reached the dispatch — it was
silently replaced by `"max_iters"`.

### D4 — Enum + models live in a new pydantic-only module `helao/deploy/test/param_models.py`, NOT in the driver

The naive home (`gpsim_driver.py`) is disqualified by the known **gpflow transitive-import trap**
(project memory: importing `gpsim_driver` drags `gpflow`/TensorFlow into every consumer): experiment
and sequence libraries, the unit test, and — via the `run_unit_tests.py` registry — every `launch.py`
invocation on every station would pay that import. `param_models.py` imports only `enum`, `typing`,
and `pydantic`; driver, experiments, sequences, and test all import from it (driver → deployment-root
module is same-deployment, no layering inversion; experiments never import the driver). This also
keeps the pattern copyable: an hte adopter needs a `param_models.py`, not a driver refactor.

### D5 — `gpsim_server.py` endpoint annotations stay `str` in 3d

Typing the endpoint parameter as `StopCondition` would make FastAPI reject invalid values with a 422
**at dispatch**, before an Active/action exists — a different failure surface (orch dispatch-error
handling) than the driver's errored action, and an OpenAPI schema change. That is a real Domain
Integrity improvement but a separate, dispatch-layer behavior change that deserves its own capture;
deferred as an open question (§10). 3d's enforcement points are: authoring (pydantic model) and
driver dispatch (enum resolution). The `base_api` default-backfill mechanism is likewise untouched
(core code; out of a test-only increment).

### D6 — Wire-identity mechanics: field order = legacy key order, `use_enum_values=True`, `extra="forbid"`, `Union[int, float]` preservation

The typed models must reproduce the legacy dicts *byte-for-byte through `yml_dumps`*, which means:
(a) **key order** — pydantic v2 `model_dump()` preserves field declaration order; every model
declares fields in the exact order of the legacy literal dict; the unit test asserts
`list(dump.keys())` equality, not just dict equality. (b) **enum leakage** — `model_config =
ConfigDict(use_enum_values=True)` so validated instances store the plain `str` value and
`model_dump()` emits `str`, never an enum instance, making yml emission byte-identical regardless of
yml_dumps' enum handling. (c) **typo class prevention** — `extra="forbid"` on every param model (the
D2 bug is impossible to author through one). (d) **numeric fidelity** — `thresh_value:
Union[int, float]` (int first): pydantic 2 smart mode keeps `10` an `int` (asserted in the test;
`10` vs `10.0` is a yml byte difference). (e) **empty-dict stripping parity** — the serializer
strips empty-dict params from -act.yml (observed: authored `repeat_experiment_kwargs: {}` absent
from the wire block in D2); models pass the same `{}` through, so stripping behaves identically —
no model field may introduce or omit a key relative to the legacy dict.

### D7 — The e2e gate is upgraded BEFORE any code change, and proven on a double-baseline

The known normalizer gaps (brief + inspection of `.omc/artifacts/p3/normalize_runs_tree.py`) are
fixed in the harness first: (a) `hlo_version` (embeds git describe/SHA — changes with every commit)
is not scrubbed; (b) the `DIRTS` regex `\d{8}\.\d{6,9}` expects `YYYYMMDD` but real dir stamps are
`YYMMDD.HHMMSSffffff` (6-digit date, up to 12 fractional digits) so run-dir timestamps leak; (c)
`*_codehash` fields must NOW be normalized — unlike 3a/3c, 3d intentionally edits authored
experiment/sequence source, so their codehashes legitimately change (declared, §3.3); (d) hlo
async-flush chunk boundaries vary run-to-run, so hlo data is compared as per-key **value multisets**
(3c's verification method), not text. A new `compare_runs.py` artifact implements scrubbed
structural diff + multiset compare, and 3d-T0 proves the whole gate's noise-immunity by capturing
**two** pre-change baselines and requiring them to compare clean against each other before any
`helao/` file is touched.

---

## 2. Current-state evidence (all verified on HEAD `b6235127`, 2026-07-10)

| Fact | Where |
|---|---|
| String-keyed dispatch: `repeat_map` dict keyed by 4 raw strings; `repeat_map[stop_condition]` KeyErrors on unknown | `helao/deploy/test/drivers/data/gpsim_driver.py:514-528` |
| Driver reads `params["stop_condition"]`, `["thresh_value"]`, `["repeat_experiment_*"]`, `["plate_id"]`, `["orch_*"]` from `activeobj.action.action_params` | gpsim_driver.py:501-509 |
| Authored typo `"stop_condtion"` — only occurrence repo-wide | `helao/deploy/test/experiments/OERSIM_exp.py:133` (grep: no other hit) |
| Endpoint default that masks it: `stop_condition: str = "max_iters"` | `helao/deploy/test/servers/action/gpsim_server.py:134` |
| Backfill mechanism: endpoint-signature defaults not present in `action_params` are added | `helao/core/servers/base_api.py:154-169` |
| Wire proof: executed action carries dead `stop_condtion` + backfilled `stop_condition`; `repeat_experiment_kwargs: {}` stripped from dump | `.omc/artifacts/p3/p3c_post.norm:952-964` (10× per run, one per iteration) |
| Authored param dicts to type: `{"plate_id": …}`, `{"num_random_points": …, "reinitialize": False}` (load_plate); 5-key check_condition dict (decision); 3-key `epm.add` dict (seq) | OERSIM_exp.py:45-55, 129-138; OERSIM_seq.py:37-44 |
| `apm.add` stores the authored dict verbatim on the `Action` (`action_params` passed through, no merge at authoring) | `helao/helpers/premodels.py:496-541` |
| `ActionPlanMaker` falls back to a blank `Experiment` when called outside the decorator context → experiment functions are callable offline for the unit test | premodels.py:443-447 |
| `OERSIM_sub_activelearn` builds `repeat_experiment_params` by reflection over `vars(apm.pars)` | OERSIM_exp.py:186-190 |
| Sequence-level spelling correct everywhere else | OERSIM_seq.py:41; `helao/deploy/test/demos/multi_orch_demo_helper.py:41` |
| Sims are bare helpers (`GPSim.__init__(action_serv: Base)`), Executor contract honored — ABC-skip is the standing decision, unchanged by 3d | gpsim_driver.py:76-83, 567-608; memory "SP8 drivers are bare helpers" |
| e2e harness works on this HEAD: `run_e2e.sh <label>` → CPSIM/GPSIM/ORCH launch, `enqueue_oersim.py` waits for `finished`, normalized snapshot | `.omc/artifacts/p3/run_e2e.sh`; trees `/tmp/hlo_p3_{baseline,fixcheck,p3c_post}` present |
| Normalizer gaps: no `hlo_version` scrub; `DIRTS` = `\d{8}\.\d{6,9}` (wrong date width); no codehash scrub | `.omc/artifacts/p3/normalize_runs_tree.py:8-15` |
| Suite registry pattern to extend (3c added `sample_union` the same way) | `run_unit_tests.py:47-69` |
| gpflow transitive-import trap: importing gpsim_driver pulls gpflow — enum must not live there | memory "SP8 driver lifecycle offenders"; gpsim_driver.py:25 |
| Python 3.12 (`StrEnum` stdlib), pydantic 2.13.4 | conda env `helao`; P3C header |

---

## 3. Declared deltas (exhaustive — anything else in a diff is a defect)

1. **Typo key fix (commit 1, capture-isolated).** In every `check_condition` action's params, on
   -exp.yml (planned actions) and -act.yml (executed): authored key `stop_condtion` → `stop_condition`,
   and the trailing endpoint-backfill `stop_condition: max_iters` line disappears (the authored value
   now occupies the key). Values identical in the gate (both `max_iters`). Behavior: the authored
   `stop_condition` value now actually reaches the driver — previously silently replaced by the
   endpoint default. Proven byte-exactly by the T1 capture diff, and functionally by the T5 probe
   (`max_ei` + huge threshold → exactly 1 iteration; pre-fix this would have run 10+).
2. **Unknown stop-condition path.** Driver: `KeyError: '<value>'` → `ValueError` naming the value and
   the four valid members (audit's "KeyErrors on invalid value" finding). Authoring layer:
   invalid values / unknown keys now fail at experiment-planning time with pydantic
   `ValidationError` instead of flowing to (and past) the driver. No valid caller is affected.
3. **`*_codehash` values change** for the edited OERSIM experiment/sequence functions and the gpsim
   driver module (codehash is derived from source). Inherent to editing authored source; normalized
   by the upgraded comparator; asserted to be the ONLY hlo/yml header-field class that moves.
4. **New WARNING-free, schema-free surface.** No OpenAPI change (endpoints untouched, D5), no core
   model change, no new log lines in the nominal path, no config change, no HLO header/data change
   (data multisets equal).

---

## 4. Harness upgrade + gate definition (3d-T0, artifacts only)

All edits under `.omc/artifacts/p3/` (operational, untracked — **nothing under `helao/`**):

**`normalize_runs_tree.py` — add/fix scrub patterns:**
- Fix `DIRTS` → `re.compile(r"\b\d{6}\.\d{6,18}\b")` (YYMMDD.HHMMSS + up to 12 fractional digits);
  keep the old 8-digit pattern too (harmless, matches nothing real).
- Add `HLOVER`: line-level `re.compile(r"(hlo_version['\"]?\s*[:=]\s*)\S+")` → keep group 1, token the value.
- Add `CODEHASH`: `re.compile(r"([a-z_]*codehash['\"]?\s*[:=]\s*)['\"]?[0-9a-f]{6,40}['\"]?")` → same.

**New `compare_runs.py <labelA> <labelB>`** — the 3d gate comparator, encoding 3c's verification
method as a script: (1) manifests of normalized relpaths must be equal; (2) every non-`.hlo` file's
normalized text must be equal (unified diff printed on mismatch); (3) every `.hlo` file: normalized
**header** (yml preamble) must be equal; **data lines** are parsed as JSON, merged per data-key, and
compared as **value multisets** (chunk/flush boundaries are declared noise; ordered-sequence equality
is reported as informational, multiset equality is the gate). Exit 0 iff all three pass.

**`enqueue_oersim.py`** — add optional `--seq-params '{"stop_condition": "max_ei", ...}'` JSON
override merged over the library defaults (needed by the T5 behavior probe; default behavior
unchanged).

**Gate protocol (used at T1 and T5):**
```bash
bash .omc/artifacts/p3/run_e2e.sh <label>          # launch sims, run OERSIM_activelearn to finished
conda run -n helao python .omc/artifacts/p3/compare_runs.py <ref_label> <label>
```

**T0 double-baseline proof:** capture `p3d_base` and `p3d_base2` on the untouched HEAD;
`compare_runs.py p3d_base p3d_base2` MUST pass. This certifies the comparator absorbs every
nondeterminism class (timestamps, uuids, chunk boundaries, hlo_version) *before* any code change —
any later mismatch is therefore attributable to 3d code, not harness noise. If the double-baseline
fails, STOP: fix the comparator (never the criterion) until it passes; escalation rule from P3
§2.5 applies unchanged (yml criterion is absolute; only hlo data-grouping may be relaxed, to
multisets, which is already the design).

---

## 5. Typed-param design — `helao/deploy/test/param_models.py` (new, pydantic + stdlib only)

```python
"""Typed action/experiment parameter models for the test deployment (CARDS 3d pilot).

Pattern contract (deployment adopters copy this, not the sim internals):
- one model per authored params payload; fields declared in the legacy dict's key order
- model_config: extra="forbid" (kills authored-key typos), use_enum_values=True (dumps plain str)
- .model_dump() feeds apm.add / epm.add UNCHANGED — wire shape is byte-identical to the
  literal dict it replaces (proven by unit_test_oersim_params + the e2e gate)
- import cost: pydantic only; NEVER house these in a driver module (gpflow import trap)
"""
from enum import StrEnum
from typing import Union
from pydantic import BaseModel, ConfigDict


class StopCondition(StrEnum):
    """Stop-condition dispatch keys for GPSim.check_condition (legacy string values, verbatim)."""
    none = "none"
    max_iters = "max_iters"
    max_stdev = "max_stdev"
    max_ei = "max_ei"


def resolve_stop_condition(value) -> StopCondition:
    """Coerce a wire value to StopCondition; clear error on unknown (was: bare KeyError)."""
    try:
        return StopCondition(value)
    except ValueError:
        valid = ", ".join(m.value for m in StopCondition)
        raise ValueError(f"invalid stop_condition {value!r}; valid: {valid}") from None


class _ParamModel(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)


# --- action-level payloads (feed apm.add) ---
class CPSIMChangePlateParams(_ParamModel):
    plate_id: int = 0

class GPSIMInitializePlateParams(_ParamModel):
    num_random_points: int = 5
    reinitialize: bool = False

class GPSIMCheckConditionParams(_ParamModel):
    stop_condition: StopCondition = StopCondition.max_iters
    thresh_value: Union[int, float] = 10
    repeat_experiment_name: str = "OERSIM_sub_activelearn"
    repeat_experiment_params: dict = {}
    repeat_experiment_kwargs: dict = {}

# --- experiment-level payloads (validate exp-function inputs / feed epm.add) ---
class OERSIMSubLoadPlateParams(_ParamModel):
    plate_id: int = 0
    init_random_points: int = 5

class OERSIMSubActivelearnParams(_ParamModel):
    init_random_points: int = 5
    stop_condition: StopCondition = StopCondition.max_iters
    thresh_value: Union[int, float] = 10
    repeat_experiment_kwargs: dict = {}

class OERSIMActivelearnSeqParams(_ParamModel):
    init_random_points: int = 5
    stop_condition: StopCondition = StopCondition.max_iters
    thresh_value: Union[int, float] = 10
```

(Executor: mutable `{}` defaults mirror the legacy signatures deliberately — pydantic deep-copies
field defaults per instance, so the shared-mutable-default hazard of plain Python does not apply;
do not "fix" them to `Field(default_factory=dict)` unless dump bytes are proven identical — they
are, but the frozen-literal test is the arbiter.)

### 5.1 `OERSIM_exp.py` rewiring (task T3)

- `OERSIM_sub_load_plate`: `pars = OERSIMSubLoadPlateParams(plate_id=plate_id,
  init_random_points=init_random_points)`; then
  `apm.add(CPSIM_server, "change_plate", CPSIMChangePlateParams(plate_id=pars.plate_id).model_dump())`
  and `apm.add(GPSIM_server, "initialize_plate",
  GPSIMInitializePlateParams(num_random_points=pars.init_random_points, reinitialize=False).model_dump(), …)`.
  (Key rename `init_random_points`→`num_random_points` is the exact legacy mapping, now explicit.)
- `OERSIM_sub_measure_CP`: authored dicts are all `{}` — unchanged (D1).
- `OERSIM_sub_decision`: signature keys == check_condition authored keys, so ONE model serves both
  roles: `pars = GPSIMCheckConditionParams(stop_condition=stop_condition, thresh_value=thresh_value,
  repeat_experiment_name=…, repeat_experiment_params=…, repeat_experiment_kwargs=…)`;
  `apm.add(GPSIM_server, "check_condition", pars.model_dump(), from_global_act_params={…verbatim…})`.
  This is where the D2 typo dies and can never return (`extra="forbid"`).
- `OERSIM_sub_activelearn`: `pars = OERSIMSubActivelearnParams(init_random_points=…,
  stop_condition=…, thresh_value=…, repeat_experiment_kwargs=…)` validates inputs (incl. requeued
  ones — the self-requeue loop re-enters this function every iteration, so the enum is enforced on
  every hop); the `repeat_experiment_params = {k: v for k, v in vars(apm.pars).items() if not
  k.startswith("experiment")}` reflection stays **verbatim** (typing it requires ActionPlanMaker
  awareness of models — core change, out of scope, §10). Function signatures, defaults, and
  decorator usage stay exactly as-is (`str`/`Union[float, int]` primitives) so orchestrator
  invocation and operator-UI param rendering are untouched.

### 5.2 `OERSIM_seq.py` rewiring (task T3)

`epm.add("OERSIM_sub_activelearn", OERSIMActivelearnSeqParams(init_random_points=…,
stop_condition=…, thresh_value=…).model_dump())`. Signature unchanged.

---

## 6. `check_condition` enum transformation — `gpsim_driver.py` (task T4)

Add `from helao.deploy.test.param_models import StopCondition, resolve_stop_condition` (top-level —
param_models is dependency-free, no cycle; driver already imports deployment-adjacent helpers).
In `check_condition` (:485):

```python
stop_condition = resolve_stop_condition(params["stop_condition"])   # was: raw string passthrough
...
repeat_map = {
    StopCondition.none: len(self.acquired[plate_id] + self.acq_fromglobal[plate_id])
    < self.features[plate_id].shape[0],
    StopCondition.max_iters: progress["plate_step"] < thresh_value,
    StopCondition.max_stdev: max(...) > thresh_value,      # bodies verbatim
    StopCondition.max_ei: progress["expected_improvement"] > thresh_value,
}
if repeat_map[stop_condition] and repeat_map[StopCondition.none]:
```

Constraints: all four condition expressions stay **byte-verbatim** (incl. the eager evaluation of
all four — side-effect-free, and laziness would be an unrequested behavior change); the met-condition
log line keeps its f-string (StrEnum interpolates as its value); `GPSimExec`, `fit_model`,
`acquire_point`, `__init__` untouched (the god-constructor is a P4/SP8 item, not 3d). Docstring
updated to name `StopCondition`.

---

## 7. Equivalence unit test (task T2) — `helao/deploy/test/tests/unit_test_oersim_params.py`

Standalone script + registry entry `("oersim_params", oersim_params_unit_test)` in
`run_unit_tests.py` (3c's `sample_union` precedent). Import cost audit is part of the test's job:
it may import `param_models`, `OERSIM_exp`, `OERSIM_seq`, `helao.helpers.yml_tools` — it must NOT
import `gpsim_driver` (gpflow) — the suite runs before every launch on every station, incl. hte
Windows. Checks:

1. **Frozen-literal dump equivalence** (the param-dump equivalence gate): for each model in §5,
   `model_dump()` == the frozen legacy dict literal (post-typo-fix spelling), AND
   `list(dump.keys()) == list(legacy.keys())` (order), AND `yml_dumps(dump) == yml_dumps(legacy)`
   (bytes), for defaults and for a non-default valuation of every field.
2. **Authoring-path equivalence**: call each OERSIM experiment function offline (blank-Experiment
   fallback, premodels.py:443-447) with defaults and with non-default args; assert every planned
   action's `action_params` equals the frozen legacy dict for that action (order + yml bytes), and
   `OERSIM_activelearn()`'s planned experiment params likewise.
3. **Type fidelity**: `thresh_value=10` stays `int` in the dump; `=10.5` stays `float`;
   `stop_condition` dumps as plain `str` (`type(...) is str`, `use_enum_values` proof); enum and
   string inputs (`StopCondition.max_ei` / `"max_ei"`) dump identically.
4. **Enforcement**: `GPSIMCheckConditionParams(stop_condition="bogus")` raises `ValidationError`;
   unknown key (`stop_condtion="max_iters"` — the literal historical typo) raises `ValidationError`
   (regression pin on D2); `resolve_stop_condition("bogus")` raises `ValueError` whose message
   contains all four valid values; `resolve_stop_condition("max_ei") is StopCondition.max_ei`.
5. **Enum surface freeze**: `[m.value for m in StopCondition] == ["none", "max_iters", "max_stdev",
   "max_ei"]` (wire values are API).

---

## 8. Task table

Executor model: **Sonnet** for all tasks. Every task's gate includes
`conda run -n helao python run_unit_tests.py` exit 0 (suite gate) and the no-stray-diff rule
(`git diff` limited to the documented edits). e2e runs are serialized (shared ports/tmp roots);
waves: **T0 → T1 → T2 → (T3 ∥ T4) → T5.**

| ID | Title | Files (exclusive ownership) | Depends | Group | Verification |
|----|-------|------------------------------|---------|-------|--------------|
| 3d-T0 | Harness upgrade + double-baseline | `.omc/artifacts/p3/normalize_runs_tree.py`, `compare_runs.py` (new), `enqueue_oersim.py` (`--seq-params`); captures `p3d_base.norm`, `p3d_base2.norm` — **nothing under `helao/`** | — | Wave 1 (serial) | Both baseline runs reach `sequence_status: finished`; `compare_runs.py p3d_base p3d_base2` exits 0 (noise-immunity proof, §4); normalizer idempotent (re-normalize same tree → self-diff empty); suite green at baseline. |
| 3d-T1 | Typo fix + isolated delta capture + **commit 1** | `helao/deploy/test/experiments/OERSIM_exp.py` (line 133 only) | T0 | Wave 2 (serial) | `grep -rn stop_condtion helao/` → empty; e2e `p3d_typofix` finishes; `compare_runs.py p3d_base p3d_typofix` fails ONLY on the §3.1 lines — the report must enumerate them exactly (key rename + backfill-line removal per check_condition act/exp entry, ×10 iterations, + codehash of the edited function) and NOTHING else; commit on `feat/cards-refactor` declaring delta §3.1. |
| 3d-T2 | `param_models.py` + unit test + registry | `helao/deploy/test/param_models.py` (new), `helao/deploy/test/tests/__init__.py` + `unit_test_oersim_params.py` (new), `run_unit_tests.py` (one registry line) | T1 | Wave 3 (serial) | §7 test exits 0 standalone AND via suite; import-cost check: `conda run -n helao python -c "import sys; import helao.deploy.test.param_models; assert 'gpflow' not in sys.modules and 'tensorflow' not in sys.modules"`; suite gate. |
| 3d-T3 | Rewire OERSIM experiment + sequence libs onto models | `helao/deploy/test/experiments/OERSIM_exp.py`, `helao/deploy/test/sequences/OERSIM_seq.py` | T2 | Wave 4 (∥ T4) | Import smoke both modules; §7 checks 1-2 re-pass (authoring-path equivalence now exercises the model-backed code); suite gate; grep gate: no dict-literal authored params with >1 key remain in either file (`{}` allowed). |
| 3d-T4 | `check_condition` enum dispatch | `helao/deploy/test/drivers/data/gpsim_driver.py` | T2 | Wave 4 (∥ T3) | `conda run -n helao python -c "import helao.deploy.test.drivers.data.gpsim_driver"` (gpflow available on Linux env); grep gate: no string-keyed `repeat_map` (`grep -n '"none"\|"max_iters"\|"max_stdev"\|"max_ei"' gpsim_driver.py` → docstring/comment hits only); condition expressions byte-verbatim vs HEAD (reviewed in diff); suite gate. |
| 3d-T5 | Verification sweep + behavior probe + **commit 2** + push | — (artifacts: `p3d_post.norm`, `p3d_probe.norm`, probe report) | T3, T4 | Wave 5 (serial) | §8.1 below. |

### 8.1 3d-T5 sweep (all must pass)

```bash
conda run -n helao python run_unit_tests.py
conda run -n helao python helao/deploy/test/tests/unit_test_oersim_params.py

# e2e wire identity vs the typo-fix reference (typed layer must be byte-invisible)
bash .omc/artifacts/p3/run_e2e.sh p3d_post
conda run -n helao python .omc/artifacts/p3/compare_runs.py p3d_typofix p3d_post
# MUST exit 0: scrubbed structural diff empty (codehash/hlo_version tokenized), hlo data multisets equal

# behavior-fix probe (proves the authored value now reaches the driver AND exercises a
# non-default enum member end-to-end; pre-fix this configuration ran >=10 iterations)
bash-with-override: run_e2e.sh p3d_probe using enqueue --seq-params '{"stop_condition": "max_ei", "thresh_value": 1e9}'
# assert: sequence finishes; exactly ONE check_condition action in the p3d_probe tree;
# its -act.yml carries stop_condition: max_ei

# grep gates
grep -rn "stop_condtion" helao/                                             # empty
grep -rn "repeat_map\[" helao/deploy/test/drivers/data/gpsim_driver.py      # enum-keyed only (reviewed)
git diff --stat b6235127..HEAD -- helao/ | grep -v "deploy/test\|run_unit_tests.py"  # empty: test-deployment-only pledge
```

Then **commit 2** (T2-T4 + test + registry) on `feat/cards-refactor`, message stating: the
frozen-literal + e2e proof results, the probe result, and deltas §3.2-3.3; push (per-increment
policy; commit 1 pushed with it). No nested-repo commits.

---

## 9. Risk and rollback

- **Wire identity is the risk, and it is double-gated:** frozen-literal yml-bytes test (fails in
  milliseconds at T2/T3) + e2e compare vs `p3d_typofix` (catches anything the literals missed —
  e.g. serializer interactions like empty-dict stripping, D6e). The comparator itself is certified
  by the T0 double-baseline before it is trusted with a verdict.
- **Delta attribution:** the only intentional wire delta (typo fix) is isolated in commit 1 with its
  own capture; the typed layer (commit 2) must be byte-invisible. Two commits → independent
  reverts: reverting commit 2 restores literal-dict authoring + string dispatch (typo stays fixed);
  reverting both restores HEAD `b6235127` exactly. `.omc` artifacts are untracked and survive.
- **Requeue-loop exposure:** the self-requeue path re-invokes `OERSIM_sub_activelearn` each
  iteration, so model validation runs ~10× per e2e — the gate exercises the typed path repeatedly,
  not once. `repeat_experiment_params` remains a reflection dict (declared non-goal), so no
  `extra="forbid"` surface faces orchestrator-injected keys.
- **Import-weight regression:** the suite gate runs at every `launch.py` on every station;
  `param_models.py` and the test module are pydantic-only and the T2 gate asserts gpflow/tensorflow
  absent from `sys.modules`. The enum deliberately does NOT live in the driver (D4).
- **Windows/hte exposure: none.** No hte/Deployment-A/Deployment-B/Deployment-C file changes (T5 grep-pledge); the one core
  file touched is the `run_unit_tests.py` registry line; new test imports are OS-neutral.
- **Sim nondeterminism:** GPSIM seed 9999 / CPSIM plate 2750 unchanged; chunk-boundary noise is
  absorbed by multiset compare; anything the double-baseline doesn't absorb blocks at T0, before
  code changes, where it is a harness bug by definition.
- **Pattern risk (this is the pattern-setter):** the §5 module docstring carries the adopter
  contract (field order, `use_enum_values`, `extra="forbid"`, no driver-module placement) so hte/Deployment-A
  adoption copies the constraints, not just the shape.

---

## 10. Open questions (appended to `.omc/plans/open-questions.md`)

- [ ] Type `gpsim_server.py` `check_condition` endpoint annotation as `StopCondition` — moves invalid
      values to a FastAPI 422 at dispatch (different orch-facing failure surface + OpenAPI schema
      change); wants its own capture. 3d follow-up or fold into P4's server-layer work?
- [ ] `base_api` endpoint-default backfill (base_api.py:154-169) is what masked the D2 typo for
      years — should the framework WARN when an authored `action_params` key matches no endpoint
      parameter (generic authored-key vs endpoint-signature mismatch detector)? Would have caught
      this and likely has hits across hte's 257 magic-string `apm.add` sites. Core change → post-P3.
- [ ] `ActionPlanMaker.add` / `ExperimentPlanMaker.add` native `BaseModel` support (accept a model,
      call `.model_dump()` internally) — core ergonomics that would let adopters skip the manual
      dump; out of 3d's test-only mandate.
- [ ] `repeat_experiment_params` reflection dict (OERSIM_exp.py:186-190) left untyped — round-trip
      typing depends on the ActionPlanMaker item above.
- [ ] Extending the typed-param pattern beyond OERSIM: `TEST_exp`/`simulatews_exp` (trivial), then
      hte/Deployment-A/Deployment-B post-P3 — Deployment-B `wait_for_temperature` payload divergence (targets+success_count vs
      flat setpoint) remains the known Deployment-B blocker (carry-over from P3 §4).
- [ ] Carry-overs unchanged from 3a/3c: base.py:1441 `set_error` field-target oddity; 3e soak
      window + enforcement flip; `SampleModel.sample_type` enum tightening.
