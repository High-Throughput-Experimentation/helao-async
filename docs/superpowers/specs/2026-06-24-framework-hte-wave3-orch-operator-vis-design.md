# Framework hte Migration — Wave 3: orchestrator + operator + visualizers (design)

**Date:** 2026-06-24
**Branch:** `feat/framework-hte-wave3-orch-op-vis`
**Cycle:** Gated hte production migration (Wave 3; plan
`2026-06-24-framework-hte-production-migration-plan.md`). First hte-edit wave for the
non-action servers. Pure import-path swap — **no logic changes**.

## 1. Scoping decision (the important part)

The naive Wave-3 surface is 20 files (1 orchestrator + 4 operator + 15 visualizer) that
still import `helao.core`/`helao.helpers`. But 5 of those are **generic host duplicates**
that the framework already provides under `helao/framework/app/servers/`, and that the
DEPLOYMENTS.md contract says a deployment must NOT carry:

| hte file | framework generic | fate |
|---|---|---|
| `servers/orchestrator/async_orch2.py` | `app/servers/orchestrator.py` | **Wave 4** repoint+delete |
| `servers/operator/standalone_operator.py` | `app/servers/standalone_operator.py` | **Wave 4** repoint+delete |
| `servers/visualizer/action_visualizer.py` | `app/servers/action_visualizer.py` | **Wave 4** repoint+delete |
| `servers/visualizer/live_visualizer.py` | `app/servers/live_visualizer.py` | **Wave 4** repoint+delete |
| `servers/visualizer/data_browser.py` | `app/servers/data_browser.py` | **Wave 4** repoint+delete |

Verified the hte copies are thin wiring functionally identical to the framework generics
(≤64 LOC each, no hte-specific logic). They are NOT import-swapped here — Wave 4 repoints
their configs to `deployment: framework` and deletes the dead hte copies.

**Critically, this also sidesteps a symbol gap:** legacy `OrchAPI` (a monolithic
`HelaoFastAPI` subclass) has no drop-in in the framework — the framework split it into
`OrchDriver` + `makeOrchApp` + the generic `app/servers/orchestrator.py`. `async_orch2.py`
is replaced wholesale at Wave 4, so no framework-side reconciliation is needed.

**Wave 3 therefore = the 15 files that genuinely STAY in hte** (deployment-specific, no
generic equivalent):
- 12 per-instrument visualizers: `tec_vis, syringe_vis, power_supply_vis, spec_vis,
  biologic_vis, gamry_vis, pal_vis, co2_vis, temp_vis, mfc_vis, nidaqmx_vis, pressure_vis`
  — `Vis` subclasses + `Live/ActionVisualizer` subscribers.
- 3 bespoke operators with no generic equivalent: `gcld_operator.py`,
  `gcld_operator_test.py`, `finish_analysis.py`.

## 2. Import mapping (every target symbol verified present in the framework)

| legacy module (symbols hte uses) | framework module |
|---|---|
| `helao.core.servers.vis` (`Vis`, `HelaoVis`) | `helao.framework.app.vis` |
| `helao.core.servers.vis_subscriber` (`LiveVisualizer`, `ActionVisualizer`, `mount_visualizers`) | `helao.framework.adapters.vis_subscriber` |
| `helao.core.servers.operator.helao_operator` (`HelaoOperator`) | `helao.framework.adapters.helao_operator` |
| `helao.core.models.hlostatus` | `helao.framework.models.hlostatus` |
| `helao.core.models.orchstatus` (`LoopStatus`) | `helao.framework.models.orchstatus` |
| `helao.core.models.data` | `helao.framework.models.data` |
| `helao.core.error` | `helao.framework.models.errors` |
| `from helao.helpers import helao_logging` | `from helao.framework.support import helao_logging` |
| `helao.helpers.dispatcher` (`private_dispatcher`) | `helao.framework.support.dispatcher` |
| `helao.helpers.premodels` (`Sequence`) | `helao.framework.domain.run_models` |
| `helao.helpers.config_loader` (`CONFIG`) | `helao.framework.support.config_loader` |
| `helao.helpers.time_utils` (`gen_uuid`) | `helao.framework.support.time_utils` |

**Seams:** none. `gcld_client` is NOT actively imported by any Wave-3 file (the only
reference is a commented-out line in `finish_analysis.py`) — leave the comment as-is.

## 3. Constraints

- Import-path rewrite ONLY. No logic, signature, formatting, or comment changes beyond the
  import lines. A commented-out import stays commented out.
- No `helao/core/**`, no `helao/framework/**` (pure parity already done), no `configs/`,
  no `helao/deploy/hte/{drivers,servers/action}/**` edits. Scope = the 15 named files only.
- The 5 generic-host duplicates are explicitly OUT of scope (Wave 4).

## 4. Test strategy

Mirror the Wave-2 smoke test: a new `helao/framework/tests/test_hte_vis_operator_import.py`
that imports each of the 15 modules under `conda run -n helao`, skipping cleanly on
missing vendor/hardware deps (none expected — these are Bokeh/UI modules, Linux-importable)
and asserting the swapped framework symbols resolve. Full framework suite + boundary stay
green.

## 5. Done criteria

- 15 files import-swapped per the table; all 15 import-smoke green.
- New smoke test added; full framework suite green; boundary green.
- Residual `helao.core`/`helao.helpers` in the 15 files = none (except the documented
  commented-out `gcld_client` line).
- Scope clean: only the 15 files + the new test + this doc changed.
- async_orch2 + the 4 generic hosts left untouched, documented as Wave-4 repoint+delete.
