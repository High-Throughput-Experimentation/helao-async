# P5 — Deployment-B Migration: Decomposition & Sequencing

> **Status:** authored 2026-08-05; **P5a is DONE** (checklist baseline re-frozen the same day),
> the rest of the phase is unstarted. **P4 closed 2026-08-05** — its station smoke passed — so
> this phase is unblocked and is the active one. The phase's
> **inputs** are already in place and were re-measured for this plan: the dependent-surface
> inventory and hardware canaries landed with P3-pre, `EstopPolicy` landed with P1, and the
> audit's "stale driver test" has since been repaired. Locks sub-project boundaries, dependency
> order, and the Linux/at-station gate split for P5 of the hexagonal rewrite (master spec:
> `docs/superpowers/specs/2026-07-16-framework-hexagonal-rewrite-design.md` §P5, as amended by
> `2026-08-04-hexagonal-rewrite-ui-amendment.md`; mandated per §13).
>
> **This is the public mirror.** The executable plan — real file paths, line numbers, per-slice
> task lists — belongs in the private deployment repo, where real names are permitted. This
> document carries structure, decisions, gates and measured state in **Deployment-B** alias
> form so the phase-plan series is complete in the public repo. Where the two disagree, the
> private plan is authoritative on tactics and this one on gates.
>
> **Privacy (binding):** Deployment-B alias only. No real deployment or nested-repo names,
> hostnames, config filenames, library module names, or campaign identifiers. Ground truth:
> `.omc/research/framework-rewrite/deploy-B.md` + the deployment's own frozen audits.

## Goal

Finish Deployment-B's hexagon migration at parity, with the **estop cascade extraction as the
phase's centre of gravity**: replace two drifted hardcoded cascades with one `EstopPolicy`
consumer, give the deployment its first Linux-testable launch path via simulated adapters, drop
the dead library mass, and disposition the audited latent bugs without changing dispatched
params. Terminal state: the station config flips to `deployment: hexagon` with per-server
rollback, gated by an at-station **estop drill**.

## The audited surface (spec §8.1, frozen map `deploy-B.md`, re-measured 2026-08-05)

- **3 action-server modules**, 32 frozen routes (10 / 12 / 10), checklists in the deployment's
  own `tests/checklists/` — resolved by `helao/hexagon/preflight.py`'s private-aware
  `_checklist_dir()`.
- **3 real driver classes, all 3 already on the `HelaoDriver` ABC + `DriverPoller`** — the
  CARDS "0/4 on ABC" figure was stale and the audit already corrected it. Plus one 0-byte stub
  file. All three drivers are **cross-platform** (pyserial / plain TCP / asyncua): there is no
  Windows-only vendor backend in this deployment's own code.
- **All 3 servers drive hardware**, so all three are in the hardware-canary gate. The
  potentiostat and syncer in its group are shared modules owned by other phases.
- **23 experiments / 1 module (2,863 ln); 6 sequences / 1 module (1,427 ln)** — of which
  **1,305 lines are a contiguous dead tail** holding zero live code (28% of the experiment file,
  34% of the sequence file; measured, see P5d).
- **1 launchable group config**, plus 2 driver *data* YAMLs shipped in `configs/` (a serial
  command keymap and a ~150-alias OPC-UA node map) and 1 Reflex dev config.
- **Cross-deployment coupling:** its group borrows the potentiostat server, the syncer, the
  orchestrator, the operator, both Bokeh visualizer shells, and — newly measured — the
  potentiostat *panel* in both UI stacks. This deployment contributes 3 action servers and
  4 panels per stack; everything else in its group is foreign.

## Corrections to the spec and Amendment, measured

Recorded here because both numbers are wrong in the source documents, and the P4 phase showed
that an unchallenged count becomes invented work later (`compute the gate numbers, don't assert
them`).

1. **Spec §P5 says "it gained 7 Reflex panels". It has 4.** Amendment 1 §10's own table says
   "6 = 5 config-selected + 1 helper", which is closer but still off. Measured: the Reflex
   directory holds **4 config-selected panel modules, 1 shared helper, 1 package `__init__`**
   = 6 files. The "5th config-selected panel" is real but **foreign** — the group declares a
   potentiostat panel name this repo does not ship, which resolves to the public deployment's
   module, present in *both* stacks. Honest statement: **4 local + 1 cross-deployment**. This
   is the same cross-deployment panel edge the Amendment flagged for Deployment-C; it applies
   here too.
2. **Amendment 1 §10 conditions the dual-stack estop drill on "if that station carries a
   `reflex:` server". It does not.** The live station config declares no `reflex:` server and
   no `control_vis`; the only `reflex:` entry is in a dev config. So the P5 drill is
   **Bokeh-only**, and this deployment needs no bundle-rebuild step in its runbook — unless the
   station opts in before the window opens, which is a config change, not a code change.
3. **New finding, not in either document: the Reflex panels have no estop buttons.** The Bokeh
   station panel carries three; its Reflex counterpart is plot-only. A Reflex-only station
   would present **no emergency-stop control**, and nothing would flag it — the panel renders,
   it just lacks the buttons. Latent today (no station declares `reflex:`). Filed as a
   **P7-UI blocker**, and it bounds what P5 may claim: after P5, only the Bokeh stack has
   buttons to re-point at the policy.

## Hard constraint: the Linux / at-station gate split

Spec §P5 calls this deployment **"HARDWARE, no Linux path"**. That is true of the *config* —
Windows `root:`, a live serial port, a private-LAN OPC-UA endpoint and robot IP — but **not of
the code**: all three drivers are cross-platform. So the "no Linux path" is a missing-simulator
problem, not a platform problem, and P5c fixes it rather than working around it. This is the
single biggest difference from P3/P4, where Windows-only vendor SDKs made the ceiling real.

**Consequence for sequencing:** P5c (simulators) moves *early*, because it converts P5b's
safety-critical work from "reviewable on Linux, provable only at station" into "rehearsable on
Linux before the station window". Spec §P5's own risk note already requires this — "the estop
drill is non-negotiable and rehearsed against sims first" — which cannot happen if the
simulators are built last.

## Explicitly OUT of scope this phase

Carried as post-parity backlog, per spec §P5:

- **The duplication mass in the libraries.** The audit quantified it: a 4-line metadata
  fragment repeated 31×, a 4-kwarg thread through ~20 signatures, a 7-key parameter dict
  repeated 6×, and ~200 lines of a 3-stage ramp skeleton duplicated between two functions that
  differ only in parameter granularity. Deleting *dead* code is in scope (P5d); deduplicating
  *live* code is not — it changes dispatched params, and parity comes first.
- **The recorder-sandwich pattern** written longhand 5× (a context-manager candidate) and the
  **unit-scaling smear** where a load value's ÷10 correction is applied in three different
  layers. Noted, not refactored.
- **The RTDE parser's hardcoded byte offsets**, brittle across robot-controller versions and
  acknowledged as such in-code. Not touched: rewriting a parser under a parity gate trades a
  known-working brittleness for an unknown one.
- **A native rewrite of any of the three drivers.** They are already ABC-conformant; there is
  no parity gain and it would consume the station window.

## Sub-project decomposition & dependency order

```
P5a (checklist re-freeze)          Linux-only, BLOCKING — DONE 2026-08-05
        │
P5c (simulated adapters) ──────────Linux-only  ← moved early, see above
        │
P5b (estop extraction) ────────────Linux-authorable + AT-STATION drill
        │
P5d (dead code drop) ──────┐       Linux-only, independent of P5b
P5e (latent-bug disposition)┤      Linux-only, independent of P5b
        │                   │
P5f (config + canary closure) ─────Linux-only
        │
P5g (assembly: flip + station window)  ── terminal HARDWARE gate
```

P5d and P5e are independent of the estop work and of each other; they can run in parallel with
P5b once P5a has landed.

### P5a — Checklist baseline re-freeze *(Linux-only; BLOCKING prerequisite — **DONE 2026-08-05**)*

**Discharged.** All 18 routes accepted with the changed-params flag; route counts held
byte-identically (10 / 12 / 10) and a follow-up dry-run reports zero drift. Measured breakdown:
**48 param defaults** rewritten from the unwrapped form to the raw param-function text, plus
**exactly 1 annotation** (`List[…]` → `list[…]`). Both wire-invisible, each verified rather than
asserted — `List[X]` and `list[X]` were measured to emit byte-identical OpenAPI, and all 48
default rewrites were AST-checked to be the same value re-expressed (the new default parses to a
call whose first positional argument is the old recorded text).

**One correction to the diagnosis below:** it attributed the drift entirely to the tooling
generation mismatch. 48 of 49 deltas are that; the single annotation delta is a genuine source
change from the PEP 585 typing sweep that landed after the freeze. So the baseline was stale for
two independent reasons. Nothing about the chosen fix changes — but "purely the wrapper text" was
an overstatement, and the same care applies to the next deployment's baseline: check for *both*
causes before concluding a re-freeze is transcription-only.

**Measured problem.** `harness/freeze.py <deployment> --dry-run` reports **18 routes with
changed `[params]` and zero route-set changes**. This is not source drift. These checklists were
frozen 2026-07-20 by the pre-generic, deployment-specific freezer, which **unwrapped** a FastAPI
param function to its first positional argument; the current generic freezer `ast.unparse`s the
written default. Traced conclusively: every `Query(...)` occurrence was **already present in the
source at the freezing commit**, so nothing in the deployment changed.

**Decision: re-freeze to the raw form.** This deployment is the odd one out — the public
deployment's baselines already store the raw text in 3 checklists and Deployment-A's in 2. And
the raw form is strictly *more* faithful: one public baseline records a default carrying `ge`
and `le` constraints, which **are** wire-visible in OpenAPI as `minimum`/`maximum` and which the
unwrapped form silently discards. Teaching the extractor to unwrap would therefore lose
wire-relevant information *and* invalidate two other deployments' baselines.

*Rejected:* (a) unwrapping in the extractor — loses constraints, breaks two other deployments;
(b) leaving the drift unapplied — it would fire as 18 false mismatches the day the runtime
`/openapi.json` cross-check runs, inside a scarce station window, which is precisely the failure
P4's motion-annotation defect would have caused; (c) a per-deployment extractor mode — two
baseline dialects is the disease, not the cure.

**Steps:** re-freeze with the changed-params flag (never the missing-route flag — the hardened
freezer requires per-route authorization to delete, and no route is being deleted); confirm the
route set is byte-identically 10/12/10; commit with the transcription rationale in the message.

**Gate:** freeze dry-run reports zero drift; route counts unchanged; the deployment's test suite
still green.

### P5b — Estop cascade extraction *(the phase's centre; Linux-authorable, AT-STATION drill)*

**Four call sites fire the cascade today, across two implementations that have drifted.** The
driver-resident cascade is invoked by an OPC-UA fault rising edge *and* by a top-level
`POST /execute_gamry_stop` route; the Bokeh station panel carries three buttons. Both
implementations read the server topology out of the world config and fire **raw HTTP at
hardcoded server keys** — a device adapter and a UI reaching sideways into orchestration.

**The measured drift is one line.** The driver puts the *resolved* recorder key in the path; the
visualizer hardcodes one key's prefix while resolving the host from either. Because an action
route is `/{server_key}/{action}` and never a bare `/{action}`, the visualizer's recorder-stop
leg **404s under a config that keys the recorder differently**, while the driver's identical leg
succeeds. Latent at this station (its config uses the hardcoded key), live under the other. This
is exactly the "duplicated with drift" the spec's §4.2.5 cites as the reason for one policy.

**The design gap P5 must close.** `EstopPolicy` (already built, P1) is a pure
trigger → ordered-command function, with topology derived from `group: orchestrator` plus
`estop_roles: [recorder|stop_private]` tags, and **cascade order fixed in policy, not config**
(Q7, resolved). But its `UiEstopButton` trigger yields the full orchestrator→recorder→private
cascade — which is **one** of the three buttons. The other two are strictly smaller: one sends
only the graceful stop to orchestrators, the other only the estop route to orchestrators.
Mapping all three onto the existing trigger would **change two buttons' wire behaviour**, on a
safety path.

**Decision: extend the policy with the two missing triggers rather than collapsing the
buttons.** Three distinct triggers, three command tuples, every button's wire preserved
byte-for-byte. *Rejected:* (a) one trigger for all three buttons — silently escalates SAFE STOP
into a full cascade and downgrades ESTOP from the estop route to the graceful one, both
safety-relevant and neither visible in an artifact diff; (b) a "scope" parameter on the existing
trigger — same commands, worse discoverability, and it invites a caller to pass the wrong scope;
(c) leaving the two smaller buttons on raw HTTP — leaves the UI an orchestration client, which
is the thing this phase exists to delete.

**Also in this slice:** the fault-monitor trigger and the top-level route both route through the
policy; the driver stops reading the injected base hook for topology (closing the same
back-channel class of finding P4a closed); the top-level route is **preserved on the wire**,
including its non-standard bare-boolean response, and now delegates.

**And the poller-lifecycle deviation, which belongs here rather than in a driver slice.** Spec
§P5 lists it as a risk: this deployment's OPC-UA poller **starts its own asyncio task in
`__init__`**, deviating from the sanctioned poller lifecycle, because its composite read is
inherently async while the base poller's data hook is called synchronously — so its hook just
returns the latest cached reading. That self-started loop is **also where the fault monitor
lives**, i.e. where the estop trigger fires. Re-pointing the trigger at the policy and
regularizing the loop's ownership are the same edit, and separating them would mean touching the
loop twice. Constraint: the poller must be stopped before disconnect on shutdown, and the
device must be open before the loop's first tick — a poller-backed driver that opens its device
later spams the log against a null handle.

**Gate:** policy unit tests covering all three triggers plus the fault edge; a dispatch-log
equivalence test asserting the policy emits the *same ordered wire calls* the legacy cascades
emitted, with the drifted leg asserted against the **driver's** correct form (the visualizer's
404-ing form is a bug, not a baseline — fixing it is wire-visible and needs a recorded
sign-off in the P5 commit, since a leg that currently 404s cannot have a consumer depending on
it); the frozen checklist unchanged including the top-level route; **and the at-station estop
drill**, Bokeh-only per correction #2, asserting via recorded dispatch log that the policy fires
what the legacy cascade fired.

### P5c — Simulated adapters *(Linux-only; moved early)*

The deployment has **zero Linux-testable launch path** today — its one group config needs a
serial device, a robot on the LAN, and a live OPC-UA server. All three drivers are
cross-platform, so simulators are genuinely achievable here (unlike P3/P4's vendor SDKs): a
serial press stub speaking the keymap's command templates and the poller's expected status
lines; a robot stub answering the dashboard and secondary-interface protocols; an OPC-UA server
stub serving the node-alias map.

**Why early:** spec §P5 requires the estop drill be "rehearsed against sims first". That is
impossible if the sims land after P5b. Moving P5c ahead converts the safety work from
station-only to Linux-rehearsable, which is the highest-leverage reordering in this phase.

**One hazard to design around:** the station server's entire action surface registers **only
when the OPC-UA connect succeeds** — the endpoints sit inside a connection-gated block. Off
station, its openapi surface is *empty*, which the existing canary docs already flag as this
deployment's "invisible port". A simulator that satisfies the connect is therefore what makes
that server's surface diffable on Linux at all.

**Gate:** a simulated group config that preflights non-vacuously and launches on Linux; each
simulator exercised by construct-tier tests; the station server's full 10-route surface visible
under simulation.

### P5d — Dead code drop *(Linux-only)*

**Measured 2026-08-05, not estimated: 1,305 lines** — each library module ends in one contiguous
dead tail (814 lines and 491 lines) containing **1,242 commented-out lines, 63 blank lines, and
zero live code**. That "zero live code" is what makes this slice safe and mechanical: both
regions are deletable to the last line without reading them, because nothing executable is
interleaved. Contents are four whole commented-out variants of the condition-ramp function and
five commented-out sequences.

Dead code is not surface, so there is no parity consequence — but it must be a **separate commit
from every live-code change**, so a later parity bisect never has to distinguish a deletion from
an edit.

**Gate:** the library-export guard and import sweep green; the registered experiment and
sequence name lists byte-identical before and after.

### P5e — Latent-bug disposition *(Linux-only)*

The audit found parameter-key mismatches where a sequence passes names the target experiment's
signature does not have — so those experiments **run with defaults, silently**. Plus a record
endpoint that reads a poll-rate key unconditionally (raising if the caller omits it), and a
handler that sets a version field to an imported *decorator function* rather than a number.

**Decision: split by wire visibility, as P4d did.** Fixing a silently-dropped parameter
**changes dispatched params**, hence artifact bytes — so each such fix needs an individually
recorded sign-off, and the permitted direction is the one where the *caller* is corrected to the
callee's frozen signature, never renaming a frozen endpoint parameter to match a broken caller.
The unconditional-key read and the decorator-as-version bug are wire-invisible crash/garbage
repairs and go in as ordinary fixes with tests.

**Explicitly not fixed here:** the deliberately-`None`-defaulting annotations of the P4 Tier-C
class, if the sweep finds any in this deployment — that is a separate coordinated change.

**Gate:** a test per disposition; every wire-visible fix named in its commit message with the
recorded reason.

### P5f — Config + canary closure *(Linux-only)*

Add the simulated group config from P5c as the non-vacuous preflight target and pin it, matching
how Deployment-A pins its configs by shelling the preflight CLI. Add the `estop_roles` tags the
policy's topology derivation needs to the station config and the simulated one — a config-only
change with a loud failure mode by design: an unknown role string raises rather than silently
yielding an empty cascade.

**Gate:** every tracked config preflights exit-0; the topology derived from the station config
reproduces exactly the key sets the legacy cascades computed by prefix-matching.

### P5g — Assembly: hex flip + terminal at-station smoke *(terminal HARDWARE gate)*

1. **Flip the station config in place** — `fast: graft` + `deployment: hexagon` +
   `legacy_module:` per action server, orchestrator/operator/visualizer entries untouched.
   **Adopt P4f's resolution:** flip in place and do not create a parallel hex config, so the
   station's real hardware params live in exactly one file and rollback is per server (delete
   two keys, restore the module name). P4f's rehearsal-variant duplicate was deleted for this
   reason; do not reintroduce the pattern here.
2. **At-station, single risk-ordered window:** full-group hex launch; the **estop drill first**
   (it is the phase's safety gate and everything else is informational if it fails); the three
   action-server runtime diffs; one fault-triggered cascade from the real fault source if it can
   be provoked safely, else the top-level route as the trigger. **Rollback is per server.**

**Runbook constraint inherited from P4f:** preflight the **in-tree** config path. The validator
infers the deployment from the config's path, so a config copied to a scratch directory yields
no deployment and the checklist gate **passes silently**.

## Decisions

1. **Re-freeze the baseline to the raw param-function form; do not teach the extractor to
   unwrap.** Rationale and rejected alternatives in P5a. The deciding measurement: the raw form
   preserves numeric constraints that are wire-visible in OpenAPI; the unwrapped form discards
   them.
2. **Extend `EstopPolicy` with two additional triggers; do not collapse the three buttons.**
   Rationale and rejected alternatives in P5b. The deciding fact: two of the three buttons send
   strictly smaller command sets, and collapsing them changes a safety path's wire in both
   directions.
3. **Build the simulators before the estop extraction, not after.** Reordering against the
   spec's listed order, justified by the spec's own requirement that the drill be rehearsed
   against sims first. Costs nothing: no other slice depends on the estop work.
4. **Fix the visualizer's drifted recorder-stop leg to the driver's correct form.** It is
   wire-visible, so it needs a recorded sign-off — but the leg currently 404s under the config
   where it differs, so no consumer can depend on the broken shape. Same reasoning P4d used, and
   the same limit: correct the caller toward the frozen route, never the route toward the caller.
5. **Leave both UI stacks on legacy core (D9), and do not port the Reflex safety buttons in
   P5.** The Reflex panels' missing estop buttons are a real gap (correction #3) but fixing it
   means adding a control surface to a UI, which is P7-UI's subject and needs the ControlSurface
   port. P5 must simply not claim dual-stack coverage it does not have.
6. **Delete the vestigial panel module referenced by no config.** It has no counterpart in the
   other stack, no server to subscribe to, and no config naming it. Dead surface.
7. **Keep the two driver-data YAMLs in the config directory.** Shipping behaviour tables beside
   group configs is unusual, but they are referenced by path from server params and moving them
   is a config-breaking change with zero parity gain. Post-parity cosmetic.

## Global constraints (inherited; apply to every slice)

- **Parity first.** No wire-visible change without a recorded per-item sign-off in the commit
  message. Dispatched params, route order, response shapes and artifact bytes are the contract.
- **Run the deployment's tests per-file with a timeout**, not as one pytest session — the suite
  hangs when collected as a single session while passing per-file.
- **Format with the project formatter as the final step before every commit**, in the repo that
  owns the files.
- **Branch per sub-project; no commit or push without authorization.** Parent-repo commits and
  docs use the **Deployment-B** alias; the private repo's own commits may use real names.
- **Never name a private deployment in a tracked parent-repo file.**

## Execution note

**Current state, verified 2026-08-05:** the phase's inputs are in place — the dependent-surface
inventory exists and was extended today with the UI-stack surface, the estop-surface map, and
the baseline-drift finding; the hardware canaries exist for all three servers; `EstopPolicy`
exists with Q7 resolved; the audit's "stale driver test" was repaired and now passes. The
deployment's own suite is green (3 test files: library exports, palette sweep, 25 Reflex panel
tests). No P5 code has been written.

**P5a — the one blocking item — is DONE** (2026-08-05): baseline re-frozen, route counts held,
dry-run clean, 49 param records rewritten and both delta classes verified wire-invisible. The
next slice is **P5c (simulators)**, per the reordering in Decision 3, and the next *artifact* is
the private executable plan with real paths and per-slice task lists.

**What has no Linux path even after P5c:** only the terminal station window itself — the real
serial press, the real arm, and the real fault source. Everything else in this phase, including
the estop drill *rehearsal*, becomes Linux-runnable once the simulators land, which is why they
moved early.
