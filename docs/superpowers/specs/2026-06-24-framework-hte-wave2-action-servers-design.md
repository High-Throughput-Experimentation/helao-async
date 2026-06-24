# Framework hte Migration — Wave 2: Action Servers Import-Swap (design)

**Date:** 2026-06-24
**Branch:** `feat/framework-hte-wave2-servers`
**Cycle:** Gated hte production migration — Wave 2 (Gate B). Edits `helao/deploy/hte/servers/action/**`.

## 1. Scope
Import-swap the **23** `helao/deploy/hte/servers/action/*.py` files from `helao.core`/
`helao.helpers` → `helao.framework.*`. Pure import-path rewrite (no logic). Every target
maps (Wave 0 + reconciliation + sample_api/analysis/plate_api ports closed all gaps):

| legacy | → framework |
|---|---|
| `core.servers.base_api` (Base/BaseAPI/Active/action_version) | `framework.app.base_api` |
| `core.error` | `framework.models.errors` |
| `core.models.{data,file,hlostatus,sample}` | `framework.models.*` |
| `core.drivers.helao_driver` | `framework.ports.driver` |
| `core.drivers.data.sync_driver` | `framework.app.sync_driver` |
| `core.drivers.data.analysis_driver` | `framework.app.analysis_driver` (ported) |
| `helpers.premodels` (Action/Experiment/Sequence ; ActionPlanMaker/ExperimentPlanMaker) | `framework.domain.run_models` ; `framework.domain.plan_makers` (split mixed lines) |
| `helpers.executor` | `framework.domain.executor` |
| `helpers.bubble_detection` | `framework.support.bubble_detection` (ported W0) |
| `helpers.make_str_enum`, `helpers.yml_tools` | `framework.support.*` |
| `helpers` (bare helao_logging) | `framework.support` |

No unmapped symbols in the action servers (YmlType is driver-only; plate_api closed).

## 2. Linux vs Windows split
Action servers wrapping Windows-only drivers (Galil io/motion, Gamry pstat) import those
drivers transitively → cannot import-smoke on Linux. Apply the SAME swap; import-smoke the
Linux-importable servers, and for any server that fails to import on `gclib`/`comtypes`
(not on our swap) skip it with a clear reason (hardware smoke → Wave 5). The smoke test
discovers these dynamically (try-import; classify ImportError on gclib/comtypes as skip).

## 3. Method
Per file: rewrite matching import lines per §1 (logic untouched). Grep gate: no live
`helao.core.`/`helao.helpers.` import remains in `servers/action/**` except `ws_utils`
(seam). Import-smoke the Linux-importable servers; skip Windows-driver ones.

## 4. Tests / done
- `helao/framework/tests/test_hte_action_servers_import.py`: import each action server
  module; pass on success, skip on `gclib`/`comtypes` ImportError (Windows hardware).
- Grep gate (live imports only; docstrings/comments OK).
- Full framework suite + boundary green; `helao/core/**` + `hte/{drivers,configs}` +
  `hte/servers/{orchestrator,operator,visualizer}` unchanged (Wave 2 = action servers only).

## 5. Reversibility / risk
Import-path only; per-file revertible; legacy intact; configs unchanged so the launched
system still uses legacy until Wave 4. Windows servers' hardware smoke deferred to Wave 5.

## 6. Gate
Gate B: spec approved before the 23-file edit. (Proceeding per the user's "continue with
the planned waves" — same low-risk mechanical pattern as the merged Wave 1.)
