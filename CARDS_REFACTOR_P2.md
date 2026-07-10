# CARDS Refactor — P2: Kill duplication (full plan)

> Expands `CARDS_REFACTOR_PLAN.md` §4 "P2 — Kill duplication". Evidence: `CARDS_AUDIT.md` Part 2.
> Date: 2026-07-10 · Branches: `feat/cards-refactor` on parent + nested lila, mea, priv repos
> (`deploy/lila_gl` and `deploy/mea/notes` excluded entirely). Increment 1 (RunDir enum) already landed.
> CARDS cards strengthened: **Resilience** (single source of truth), **Clarity**.

---

## 1. Scope statement

**Goal:** remove duplicated knowledge in four campaign/spec/script hot spots — pure structural,
**zero behavior change**, fully verifiable on Linux with no hardware. Every public name and file
path referenced by configs, sequences-by-string, processors, or HTTP routes is preserved via thin
wrappers. Serialized outputs (experiment/sequence plan lists, `SampleModel` dicts, HTTP responses,
OpenAPI operation ids) must be byte-identical, proven by captured baselines.

**Targets (one per repo — fully parallelizable):**

| # | Repo | Target | Audit evidence |
|---|------|--------|----------------|
| T1 | parent (hte) | `specifications/last2weeks.py` + `bimonthly.py` byte-identical; `last3months.py` differs by one number → one parameterized parser + 3 thin wrapper files | Part 2 hte |
| T2 | lila (nested) | `sequences/SDC_seq.py` three ~430–516-line near-duplicate sequences (`:3487`, `:3972`, `:4488`) → one core builder + 3 signature-preserving wrappers | Part 2 lila |
| T3 | mea (nested) | `experiments/AMTS_exp.py`: 29× copy-pasted `SampleModel` block → factory; `configure_leancat` vs `configure_leancat_for_ADVENT_MEA` → extract byte-identical common stages only | Part 2 mea |
| T4 | priv (nested) | delete dead `extract_parts` in `scripts/common/helao_nbio.py`; unify the four `/run_<instrument>` handlers — **scope correction: they live in `servers/action/batch_convert_server.py:387-405`, not helao_nbio.py** | Part 2 priv |

**Decisions (one option each, per mandate):**

- **dbpack retirement: DEFERRED (keep frozen).** Retiring `dbpack_driver.py`/`dbpack_server.py`
  requires sweeping ~10 hte YAML configs on live-hardware stations plus operator sign-off — out of
  scope for a pure-structural, no-behavior-change phase. dbpack stays untouched and frozen exactly
  as in Increment 1. Do NOT touch any dbpack file in P2.
- **`extract_parts_old` is LIVE, not dead** (called from `scripts/icpms/convert_icpms_csv.py:174,177`).
  Despite the name, it is the icpms conversion path. P2 deletes only the genuinely dead
  `extract_parts` (zero callers repo-wide). No rename of `extract_parts_old` in P2 (open question).
- **mea `configure_leancat*`: dedupe identical stages only, do NOT unify.** The two functions have a
  real payload-schema divergence in `wait_for_temperature` (`targets` dict + `success_count` vs flat
  `setpoint`) plus `process_finish`/`from_global_act_params`/`technique_name` differences. Unifying
  those is a behavior change → out of scope; divergent steps stay inline verbatim (open question).
- **`bimonthly.py` keeps its current 2-week behavior** (it is byte-identical to `last2weeks.py`
  today, i.e. `range(2)` despite the name). "Fixing" it to ~8 weeks is a behavior change (open question).
- **priv route factory iterates the fixed tuple `("bruker","edax","xafs","icpms")`**, NOT
  `JOB_MODULES.keys()` — deriving from the registry would drop `/run_edax` (edax is commented out of
  `JOB_MODULES`) and add routes for `xrfs_quant`/`xrfs_cal`. Both are behavior changes (open questions).
- **hte production safety:** T1 touches only `helao/deploy/hte/specifications/` — these files are
  loaded only by the Bokeh operator UI (`bokeh_operator.py:318-332`), never by drivers or the
  action/orchestrator control path. No other hte file is touched in P2.

**Estimated complexity: MEDIUM** — 4 independent tasks + 1 verification task, ~10 files across 4 repos.

---

## 2. Framework mechanics that constrain the design (verified 2026-07-10)

1. **Spec-parser contract** (`helao/core/servers/operator/bokeh_operator.py:318-332`): the operator
   loads the config's `seqspec_parser_path` file via `importlib.util.spec_from_file_location` (module
   name = file basename) and calls `module.SpecParser()` with **no args**. Contract = exact file path
   + a class named `SpecParser` + no-arg constructor + `PARAM_TYPES`/`lister`/`list_params`/`parser`.
   Because the module is exec'd outside the package, wrapper files must use **absolute imports**
   (`from helao.deploy.hte.specifications... import ...`) — fine, since `PYTHONPATH` always includes
   the repo root. Config-referenced paths (e.g. `hte/configs/ccsi2.yml:23` → `last2weeks.py`;
   ~10 configs + `priv/configs/icpm1.yml:19` → `last3months.py`) must keep resolving to real files.
2. **`ActionPlanMaker.__init__` inspects the caller's frame** (`helao/helpers/premodels.py:409-411`):
   it reads the calling function's declared args and `co_name`. Therefore in mea, `apm =
   ActionPlanMaker()` **must remain inside each public experiment function**. `apm.add(...)` is
   frame-free (`premodels.py:496-541`), so groups of `add` calls MAY move into private helpers that
   receive `apm` + explicit values.
3. **`ExperimentPlanMaker` is frame-free** (`premodels.py:551-583`): lila sequence bodies can
   delegate entirely to a shared core function; only the public function's **name, signature with
   defaults, and `@sequence(version=N)` decorator** are contract (the operator/spec-parser introspect
   signatures via `inspect.getfullargspec` — wrappers must use real named params, never `**kwargs`).
4. **lila public-name registry:** configs list the module (`configs/electrode-demo.py:16`
   `sequence_libraries: ["SDC_seq"]`); the orchestrator enumerates `__all__`/`SEQUENCES`
   (`SDC_seq.py:11-37`). The three function names must stay in `__all__` unchanged. Additionally,
   `processors/append_ref_vshe.py:25` string-matches the literal `"SDC_seq_EFG_MUX_autoimport"`
   (currently dormant — commented out in the config) — names are preserved, so no change needed there.
5. **mea public-name registry:** `configs/amts.yml` lists `AMTS_exp`/`AMTS_seq`; `AMTS_seq.py` calls
   `epm.add("configure_leancat", ...)` (`:146`, `:414`) and
   `epm.add("configure_leancat_for_ADVENT_MEA", ...)` (`:658`) by string; `EXPERIMENTS`
   (`AMTS_exp.py:15-43`) lists both. Names and signatures unchanged.
6. **FastAPI operation ids** derive from endpoint function `__name__` — the priv route factory must
   set `__name__ = f"run_{name}"` and the original docstring on each generated handler so the OpenAPI
   schema is unchanged.

---

## 3. Behavior-equivalence harness (shared methodology)

All equivalence scripts live under `/tmp/p2_equiv/` (throwaway, never committed). Pattern per target:

1. **Capture twice, pre-change:** run the capture script two times; diff the two JSON outputs. Any
   field that differs between two identical runs is nondeterministic (e.g. a lazily-set timestamp) —
   record it in an explicit `EXCLUDE_FIELDS` list inside the script and strip it symmetrically. The
   remaining dump is the baseline.
2. **Refactor.**
3. **Compare:** re-run capture, strip the same `EXCLUDE_FIELDS`, and `diff` against the baseline.
   Byte-identical JSON required.

Serialization: pydantic models via `model_dump()` (fall back to `.dict()` on pydantic v1), then
`json.dumps(obj, sort_keys=True, indent=1, default=str)`.

Python is always `conda run -n helao python`, run from `/mnt/STORAGE/repos/helao/helao-async` unless
a task says otherwise. Global gate for every task: `conda run -n helao python run_unit_tests.py`
exits 0. Files whose transitive deps don't import on Linux are gated by
`conda run -n helao python -m py_compile <file>` instead of import.

---

## 4. Per-target transformation detail

### T1 — hte `specifications/` (parent repo)

**Files (before):** `helao/deploy/hte/specifications/{last2weeks.py, bimonthly.py, last3months.py}` —
110 lines each. `last2weeks.py` ≡ `bimonthly.py` byte-identical (`diff` exit 0); `last3months.py`
differs only in docstrings and `for i in range(2)` → `range(15)` (`lister`, line 46).

**Files (after):**

- **NEW `helao/deploy/hte/specifications/week_window.py`** — the entire current parser moved
  verbatim, with the window width lifted to a class attribute:

  ```python
  """Shared week-windowed sequence-zip specification parser."""
  import os, glob, inspect
  from datetime import datetime, timedelta
  from helao.helpers.specification_parser import BaseParser
  from helao.helpers.sequence_constructor import constructor
  from helao.helpers.helao_data import HelaoData
  from helao.helpers import helao_logging as logging

  LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


  class WeekWindowSpecParser(BaseParser):
      """Lister/parser for sequence zips collected over the last ``WEEKS`` weeks."""

      WEEKS: int = 2

      def __init__(self):
          self.PARAM_TYPES = {...}          # verbatim from current files

      def lister(self, folderpath: str) -> list:
          ...
          for i in range(self.WEEKS):       # was range(2) / range(15)
          ...                               # rest verbatim, incl. __manual_orch_seq__ filter + [:50]

      def list_params(self, specfile, orch) -> dict: ...   # verbatim
      def parser(self, specfile, orch, params={}, **kwargs): ...  # verbatim
  ```

- **Each existing file becomes a thin wrapper at the SAME path** (paths are the config contract —
  `seqspec_parser_path` values in ~12 configs across hte/priv point at these basenames):

  ```python
  """Specification parser that lists sequence zip files from the last 2 weeks. ..."""
  from helao.deploy.hte.specifications.week_window import WeekWindowSpecParser


  class SpecParser(WeekWindowSpecParser):
      """Lister/parser for sequence zips collected over the last two weeks."""
      WEEKS = 2
  ```

  `last2weeks.py` → `WEEKS = 2`; `bimonthly.py` → `WEEKS = 2` (**preserve current behavior — it is
  byte-identical to last2weeks today; do not "fix" to 8**); `last3months.py` → `WEEKS = 15`.
  Keep each file's original module/class docstrings.

**Why this preserves the contract:** loader (`bokeh_operator.py:325-332`) execs the file by path and
instantiates `module.SpecParser()` — still present, still no-arg, still a `BaseParser`. Absolute
import of `week_window` resolves via `PYTHONPATH` (repo root) exactly as `helao.helpers.*` already
does inside these files today.

**Equivalence check (`/tmp/p2_equiv/specs_check.py capture|compare`):** for each of the three files,
load via the exact production mechanism (`importlib.util.spec_from_file_location(basename, path)` +
`exec_module`), instantiate `SpecParser()`, then record to JSON: (a) `PARAM_TYPES` (as
`{name: type.__name__}`), (b) `lister(tmp_tree)` output, where `tmp_tree` is a synthetic folder tree
built by the script containing `YY.WW` week folders for each of the last 20 weeks (via the same
`(datetime.now() + timedelta(weeks=-i)).strftime("%y.%W")` formula), each holding 3 nested dummy
`*.zip` files plus one path containing `__manual_orch_seq__` (must be filtered out), and >50 total
zips inside the window to exercise the `[:50]` truncation. `list_params`/`parser` need a live orch —
they are covered by the verbatim-code-move rule plus diff review, not the harness.

### T2 — lila `sequences/SDC_seq.py` (nested repo `helao/deploy/lila`)

**The three variants (before):**

| Name | Line | Decorator | Distinguishing traits |
|------|------|-----------|----------------------|
| `SDC_seq_EFG_MUX_autoimport` | 3487 | `@sequence(version=4)` | EFG protocol only; dead commented pause block at the protocol slot |
| `SDC_seq_EFG_MUX_autoimport_PEIS_test` | 3972 | `@sequence(version=1)` | = A + one inserted `epm.add("SDC_prot_PEIS", ...)` before EFG; adds 6 PEIS params; ~10 default-value drifts vs A |
| `SDC_seq_EFG_MUX_autoimport_PEIS` | 4488 | `@sequence(version=1)` | = B with PEIS+EFG collapsed into a single `epm.add("SDC_prot_PEFG", ...)`; drops `plate_id` (hardcodes `1` at 5 sites) and drops all 21 protocol-tuning params (pins B's defaults as literals, incl. `5.5` at :4856) |

Everything else (MUX-electrolyte CSV lookup loop, unload→RHE-calibration opener, per-sample
movexy→MUX_valve→startup→protocol→drain→rinse→drain→unload chain, region_id-conditional rinse,
closing RHE calibration) is byte-identical across all three. All return `epm.planned_experiments`.

**After — one private core + three wrappers, all in `SDC_seq.py`:**

- **NEW private `_sdc_efg_mux_autoimport_core(...)`** (no `@sequence` decorator, NOT added to
  `__all__`): takes the **union** of A's and B's parameters (including `plate_id`) plus
  `protocol: str` in `{"efg", "peis_then_efg", "pefg"}`. Body = the shared chain, verbatim, with the
  protocol slot branching:
  - `"efg"` → `epm.add("SDC_prot_EFG", {...})` only (A's slot; the dead commented pause block may be
    kept as a comment in this branch or dropped — comments don't affect equivalence),
  - `"peis_then_efg"` → `epm.add("SDC_prot_PEIS", {...}, from_global_exp_params={"last_OCP_V": "ref_vshe"})`
    then `epm.add("SDC_prot_EFG", {...})` (B's slot),
  - `"pefg"` → single `epm.add("SDC_prot_PEFG", {merged dict})` (C's slot).
  Every payload value comes from core parameters — no literals that were parameters in any variant.
- **Three public wrappers keep the EXACT original `def` names, full original signatures with the
  original per-variant defaults, original `@sequence(version=…)` numbers (4/1/1), and original
  docstrings**, each delegating in one statement:

  ```python
  @sequence(version=4)
  def SDC_seq_EFG_MUX_autoimport(<A's exact 40+ params with A's exact defaults>):
      """<original docstring>"""
      return _sdc_efg_mux_autoimport_core(protocol="efg", plate_id=plate_id, <every param forwarded>)
  ```

  Wrapper C (`..._PEIS`) forwards its (smaller) signature and passes `plate_id=1` plus the pinned
  literal values it hardcodes today (`cp1_max_vrhethresh_stop_V=5.5`, `slope_analysis_start_s=180`,
  `finit_hz=100000.0`, etc. — the exact literal set catalogued in the body of the current C variant,
  which matches B's defaults) for every tunable it does not expose.
- `__all__`/`SEQUENCES` (`SDC_seq.py:11-37`) unchanged. `processors/append_ref_vshe.py` untouched
  (its literal match `"SDC_seq_EFG_MUX_autoimport"` still hits wrapper A).

**Signature invariants (hard):** real named parameters with defaults in every wrapper — the operator
UI and spec parsers introspect via `inspect.getfullargspec`. `**kwargs` forbidden. Do not fix the
pre-existing `stop_ce_pump: bool = "True"` type bug at `SDC_seq.py:2252` (different function, P3 item).

**Linux import workaround (pre-existing blocker):** module import fails on Linux because of the
module-level `MUX_ELEC_DF = pd.read_csv("C:/sdc_config/mux_electrolytes.csv")` (`SDC_seq.py:40-41`).
On Linux that forward-slash path is *relative*, so the harness runs from a scratch CWD containing a
literal `./C:/sdc_config/mux_electrolytes.csv` fixture:

```bash
mkdir -p /tmp/p2_equiv/lila/'C:'/sdc_config
cd /tmp/p2_equiv/lila
# executor: read the MUX lookup loop in SDC_seq.py to determine the required CSV columns,
# then write a fixture with rows covering the default mux_valve_no values plus one extra valve.
PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao --cwd /tmp/p2_equiv/lila python sdc_check.py capture
```

Verify the fixture makes `import helao.deploy.lila.sequences.SDC_seq` succeed **before** any edit;
the fixture is identical for capture and compare, so any fixture-shape imperfection cancels out.

**Equivalence check (`sdc_check.py capture|compare`):** for each of the three public functions, call
with (a) all defaults, and (b) one non-default combo (≥2 entries in `sample_no_list`/`xy_list`, a
`mux_valve_no` present in the fixture, and a `rinse_region_id` value that flips the conditional-rinse
branch). Dump `[m.model_dump() for m in fn(...)]` (`ShortExperimentModel` list — no uuids, fully
deterministic) to JSON; compare byte-identical after refactor (double-capture rule from §3 applies).

### T3 — mea `experiments/AMTS_exp.py` (nested repo `helao/deploy/mea`)

**Part A — `SampleModel` factory.** The block below is copy-pasted 29× (representative:
`AMTS_exp.py:317-325`; full site list at lines 317, 383, 413, 524, 554, 669, 902, 935, 1143, 1176,
1334, 1412, 1482, 1503, 1578, 1600, 1683, 1704, 1810, 1830, 1863, 1883, 1969, 2040, +…):

```python
SampleModel(**{
    "machine_name": gethostname().lower(),
    "global_label": mea_global_label,
    "sample_type": "MEA",
    "action_uuid": [],
    "etc": {"mea_supplier": mea_supplier, "mea_gdl_type": mea_gdl_type},
    "comment": comment,
})
```

Add one module-level factory and replace every inline construction:

```python
def _mea_sample(mea_global_label, mea_supplier, mea_gdl_type, comment) -> SampleModel:
    """Build the standard MEA sample record used in fast_samples_in."""
    return SampleModel(
        machine_name=gethostname().lower(),
        global_label=mea_global_label,
        sample_type="MEA",
        action_uuid=[],
        etc={"mea_supplier": mea_supplier, "mea_gdl_type": mea_gdl_type},
        comment=comment,
    )
```

Call sites become `"fast_samples_in": [_mea_sample(mea_global_label, mea_supplier, mea_gdl_type, comment)]`.
Also delete the ~13 dead `MEA_sample: SampleModel = SampleModel()` assignments (each declared once
near a function top and never referenced again — confirmed by grep). `_mea_sample` is NOT added to
`EXPERIMENTS`. Do not touch `deploy/mea/notes/**` (excluded), even though it contains a stale copy.

**Part B — `configure_leancat` (:691) vs `configure_leancat_for_ADVENT_MEA` (:983) common core.**
Diff-confirmed: identical 3-stage skeleton (`set_valves` → flow/temp stage A → flow/temp stage B →
`run_OCV` → `run_PEIS` → `set_valves`(air) → `set_pressure` → ORCH `wait` 60 s), but with REAL
divergences that must be preserved verbatim:
`wait_for_temperature` payloads (`targets` 4-key dict + `success_count: 1` vs flat `setpoint`, plus
`process_finish=True` only in ADVENT), `from_global_act_params={"_fast_samples_in": ...}` only in
`configure_leancat`'s stage-2 calls, `technique_name="set_pressure"` only in `configure_leancat`.

Therefore: extract into private module-level helpers **only the stages the diff proves byte-identical
modulo local variable names** — the `run_OCV`+`run_PEIS` tail (which also absorbs 4 of Part A's
`_mea_sample` sites) and, if byte-identical, the closing air-switch/pressure/wait block:

```python
def _leancat_ocv_peis(apm, *, OCV_duration_sec, samplerate_sec, versus_OCV,
                      OCV_duration__s, OCV_acquisition_period__s, Voffset__V, Vamp__V,
                      Finit__Hz, Ffinal__Hz, FrequenciesPerDecade, Zinit_expected_Ohm,
                      mea_global_label, mea_supplier, mea_gdl_type, comment):
    apm.add(PSTAT_server, "run_OCV", {... verbatim payload, samples via _mea_sample(...) ...}, ...)
    apm.add(PSTAT_server, "run_PEIS", {... verbatim ...}, ...)
```

Both public functions keep their exact names, signatures, defaults, `@experiment(version=1)`
decorators, and keep `apm = ActionPlanMaker()` as their first statement (**mandatory** — its
`__init__` reads the caller's frame args, `premodels.py:409-411`; helpers only receive the built
`apm`). Divergent steps (`set_valves`, `set_flow`, `set_temperature`, `wait_for_temperature`,
`set_pressure`) stay inline in each function, byte-for-byte. **Do NOT reconcile the
`wait_for_temperature` schemas** — logged as an open question. Do NOT touch the four commented-out
`configure_leancat_for_*` sibling defs (:2083, :2337, :2545, :2779) or `AMTS_seq.py`.

**Equivalence check (`/tmp/p2_equiv/mea_check.py capture|compare`):**
`import helao.deploy.mea.experiments.AMTS_exp` works on Linux (verified). The script iterates every
live name in `EXPERIMENTS`, calls each function with all-default args inside `try/except`, and
records `{name: [a.model_dump() for a in result]}` for successes plus the sorted list of names that
raised (with exception type). Requirements: the success/failure name sets are identical pre/post;
every successful dump is byte-identical (after §3's double-capture nondeterminism exclusion — blank
`Experiment()` fallback fields like timestamps are the likely candidates); `configure_leancat` and
`configure_leancat_for_ADVENT_MEA` MUST be in the success set.

### T4 — priv (nested repo `helao/deploy/priv`)

**Part A — dead-code deletion in `scripts/common/helao_nbio.py`.**

| Function | Lines | Verdict |
|----------|-------|---------|
| `extract_parts_old` | 274-304 | **KEEP — live** (callers: `scripts/icpms/convert_icpms_csv.py:174,177`; self-recursion :299) |
| `extract_parts` | 307-342 | **DELETE — dead** (only reference anywhere is its own recursion at :333) |
| `extract_parts_json` | 345-377 | **KEEP — live** (internal callers `helao_nbio.py:898,995`) |

Also delete the two stale commented-out import lines that name the deleted function:
`scripts/edax/converters.py:21` and `scripts/xafs/converters.py:22`
(`# from helao_nbio import extract_parts, ...`). Nothing else in `helao_nbio.py` changes in P2.

**Part B — `/run_<instrument>` route factory in `servers/action/batch_convert_server.py`**
(scope correction from the P2 sketch — the handlers are here, not in helao_nbio.py). Before: four
copy-pasted 4-line handlers at :387-405, each `@app.post("/run_<x>", tags=["private"])` wrapping
`return await _run_job("<x>")` inside `makeApp`. After — inside `makeApp`, at the same position:

```python
def _make_run_route(name: str, doc: str):
    async def _handler():
        return await _run_job(name)
    _handler.__name__ = f"run_{name}"      # preserves FastAPI operationId
    _handler.__doc__ = doc                 # preserves OpenAPI description
    app.post(f"/run_{name}", tags=["private"])(_handler)

for _name, _doc in (
    ("bruker", "Convert every currently unprocessed Bruker XRD source folder."),
    ("edax",   "<original run_edax docstring verbatim>"),
    ("xafs",   "<original run_xafs docstring verbatim>"),
    ("icpms",  "<original run_icpms docstring verbatim>"),
):
    _make_run_route(_name, _doc)
```

Fixed 4-name tuple (NOT `JOB_MODULES.keys()`); identical paths, tag, docstrings, operation ids,
and responses — including the current `/run_edax` behavior (always returns the "not available"
error because `"edax"` is commented out of `JOB_MODULES` at :52-61; preserved as-is, open question).
No change to `_run_job`, `JOB_MODULES`, `_summarize`, or `/run_directory`.

**Equivalence check:** `py_compile` both files; import parity (`import
helao.deploy.priv.scripts.common.helao_nbio` succeeds on Linux — verified pre-change — and must
still succeed; attempt `import helao.deploy.priv.servers.action.batch_convert_server` pre-change:
if it imports on Linux it must still import, otherwise its gate is `py_compile` only); grep
route-string preservation (see task table); grep-zero for the deleted symbol:
`grep -rnw "extract_parts" helao/deploy/priv --include='*.py'` must return only `extract_parts_old`
/ `extract_parts_json` hits.

---

## 5. Task table

Groups: **A = P2-01…P2-04, fully parallel** (disjoint by repo: parent/lila/mea/priv — zero shared
files). **P2-05 serial-post.** Executors: Sonnet. Each task captures its own baseline BEFORE editing,
edits, compares, then commits **its own repo** (nested repos committed from inside their directory —
they are invisible to parent git). Baseline scripts stay in `/tmp/p2_equiv/`, never committed.

| ID | Title | Repo | Files | Depends on | Group | Verification (all must pass) |
|----|-------|------|-------|-----------|-------|------------------------------|
| P2-01 | hte spec parsers → `WeekWindowSpecParser` + 3 thin wrappers | parent | `helao/deploy/hte/specifications/{week_window.py (NEW), last2weeks.py, bimonthly.py, last3months.py}` | — | A | `conda run -n helao python /tmp/p2_equiv/specs_check.py capture` (×2, pre-edit) then `... compare` byte-identical (the script itself performs the production-style file-location load + `SpecParser()` instantiation of each of the 3 files, so load success is part of the gate); `conda run -n helao python -c "import helao.deploy.hte.specifications.week_window"`; `conda run -n helao python run_unit_tests.py`; `ls` confirms all 3 original paths still exist; commit on parent `feat/cards-refactor` |
| P2-02 | lila SDC triple sequences → `_sdc_efg_mux_autoimport_core` + 3 wrappers | lila | `helao/deploy/lila/sequences/SDC_seq.py` | — | A | build CSV fixture; from `/tmp/p2_equiv/lila`: `PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao python sdc_check.py capture` (×2) then `... compare` byte-identical (defaults + non-default combo per function); `conda run -n helao python -m py_compile helao/deploy/lila/sequences/SDC_seq.py`; `grep -n "SDC_seq_EFG_MUX_autoimport" helao/deploy/lila/sequences/SDC_seq.py` shows all 3 names in `__all__` and as `def`s; `grep -c getfullargspec`-introspectable: no `**kwargs` in the 3 wrapper signatures; `conda run -n helao python run_unit_tests.py`; commit inside `helao/deploy/lila` |
| P2-03 | mea `_mea_sample` factory + leancat common-stage extraction | mea | `helao/deploy/mea/experiments/AMTS_exp.py` | — | A | `conda run -n helao python /tmp/p2_equiv/mea_check.py capture` (×2) then `... compare`: identical success/failure sets + byte-identical dumps, `configure_leancat*` both in success set; `conda run -n helao python -c "import helao.deploy.mea.experiments.AMTS_exp"`; `grep -n 'SampleModel(' helao/deploy/mea/experiments/AMTS_exp.py` → only the factory + type annotations remain (no inline `SampleModel(**{` blocks, no `= SampleModel()` dead inits); `EXPERIMENTS` list unchanged (`git diff` shows no edits in lines 15-43); `conda run -n helao python run_unit_tests.py`; commit inside `helao/deploy/mea` |
| P2-04 | priv: delete dead `extract_parts`; `/run_*` route factory | priv | `helao/deploy/priv/scripts/common/helao_nbio.py`, `helao/deploy/priv/scripts/edax/converters.py`, `helao/deploy/priv/scripts/xafs/converters.py`, `helao/deploy/priv/servers/action/batch_convert_server.py` | — | A | `conda run -n helao python -m py_compile` all 4 files; `conda run -n helao python -c "import helao.deploy.priv.scripts.common.helao_nbio"`; batch_convert_server import-parity rule (§4 T4); `grep -n '"/run_bruker"\|"/run_edax"\|"/run_xafs"\|"/run_icpms"\|f"/run_{' helao/deploy/priv/servers/action/batch_convert_server.py` confirms all 4 paths still constructed; `grep -rnw extract_parts helao/deploy/priv --include='*.py'` → zero bare-name hits; `conda run -n helao python run_unit_tests.py`; commit inside `helao/deploy/priv` |
| P2-05 | Whole-tree verification sweep + config-reference check + push | all | — | P2-01…04 | serial-post | §6 script below; then push parent + lila + mea + priv `feat/cards-refactor` branches |

Shared-file contention: none — the four group-A tasks touch four disjoint repos, and within each
repo a single task owns every touched file. If a hotfix lands on `unstable` mid-flight, rebase the
parent branch before P2-05 (nested repos are unaffected).

---

## 6. "No config references broke" — explicit verification (run in P2-05)

```bash
cd /mnt/STORAGE/repos/helao/helao-async

# 0) Global gate
conda run -n helao python run_unit_tests.py

# 1) hte/priv spec-parser paths: every config-referenced spec basename still exists and defines SpecParser
grep -rn "seqspec_parser_path" helao/deploy/hte/configs helao/deploy/priv/configs
ls helao/deploy/hte/specifications/last2weeks.py \
   helao/deploy/hte/specifications/bimonthly.py \
   helao/deploy/hte/specifications/last3months.py
grep -l "class SpecParser" helao/deploy/hte/specifications/{last2weeks,bimonthly,last3months}.py  # all 3

# 2) lila: public sequence names still defined and exported; processor literal still matches
grep -n 'def SDC_seq_EFG_MUX_autoimport\b\|def SDC_seq_EFG_MUX_autoimport_PEIS_test\b\|def SDC_seq_EFG_MUX_autoimport_PEIS\b' \
    helao/deploy/lila/sequences/SDC_seq.py                       # 3 hits
grep -n '"SDC_seq_EFG_MUX_autoimport"' helao/deploy/lila/sequences/SDC_seq.py \
    helao/deploy/lila/processors/append_ref_vshe.py              # __all__ + processor hit intact

# 3) mea: string-called experiment names still defined + registered
grep -n 'def configure_leancat\b\|def configure_leancat_for_ADVENT_MEA\b' \
    helao/deploy/mea/experiments/AMTS_exp.py                     # 2 hits
grep -n '"configure_leancat"\|"configure_leancat_for_ADVENT_MEA"' \
    helao/deploy/mea/experiments/AMTS_exp.py helao/deploy/mea/sequences/AMTS_seq.py  # EXPERIMENTS + epm.add sites

# 4) priv: HTTP routes preserved; dead symbol gone; live symbols intact
grep -n 'run_bruker\|run_edax\|run_xafs\|run_icpms' helao/deploy/priv/servers/action/batch_convert_server.py
grep -rnw 'extract_parts' helao/deploy/priv --include='*.py'     # only _old/_json variants remain
grep -n 'extract_parts_old' helao/deploy/priv/scripts/icpms/convert_icpms_csv.py  # caller untouched

# 5) dbpack untouched (frozen per decision)
git diff --stat feat/cards-refactor -- helao/deploy/hte/drivers/data/dbpack_driver.py \
    helao/deploy/hte/servers/action/dbpack_server.py             # empty

# 6) Duplication actually killed
diff helao/deploy/hte/specifications/last2weeks.py helao/deploy/hte/specifications/bimonthly.py | head -5
    # now differ ONLY in docstrings (both WEEKS = 2), and each file is <~20 lines
wc -l helao/deploy/hte/specifications/*.py helao/deploy/lila/sequences/SDC_seq.py
```

Per-repo commit inventory check: `git -C . log --oneline -1`, `git -C helao/deploy/lila log --oneline -1`,
`git -C helao/deploy/mea log --oneline -1`, `git -C helao/deploy/priv log --oneline -1` — one P2
commit each; then push all four.

---

## 7. Risk / rollback notes

- **No behavior change by construction + by measurement.** Every wrapper reproduces the exact
  serialized payloads (captured baselines, double-capture nondeterminism exclusion). The three
  highest-risk semantic traps are each closed by a specific rule: (1) `ActionPlanMaker` frame
  inspection → the constructor never moves out of the public mea functions; (2) signature
  introspection by the operator UI / spec parsers → wrappers keep real named params with original
  defaults, no `**kwargs`; (3) FastAPI operationIds → factory sets `__name__`/`__doc__`.
- **hte production exposure: minimal by design.** Only `specifications/*.py` change — loaded solely
  by the operator Bokeh UI, `py`/import-gated, and behavior-pinned by the lister harness. No driver,
  server, or control-path file in hte is touched; dbpack frozen.
- **lila C-variant literal pinning:** wrapper C must pass the exact literals the current body pins
  (they equal B's defaults, incl. the `5.5` at :4856, NOT A's `-1/200/100` values) — the baseline
  compare catches any slip. The dormant `append_ref_vshe.py` literal-match survives because names
  never change.
- **mea leancat divergences are load-bearing until proven otherwise:** the `targets`-vs-`setpoint`
  `wait_for_temperature` schemas stay verbatim; only diff-proven-identical stages are extracted. If
  the executor's diff shows a stage is NOT byte-identical (beyond local-variable naming), it stays
  inline — when in doubt, extract less.
- **priv `/run_edax` stays a silent no-op** (registry-disabled) — deliberately preserved; changing it
  is a behavior decision for the owner.
- **Baseline-first discipline:** if any capture script cannot be made to run pre-change (e.g. the
  lila CSV fixture columns can't be satisfied), the task STOPS and reports — do not refactor without
  a working baseline. `py_compile` alone is only an acceptable gate where the plan explicitly says so.
- **Rollback:** one commit per repo, no cross-repo dependency (unlike Increment 1, P2 introduces no
  shared parent-repo module consumed by nested repos — `week_window.py` is consumed only by hte files
  in the same parent repo). Any repo can be `git revert`ed independently. Pre-push, a branch reset of
  the single P2 commit fully restores the previous state.
- **Deployed stations are unaffected until merge:** stations run their deployed branches; hot-reload
  watches those branches, not `feat/cards-refactor`.

---

## 8. Open questions (appended to `.omc/plans/open-questions.md`)

- dbpack retirement — DEFERRED in P2 (frozen); needs ~10 hte YAML config sweep + station sign-off.
- `bimonthly.py` behaves as a 2-week window (byte-identical to last2weeks); intended ~8? Behavior
  decision for the hte owner; P2 preserves `WEEKS = 2`. (Also: no hte config currently references
  `bimonthly.py` — retire the file entirely?)
- mea `wait_for_temperature` payload divergence (`targets`+`success_count` vs flat `setpoint`) —
  latent bug or two supported schemas? Blocks any future unification of `configure_leancat*`.
- priv `/run_edax` permanently returns "not available" (edax disabled in `JOB_MODULES`); and
  `xrfs_quant`/`xrfs_cal` jobs have no dedicated routes — retire the route or derive routes from the
  registry? (behavior change, owner decision).
- priv `extract_parts_old`: misleading name + shallow recursion (re-loads the same top-level meta
  instead of descending into parts) — rename/fix in a later phase with icpms owner sign-off.
- lila `SDC_seq_EFG_MUX_autoimport_PEIS` hardcodes `plate_id=1` — expose as a param later? (signature
  change → operator-visible; not P2).
- lila `stop_ce_pump: bool = "True"` (`SDC_seq.py:2252`) — still deferred to P3 (P1 carry-over).
