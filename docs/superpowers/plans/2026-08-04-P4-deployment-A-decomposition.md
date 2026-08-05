# P4 — Deployment-A Migration: Decomposition & Sequencing

> **Status:** P4a–P4e **implemented and Linux-green** (217 tests across 13 files, verified
> 2026-08-04); **P4f and one mid-stream at-station gate remain**. Locks sub-project
> boundaries, dependency order, and the Linux/at-station gate split for P4 of the hexagonal
> rewrite (master spec: `docs/superpowers/specs/2026-07-16-framework-hexagonal-rewrite-design.md`
> §P4, as amended by `2026-08-04-hexagonal-rewrite-ui-amendment.md`; mandated per §13).
>
> **This is the public mirror.** The executable plan — file paths, line numbers, per-slice
> task lists, and the measured diffs behind each decision — lives inside the private
> deployment repo (`docs/2026-07-29-P4-decomposition.md`, committed 2026-07-30), where real
> names are permitted. This document carries the structure, decisions, gates and current
> state in **Deployment-A** alias form so the phase-plan series is complete in the public
> repo. Where the two disagree, the private plan is authoritative on tactics and this one is
> authoritative on gates.
>
> **Privacy (binding):** Deployment-A alias only. No real deployment or nested-repo names,
> hostnames, config filenames, library module names, or plate/campaign identifiers. Ground
> truth: `.omc/research/framework-rewrite/deploy-A.md` + the deployment's own frozen audits.

## Goal

Finish Deployment-A's hexagon migration at parity: split the motion god-file along the
already-station-proven galil substrate, replace the two remaining custom-framework seams
(potentiostat route surgery, the ML back-channel) with first-class composition features,
disposition the audited latent bugs without breaking wire parity, and close the
config/canary gaps so both tracked configs are non-vacuous Linux preflight targets and the
experiment/sequence libraries are exercised by an automated gate. Terminal state: the
tracked station config flips to `deployment: hexagon` with per-server rollback.

## The audited surface (spec §8.1, frozen map `deploy-A.md`)

- **9 action-server modules**, frozen per-server endpoint checklists in the deployment's own
  `tests/checklists/` (private-repo location, resolved by `helao/hexagon/preflight.py`'s
  private-aware `_checklist_dir()` — the public source names nothing private).
- **7 local driver classes; 6 already on the `HelaoDriver` ABC**, 1 deliberately bare (the
  sim, per spec A4). The `deploy-A.md` audit corrected the stale CARDS "2/9 migrated" figure.
  Counting driver-backed server surfaces, 8 of 9 ride on ABC-conformant drivers.
- **Only 4 servers drive hardware** (motion, IO, potentiostat, valve). The rest are software
  or openapi-only, and are therefore not part of the hardware-canary gate.
- **37 experiment fns / 1 module; 20 sequence fns / 1 module** (~8.7k lines, heavily
  duplicated — explicitly out of scope, see below).
- **2 tracked configs**: one live demo config, one dormant simulation config.
- **Cross-deployment coupling:** imports hte's Gamry driver + dyn-endpoint registrar, hte's
  NI-DAQmx server (pure re-export), and hte motion enums. **This deployment cannot load
  without the hte tree present** — which is why spec §P4 orders P3's shared adapters first.

## Hard constraint: the Linux / at-station gate split

Windows `root:` paths and Windows-only vendor backends (Kinesis over FTDI, Advantech BDaq,
Gamry comtypes, a vendor valve DLL). Consequence (spec §6.6, §11, A2): everything
authorable on Linux is authorable *now*; hardware exercise is per-station and scheduled.

**Already discharged, which changes the shape of this phase:**
- **The hardware gate PASSED** (2026-07-29): all five Windows `.bat` diffs run at station.
  The one reported diff was a masking-harness bug in the capture script, not a parity
  failure. Potentiostat parity is **inherited** from hte's station-verified Gamry graft
  rather than re-earned here.
- **The cut-over mechanism is config-driven, not code:** a canary server sets `fast: graft`
  + `deployment: hexagon` + a sibling `legacy_module:` key, which the launcher resolves to
  the shared `makeActionApp(server_key, legacy_module)` factory. Because the private module
  path is a *config value*, it lives only in the private repo — **this is the general
  solution for P5/P6 too**, and it is why no per-deployment hexagon shim code exists here.
- **Offline preflight is live and non-vacuous** for the deployment's hex configs: the
  deployment resolves from the config path, the in-repo checklist dir is found, and each
  `fast: graft` server is gated on its frozen checklist. Invoke with the **full config
  path** — the hex configs live under `tests/smoke/configs/`, so a bare prefix will not
  resolve them.

## Explicitly OUT of scope this phase

- The ~8.7k lines of duplication in the two library modules (measured: 73–90% similarity
  across seven function pairs; the protocol-letter combinatorics multiply near-identical
  bodies). **Parity first**; dedup is post-parity backlog per spec §P4's risk note.
- The sim driver's bare / asyncio-in-`__init__` pattern — sims stay bare (spec A4).
- Implementing the ML driver's missing model (`fit`/`acquire` TODOs) — science backlog. P4
  only makes the gap **fail loud**.
- The NI-DAQmx re-export server's internals — a pure pass-through to hte's module; its
  member surface is tracked against the hte adapter, not rebuilt here.
- **A native Kinesis driver rewrite.** After the split the residual driver *is* the Kinesis
  component; a galil-style native command-channel analogue gates nothing (the hardware gate
  already passed on the graft) and would burn a scarce station window for zero parity gain.

## Sub-project decomposition & dependency order

```
P4a (motion 4-way split; largest item) ──┐
P4b (endpoint-override composition) ─────┤
P4c (ML back-channel via TransportPort) ─┼─► P4f (config flip + at-station smoke)
P4d (latent-bug disposition) ────────────┤
P4e (config repair + library canary) ────┘
```

P4a–P4e are mutually independent and were parallelizable; P4f assembles. **Only P4a carries
a hard at-station gate mid-stream** — the aligner dry-run, mirroring the galil slice-4 rule.

### P4a — Motion driver 4-way split  *(a1/a2/a4 COMPLETE; a3 code complete, AT-STATION DRY-RUN PENDING)*

The god-file was 1706 lines holding four separable things: a local `TransformXY` copy,
calibration persistence, a Bokeh `Server` started **inside `connect()`**, and the driver
itself — plus a `base` property alias existing only so the aligner UI could reach
`base.helaodirs` / `base.get_main_error`. Split against the galil substrate already merged
and station-proven on `unstable` (`domain/motion_transform.py`,
`ports/calibration_store.py` + `JsonFileCalibrationStore`, `adapters/vis/*_aligner_host.py`),
whose tests served as the fixture patterns.

- **a1 — `TransformXY` unification. DONE.** Measured AST-stripped diff ratio 0.897; the two
  classes were **identical in all matrix math**. Unified on the hexagon domain service, local
  copy deleted. Pinned by a 132-test equivalence suite.
- **a2 — Calibration store adoption. DONE.** Both calibration JSON paths are
  **byte-identical to galil's**, which is what made the shared port a drop-in.
- **a3 — Aligner extraction (D6). Code DONE; station dry-run is the merge gate.** The driver
  no longer constructs a Bokeh `Server`. 18 construct-tier tests.
- **a4 — Residual driver thin-out. DONE.** The `_base_hook` deferred-`Base` seam is
  **deleted**, replaced by an injected calibration store and an estop-flag callable — so the
  audit's §4(3) finding is closed, not merely wrapped.

**Gate:** unit/construct tiers green (Linux) **+ the at-station aligner dry-run before a3 is
considered discharged**. The dry-run must confirm the aligner's active still carries its
custom hlo `file_type` and that the finish path writes the named-plate calibration and its
backup byte-identically — the teardown now resolves dirs through the injected context, which
is precisely the thing Linux cannot certify.

### P4b — Potentiostat route surgery → endpoint-override composition  *(DONE; runtime diff at-station)*

Legacy deleted the inherited `run_CP` route from `app.router.routes`, re-registered an
extended v3, then nulled and rebuilt the OpenAPI schema. Replaced by a **declarative overlay
combinator** in the public tree (`helao/hexagon/app/endpoint_overlay.py`
`overlay_dyn_endpoints`), landing the replacement at the legacy position with the schema
rebuilt once.

**Gate:** combinator unit tests green (4) + the frozen checklist unchanged + at-station
potentiostat diff. **The subtle one:** legacy's delete+append put the overridden route
**last**, and OpenAPI path order is byte-visible — the overlay must reproduce that position
or the station diff fails on ordering alone.

### P4c — ML back-channel through the Transport port  *(DONE)*

The ML server enqueues follow-up experiments by POSTing `insert_experiment` to the
orchestrator — an inversion of the normal dispatch direction (closed-loop active learning).
Now routed through the wiring's transport port when grafted, falling back to the legacy
dispatcher otherwise, so the rollback path keeps working and the wire is identical either way.

**Gate:** 3 tests green; one closed-loop round trip at station (P4f).

### P4d — Latent-bug disposition  *(DONE)*

Eight audited latent bugs (`deploy-A.md` §4), split by wire visibility:
- **Wire-invisible crash repairs — fixed.** Private endpoints calling a nonexistent public
  getter; private endpoints `await`ing synchronous methods; a driver mutating a dict while
  iterating it; stray debug prints. These were **guaranteed-500 paths**, so carrying them
  would have meant shipping known-dead endpoints through the very phase whose point is
  decomposition with tests. 9 tests.
- **Two wire-visible items — fixed under recorded sign-off**, in one commit, with the
  decision in the commit message. Accepted consequence: recorded `-act.yml` bytes change
  going forward for one of them. Basis: both paths crash 100% today, so no consumer could
  have depended on the broken shapes, and they are two halves of the same dead pipeline.
  For the parameter-name mismatch, **only the direction where the handler follows the frozen
  OpenAPI was permitted** — never renaming endpoint params to match a broken handler. 3 tests.
- **The ML model gap — fail-loud guard, implementation deferred.**

### P4e — Config repair + library canary closure  *(DONE)*

- **The dormant simulation config declared a non-code key** for its sim server. The
  launcher's consequence is worse than a preflight failure: a server whose entry carries no
  recognized code key is **silently SKIPPED at launch**, so that server was never starting.
  Fixed. (Its sibling `live_vis:` key was legitimate — it names a public test-deployment vis
  module.)
- The live demo config needed no key repair; its former Linux blocker — an import-time
  `pd.read_csv` of a station-local absolute path inside both library modules — **fell with
  the catalog port** (see "reference split" below).
- Both legacy configs now preflight, but **checklist-vacuously** (no `fast: graft` servers),
  so a full-group hex variant was added as the non-vacuous preflight target and P4f flip
  rehearsal. All three configs are pinned by a test that shells the preflight CLI and
  asserts exit 0.
- **Library coverage closed in two tiers**, because no canary config loaded the libraries at
  all: (1) a committed import + export + flat-namespace-collision sweep that runs on a
  vendor-less Linux box; (2) a Linux-runnable orchestrated canary that launches, asserts the
  orchestrator's **real dynamic-import path** registered all 35 experiment + 15 sequence
  names, then dispatches the one pure-metadata, zero-action experiment end-to-end and checks
  the run yml. Tier 1 alone would miss `import_autolibs`, premodel construction, and
  dispatch-param serialization; dispatching a real sequence is impossible on Linux because
  every one drives hardware.

### P4f — Assembly: hex flip + terminal at-station smoke  *(REMAINING — the phase's terminal gate)*

1. **Flip the live demo config** to the hex variant (or add the `deployment:`/`legacy_module:`
   keys in place) and preflight it. Per the resolved Q1, the flip list is **that config only**
   — the dormant simulation config gates nothing and must not consume a station window.
   Confirmed still unflipped as of 2026-08-04.
2. **At-station, single risk-ordered window:** full-group hex launch of the demo config; the
   motion canary + diff re-run (driver internals changed in P4a); the aligner dry-run if a3
   has not already discharged it; the potentiostat diff (P4b's OpenAPI ordering); one
   closed-loop ML → orchestrator `insert_experiment` → dispatch round trip (P4c); IO and
   valve canaries as informational (code unchanged). **Rollback is per server** — flip the
   keys back; legacy is untouched in-tree.

## Amendment-1 deltas (UI era; see the amendment's §10)

Deployment-A is the **least** UI-affected deployment, and that is a scheduling asset:

1. **No Reflex panels, no `reflex:` server, no `control_vis` in either config.** Under D9
   that is a choice, not a gap — panels resolve by the same config keys in either stack, and
   a station opts in later by adding a `reflex:` server and changing nothing else.
   **Decision: Bokeh only for P4.** Rationale: P4f's terminal gate is a single scarce station
   window, and adding a first-ever frontend bundle build at that station would couple a
   hardware parity gate to a build artifact whose failure mode is a blank, silently
   disconnected page. Adding Reflex here is a P7-UI concern.
2. **Its IO server gained the private digital-out setter on 2026-08-04. DONE** — re-frozen
   additively via the new generic `harness/freeze.py` (7 routes, +1, zero deletions), so
   preflight now gates that `fast: graft` server against a baseline that matches its code.

   **But freezing it exposed a larger problem: the deployment's other checklists are not
   reproducible by the committed tooling.** Running the freezer across all 9 modules reports
   drift in five of them that is *not* code drift:
   - **Server-key substitutions the manifest says do not exist.** Four checklists were frozen
     with concrete keys while `servers.json` records `representative_key: null` for those
     modules ("not wired in tracked configs"). The keys came from the audit's list of
     commented-out aliases. Manifest and checklists therefore disagree, and no mechanical
     re-freeze can reproduce the frozen paths.
   - **Routes static extraction cannot see.** The potentiostat checklist contains the
     technique routes and private probes that the **cross-deployment** dyn-endpoint registrar
     adds at runtime. Static AST extraction of the local module alone will never produce
     them — this is §8.3's documented static/runtime split, but the frozen file mixes both
     tiers without recording which is which.
   - **Annotations the extractor cannot emit.** Six motion routes are frozen with
     `Optional[...]` parameters that **never existed in the source** — no commit in that file's
     history contains the string, and the extractor only `ast.unparse`s what is written.
     Something inferred nullability from a `= None` default. (One reported delta *is* pure
     PEP 585 spelling, already normalized at the comparison layer; the `Optional` ones are not.)

   Consequence: the original freeze was not produced by `harness/endpoints.py`, so the
   P3-pre rule "extraction reproducible via a committed script" does not hold for this
   deployment. **This is a P4f prerequisite in its own right, and it must not be resolved by
   re-freezing** — that would silently shrink the parity baseline of a deployment awaiting its
   station gate (dropping the runtime-registered potentiostat routes from the checklist would
   make the gate stop asserting them). Resolve it deliberately: reconcile the manifest's keys
   with reality, and either record the runtime-registered tier separately or mark those
   entries as runtime-sourced so the static freezer leaves them alone.
3. **Its palette sweep is broader than the parent's, which is the safe direction.** The
   parent's AST sweep globs `helao/deploy/*/servers/**`; this deployment's own test
   `rglob`s the entire repo, so the extracted aligner host — which lives under `layouts/`,
   **outside** `servers/` — is covered. Had it relied on the parent's glob, the one file P4a
   moved colours into would have been unguarded. Keep the repo-wide form; do not "align" it
   to the parent's narrower glob.
4. No `/control` route and no control panel means **artifact row 15 and the capture-window
   rule are inert here** — but the amendment's §4.2 procedural rule still applies to the P4f
   window if a control panel is ever added before it opens.

## Decisions

1. **Unify on the shared `TransformXY`; delete the local copy.** Math verified identical by
   measured diff; the hexagon version is a strict superset on input coercion. *Rejected:*
   parameterizing the local copy (keeps a ~390-line duplicate the spec says to unify);
   adding a strictness flag to reproduce the narrower input handling (the extra leniency only
   converts previously-500ing requests — see Wire-visible risks #1).
2. **No native Kinesis rewrite this phase.** After a1–a3 the residual driver *is* the Kinesis
   component, thinned in a4. *Rejected:* native-now (scarce station window, zero parity gain).
3. **Keep two aligner hosts; do NOT extract a shared base.** *This supersedes the plan's
   original preferred option* and adopts its recorded fallback as the chosen design — decided
   only after a3's extraction made the real surface visible, which is what the original
   decision deferred it for. Roughly 80% of the two hosts coincides by line count, but the
   shared part is boilerplate (the context-delegation skeleton, the host shell, the
   `bokeh_port` else `port + 1000` derivation) while the divergences are **structural**: the
   two `start_aligner_run` methods solve *different problems* (one takes a plate id and
   platemap path, the other six calibration coordinates and builds a 3-row map); the UI
   classes differ in constructor contract; one host has a calibration-backup path the other
   retired; the device-enabled flag differs by attribute name. Unifying would mean adding a
   factory callable, a usermap-builder callable and an attribute-name indirection to
   **station-validated code** to save boilerplate. *Cost accepted:* hand-sync where they
   coincide, mitigated by construct-tier tests on both sides pinning the shared behaviors
   independently. Revisit only if a third deployment grows an aligner **and** its
   `start_aligner_run` matches one of the two — three data points, not two.
4. **The route override becomes a declarative overlay combinator**, not deployment-side
   router mutation. Invariants: the target must pre-exist, the replacement lands at the
   legacy position, the schema is rebuilt once. *Rejected:* a `skip=` parameter on hte's
   registrar (couples a public server to an override need and re-opens hte's settled parity
   surface); keeping the surgery (spec §P4 mandates the first-class feature); shadow-router
   interception (over-engineered — FastAPI registers eagerly inside the registrar).
5. **ML back-channel: wiring-preferred transport with legacy fallback.** *Rejected:*
   port-only (breaks the rollback path); status quo (spec §P4 mandates the port).
6. **Latent bugs: wire-invisible crash repairs now; wire-visible only under recorded
   sign-off, one commit, handler-follows-OpenAPI direction only.** *Rejected:*
   fix-everything-silently (violates the parity rule and the frozen checklists);
   carry-everything (ships known-dead endpoints through a decomposition phase).
7. **Library coverage = committed import/collision gate + an orchestrated zero-action
   dispatch canary.** *Rejected:* import-sweep only (misses the real import path, premodel
   build, dispatch-param serialization); dispatching a real sequence (not Linux-runnable).
8. **Bokeh only for P4** (new, Amendment 1) — rationale in the deltas section above.

## The reference "native special split"

The electrolyte-CSV → injected catalog port is **the pattern every P4 slice follows**, and
it is worth stating separately because it resolves the confidentiality problem generically:
the **port and adapter are public and generic** (`helao/hexagon/ports/catalog.py`
`TableCatalogPort`, `adapters/native/csv_catalog.py`, a fake, and public tests written
against a **fictional** table); **only the deployment-specific resolver lives in the private
repo**. Legacy quirks were **reproduced, not improved**: both distinct lookup shapes (one
with an assert-and-fallback, one first-match-or-`IndexError`), the fallback tuple, dtype
preservation, and — the subtle one — the **read timing**. The legacy modules read the CSV at
*import*, and a spec parser rewrites that same CSV at runtime, so sequences deliberately saw
the pre-parser table; the adapter primes at first access to hold that timing, because a lazy
first-lookup read would have silently upgraded to newer data. That is a wire-visible change
that no test would have flagged.

**A confidentiality scrub was needed before that work could be committed**, and it is the
cautionary half of the pattern: the first draft of the *public* test reproduced the real
table schema and a station path, and two docstrings described the private domain. Public
port + adapter + fake + fictional-fixture tests; **all real-schema parity tests stay
private**.

## Global constraints (inherited from the P3 plan; apply to every slice)

- **Frozen checklists are never regenerated to make a diff pass.** Re-freeze only for a
  genuine, reviewed surface addition — and record it (Amendment 1 §5.1 is the worked example).
- **No silent wire/disk-visible fixes.** Documented latent bugs are carried, not fixed,
  unless behind a recorded decision.
- **Legacy stays launchable** — cut-over is a config key flip; rollback is flipping it back.
- **Instance-rebind, never subclass** `Base`/`Active`.
- **Vendor imports lazy + adapter-scoped**; every adapter imports on Linux for
  schema/introspection/preflight.
- **Co-located RPC mirror** on `derive_rpc_port(port)` for every hexagon FastAPI server.
- **black** (88) on changed files immediately before every commit, per repo independently.
- **`conda run -n helao`** for all python/pytest. Run test files **individually** — the suite
  hangs as a single pytest session.
- **Branch-per-sub-project; no commit or push without authorization.** Parent-repo commits
  and docs use the **Deployment-A** alias; the private repo's own commits may use real names.

## Execution note

**Current state, verified 2026-08-04:** P4a–P4e are implemented and green — 217 tests across
13 files in the deployment's suite, all passing on a vendor-less Linux box. The hardware
canary gate passed at station on 2026-07-29. The live config is **not yet flipped**.

**Two things stand between here and P4 complete, both requiring station access:**
1. The **a3 aligner dry-run** (custom hlo `file_type` preserved; named-plate calibration and
   backup written byte-identically through the injected context).
2. **P4f** — flip the live config, then the single risk-ordered station window.

**Linux-completable prerequisites for P4f:**
1. IO server checklist re-freeze — **DONE** (additive, +1 route), and the missing generic
   freeze script now exists as `harness/freeze.py`.
2. **Open:** reconcile the five non-reproducible checklists (Amendment-1 delta #2). Not a
   re-freeze — a deliberate reconciliation, because re-freezing would shrink the baseline.
3. Hexagon preflight rejected every config carrying a `reflex:` server — **FIXED**
   2026-08-04 (Amendment 1 §9.1). It had the same stale "exactly one of fast/bokeh" rule the
   spec did, which blocked the P3e gate for three hte stations and one Deployment-C station.
   Deployment-A has no Reflex server so P4f was never blocked by it, but P4f runs the same
   gate. The validator now shares the launcher's code keys (pinned by a test that reads
   `launch.py`) and reserves a reflex entry's `port + 1`.

**Dependency reminder for the phases after this one:** P5 and P6 reuse this phase's
config-driven graft and its public-port/private-specifics split. Neither needs a
per-deployment shim written in the public tree — that problem is solved.
