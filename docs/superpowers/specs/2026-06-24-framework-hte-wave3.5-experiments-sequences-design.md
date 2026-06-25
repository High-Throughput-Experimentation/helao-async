# Framework hte Migration — Wave 3.5: experiments + sequences (design)

**Date:** 2026-06-24
**Branch:** `feat/framework-hte-wave3.5-exp-seq`
**Cycle:** Gated hte production migration. **Newly discovered prerequisite** for the Wave 4
config cut-over — surfaced by the canary Gate B launch.

## 1. Why this wave exists (root cause)

The original wave plan (1 drivers, 2 action servers, 3 vis/operators, 4 configs) **omitted
the experiment and sequence libraries** (`helao/deploy/hte/{experiments,sequences}/`, 31
files). They still import from `helao.helpers`/`helao.core`, including the **legacy**
`@experiment`/`@sequence` decorators.

When the canary config cut ORCH over to the framework orchestrator, running an experiment
crashed:

```
TypeError: orch_sub_wait() got multiple values for argument 'wait_time_s'
```

Reproduced headlessly via `expansion.unpack_experiment`. Root cause: the framework orch
dispatches an experiment by `exp_func(experiment, **params)`, passing a framework
`RunExperiment` positionally. The **framework** `@experiment` decorator
(`helao.framework.support.lib_decorators`) strips that positional for exp-free functions
(duck-typing on `experiment_name`) and publishes it on `EXPERIMENT_CTX`. The **legacy**
decorator (`helao.helpers.lib_decorators`) only recognizes legacy `Experiment` objects, so
it neither strips the framework experiment nor sets the framework context var → the
experiment object binds to the first real parameter → "multiple values".

The `test` deployment already migrated its experiment/sequence libs to the framework
decorator; hte never did. This wave closes that gap.

## 2. Scope

All 31 files under `helao/deploy/hte/experiments/` + `helao/deploy/hte/sequences/` that
import `helao.helpers`/`helao.core`. Pure import-path rewrite — **no logic changes** —
except the symbol-aware `premodels` split (below). No `helao/core/**`, no
`helao/framework/**` (all target symbols already exist — verified), no configs, no other
`helao/deploy/hte/**`.

## 3. Import mapping (every target symbol verified present; mirrors the `test` deployment)

| legacy import | framework |
|---|---|
| `from helao.helpers.lib_decorators import experiment` | `from helao.framework.support.lib_decorators import experiment` |
| `from helao.helpers.lib_decorators import sequence` | `from helao.framework.support.lib_decorators import sequence` |
| `from helao.helpers.premodels import Experiment, ActionPlanMaker` | **SPLIT** into two lines: `from helao.framework.domain.run_models import RunExperiment as Experiment` **and** `from helao.framework.domain.plan_makers import ActionPlanMaker` |
| `from helao.helpers.premodels import ExperimentPlanMaker` | `from helao.framework.domain.plan_makers import ExperimentPlanMaker` |
| `from helao.helpers.premodels import Sequence` (if present) | `from helao.framework.domain.run_models import RunSequence as Sequence` |
| `from helao.core.models.machine import MachineModel [as MM]` | `from helao.framework.models.machine import MachineModel [as MM]` (preserve any `as` alias) |
| `from helao.core.models.process_contrib import ProcessContrib` | `helao.framework.models.process_contrib` |
| `from helao.core.models.sample import SolidSample, LiquidSample, GasSample` | `helao.framework.models.sample` (preserve the imported-name list, incl. multi-line form) |
| `from helao.core.models.electrolyte import Electrolyte` | `helao.framework.models.electrolyte` |
| `from helao.core.models.action_start_condition import ActionStartCondition [as asc]` | `helao.framework.models.action_start_condition` (preserve any `as` alias) |
| `from helao.core.models.run_use import RunUse` | `helao.framework.models.run_use` |
| `from helao.helpers.constants import REF_TABLE / SPECSRV_MAP / SPEC_MAP` | `helao.framework.support.constants` |
| `from helao.helpers import config_loader` | `from helao.framework.support import config_loader` |
| `from helao.helpers import helao_logging as logging` | `from helao.framework.support import helao_logging as logging` |

**Rules:** preserve every imported symbol list and `as` alias exactly — only the module
path (and the premodels split) changes. A commented-out import stays commented out
verbatim. If a file imports a `helao.core`/`helao.helpers` target NOT in this table, STOP
and report rather than guess.

## 4. Test strategy

1. **Regression test** (the bug): `helao/framework/tests/test_hte_experiment_expansion.py`
   — load `power_supply_test` config, import `samples_exp`, build a `RunExperiment`
   named `orch_sub_wait` with `experiment_params={"wait_time_s": 3}`, call
   `expansion.unpack_experiment(...)`, and assert it returns a non-empty action list with
   the ORCH `wait` action and does NOT raise. (Pre-fix this raises the "multiple values"
   TypeError; post-fix it passes.)
2. **Import smoke**: extend/add a test importing every migrated experiment + sequence
   module (skip cleanly on any vendor/hardware dep), asserting the module imports and that
   `orch_sub_wait.experiment_version == 2` (decorator applied).
3. Full framework suite + boundary stay green.

## 5. Done criteria

- 31 files migrated per the table; the `premodels` line correctly split everywhere.
- The regression test passes (crash gone); import smoke green for all 31.
- Residual `helao.core`/`helao.helpers` in the 31 files = none (except commented lines).
- Full suite + boundary green. Scope: only the 31 files + the two tests + this doc.
