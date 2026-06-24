# Framework — Analysis Subsystem Port (design)

**Date:** 2026-06-24
**Branch:** `feat/framework-analysis` (waves on this branch)
**Cycle:** Gated hte migration — dedicated port (user chose full port). No hte edits.

## 1. Key finding: it's mechanical, not an architectural rework
`AnalysisSyncer(HelaoSyncer)` is **vestigial inheritance** — verified: it never calls
`super().__init__` and every `self.<method>` it invokes (`enqueue_calc`/`get_loader`/
`sync_ana`/`syncer`) it defines itself; it uses NO inherited `HelaoSyncer` method. So
the SP6 `SyncDriver`-vs-`HelaoSyncer` mismatch does not matter: **drop the base**
(`class AnalysisSyncer:`), no behavior change. The remaining work is near-verbatim
module ports with import repoints.

## 2. Scope (~1700 LOC, 6 modules)
| Legacy | → framework | deps |
|---|---|---|
| `drivers/data/loaders/model_base.py` (66) | `adapters/loaders/model_base.py` | none (pure) |
| `drivers/data/loaders/helao_loader.py` **`HelaoLoader` class** (legacy:206+) | add to `adapters/loaders/hlo_loader.py` (read fns already ported by SP6) or a sibling | boto3 etc. |
| `drivers/data/loaders/localfs.py` (739) | `adapters/loaders/localfs.py` | yml_tools, **file_mapper(ported W0)**, hlo_loader.read_hlo_bytes, model_base |
| `drivers/data/loaders/pgs3.py` (172) | `adapters/loaders/pgs3.py` | helao_loader.HelaoLoader |
| `drivers/data/analyses/base_analysis.py` (193) | `domain/analysis/base_analysis.py` | models.analysis/s3locator/run_use, time_utils (all framework) |
| `drivers/data/analysis_driver.py` (555) | `app/analysis_driver.py` | Base/BaseAPI, Executor, sync helpers, loaders.pgs3/localfs, base_analysis |

All non-loader deps verified present in the framework (Base/BaseAPI, domain/executor.Executor,
models.analysis/s3locator/run_use, support time_utils/yml_tools/config_loader, file_mapper W0).

## 3. Waves
- **Wave A — loaders:** port `model_base`, `localfs`, `pgs3` into `adapters/loaders/`;
  add the `HelaoLoader` class to the framework `hlo_loader` (the read fns are already
  there from SP6). Repoint imports to framework (`yml_tools`/`file_mapper`/`hlo_loader`/
  `model_base` siblings). Tests: HelaoDataModelMixin + a LocalLoader load round-trip on a
  temp tree; pgs3 LOADER construction (no live S3 — construct + assert attrs; mock/skip
  network). Loaders are I/O → adapters.
- **Wave B — base_analysis:** port to `domain/analysis/base_analysis.py` (BaseAnalysis +
  whatever models it builds). Pure-ish (models + time_utils). Test: subclass + run a
  trivial analysis, assert output model shape.
- **Wave C — analysis_driver:** port to `app/analysis_driver.py` — `AnalysisSyncer`
  (drop `HelaoSyncer` base), `AnalysisExecutor(Executor)`, `make_analysis_app(server_key)`.
  Repoint: `core.servers.base.Base`→`app/base_api.Base`, `base_api.BaseAPI`→`app/base_api`,
  `helpers.executor.Executor`→`domain/executor`, `error.ErrorCodes`→`models/errors`,
  `loaders.pgs3`/`localfs`→`adapters/loaders/*`, `base_analysis`→`domain/analysis/base_analysis`,
  `config_loader`/`time_utils`/`yml_tools`→`support/*`. Remove the `HelaoSyncer` import +
  base. Test: `load_analysis_classes` + `make_analysis_app` builds a BaseAPI app from a
  minimal config (AnalysisExecutor/AnalysisSyncer construct); no live S3.

## 4. Boundary
loaders/syncer = adapters (I/O); base_analysis = domain (pure); analysis_driver/make_analysis_app
= app (builds a BaseAPI). app may import adapters+domain; adapters may import models/support;
domain stays pure. AST boundary check unaffected.

## 5. Tests / done
Per-module parity tests (above); full framework suite + boundary green after each wave;
no hte/core edits; the `HelaoSyncer` base dropped with zero functional change (verified).
Done when `make_analysis_app` + `BaseAnalysis` import + build from the framework, so the
hte analysis server migrates by import-path swap (Wave 2).
