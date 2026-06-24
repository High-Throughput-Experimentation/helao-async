# Framework — sample_api Port (design)

**Date:** 2026-06-24
**Branch:** `feat/framework-sample-api`
**Cycle:** Gated hte migration — dedicated port (user chose to port, not seam).
No hte edits; pure framework addition.

## 1. Context
`helao/helpers/sample_api.py` (1360 LOC) is the SQLite + filesystem sample-tracking
DB subsystem, used by 8 hte files. hte's public surface: `UnifiedSampleDataAPI`,
`unpack_samples_helper`, `update_vol`. It is I/O (sqlite3 + aiofiles) → an **adapter**.

## 2. Goal & non-goals
**Goal:** near-verbatim port to `helao/framework/adapters/sample_api.py` with import
repoints, parity tests (real SQLite round-trip). **Non-goals:** behavior change;
refactor; hte edits.

## 3. Component
`adapters/sample_api.py` = byte-for-byte copy of the legacy module with ONLY these
import repoints (all verified present in the framework):
- `from helao.helpers import helao_logging as logging` → `from helao.framework.support import helao_logging as logging`
- `from helao.core.models.sample import (AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample, object_to_sample, SampleType)` → `from helao.framework.models.sample import (...)`
- `from .file_utils import file_in_use` → `from helao.framework.support.file_utils import file_in_use`
Keep sqlite3/pandas/aiofiles/shortuuid/json/os/asyncio as-is. Preserve all public
names: `SampleModelAPI`, `LiquidSampleAPI`, `GasSampleAPI`, `AssemblySampleAPI`,
`SolidSampleAPI`, `OldLiquidSampleAPI`, `UnifiedSampleDataAPI`, `unpack_samples_helper`,
`update_vol`.

Boundary: an adapter — may do sqlite/file I/O + import framework `models`/`support`.
Must not be imported by `domain/`.

## 4. Test strategy
`helao/framework/tests/test_adapters_sample_api.py`:
- `UnifiedSampleDataAPI` round-trip on a temp SQLite root: `init_db`, `new_samples`
  (a liquid + a solid sample), `get_samples` back (fields match), `update_samples`,
  `count_samples`/`list_new_samples`. Real DB assertions.
- `unpack_samples_helper` + `update_vol` unit tests on representative inputs.
- Reuse legacy as the parity reference. Full framework suite + boundary stay green.

## 5. Done criteria
`adapters/sample_api.py` exists with parity API + passing tests; full suite green;
boundary green; only the one intended-import delta vs legacy; no hte/core edits.
