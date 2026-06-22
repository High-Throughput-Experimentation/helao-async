# Framework Models — Design Spec (Sub-project 1)

**Date:** 2026-06-22
**Status:** Approved (standing authorization)
**Parent spec:** `docs/superpowers/specs/2026-06-22-helao-framework-core-rewrite-design.md` (§4.5)
**Branch:** folded into `feat/framework-scaffold` (per user: one PR covering scaffold + models)

---

## 1. Goal

Port the deployment-agnostic pydantic **data models** from `helao/core/models/` into `helao/framework/models/` as clean, pure, well-validated schemas, and seed `models/` test coverage to the ≥90% gate. This is the second sub-project of the framework rewrite; it depends only on the scaffold (#0).

## 2. Scope decision: data models only; runtime classes deferred

Parent spec §4.5 said to "merge in the premodels runtime classes so the domain model is unified." On inspection, the `premodels` classes (`Sequence`, `Experiment(Sequence, ExperimentModel)`, `Action(Experiment, ActionModel)`, `ActionPlanMaker`, `ExperimentPlanMaker`) are **runtime builder behavior**, not data:

- `Action.init_act()` calls inherited `init_seq()`/`init_exp()`, reads `self.sequence_timestamp`/`self.experiment_*`, and auto-promotes manual actions.
- `ActionPlanMaker.add()` builds `Action(**experiment.as_dict())`, frame-inspects the caller, and assigns UUIDs/timestamps/output dirs.
- These do I/O-adjacent work (wall clock via `set_time`, `gen_uuid`, `gethostname`, `inspect.currentframe`).

The `Action(Experiment(Sequence))` multiple-inheritance **is load-bearing**: it denormalizes parent provenance onto each action so actions dispatch standalone with full identity. That coupling is a *runtime* concern.

**Decision:** SP1 ports only the **pure pydantic data schemas** (`SequenceModel`, `ExperimentModel`, `ActionModel`, their `Short*` views, and all supporting models). The runtime `Sequence`/`Experiment`/`Action` wrappers, the `PlanMaker`s, and the **flatten-vs-keep-inheritance decision** are deferred to the domain sub-projects (SP4 action-lifecycle / SP5 orchestration), where the behavior is rebuilt as pure domain logic returning command/result objects. This keeps SP1 low-risk and mechanical, and makes the inheritance call with full context of the action lifecycle rather than prematurely.

## 3. What gets ported

All 19 modules under `helao/core/models/` → `helao/framework/models/`, as pure pydantic v2 models:

`action`, `action_start_condition`, `analysis`, `credentials`, `data`, `electrolyte`, `experiment`, `file`, `helaodirs`, `hlostatus`, `machine`, `orchstatus`, `process`, `process_contrib`, `run_use`, `s3locator`, `sample`, `sequence`, `server`.

**Supporting framework pieces this sub-project must also bring over** (models depend on them):
- `ErrorCodes` (from `helao/core/error.py`) → `helao/framework/models/errors.py`. Canonical error vocabulary (parent spec §6); imported 70× by deployments.
- `HelaoDict` mixin (from `helao/core/helaodict.py`) → `helao/framework/models/helao_dict.py`. Base mixin many models use for dict serialization.
- HLO version helper (from `helao/core/version.py`) → `helao/framework/support/version.py` (it is a generic utility, not a model).

## 4. Cleanups (what "rewrite, not copy" means here)

1. **Break the data→runtime circular import.** A current model imports `from helao.helpers.premodels import Action`. The ported model must not depend on any runtime/premodels class. Replace with the pure model type (`ActionModel`/`ShortActionModel`) or a `TYPE_CHECKING`-only import, whichever the field actually needs.
2. **Remove impurity from models.** No `gethostname()` / network / filesystem calls executed at model definition or default-factory time. If a default needs the hostname, accept it as a field with an explicit caller-supplied value (the runtime layer provides it later), not a module-level side effect.
3. **Pydantic v2 hygiene.** Use `model_config`/`Field` consistently; replace any deprecated v1 patterns; make optional fields explicitly `Optional[...] = None`; drop fields confirmed dead (only after grep shows no deployment reads them — otherwise keep and note).
4. **Internal imports only within the new package.** Ported models import from `helao.framework.models.*` / `helao.framework.support.*`, never from `helao.core.*` or `helao.helpers.*`.
5. **Keep field names and serialization byte-compatible.** Parent-spec invariant: on-disk HLO/meta JSON must not change. Renames of serialized fields are out of scope.

## 5. Testing

- Port `helao/core/tests/unit_test_sample_models.py` and `unit_test_extra_models.py` (callable-style, return bool) into `helao/framework/tests/` as real pytest tests (`test_models_sample.py`, `test_models_extra.py`), one assertion per behavior.
- Add focused pytest modules per model file as needed to reach the gate.
- **Coverage gate:** `run_framework_tests.py` must report ≥90% on `helao/framework/models/` (the gate already enforces domain+models; models now has statements, so this becomes a real bar).
- The AST boundary test continues to pass (models import only models/support, never adapters/app/web).

## 6. Out of scope

- Runtime `Sequence`/`Experiment`/`Action` wrapper classes and `ActionPlanMaker`/`ExperimentPlanMaker` (→ SP4/SP5 domain).
- The `Action(Experiment(Sequence))` inheritance flatten-vs-keep decision (→ SP4/SP5, with action-lifecycle context).
- Any deployment migration; old `helao/core/models` stays in place untouched.
- Changing serialized field names or on-disk formats.

## 7. Risks

| Risk | Mitigation |
|---|---|
| Hidden coupling between models and core/helpers | Port leaf models first; AST boundary test + import-only-within-package rule catch leaks |
| Dropping a field deployments rely on | Only drop after grep across `helao/deploy` shows zero readers; otherwise keep + comment |
| Serialization drift | Keep field names/types; port the existing model tests first as a regression net |
