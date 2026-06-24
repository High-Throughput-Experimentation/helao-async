# Framework hte Migration — Wave 1: Drivers Import-Swap (design)

**Date:** 2026-06-24
**Branch:** `feat/framework-hte-wave1-drivers`
**Cycle:** Gated hte production migration — Wave 1 (Gate B). **FIRST wave that edits
`helao/deploy/hte/**`** (production code).

## 1. Scope
Import-swap the **31** `helao/deploy/hte/drivers/**` files from `helao.core`/
`helao.helpers` → `helao.framework.*`. Every symbol they import now has a framework
home (closed by Wave 0 + symbol reconciliation + the sample_api & analysis ports):

| legacy import | → framework |
|---|---|
| `core.servers.base` (Base) | `framework.app.base_api` |
| `core.error` | `framework.models.errors` |
| `core.models.{hlostatus,sample,file,data,analysis}` | `framework.models.*` |
| `core.version` | `framework.support.version` |
| `core.drivers.helao_driver` | `framework.ports.driver` |
| `core.drivers.data.loaders.helao_loader` | `framework.adapters.loaders.hlo_loader` |
| `core.drivers.data.analyses.base_analysis` | `framework.domain.analysis.base_analysis` |
| `helpers.premodels` (Action/Experiment/Sequence) | `framework.domain.run_models` (aliases) |
| `helpers.executor` | `framework.domain.executor` |
| `helpers.sample_api` | `framework.adapters.sample_api` |
| `helpers.active_params`, `sample_positions` | `framework.models.*` (ported W0) |
| `helpers.{make_str_enum,time_utils,yml_tools,file_utils,file_mapper,dispatcher}` | `framework.support.*` |
| `helpers.hlo_data` | `framework.adapters.loaders.hlo_loader` (or support, per layer) |
| `helpers.ws_utils` | **kept as legacy seam** (framework reuses it too) |

This is a **pure import-path rewrite** — no logic changes.

## 2. Linux-testable vs Windows-only split
- **27 files** are Linux-importable (sims, data, non-vendor drivers) → import-swap + an
  import-smoke (the module imports cleanly under the framework) on CI.
- **4 Windows-only** files import `gclib` (Galil) / `comtypes` (Gamry) — UNINSTALLABLE on
  Linux/CI: `drivers/io/galil_io_driver.py`, `drivers/motion/galil_motion_driver.py`,
  `drivers/pstat/gamry/driver.py`, `drivers/pstat/gamry/readz.py`. Apply the SAME
  import-swap, but they CANNOT be import-smoked here; their hardware smoke is **deferred
  to Wave 5** (per-station bring-up on a Windows station). The swap itself is verified by
  inspection + grep (no residual `helao.core`/`helao.helpers` except the ws_utils seam).

## 3. Method
For each of the 31 files: rewrite the import lines per the §1 map (logic untouched).
After: grep each file for residual `helao.core`/`helao.helpers` — the ONLY allowed
remainder is `helao.helpers.ws_utils` (documented seam). For the 27 Linux files, an
import-smoke test asserts each imports under the framework. For the 4 Windows files,
verify by grep only (note the deferred hardware smoke).

## 4. Reversibility
Per-file git revert; legacy `helao/core` untouched, so any driver can roll back to legacy
imports independently. hte servers/configs are NOT changed in Wave 1 (that's Wave 2/4) —
so the launched system still uses legacy until later waves flip it; Wave 1 just makes the
driver modules framework-import-clean.

## 5. Tests / done
- `helao/framework/tests/test_hte_drivers_import.py` (or a deploy-side smoke): import the
  27 Linux-importable hte driver modules; assert no ImportError. (Skip the 4 Windows ones
  with a clear reason.)
- Grep gate: no `helao.core.`/`helao.helpers.` import remains in `hte/drivers/**` except
  the `ws_utils` seam.
- Full framework suite + boundary green; no `helao/core/**` modified; `hte/servers` +
  `hte/configs` unchanged (Wave 1 = drivers only).

## 6. Risks
| Risk | Mitigation |
|---|---|
| Editing production hte driver code | Import-path only (no logic); per-file revertible; legacy intact |
| Windows drivers untestable on CI | Import-swap by inspection + grep; hardware smoke at Wave 5 on a Windows station; keep legacy launchable until then |
| A symbol with a subtly different framework API | Driver import-smoke catches import-time breaks; per-server runtime parity verified in Wave 2 + Wave 5 hardware smoke |

## 7. Gate
Gate B: this spec approved before executing the 31-file edit. Wave 5 (Gate C) covers the
hardware smoke for the Windows drivers + the full per-station bring-up.
