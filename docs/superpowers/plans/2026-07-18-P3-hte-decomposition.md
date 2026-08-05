# P3 — hte Deployment Migration: Decomposition & Sequencing

> **Status:** planning. Locks sub-project boundaries, dependency order, and the Linux/hardware gate split for P3 of the hexagonal rewrite (master spec: `docs/superpowers/specs/2026-07-16-framework-hexagonal-rewrite-design.md`, §P3 line 557).
>
> This is a **sequencing overview**, not an executable task plan. Each sub-project gets its own `docs/superpowers/plans/2026-07-18-P3<x>-*.md` written just-in-time (later plans depend on earlier outcomes — e.g. P3b's action-server list depends on which drivers ported cleanly in P3a). Mirrors the P2a→P2e cadence.

## Goal

Migrate the `hte` deployment onto the hexagon composition, station-by-station, at parity. Reach **Linux-green** for everything Linux can certify (adapters construct + import-sweep, exp/seq libraries import + collision-check, vis mounts, endpoint-parity static+runtime diff on the one sim-capable config, port wiring complete) and hand each station to its **at-station HARDWARE gate** (smoke + soak + on-station golden diff) during its cut-over window.

## The audited surface (spec §8.1, frozen maps `deploy-hte-servers.md` + `deploy-hte-drivers-A/B.md`)

- **23 action-server modules**, **241 static endpoints** + config-driven `analyze_<name>` (ANA). *(237 when this plan was written; +4 on 2026-08-04 — the private `POST /get_digital_outs` + `POST /set_digital_out` pair on `galil_io` and `nidaqmx_server`, backing the engineering control panel. Checklists re-frozen; see master-spec Amendment 1 §5.1.)*
- **~18 Hardware-adapter port targets** (of 23 driver classes: DBPack dead, Leancat broken-orphan, Calc→domain service, Archive→SampleState, sample_shim already-shaped). **15 Linux-importable/testable, 8 Windows-only** (Gamry/Biologic/SM303/Andor/galil-io/galil-motion/NI/PAL — need lazy adapter-scoped vendor imports, §11.1).
- **242 experiment fns / 13 modules; 86 sequence fns / 14 modules** (flat name-keyed registries; two known collision hazards).
- **13 config-selected `*_vis` modules** (+ 2 thin hosts + data_browser shim); **4 operator scripts**. *(As of 2026-08-04 also **13 config-selected Reflex panel modules** and a third vis key `control_vis` in **15 of 21 configs** with its `control_visualizer` host. Both are P7-UI subjects under D9, not P3 subjects — but they are P3 **inventory**: see `_dependent_surface.md`'s 2026-08-04 addendum.)*
- **21 station configs**; only `gamry.yml` declares `simulation: true`. *(4 now also declare a `reflex:` server — `clad`, `eche10`, `hispec`, and the `htereflex` dev config — each claiming `port` **and** `port + 1`. Those three stations' cut-over runbooks need a `build_reflex_bundle.py` step; the other control-panel stations need only a visualizer restart.)*

## Hard constraint: the Linux / hardware gate split

hte configs use Windows `root:` paths and wrap Windows-only vendor backends (gclib, comtypes/GamryCOM, NI-DAQmx). **They do not launch on Linux.** Consequence (spec §6.6, §11, A2):

- **Linux-capturable (this session, no hardware):** adapter construct-without-hardware + import-sweep; exp/seq library import + flat-namespace collision check; vis config-key mount wiring; endpoint-parity **static AST extraction** for all 23 servers + **runtime `/openapi.json` diff** on the one sim-launchable config (`gamry.yml`, with a Linux `root:` override + simulated-driver path); member-surface + dependent-surface inventory; port-wiring completeness.
- **At-station HARDWARE only (deferred to each station's cut-over window):** station smoke sequence, soak window, **on-station golden diff** (§6.6: capture on legacy pre-migration, diff on hexagon post-migration, same window). Per-station gate; per-station rollback via `deployment:` flip; legacy untouched in-tree.

A sub-project may legitimately hold at **"Linux-green, awaiting station"** (spec A2) without blocking the next sub-project's Linux work — subject to the dependency order below. **P3's shared adapters (P3a) must land before P4/P5** (Deployment-A/B reuse hte Gamry/NI/motion adapters + `TransformXY`).

## Sub-project decomposition & dependency order

**Architecture pin (verified against the P2 graft, 2026-07-18):** the hexagon `makeActionApp` graft reroutes only the **write/status path** (`base.contain_action`, `base.meta_writer`, `active.data_stream`/`data_file_writer`/`action_finalizer`) via instance-rebind. It does **NOT** touch `app.driver` — the legacy driver instance stays live (`HardwarePort` in `wiring.py:73` is an unused `Optional=None` stub as of P2). Therefore:

- **hte cut-over parity is reached by graft-wrapping the legacy servers (P3b) with their legacy drivers intact** — exactly as P2 did for the SIM server. The per-station golden-diff gate certifies this.
- **Native Hardware adapters (P3a) are a parallel native-replacement track, NOT a P3b prerequisite.** Spec still wants them landed (shared Gamry/NI/motion + `TransformXY` are reused by P4/P5, and native replacement is the end state), but they do not block hte parity. P3a and P3b proceed independently; P3a's shared adapters gate P4/P5, not P3.
- **Runtime caveat:** hte legacy drivers are Windows-only and won't import/run on Linux, so P3b's *runtime* graft is exercised at-station. P3b's Linux-green portion is limited to shim compile/import + the static endpoint checklist (P3-pre). P3a native adapters, by contrast, ARE Linux construct/import-sweep testable (lazy vendor imports, §11.1) — making P3a the more Linux-productive track.

```
P3-pre ─┬─► P3b (graft-wrap 23 servers; parity critical path) ─► P3e (config cut-over + station gate)
        ├─► P3c (libraries — import-only, no driver dep) ───────┘
        ├─► P3d (vis + operator) ───────────────────────────────┘
        └─► P3a (native Hardware adapters; parallel track, gates P4/P5, Linux-testable)
```

### P3-pre — Dependent-surface inventory + endpoint-extraction checklist  *(MANDATORY FIRST — Linux-complete)*
**Why first:** spec §8.3(3) / AVOID #8 — the old attempt's "Wave 3.5 emergency" came from omitting the experiment/sequence + member-surface audit until mid-wave. The inventory is a **gate input attached to the phase plan before the wave starts**.
**Scope:** (1) AST endpoint-extraction harness run over all 23 legacy `makeApp` modules → frozen per-server checklist artifacts (route path/method/tags/param names+types+defaults, incl. config-shaped dynamic enums extracted with a target config so `drv.dev_*` signatures materialize); (2) member-surface audit (§8.2 — grep-derived `app.*`/`base.*`/`active.*`/`dyn_endpoints`/`poller_class`/`server_params` usage per server); (3) dependent-surface inventory (§8.3(3) — exp/seq library imports, `active.*`/`base.*` member usage, config references to shared modules, `bokeh_port` claims); (4) flat-namespace collision scan (CCSI/CSIL, ECHEUVIS_postseq). No production code changes — tooling + committed audit artifacts under `helao/hexagon/tests/checklists/hte/`.
**Gate:** artifacts committed; collision scan enumerates the two known hazards + any others; extraction reproducible via a committed script.

### P3a — Shared Hardware adapter substrate + driver conformance  *(parallel native track; gates P4/P5, not P3; Linux-complete for construct/import; hardware exercise deferred)*
**Scope:** bind the ~18 hte drivers to `HardwarePort` (`helao/hexagon/adapters/legacy/hardware.py` `LegacyDriverHardwareAdapter` for clean serial/HTTP/compute; net-new adapters for the special cases). **P2 wired NO real hardware** (`wiring.py:73` stub) — this is net-new. Includes: lazy adapter-scoped vendor imports (§11.1) + Linux import-sweep CI test; per-driver `_METHOD_MAP` refinement; `ExclusiveAccess` port for poller-mutex drivers (AliCat/legato/sensors); empty-`DriverResponse()`=skip-sample sentinel formalized; the two Galil `{err_code:ErrorCodes}` command surfaces mapped once. **4 special-case splits:**
  - **PAL** — 4-way (§4.4 #1): transport / trigger / sample-reconciliation policy / job-context(DataSink) port. **Wrap-then-split**: port PAL as a single adapter behind the job-context port to parity first, split internals after (largest single item; may sub-phase P3a-PAL).
  - **galil_motion** — 3-way + aligner (D6, §4.4 #2): gclib motion adapter / pure `TransformXY` domain service + calibration storage port / Bokeh Aligner→visualizer adapter. `TransformXY` lifted whole (Base-free ~370 LOC); shared with P4 ThorlabsMotor.
  - **Gamry** — COM STA-thread adapter (§11.2): dedicated apartment thread owns COM init + dtaq sinks + `PumpEvents`; `sys.coinit_flags` out of module import; 3 strategies (DC/dtaq · EIS/ReadZ · idle-poller) behind one adapter; psutil kill = supervisor concern.
  - **Archive → SampleState** (archive-hoist, §4.3.11): never a driver; re-home behind the SAMPLE server via the existing `SampleShimAdapter`; inject `helaodirs`×3 + sample-DB API.
  - Excluded: DBPack (dead), Leancat (broken orphan — keep/kill decision first). PowerSupply + Leancat are **rewrites not wraps**.
**Gate:** every adapter constructs disconnected + is `HardwarePort`; Linux import-sweep green over all adapters incl. Windows-only; `nidaqmx` DataSink-port exemplar promoted; boundary test green. Hardware exercise → station gate.

### P3b — 23 action servers as inbound adapters  *(Linux-green for the sim config; per-server at station)*
**Scope:** one `helao/deploy/hte/servers/<group>/<module>.py` hexagon shim per server (basename-matched, `makeApp = makeActionApp(server_key, LEGACY_MODULE)` + startup grafts) mirroring `helao/deploy/hexagon/servers/`. Reproduce both dispatch behaviors (HTTP queuing middleware path + RPC-bypass path, §7.2). Co-located RPC mirror mandatory (§7.1). Config-shaped endpoint signatures from driver device maps preserved. PAL server tracks the P3a wrap-then-split state.
**Gate:** endpoint-parity checklist (static, all 23) + runtime `/openapi.json` diff on `gamry.yml`; member-surface audit green; per-station runtime diff → station gate.

### P3c — Experiments/sequences libraries via Library port  *(Linux-complete)*
**Scope:** 242 exp + 86 seq fns imported through the Library port (dynamic import + codehash/codepath provenance + **load-time collision check**, config-overridable for intentional shadowing). Resolve the two hazards loudly: CCSI/CSIL shared `CCSI_sub_*` names; `ECHEUVIS_postseq` in both ECHEUVIS_seq + HISPEC_seq. `specifications/*.py` `BaseParser` + `processors/` `MetaProcessor` contracts supported (non-standard artifact outputs preserved verbatim; latent bugs at `week_window.py:77,110` documented not silently fixed).
**Gate:** all libraries import; collision check fires loudly on the two hazards; provenance recorded; parity of dispatched params (no silent "fixes").

### P3d — Visualizer (13) + operator scripts  *(Linux-mountable)*
**Scope:** config-key-selected mounting (`action_vis:`/`live_vis:`) via core `vis_subscriber.mount_visualizers` through the hexagon vis adapters (P2d pattern); 12 `*_vis` + styles.css; thin hosts + data_browser shim; `layouts/aligner.py` Bokeh panel wired to galil_motion `run_aligner`/`stop_aligner` (depends on P3a aligner extraction). Operator: `standalone_operator` (makeBokehApp style) + the 3 script-style operators (external `data_request_client` dep noted).
**Gate:** vis modules mount under a hexagon-composed config; operator composes; runtime render → station/browser smoke.

### P3e — Config cut-over + hte preflight validator  *(Linux-green assembly; per-station HARDWARE cut-over deferred)*
**Scope:** offline preflight validator extended with hexagon checks (§8.3: config sanity + endpoint-parity checklist + library collision + port-wiring completeness, runnable with disconnected adapters on Linux). Per-config `deployment: hexagon` shims committed **before** any flip. Canary station first, risk-ordered rollout, per-station rollback.
**Gate (per station, HARDWARE):** endpoint-parity checklist green (static + runtime preflight); station smoke; soak; on-station golden diff (§6.6). Canary first. **This is the phase's terminal hardware gate — surfaced to the human at station-window time; not executable from Linux.**

## Global constraints (apply to every sub-project)

- **Instance-rebind, never subclass** `Base`/`Active`; grafts reproduce the legacy body pinned by an `inspect.getsource` drift test and swap collaborators on the live instance (P2 precedent).
- **Vendor imports lazy + adapter-scoped** (inside `connect()`/factory); every adapter imports on Linux for schema/introspection/preflight; Linux import-sweep CI test covers all.
- **Disconnected construct** first-class: every adapter constructible + schema-introspectable without hardware/vendor runtime.
- **`DriverResponse` two-axis kept verbatim** incl. `DriverStatus.retry` and empty-`DriverResponse()`=skip-sample poller sentinel. Executors call `driver_response_to_error_code`, never string-compare.
- **Co-located RPC mirror** on `derive_rpc_port(port)` for every hexagon FastAPI server (composition fails preflight if absent).
- **No silent bug-fixes where wire/disk-visible** (dispatched params, artifact bytes) — parity first; documented latent bugs carried, not fixed, unless behind a flag with a recorded decision.
- **Legacy untouched in-tree** — cut-over is a `deployment:` key flip; rollback is flipping it back.
- **black** (line length 88) on changed files immediately before every commit (parent repo + each nested deployment repo independently).
- **conda run -n helao** for all python/pytest.
- **Branch-per-sub-project**; do not commit/push without authorization; nested deployment repos are private (never name them in parent-repo docs/code).

## Execution note

P3-pre is Linux-complete and mandatory-first — **DONE** (branch `feat/p3-pre-hte-inventory`, 92 harness tests green; frozen checklists + member/dependent-surface audits + collision scan committed).

Given the architecture pin above, the two Linux-productive next tracks are **P3a** (native Hardware adapters — construct/import-sweep testable on Linux, gates P4/P5) and **P3c** (libraries — import + collision-check, no driver dependency). **P3b** and **P3d** are shim-scaffold on Linux but runtime-exercised at-station. The terminal per-station hardware gate (P3e) is a hard stop requiring station access — surfaced explicitly, not guessed through.

Note: P3d's aligner-panel wiring depends on P3a's galil_motion aligner extraction (D6); schedule that split early in P3a if P3d is pulled forward.
