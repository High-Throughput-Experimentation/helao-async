# Framework hte Migration — Wave 0: Dependency Audit + Gap Close (design)

**Date:** 2026-06-24
**Branch:** `feat/framework-hte-wave0-gaps`
**Cycle:** Gated hte production migration (Wave 0; see
`2026-06-24-framework-hte-production-migration-plan.md`). **No hte edits** — pure
framework-side work + the audit artifact. Satisfies the plan's **Gate A**.

## 1. Audit method

Enumerated every `helao.core.*` / `helao.helpers.*` import target across
`helao/deploy/hte/servers/` + `helao/deploy/hte/drivers/` (43 server + 31 driver
files), deduped to 44 module targets, and mapped each to a framework home (exists)
or a gap. Result: **35 already have framework homes, 9 gaps.**

## 2. Audit result

### 2.1 Already in the framework (35) — no work

models (`action/analysis/data/file/hlostatus/orchstatus/process/run_use/sample`,
`error`→`models/errors`, `helaodict`→`models/helao_dict`); servers
(`base`/`base_api`→`app/base_api`, `orch_api`→`app/orch_api`, `vis`→`app/vis`,
`vis_subscriber`→`adapters/vis_subscriber`, `data_browser`→`app/data_browser`,
`operator.bokeh_operator`→`app/operator/bokeh_operator`,
`operator.helao_operator`→`adapters/helao_operator`,
`operator.orch_backend`→`ports/operator_backend`); drivers
(`helao_driver`→`ports/driver`, `data.sync_driver`→`app/sync_driver`,
`data.loaders.helao_loader`→`adapters/loaders/hlo_loader`, `data.enum`→`models/run_use`);
helpers (`config_loader`, `dispatcher`, `file_utils`, `make_str_enum`, `time_utils`,
`yml_tools` → `support/*`; `executor`→`domain/executor`; `premodels`→`domain/run_models`;
`hlo_data`→`adapters/loaders/hlo_loader`; `version`→`support/version`).

> **Symbol-level caveat (for later waves, not Wave 0):** module existence ≠ symbol
> parity. Three "exists" mappings need a symbol check during the action-server wave:
> `premodels` (hte uses `Sequence`/`Experiment`/`Action`/`ActionPlanMaker`/
> `ExperimentPlanMaker`; framework split these into `run_models` + `domain/plan_makers`),
> `executor` (legacy `helpers.executor.Executor` base vs framework `domain/executor`),
> and `base`/`base_api` (`Base`/`BaseAPI` surface). SP7 covered the common surface on
> `test`; hte may use more. Reconcile per-server in Wave 2.

### 2.2 Gaps (9) — port / seam decision

| Gap | LOC | hte files | Decision | Target |
|---|---|---|---|---|
| `helpers.bubble_detection` | 141 | 2 | **PORT** (pure scipy helper) | `support/bubble_detection.py` |
| `helpers.active_params` | 41 | 6 | **PORT** (pydantic `ActiveParams`) | `models/active_params.py` |
| `helpers.sample_positions` | 337 | 1 | **PORT** (pydantic sample-holder models) | `models/sample_positions.py` |
| `helpers.file_mapper` | 263 | 1 | **PORT** (RUNS_* file resolver; pure stdlib) | `support/file_mapper.py` |
| `helpers.ws_utils` | — | 1 | **SEAM** (already reused by framework vis/operator) | keep `helao.helpers.ws_utils` |
| `helpers.gcld_client` | 253 | 1 | **SEAM / deployment-local** (GCLD-specific external API client, not generic; only the custom gcld_operator uses it) | decide at operator wave |
| `helpers.sample_api` | 1360 | 8 | **SEAM now → dedicated port later** (SQLite sample-DB subsystem; too large for a gap-close, heavily used) | reuse `helao.helpers.sample_api`; own sub-project if/when desired |
| `drivers.data.analysis_driver` | 555 | 2 | **SEAM now → dedicated port later** (AnalysisSyncer + executor + FastAPI app subsystem) | reuse legacy |
| `drivers.data.analyses.base_analysis` | 193 | 2 | **SEAM now → dedicated port later** (with analysis_driver) | reuse legacy |

**Rationale:** port the small, generic, low-dependency helpers (4) so the bulk of the
action servers/drivers have clean framework homes; **seam** the large subsystems
(sample DB, analysis) and the deployment-specific client (gcld) — they are their own
efforts (or legitimately stay legacy seams), not Wave-0 gap-closes. Seams follow the
established strangler-fig rule (import from `helao.helpers`/`helao.core`, not crossing
the `domain/` boundary).

## 3. Wave 0 work (this sub-project)

Port the 4 small gaps, near-verbatim, with parity tests:

### 3.1 `support/bubble_detection.py`
Copy `helpers/bubble_detection.py`; repoint `helao.helpers.helao_logging` →
`helao.framework.support.helao_logging`. Else stdlib + `scipy.signal`. Public API
(the detection function(s)) preserved.

### 3.2 `models/active_params.py`
Copy `helpers/active_params.py` (the `ActiveParams` pydantic model); repoint
`helao.core.models.file.FileConnParams` → `helao.framework.models.file`,
`helao.core.helaodict.HelaoDict` → `helao.framework.models.helao_dict`.

### 3.3 `models/sample_positions.py`
Copy `helpers/sample_positions.py` (pydantic `Custom`/tray models); repoint
`helao.core.models.sample.*` → `helao.framework.models.sample`, `helao.core.helaodict`
→ `helao.framework.models.helao_dict`, `helao.helpers.helao_logging` →
`helao.framework.support.helao_logging`.

### 3.4 `support/file_mapper.py`
Copy `helpers/file_mapper.py` verbatim (no helao imports — pure stdlib).

## 4. Test strategy

Per ported module, a unit test under `helao/framework/tests/`:
- `bubble_detection`: synthetic OCP trace → assert the detection returns the expected peaks/flag (parity with legacy on a fixed input).
- `active_params`: construct `ActiveParams` from a representative dict; assert fields + `HelaoDict` round-trip (`as_dict`).
- `sample_positions`: construct a `Custom`/tray model; assert positions/lookup behavior.
- `file_mapper`: build a temp RUNS_* tree; assert the resolver maps a file as legacy does.
Reuse the legacy modules as the parity reference. Full framework suite + boundary stay green.

## 5. Boundary

`support/` + `models/` may not import `adapters`/`app`. `bubble_detection` (scipy) and
`file_mapper` (stdlib) are fine in `support/`. `active_params`/`sample_positions` are
pydantic models depending only on other `models/` — fine in `models/`. AST boundary
check (domain purity) unaffected.

## 6. Out of scope

- Any `helao/deploy/**` edit (Wave 1+; Gate B).
- The seam/defer gaps (sample_api, analysis subsystem, gcld_client) — reused as legacy
  seams; a dedicated port of sample_api and/or the analysis subsystem is a separate
  decision (flagged for the user).
- Symbol-level parity reconciliation of `premodels`/`executor`/`base_api` (Wave 2).

## 7. Done criteria

- The 4 gap modules exist in the framework with parity APIs + passing tests.
- Audit table (this doc) is the Gate-A artifact: 35 mapped, 9 classified.
- Full framework suite green; boundary green; no `helao/deploy/**` or `helao/core/**`
  modified.
- Remaining gaps documented as seams/deferred for the user to weigh in on before Wave 1.
