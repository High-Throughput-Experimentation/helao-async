# P3a-PAL — internal 4-way split (step 2 of wrap-then-split)

Branch `feat/p3a-pal-4way-split`. WRAP (step 1) done: `pal.yml`/`palhex.yml` +
`pal_canary.bat` (commit 258808d0); hexagon shim `helao/deploy/hexagon/servers/
action/pal_server.py` (`makeActionApp`, grafts write path only — `app.driver`
stays the live legacy `PAL`) + frozen checklist `helao/hexagon/tests/checklists/
hte/pal_server.json`. **Invariant for the whole split: `/openapi.json` stays
byte-identical to that checklist** (the split is internal to the driver).

The four concerns are today interleaved in one 3,236-LOC `PAL(HelaoDriver)` in
`helao/deploy/hte/drivers/robot/pal_driver.py`. Split into 4 ports + 1 domain
service; keep the `_PAL_IOloop` job engine + `HelaoDriver` lifecycle in the
driver as the composition root (galil precedent: driver stays the engine that
composes `TransformXY` + `JsonFileCalibrationStore`).

## Ports / domain
- **A. DataSinkPort** — ALREADY EXISTS (`helao/hexagon/ports/data_sink.py`, docstring names PAL as its motivation). Retype `PALJob.active: "Active"` → `DataSinkPort`; drop the sole `helao.core.servers.base.Active` import (pal_driver.py:35,259). Pass the thread-safe `get_realtime_nowait` callable to transport/trigger instead of the whole object.
- **B. SampleStatePort** — ALREADY EXISTS (`helao/hexagon/ports/sample_state.py` + `adapters/legacy/sample_state.py SampleShimAdapter`). Inject the adapter; rewrite ~15 `self.archive.unified_db.X`/`self.archive.X` → `self.sample_state.X`.
- **C. PalTransportPort** — NET-NEW (`helao/hexagon/ports/pal_transport.py` + `adapters/legacy/pal_transport.py`). Owns SSH/subprocess/psutil (`_sendcommand_submitjoblist_helper` 1986-2128, `_write_local_rshs_aux_header` 1976-1984, `kill_PAL*` 3148-3236). Move `paramiko` off the module top (line 23) into adapter methods (lazy, §11.1). Methods: `ensure_aux_logfile`, `submit_joblist`, `kill`, `host` property. The two cross-concern lines (trigger-start 2009, `joblist_time` stamp 2029/2114) move OUT to the engine.
- **D. PalTriggerPort** — NET-NEW (`helao/hexagon/ports/pal_trigger.py` + `adapters/legacy/pal_trigger.py`). Owns the NI-DAQmx DIO handshake (`_poll_trigger_task` 535-604, `_sendcommand_triggerwait` 1918-1974, `_clear_trigger_qs` 523-533) + the 3 queues. `nidaqmx` already lazy (544-545). `wait_for_triggers` returns `(ErrorCodes, start,continue,done)` preserving the three timeout codes; engine sets `IO_error`/`IO_continue`. Poller receives `realtime_nowait` callable (removes the 572/582/591 DataSink reach). Null adapter when `dev_trigger != "NImax"`.
- **PalReconciliation domain service** — NET-NEW (`helao/hexagon/domain/pal_reconciliation.py`), the TransformXY analogue + biggest Linux-testable win (~900 LOC). Base-free, constructed with `(sample_state, cams)`; `plan(palcam, action_uuid, action)` = cam-table + source/dest resolution (`_check_source*` 980-1192, `_check_dest*` 1194-1817, `_sendcommand_prechecks` reconciliation half 1819-1916); `reconcile_after_trigger(...)` = steps (1)-(7),(9) + `_update_archive_helper` (2144-2226) + `_update_sample_volume` (2228-2262). Follows `motion_transform.py` boundary rules (stdlib logger, no Base/server/vendor imports, models from `helao.hexagon.domain.models`). **Step-8 HLO write (842-887) stays ENGINE-owned** (it sits between steps 7 and 9 and uses `file_conn_keys` mutated by `split()`).

## Slice sequence (lowest-risk first)
- **0. Baseline freeze** (Linux, no code): confirm checklist current; capture an `inspect`-based public-API drift snapshot (names `pal_server.py`/`PALJobExec` depend on: `build_palcam_*`, `submit_job`, `stop`, `kill_PAL`, `is_busy`, `sshhost`).
- **1. DataSink typing** (Linux, lowest risk): retype `PALJob.active`→`DataSinkPort`, drop `Active` import, pass `get_realtime_nowait` callable. Makes the driver Base-free → unlocks Linux unit tests.
- **2. SampleState port adoption** (Linux): inject `SampleShimAdapter`; mechanical ~15 call-site rewrite.
- **3. PalReconciliation domain lift** (Linux; sub-phased 3a source / 3b dest+assembly / 3c after-trigger / 3d prechecks disentangle — engine keeps `_palcmd` joblist assembly + aux-log write). Unit-test each with a fake `SampleStatePort` (pattern: `test_motion_transform.py`, `test_calibration_store.py`).
- **4. PalTransportPort + LegacyPalTransport** (Linux construct/import; SSH runtime at station).
- **5. PalTriggerPort + NidaqmxPalTrigger** (Linux construct/import; NI runtime at station).
- **6. Engine thin-out + final parity sweep** (Linux).

Linux-completable: 0-3, 6. Station-gated runtime only: 4-5 (SSH `10.231.100.128` + NI DIO), Linux portion = construct-disconnected + import-sweep.

## Verification (every slice)
Import-sweep (pal_driver + both pal_server + hexagon subtrees, incl. lazy paramiko/nidaqmx) · pyright (authoritative) on changed files · **openapi/checklist diff EMPTY vs `pal_server.json`** · `run_unit_tests` PASS · black pre-commit. Slices 1-3 add domain/port unit tests with fakes. Slices 4-5 Linux-stop at construct+import-green; runtime parity via `pal_canary.bat` at station.

## Decisions (both RECOMMENDED, per architect)
1. **Joblist assembly in the ENGINE**, not the transport port — reconciliation returns resolved positions; engine builds the `_palcmd` param-string and hands bytes to `transport.submit_joblist`. Keeps the transport port a pure byte-shipper.
2. **Reconciliation as a Base-free DOMAIN SERVICE** (not driver methods) — Linux-testable, mirrors TransformXY, thins the god-class. Inject only `action_uuid` + `action` (the two job-context values it reads), not a DataSink handle.

## Risks (full list in the session design output; headline items)
Trigger-start ordering parity (kill→clear→poll-task→submit; must reproduce exactly) · `realtime_nowait` thread-safety captured at `start_polling` · step-8 stays engine-owned · model/enum import surface (`pal_server.py:24-33`) load-bearing — keep models defined/re-exported in `pal_driver.py` · shared `CAMS` enum per-instance mutation (350-359) is pre-existing; keep+document · latent-broken `method_dilute/autodilute` (commented-out; not in canary) — leave untouched · vestigial `IO_*` flags — don't prune.
