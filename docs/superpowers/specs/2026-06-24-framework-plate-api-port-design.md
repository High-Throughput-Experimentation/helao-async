# Framework — plate_api + legacy_api Port (design)

**Date:** 2026-06-24
**Branch:** `feat/framework-plate-api`
**Cycle:** hte migration — close the `plate_api` follow-up gap before Wave 2.

## 1. Context
`plate_api` (305 LOC, `HTEPlateAPI`) is the last cross-cutting legacy seam: used by
framework `sample_api` (SolidSampleAPI) + `bokeh_operator` (gated SP-VIS-3 seam), and hte
`HTEdata_legacy`/`layouts/aligner`. It transitively needs `legacy_api` (728 LOC,
`HTELegacyAPI`). Both are clean ports (helao deps: `helao_logging`→support;
`HelaoLoader`→`adapters/loaders/hlo_loader` [ported WA1]; `HTELegacyAPI`→`legacy_api`).
**Note:** the earlier-flagged `AnalysisInput` gap is a NON-issue — the framework
`models.analysis` is class-identical to legacy; `baseline_spec`/etc. are `@property`s on a
local `EcheUvisInputs(AnalysisInput)` subclass (runtime-correct; Pyright static noise).

## 2. Components (port to adapters — I/O: httpx/HelaoLoader/numpy/files)
- `adapters/legacy_api.py` = `cp` of `helpers/legacy_api.py`; repoint `helao.helpers.helao_logging`→`helao.framework.support.helao_logging`. Else numpy/zipfile/os. Public: `HTELegacyAPI`.
- `adapters/plate_api.py` = `cp` of `helpers/plate_api.py`; repoint: helao_logging→support; `helao.core.drivers.data.loaders.helao_loader.HelaoLoader`→`helao.framework.adapters.loaders.hlo_loader`; `helao.helpers.legacy_api.HTELegacyAPI`→`helao.framework.adapters.legacy_api`. Else httpx/mendeleev/pandas. Public: `HTEPlateAPI`.

## 3. Repoint the seam users (close the seam)
- framework `adapters/sample_api.py` + `app/operator/bokeh_operator.py`: `helao.helpers.plate_api`→`helao.framework.adapters.plate_api`.
- hte `drivers/data/HTEdata_legacy.py` + `layouts/aligner.py`: `helao.helpers.plate_api`/`legacy_api`→`helao.framework.adapters.{plate_api,legacy_api}`.
- Grep gate: no live `helao.helpers.plate_api` / `helao.helpers.legacy_api` / `helao.core.drivers.data.loaders.helao_loader` import remains in framework/ or hte/ (docstrings/comments OK).

## 4. Tests / done
- `test_adapters_legacy_api.py`: `HTELegacyAPI` imports + construct without live network (assert public methods via inspect; skip live paths) OR a pure-method test if any.
- `test_adapters_plate_api.py`: `HTEPlateAPI` imports + public surface; construct without live HTE Plate API (no network) — assert attrs/methods; note skipped live paths.
- Full framework suite + boundary green; hte edits limited to the 2 named files; no `helao/core/**` modified.

## 5. Done
Both ported to adapters with parity APIs + tests; seam users repointed; grep gate clean;
suite+boundary green. Closes the plate_api gap (sample_api/operator no longer seam helpers).
