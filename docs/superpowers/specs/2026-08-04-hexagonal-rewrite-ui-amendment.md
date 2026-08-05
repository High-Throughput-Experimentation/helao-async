# Hexagonal Rewrite — Amendment 1: the second UI stack

**Date:** 2026-08-04
**Amends:** `docs/superpowers/specs/2026-07-16-framework-hexagonal-rewrite-design.md` (master spec)
**Status:** Adopted. §13 of the master spec requires an amendment to add a phase, extend a
gate, or add a row to the artifact inventory. This does all three.
**Baseline:** `unstable` @ `8e18c0f9`
**Privacy rule:** inherited verbatim from the master spec §8 preamble. The private
deployments are **Deployment-A/B/C** only.

---

## 1. Why this amendment exists

The master spec was written on 2026-07-16 against a Bokeh-only UI. Between 2026-08-01 and
2026-08-04 the repository grew a **second, coequal UI stack** (Reflex + `xy`), a
**single-source colour layer** shared by both, and a **hardware-control surface that
deliberately produces no artifacts**. None of it is anticipated anywhere in the master
spec: the string "reflex" appears zero times in that document and zero times in
`helao/hexagon/`.

Three consequences, in ascending order of how badly they would have bitten:

1. **Two master-spec statements are now factually wrong** (§9.2(3), §9.4) and would have
   been implemented as written by a phase plan.
2. **Frozen gate inputs went stale.** The hte endpoint checklists were frozen 2026-07-21;
   four private routes were added 2026-08-04. A station's gate would have diffed against a
   baseline that predates its own production code.
3. **A new cross-cutting invariant exists that the hexagon tree is structurally exempt
   from** (the palette sweep), so hexagon vis adapters can violate it with a green suite.

This amendment does not re-litigate any locked decision of §3. It adds **D9**, adds
**P7-UI**, adds artifact-inventory row **15**, and corrects the two wrong statements.

## 2. What actually landed (the delta being accounted for)

Inventory, not narrative. Every path verified present on `unstable` @ `8e18c0f9`.

**New shared core UI layers** (`helao/core/servers/`):

| Area | Modules |
|---|---|
| Reflex framework | `reflex/{app,control,discovery,ingest,plots,ringbuffer,state,xy_component}.py` |
| Colour | `palette.py` (single source), `bokeh_theme.py` |
| Data browser | `data_browser/{readers,sources,state}.py` (shared) + `app.py` (Bokeh) + `app_reflex.py` (Reflex) |
| Operator | `operator/{orch_backend,param_forms,param_store,spec_parser,object_tree}.py` (shared) + `bokeh_operator.py` + `app_reflex.py` |
| IO control | `io_control.py` (shared logic) + `io_control_vis.py` (Bokeh panel) |

**New launcher surface:** `reflex_launcher.py` (720 lines); `build_reflex_bundle.py`;
`launch.py:583` `codeKeys = ("fast", "bokeh", "reflex")`;
`launch.py:61` imports `reserved_addresses` from `reflex/discovery.py`.

**New config keys:** `reflex:` (a third code key, claiming `port` **and** `port + 1`);
`control_vis:` (a third vis key beside `live_vis:`/`action_vis:`).

**New wire surface:** bare-path private routes on three IO action servers —
`POST /get_digital_outs` → `(error_code, {name: bool | None})` and
`POST /set_digital_out {do_name, on}` → same shape. Present on hte `galil_io` and
`nidaqmx_server`; the third is a Deployment-A Advantech server in its own repository.

**Deployment panel deltas** (counted on `unstable` @ `8e18c0f9`; `_`-prefixed modules are
shared helpers, not config-selected panels):

| Deployment | Reflex panel modules | Configs with `reflex:` | Configs with `control_vis:` |
|---|---|---|---|
| hte | 19 files = **13 config-selected** + 6 helpers | 3 station (`clad`, `eche10`, `hispec`) + 1 dev (`htereflex`) | **15** of 21 |
| test | 4 = 3 panels + 1 helper | 1 (`goldenreflex`) | 1 (`goldenreflex`) |
| Deployment-A | **none** | none | none |
| Deployment-B | 6 = **5 config-selected** + 1 helper, plus its own palette-sweep test | 1 dev config | none |
| Deployment-C | **none of its own** | 1 station config | 1 station config |

Two things in that table are easy to misread. First, `control_vis` is **not** a
Reflex-only key — 15 hte configs declare it and pair it with a `control_visualizer` Bokeh
server; only 4 of those also carry a `reflex:` server. The control panel is a Bokeh feature
that Reflex also renders. Second, Deployment-C runs the Reflex UI with **no panel modules
of its own**: its `control_vis: digital_out_control` resolves to the *hte* Reflex module by
the launcher's cross-deployment module fallback, which is the same shared-legacy-surface
path §9.2(4) already sanctions for its Gamry/NI/motion reuse.

**New test surface:** 20 `test_*.py` files under `helao/core/tests/` covering the Reflex
stack, the palette sweep, the shared operator layers, and `io_control`.

**Launcher/process facts that changed underneath §9.4/§11:** `PR_SET_PDEATHSIG` arming
(Linux) and a Windows Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`
(`helao/helpers/win_job.py`); the CTRL-d detach marker; CTRL-t runtime watcher toggle;
`--reconnect` / `--force-relaunch`; live-member confirmation by cmdline match rather than
`pid_exists`. Plus `run_tests.py`, a per-file pytest sweep of the whole tree.

## 3. New locked decision

| # | Decision |
|---|---|
| **D9** | **Both UI stacks stay on legacy core through P0–P6 and migrate together in a single dedicated phase, P7-UI (§6 below).** Rationale: the UI is a *consumer* of the hexagon servers' wire surface, not a producer of parity artifacts (§4 below establishes it writes nothing the parity contract covers, with one bounded exception). Migrating it per-deployment would reopen P3, which is already Linux-green and awaiting station gates. Migrating it never — the Q5-runners treatment — was rejected because the UI holds real logic (the shared operator/browser/io_control layers) that will otherwise remain the last un-ported god-area. **Corollary, binding on P0–P6:** a phase may not change a WS payload shape, a private route, or a config key that either UI stack consumes without updating that stack in the same commit; the UI is legacy code the hexagon must keep working, exactly as legacy configs must stay launchable. |

## 4. Amendments to the parity contract (§5)

### 4.1 New artifact-inventory row

Added to the §5.2 taxonomy:

| # | Artifact | Path/filename template | Writer | When | Content schema |
|---|---|---|---|---|---|
| 15 | **none — direct hardware control** | *(no artifact)* | `io_control.set_digital_out` via a server's private `/set_digital_out` | on operator click, at any time, including mid-run | **Nothing is written.** No action, no `-act.yml`, no HLO, no run record, no status push. The digital output changes state and the response carries the post-write readback. |

Row 15 is a **negative row** and is normative as such: the parity harness must assert that
driving a digital output through the control surface leaves the artifact tree
**unchanged**. This is the inverse of every other row and is why it needs stating — the
master spec's §5 tacitly assumes hardware activity implies artifacts, and a hexagon
implementation that "helpfully" logged a control toggle as an action would pass every
existing check while writing rows no legacy run contains.

### 4.2 Capture-window rule (extends §6.6)

Because row 15 changes hardware state without changing the tree, an at-station golden
capture is silently corruptible: a toggle during the window alters what the *next*
sequence measures, with nothing in the diff to show it. **The at-station capture and diff
runbook must state that no control panel is operated during either window**, and the
provenance manifest (§6.5) gains a signed-off `control_surface_idle: true` field. This is
a procedural gate, not a code gate — there is no way to detect the violation after the
fact, which is precisely why it must be recorded before the run.

### 4.3 Hardware port: readback fidelity is a contract axis (extends §4.3.1)

The master spec's Hardware port treats a read as a read. The IO control work proved that
is not safe to assume: `nidaqmx` offers **no readback** for a line held by a one-shot
`Task`, so its `/get_digital_outs` returns the server's own **write mirror**, while
`galil_io` performs a real controller read (`MG @OUT[port]` per line). Two additions to
the port contract:

1. **A state read declares its fidelity**: measured-from-hardware vs mirror-of-last-write.
   An adapter may not present a mirror as a measurement.
2. **Unknown is a third value, never coerced to off.** A line the process has not written
   since startup reports `None`, and `None` must not render, serialize, or compare equal to
   `False`. The concrete trap: gclib renders a readback as the *string* `" 1.0000"`, so
   `bool(value)` is true for `" 0.0000"` as well — the coercion belongs in one tested
   function (`do_value_to_bool`), not at call sites.

Neither is a parity concern (no artifact carries it). Both are correctness concerns that a
Hardware adapter can get wrong invisibly, which is the class of thing §4.3.1 exists to pin.

## 5. Amendments to the public-surface audit (§8)

### 5.1 Corrected counts and re-freeze

§8.1's "**237 statically-defined endpoints**" is now **241**. The four additions are the
two private digital-out routes on each of `galil_io` and `nidaqmx_server`. Verified by
re-running `harness/hte_freeze.py`: route set diff is four additions, **zero removals**.

The frozen checklists under `helao/hexagon/tests/checklists/hte/` are re-frozen as part of
this amendment.

### 5.2 The extractor compares annotation strings — a formatting sweep breaks the freeze

Re-freezing produced diffs in 11 servers that have **no surface change at all**: the PEP 585
sweep (`14a373ef`) rewrote `List[...]` to `list[...]`, and `harness/endpoints.py` records the
annotation as source text. Left unaddressed this is a live hazard in both directions — a
reviewer either re-freezes reflexively (and a real removal rides along unnoticed) or trusts
a stale freeze.

**Rule added to §8.3:** a checklist diff must be evaluated as a **route-set** diff
(path, method) plus a **parameter-name** diff first; annotation-spelling changes are
reported separately and do not by themselves constitute surface drift. The comparison
script used for this amendment is the reference implementation of that rule and belongs in
`harness/` before P4's checklist work.

### 5.3 `control_vis` joins the dependent-surface inventory

§8.3(3)'s per-config module set must now enumerate three vis keys, not two:
`live_vis`, `action_vis`, **`control_vis`**. A station opts into the control page by a
server declaring `control_vis`; without it, `/control` renders only a "none declared"
note. Reach is wider than the Reflex rollout: **15 of 21 hte configs** declare
`control_vis` (paired with a `control_visualizer` Bokeh server), plus `goldenreflex.yml`
and one Deployment-C config — see the table in §2. Any inventory that treats `control_vis`
as a Reflex-era key will miss 11 hte configs.

The same section gains **`reflex:` servers** in its per-config server set, and the
`bokeh_port`-style "invisible port claim" hazard of §8.3(3d) gains its worst case yet:
a `reflex:` server claims `port + 1` with nothing in the config naming that port. One
real collision has already been shipped and fixed (a control panel placed on 5003, which
the Galil aligner binds), which is the empirical argument for treating this as a first-class
preflight check rather than a review habit.

## 6. New phase: P7-UI

Placed after P6. Does not gate P0–P6; D9's corollary is what protects the UI during them.

### P7-UI — both UI stacks onto hexagon

**Scope:** host the Bokeh visualizers/operator/browser and the Reflex app from the hexagon
app layer; the shared layers (`operator/{orch_backend,param_forms,param_store,spec_parser}`,
`data_browser/{readers,sources,state}`, `io_control`) move behind ports rather than being
imported directly; `palette.py` becomes the hexagon tree's colour source too (§7 below);
the aligner visualizer adapter (D6), already in-tree at
`helao/hexagon/adapters/vis/galil_aligner_host.py`, is folded into the same hosting layer
instead of standing alone.

**New ports this phase introduces:**
- **UiHost** — the Bokeh `Server` / Reflex app construction seam. Only the app layer may
  build either. The D6 ban ("a driver may never construct a Bokeh `Server`") is generalized:
  *nothing outside the app layer* may construct a UI host, which the aligner adapter
  currently does (`galil_aligner_host.py:139`) and which P7 resolves.
- **ControlSurface** — the `io_control` logic behind a port, so a control panel in either
  stack drives hardware through one tested path with row-15 semantics and §4.3 fidelity
  reporting.
- The **Status port (§4.3.6) gains a third consumer face** — see §8 below.

**Gate:** this is the first phase whose gate is not an artifact diff, because its subject
writes no artifacts (row 15). Its gate is instead:
1. **Wire-consumer parity** — for every WS channel and private route the UIs consume, the
   hexagon-hosted UI decodes byte-identical frames produced by a hexagon server; asserted
   with the *real* consumer decoders on both sides (§10.1(3), now plural — §8 below).
2. **Rendered parity** — headless-browser checks (the Playwright lane established during
   the UI work) over each route of both stacks: `/`, `/live`, `/action`, `/operator`,
   `/browser`, `/control`, and the Bokeh visualizer/operator/aligner documents. Assert
   **computed styles and drawn content**, never source greps — a stale Reflex bundle
   renders new utilities completely unstyled with no error on either side.
3. **Palette sweep extended over `helao/hexagon/`** and green (§7).
4. **Row-15 negative assertion** — a control toggle against a hexagon-hosted server leaves
   the artifact tree unchanged.
5. Bundle-rebuild step present in every affected station runbook (§9 below).

**Risks:** the Reflex frontend is a *build artifact with a baked backend URL*, so this phase
is the first where a gate can pass on a development machine and fail at a station purely
from a stale bundle; the WebGL context cap (Chrome evicts past 16 live contexts, silently
and permanently for the evicted chart, with nothing logged server-side) makes
"panels render" a per-page budget question, not a per-panel one.

**Rollback:** flip the config's `reflex:`/`bokeh:` server entries back to the legacy
launcher path; both stacks remain in legacy core in-tree.

## 7. New cross-cutting invariant: the palette (extends §10)

`helao/core/servers/palette.py` is the single source of every colour in both UI stacks,
enforced by an AST sweep in `helao/core/tests/test_palette.py`. **The sweep's globs are
`helao/core/servers/**/*.py` and `helao/deploy/*/servers/**/*.py` — `helao/hexagon/` is
outside it.** The tree's one vis adapter today
(`helao/hexagon/adapters/vis/galil_aligner_host.py`) names no colour and never imports
`palette`; it inherits theming only transitively, because `HelaoVis.__init__` calls
`apply_theme` and the adapter constructs a `HelaoVis` (line 158). That is luck, not
structure: the next hexagon vis adapter can hardcode colours and ship green.

**Added to §10 as a mandatory test requirement, effective immediately (not deferred to
P7-UI):** the palette sweep's glob set includes `helao/hexagon/**/*.py`, and any hexagon
adapter that hosts or themes a UI obtains its colours from `palette.py`. Two notes for
whoever implements it:

- The sweep's exemption list is pinned by a test to **exactly two entries**
  (`palette.py`, `bokeh_theme.py`) by exact path. Extending the glob must not extend the
  exemptions; a hexagon module needing a literal is a design error, not an exemption.
- The sweeper is calibrated against frozen fixtures under
  `helao/core/tests/fixtures/sweeper_calibration/` with pinned line numbers. Do not
  reformat that directory while extending the globs.

## 8. Amendments to the Status port and fixture rules (§4.3.6, §10.1)

§4.3.6 describes two parallel WS mechanisms and §10.1(3) says to decode with "the real
consumer's decoder", singular. There are now **three** consumer classes, and the third one
distinguishes payloads the first two do not:

`helao/core/servers/reflex/ingest.py` selects a normalizer **by `ws_path`**, because
`ws_live` relays a `{datalab: (value, epoch)}` dict while `ws_data` carries a pickled
`DataPackageModel` whose samples sit at `.datamodel.data[key][column]`. A single
normalizer silently drops the other endpoint's messages with no error on either side.

**Amendments:**
1. §4.3.6 enumerates three consumer faces: Bokeh `WsSubscriber`, the zstd-pickle
   `_ws_relay` stream, and the Reflex `ingest` normalizers — the last keyed by channel, not
   uniform across channels.
2. §10.1(3) becomes plural: a wire-format test decodes with **every** real consumer decoder
   registered for that channel. A WS adapter that satisfies `WsSubscriber` alone is not
   covered, and its failure mode is a blank panel with a healthy server.
3. A further trap worth pinning in the same tests: **not every HELAO data column is
   numeric.** Datasets carry an orchestrator host or a status string beside the traces;
   handing one to a plotting facade raises `could not convert string to float` from inside
   the render and takes down the whole chart. Column filtering is consumer-side behavior
   that a hexagon-hosted UI must keep.

## 9. Corrections to §9 and §11 (statements now false, and missing facts)

### 9.1 §9.2(3) — wrong as written

> "exactly one of `fast`/`bokeh`"

Correct: **exactly one of `fast`/`bokeh`/`reflex`** (`launch.py:583`). And the uniqueness
check is no longer one address per server: a `reflex:` entry claims `host:port` **and**
`host:port+1`, resolved by `reflex.discovery.reserved_addresses` (`launch.py:61`). The
preflight validator inherits both, and the second is the load-bearing half — nothing else
in the config may claim `port + 1`, and nothing in the config mentions it.

### 9.2 §9.4 — hot-reload snapshot statement incomplete

The master spec attributes the `STATES/loaded_modules_<key>.json` startup snapshot to bokeh
servers. **Reflex servers use the same snapshot path** for the same reason: neither exposes
a `/loaded_modules` HTTP route, and `server_loaded_files` (`launch.py:1570`) branches on
`"fast" in server_entry`, sending both bokeh and reflex down the snapshot path. Read the
statement as "bokeh **and reflex** servers".

### 9.3 §9.4 / §11 — process-lifecycle facts added since

§9.4's kill contract (SIGTERM → 7.0 s → SIGKILL, pid pickles) is still accurate but is no
longer the whole mechanism. Added:

- **Linux:** each launched server arms `PR_SET_PDEATHSIG` at its entry point
  (`helao.helpers.parent_death`). The signal is scoped to the *spawning thread*, so the
  handler re-checks `getppid()` and re-arms; arming must not move into a `preexec_fn`
  because `launch.py` is multi-threaded.
- **Windows:** containment is a Job Object on the **launcher** with
  `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` (`helao/helpers/win_job.py`), inherited by spawned
  children. **The job handle must stay referenced for the launcher's whole life — closing
  it kills the group.** §11 gains this as a subsection; it is the Windows half of a
  guarantee §9.4 currently describes only in POSIX terms.
- **Both:** CTRL-d writes `STATES/detached_<prefix>_<extraopt>.marker` and a server finding
  it stands down instead of shutting down; on Windows CTRL-d must *clear* the
  kill-on-close limit first, since a process cannot be removed from a job.
- `--reconnect` / `--force-relaunch` semantics, and live-member confirmation by cmdline
  match against `<fast|bokeh|reflex>_launcher.py <configPrefix> <server_key>` rather than
  `pid_exists` (a recycled PID must never read as a live server).

### 9.4 §11.5 — verification placement gains a Linux browser lane, and stations gain a build step

- **New Linux lane:** headless-browser checks are available in this environment and were
  used throughout the UI work. Rendered-UI verification is therefore *not* inherently an
  at-station activity; only hardware-backed panels are. §11.5's Linux column gains
  "rendered UI checks against sim configs".
- **New station step:** the Reflex frontend is a prebuilt bundle with the backend URL baked
  in at export. A bundle built for one config's port serves a **blank, silently
  disconnected** page under a config on any other port. Rebuild is required whenever a
  config's port changes **or** any `class_name=` usage changes, because the compiled CSS
  contains only the utilities present at build time and a stale bundle renders new ones
  completely unstyled with no error. Every station runbook for a config carrying a
  `reflex:` server gains an explicit `build_reflex_bundle.py` step with a rendered check
  after it. Bokeh needs only a restart — the asymmetry is the thing to remember.

### 9.5 §10.5 — suite shape

`run_tests.py` now sweeps the whole tree **one file per pytest process**, because collecting
the tree as a single session hangs indefinitely and ignores SIGINT while the same files pass
individually (the tests start event loops, bind sockets, and spawn Bokeh servers). Third-party
import failures report `ENV`, not `FAIL`; a missing `helao*` module stays a failure. The
hexagon suite inherits this: run it per-file. `run_unit_tests.py` remains the fast pre-launch
gate and is deliberately separate.

## 10. Amendments to the per-deployment phase scopes (§12)

Deltas only; everything else in each phase stands.

- **P3 (hte) — reopened at the checklist level, not the code level.** Its frozen checklists
  are re-frozen here (§5.1); its at-station gates were still open, so no station diffed
  against the stale baseline. Its dependent-surface inventory gains `control_vis`
  (15 configs) and `reflex:` servers (3 station configs + 1 dev config). The three
  Reflex-carrying stations' runbooks gain §9.4's bundle step; the other twelve
  control-panel stations need only a visualizer restart.
- **P4 (Deployment-A) — one new decision, otherwise unchanged.** It has no Reflex panels
  today. Under D9 that is a *choice*, not a gap: P4 may ship with Bokeh only and gain
  Reflex panels later, since panels resolve by the same config keys in either stack and a
  station opts in by adding a `reflex:` server and changing nothing else. **Recommended:
  Bokeh only for P4**, so the phase's hardware gate is not entangled with a bundle build at
  a station that has never run one. Its Advantech server already carries the private
  digital-out pair, so its checklist re-freeze must pick that up.
- **P5 (Deployment-B) — scope grew.** It gained 5 config-selected Reflex panels (6 modules)
  and its own palette-sweep test, wired only in a dev config so far. Both are P7-UI
  subjects, not P5 subjects, but P5's dependent-surface inventory must
  list them, and D9's corollary applies with unusual force here: P5 is the phase that
  *deletes* a duplicated estop cascade whose second copy lives **in a visualizer**. That
  deletion touches UI code during a non-UI phase. It stays in P5 (the master spec's §4.2.5
  and P5 scope are unchanged), and the at-station estop drill remains its gate — but the
  drill must now be run against **both** UI stacks if that station carries a `reflex:`
  server, because a stack whose buttons were not re-pointed at `EstopPolicy` is a
  safety-relevant regression that no artifact diff would catch.
- **P6 (Deployment-C) — unchanged scope, one inventory addition with a wrinkle.** One
  station config declares **both** `control_vis` and a `reflex:` server while the deployment
  has **no Reflex panel modules of its own** — the panel resolves to the hte module by the
  launcher's cross-deployment fallback. So this deployment's UI surface is partly *hte's*
  code, and P6's dependent-surface inventory must record the cross-deployment edge rather
  than reporting "no panels". Its runbook needs the bundle step even though it ships no
  panel source.

## 11. Open questions added

- **Q8 — Does the shared-layer split survive porting?** `operator/param_forms.py`,
  `param_store.py`, `spec_parser.py`, `data_browser/{readers,sources,state}.py` and
  `io_control.py` are backend-agnostic layers with two UIs over each. P7-UI must not fork
  them per stack. Whether they become ports, or stay imported modules the hexagon app layer
  calls directly, is a P7 design question. Default: ports for anything that reaches the
  network or the filesystem (`orch_backend`, `param_store`, `spec_parser`, `io_control`),
  plain shared modules for pure logic (`param_forms`, `readers`).
- **Q9 — Where does `palette.py` live after P7?** It is dependency-free and currently under
  `helao/core/servers/`. Moving it into the hexagon tree would break the legacy stack that
  still consumes it during coexistence; leaving it makes the hexagon tree import legacy
  core for colours, which the boundary rule permits for adapters and forbids for domain
  (colour is adapter territory, so this is legal — but it should be a stated choice, not an
  accident). Default: leave it, and extend the sweep (§7) rather than move the module.
- **Q10 — Is a spec parser's absence a gate failure?** A deployment's spec parser is code
  this repo never sees, loaded by path, and every function degrades to "nothing configured"
  rather than raising — a broken parser disables a tab instead of taking down a page. Good
  behavior for an instrument; ambiguous for a gate, which cannot distinguish "no parser
  configured" from "parser broken". P7's rendered checks need an explicit answer.

## 12. What this amendment does not change

- No locked decision of §3 is altered. D9 is additive.
- The artifact parity contract (§5 rows 1–14), the normalizer's volatile list (§5.5), and
  the golden-master procedure (§6.1–6.5) are untouched. Row 15 is additive and negative;
  §4.2's capture-window rule is procedural.
- No phase gate P0–P6 is weakened. P3's checklist baseline is *refreshed*, which tightens it.
- The Bokeh stack remains the production UI. `bokeh_operator.py` is named by 32 configs and
  `test_standalone_operator.py`'s 48 tests must pass with it unedited — that constraint
  outlives P7-UI and is not a migration target.
