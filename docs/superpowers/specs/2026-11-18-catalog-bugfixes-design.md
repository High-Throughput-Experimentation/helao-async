# Catalog bug fixes: design

Date: 2026-11-18
Status: decisions taken in conversation (2026-11-18); pending written-spec review

## Goal

Fix the code defects found while writing the output catalogs
(`2026-11-18-output-catalog-design.md`). Each fix is the smallest change at the root
cause, carries one falsifiable test, and removes the matching defect bullet from the
owning folder README.

## Scope

All bug groups, in every repo that owns one:

- parent: `ErrorCodes` rendering, `HelaoDict` key guard, `MetaProcessor` global params,
  `get_Mplate_Msystem` string input;
- hte: mfc, analyses, motion/aligner, sample, PAL, biologic olecom, power_supply;
- Deployment-C: xafs defaults, mount guards, box_notes, ecms_ms;
- Deployment-B: test_station, live-stream keys;
- Deployment-A: motion timeout, `MxytoMPlate`, muxvalve;
- Deployment-E: oceandirect `dev_ts_ns`, scaler provenance.

Out of scope:

- Production data cleanup or re-drops, except the read-only xafs inventory (C1).
- Station deploys. The H5 config edit is committed in hte, but it reaches a station
  only through the station check after approval.
- Adjacent defects the root-cause reports flag as separate (mfc totalizer meter and the
  incomplete status-flag filter, galil `q.split(",")` vs `", "`, sample `tray_new_position`
  per-call lock and `req_vol=None`, thorlabs unused `tmax`, Deployment-B notes scripts).

Line numbers are as of: parent `unstable` 37738012, hte `origin/main` f4e8a368,
Deployment-C 7fd9690, Deployment-A e287ef1, Deployment-B 08161c4, Deployment-E 785be5c.
Paths in Deployment-X are relative to that repo root.

## Shared rule: motion timeout (H6, A2)

The orchestrator E-STOPs the station on any non-`none` action `error_code`
(`orch_dispatch.py:415-421`). It pauses and re-queues the action at the head when the
endpoint raises (HTTP 500, `orch_dispatch.py:303-317`). Decision 1 picks the second.

Both motion drivers (hte galil, Deployment-A thorlabs) classify the end of the settle
loop the same way:

| loop exit | per-axis `err_code` | action |
|---|---|---|
| every requested axis reported `stopped` | move code if not `none`, else the query's code | finishes as today |
| deadline passed without every axis `stopped` (including a failed last query) | n/a | `stop_axis(axis)`, release `motor_busy`/locks, then `raise RuntimeError("motion timeout: ...")` naming the axes and the timeout |
| E-STOP | `estop` | unchanged |

`RuntimeError`, not `TimeoutError`: the dispatcher treats `asyncio.TimeoutError`
(= `TimeoutError`) as an RPC transport failure and falls back to HTTP
(`helao/helpers/dispatcher.py:244`). A handler `RuntimeError` reaches the client as
`RPCHandlerError` and is never re-sent (`dispatcher.py:240`).

## Bugs

Each entry: symptom; root cause; reach; fix (with wire/data effects); test (path,
input, expected value derived independently of the fix); decision.

### Tier 1: live on stations, do first

#### H1 mfc: `FlowMeter.get_status` mutates `status_keys`

- Symptom: after one 5-field reply a controller publishes `setpoint: null` and
  `gas: "+003.00"` forever. A 7-field reply makes later 6-field replies raise, which
  triggers a reconnect each time. Since b143c278 the corrupt dict is published, not dropped.
- Root cause: `servers/mfc/alicat_driver.py:1183-1188` edits `self.status_keys` (built at
  `:1068`) in place.
- Reach: LIVE: `ccsi2.yml`, `ecms3.yml`, Deployment-F's station config (`fast: mfc_server`).
- Fix: derive `keys = list(self.status_keys)` per reply and adjust that copy; never
  assign to `self.status_keys`. `is_connected` (`:1113-1131`, no callers) tests the
  returned dict instead of `status_keys`. The `__main__` stream (`:1654`, `:1662`)
  iterates the reply's own keys. Effect: controllers stop publishing wrong `gas` and null
  `setpoint` after a glitch; no reconnect per mixed-length reply.
- Test: new `helao/deploy/hte/tests/test_alicat_status_keys.py`. This is a new file
  so it does not conflict with the other session's edits to
  `test_alicat_meter_status.py`. Build `object.__new__(FlowController)` with a
  scripted `_write_and_read`.
  - (a) Replies 6, 5, 6 fields (`"B +014.70 +022.00 +003.00 +002.90 +003.00 CO2"`,
    then the same without the setpoint, then the 6-field reply). The third call gives
    `setpoint == 3.0`, `gas == "CO2"`.
  - (b) Replies 6, 7, 6. The third call gives `gas == "CO2"`, no `"total flow"` key,
    and no raise.
  - (c) `status_keys` equals its initial list after both sequences.
- Decision: default (investigator), no user decision needed.

#### P1 `ErrorCodes` renders as `"ErrorCodes.none"` (parent)

- Symptom: on Python 3.14, `f"{ErrorCodes.none}"` and `str()` give `"ErrorCodes.none"`.
  These strings land in the hte aligner `plate_calib` row (`layouts/aligner.py:1266`), in
  Deployment-A's `layouts/plate_aligner.py:1027`, and in the Reflex pstat status text
  (`helao/deploy/base/servers/reflex/_pstat.py:228`), and in log lines.
- Root cause: `helao/core/error.py:8`. `ErrorCodes(str, Enum)` is not a `StrEnum`, and
  since Python 3.12 `format()` follows `Enum.__str__`.
- Reach: LIVE on every aligner station (`enable_aligner` on adss3, anec, clad, eche10,
  hispec; Deployment-A's electrode config).
- Fix: `__str__ = str.__str__` on `ErrorCodes`. The aligners need no edit. Effect: new rows
  carry `"none"`/`"stop"`, as the pre-3.12 envs did. Log text and the pstat status
  string drop the class prefix. Existing rows stay as written (decision 2), so consumers
  must accept both spellings.
- Test: extend `helao/core/tests/unit_test_error_codes.py` (run by `run_unit_tests.py`):
  `f"{ErrorCodes.none}" == "none"`, `str(ErrorCodes.stop) == "stop"`. Re-check its
  `"ErrorCodes."` check labels at `:61,83,87` and `unit_test_dispatcher.py:393,397`.
- Decision: 2.

#### H2 sample: `archive_tray_export_json` on an undefined slot raises

- Symptom: `ValidationError` after `ctx.begin`. The action returns 500, the orchestrator
  pauses and re-queues, and the action fails again on resume.
- Root cause: `servers/sample/sample_server.py:330-332` wraps the driver's
  "nothing to export" `None` (`archive_driver.py:549-559`) in `DataModel`.
- Reach: LIVE via the operator: `ADSS_sub_tray_unload` on adss3 with `tray=1`
  or `slot>3` (`adss3.yml:180-183`).
- Fix: if `datadict is None`, log a WARNING, enqueue no row, and finish with `none`.
  This matches `archive_tray_export_csv`.
- Test: new `helao/deploy/hte/servers/sample/tests/test_tray_export_json.py`, using the
  fake-ctx pattern from `tests/test_motion_private_endpoints.py`. Input
  `trays_dict={1: {1: None}}`, `tray=1, slot=1`. Expected: no raise, zero enqueues,
  `error_code is ErrorCodes.none`.
- Decision: 5.

#### H3 galil: real move timeout, unconfigured axes, disabled-controller indexing

- Symptoms:
  - A stage still moving at `motor_timeout` is halted and reported `none`.
  - An unconfigured axis is dropped from `axis` but not from `d_mm`. With an `x`-only
    station, `["z","x"]`/`[5.0, 1.0]` drives x to 5 mm.
  - When the controller is disabled mid-move, the scalar `err_code` gets
    character-indexed (`'n' != none` turns into `timeout`; more than 13 axes would
    raise `IndexError`).
- Root cause: `servers/galil_motion/galil_motion_native.py:598-601` (filters `axis`
  only); `:712-721` (classifies the timeout from the query's code and assumes a list).
- Reach:
  - Timeout: LIVE but rare. All galil configs use `timeout: 600`; it fires on a stuck
    homing move or a stall.
  - `d_mm` misalignment: latent for tracked callers. A manual `move` or the aligner
    with an out-of-order axis list hits it.
  - Scalar path: latent (needs a mid-move disconnect or reset).
- Fix: all in `_motor_move_unguarded`; every caller routes through it.
  - Filter `axis` and `d_mm` jointly, with one WARNING per dropped axis. Delete the
    dead `else` at `:608-616`.
  - Settle loop per the shared rule above. Normalize a scalar query `err_code` to
    `[code] * len(axis)`. Reset `motor_busy` in a `finally` so a raise cannot wedge
    the driver.
  - Effects:
    - A timed-out move now raises: 500, orchestrator pause and re-queue, no row for
      that move.
    - A mid-move disconnect reports `not_available` instead of `timeout`; both E-STOP
      as today.
    - An out-of-order request moves the right axis by the right distance;
      `supplied_rel_dist` changes to match.
- Test: extend `servers/galil_motion/tests/test_galil_motion_native.py` (fakes
  `MOVE_CFG`, `_move_responses`):
  - (a) `[5.0, 1.0]`, `["z","x"]`, absolute, `axis_id {"x":"A"}`: expect `"PAA=1000"`
    in commands and no `"PAA=5000"` (1.0 mm / 0.001 mm per count = 1000).
  - (b) SC `"0"` with `timeout=0.01`: `pytest.raises(RuntimeError, match="motion timeout")`,
    `"STA"` sent, and `motor_busy is False` afterwards.
  - (c) SC `"1"` with `timeout=0.01`: no raise, `err_code == [none]` (regression guard).
  - (d) `galil_enabled` flipped False inside `query_axis_moving`:
    `err_code == [ErrorCodes.not_available]` (today `[timeout]`).
- Decision: 1, plus the default "drop unconfigured axis with its `d_mm` and a WARNING".

#### A2 thorlabs: real move timeout, `qmove` unbound (Deployment-A)

- Symptom: same as H3. In addition, `motor_timeout <= 0` leaves `qmove` unbound and
  raises `UnboundLocalError` at `servers/motion/thorlabs_kinesis.py:770`.
- Root cause: `thorlabs_kinesis.py:749-776`, which classifies from the query's code;
  `qmove` is assigned only inside the loop.
- Reach: LIVE but rare (`SDC_exp` `move`/`easymove`, when a move exceeds `timeout`).
- Fix: the shared rule. Initialize
  `qmove = {"motor_status": [], "err_code": []}` before the loop. A failed last query at
  the deadline now raises too (today it reports `timeout`, which E-STOPs). Release any
  busy flag before raising. A failed last query at the deadline raises as well (user
  confirmed, for parity with galil).
- Test: extend `servers/motion/tests/test_motor_move.py`:
  - (a) `StuckKinesisMotor` whose `get_status` always reports a moving status, with
    `timeout=1`: raises `RuntimeError("motion timeout...")` and `stop_calls` is
    non-empty. Today it returns `[none]`.
  - (b) `timeout=0`: raises the same `RuntimeError`, not `UnboundLocalError`.
  - (c) A normal move still returns `[none]`.
- Decision: 1.

#### C1 xafs: non-GAIA sources crash on `campaign_uuid=""` (Deployment-C)

- Symptom: every non-GAIA EASYXAFS grid source dropped since 2026-06-08 lands in
  `failed/` with a `uuid_parsing` `ValidationError`. A partial RUNS tree (no `-seq`)
  is left behind.
- Root cause: `scripts/xafs/converters.py:103-104`. The defaults are `""`, and the
  analysis construction at `:496-512` is unguarded against them. The model field is
  `Optional[UUID]`.
- Reach: LIVE (note1 BATCH job, `EASYXAFS` state root).
- Fix: defaults become `str | None = None`. The existing
  `if campaign_uuid and campaign_name` guards are unchanged. Delete the dead
  `jmnt/kmnt/env_file` block and `sys.path.append` at `:24-33` in the same commit (C2),
  because any edit re-stamps `_ANALYSIS_CODEHASH`. Effect: non-GAIA analyses are written,
  with `campaign_*` set to `null`.
- Remediation inventory (READ-ONLY, over ssh on note1; nothing deleted or re-dropped):
  - `EASYXAFS/failed/*.state.json` whose error matches `uuid_parsing`/`valid UUID`;
  - anything stuck in `processing/` or `drop/`;
  - RUNS sequence dirs `*XAFS_wafer_grid_multiscan*` with no `*-seq.*`;
  - a check that none of the 14 plate-corrected XAFS sources is in the list.
  The list goes to the user. Cleanup and re-drop are decided after it.
- Test: new `scripts/xafs/tests/test_campaign_default.py`. `make_xafs_processes(tmp)`
  with no campaign kwargs, and `parse_xafs`, `build_xafs_values`, `SESSION` and
  `CONFIG` (`local_only`) monkeypatched. Expected: one `-ana` record under
  `tmp/ANALYSES` with `campaign_uuid` null. Today it raises `ValidationError`, which
  follows from the model contract. Never call the real `parse_xafs`: it writes the
  production standards registry.
- Decision: 7.

#### C2 mount guards and import-time `sys.path` (Deployment-C)

- Symptom:
  - `bruker_gadds/reconvert_legacy.py:52-54` hardcodes the production
    `SOURCES`/`DATA` paths. Under a `HELAO_SOURCES_ROOT` override it still copies
    into production `drop`. Its dry run writes the checkpoint (`:313`, `:345-352`).
  - `tests/test_sources_root.py::test_no_module_hardcodes_the_production_sources_root`
    is red today.
  - The edax repair CLIs default to `/mnt/wd4/DATA`: `reconvert_duplicates.py:60-61`,
    `retire_duplicate_records.py:102-106,536`, `prune_process_sets.py:884`.
  - The sibling `--root` defaults: `xrfs_calibration/fix_standard_provenance.py:246`,
    `xrfs_calibration/reconvert_per_standard.py:319`,
    `xrfs_quantification/backfill_calibration.py:213`,
    `xrfs_quantification/backfill_analysis_calibration.py:288`.
  - `edax/converters.py:32-41` and `xafs/converters.py:24-33` append
    `/mnt/j/repos/helao-async` to `sys.path` at import.
- Root cause: the literals bypass `scripts/common/roots.py`. The `sys.path` lines are
  dead code (used only by a commented-out line).
- Reach:
  - LIVE: the xafs converter is imported by the production BATCH job.
  - Manual CLIs: these are dangerous when run off note1.
- Fix (Option A): `DROP`/`PROCESSING` come from `sources_root()`, and data roots from
  `roots.PRODUCTION_DATA_ROOT`. Dry runs write nothing, so `reconvert_legacy` logs to
  stdout unless `--execute` is given. Delete both `sys.path` blocks; keep `import sys`
  only where it is still used. `legacy_jcap/cli.py` (a correct deny-list) and
  `servers/analysis/analyses/xrfs_local.py:235` stay as exact-string `KNOWN_UNMIGRATED`
  entries. Effect: none on note1, where defaults resolve to the same strings; under an
  override nothing reaches production.
- Test (static only; never execute a pre-fix CLI, since every one defaults to
  production):
  - (a) the existing gate goes red to green;
  - (b) add the `"/mnt/wd4/DATA"` marker to the `test_sources_root.py` sweep, with a
    planted-literal vacuity test like `:394-410`;
  - (c) new `tests/test_no_sys_path_mutation.py`: an AST sweep for
    `sys.path.append/insert` outside `tests/`. It fails today on the two converters.
- Decision: 8. All four sibling `--root` CLIs are migrated (user confirmed).

#### C3 box_notes: unsafe moves, re-posted notes, colliding crop keys (Deployment-C)

- Symptoms:
  - (a) `shutil.move` copies and then unlinks on a rename error, which can leave a copy
    in `processing/`. The claim is outside the `try`, and a same-name `rename`
    overwrites (`scripts/box_notes/batch_process.py:77-119`).
  - (b) A human re-drop after a partial failure re-posts every note already posted
    (`process.py:188-262`).
  - (c) The crop is uploaded as `<serial>.png`, and the API keys by basename, so a
    second box note for a plate overwrites the image behind every earlier one
    (`process.py:190`).
- Reach: LIVE (note1, `box_notes_enabled`, `box_notes_create_notes`).
- Fix:
  - (a) `_move` keeps its own `stem__n.ext` collision loop, applied to every move, and
    calls `common/batch_converter.move_bundle`. Do not reuse `_collision_free_dest`:
    it suffixes after `.tif`, and `discover_tifs` would then never rediscover the
    file. The claim goes inside the `try`, so a failed claim leaves the tif in `drop/`.
  - (b) Read each plate live (`require_plate(pid, live=True)`). Skip a plate whose
    `notes[]` already holds a note whose text starts with
    `f"Box-notes scan {input_tif} (plate {serial},"`, and log the skip. No JSON tail,
    no `force` flag (decision 9). Consequence: a genuine rescan under the same filename
    gets no new note.
  - (c) The crop name becomes `f"{stem}__{serial}__{sha256(png)[:12]}.png"`. The fix
    stays in `process.py`; `note_api.py` is shared and its other callers already pass
    unique names. Effect: new `image_s3_uri` and local crop names change form.
- Tests:
  - (a) Extend `box_notes/tests/test_batch_process_plate.py`. Monkeypatch `os.rename`
    to raise `PermissionError` on the claim, and `os.unlink` to raise as well. Expect
    the tif still in `drop/` and `processing/` empty.
  - (b, c) New `box_notes/tests/test_note_dedupe.py`. The fake `require_plate` returns
    an existing box note for 10232 and none for 10230. Expect one post, for 10230, and
    an image basename containing the tif stem and a 12-hex hash. Update the existing
    one-argument `require_plate` fake to accept `**k`.
- Decision: 9.

#### B1 test_station: `leak_test_passed` null, row duplicated (Deployment-B)

- Symptom:
  - Every mode-5 finishing row and every leak-failure row carries
    `leak_test_passed: null` and `error_code: "unspecified"`.
  - Every `set_mode` file writes its last row twice.
- Root cause:
  - `servers/test_station/test_station_server.py:553-556`, `:578-581`: the outcome
    bool is passed as a node alias to `_multi_read`.
  - `:561`, `:589`: an explicit `enqueue_data_dflt` runs and the runner also writes the
    returned `data`.
- Reach: LIVE (`AMTS_exp.py` leak-test mode and every `set_mode`).
- Fix: read only `_LEAK_NODES`, pop their `error_code`, then set
  `leak_test_passed=True/False` directly. Override the row's `error_code` only if a leak
  read failed. Delete the two explicit enqueues. Effect: `true`/`false` in place of
  `null`; the row `error_code` is `none` when the reads succeed; row count drops by one
  per file.
- Test: extend `tests/test_station_executors.py`.
  - (a) Real driver with `_nodes` AsyncMocks (mode 5, leak not failed). Expect
    `leak_test_passed is True` and `error_code == none`.
  - (b) Failure path: mode stays 1, with `_start_ts -= 11`. Expect `False`.
  - (c) `mode: 1`: rows written = `enqueue_data_dflt.await_count + (1 if out["data"] else 0)`,
    expected 1 (today 2).
- Decision: defaults (alias fix, delete double enqueues).

#### B2 live-stream keys never populated (Deployment-B)

- Symptom: the actuator live stream carries `strain_adc: 0` and `setpoint_adc: 0`
  forever. The robot arm carries `is_moving: False` and `robot_mode: -1` forever.
- Root cause: initializers left over from a rename
  (`servers/actuator/actuator_driver.py:57-59`, commit 3cb6f34). The robot arm
  skeleton never parsed these fields (`servers/robotarm/robotarm_driver.py:69-70`,
  `_parse_rtde_packet` `:242-300`).
- Reach: LIVE stream (`amts.yml`). There is no consumer today.
- Fix (decision 11: populate):
  - Actuator: `_parse_line` also sets `strain_adc` = the `STR_ACT` value and
    `setpoint_adc` = the `STR_SET` value. These are the same raw values as
    `load_act_lbs`/`load_set_lbs`, matching the server's cached-state column mapping
    (`actuator_server.py:43-44`). `load_*` must not be seeded: `wait_for_load` relies
    on `None` before the first telemetry line.
  - Robot arm: unpack `robot_mode` (double at offset 756) and `qd_actual` (6 doubles
    at offset 300) from the port-30003 packet. Set
    `is_moving = max(abs(qd)) > eps`, with `eps` a config param, default 1e-3 rad/s.
    The offsets come from UR's client-interface table and are not pinned by the
    repo, so they need a station check.
- Test:
  - (a) Extend `servers/actuator/tests/test_sim_actuator.py`:
    `_parse_line("STR_ACT:123 STR_SET:456")` gives `strain_adc == 123` and
    `setpoint_adc == 456`.
  - (b) Extend `servers/robotarm/tests/test_sim_robotarm.py`: a 1060-byte packet
    built in the test with `7.0` packed at 756 and `qd = [0, 0, 0.1, 0, 0, 0]` at
    300. Expect `robot_mode == 7` and `is_moving is True`. With `qd` all 0, expect
    `is_moving is False`.
- Decision: 11.

#### E1 scaler refine keeps the source's `version`/`created_utc` (Deployment-E)

- Symptom: a refined scaler file keeps the source's `created_utc` and `version`, even
  though its body is written in the v2 encoding.
- Root cause: `servers/calc/spectrum_utils.py:191-203`. `from_dict` puts `version`
  and `created_utc` into `meta`, and `to_dict` (`:179-189`) spreads `meta` last.
- Reach: LIVE but manual (CALC `refine_ocean_scaler` on `hispec2.yml`).
- Fix: `from_dict` drops `version`, and moves `created_utc` to
  `meta.setdefault("source_created_utc", ...)`. This keeps the lineage origin across
  repeated refines. Effect: `version` and `created_utc` describe the file being
  written, and `source_created_utc` carries the original.
- Test: extend `servers/calc/tests/test_spectrum_utils.py`. Save, rewrite the JSON with
  `version: 1, created_utc: "2000-01-01T00:00:00+00:00"`, then load and `to_dict()`.
  Expected: `version == 2`, `created_utc != "2000-..."`,
  `source_created_utc == "2000-..."`. A second load/save cycle still gives
  `source_created_utc == "2000-..."`.
- Decision: 12.

### Tier 2: latent (no tracked caller or config reaches them today)

#### H4 PAL: repeats and multi-run jobs share one action

- Symptom:
  - `repeat > 0` on microcam 0 runs every repeat inside the parent action, and the
    parent keeps only the last repeat's samples.
  - With `totalruns > 1`, microcam 0 of run 2 runs inside run 1's last split action
    and relabels it.
- Root cause: `servers/pal/pal_driver.py:535` uses `i > 0` (WIP commit cf1f5c45). The
  pre-2024 guard was `IO_action_run_counter > 0`; the counter is still maintained at
  `:633` and reset at `:962`.
- Reach: latent. Every tracked call uses `sampleperiod: [0.0]` and no `repeat`.
- Fix: restore `if self.IO_action_run_counter > 0: await job.active.split()`. Effect:
  one action per palaction. A job with R repeats or runs yields R `-act` records, each
  with its own samples and row.
- Test: `helao/deploy/hte/tests/test_pal_golden_master.py` (run with `python <file>`).
  - Scenario c (`repeat: 2`): change `split_count == 0` to `== 2`.
  - Add a scenario with `totalruns: 2` and 2 microcams: `split_count == 3`
    (palactions − 1).
  - Re-check `tests/test_pal_ioloop_c1_guard.py` and `servers/pal/tests/*` for
    split-count assertions.
- Decision: 3.

#### H5 analyses `uvis_bkgsubnorm` / `echeuvis_stability` cannot run

- Symptom: four stacked defects.
  - (i) `DryUvisOutputs`/`EcheUvisOutputs` lack `output_type`, so `export_analysis`
    raises `AttributeError` (since c3a3daa7).
  - (ii) The aggregation window starts `skip_first_n` frames early.
  - (iii) The echeuvis fallback calls `np.where` on a 0-d value and always raises.
  - (iv) The classes take a `query_df` and the driver passes a `LocalLoader` (since
    5e884505); `ECHEUVIS_exp.py:828` dispatches the nonexistent `analyze_echeuvis`
    with params the endpoint ignores.
- Root cause:
  - `servers/analysis/analyses/uvis_bkgsubnorm.py:215`, `:308`, `:350-384`;
  - `echeuvis_stability.py:367`, `:506`, `:584-642`;
  - `experiments/ECHEUVIS_exp.py:808-830`.
- Reach: latent. No config lists either analysis, and the dispatched route does not
  exist.
- Fix:
  - Both `*Outputs` subclass `AnalysisOutput`, with
    `output_type="spectrum.uvis_bkgsubnorm_ref"` and
    `output_type="spectrum.echeuvis_stability"`.
  - One helper `last_secs_start(ep, skip, secs) = skip + np.where((ep[skip:] - ep.max()) >= -secs)[0].min()`
    in `echeuvis_stability.py` (already imported by `uvis_bkgsubnorm.py`) replaces the
    six slice sites. The fallback becomes `np.where((ep - ep.max()) >= -secs)[0].min()`
    on the whole epoch vector.
  - Port both classes to `__init__(process_uuid, local_loader, analysis_params)`.
    Build the per-process frame from `local_loader.processes`/`actions`, and read
    spectra through the loader. Override `select_process_uuids` to pick only the
    target technique's processes.
  - Trigger (user ruling): the SYNC `dispatch_analysis` post-finish hook, not an
    in-sequence dispatch. See "Analysis trigger" below.
  - Delete the dangling in-sequence path:
    - `ECHEUVIS_analysis_stability` (`ECHEUVIS_exp.py:808-830`, plus its `__all__`
      entry);
    - its two callers, `ECHEUVIS_postseq` (`ECHEUVIS_seq.py:1038`,
      `HISPEC_seq.py:481`, plus their `__all__`/`SEQUENCES` entries).
    - The same pattern for the dry analysis, also deleted: `UVIS_T_postseq`
      (`UVIS_T_seq.py:137`) → `UVIS_analysis_dry` (`UVIS_exp.py:560`), which
      dispatches the nonexistent `analyze_dryuvis`.
    - Update the tests and fixtures that pin these names:
      `tests/test_queued_experiments_exist.py:89-92`,
      `tests/test_hte_library_import.py:79-80`, `tests/test_hte_collisions.py:12-14`,
      `tests/checklists/_collisions.json`.
  - Effects:
    - `output_type` joins the scalar output group, as for every base-export analysis.
    - The `agg_*`, `mean_ref_*` and downstream values change.
    - The codehash changes, so `analysis_uuid` changes.
    - Nothing was ever published, so no record is invalidated.
- Test: new `helao/deploy/hte/tests/test_uvis_analysis_export.py`.
  - (a) Frames with `epoch 0..9`, frame k value = k (light = k+100 for dry),
    `skip_first_n=4`, `agg_last_secs=2`. Expect `agg_*[0] == 8.0` (mean of 7, 8, 9);
    today 6.0.
  - (b) 3-frame insitu with `skip_first_n=4`: `calc_output()` is True and
    `agg_insitu[0] == 1.0`; today `ValueError`.
  - (c) A sequence tree built in `tmp_path` (pattern: `_record` in
    `helao/core/tests/test_loader_parity.py`), then `LocalLoader` →
    `select_process_uuids` → constructor → `calc_output` → `export_analysis`. Expect
    the `output_type` set to equal `{"spectrum.uvis_bkgsubnorm_ref"}` (and the
    echeuvis tag); today `AttributeError`.
  - (d) `select_process_uuids` on that tree returns only the `run_use == "data"`
    processes of the target sequence. The expected uuids are the ones the test wrote.
  - (e) Hook wiring: `postfinish_config` (`helao/core/hooks/config.py:78`) accepts
    the station block below, and a `HookSet` built from its `sequence` map selects for
    `"UVIS_T"`
    `dispatch_analysis` with `endpoint == "analyze_uvis_bkgsubnorm"`. Add this to
    `servers/analysis/tests/test_analysis_resolution.py`, which already names both
    endpoints at `:26`.
  - Station check required.
- Decision: 4, with the user ruling on the trigger (SYNC hook).

**Analysis trigger (H5).** How it works today:
- The SYNC entry's top-level `postfinish_hooks` config (read at
  `native_syncer.py:55` → `sync_driver.py:1231-1249`) selects hooks per record name.
  An exact name wins over `"*"` (`helao/core/hooks/__init__.py:90-102`).
- `dispatch_analysis` (`helao/core/hooks/builtin/dispatch_analysis.py`) is
  non-blocking. It runs after sync at the `sequence` (or `experiment`) level and POSTs
  `<endpoint>` to `server_key` with `{"sequence_path": <record dir>, "params": ...}`.
- The analysis server's `params.analyses` list registers one `analyze_<module>` route
  per module (`analysis_driver.py:305`). The route builds a `LocalLoader` on the path
  and enqueues one analysis per `select_process_uuids` result.
- A present `postfinish_hooks` owns the whole chain, so `s3_upload` must be restated at
  every level.
- Deployment-C's production SYNC uses exactly this shape for its two local analyses.

Which sequences feed each analysis (from each module's query filter):

| analysis | route | sequence (`sequence_name`) | actions read |
|---|---|---|---|
| `uvis_bkgsubnorm` | `analyze_uvis_bkgsubnorm` | `UVIS_T` (`UVIS_T_seq.py:10`) | `acquire_spec_adv`; `run_use` ref_dark / ref_light / data |
| `echeuvis_stability` | `analyze_echeuvis_stability` | `ECHEUVIS_multiCA_led` (`ECHEUVIS_seq.py:774`) | `run_OCV`, `run_CA`, `acquire_spec_adv`, `acquire_spec_extrig` |

Config shape, added to the chosen station config in the hte repo:

```yaml
  ANA:                      # eche10.yml has this block commented out at :175-182
    host: ...             # same host as the station's other servers
    port: 8014              # unique host:port is validated by launch.py
    group: action
    fast: analysis_server
    params:
      local_only: true      # first station check: no S3/API publish
      analyses: [uvis_bkgsubnorm, echeuvis_stability]
  SYNC:
    ...
    postfinish_hooks:
      action:     {s3_upload: ["*"]}
      experiment: {s3_upload: ["*"]}
      sequence:
        s3_upload: ["*"]
        dispatch_analysis:
          UVIS_T:               {server_key: ANA, endpoint: analyze_uvis_bkgsubnorm}
          ECHEUVIS_multiCA_led: {server_key: ANA, endpoint: analyze_echeuvis_stability}
```

`host`/`port` are omitted from the hook args, so the hook resolves `ANA` from the
syncer's world config. Set `local_only: false` after the station check passes.

hte configs that run the consumed sequences: `eche10.yml` is the only one. Its
`sequence_libraries` hold `UVIS_T_seq` and `ECHEUVIS_seq`, and it already has the
commented ANA block. `hispec.yml` loads `HISPEC_seq` and `ECHEUVIS_exp` but neither
consumed sequence, so it would produce no inputs. Recommendation: eche10 for the
station check and as the wired config.

#### H7 biologic olecom: `.mps/.mpr/.mpt` moved but never registered

- Symptom: the EC-Lab files land in the action dir and are never uploaded; every
  sync logs them as unregistered.
- Root cause: `servers/biologic/biologic_ole/driver.py:686-709` moves the files and
  records nothing; only the executor holds `active`.
- Reach: latent. Only the simulated `biologicole.yml` selects `olecom`.
- Fix:
  - Driver: keep the moved paths per channel (reset in `setup`/`setup_protocol`, not in
    `cleanup`, so the internal-cleanup path at `:547` keeps them), and return
    `data={"files": [...]}` from `cleanup`.
  - `BiologicExec._post_exec`: `track_file` each path, with `file_type`
    `biologic_mps`/`biologic_mpr`/`biologic_mpt` and the action's `samples_in`. Check
    the attribute name against `ActionModel`. eclib and eclib2 return no `files`, so
    they are untouched.
  - Fix the `misc_files` wording in the `driver.py:37/:690` docstrings and
    `servers/biologic/CLAUDE.md:61-63`.
  - Effect: the record's `files` list and the upload set gain all three files.
- Test:
  - (a) Extend `tests/test_ole_driver.py::test_cleanup_moves_the_artifacts_into_the_action_directory`:
    touch an `.mpr` in scratch. Expect `resp.data["files"]` == the sorted action-dir
    `.mps` + `.mpr` paths, each existing.
  - (b) New `servers/biologic/tests/test_biologic_ole_track_files.py`: a stub driver
    returning `files=[p]` gives exactly one `track_file(p)`; an eclib-shaped response
    gives zero.
- Decision: 6.

#### H8 power_supply: endpoints overwrite dispatched params with defaults

- Root cause: `servers/power_supply/power_supply_server.py:511-512, 553-554, 603-606`
  assign the endpoint's default kwargs over `action_params`, which `build_action`
  already filled correctly.
- Reach: latent. No caller, and no config launches the server.
- Fix: delete the 8 lines. Effect: the executors run with the dispatched values.
- Test: extend `tests/test_med_servers_fixes.py`. Dispatch `{voltage: 2.5, sleep_time: 0.2}`
  and call the endpoint with its defaults. Expected: `action_params` unchanged; today
  `voltage == 1.0`.
- Decision: default.

#### P2 / H9 / A3 `MxytoMPlate` never yields a value (parent + hte + Deployment-A)

- Symptom: a string or `None` `Mxy` raises `IndexError` on a 0-d array (500). A real
  matrix returns `np.matrix`, which the data stream cannot serialize.
- Root cause:
  - Input: `helao/hexagon/domain/motion_transform.py:357-385` does not parse the
    JSON string its only action callers declare (`Mxy: Optional[str]`).
  - Output: the endpoints (`hte servers/galil_motion/galil_motion.py:255-269`,
    Deployment-A `servers/motion/motion_server.py:256-274`) enqueue the matrix as is.
- Reach: latent (manual/API only). The route signature is frozen in
  `tests/checklists/galil_motion.json`; keep it.
- Fix:
  - Parent: `get_Mplate_Msystem` does `json.loads` on a `str`, and raises
    `ValueError("Mxy required")` on `None` (user confirmed: 500, pause and re-queue,
    no E-STOP). It still returns `np.matrix`, which the
    aligners use.
  - Both endpoints enqueue `{"mplate": None if M is None else M.tolist()}`; a singular
    `Minstr` gives `null`, as today.
  - Effect: a valid `mplate` list where today the call fails.
- Test:
  - (a) Parent `helao/hexagon/tests/test_motion_transform.py`: an identity transform with
    `"[[1,0,0],[0,1,0],[0,0,1]]"` is `allclose(identity(3))`.
  - (b) hte `tests/test_motion_private_endpoints.py` and (c) Deployment-A
    `servers/motion/tests/`: the captured row dumps without `TypeError` and
    `mplate == [[1,0,0],[0,1,0],[0,0,1]]`.
- Decision: default.

#### P3 / H10 sample `_tray_pos` tuple keys crash `-act.json` (parent + hte)

- Root cause:
  - Core: `helao/core/helaodict.py:42-43` calls `k.startswith` on any key whose value
    is a str (an int key crashes too).
  - hte: `servers/sample/sample_server.py:906-907` builds tuple keys.
- Reach: latent (only manual `get_loaded_positions` with a loaded vial).
- Fix:
  - Core guard `isinstance(k, str) and k.startswith("__")`. This strictly widens: every
    input that serializes today serializes identically.
  - hte keys become `f"{tray},{slot},{vial}"`. Effect: `-act.json`
    `action_params._tray_pos` keys look like `"1,1,1"`. No consumer reads them.
- Test:
  - (a) New `helao/core/tests/test_helaodict_keys.py`:
    `_serialize_dict({1: "a"}) == {1: "a"}`.
  - (b) New `servers/sample/tests/test_get_loaded_positions.py`: a loaded VT54 vial
    gives `clean_dict()` with no raise and `_tray_pos == {"1,1,1": label}`.
- Decision: default.

#### H11 sample `tray_new_position` blocks superseded candidates

- Root cause: `servers/sample/archive_driver.py:774-776` blocks inside the search loop.
- Reach: latent (all shipped trays are homogeneous VT54).
- Fix: record the winning position and block only it after the loop.
- Test: new `servers/sample/tests/test_tray_new_position.py`:
  `Archive.tray_new_position(SimpleNamespace(positions=Positions(trays_dict={1:{1:VT15()},2:{1:VT54()}})), req_vol=1.0)`
  returns tray 2/slot 1/vial 1, tray 1 `blocked == [False]*15`, tray 2 `blocked[0]`.
- Decision: default.

#### P4 `MetaProcessor` never sees orchestrator `global_params` (parent)

- Root cause: `helao/helpers/processors.py:89-91` compares the class name to `"orch"`;
  the orchestrator class is now `OrchHost`. Deployment-A's
  `processors/append_ref_vshe.py` therefore writes `ref_vshe: null`.
- Reach: latent (Deployment-A's hook wiring is commented out).
- Fix: `getattr(core, "global_params", None) or {}`.
- Test: `helao/core/tests/test_hooks_loader.py`:
  `object.__new__(OrchHost)` with `global_params={"last_OCP_V": 0.5}`; the processor
  sees `{"last_OCP_V": 0.5}` (today `{}`).
- Decision: default.

#### A4 muxvalve `get_valve` ignores the MUX (Deployment-A)

- Root cause: `servers/muxvalve/muxvalve_server.py:48-51` matches only the valve number.
- Reach: latent (single MUX configured).
- Fix: match `(mux_id, valve_number)` as `set_valve_number` does (`:124-132`). This is
  a one-line change, with no helper extraction unless the test needs one.
- Test: new `servers/muxvalve/tests/test_valve_name.py`. With
  `mux_map={"a":("m0",1),"b":("m1",1)}`, looking up `("m1",1)` gives `"b"`; today
  `"a"`.
- Decision: default.

#### C4 ecms_ms: inject reads only YAML; `from_s3 --repair-legacy-keys` clobbers snapshots (Deployment-C)

- Root cause:
  - `scripts/ecms_ms/inject.py:157-171` globs only `*-exp.yml`, and `:211-226` always
    writes YAML.
  - In `from_s3.py`, `snapshot_metas` (`:473-498`) overwrites existing snapshots, and
    the flag (`:673-680`, `:764-771`) runs before the syncer has re-uploaded.
- Reach: inject is latent (no JSON-era zips exist). `from_s3` is a manual operator CLI.
- Fix:
  - `_find_exp_yml` uses `meta_glob(exp_dir, "exp")`. For `.json` use
    `read_meta`/`write_meta`; keep the YAML round-trip path.
  - Remove `--repair-legacy-keys` and its block, and print a hint to run `repair_legacy`
    after sync. `snapshot_metas` skips existing files.
  - Update the docstring and README `:92`, `:105`.
- Test:
  - (a) `tests/test_inject.py` variant with native `-exp.json`: inject succeeds, and
    `process_order_groups["0"] == [0, 1]`.
  - (b) `tests/test_from_s3.py`: two `snapshot_metas` calls, with `experiment_list`
    removed between them. The snapshot still holds it.
- Decision: 10. Also flag in the README: post-2026-10-23 unpaired ECMS sequences
  (unzipped) can only go through `from_s3`.

#### E2 oceandirect drops `dev_ts_ns` per packet (Deployment-E)

- Root cause: `servers/oceandirect/oceandirect_driver.py:1415-1422` drops the column
  when every value is `None`. The readers then misalign it across packets.
- Reach: latent (the buffered path always yields stamps; unused by experiments).
- Fix: drop the column only when `dev_timestamps is None`. Also guard the empty
  timestamp list at `oceandirect_server.py:194` (`if timestamps and all(...)`).
- Test: extend `servers/oceandirect/tests/test_oceandirect_driver.py`:
  `build_rows([s], [t], dev_timestamps=[None])["dev_ts_ns"] == [None]`; today the key
  is absent.
- Decision: default.

#### B3 (optional, low) test_station first poll reads `get_flow` twice (Deployment-B)

- Fix: remember the composite read before the loop (`done = {"flow"}`), and drop the
  dead `if tag in record` lines. Test: the first `_poll` calls `read` 4 times (today 5).
  Skip it if the plan runs long.

## Work units and order

| # | unit (repo) | bugs, in order | depends on |
|---|---|---|---|
| U0 | hte (mfc only) | H1 | none: first, on `origin/main` |
| U1 | parent | P1, P2, P3, P4 | none |
| U2 | hte | H2, H3; then H4, H5, H7, H8, H9, H10, H11 | U1 (H9 needs P2; H10's test exercises P3) |
| U3 | Deployment-C | C1, C2, C3; then C4 | none |
| U4 | Deployment-B | B1, B2; then B3 (optional) | none |
| U5 | Deployment-A | A2; then A3, A4 | U1 (A3 needs P2; the aligner row and `ref_vshe` are fixed by P1/P4, no edit here) |
| U6 | Deployment-E | E1; then E2 | none |

Cross-repo dependencies:

- **Motion timeout parity:** H3 and A2 implement the shared rule identically (exception
  type, message prefix, busy release). They are reviewed side by side and pushed
  together.
- **Parent first for shared fixes:** P1 fixes the aligner rows in hte and Deployment-A
  and the base pstat text; P4 fixes Deployment-A's `ref_vshe`; P2 is required by H9/A3;
  P3 backs H10. README notes in hte/Deployment-A that describe these defects are updated
  in those repos once U1 lands.
- **mfc consumers:** the hte mfc server is also launched by Deployment-F's config;
  that repo needs no edit.

## Verification (per unit)

- Each new test fails on the pre-fix code and passes after. Mutation check: revert only
  the fix lines and confirm the test goes red. For Deployment-C, mutation checks are
  static or fully monkeypatched; never run a pre-fix CLI or a converter with production
  defaults.
- The repo's existing suite stays green. The parent runs `run_unit_tests.py` and
  `run_tests.py`; each nested repo runs its `tests/` and server `tests/`. The
  `test_readme_outputs.py` output-catalog guard stays green, and so does the PAL golden
  master script.
- README `## Outputs`/`## Notes`: follow the `helao-output-catalog` skill procedure for
  each changed writer. Remove the resolved defect bullets and correct rows: mfc
  `gas`/`setpoint`, aligner `err_code`, PAL record count, olecom files, analysis
  `output_type`/`agg_*`, sample `_tray_pos`, leak-test row, live keys,
  `source_created_utc`, `dev_ts_ns`, box_notes crop name, xafs `campaign_*`.
- Separate reviewer pass per unit; `black` on changed files before each commit.
- Station-check rows (added to the station checklist; run after deploy approval):

| row | station | check |
|---|---|---|
| motion timeout raise | one galil station; Deployment-A motion | a manual orchestrated move with a short `timeout`. Expect: the orch pauses and re-queues (no E-STOP); motors halted; the next move accepted; resume re-dispatches cleanly |
| hte analyses port | eche10 (user-confirmed), wired as in "Analysis trigger", `local_only: true` | finish one `UVIS_T` and one `ECHEUVIS_multiCA_led` sequence. After sync, the SYNC log shows both dispatches, and ANA writes one analysis per data process with the new `output_type` and plausible `agg_*` |
| UR offsets | Deployment-B robot arm | `robot_mode` matches the pendant, and `is_moving` toggles during a jog for the controller's PolyScope version |
| leak test | Deployment-B station | a mode-5 run writes `leak_test_passed: true` and one final row |
| mfc | ccsi2 or ecms3 | after a forced odd-length reply, a controller still publishes the real `gas` and `setpoint` |
| olecom | EC-Lab Windows host | a real run tracks and uploads `.mps/.mpr/.mpt` |

## Risks

- **Motion timeout now raises.** A stuck homing move or stall that today silently
  continues now pauses the orchestrator and re-queues the move. The raised action's
  server-side session stays open until it is reconciled at the next server startup
  (`action_host.py:1486-1505`). The station row confirms a resume is accepted. On
  Deployment-A, a failed last query at the deadline moves from E-STOP to pause and
  re-queue.
- **PAL record count.** Jobs with `repeat`/`totalruns > 1` emit one `-act` per
  palaction. Downstream counts and upload volume rise for such jobs; none are produced
  by tracked experiments.
- **ErrorCodes render change.** Logs, the pstat UI text and new aligner rows lose the
  `ErrorCodes.` prefix. Rows written since the 3.12+ env bump keep it; consumers accept
  both.
- **olecom upload volume.** `.mpr` grows with run length, roughly doubling per-action
  upload bytes on long runs.
- **mfc branch overlap.** The other session's hte branch edits the same driver area.
  Building on `origin/main` (which already has b143c278) means that session rebases
  onto this fix.
- **Codehash re-stamps.** C1/C2 and H5 change `analysis_codehash`, and so future
  `analysis_uuid`s.

## Delivery

- One commit per repo per unit (U0 may be its own hte commit). Never `git add`/commit
  from subagents; commits happen on the main thread.
- No push without user approval. A push to a default branch is a deploy: note1 autopull
  pulls it within about a minute, and other stations need an explicit update.
- hte: the shared clone is on another session's `fix/alicat-meter-status`, and the
  Deployment-F clone is on its MFC feature branch. Never switch either. Do hte work in a
  `git -C helao/deploy/hte worktree add` of `origin/main`, and do not touch the
  Deployment-F clone. Other nested repos: check branch and status before each commit.
- Parent commits are on `unstable` and never name a private deployment; nested-repo
  commits in public hte do not either.

## Open questions

None. H5 station config: `eche10.yml` (user-confirmed 2026-11-18); both dangling postseq paths (`ECHEUVIS_postseq`, `UVIS_T_postseq`) are deleted (user-confirmed).
