# Framework hte Migration — Wave 4: config cut-over rollout (design)

**Date:** 2026-06-25
**Branch:** `feat/framework-hte-wave4-config-rollout`
**Cycle:** Gated hte production migration, Wave 4. Cuts every hte config's generic
server entries over to the framework apps and removes the now-dead hte host duplicates.
Enabled by SP-ORCH-5 (the framework orchestrator is live-verified end-to-end on `test`).

## 1. Scope

21 hte configs reference the generic host apps. For each:
- `fast: async_orch2` -> `fast: orchestrator` + `deployment: framework`
- `bokeh: standalone_operator` -> + `deployment: framework`
- `bokeh: action_visualizer` -> + `deployment: framework`
- `bokeh: live_visualizer` -> + `deployment: framework`
(commented entries left untouched; no hte config uses `bokeh: data_browser`.)

Delete the 5 dead hte host duplicates (now provided generically by
`helao/framework/app/servers/`):
`servers/orchestrator/async_orch2.py`, `servers/operator/standalone_operator.py`,
`servers/visualizer/{action_visualizer,live_visualizer,data_browser}.py`.

Per-instrument `*_vis.py` stay in hte (loaded by the framework visualizer host via
`mount_visualizers`, resolved against `CONFIG["deployment"]=hte`). Action servers stay on
the hte deployment path. The transform mirrors the proven `test` deployment cut-over.

## 2. Validation (static; live launch is Wave 5 / per-station hardware)

- Every config parses (`read_config`).
- Every `deployment: framework` server resolves to an importable framework module with the
  right factory (`makeApp`/`makeBokehApp`): 21/21 configs, 67 framework-routed entries — all
  resolve. (orchestrator/standalone_operator/action_visualizer/live_visualizer are Linux-
  importable; action servers + per-instrument vis are not re-validated here — hardware deps.)
- Full framework suite + boundary stay green (Wave 4 touches no framework code).

## 3. Out of scope

- Live launch / hardware bring-up (Wave 5, per station, Gate C; Windows Galil/Gamry).
- Any framework code change.

## 4. Done criteria

- 21 configs cut over; 5 dead host files deleted; no residual `fast: async_orch2`.
- Static validation passes; suite + boundary green; scope = hte configs + the 5 deletions
  + this doc only.
