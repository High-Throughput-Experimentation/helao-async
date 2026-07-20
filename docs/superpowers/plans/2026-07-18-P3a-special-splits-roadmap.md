# P3a Special Splits — Roadmap (galil / PAL / Gamry / Archive)

> Sub-project of P3 (see `2026-07-18-P3-hte-decomposition.md`). Native-adapter hardening, **post-parity** (graft-wrap keeps legacy drivers at runtime; these native adapters are not yet wired to `app.driver`). Each split is tiered **Linux-verifiable** (behavior-preserving domain/port extractions — do now) vs **at-station** (Windows-runtime native hardware adapters + Bokeh — construct-test on Linux, behavior verify at-station). Line refs verified 2026-07-18.

## Status

| Split | Slice | State |
|---|---|---|
| galil | 1 — `TransformXY` → `helao/hexagon/domain/motion_transform.py` | **DONE** 667fcb3d (Linux, 9 tests) |
| galil | 2 — CalibrationStore port + `JsonFileCalibrationStore` | **DONE** 5d809df8 (Linux, 9 tests) |
| galil | 3 — gclib Hardware adapter | PLANNED (at-station) |
| galil | 4 — aligner visualizer-adapter (D6 fix) | PLANNED (at-station, highest risk) |
| PAL | 1 — build_palcam recipes + CAM catalog | PLANNED (Linux) |
| PAL | 2 — sample-reconciliation policy (~1330 LOC) | PLANNED (Linux, high-effort/risk) |
| PAL | 3 — trigger-wait state machine (consumer) | PLANNED (Linux) |
| PAL | 4 — transport / trigger-producer / job-context ports | PLANNED (at-station) |
| Gamry | catalogs (already separate modules) + COM STA-thread adapter | PLANNED (adapter at-station) |
| Archive→SampleState | — | Use existing approved plan `feat/hoist-archive-to-sample-server` (do NOT duplicate) |

Branch stack tip: `feat/p3a-galil-transformxy` (holds galil slices 1-2).

---

## galil — remaining slices

**Slice 3 — gclib Hardware adapter (Windows-runtime; Linux construct-testable).** Driver `helao/deploy/hte/drivers/motion/galil_motion_driver.py`. The device-command methods issue `self.galilcmd`/`self.g.*` and return legacy `{err_code: ErrorCodes}` dicts consumed directly by the server (`galil_motion.py:257,280,317,382,400,416,528,586` via `app.base.get_main_error`). **These dict returns MUST be preserved verbatim** (D6 + §4.4). Adapter satisfies `HardwarePort` lifecycle for `connect/get_status/reset/disconnect/estop(switch: bool)/shutdown/abort(=stop)` and exposes the motion verbs (`motor_move`, `query_axis_position`, `query_axis_moving`, `motor_off/on`, `stop_axis`, `setaxisref`, `reset_controller`) as first-class named methods with dict returns intact. Keep the `_is_estopped()` framework read (`self._base_hook.actionservermodel.estop`, L1108-1118) and route calibration file access through the slice-2 `CalibrationStorePort`. `import gclib` stays lazy (already in `connect()`/`motor_disconnect`). Construct-test on Linux (`__init__` does zero device I/O; assert `galil_enabled is None`, drive axis-id math); runtime at-station. **Not runtime-wired** — the graft-wrap path keeps the legacy driver; this adapter is the native-cut-over target.

**Slice 4 — aligner visualizer-adapter (D6 violation removal; at-station, HIGHEST RISK).** The driver **constructs a Bokeh `Server`** in `Galil.start_aligner()` (L352-380, `Server({...}, port=...)` at 372-377, `self.bokehapp.start()` 379), builds `HelaoVis` in `makeBokehApp` (382-390), and **holds an `Active`** (`self.aligner_active`, set in `start_aligner_run` L503-532). Module-top imports `from bokeh.server.server import Server` (41) + `from ...layouts.aligner import Aligner` (56). The aligner (`layouts/aligner.py`, 1685 LOC) reaches into the driver directly (`motor._motor_move` L1225, `motor.query_axis_position` L1238, `motor.update_plate_transfermatrix` L1169, `motor.transform.*`, `motor.base.helaodirs.db_root` L1174, `motor.base.get_main_error` L1180, `motor.aligner_active.write_file/enqueue_data/finish` L1182-1206). The split: (1) move the `Server(...)`/`HelaoVis`/`makeBokehApp` construction to a vis-layer adapter (delete driver L352-390, connect() call 265-266, imports 41/56); (2) route the aligner's `motor.*` motion + persistence + Base reach-through through the existing `/run_aligner`,`/stop_aligner`, motion, and `save_named_plate_calibration` (a 4th CalibrationStore method) endpoints; (3) move the `aligner_active`/`aligning_enabled`/`blocked` flag-passing + `finish_alignment` Active file-write to the server endpoint layer so **no `Active` is held on the driver**; (4) delete the driver `base` property (137-145, exists only for the aligner). **Cannot be runtime-verified on Linux** (Bokeh session + at-station alignment). Requires an at-station alignment dry-run before cut-over. Do NOT force-land blind.

---

## PAL — 4-way split (wrap-then-split)

Driver `helao/deploy/hte/drivers/robot/pal_driver.py` (3236 LOC, `class PAL(HelaoDriver)` @ L264). Driver touches ONLY the per-job injected `Active` — never Base/app (docstring L269-271). nidaqmx lazy (`_poll_trigger_task` L544-545). Constructs on Linux (needs `paramiko`+`aiofiles` in the env; both pure-Python cross-platform). Wrap-then-split entry = the single `Active` choke point: `submit_job(palcam, active)` L437 / `PALJobExec._pre_exec` (`pal_server.py` L65-67).

**Linux-verifiable slices (do first, behavior-preserving):**
- **PAL-1 — recipes + CAM catalog.** 13 `build_palcam_*` methods (L2479-3112, pure `(params, samples_in) -> PalCam`) + `robot/enum.py` `CAMS` catalog (already a separate module — declarative data). Characterization-testable. Note: they read `self.CAMS` + `self.file_name`/`file_path` (config, set in `__init__` L354-357) — extract as pure functions taking the catalog + file config as args.
- **PAL-2 — sample-reconciliation policy (~1330 LOC, HIGH-VALUE, HIGH-EFFORT).** `_sendcommand_check_*` family + `_sendcommand_next_full_vial` (L911) + `_sendcommand_check_source*`/`_check_dest*` (L980-1818) + `_sendcommand_prechecks` (L1819) + `_sendcommand_update_archive_helper` (L2144) + `_sendcommand_update_sample_volume` (L2228) + the sample-pipeline block in `_sendcommand_main` (L708-895). Speaks ONLY through the shim's 12 methods (`SampleShimAdapter` in `helao/hexagon/adapters/legacy/sample_state.py` already flattens this surface). Only non-shim coupling: read-only `job.active.action.action_uuid` + `action=job.active.action` kwarg to `new_ref_samples` — stub in tests. **Risk: sample-DB corruption if wrong; requires thorough characterization tests before the move.** Extract as a domain object depending on the existing SampleState port.
- **PAL-3 — trigger-wait state machine (consumer).** `_sendcommand_triggerwait` (L1918-1974, pure asyncio queue-wait) + `_clear_trigger_qs` (L523). Test by posting to the `IO_trigger_*q` queues directly.

**At-station slices (construct-test on Linux, verify at-station):**
- **PAL-4a — TRANSPORT adapter.** `_sendcommand_submitjoblist_helper` (L1986-2128; local `subprocess.Popen` L2030 / paramiko SSH+Cygwin L2035-2126) + `kill_PAL`/`kill_PAL_cygwin`/`kill_PAL_local` (L3148-3236) + `_PAL_IOloop_meas_end_helper` communicate (L2443). paramiko/psutil/subprocess portable; runtime target is Windows/Cygwin. Mock-testable, real behavior at-station.
- **PAL-4b — TRIGGER-producer adapter.** `_poll_trigger_task` (L535-604, lazy nidaqmx, the only nidaqmx user). NI hardware; fake-DAQ construct-test, verify at-station.
- **PAL-4c — JOB-CONTEXT / DataSink port (LAST, the wrap seam).** Port methods PAL actually calls on `Active`: `split()`, `enqueue_data(dict)`, `append_sample(samples, IO)`, `write_file_nowait(...) -> path`, `finish_hlo_header(file_conn_keys, realtime)`, `get_realtime()/get_realtime_nowait()`, `set_estop()`, + an `action` view (`action_uuid`, `error_code`, `samples_in/out`, `action_sub_name`, `save_data`, `file_conn_keys`). Completion contract stays on `PALJob` (`done` event + `error`, set in `_PAL_IOloop_meas_end_helper` L2432-2477). `PALJobExec` (`pal_server.py` L42-81) adapts the real `Active` to the port. Wrap PAL behind this single port first, then split internals PAL-1→2→3→4a/4b.

---

## Gamry — COM STA-thread adapter (§11.2, at-station)

Declarative technique/signal/dtaq/range catalogs already live in separate modules (`pstat/gamry/{device,technique,signal,dtaq,range}.py`) — no extraction needed. The adapter (Windows-only, comtypes) owns a dedicated **STA thread**: COM init + dtaq event sinks + `PumpEvents` loop on it; results marshal out via queue; `sys.coinit_flags` moved OUT of module import (currently process-wide at import — now lazy per P3a-1); three strategies behind one adapter (DC/dtaq sink path · EIS/ReadZ · idle-poller — today `stop()` must know which is live); `kill_gamrycom`/`reset()` psutil kill = adapter-supervisor concern. Construct-test on Linux (comtypes absent → construction must not touch COM); runtime + apartment-affinity verify at-station. Also the constructor-connect §10.4 fix (GamryDriver `__init__` self.connect()) folds here.

## Archive → SampleState (§4.3.11)

Do NOT re-plan or duplicate. Use the existing **approved 3-round-consensus plan** on `feat/hoist-archive-to-sample-server` (hte-only, live-exec shim, atomic Phase-4 cutover). Archive (2451 LOC) re-homes behind the SAMPLE server via the existing `SampleShimAdapter`; only Base coupling is `helaodirs`×3 + `UnifiedSampleDataAPI(base)` — mechanical inject. Coordinate with that branch.

## Sequencing recommendation

Land the Linux-verifiable slices next (galil is done through slice-2; PAL-1 recipes, then PAL-2 reconciliation with heavy characterization tests). Hold the at-station slices (galil-3/4, PAL-4a/b/c, Gamry COM) until the **gamry canary cut-over** validates the graft-wrap parity at-station — the at-station result can reshape the native-adapter design, and none of these are runtime-wired yet, so building them ahead of the parity proof risks rework. Archive→SampleState proceeds on its own branch.
