# P3a galil slice-4 — aligner Bokeh/D6 extraction (construct-test tier)

> Sub-slice of the galil special-split (roadmap `2026-07-18-P3a-special-splits-roadmap.md`
> §"galil slice 4"). **HIGHEST RISK; NOT Linux-runtime-verifiable** (needs a live
> Bokeh session + an at-station plate-alignment dry-run). Built construct-test-only
> per an explicit user decision (2026-07-22), accepting rework risk if the design
> shifts at station. **Do NOT merge until an at-station alignment dry-run passes.**

## The D6 violation being removed

The Galil motion **driver** currently (a) constructs a Bokeh `Server` + `HelaoVis`
(`start_aligner`/`makeBokehApp`), (b) holds an action `Active` (`self.aligner_active`),
and (c) exposes a `base` property that exists solely so the Bokeh aligner
(`layouts/aligner.py`, 1685 LOC) can reach `motor.base.helaodirs` / `motor.base.get_main_error`.
A hardware driver owning a UI server + an Active + a Base back-reference is the D6
"Bokeh-Server-in-driver" violation.

## Design — `AlignerMotorContext` + vis-layer `AlignerHost` (minimal-aligner-edit)

Chosen because the 1685-LOC aligner cannot be runtime-verified: keep its body
almost untouched by handing it a **context object in place of the raw driver**.
The aligner still calls `self.motor.<x>`; `motor` is now the context, which:

- **Delegates to the legacy driver** (live, cache-nothing): motion (`_motor_move`,
  `query_axis_position`), `transform`, calibration (`plate_transfermatrix`,
  `dflt_matrix`, `update_plate_transfermatrix`, `save_transfermatrix`), and the
  **driver-owned mutual-exclusion/motion flags** `blocked` (shared lock with
  `_motor_move` D:558-567 — MUST stay on the driver) and `motor_busy`.
- **Owns** the aligner-session state the hardware driver should never hold:
  `base` (the real `Base`), `aligner_active` (the `Active`), `aligner_plateid`,
  `aligning_enabled`, and the `aligner` back-ref (A:104 `self.motor.aligner = self`).

The **`AlignerHost`** (vis layer, `helao/hexagon/adapters/vis/galil_aligner_host.py`)
owns the Bokeh `Server` + `HelaoVis` construction (relocated `start_aligner` +
`makeBokehApp`) and the aligner-orchestration verbs the server calls
(`run_aligner_precheck`, `start_aligner_run`, `stop_aligner`). It builds the
`AlignerMotorContext(driver, base)`, and on `Aligner` construction wires the
driver's position-notify sink to the aligner's `motorpos_q`.

### Driver after slice-4
- **Removed:** imports `Server` (D:41), `HelaoVis` (D:47), `Aligner` (D:56);
  methods `start_aligner`, `makeBokehApp`, `start_aligner_run`,
  `run_aligner_precheck`, `stop_aligner`; the `base` property (D:139-147);
  attrs `bokehapp`, `aligner_active`, `aligner_plateid`, `aligning_enabled`;
  the `connect()` aligner-start block (D:272-273).
- **Kept:** `blocked`, `motor_busy` (motion state); `_base_hook` (its own
  `connect()` reads `helaodirs`/`server_cfg` off it — unrelated to the aligner).
- **Changed:** `self.aligner` becomes an optional **position-notify sink**
  (an object with `motorpos_q`, or `None`), set by the host. `update_aligner`
  (D:1275-1278, called from `query_axis_position` D:1042 / `query_axis_moving`
  D:1098) pushes to that sink. `shutdown`'s `self.aligner.IOtask.cancel()`
  (D:1272) moves to `AlignerHost.shutdown()`, invoked from the server shutdown.

### Aligner (`layouts/aligner.py`) edits — kept minimal
- `Aligner(vis, motor)` unchanged signature; `motor` is now the context.
  Every `self.motor.<x>` continues to resolve (context provides the surface).
- A:104 `self.motor.aligner = self` still valid (context stores it + the host
  reads `aligner.motorpos_q` to wire the driver sink).
- Teardown A:1203-1206 unchanged: `aligner_active=None`/`aligner_plateid=None`/
  `aligning_enabled=False` hit context state; `blocked=False` delegates to the
  driver (correctly clears the shared lock).

### Server (`servers/action/galil_motion.py`) edits
- After `connect()`, if `enable_aligner` + `galil_enabled`, construct
  `AlignerHost(driver=app.driver, base=app.base, config=...)` and start it
  (replaces the driver's self-start).
- `run_aligner`/`stop_aligner`/`setmotionref` endpoints call the **host**
  (`host.run_aligner_precheck()`, `host.start_aligner_run(active)`,
  `host.stop_aligner()`) instead of `app.driver.*`. The `Active` is still built
  by the endpoint (`app.base.contain_action`, S:156) and handed to the host.
- Register `host.shutdown()` on the FastAPI shutdown path.

## Construct-test coverage (Linux)
- Driver imports with NO bokeh/aligner symbols; constructs; `hasattr(driver,
  "start_aligner") is False`; `hasattr(driver, "base") is False`;
  `aligner_active`/`bokehapp` gone.
- `AlignerMotorContext` delegates every driver verb/flag (fake driver records
  calls); owns base/active/plateid/aligning_enabled; `blocked` r/w hits the
  driver.
- `AlignerHost` builds a Bokeh `Server` object (no `.start()`), wires the sink,
  exposes the 3 orchestration verbs.
- Aligner still resolves `self.motor.<x>` against the context (smoke-construct
  with a fake vis + context, guarded — the real `Aligner.__init__` starts an
  asyncio task + builds Bokeh layout, so this may stay a surface-audit rather
  than a live construct; decide during impl).

## AT-STATION GATE (do first before merge)
Real Bokeh session on the galil/aligner station: open the `/Aligner` page,
run a plate alignment, confirm motion + live position widgets + calibration
write (`-plate_calib`) + Active finish behave byte-identically to legacy, and
that estop/`blocked` still serialize aligner-vs-motion. Only then merge.
