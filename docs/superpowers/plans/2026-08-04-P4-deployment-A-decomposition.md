# P4 — Deployment-A Migration: Decomposition & Sequencing

> **Status:** P4a–P4e **implemented and Linux-green** (247 tests across 17 files, verified
> 2026-08-05); **P4f step 1 — the config flip — is DONE (2026-08-05)**; what remains is
> station-only: the a3 aligner dry-run and P4f's single risk-ordered window. Locks sub-project
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

### P4f — Assembly: hex flip + terminal at-station smoke  *(step 1 DONE; the station window is the phase's terminal gate)*

1. **Flip the live demo config. DONE 2026-08-05**, resolving the plan's "flip to the hex
   variant *or* add the keys in place" either/or in favour of **in place**. Per the resolved
   Q1 the flip list was **that config only** — the dormant simulation config gates nothing and
   must not consume a station window. All four action servers now carry `fast: graft` +
   `deployment: hexagon` + `legacy_module:`; the orchestrator, operator and visualizer entries
   are unflipped by design (non-action roles are out of P4 scope, and D9 keeps both UI stacks
   on legacy core until P7-UI).

   **The hex rehearsal variant was deleted rather than promoted.** It existed (P4e) only to
   prove a hex-composed group preflights non-vacuously, and it did that by duplicating the live
   config's params verbatim. Promoting it would have left two ~190-line configs holding the
   same real station hardware params — device serials, channel maps, a vendor DLL path, ports,
   `root:` — to be hand-synced for the rest of the deployment's life, and would have made
   rollback all-or-nothing (launch the other prefix). In place, **rollback is per server and
   needs no second file:** delete that server's two keys and restore its `fast:` module name.
   The legacy modules are untouched in-tree, so a rolled-back server is byte-identical to
   pre-flip. The preflight pin went from three configs to two.

   Evidence: `PREFLIGHT OK` on both remaining configs, and the checklist gate proven **live**
   on the flipped config by negative control — a scratch copy with one `legacy_module:` pointed
   at a nonexistent module failed with `frozen endpoint checklist missing`. 247 tests across 17
   files green on a vendor-less Linux box.

   **A silent-pass trap in the gate, found while proving it, that the station runbook must
   respect.** Preflight infers the deployment from the config's **path** — a config not under
   `helao/deploy/<dep>/configs/` yields no deployment, and the checklist-presence gate then
   returns early and **passes silently**. The first negative control was run on a copy in a
   scratch directory and printed `PREFLIGHT OK` with a deliberately broken `legacy_module:`.
   So: preflight the **in-tree** config path. A copy staged elsewhere returns a meaningless OK
   and does not say that the route gate was skipped. (Not fixed here — widening the validator
   is outside a config flip; recorded as a backlog item and a runbook constraint.)
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

   **Reading the freezer's report on the other eight modules needs the scope decision in
   hand, or it manufactures work that does not exist.** Run across all 9, it flags five —
   and four of those five are **not defects**:

   - **Four modules are deliberately out of scope, and their `representative_key: null` is
     correct.** Two software servers, one openapi-only pump server, and the NI-DAQmx
     re-export are **not wired by any operational config** and are **not gating** — a
     standing scope decision, recorded both in the manifest's own per-entry notes ("not wired
     in tracked configs") and in this phase's hardware-scope note, which lists exactly four
     hardware servers and excludes these. Their frozen checklists carry concrete server keys
     because the canary configs that exercise them were **synthesized** to give those servers
     openapi-only coverage; the manifest surveyed *operational* configs, which is the right
     question for it to answer. Manifest and checklists are each accurate about different
     things. **Nothing to reconcile, and nothing here is a P4f prerequisite.**
     `harness/freeze.py` now **skips** a checklist frozen under a synthesized key, quoting
     the manifest's own note as the reason, so its report no longer presents a scope decision
     as a defect list — which is exactly how it was misread once. `--include-unwired` forces
     them if ever needed. The narrowness matters: four *hte* modules also carry
     `representative_key: null`, but they are frozen with `{server_key}` **unsubstituted**,
     agreeing with their manifest, and must keep being frozen or a route added to one later
     goes unnoticed. So the skip fires on a concrete prefix, never on the placeholder.
   - **The NI-DAQmx re-export is a special case of the above.** Its local module is 727 bytes
     with **zero** extractable routes — a pure pass-through to hte's server — and its
     checklist is hte's route set with a synthesized key substituted. So static extraction of
     the local module can never reproduce it, and it is consequently missing the two
     digital-out routes hte's module gained on 2026-08-04. Harmless while nothing wires it;
     it becomes real the day something does. Per this phase's out-of-scope list, that
     module's surface is tracked against the hte adapter, not rebuilt here.
   - **The potentiostat checklist mixes the static and runtime tiers.** It contains technique
     routes and private probes that the **cross-deployment** dyn-endpoint registrar adds at
     runtime, which static AST extraction of the local module will never produce. That split
     is §8.3's documented design, not a defect — but the frozen file does not record which
     entries came from which tier, so a static freezer reads the runtime ones as removals.
     Worth marking so the tool can skip them; not blocking.
   - **The one genuine defect — six motion routes frozen with `Optional[...]` parameters
     that never existed in the source. FIXED 2026-08-04.** Traced conclusively: the source at
     the very commit that wrote the checklist already said `str = None` / `int = None`, and
     `Optional` appears in that file today only inside a docstring. The extractor only
     `ast.unparse`s what is written, so it cannot invent a type — whatever produced the
     original checklist inferred nullability from a `= None` default, and did so **only** for
     bare `str`/`int`, leaving config-shaped dynamic enums and existing `Union[...]` alone
     even though they also default to `None`. Same signature as the NI-DAQmx case above.

     Why it mattered: the two forms emit **different** OpenAPI. Measured —
     `int = None` → `{"type": "integer"}`, `Optional[int] = None` →
     `{"anyOf": [{"type":"integer"},{"type":"null"}]}`. So the frozen file recorded a schema
     the live server will never emit, on a server that **is** one of the four hardware
     servers and **is** gating. It was not firing: the canary diffs compare legacy-vs-hex
     captured artifacts, both live, so they agree. It would have fired as six false
     mismatches the day §8.3(2)'s runtime `/openapi.json` cross-check runs — a scarce station
     window. Corrected via `--accept-drift` as a **transcription fix**, not a baseline
     widening: the checklist exists to record legacy behaviour, and it was wrong about it.

     **Not fixed, deliberately:** the source really does say `speed: int = None`, an
     annotation that contradicts its own default. Changing it to `Optional[int]` is
     wire-visible per the measurement above, so the parity rule says preserve. Post-parity
     backlog, needing a P4d-style recorded decision.
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

**Current state, verified 2026-08-05:** P4a–P4e are implemented and green — 247 tests across
17 files in the deployment's suite, all passing on a vendor-less Linux box. The hardware
canary gate passed at station on 2026-07-29. **The live config is flipped** (P4f step 1, in
place; the rehearsal variant deleted) and preflights non-vacuously.

**Every Linux-authorable item in this phase is now discharged.** The three prerequisites
below are closed, and so is the flip. What remains is station-only.

**Two things stand between here and P4 complete, both requiring station access:**
1. The **a3 aligner dry-run** (custom hlo `file_type` preserved; named-plate calibration and
   backup written byte-identically through the injected context).
2. **P4f** — flip the live config, then the single risk-ordered station window.

**Linux-completable prerequisites for P4f:**
1. IO server checklist re-freeze — **DONE** (additive, +1 route), and the missing generic
   freeze script now exists as `harness/freeze.py`.
2. **Closed.** Of the checklists the freezer flags, four cover modules deliberately out of
   scope — not wired by any operational config, not gating — and are now skipped rather than
   reported. The one real defect, six motion routes carrying `Optional[...]` annotations the
   source never had, is **fixed** (delta #2). The potentiostat's runtime-registered
   cross-deployment routes — the last thing still flagged, and correct to leave unapplied since
   accepting would have deleted them from the baseline — are now **marked as externally
   registered**, so the freezer confirms them against the foreign registrar instead of
   proposing their removal. **Re-verified 2026-08-05:** a freeze dry-run over all nine modules
   reports zero drift — five `unchanged`, one `external` (15/15 routes confirmed in their
   registrar), four deliberate scope-skips. Nothing outstanding.
3. Hexagon preflight rejected every config carrying a `reflex:` server — **FIXED**
   2026-08-04 (Amendment 1 §9.1). It had the same stale "exactly one of fast/bokeh" rule the
   spec did, which blocked the P3e gate for three hte stations and one Deployment-C station.
   Deployment-A has no Reflex server so P4f was never blocked by it, but P4f runs the same
   gate. The validator now shares the launcher's code keys (pinned by a test that reads
   `launch.py`) and reserves a reflex entry's `port + 1`.

**Dependency reminder for the phases after this one:** P5 and P6 reuse this phase's
config-driven graft and its public-port/private-specifics split. Neither needs a
per-deployment shim written in the public tree — that problem is solved.
