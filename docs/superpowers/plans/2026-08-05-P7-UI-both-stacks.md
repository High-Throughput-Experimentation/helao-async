# P7-UI — Both UI Stacks onto Hexagon: Decomposition & Sequencing

> **Status:** authored 2026-08-05; unstarted. Branch `feat/hexagon-p7-ui`. Locks sub-project
> boundaries, dependency order, the Linux/at-station gate split, and the answers to open
> questions Q8/Q9/Q10 for P7-UI of the hexagonal rewrite (master spec:
> `docs/superpowers/specs/2026-07-16-framework-hexagonal-rewrite-design.md` §12 P7-UI, as added
> and amended by `docs/superpowers/specs/2026-08-04-hexagonal-rewrite-ui-amendment.md`;
> mandated per master spec §13).
>
> **Prerequisite state:** P0–P5 complete (P4/P5 station gates passed 2026-08-05); P6 is
> Linux-capturable and does not block P7's Linux work — P7 slices touch no analysis writer.
> Where a P7 slice touches a surface P6 also touches (none identified), P6 wins.
>
> **Privacy (binding):** the three private nested deployments are **Deployment-A**,
> **Deployment-B**, **Deployment-C** in this document and in every parent-repo commit. No real
> deployment or nested-repo names, hostnames, config filenames, or module names from those
> repos. Work inside a private repo is described here by alias and executed there on that
> repo's own branch, where real names are permitted.
>
> **Ground truth:** two recon reports (hosting seams; wire-consumer surface) measured in-tree
> 2026-08-05. Every number below marked *(measured)* was verified that day; do not contradict
> one without re-measuring.

## Goal

Host both UI stacks — the Bokeh visualizers/operator/browser/aligner and the Reflex app —
from the hexagon app layer, with the shared UI logic layers behind ports, without changing a
single wire byte or rendered pixel either stack consumes or produces. Terminal state: any
config can flip a `bokeh:` or `reflex:` server to `deployment: hexagon` exactly the way it
flips a `fast:` server, with per-server rollback; `EstopPolicy` is reachable from both stacks'
station panels instead of exactly one; and the phase's five gate items (Amendment §6) are
discharged by named tests. This is the first phase gated on wire/rendered parity rather than
an artifact diff, because its subject writes no artifacts (row 15).

## Entry state and the D9 handoff

**What P7 inherits** *(all measured 2026-08-05)*:

- `helao/hexagon/` = 181 files, 34,329 lines; `ports/` = 17 modules, all
  `@runtime_checkable Protocol`. Relevant existing ports: `StatusPort`
  (`ports/status.py` — publish-side only), `TransportPort` (`ports/transport.py:24-45`),
  `LoggingPort` (`ports/logging.py:20`), `AnalysisArtifactPort` (`ports/analysis.py`).
- **The Bokeh hosting seam is scaffolded, not wired.** `makeVisApp`
  (`helao/hexagon/app/factory.py:123-134`) is a compat facade that attaches **no wiring**;
  three 14-line shims route through it
  (`helao/deploy/hexagon/servers/visualizer/{live_visualizer,action_visualizer}.py`,
  `.../operator/standalone_operator.py`), each hardcoding
  `LEGACY_MODULE = "helao.deploy.hte..."` — **a private deployment cannot use them**. The
  action path already solved this generically: `graft.py` reads `legacy_module:` from config
  (`helao/deploy/hexagon/servers/action/graft.py:42-64`). P7's Bokeh work is giving the
  scaffold real wiring and the generic treatment, not inventing a route.
- **`reflex:` has no module-resolution seam at all.** `reflex_launcher.py:585` hardcodes
  `from helao.core.servers.reflex import app as _reflex_app`; the backend is a spawned
  grandchild `reflex run --env prod --backend-only` (`reflex_launcher.py:630-658`) whose
  entry module `helao/core/servers/reflex/_app/helao_ui/helao_ui.py` is a one-line import of
  `helao.core.servers.reflex.app.app`. All 5 tracked `reflex:` values are the **bundle name**
  `helao_ui`, not a module. `preflight.py:170-178` actively rejects `deployment: hexagon` on
  a reflex server, citing D9.
- **Five UI-host construction sites**: `bokeh_launcher.py:199-216`;
  `helao/core/servers/vis.py:26-42` (`HelaoVis.__init__` → `apply_theme` at `:41`);
  `helao/hexagon/adapters/vis/galil_aligner_host.py:139-145` (constructs a Bokeh `Server`
  inside an action-server process — the standing D6 exception P7 folds in) and `:158`;
  `reflex_launcher.py:462-483` (frontend FastAPI + `/xy/buffers` proxy + `StaticFiles`,
  mount order load-bearing); `helao/core/servers/reflex/app.py:487-495` (`rx.App`, six
  unconditional `add_page` at `:496,497,507,517,522,527`, `_ensure_panel_states` at
  `:368-406` MUST precede `add_page`).
- **The wire surface the UIs consume** — six WS routes, **two producer families with
  different payload types under the same route names**, 30 private routes, one UI-internal
  HTTP route. Detailed in the slice sections; this asymmetry is the single most load-bearing
  fact for gate item 1 and is stated nowhere in spec or amendment (Corrections §C1).
- **The estop asymmetry** *(measured; P5 filed it as a P7 blocker)*: `EstopPolicy` is
  reachable from exactly one UI surface in the tree — Deployment-B's Bokeh station panel
  (3 buttons via `EstopExecutor.fire`). Both operators' single ESTOP buttons
  (`operator/bokeh_operator.py:510-523,1971-1973`; `operator/app_reflex.py:148,2892`) call
  `estop_orch` directly. Deployment-B's Reflex station panel has **zero** estop buttons;
  `grep -rn 'estop' helao/deploy/*/servers/reflex/` returns nothing. Second gap of the same
  class: Bokeh `gamry_vis.py:226` / `biologic_vis.py:400` (and Deployment-B's Bokeh
  potentiostat panel `:601`) carry `stop_private` stop-measurement buttons; **no Reflex
  panel calls `stop_private`** — a Reflex-only station cannot abort a running potentiostat
  measurement from the UI.
- **Regression floor: 1158 UI tests, all green today** *(measured)* — core UI suites 964
  (incl. `test_standalone_operator` **59**, `test_palette` 169, `test_reflex_operator` 174,
  `test_motion_control` 58, `test_reflex_motion_control` 65), deployment UI suites 175,
  hexagon UI-adjacent 19 (`test_ws_publish_bridge` 2, `test_vis_gate_config` 3,
  `test_galil_aligner_host` 14). Every slice gate below includes "the floor holds".

**The D9 handoff.** Through P0–P6, D9's corollary was a *constraint*: no phase changes a WS
payload shape, a private route, or a config key that either UI stack consumes without
updating that stack in the same commit. In P7 that corollary stops being a guard rail and
becomes the phase's subject — but it does **not** lapse. Restated for this phase: **P7 moves
the hosting, never the wire.** The legacy stack is the wire and rendered baseline; every WS
frame encoding, private-route path/payload/response shape, config key, and rendered pixel is
frozen exactly as the artifact tree was frozen for P1–P6. A P7 slice that changes a frame or
a route is wrong by definition unless it carries a recorded per-item sign-off (the only ones
planned: the Bokeh browser's unguarded non-numeric-column crash, P7h; the additive Reflex
buttons, P7i).

## Explicitly OUT of scope this phase

- **Editing `bokeh_operator.py`.** It is the production UI; `test_standalone_operator.py`'s
  **59** tests must pass with it unedited (Amendment §12's "48" is a stale count — Corrections
  §C2). That constraint outlives P7 and is not a migration target.
- **Rewriting any panel, document, or the Reflex app's construction natively.** P7 hosts the
  existing UI code from the hexagon app layer via compat facades (the settled D1/D2 pattern of
  `makeActionApp`/`makeVisApp`); rendering code is untouched. Native re-implementation is
  post-parity backlog.
- **Moving `palette.py` into the hexagon tree** (Q9, answered below: leave and extend the
  sweep).
- **Changing the orch `_ws_relay` encoding or building a hexagon producer for it.** The orch
  WS stays on legacy relays (recorded in `adapters/native/ws_publish.py:21`); P7b gives that
  encoding its **first wire test** but does not migrate it.
- **Deleting the dead `/ws_globstat` sender** (`orch.py:355` → `orch_status_sync.py:289`).
  No route registration, no consumer *(measured)*; P7b pins its deadness, the spec correction
  records it, deletion is post-parity.
- **Re-pointing the operator ESTOP buttons through `EstopPolicy`.** They fire a single
  orchestrator's `estop_orch` — a scoped stop, not a cascade — and the policy's topology
  derivation requires `estop_roles` tags only Deployment-B's configs carry. Re-pointing would
  change wire behavior for every deployment on a safety path. Recorded deviation, mirror of
  P5 Decision 3; revisit when topology tags exist broadly.
- **The WebGL per-page chart budget refactors** beyond counting and asserting (the hte action
  page already merged per-action figures into segment traces); any new UI element in P7 adds
  traces or buttons, never charts.
- **Unifying `helao_operator.py`'s `.as_dict()` serialization with `RemoteBackend`'s
  `model_dump()`** (`operator/helao_operator.py:70` vs `orch_backend.py`) — 9 callers
  including 7 Deployment-C batch scripts depend on the headless form; P7h pins both, unifies
  neither.

## Sub-project decomposition & dependency order

```
P7a (palette sweep over hexagon) ── Linux, tiny, FIRST (already-mandatory invariant, overdue)
P7b (wire-consumer parity fixtures) ──► P7c (Status port consumer faces)
P7d (UiHost port + aligner fold-in) ──► P7e (Bokeh hosting: generic graft + wiring)
                                    └─► P7f (Reflex hosting seam + preflight lift)
P7g (ControlSurface port + row-15 negative) ─┐
P7h (shared-layer ports — Q8) ───────────────┼─► P7j (rendered-parity lane) ─► P7k (assembly)
P7i (estop / stop_private parity) ───────────┘
```

P7a stands alone and lands first. P7b/P7c, P7d→P7e/P7f, P7g, P7h, P7i are five independent
tracks once P7a is in; P7j needs the hosting slices (e, f) and the buttons (i) to have
something to render-diff; P7k assembles. Every slice's gate is runnable with only its
ancestors landed.

---

### P7a — Palette sweep over `helao/hexagon/` *(Linux; first; discharges an overdue mandate)*

**Measured problem.** Amendment §7 made the glob extension mandatory **effective immediately,
not deferred to P7** — and it has not been done. The sweep's globs are still only
`helao/deploy/*/servers/**/*.py` and `helao/core/servers/**/*.py`
(`helao/core/tests/test_palette.py:1770-1771`); `helao/deploy/hexagon/servers/**` (28 shims)
is already swept, `helao/hexagon/` proper is not. Extending it today yields exactly **2
findings, neither a colour**: `helao/hexagon/adapters/native/gamry_com.py:30` and `:273`,
both the docstring text `PR #205`, matched because `_HEX_RE = r"#[0-9a-fA-F]{3,8}\b"`
(`test_palette.py:1473`) reads `#205` as 3-digit hex and rule 2 (`:1641-1642`) inspects every
string constant including docstrings.

**Decision: fix the two docstrings, not the regex.** The sweeper is calibrated against frozen
fixtures with pinned line numbers (`helao/core/tests/fixtures/sweeper_calibration/`, presence
pinned at `:1718-1723`); a regex change re-calibrates the world to dodge a 2-line prose edit.
*Rejected:* regex tightening (touches calibration); an exemption (the 2-entry pin at
`:1658-1667` must not grow — Amendment §7 is explicit).

**Tasks (TDD order):**
1. `test_palette.py`: extend the glob set with `helao/hexagon/**/*.py`. Run; observe exactly
   the 2 predicted findings — this *is* the failing-test step, and the count doubles as a
   calibration check (a different count means the recon or the glob is wrong; stop and
   re-measure).
2. Reword the two `gamry_com.py` docstrings (`PR #205` → `PR 205`); sweep green.
3. New test `test_palette.py::test_sweep_reaches_hexagon_tree`: assert the collected file set
   includes `helao/hexagon/adapters/vis/galil_aligner_host.py` by path. **Vacuity trap:** an
   empty/mistyped glob passes a "no findings" assertion silently; pinning one known-included
   file makes an inert glob fail loudly.
4. Assert (existing test) the exemption list is still exactly 2 entries; do not touch
   `fixtures/sweeper_calibration/`.

**Gate:** `test_palette.py` green (169 + new); exemption pin unchanged; Amendment §6 gate
item 3 discharged permanently (every later hexagon UI module lands pre-guarded).

---

### P7b — Wire-consumer parity fixtures *(Linux; test-and-harness only, no production code)*

**Measured problem — the gate-item-1 substrate does not exist.** Six WS routes, **two
producer families, different payload types under the same route names**:

| Route | `BaseAPI` family (`base_api.py:679,690,701`, via `WsPublisher.broadcast` → `pyzstd.compress(pickle.dumps(...))`, `helao/helpers/ws_utils.py:64-66`) | `OrchAPI` family (`orch_api.py:183,188,193`, via `Base._ws_relay`, `base_status.py:246-272`) |
|---|---|---|
| `/ws_status` | pickled **`ActionModel` object** (`base_api.py:457,484`) | pickled **dict** (`as_dict()`) |
| `/ws_data` | pickled **`DataPackageModel`** (`active_data_stream.py:140,149`) | pickled **dict** |
| `/ws_live` | dict `{datalab: (value, epoch)}` (`base_live_buffer.py:78,83`) | dict |

`OrchAPI` is a **sibling** of `BaseAPI` (`orch_api.py:109` vs `base_api.py:580`), not a
subclass — the two encodings are independent code. Consumer decoder faces *(measured)*:
(1) transport — `WsSubscriber.subscriber_loop` (`ws_utils.py:135`),
`WsSyncClient.read_messages` (`:95`); (2) Bokeh — **no shared payload decoder**;
`VisSubscriber.IOloop_data` (`vis_subscriber.py:347-364`) hands raw batches to **17 distinct
`add_points` implementations** (hte 12, test 3, Deployment-B 4); (3) Reflex —
`ingest.NORMALIZERS` keyed by `ws_path` (`ingest.py:239`): `normalize` (`:46-142`, non-float
values diverted to `rows` at `:104-109` because the ring buffer is float64-only,
`ringbuffer.py:106`) vs `normalize_data_package` (`:145-234`, non-numeric columns **silently
dropped** at `:204-209` — deliberately different semantics), plus the bypass `WsIngest.raw`
(`ingest.py:307,360`, used by the test deployment's sim panel); (4) the operator's
`ws_status` face — `RemoteBackend._ws_loop` (`orch_backend.py:337-346`) decodes **nothing**
(truthiness only). Hexagon's only WS producer test, `test_ws_publish_bridge.py`, decodes with
`WsSubscriber` alone (`:82,:110`) — **exactly the insufficiency §10.1(3) names, inside the
hexagon tree itself** — and the orch `_ws_relay` encoding has **no wire test at all**.

**Design.** A fixture module `harness/ws_frames.py` (harness/ is the parity-harness home)
that produces canonical **byte frames** per (channel × producer family), generated through
the **real encoders** — `WsPublisher`'s broadcast path and `Base._ws_relay`'s
compress-pickle path — never a hand-rolled copy (§10.1(2), the dd31c36f trap). Payload
content is fixed synthetic model instances (an `ActionModel`, a `DataPackageModel` with one
numeric and one **string** column, a live dict with one float and one string datalab) so the
non-numeric traps are inside every fixture. Consumer tests then drive each real decoder over
each frame it is registered for.

**Tasks:**
1. `harness/ws_frames.py`: `frame(channel, family) -> bytes` + the payload builders.
   Test `helao/hexagon/tests/test_ws_frames.py::test_frames_roundtrip_via_wssubscriber`:
   each frame decodes through the real `WsSubscriber` machinery to the original payload
   type. **Vacuity trap:** asserting only "decodes without error" passes on an empty dict —
   assert payload type *and* one sentinel value per frame.
2. `helao/hexagon/tests/test_ws_consumer_parity.py`:
   - `test_ws_publish_bridge_frames_byte_identical_to_legacy`: for identical inputs, the
     `WsPublishBridge` output frame == the legacy `WsPublisher` frame, byte-compared
     (extends the existing 2-test file past its WsSubscriber-only coverage).
   - `test_orch_relay_encoding_pinned`: first wire test for `_ws_relay` — frame bytes decode
     to `as_dict()` output; pins the dict-not-model family so a future phase can't silently
     converge the two families and blank every remote subscriber.
   - `test_reflex_normalize_per_channel`: `normalize` over the ws_live frame yields the
     float in the buffer and the string in `rows` (`:104-109` semantics pinned);
     `normalize_data_package` over the ws_data frame yields numeric columns and **drops**
     the string column (`:204-209` pinned as intended, with a comment naming it). **Vacuity
     trap:** each normalizer over the *other* channel's frame yields **nothing** — assert
     that emptiness explicitly as the cross-pair test, so "returns empty" can never read as
     a pass in the right-pair tests (those assert non-empty parsed content first).
   - `test_ws_globstat_is_dead`: no route registration for `/ws_globstat` exists on either
     API class; the sender at `orch_status_sync.py:289` has no consumer. Pins Corrections
     §C1b until the spec is amended.
   - `test_operator_ws_face_is_shape_blind`: `_ws_loop` accepts both families' ws_status
     frames indistinguishably — documented so nobody cites the operator as evidence of
     ws_status parity.
3. Per-deployment `add_points` conformance: `helao/deploy/hte/tests/test_vis_ws_parity.py`
   and `helao/deploy/test/tests/test_vis_ws_parity.py`, parametrized over the local vis
   modules (hte 12, test 3), feeding each panel's `add_points` the decoded payload the real
   `VisSubscriber.IOloop_data` would hand it, built from the P7b frames. Assert each panel's
   source/buffer gains rows for the numeric columns and **does not raise** on the string
   column. **Vacuity trap:** a panel whose `add_points` early-returns on an unrecognized
   server key passes anything — each test primes the panel with the config key it answers to
   and asserts the row count strictly increased.

**Private-deployment callout:** Deployment-B's 4 `add_points` implementations get the same
conformance test in its own repo, importing `harness.ws_frames` (a public, generic helper —
the P4 public-port/private-specifics pattern).

**Gate:** all new suites green per-file; the two existing `test_ws_publish_bridge` tests
still green; the floor holds. Amendment §6 gate item 1's substrate now exists; item 1 itself
is discharged when P7e/P7f run these decoders against hexagon-hosted ends (their gates say
so).

---

### P7c — Status port: the third consumer face *(Linux; small; needs P7b)*

**Measured problem.** `ports/status.py` is publish-side only (attach/detach/send/publish
members); Amendment §8 requires the port to enumerate **three consumer faces**, and the
Reflex face is keyed by `ws_path`, not uniform — with a real edge: a module's own `WS_PATH`
wins over its config key (`app.declared_ws_path`, `reflex/app.py:128-149`;
`hte/servers/reflex/nidaqmx_vis.py:28` sits under `live_vis` but reads `ws_data`), and
`IngestRegistry` (`ingest.py:391-412`) maps only `live_vis→ws_live`, `action_vis→ws_data` —
**no Reflex consumer of `ws_status` exists** *(measured)*.

**Design.** Add to `ports/status.py` two vendor-free Protocols: `StatusStreamPort`
(subscribe to a channel on a server, yielding decoded payloads as `object`) and
`ChannelNormalizerPort` (`__call__(payload: object, ws_path: str) -> object`). Ports may
import only domain/ports/`helao_driver` (`test_boundaries.py:78-82`), so all returns are
opaque. Adapters: `adapters/vis/ws_consumer.py` wrapping `WsSubscriber` (legal —
`adapters/` returns before `VENDOR_BANNED` at `test_boundaries.py:144-152`, and it is not
under `adapters/native/`, which additionally bans `helao.core.servers.*` at `:131-143`);
a conformance declaration that `ingest.NORMALIZERS`' two entries satisfy
`ChannelNormalizerPort`. No behavior change anywhere.

**Tasks:**
1. `helao/hexagon/tests/test_status_consumer_faces.py`:
   `test_three_faces_enumerated` (the port module names the three faces; `WsSubscriber`
   adapter and both ingest normalizers pass `isinstance` against the Protocols);
   `test_ws_path_override_edge` (a module with `WS_PATH` set is routed by it, not by its vis
   key — fixture mirrors `nidaqmx_vis.py:28`); `test_registry_has_no_ws_status_consumer`
   (pins the measured absence, so a future ws_status Reflex consumer is a deliberate
   addition with a test change, not drift).
2. Conformance runs over the P7b frames (reuse, don't re-encode).
3. `test_boundaries.py` stays green — the Protocols carry no vendor types. **Vacuity trap:**
   `@runtime_checkable` `isinstance` checks only method *presence* — pair each with one
   behavioral call over a P7b frame.

**Gate:** new file green; boundary test green; floor holds.

---

### P7d — UiHost port + aligner fold-in (D6 generalized) *(Linux)*

**Measured problem.** The generalized D6 rule ("nothing outside the app layer may construct
a UI host", Amendment §6) has no structural teeth: `galil_aligner_host.py:139-145` constructs
`Server(...)` + `.start()` inside an action-server process (port from `bokeh_port` at
`:137`, default `port + 1000`), and nothing stops the next adapter doing the same. The
boundary test's `VENDOR_BANNED` is consulted only for domain/ports (`test_boundaries.py:
153-155`), so `bokeh` imports in adapters are legal — the rule needs its own check.

**Design.** `ports/ui_host.py`: `@runtime_checkable UiHostPort` with two faces —
`start_document_host(build_fn, host, port, ...) -> object` / `stop(handle)` (Bokeh) and
`build_ui_app(config) -> object` (Reflex; consumed by P7f). Implementation
`app/ui_host.py` (`BokehServerUiHost`) — the app layer is the only layer that constructs
`bokeh.server.server.Server`, per master spec §4.5. The aligner adapter keeps building its
*document* (widgets, `HelaoVis` at `:158` — the theme seam) but receives a `UiHostPort`
through its wiring and never touches `Server` again. New boundary rule: importing
`bokeh.server` anywhere in `helao/hexagon/` outside `app/` fails.

**Tasks (TDD order):**
1. `test_boundaries.py`: add the `bokeh.server`-outside-`app/` rule **first** — it must fail
   on `galil_aligner_host.py:139` as written. **Vacuity trap:** a rule that matches nothing
   passes forever — calibrate it mutation-style like the existing walk: a fixture module
   under `tests/` importing `bokeh.server` must be flagged when pointed at directly.
2. `ports/ui_host.py` + `helao/hexagon/tests/test_ui_host_port.py`: Protocol is vendor-free
   (no bokeh/reflex names in annotations); `isinstance` + one behavioral start/stop against
   a fake.
3. `app/ui_host.py` + tests: constructs a real `Server` on an ephemeral port, serves a
   trivial document, stops cleanly; asserts the returned handle is opaque to callers.
4. Refactor `galil_aligner_host.py` to consume the injected port; `PortWiring` gains
   `ui_host` (not added to `ACTION_REQUIRED`/`ORCH_REQUIRED` — `app/wiring.py:38-57` —
   required only when a server declares an aligner or is a UI host; `PortWiring.require`
   at `:77-88` enforces at the sites that need it).
5. `test_galil_aligner_host.py` (14 tests) green with assertions intact — the aligner still
   binds `bokeh_port`-else-`port+1000`, still constructs `HelaoVis` (theme reach unchanged).

**Gate:** boundary rule live and calibrated; 14 aligner tests green; floor holds. The D6
exception noted in master spec §4.4 ("the one exception already in-tree") is closed.

---

### P7e — Bokeh hosting: generic graft + real `makeVisApp` wiring *(Linux; needs P7d)*

**Measured problem.** The three vis/operator shims hardcode hte modules, so Deployment-A/B/C
cannot flip a Bokeh server; and `makeVisApp` attaches no wiring, so a hexagon-hosted Bokeh
process is hexagon in name only. Deployment-A is the extreme case *(measured)*: it has **no
`servers/visualizer/` package at all** — its `action_vis: gamry_vis`, `control_vis`, and all
three `bokeh:` values resolve into hte by launcher / `import_vis_class` fallback
(`vis_subscriber.py:92-102`); its only own Bokeh UI is `layouts/plate_aligner.py` +
`layouts/aligner_host.py`.

**Design.** Mirror the action graft exactly: `helao/deploy/hexagon/servers/visualizer/graft.py`
and `.../operator/graft.py`, each exposing `makeBokehApp(...)` that reads
`CONFIG["servers"][server_key]["legacy_module"]` (fail-loud when absent, same message shape
as `action/graft.py:56-63`) and delegates to `makeVisApp`. A config flips with
`bokeh: graft` + `deployment: hexagon` + `legacy_module: helao.deploy.<dep>.servers.<group>.<mod>`
— the private module path is a **config value**, living only in the private repo (the P4
resolution, verbatim). The three explicit hte shims stay (readability, and 28 shims are
already palette-swept). `makeVisApp` gains real wiring: build a `PortWiring` carrying
config/logging/UiHost (P7d)/status-consumer (P7c) and attach it to the document session
context — **delegating rendering to the legacy `makeBokehApp` unmodified** (the D1/D2
facade discipline; native panel consumption of the wiring is post-parity). Because
`legacy_module` is explicit, the graft *bypasses* the cross-deployment auto-detect — which is
the correct fix for the Deployment-A sleeper: its flip names the hte module it actually runs,
instead of depending on fallback order.

**Preflight:** `_shim_completeness` (`preflight.py:165-189`) already checks
`helao/deploy/hexagon/servers/<group>/<module>.py` exists; extend it to require
`legacy_module:` when the module is `graft` (mirroring the action-side check), for bokeh
groups too.

**Tasks:**
1. `helao/hexagon/tests/test_vis_graft.py`: graft without `legacy_module:` raises with the
   instructive message; graft with it imports and delegates (assert the legacy module's
   `makeBokehApp` was called with the same 4 args — spy on `import_module`). **Vacuity
   trap:** a spy-only test passes with a facade that drops the doc — also run one real
   legacy module (a test-deployment vis) end-to-end into a `Document` and assert roots
   exist.
2. `test_factory.py`: extend the `makeVisApp` tests (`:101-122,295-324`) — wiring object
   present, ports wired, `UnwiredPortError` on a missing required port (fail-loud
   composition, spec §4.5).
3. `test_vis_gate_config.py`: a test-deployment config variant with one `bokeh: graft`
   server preflights and launches; `STATES/loaded_modules_<key>.json` snapshot still written
   (the hot-reload contract, `launch.py:1570-1597`, is bokeh-launcher-side and must be
   unaffected — assert the snapshot lists the *legacy* panel modules, since those are what
   hot-reload must watch).
4. Preflight tests: `graft`-without-`legacy_module` is a finding; the three explicit shims
   still pass.
5. Wire-consumer cross-check: run the P7b Bokeh conformance suite against a hexagon-hosted
   vis process fed by a hexagon action server (`WsPublishBridge` producer) — this is
   Amendment §6 gate item 1's Bokeh half, discharged here.

**Gate:** a full sim group with grafted visualizer + operator launches on Linux; existing
`browser_check_*` scripts pass against it unchanged (they assert the legacy-rendered DOM —
rendering must be identical because the legacy module rendered it); P7b decoders green
against its frames; floor holds. **Rollback:** restore the `bokeh:` module name, delete two
keys — the launchers treat `deployment:` as a plain string with auto-detect fallback
(`fast_launcher.py:102-166`, `bokeh_launcher.py:115-175`), so legacy is byte-identical.

---

### P7f — Reflex hosting seam + preflight D9 lift *(Linux; needs P7d; the hard one)*

**Measured problem.** `reflex:` is the one code key with no routing seam: the launcher
ignores `deployment:` on reflex servers (it stores it into `CONFIG["deployment"]` at
`reflex_launcher.py:547-550` but never resolves a module from it), hardcodes the app import
(`:585`), and spawns the backend from a fixed `APP_DIR` (`:57`) whose entry module is a
one-line import. `preflight.py:170-178` rejects `deployment: hexagon` on reflex servers,
citing D9 — lifting that is P7's first Reflex code change. Rollback is safe today *precisely
because* the launcher ignores the key — so the seam must be added without making the legacy
path conditional on anything new.

**Decision — the mechanism: an env-var-routed entry module, defaulting to legacy.**
1. `build_env` (`reflex_launcher.py:319-344`) additionally sets
   `HELAO_REFLEX_APP_MODULE=helao.hexagon.app.reflex_host` **iff** the server entry declares
   `deployment: hexagon`; otherwise the variable is **not set at all**.
2. `_app/helao_ui/helao_ui.py` becomes a 6-line resolver: import the module named by
   `HELAO_REFLEX_APP_MODULE`, default `helao.core.servers.reflex.app`, and re-export its
   `app`. Absent variable ⇒ byte-identical behavior to today (the whole rollback story).
3. `helao/hexagon/app/reflex_host.py` implements `UiHostPort.build_ui_app` as a compat
   facade: it imports the legacy `helao.core.servers.reflex.app` builder and re-exports its
   `app`, attaching the hexagon wiring object for state access — construction (backend
   FastAPI at `app.py:460`, `make_buffer_router` at `:461`, `rx.App` at `:487-495`, the six
   `add_page` calls, and the `_ensure_panel_states`-before-`add_page` ordering at
   `:368-406`) is **delegated, not reimplemented**. Same facade discipline as P7e.
4. `reflex_launcher.py:585`'s hardcoded snapshot import resolves through the same env logic,
   so `STATES/loaded_modules_<key>.json` reflects what will actually serve (hot-reload
   correctness).
5. Preflight: replace the `:170-178` rejection with — a reflex server with
   `deployment: hexagon` passes iff `helao/hexagon/app/reflex_host.py` exists;
   `reserved_addresses` port+1 handling unchanged (`discovery.py:107-127`). The pinned
   test on the rejection message is rewritten to pin the new acceptance.

*Rejected alternatives:* (a) making the `reflex:` *value* a module path — it is a **bundle
name** consumed by `resolve_bundle`/`build_reflex_bundle.py` (which imports
`APP_NAME`/`APP_DIR` from the launcher so they cannot drift, `build_reflex_bundle.py:36-42`);
overloading it breaks the bundle contract and all 5 tracked configs. (b) A second `_app`
tree for hexagon — forks `rxconfig.py`, the compiled-CSS story, and the bundle install path
(`<repo_root>/.reflex-bundle/helao_ui/`) for zero gain. (c) Routing inside
`helao.core.servers.reflex.app` by reading CONFIG — puts hexagon composition knowledge in
legacy core, inverting the dependency this rewrite exists to remove.

**What it costs at a station — nothing bundle-shaped, by construction.** The baked backend
URL keys on the config's **port** (`HELAO_REFLEX_API_URL`, `build_env:339`), not on the
hosting stack, and the compiled CSS keys on `class_name=` usage — the seam changes neither,
so flipping `deployment: hexagon` on a reflex server requires **no bundle rebuild**. The
rebuild P7 *does* force comes from P7i's new buttons (new utilities), and lands once, in the
P7k runbook. Station cost of the seam itself: one config key, rollback = delete it.

**Tasks:**
1. `test_reflex_launcher.py` additions: `test_app_module_env_set_only_for_hexagon` (legacy
   server entry ⇒ variable absent from `build_env` output; hexagon entry ⇒ set to the fixed
   value); `test_snapshot_import_follows_routing`.
2. New `helao/core/tests/test_reflex_entry_resolver.py`: the `_app` entry module resolver
   returns the legacy `app` object with the env unset, the hexagon host's `app` with it set
   (monkeypatched env, direct import — no spawn needed). **Vacuity trap:** asserting "env
   var is set" proves nothing about the serving process; this test imports through the real
   entry module so the resolution itself is exercised.
3. `helao/hexagon/tests/test_reflex_host.py`: `reflex_host.app` **is** the legacy module's
   `app` object (identity, not equality — the facade must not construct a second `rx.App`);
   panel states are registered before pages (re-assert the `_ensure_panel_states` ordering
   through the facade — the "backend-only never runs `add_page` callables" trap from the
   Reflex work, pinned so the facade can never accidentally defer state creation); wiring
   object attached.
4. Preflight tests: all six reflex-carrying tracked configs still pass; a hexagon-flipped
   variant passes; the D9-rejection test is replaced, not deleted (its replacement pins the
   new behavior).
5. End-to-end (the slice gate): a test-deployment config variant with
   `deployment: hexagon` on its reflex server launches; the existing
   `browser_check_data_browser/operator` scripts pass against it; the P7b Reflex normalizer
   conformance runs against its live `ws_live`/`ws_data` ends — gate item 1's Reflex half.

**Gate:** e2e above green on Linux (dev bundle via `REFLEX_ALLOW_LOCAL_BUILD=1`, staged off
the `noexec` mount per the standing rule); legacy configs byte-identical in behavior
(`test_reflex_config` 32 + `test_reflex_routes_e2e` 15 green); floor holds. **Rollback:**
delete the `deployment:` key — env var never set, entry module takes the default, launcher
path identical to today.

---

### P7g — ControlSurface port over `io_control` **and** `motion_control`, + row-15 negative *(Linux)*

**Measured problem.** Amendment §6 scopes ControlSurface to `io_control` only — but
`motion_control.py` is **831 lines vs io_control's 270**, three routes vs two, both stacks,
and the larger half of the same `control_vis` surface (Q8 correction: it is absent from Q8's
list entirely). The two discovery functions were deliberately aligned
(`discover_do_items(config, groups)` / `discover_axes(config, axis_source)`, Amendment §5.3)
*so that* one port covers both. The five private routes: `get_digital_outs`/`set_digital_out`
(`io_control.py:175,215`), `get_axis_positions`/`move_axis`/`stop_motion`
(`motion_control.py:477,543,581`); shared wrappers use `CALL_TIMEOUT=5, READ_RETRIES=1,
WRITE_RETRIES=2` (`io_control.py:64-66`) and **discard the body on a non-`none` error code**
(`io_control.py:186-192`) — without that, a 404's `{"detail": ...}` renders a phantom
control named "detail" reading ON. Also inherited: the dependent surface with no port —
`NativeGalilMotion.query_axis_position_counts` (`adapters/native/`), whose only consumer is
a legacy-core UI module (Amendment §5.3 item 2). And row 15's harness support **does not
exist**: `harness/treepass.py` has `snapshot` (`:171`) and `diff_member_sets` (`:194`) but
no negative form anywhere; `assert_smoke_tree.py` is all-positive.

**Design.** `ports/control_surface.py`: one `@runtime_checkable ControlSurfacePort` with the
five methods (mirroring the wrappers' signatures — `move_axis(server_key, axis, value:
float, units, mode=None, speed=None)` per `motion_control.py:530-541`, value dispatched
exactly as typed), returning opaque tri-state maps. Contract clauses carried from Amendment
§4.3: **fidelity declared** (measured vs mirror) and **unknown is a third value** — `None`
never renders/serializes/compares as `False`; the `" 0.0000"`-is-truthy trap stays inside the
one tested coercion function. Adapter `adapters/vis/control_surface.py` **delegates to the
existing shared wrappers** (io_control/motion_control) so timeouts, retries, and the
error-body-discard rule are inherited, never reimplemented (it cannot live under
`adapters/native/` — that subtree bans `helao.core.servers.*` imports,
`test_boundaries.py:131-143`). Discovery (`discover_do_items`/`discover_axes`) stays in the
shared modules — pure config parsing, not a port (Q8 answer). The dual-unit axis read
(wrapping `query_axis_position_counts`' consumer path) surfaces through
`get_axis_positions`, which already returns both units on the wire.

**Row-15 negative harness.** `harness/control_negative.py`: `snapshot` the run root
(`treepass.snapshot` with `explode_zips` where needed), drive every ControlSurface method
against a launched sim group, `snapshot` again, assert `diff_member_sets(before, after) ==
[]`. Precondition (the vacuity trap): each call must **succeed** — error code `none` and a
readback observed — before the tree diff counts, because an unlaunched group or a 404 also
leaves the tree unchanged. Server-side substrate *(verified)*: the routes are bare-path
`tags=["private"]` (`galil_io.py:272-291`, comment at `:246-248`; motion equivalents
`galil_motion.py:745,848,885`, `kinesis_server.py:311,375,417`) — they never enter the
action namespace or the queueing middleware, so nothing writes. The Linux target is the test
deployment's control-vis sim config (the only non-hte `control_vis` besides Deployment-A/C
*(measured: test 1/1)*); its sim server gains the three motion routes (additive, sim-only —
the test deployment has no frozen checklist, `preflight.py:129` comment, so this is not a
baseline widening) so the negative gate covers all five routes on Linux.

**Tasks:**
1. `helao/hexagon/tests/test_control_surface_port.py`: Protocol conformance; `None`
   tri-state round-trip (`None` in ⇒ `None` out, never `False`); `" 0.0000"` coercion pinned
   at the single function; error-body-discard pinned (a fake 404 response yields an error,
   never a phantom item).
2. Adapter tests: each method issues exactly the legacy wrapper's wire call (spy on
   `async_private_dispatcher`; assert route name, params incl. `move_axis`'s typed value
   pass-through).
3. Sim motion routes on the test deployment's control server + its tests.
4. `harness/tests/test_control_negative.py`: the harness fails on a mutated tree
   (mutation self-test — drop a file into RUNS_ACTIVE between snapshots and assert the diff
   is reported); the success-precondition fails loudly on a dead server.
5. Smoke: `helao/hexagon/tests/smoke/` gains the live negative run against the sim group —
   all five routes toggled/moved/stopped, tree unchanged, readbacks observed.
6. Existing suites green unchanged: `test_io_control` 17, `test_io_control_vis` 15,
   `test_motion_control` 58, `test_motion_control_vis` 44, `test_reflex_control` 21,
   `test_reflex_motion_control` 65.

**Gate:** the smoke negative green (Amendment §6 gate item 4, discharged — honest note: this
is **net-new harness capability**, not an extension); mutation self-test green; floor holds.
Hardware-backed negative (real Galil/Kinesis) is a one-line addition to each station
runbook's existing canary section (P7k), informational not gating, since the wire and
server code are unchanged by P7.

---

### P7h — Shared-layer ports: the Q8 execution *(Linux)*

**Measured I/O boundaries** (line counts measured): `orch_backend.py` 366 — network (25
private routes at `:205-327` + ws_status + `import_autolibs` fs/import at `:155-166`);
`param_forms.py` 263 — **pure** (process-lifetime cache `:71`); `param_store.py` 140 — fs
read+write (`:38,57,125`); `spec_parser.py` 149 — fs + **arbitrary code execution**
(`spec.loader.exec_module` at `:67`, module cache `:36`); `object_tree.py` 152 — pure;
`data_browser/readers.py` 96 — **fs** (`open()` + `zipfile.ZipFile` `:49-52`);
`sources.py` 386 — **fs walk**; `state.py` 131 — fs transitively (`:112` → `read_dataset`).

**Design (the Q8 answer, executed here; reasoning in the Q8 section below):**
- **Ports:** `ports/operator_backend.py` (Protocol mirroring the 25-method `OrchBackend`
  ABC, `orch_backend.py:25-123`); `ports/param_store.py`; `ports/spec_parser.py`;
  `ports/browser_source.py` (covering **both** fs faces of the browser: readers' dataset
  reads and sources' tree walk); ControlSurface already landed in P7g.
- **Plain shared modules (no port):** `param_forms`, `object_tree`, `data_browser/state`.
- **Nothing moves; everything is mirrored.** The legacy ABC and modules stay where the 1158
  tests and `bokeh_operator.py` (unedited!) find them. Each hexagon port is a structural
  mirror + adapter delegating to the legacy module; a **drift-pin test** asserts the
  Protocol's method-name set equals the legacy ABC/module surface, so the two cannot
  diverge silently during coexistence.
- **The spec_parser port carries the degrade contract**: every method returns
  empty/none on a missing or broken parser, never raises through the port
  (`load_parser` executes a file this repo never sees — a broken parser must disable a tab,
  not take down a page). Q10's gate-side answer lives in P7j.
- **One recorded behavior fix** (the shared-layer discipline slip, measured):
  `is_numeric`/`chart_series` live in `data_browser/app_reflex.py:218,239` (a UI) while the
  Bokeh browser calls `state.build_trace`/`state.downsample` **unguarded** (`app.py:233,236`)
  — a string column crashes the Bokeh browser render where the Reflex one filters. Hoist the
  guards into `data_browser/state.py`; both UIs call through them. Wire-invisible (render
  behavior of a crash path); recorded sign-off in the commit: no consumer can depend on a
  render crash. This is the *data-browser* instance of the "could not convert string to
  float" trap — which Amendment §8(3) mislocates as a WS-channel behavior (Corrections §C6).
- **Serialization seam pinned, not unified:** `helao_operator.py:70` uses `.as_dict()` where
  `RemoteBackend` uses `.model_dump()`; a test pins both shapes so a port adapter can never
  silently switch one (9 callers, 7 of them Deployment-C batch scripts).

**Tasks:**
1. `helao/hexagon/tests/test_operator_backend_port.py`: method-set drift pin against the
   legacy ABC; `RemoteBackend` passes `isinstance`; one behavioral call (`get_orch_state`)
   through the port against a fake transport. **Vacuity trap:** `runtime_checkable` checks
   names only — the behavioral call is mandatory, and the drift pin compares *sets both
   ways* (a method added to the ABC but not the Protocol must fail too).
2. `test_param_store_port.py` / `test_spec_parser_port.py`: fs round-trip through the
   adapter equals the legacy module's bytes (`previous_params.json` written by one, read by
   the other — the cross-UI contract); broken-parser file ⇒ empty result, no raise, error
   logged.
3. `test_browser_source_port.py`: walk + read through the port equals `sources`/`readers`
   output over a fixture run tree (reuse a P0 golden tree fixture — capture-derived, per
   §10.1(1)).
4. The `is_numeric` hoist: failing test first on the Bokeh side
   (`test_data_browser`-adjacent: a dataset with a string column renders traces for numeric
   columns and **does not raise**), then the hoist, then `test_reflex_data_browser` 30 green
   (the Reflex behavior must be unchanged — same filter, new home).
5. Serialization-seam pin test.
6. `test_standalone_operator.py` **59** green with `bokeh_operator.py` unedited (`git diff
   --stat` on that file is empty at slice end — stated in the commit).

**Gate:** all above green; boundary test green (ports vendor-free, no `helao.core.servers`
import under `ports/`); floor holds.

---

### P7i — Estop and `stop_private` parity in the Reflex stack *(Linux-authorable; private-repo work; forces the bundle rebuild)*

**Measured problem** (entry-state summary above; P5 Corrections #3 filed it): a Reflex-only
station presents **no emergency-stop control** and **no way to abort a running potentiostat
measurement**, and nothing flags either — the panels render, they just lack the buttons.

**Design.**
- **Deployment-B station panel (private repo):** add the three buttons the Bokeh panel
  carries, firing `EstopExecutor.fire(UiOrchEstopButton / UiGracefulStopButton /
  UiEstopButton)` — the same three triggers, the same executor, so the wire is the policy's
  by construction. The executor's recorded deviation stands: plain HTTP, **not**
  TransportPort (RPC bypasses the action-queuing middleware the recorder leg traverses), and
  each leg individually try-wrapped — so the panel must surface per-leg failures in the UI
  (a failed leg is otherwise invisible; the P5 lesson: never accept "no error appeared" for
  a safety cascade).
- **`stop_private` stop-measurement buttons** on the Reflex potentiostat panels — hte's
  `gamry_vis` and `biologic_vis` Reflex ports (public tree; Deployment-B's config-selected
  potentiostat panel resolves cross-deployment to hte's, so it gains the button for free —
  the same edge that gives Deployment-C its panels). Wire mirrors the Bokeh buttons exactly:
  bare `stop_private` via the shared private-dispatch wrapper pattern (io_control-style
  timeout/retry constants), `{channel}` param for biologic (`biologic_vis.py:400`'s shape).
  **Not** through ControlSurface — its scope is the five control routes, and widening it to
  measurement-abort conflates a halt surface with an estop-adjacent one; the route name
  distinction is deliberate (`/stop_motion` is *not* `/stop_private` precisely because
  `stop_private` is a taggable estop-cascade role, Amendment §5.3).
- **Colours from `palette.py` only** — semantic danger/warning roles; the sweep (P7a +
  Deployment-B's own repo-wide sweep) enforces.
- **Wire-visible change, recorded:** these are **additive UI controls calling existing
  frozen routes** — no route, payload, or response changes; the frozen checklists are
  untouched. The per-item sign-off in each commit records "additive consumer of an existing
  route, mirror of the Bokeh button at <file:line>".
- **Chart budget unchanged:** buttons, not charts; per-page WebGL counts stay as measured
  (hte action page within the 16-context cap post-merge).

**Tasks:**
1. hte: `helao/deploy/hte/tests/test_reflex_pstat_stop.py` — driving the panel's stop
   handler issues exactly the Bokeh button's wire call (spy on the dispatcher; assert route
   + params match a fixture extracted from the Bokeh implementation, not hand-written).
   **Vacuity trap:** test the *event handler the component binds*, not a helper — assert
   the button component's `on_click` resolves to the tested handler, so an orphaned helper
   can't pass.
2. Deployment-B (private repo, own branch): panel buttons + a dispatch-log equivalence test
   asserting Reflex-button wire == Bokeh-button wire per trigger (reuse P5b's recorded
   dispatch-log fixture pattern); per-leg failure surfaced in panel state and asserted.
3. Bundle: rebuild the dev bundle; `test_reflex_panels` green; the new utilities present in
   compiled CSS (asserted properly in P7j's computed-style lane — grep is banned as a gate).

**Gate:** both repos' suites green; the estop-parity statement flips (policy reachable from
both stacks' station panels); the P5-filed P7 blocker is closed. **Consequence recorded for
P7k:** `class_name=` usage changed ⇒ every reflex-carrying station's runbook requires a
bundle rebuild at rollout (stale bundle = new buttons render unstyled with no error).

---

### P7j — Rendered-parity lane *(Linux; needs P7e/P7f/P7i; net-new, stated honestly)*

**Measured problem.** Amendment §6 gate item 2 is **net-new work, not an extension**: the
three existing browser checks (`helao/core/tests/browser_check_{data_browser,operator,
hte_panels}.py`, 89/122/210 lines) are standalone `__main__` scripts covering only
`/browser`, `/operator`, `/live`, `/action`; **`/`, `/control`, and every Bokeh document are
uncovered**, and **zero computed-style or drawn-content assertions exist anywhere in the
repo** (repo-wide grep for `getComputedStyle`/`toDataURL` hits only prose) — canvas checks
are `.count()` only.

**Design.** A `helao/core/tests/browser_parity/` package of standalone `__main__` scripts
(staying non-pytest is deliberate — they spawn groups and browsers, the class of thing that
hangs collected sessions; `run_tests.py` reporting NOTESTS for them is the standing
convention) plus one runner (`run_browser_parity.py`) that launches a config, runs every
script, and exits non-zero on any failure — so the lane is one command in a gate or runbook.
Coverage matrix: both stacks × {`/`, `/live`, `/action`, `/operator`, `/browser`,
`/control`} for Reflex routes, plus the three Bokeh documents (visualizer, operator via
`standalone_operator`, aligner). Two assertion classes, both firsts for this repo:

- **Computed styles:** per-route canvas tint (`REFLEX_PAGE_TINTS`), table header hues,
  Bokeh semantic-button colors read via `getComputedStyle` through the shadow roots. Per the
  settled OKLCH finding: assert the **contrast achieved on measured pixels** (the palette's
  pinned luminance math) with per-shade-class tolerance — never a hex equality, never a
  source grep. **Every style assertion is paired with a content assertion** (element count
  > 0 first): a blank page has computed styles too — that is the vacuity trap for this
  entire lane.
- **Drawn content:** after driving the sim producers, sample chart canvas pixels
  (`toDataURL`/pixel read) and assert non-blank; count live WebGL contexts per page and
  assert ≤ the page's declared budget. This is the only check that catches both the WebGL
  eviction failure (evicted chart never draws again, nothing logged server-side) and the
  stale-bundle failure (new utilities render unstyled with no error on either side).

**Parity form:** run the identical matrix against the **legacy-hosted** and
**hexagon-hosted** variants of the same config and diff the extracted style/content matrix
(values, not screenshots — screenshots diff on antialiasing). The legacy run is the baseline
(the D9-handoff rule made concrete).

**Q10, implemented (the answer):** a spec parser's absence is a gate failure **iff the gate
config declares `seqspec_parser_path`** — the gate holds the config, so the ambiguity the
instrument faces ("none configured" vs "broken") does not exist for it. Concretely: config
declares the key ⇒ the Specs tab must list ≥1 spec and carry no degraded note; config omits
it ⇒ the "nothing configured" note must be present (asserted positively — its absence with
no parser would mean the degrade path broke). The test deployment's gate config gains a
minimal fixture `SpecParser` (lister + `PARAM_TYPES` + `list_params` + `parser` over one
fixture spec file) so **both branches run on Linux**; hte's 11 declaring configs exercise
the declared branch at stations for free.

**Tasks:**
1. Runner + the six Reflex-route scripts (extending the three existing scripts rather than
   duplicating: they gain the style/content assertions and the two missing routes).
2. Bokeh-document scripts ×3 (visualizer doc, operator doc, aligner doc — the aligner check
   drives P7d's hosted server).
3. The matrix-diff harness (`browser_parity/matrix.py`): serializes extracted values to
   JSON; `diff` of legacy vs hexagon runs must be empty. Mutation self-test: a deliberately
   perturbed tint in a scratch bundle must produce a reported diff (mirrors the P0
   harness-fails-on-perturbation principle).
4. The fixture spec parser + both Q10 branch assertions.
5. WebGL budget assertion per page, with the budget declared per config in the script (hte
   action page: measured count post-merge; fail on exceed *or* on eviction warning in the
   console log).

**Gate:** lane green against the test-deployment config pair (legacy + hexagon variants) for
both stacks — Amendment §6 gate item 2 discharged on Linux; at-station reruns become one
runbook line. Floor holds.

---

### P7k — Assembly: config flips, runbooks, gate roll-up *(Linux + runbook authoring)*

1. **Test-deployment flip.** The golden Reflex dev config **stays legacy** — it is P7j's
   baseline lane and the P0-substrate configs must keep reproducing themselves. A sibling
   hexagon variant config (same ports, `deployment: hexagon` on the bokeh/reflex/operator
   servers, `bokeh: graft` + `legacy_module:` where applicable) is added as the permanent
   hexagon lane. **Recorded deviation from P4f's flip-in-place rule, and why it is safe:**
   P4f rejected parallel configs because two copies of *real station hardware params* must
   be hand-synced; a sim config has no hardware params, and the parity lane structurally
   *requires* both variants to exist. The hte dev Reflex config flips the same way.
2. **Preflight pins:** both variants preflight exit-0, pinned by test (the P4e pattern);
   negative control per P4f's silent-pass trap — preflight the **in-tree** path only, a
   scratch copy passes vacuously (`preflight` infers deployment from the config path).
3. **Runbooks.** Every station runbook for a config carrying a `reflex:` server gains, in
   order: `build_reflex_bundle.py <config>` (P7i changed `class_name=` usage, so this is
   unconditional at P7 rollout, not port-conditional); the rendered check (`run_browser_parity`
   subset) after it; the capture-window rule (`control_surface_idle: true` sign-off,
   Amendment §4.2) for any window that also captures. Affected *(measured)*: 3 hte station
   configs + 1 hte dev; Deployment-C's station config; **Deployment-A's demo config — which
   already declares `"reflex": "helao_ui"`** (`configs/electrode-demo.py:213`), so Amendment
   §10's "Bokeh only for P4, add Reflex later" recommendation is already half-overtaken:
   that config needs a bundle regardless (Corrections §C5). The 12 non-reflex hte
   control-panel stations need only a visualizer restart.
4. **Station flips** of `bokeh:`/`reflex:` servers follow the P3–P6 canary-first runbook
   practice, per-station scheduled, each individually rollback-able. P7k delivers the
   runbooks and the Linux-green everything; it does not consume station windows itself.
5. **Gate roll-up:** the table below (Gate map) is checked off with test names + run IDs
   recorded in the phase-close note.

**Gate:** all five Amendment §6 items show green named tests; every tracked config
preflights; the full UI floor (1158 + P7 additions) green per-file; both plan-repo docs
(this file's status header; the master spec's P7 section if amended) updated.

---

## Q8 / Q9 / Q10 — answered

**Q8 — the shared-layer split, decided from the measured I/O boundaries, with three
corrections to the spec's default.** Ports for what touches network/fs/exec; plain modules
for pure logic — the default's *principle* survives, its *list* does not:

1. **`readers` is NOT pure** — Q8's default lists it beside `param_forms`; measured, it is
   the only fs-touching module of the browser trio (`readers.py:49-52`) and `state.py:112`
   reaches the fs through it. The default is inverted: **readers is the port's substance**,
   and since `sources.py` is a 386-line fs walk, the browser port (`browser_source`) covers
   both fs faces; `state` is the pure caller. (P7h.)
2. **`motion_control` was absent from Q8 entirely** — 831 lines, 3 routes, both stacks, the
   larger half of the `control_vis` surface. Whatever `io_control` becomes, it becomes:
   one ControlSurface port, five methods. (P7g.)
3. **`orch_backend` is already a port in all but name** — a 25-method async ABC with one
   implementation, constructor-injected in both UIs. The hexagon port is a structural
   mirror + drift pin, **not a move**: moving it would edit `bokeh_operator.py` (forbidden)
   and break the 59-test gate. (P7h.)

Final split — **ports:** operator_backend, param_store, spec_parser, browser_source
(readers+sources), control_surface (io+motion). **Plain shared modules:** param_forms,
object_tree, data_browser/state, the two discovery functions. Everything mirrored, nothing
moved, drift-pinned both ways.

**Q9 — `palette.py` stays in `helao/core/servers/`, sweep extended (P7a); the import
direction is now a stated choice.** Measured basis: extending the glob costs two docstring
edits and nothing else; moving the module would break every legacy import during coexistence
*and* invalidate the frozen sweeper-calibration fixtures whose pinned line numbers the tests
depend on. The hexagon tree importing legacy core for colours is legal by construction:
colour lives in `adapters/vis/` and `app/` (both may import `helao.core.servers.*`;
`adapters/native/` may not, `test_boundaries.py:131-143`) and never in domain/ports — which
is enforced, not hoped, because ports' import allow-list (`:78-82`) excludes it. Post-legacy
relocation is a one-line glob + import sweep, deferred until legacy retires.

**Q10 — a spec parser's absence is a gate failure exactly when the gate config declares
`seqspec_parser_path`.** The instrument cannot distinguish "none configured" from "broken";
the gate holds the config, so it can and must. Both branches asserted (declared ⇒ populated
Specs tab; undeclared ⇒ the "nothing configured" note present), both Linux-runnable via a
fixture parser in the test deployment. (P7j.)

## Corrections to the spec and amendment (measured; flagged)

Each item: the claim, the measurement, and whether it needs a **master-spec amendment**
(per §13: gates, locked decisions, contracts) or is **editorial** (factual count/pointer
drift).

- **C1 (AMENDMENT NEEDED — wire contract, §7.4/§7.5 and §4.3.6).** (a) The spec nowhere
  states that the two producer families put **different payload types under the same three
  route names** — `BaseAPI` pickles model objects (`ActionModel`/`DataPackageModel`) where
  `OrchAPI`'s `_ws_relay` pickles `as_dict()` dicts; `OrchAPI` is a sibling, not a subclass
  (`orch_api.py:109` / `base_api.py:580`). This is the single most load-bearing fact for
  gate item 1 and P7b exists because of it. (b) §7.4/§7.5 imply `/ws_globstat` is a live
  channel; **it is dead code** — `orch.py:355` → `orch_status_sync.py:289` sends JSON text
  with no route registration and no consumer *(measured)*. Pinned by P7b; deletion is
  post-parity.
- **C2 (editorial — Amendment §12 and repo CLAUDE.md).** `test_standalone_operator.py` has
  **59** tests, not 48 *(measured today, all green)*. The constraint stands; the count is
  stale.
- **C3 (editorial — master spec §12 P3 note and Amendment §12).** "`bokeh_operator.py` is
  named by 32 configs" is wrong twice: **zero** configs contain that string — they say
  `bokeh: standalone_operator` — and the count is **26 tracked / 35 total** *(measured)*.
- **C4 (editorial — Amendment §10, already corrected in the P5 plan; carried).**
  Deployment-B's Reflex delta is **4 local config-selected panels + 1 helper + 1 package
  `__init__` = 6 files**, plus a 5th config-selected name resolving cross-deployment; not
  "5 config-selected (6 modules)".
- **C5 (editorial — Amendment §10 P4 delta).** Its premise (Deployment-A has no Reflex
  panels) is right; its conclusion is undercut: Deployment-A's demo config **already
  declares `"reflex": "helao_ui"`** (`configs/electrode-demo.py:213`), so that config needs
  a bundle regardless of the "Bokeh only for P4" recommendation. And §10 attributes the
  cross-deployment-panel wrinkle to Deployment-C alone — **Deployment-A has it far more
  severely**: no `servers/visualizer/` package at all; its `action_vis`, `control_vis`, and
  all three `bokeh:` values resolve into hte by launcher/`import_vis_class` fallback
  (`vis_subscriber.py:92-102`). P7e's explicit `legacy_module:` is the structural fix.
- **C6 (editorial — Amendment §8(3), spec §10.1(5)).** The "could not convert string to
  float" trap is a **data-browser** behavior (`test_reflex_data_browser.py:239-252`), not a
  WS-channel one; the WS-side equivalents are different code with different semantics —
  `ingest.normalize`'s float guard diverts to `rows` (`:104-109`) while
  `normalize_data_package` **silently drops** (`:204-209`). P7b pins both; P7h fixes the
  Bokeh browser's unguarded instance.
- **C7 (editorial — repo CLAUDE.md, not the spec).** "`enable_op: true`, `bokeh_port:
  <port>`" as the orchestrator-operator mechanism is stale: `enable_op` is
  **deprecated-and-ignored** (`helao/helpers/config_loader.py:187,195`; declared false in 2
  configs), and `bokeh_port` is a *motion-server* params key read only by the two aligner
  hosts (default `port + 1000`).
- **C8 (compliance note, not a correction).** Amendment §7's palette-glob extension was
  mandated "effective immediately" on 2026-08-04 and had not been done as of this plan's
  authoring; P7a discharges it. Also `params.limit_vis` is read in 3 places
  (`vis_subscriber.py:126`, `reflex/app.py:423`, `control.py:287`) and declared in **zero**
  configs anywhere — dead-key candidate for the post-parity sweep, recorded here so nobody
  "restores" it as a regression.
- **C9 (this plan answers open questions; no amendment needed).** Q8's default list was
  measurably wrong in three places (see Q8 above) — answering an open question with
  corrections is what §14 is for; the answers above are the record.

## Private-deployment work map

All private work happens in the respective repo on its own branch; parent-repo text uses
aliases only.

- **Deployment-A** — *the sleeper; inventory + config work, no panel code.* No visualizer
  package: every Bokeh UI it renders is hte's code via fallback, its only own UI being the
  aligner layouts. P7 items: (1) its demo config already declares `reflex:` → its runbook
  gets the bundle step (P7k); (2) when its Bokeh servers flip, use P7e's `bokeh: graft` +
  explicit `legacy_module:` naming the hte modules — converting the implicit fallback into a
  stated config value; (3) its Advantech IO server is a ControlSurface target by config only
  (routes frozen in P4); (4) its repo-wide palette sweep already covers `layouts/` — keep
  the repo-wide form (P4 delta #3), do not narrow.
- **Deployment-B** — *the safety work.* (1) P7i: three estop buttons on the Reflex station
  panel via `EstopExecutor.fire`, dispatch-log equivalence vs the Bokeh buttons, per-leg
  failure surfaced; (2) P7b: its 4 `add_points` conformance tests over `harness/ws_frames`;
  (3) its cross-deployment potentiostat panel gains hte's `stop_private` button for free
  and its station drill note is updated: if the station ever adds a `reflex:` server, the
  estop drill becomes dual-stack (the Amendment §10 condition, currently unmet — P5
  Corrections #2).
- **Deployment-C** — *runbook + regression only.* No panels of its own (hte's resolve by
  fallback); its station config declares both `control_vis` and `reflex:` → bundle step +
  rendered check in its runbook (P7k); P7h's serialization-seam pin protects its 7 batch
  scripts and the headless-operator callers (`gcld_operator.py:359`, `finish_analysis.py:289`
  are the public-tree analogues).

## Gate map (Amendment §6 → slices; net-new stated honestly)

| # | Gate item | Discharged by | Net-new? |
|---|---|---|---|
| 1 | Wire-consumer parity, every real decoder, both producer families | P7b (substrate) + P7e (Bokeh half, hexagon-hosted ends) + P7f (Reflex half) + P7c (faces formalized) | **Yes** — the existing hexagon wire test decodes with `WsSubscriber` alone; orch `_ws_relay` had no wire test at all |
| 2 | Rendered parity: all routes + Bokeh docs, computed styles + drawn content | P7j (+P7i's buttons asserted there) | **Yes** — 2 routes × 2 stacks + 3 Bokeh docs uncovered today; zero computed-style/pixel assertions exist in the repo |
| 3 | Palette sweep over `helao/hexagon/` green | P7a | Overdue mandate, cheap (2 docstring edits) |
| 4 | Row-15 negative assertion | P7g (`harness/control_negative.py` + smoke, all five control routes) | **Yes** — no negative harness form exists; `assert_smoke_tree` is all-positive |
| 5 | Bundle-rebuild step in every affected runbook | P7k (unconditional at P7 rollout, because P7i changes `class_name=` usage) | Procedural; the *reason* it is unconditional is P7i |

## Risks and rollback

- **Stale bundle — the phase's signature failure mode.** A gate can pass on a development
  machine and fail at a station purely from a stale bundle: the baked backend URL keys on
  the config's port, the compiled CSS on build-time `class_name=` usage, and both failure
  modes are **silent** (blank disconnected page; unstyled new controls). Mitigations: the
  seam itself forces no rebuild (P7f, by construction); P7i does, once, recorded; P7j
  asserts computed styles + drawn pixels, which is the only check that catches it; P7k makes
  the rebuild unconditional in every affected runbook. Build staging respects the `noexec`
  mount rule (stage under `/tmp`, ship `frontend.zip` back).
- **WebGL 16-context cap — a per-page budget, not a per-panel property.** Chrome silently
  and permanently evicts the oldest context past 16; the evicted chart reads healthy on
  every server-side signal. P7 adds buttons, never charts; P7j counts live contexts per page
  against a declared budget and fails on the eviction warning. Any future panel wanting
  "another view" adds a trace, not a chart.
- **Two-process Reflex hosting ambiguity.** The backend is a spawned grandchild running from
  `_app/` — "which code is serving" is answerable only if the loaded-modules snapshot
  reflects the routing; P7f task 4 covers it, and the entry-resolver test pins the actual
  import. Residual risk: an env var stripped by an intermediate shell would silently serve
  legacy under a hexagon-flagged config — the P7j matrix diff (hexagon lane vs legacy lane)
  would show *zero* diff either way, so the e2e gate asserts the hexagon host's marker
  (wiring object present via a debug endpoint on the backend) before trusting the lane.
- **The 59-test / `bokeh_operator.py`-unedited constraint** (P7h). Any slice that finds
  itself wanting to edit that file is out of scope by definition; the mirror-not-move design
  exists to make that structurally unnecessary.
- **Fixture drift between the two producer families.** P7b's frames are generated through
  the real encoders at test time, not frozen bytes — so an encoder change breaks the tests
  (desired) rather than diffing against a stale capture. The one frozen thing is the
  `_ws_relay` family pin, which is the point.
- **Cross-file test interference.** The whole suite runs **per-file** (`run_tests.py`
  convention; the hexagon suite inherits it) — every gate above says "green per-file", and
  the browser lane stays standalone-`__main__` for the same reason.
- **Rollback, per mechanism, all config-only:** Reflex — delete `deployment: hexagon`; the
  env var is never set and the entry module takes the legacy default (byte-identical path).
  Bokeh — restore the `bokeh:` module name and drop `legacy_module:`. Aligner/ports — the
  legacy stack never consumed them; hexagon composition raises loudly if unwired. Both UI
  stacks remain fully present in legacy core in-tree; **P7 deletes nothing.**

## Global constraints (inherited; apply to every slice)

- **P7 moves the hosting, never the wire** (the D9 handoff, above). No wire- or
  render-visible change without a recorded per-item sign-off in the commit message. The two
  planned: the Bokeh browser's string-column crash fix (P7h); the additive Reflex buttons
  (P7i).
- **Frozen checklists are never regenerated to make a diff pass**; P7 plans no re-freeze
  anywhere (the new buttons call existing frozen routes).
- **Run tests per-file with a timeout**, via `conda run -n helao` python — never one
  collected session.
- **black (88) on changed files immediately before every commit**, per repo independently;
  never reformat `helao/core/tests/fixtures/sweeper_calibration/`.
- **Branch per sub-project; no commit or push without authorization.** Parent-repo commits
  and docs use the A/B/C aliases; private repos' own commits may use real names.
- **The regression floor (1158 UI tests) holds at every slice gate.**
- **Fail-loud composition:** any new port a host requires raises `UnwiredPortError` at
  startup; no default fakes.

## Execution note

**Current state, verified 2026-08-05:** nothing in P7 is started. The inputs are in place:
`makeVisApp` + shims + `graft.py` + `preflight` (P2d/P3e), `EstopPolicy` + Deployment-B's
executor (P1/P5), `harness/treepass.py` + `capture.py` (P0), the three browser-check
scripts, the 1158-test floor all green, and the two recon reports this plan is built on.

**First moves:** P7a (hours, discharges the overdue mandate), then P7b and P7d in parallel —
P7b is the substrate half the phase's gates cite, P7d is the structural piece both hosting
slices need. The Reflex seam (P7f) is the phase's long pole and should start as soon as P7d
lands; P7i's private-repo half can proceed any time after P7a (its only coupling is the
palette sweep and the bundle consequence).

**What has no Linux path:** only the per-station rollout windows themselves (bundle rebuild
+ rendered check + optional hardware-backed row-15 negative at each reflex-carrying
station). Every gate item 1–4 is Linux-dischargeable; item 5 is runbook text. That is the
inversion this phase enjoys over P3–P5: its subject renders in a headless browser, so the
station windows verify deployment mechanics, not correctness.
