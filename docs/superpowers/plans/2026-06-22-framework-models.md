# Framework Models Implementation Plan (Sub-project 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Port the pure pydantic data models from `helao/core/models/` into `helao/framework/models/` (plus their support deps), cleaned per the SP1 spec, with ≥90% pytest coverage on `models/`.

**Architecture:** Pure pydantic v2 models in the hexagonal `models/` layer. No runtime/premodels behavior, no I/O, no imports outside `helao.framework.*`. See spec `docs/superpowers/specs/2026-06-22-framework-models-design.md`.

**Tech Stack:** Python 3.12 (helao conda env), pydantic v2, pytest.

---

## Conventions (read first)

- **helao conda env only:** prefix every command with `conda run -n helao` (e.g. `conda run -n helao python -m pytest`). Never OS python. `conda run` prints a cosmetic `ERROR conda.cli.main_run` on non-zero exit; ignore it.
- **Branch:** `feat/framework-scaffold` (models fold into the scaffold PR per user decision). Confirm with `git branch --show-current`. Never commit to `unstable`/`main`.
- **No private-deployment names** in any added file.
- **Porting rule for every model file:** copy the class definitions from the source file in `helao/core/models/<name>.py`, then apply the cleanups below. Do NOT invent new fields or rename serialized fields. The "exact code" is the source file; your job is a faithful, cleaned port.

**Cleanups to apply to every ported model (SP1 spec §4):**
1. Rewrite imports to `helao.framework.models.*` / `helao.framework.support.*`. Never import `helao.core.*` or `helao.helpers.*`.
2. No module-level or default-factory side effects (no `gethostname()`, no network/fs). If a default needs runtime data, make it a plain field defaulting to `None`.
3. No dependency on any runtime/premodels class. Where a model references `Action`, use the pure `ActionModel`/`ShortActionModel` (or a `typing.TYPE_CHECKING` import if only used as an annotation).
4. Pydantic v2 hygiene: explicit `Optional[...] = None`; `Field(default_factory=...)` for mutable defaults; `model_config = ConfigDict(...)` instead of v1 `class Config`.
5. Keep field names, types, and serialization identical (on-disk byte-compatibility invariant).

**Verification after every task:** `conda run -n helao python run_framework_tests.py` stays green, and the AST boundary test still passes.

---

## Task 1: Port support dependencies (errors, HelaoDict, version)

**Files:**
- Create: `helao/framework/models/errors.py` (from `helao/core/error.py`)
- Create: `helao/framework/models/helao_dict.py` (from `helao/core/helaodict.py`)
- Create: `helao/framework/support/version.py` (from `helao/core/version.py`)
- Test: `helao/framework/tests/test_models_support.py`

- [ ] **Step 1: Read the three source files** `helao/core/error.py`, `helao/core/helaodict.py`, `helao/core/version.py` to learn their exact contents.

- [ ] **Step 2: Write failing tests** in `test_models_support.py`:
  - `ErrorCodes` is an enum/str-enum with a `none`/success member and at least the members referenced by deployments (e.g. `none`, `critical`, `timeout`); assert a couple of known members exist and round-trip by value.
  - `HelaoDict` mixin: a tiny pydantic model mixing it in produces the expected dict via its serialization method (mirror the behavior in `helao/core/tests/unit_test_helaodict.py`).
  - `get_hlo_version()` returns the expected version string/constant.
  Run: `conda run -n helao python -m pytest helao/framework/tests/test_models_support.py` → FAIL (modules missing).

- [ ] **Step 3: Port the three modules** applying the cleanup rules. `errors.py` and `helao_dict.py` go under `models/`; `version.py` under `support/`. Fix internal imports to framework paths.

- [ ] **Step 4: Run tests** → PASS.

- [ ] **Step 5: Commit** `git commit -m "feat(framework): port ErrorCodes, HelaoDict, version helper"`

---

## Task 2: Port leaf models (no model-to-model deps)

These import at most `helao_dict`/`version`/`errors` (now available): `action_start_condition`, `credentials`, `electrolyte`, `hlostatus`, `orchstatus`, `process_contrib`, `run_use`, `s3locator`, `helaodirs`, `machine`, `server`, `data`.

**Files:**
- Create: `helao/framework/models/<name>.py` for each of the 12 modules above (port from `helao/core/models/<name>.py`).
- Test: `helao/framework/tests/test_models_leaf.py`

- [ ] **Step 1: Read** each source file under `helao/core/models/` for the 12 modules.

- [ ] **Step 2: Write failing tests** in `test_models_leaf.py` — for each module, at minimum: construct the primary model with valid data, assert key fields/defaults, and assert one validation rule (e.g. an enum rejects a bad value, a required field raises). Mirror any assertions already in `helao/core/tests/unit_test_extra_models.py` that cover these. Run → FAIL.

- [ ] **Step 3: Port** all 12 modules with cleanups. Resolve any cross-references among them to framework paths.

- [ ] **Step 4: Run tests** → PASS. Confirm AST boundary test still green.

- [ ] **Step 5: Commit** `git commit -m "feat(framework): port leaf data models"`

---

## Task 3: Port composite models (sample, file, process, analysis)

**Files:**
- Create: `helao/framework/models/{sample,file,process,analysis}.py`
- Test: `helao/framework/tests/test_models_sample.py` (this is also the home for the ported sample unit test)

- [ ] **Step 1: Read** `helao/core/models/{sample,file,process,analysis}.py` and `helao/core/tests/unit_test_sample_models.py`.

- [ ] **Step 2: Port `unit_test_sample_models.py` into `test_models_sample.py`** as real pytest tests (one assertion per behavior; convert the `def *_unit_test() -> bool` + prints into `def test_*` + `assert`). Add tests for `file`/`process`/`analysis` primary models (construct + validate). Run → FAIL (model modules missing).

- [ ] **Step 3: Port** `sample.py`, `file.py`, `process.py`, `analysis.py` with cleanups. `sample.py` is the largest (494 LOC) — port faithfully including the sample-type union and `get_global_label`-style helpers (these are pure methods on the data model and stay).

- [ ] **Step 4: Run tests** → PASS.

- [ ] **Step 5: Commit** `git commit -m "feat(framework): port sample/file/process/analysis models + sample tests"`

---

## Task 4: Port sequence / experiment / action model bases

These are the `SequenceModel`, `ExperimentModel`, `ActionModel` + `Short*` views. **Only the pydantic model bases** — NOT the runtime `Sequence`/`Experiment`/`Action` wrappers (those are SP4/SP5).

**Files:**
- Create: `helao/framework/models/{sequence,experiment,action}.py`
- Test: `helao/framework/tests/test_models_aes.py`

- [ ] **Step 1: Read** `helao/core/models/{sequence,experiment,action}.py`. Note any cross-imports (e.g. action referencing machine/sample/file) and the `from helao.helpers.premodels import Action` coupling flagged in the spec.

- [ ] **Step 2: Write failing tests** in `test_models_aes.py`: construct `SequenceModel`, `ExperimentModel`, `ActionModel` and their `Short*` views with valid data; assert defaults, required fields, and that `model_dump()` round-trips. Add a regression test asserting `action.py` has NO import of any premodels/runtime class. Run → FAIL.

- [ ] **Step 3: Port** the three modules. **Break the circular import** (spec §4.1): replace `from helao.helpers.premodels import Action` with the pure model type or a `TYPE_CHECKING` import. Confirm no `helao.core`/`helao.helpers` imports remain.

- [ ] **Step 4: Run tests** → PASS. Run the AST boundary test and a grep proving no `helao.core`/`helao.helpers` imports under `helao/framework/models/`.

- [ ] **Step 5: Commit** `git commit -m "feat(framework): port sequence/experiment/action model bases"`

---

## Task 5: Port remaining extra-model tests + close coverage to ≥90%

**Files:**
- Create: `helao/framework/tests/test_models_extra.py` (from `helao/core/tests/unit_test_extra_models.py`)
- Modify: any model whose coverage is below target (add tests, not code, unless a real gap surfaces).

- [ ] **Step 1: Port `unit_test_extra_models.py`** into `test_models_extra.py` as pytest assertions.

- [ ] **Step 2: Run the coverage gate** `conda run -n helao python run_framework_tests.py`. Read the per-file coverage in `.framework-cov.json`.

- [ ] **Step 3: For each `models/` file below 90%,** add targeted tests exercising the uncovered branches (validators, helper methods, `Short*` conversions). Re-run until the gate reports `models` ≥90% and prints PASS.

- [ ] **Step 4: Commit** `git commit -m "test(framework): port extra-model tests; models coverage >=90%"`

---

## Task 6: Final verification

- [ ] **Step 1:** `conda run -n helao python run_framework_tests.py` → all tests pass, gate PASS (domain still empty/vacuous; models ≥90%).
- [ ] **Step 2:** Prove purity — `grep -rE "from helao\.(core|helpers)" helao/framework/models/` returns nothing.
- [ ] **Step 3:** AST boundary test passes (`models/` imports only framework).
- [ ] **Step 4:** No private-deployment names — `git diff unstable --name-only | xargs grep -niE "lila|lila_gl|\\bmea\\b|\\bpriv\\b"` (ignore matches inside the plan/spec docs' own grep commands).
- [ ] **Step 5:** `git log --oneline unstable..HEAD` shows the models commits stacked on the scaffold commits.

---

## Self-review notes

- Delivers SP1 spec §3 (all 19 models + 3 support deps ported), §4 (cleanups: framework-only imports, no I/O side effects, broken premodels circular import, pydantic v2 hygiene), §5 (both legacy model tests ported to pytest, ≥90% models coverage).
- Correctly OUT of scope: runtime Sequence/Experiment/Action wrappers, PlanMakers, inheritance flatten-vs-keep (SP4/SP5).
- All commands use `conda run -n helao`. No private-deployment names.
