# CARDS Refactor — P4: `HelaoDriver` ABC migration (Separation + Resilience)

> Deployment aliasing: this doc lives in the **public** parent repo, so private deployments
> are referred to as **Deployment-A/B/C/D**. Public deployments keep their names (`hte`, `test`).
> The alias key is held privately, out of the repo.

**Status:** EXECUTED 2026-07-11 (was: draft). 22 drivers migrated to the ABC across W0–W5,
each Opus-reviewed for behavior-preservation and pushed on `feat/cards-refactor`. All
construction-proof; Windows/hardware drivers require a station smoke test before production
reliance. P4 does **not** wait on 3e (soak-gated, orthogonal).

### Execution outcome (2026-07-11)
- **Migrated + reviewed + pushed (22):** W0 retired dead legacy advantech/stenner pairs
  (Deployment-A). W1 HTEdata, hte Calc, Deployment-A Calc + active-learning driver. W2 cm0134,
  axiscam. W3 sprintir, alicat, legato, simdos, mecom. W4 Deployment-B actuator/robotarm/leancat,
  galil_io, Deployment-A thorlabs. W5 elveflow, nidaqmx, galil_motion, spectral_products.
- **Bugs caught by review + fixed:** hte Calc CRITICAL (endpoint passed FastAPI fn-args instead of
  `action_params` → defaults under orch dispatch); legato CRITICAL (dropped synchronous start-status
  publish → premature action finish); shutdown-ordering regressions (legato/alicat); spectral dropped
  hang-backstop. nidaqmx `/cellIV` and spectral stop-paths were pre-existing DEAD code — reconstructed
  (flagged NEW/unverified, station smoke required).
- **Systematic rules learned (in the weaning spec):** K7 params MUST come from `action_params` not
  fn-args; `async_shutdown` = safe_state then disconnect (sync `shutdown()` no-op); synchronous
  state-transition publishes must not defer to the poller; poll cadence now config-driven
  (`polling_time`) — set per-server to the legacy Hz at station bring-up.
- **EXCLUDED — archive_driver.py:** OQ-4 resolved **NO**. It is not a device driver — 2448 lines of
  sample/tray bookkeeping (UnifiedSampleDataAPI + state files + in-memory slots, zero hardware).
  Forcing the ABC (connect/stop/reset for no device) is semantically wrong (same principle as
  bare-helper sims); a separate approved plan hoists it to a sample server. Left legacy.
- **BLOCKED — pal_driver.py (needs a design decision, not a mechanical migration):** `_PAL_IOloop` is
  the sole process-lifetime execution path for all 14 action handlers, creates its own `Active`
  (endpoint returns before the job runs), and `_sendcommand_main` threads `self.active` through ~20
  order-dependent sample-DB mutations with a mid-loop `active.split()`. A faithful K7b port =
  rewriting the physical sample-tracking pipeline into an Executor state machine — unverifiable
  without PAL hardware. Deferred with two candidate designs: (1) Executor injects `active` into the
  driver at job-start (partial K7b, lowest-rewrite); (2) full Executor state-machine decomposition.
- **Frozen:** dbpack (deprecated). **Exempt:** `test` sims (bare helpers).

---

## 0. What P4 is, in one paragraph

The root finding of `CARDS_AUDIT.md` is a two-population driver base: **compliant** drivers
(`config: dict` + `HelaoDriver` ABC + `DriverResponse`, paired with an `Executor` per action)
vs **legacy god-class** drivers (`action_serv: Base`, reach into the server, spin a persistent
loop in `__init__`). P4 migrates the legacy population to the ABC. This lifts **Separation**
(driver no longer knows the server) and **Resilience** (per-action lifecycle replaces a
process-lived loop; construction stops opening resources / spawning tasks).

---

## 1. Decisions (made, evidence-backed — 2026-07-10, verified on tip `dece5a99`)

### D1 — The construction seam is already dual-convention and is NOT touched by P4
`helao/core/servers/base_api.py:661-676` instantiates each `driver_classes=[X]` entry by
branching on the ABC:
```python
if issubclass(driver_class, HelaoDriver):
    driver_inst = driver_class(config=self.server_params)   # compliant path (+ poller_class wiring)
else:
    driver_inst = driver_class(self.base)                    # legacy action_serv path
```
Migrating a driver flips it from the `else` branch to the `if` branch by subclass check alone.
**The `makeApp` call site stays `driver_classes=[X]` verbatim; base_api is not edited.** This is
the SP8 dual-convention wiring, already landed. Consequence: P4 is per-driver and incremental
with zero shared-framework churn — no big-bang.

### D2 — The substantive work is IOloop → Executor / DriverPoller, not the signature swap
The signature change (`action_serv` → `config`) is mechanical. The real work is relocating the
driver's long-running async work, of which legacy drivers have **two distinct kinds** that map to
**two different framework homes**:

| Legacy loop kind | What it does | Framework home | Lifecycle owner |
|---|---|---|---|
| **action-scoped IOloop** | records/services data *while an action runs*, gated by a boolean flag the endpoint flips | an `Executor` subclass in the **action server** (`oneoff=False`, `_poll` at `poll_rate`) | the `Active` action (`active.start_executor` → poll → finish/cancel) |
| **always-on poll** | continuously publishes a live value (e.g. `co2_ppm`) to the buffer regardless of any action | `DriverPoller.get_data` (`helao/core/drivers/helao_driver.py:141-231`) | the poller, wired by base_api when `poller_class` is passed |

Both are started today via `create_task(...)` **in `__init__`** — that call *is* the loop, and it
is exactly the SP8 lifecycle hazard. Migration = delete the `__init__` `create_task`; re-home the
loop body into an `Executor._poll` (action-scoped) or `DriverPoller.get_data` (always-on);
construction becomes pure (store config), `connect()` opens the device.

Answer to "does P4 migrate legacy code to the Executor framework used by `gamry_server2.py`?":
**yes — that is P4's spine.** `gamry_server2.py` is the reference shape: `class GamryExec(Executor)`
with `_pre_exec`/`_exec`/`_poll`/`_post_exec`/`_manual_stop`, `self.driver = self.active.driver`,
launched by `active.start_executor(executor)`. Legacy IOloops collapse into that.

### D3 — Most hardware drivers are already HYBRID; their P4 work is "finish the split", not greenfield
Evidence (grep of `Executor` + `create_task`/thread + loop defs per legacy driver, 2026-07-10):
10 of the legacy hardware drivers **already import `Executor` and define `*Exec` classes** for
their per-action work, yet **still spawn always-on poll loops in `__init__`**. For these the
migration is bounded: move the residual `__init__` loop to `DriverPoller`, flip the signature,
return `DriverResponse` from the lifecycle methods. Greenfield Executor authoring is only needed
for the handful with no `Executor` at all.

### D4 — Migrate lowest-risk first; production Windows drivers last and hardware-gated
Ordering by (a) can it run/verify on this Linux box, (b) blast radius, (c) production criticality.
Waves in §4. Pilot = the pure-Python drivers (no hardware, no loop) to prove the signature +
`DriverResponse` + endpoint-unwrap pattern with zero lifecycle risk, then a hybrid driver to prove
the `__init__`-loop → `DriverPoller` relocation, then hardware/prod.

### D5 — Superseded duplicates are RETIRED, not migrated
`Deployment-A` carries superseded driver duplicates already replaced by compliant versions
(`advantech/driver.py`, `stenner/driver.py`). Their legacy twins are deleted (with config
confirmation that nothing references them), not migrated. `hte` `dbpack_driver.py` stays
**frozen/deprecated** — do not migrate (superseded by `sync_driver.py`).

### D6 — `test` sims stay ABC-exempt
`test` deployment sims (`cpsim`, `gpsim`) are deliberately bare helpers honored by the Executor
contract; they are **not** in P4 scope (SP8 decision, unchanged).

### D7 — Per-driver behavior gate before each merge
Each driver migration ships only after: (a) unit suite green, (b) `import_smoke` constructs the
affected `makeApp` identically to baseline, (c) for Linux-runnable drivers, an action exercised
end-to-end against a sim/loopback with output compared to a pre-change capture, (d) for
hardware-only drivers, construction-time proof + a station smoke-test checklist deferred to the
first live run (same gating model as the hte migration waves).

---

## 2. Current-state evidence (verified on tip `dece5a99`, 2026-07-10)

- ABC contract: `helao/core/drivers/helao_driver.py:85-138` (`HelaoDriver`: `connect`/`get_status`/
  `stop`/`reset`/`disconnect` → `DriverResponse`); `DriverPoller:141-231` (`get_data`, owns its task);
  `DriverResponse:57-82`.
- Executor contract: `helao/helpers/executor.py:22` — `__init__(active, oneoff=True, poll_rate=...)`,
  overridable `_pre_exec`/`_exec`/`_poll`/`_post_exec`/`_manual_stop`, plus `set_*` injectors;
  `oneoff=True` runs `_exec` once, `oneoff=False` loops `_poll`.
- Reference compliant server: `helao/deploy/hte/servers/action/gamry_server2.py` — `GamryExec(Executor)`,
  `active.start_executor(executor)` (lines ~690/755/820).
- Reference IOloop legacy: `helao/deploy/hte/drivers/sensor/sprintir_driver.py` — `IOloop` (:175) started
  by `create_task` in `__init__` (:153), `poll_sensor_loop` (:284) always-on, flag `IOloop_run` (:150).

---

## 3. Per-driver migration table (the effort/risk axis)

Columns: **Driver** · **init conv** · **loop kind(s)** · **has `Executor` today?** · **target
(Executor / DriverPoller)** · **action-server endpoint delta** · **wave**. Endpoint-delta grades:
- **none** — no action server, or driver has no per-action endpoints.
- **light** — endpoints already call the driver thinly; only unwrap `DriverResponse` / drop `active` arg.
- **medium** — endpoints pass `active` into the driver and the driver enqueues data → move enqueue into an `Executor` (author/extend an `*Exec`).
- **heavy** — endpoints reference driver-owned dynamic types as parameter annotations, or wrap a persistent IOloop via flags → rework endpoint signatures + full Executor lifecycle.

### hte (public)
| Driver | init | loops | Exec now? | target | endpoint delta | wave |
|---|---|---|---|---|---|---|
| `data/calc_driver.py` Calc | action_serv | none | no | oneoff Executor (or plain call) | **medium** (`calc_server.py` passes `active`, driver enqueues) | W1 pilot |
| `data/HTEdata_legacy.py` HTEdata | action_serv | none | no | none (pure query) | **light** (`HTEdata_server.py`) | W1 |
| `sensor/axiscam_driver.py` AxisCam | action_serv | none | yes(5) | keep Exec; flip sig | **light** (`cam_server.py`) | W2 |
| `sensor/cm0134_driver.py` CM0134 | action_serv | 1 always-on | yes(5) | DriverPoller + keep Exec | **light** (`co2sensor_server.py`) | W2 |
| `sensor/sprintir_driver.py` SprintIR | action_serv | IOloop + poll | yes(5) | Exec(`_poll`) for IOloop + DriverPoller for always-on | **heavy** (`o2sensor_server.py` flag-driven) | W3 |
| `mfc/alicat_driver.py` AliCatMFC | action_serv | poll | yes(7) | DriverPoller + keep Exec | **medium** (`mfc_server.py`) | W3 |
| `pump/legato_driver.py` KDS100 | action_serv | poll | yes(5) | DriverPoller + keep Exec | **medium** (`syringe_server.py`) | W3 |
| `pump/simdos_driver.py` SIMDOS | action_serv | poll | yes(5) | DriverPoller + keep Exec | **medium** (`diapump_server.py`) | W3 |
| `temperature_control/mecom_driver.py` MeerstetterTEC | action_serv | poll | yes(6) | DriverPoller + keep Exec | **medium** (`tec_server.py`) | W3 |
| `io/galil_io_driver.py` Galil | action_serv | signal+sensor loops | yes(3) | DriverPoller + Exec | **heavy** (`galil_io.py` uses `app.driver.dev_*items` as endpoint annotations) | W4 |
| `io/nidaqmx_driver.py` cNIMAX | action_serv | 16 loop refs | yes(3) | DriverPoller + Exec | **heavy** (`nidaqmx_server.py`) — Windows-only | W5 (hw) |
| `motion/galil_motion_driver.py` Galil | action_serv | bokeh thread | no | Executor (build) | **heavy** (`galil_motion.py`) — Windows(gclib) | W5 (hw) |
| `spec/spectral_products_driver.py` SM303 | action_serv | 10 loop refs | no | Executor (build) | **heavy** (`spec_server.py`) — Windows(ctypes) | W5 (hw) |
| `robot/pal_driver.py` PAL | action_serv | 36 loop refs | no | Executor (build), large | **heavy** (`pal_server.py`) — Windows, **PROD CRITICAL** | W6 (hw, last) |
| `data/archive_driver.py` Archive | action_serv | data threads | no | ABC lifecycle; no measurement loop | **medium** (`sample_server.py` + archive routes) — **PROD CRITICAL** | W6 (hw, last) |
| `data/dbpack_driver.py` DBPack | — | — | — | **FROZEN — do not migrate** | — | — |

### Deployment-A (private)
| Driver | init | loops | Exec now? | target | endpoint delta | wave |
|---|---|---|---|---|---|---|
| `calc_driver.py` Calc | action_serv | none | no | oneoff Executor / plain | **medium** | W1 |
| `ml_driver.py` OerAL | action_serv | none | no | none (pure compute) | **light** | W1 |
| `elveflow_driver.py` MuxDRI | action_serv | none | no | Executor if endpoint streams | **light/medium** — Windows(ctypes) | W5 (hw) |
| `thorlabs_kinesis.py` ThorlabsMotor | action_serv | bokeh thread | no | Executor (build) | **heavy** — vendor(pylablib) | W4 |
| `advantech_driver.py` USB5830 | action_serv | poll | yes(3) | **RETIRE** (superseded by `advantech/driver.py`) | delete + config check | W0 |
| `stenner_s3001.py` / `_blocking.py` | action_serv | gather/none | no | **RETIRE** (superseded by `stenner/driver.py`) | delete + config check | W0 |

### Deployment-B (private)
| Driver | init | loops | Exec now? | target | endpoint delta | wave |
|---|---|---|---|---|---|---|
| `actuator/actuator_driver.py` ActuatorDriver | action_serv | poll | no | Executor (build) + DriverPoller | **medium** | W4 |
| `robotarm/robotarm_driver.py` Ur10eRobotArmDriver | action_serv | poll | no | Executor (build) | **medium/heavy** | W4 |
| `leancat/leancat_driver.py` OpcUaStationDriver | action_serv | poll | no | DriverPoller + Executor | **medium** | W4 |

### Already compliant — verify-only (no migration)
`hte`: gamry, biologic, kinesis, andor, synaccess/netbooter, power_supply, leancat.
`Deployment-A`: `advantech/driver.py`, `stenner/driver.py`. Action: confirm they still match the ABC
after any shared-helper changes; no code edits expected.

---

## 4. Waves (each independently shippable; push per wave, per [[cards-audit]] cadence)

- **W0 — Retire superseded duplicates (Deployment-A).** Delete legacy `advantech_driver.py` +
  `stenner_s3001*.py` after confirming no config/import references. Lowest risk, immediate Separation win.
- **W1 — Pure-Python pilot (Linux-runnable).** `hte` Calc + HTEdata, `Deployment-A` Calc + ml. Proves
  signature + `DriverResponse` + endpoint-unwrap/oneoff-Executor with no lifecycle hazard. Full e2e
  runnable on this box. This wave sets the migration template doc.
- **W2 — Easy hybrids (Linux-runnable / no always-on hazard).** `hte` axiscam (no loop), cm0134
  (single poll → DriverPoller). Proves the `__init__`-loop → `DriverPoller` relocation cheaply.
- **W3 — Serial/modbus hybrids.** `hte` sprintir (the canonical IOloop→Executor), alicat, legato,
  simdos, mecom. Each: IOloop→`Executor._poll`, always-on→`DriverPoller`, kill `__init__` create_task.
- **W4 — Non-prod full builds.** `hte` galil_io (heavy annotations), `Deployment-A` thorlabs_kinesis,
  `Deployment-B` actuator/robotarm/leancat. Executor authored where absent.
- **W5 — Windows hardware, non-critical.** nidaqmx, galil_motion, spectral_products, `Deployment-A`
  elveflow. Construction-proof on Linux; station smoke-test checklist deferred to first live run.
- **W6 — Windows hardware, PRODUCTION CRITICAL, last.** PAL (36-loop driver), Archive. Separate careful
  review each; live-hardware gated. Do not batch with anything else.

---

## 5. Per-driver migration recipe (the repeatable template W1 establishes)

1. **Freeze behavior:** capture a pre-change reference (unit + e2e/loopback for Linux-runnable;
   construction snapshot for hw-only).
2. **Signature:** `__init__(self, action_serv: Base)` → `__init__(self, config: dict = {})`; store
   config, do **not** open the device or `create_task` here.
3. **Lifecycle:** implement `connect`/`get_status`/`stop`/`reset`/`disconnect` returning
   `DriverResponse`; move device-open into `connect()`.
4. **Loops:**
   - always-on poll → `DriverPoller.get_data`; pass `poller_class` to `makeApp`'s `BaseAPI(...)`.
   - action-scoped IOloop → an `Executor` subclass in the action server (`oneoff=False`, body of the
     old loop becomes `_poll`; start/stop flags become `_pre_exec`/`_manual_stop`).
5. **Endpoints:** replace `app.driver.<method>(active/**params)` + in-driver enqueue with
   `active.start_executor(<Exec>(active, ...))`; unwrap `DriverResponse`; remove endpoint parameter
   annotations that referenced driver-owned dynamic types (pin them explicitly).
6. **Gate (D7)** then commit + push that wave.

---

## 6. Risk & rollback

- **Per-driver, per-wave commits** → rollback is a single revert; the dual-convention seam means a
  half-migrated fleet runs fine (compliant and legacy drivers coexist under `driver_classes`).
- **Highest risks:** (a) `__init__`-loop relocation changing timing/ordering of first data sample —
  mitigated by the pre-change capture gate; (b) endpoint annotation rework on `galil_io`/`nidaqmx`
  changing the OpenAPI/param surface — mitigated by `import_smoke` param-shape diff; (c) PAL/Archive
  are production-critical and Windows-only — isolated to W6 with live gating, never batched.
- **3e independence:** enforcement flip is orthogonal; P4 does not depend on it and vice-versa.

## 7. Open questions (append to `.omc/plans/open-questions.md`)
- W1 Calc/ml: is a `oneoff` Executor warranted, or is a plain synchronous `DriverResponse` call the
  cleaner endpoint shape? Decide during the pilot from the reference capture.
- Archive (W6): it has no measurement loop but owns sample/data-management state co-located with the
  server — confirm the ABC boundary before touching (it may be a `HelaoDriver` in name only).
