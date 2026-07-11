# CARDS Refactor — P5 Design Plan: splitting the `Orch` god-class

> Deployment aliasing: this doc lives in the **public** parent repo, so private deployments
> are referred to as **Deployment-A/B/C/D**. Public deployments keep their names (`hte`, `test`).
> The alias key is held privately, out of the repo. No config YAML content is reproduced here.

**Status:** DESIGN PLAN (no code yet). All line references verified on branch
`feat/cards-refactor` (2026-07-11); `helao/core/servers/orch.py` is 2622 lines at HEAD
(the audit's "2545 lines" predates the P1/P3 and e-stop-artifact commits that landed on
this branch). Framework references are read from branch `feat/framework-scaffold`
(`helao/framework/**` — present on disk only as `__pycache__` on this branch; the source
is **not merged** into `unstable` or `feat/cards-refactor`).

---

## 0. Executive summary

`Orch` (`helao/core/servers/orch.py:80-2623`, 80 methods) fuses seven concerns: queue CRUD,
the dispatch state-machine, network subscription/heartbeats, global-status ingestion + WS
broadcast, e-stop policy, queue persistence, and composition-root wiring. The worst single
function is `loop_task_dispatch_action` (`orch.py:1012-1325`, ~313 lines).

**Strategic finding (Section 2):** the framework rewrite already produced the clean
decomposition of this exact orchestrator (pure FSM in `helao/framework/domain/orchestration.py`,
async shell in `app/orch_api.py`, adapters, ports). Re-deriving that decomposition inside
legacy `orch.py` would be double work on code slated for replacement. But the framework is
unmerged, and the hte production migration is **paused with an open blocker** — legacy `Orch`
remains the *only* production orchestrator for an unbounded window, and every hotfix during
that window lands in this file.

**Recommendation: option (b) minimal-seams, framed as (d) a cutover bridge.** Extract only
the three leaf collaborators with narrow interfaces — persistence, network monitors,
status-ingestion/broadcast — using the in-tree `base_api.py` free-function style (attribute
layout untouched, methods become thin delegators), plus a *clarity-only* in-file decomposition
of `loop_task_dispatch_action` into named helpers with pure global-param fold functions
mirroring `framework/domain/expansion.py`. **Explicitly cancel** the full dispatch-FSM
inversion for legacy: that Separation win is realized by adopting the framework, not by
refactoring the same semantics twice. The dispatch-decision golden-master built to verify P5
doubles as the acceptance suite for the eventual hte framework cutover.

P5 is **fully Linux-verifiable** (unlike P4's hardware waves): every gate — unit suite, e2e
OERSIM run-tree diff, dispatch-trace golden master — runs on this box.

---

## 1. Current-architecture map

### 1.1 External consumers (the frozen surface)

Extraction must not move or rename any `Orch` attribute or public method, because consumers
reach directly into the instance:

- `helao/core/servers/orch_api.py` (936 lines) — the FastAPI layer; **117 direct
  `.orch.<attr>` reach-ins** (top: `globalstatusmodel` ×10, `global_params` ×8,
  `setup_and_contain_action` ×8, `seq_model`, `active_experiment`, the three deques, …).
  Also registers bound methods as endpoints/WS handlers (`orch.ws_globstat`,
  `orch.update_status`, `orch.update_nonblocking`, `orch.export_queues`, `orch.import_queues`).
- `helao/core/servers/operator/orch_backend.py` + `bokeh_operator.py` — the operator UI
  backend (already decoupled from Bokeh internals by the earlier operator-queue work); calls
  queue CRUD, `start/stop/skip`, list/get methods.
- `helao/deploy/hte/servers/orchestrator/async_orch2.py` — the only deployment module that
  imports the class; `test` runners use the framework `MicroOrch`, not legacy `Orch`.
- **Private deployments: zero direct `Orch`/`OrchAPI` consumers** (verified by grep across
  all nested repos, 2026-07-11). P5 is parent-repo-only; no nested-repo commits.
- `Base` (superclass) supplies `aiolock`, `put_lbuf`, `write_seq`/`write_exp`, `helaodirs`,
  `ntp_offset`, `orch_key/host/port` — all seams P5 leaves in place.

### 1.2 Concern clusters (method inventory, line refs at HEAD)

| # | Cluster | Methods (orch.py lines) | ~LOC | Coupling notes |
|---|---------|-------------------------|-----:|----------------|
| **A** | **Queue CRUD & composition** | `register_obj_uuid` :250, `register_action_uuid` :269, `track_action_uuid` :273; `_prep_sequence_meta` :1832, `_ensure_run_id` :1845, `_resolve_active_run_id` :1855; `add_sequence` :1862, `add_split_sequences` :1873, `prepend_sequences` :1943; `_rebuild_{sequence,experiment,action}_dq` + `move_/remove_` ×6 :1964-2034; `add_experiment` :2036; `list_*`/`get_*`/`drop_experiment_inds` :2081-2138; `supplement_error_action` :2140, `replace_action` :2169, `append_action` :2202; `clear_{sequences,experiments,actions}` :1817-1830 | ~500 | Pure deque/state ops; heavily reached-into by `orch_api`/operator backend |
| **B** | **Dispatch state-machine** (expansion + run lifecycle) | `wait_for_interrupt` :277; `unpack_sequence` :599, `get_sequence_codehash` :611, `seq_unpacker` :615, `verify_plate_in_params` :629; `loop_task_dispatch_sequence` :661-801 (~140), `loop_task_dispatch_experiment` :803-1010 (~207), **`loop_task_dispatch_action` :1012-1325 (~313)**, `dispatch_loop_task` :1327-1493 (~166); `orch_wait_for_all_actions` :1495; `start` :1512, `start_loop` :1528, `stop_loop` :1575, `skip` :1754, `stop` :1767, `intend_{skip,stop,estop,none}` :1762-1797; `finish_active_sequence` :2224-2281, `finish_active_experiment` :2283-2371, `write_active_{experiment_exp,sequence_seq}` :2373-2385; `start_wait` :2407, `dispatch_wait_task` :2411 | ~1250 | The load-bearing core. Mutates deques, `globalstatusmodel`, `global_params`, `active_*`; acquires `aiolock`; talks to `async_action_dispatcher`, `HelaoSyncer.to_s3`, `PLATE_API`, postprocessors, `move_dir` |
| **C** | **Status ingestion + WS broadcast** | `update_status` :458-576 (~118), `update_nonblocking` :366-437, `clear_nonblocking` :439-456; `ws_globstat` :578-592, `globstat_broadcast_task` :594-597 | ~230 | Holds `aiolock`; mutates `globalstatusmodel`, `nonblocking`, histories; feeds `interrupt_q` + `globstat_q`; can trigger `estop_loop` |
| **D** | **Network subscription & heartbeats** | `subscribe_all` :311-364, `active_action_monitor` :2440-2463, `ping_action_servers` :2465-2513, `action_server_monitor` :2515-2519 | ~160 | Reads `world_cfg["servers"]`; `async_private_dispatcher`/`endpoints_available`; writes `init_success`, `status_summary`; calls `self.stop()` |
| **E** | **E-stop policy & finalization** | `estop_loop` :1543, `estop_actions(switch)` :1579, `estop_finish_active` :1625, `_estop_promote_all` :1699, `_estop_promote` :1706, `clear_estop` :1799, `clear_error` :1810 | ~270 | Recently redesigned (no fabricated artifacts; guarded transitions; co-located child-dir race guard). Production-critical, freshly verified |
| **F** | **Queue persistence** | `export_queues` :2521-2555, `import_queues` :2557-2622; export call sites `dispatch_loop_task` :1481, `shutdown` :2387-2405 | ~120 | Pickle of deques + active/last exp/seq + `globalstatusmodel` + histories to `STATES/queues.pck`; consumed by `--restore` / `restore_queues_on_startup` and hot-reload |
| **G** | **Composition root & task wiring** | `__init__` :97-194, `exception_handler` :196, `myinit` :205-235 | ~140 | Spawns the 4 background tasks + Base tasks; imports exp/seq libs; optional `HelaoSyncer` |

Module-level: `sanitize_sequence_label` :66, `PLATE_API = HTEPlateAPI()` :77 (module-global
service handle used by cluster B's plate verification).

**Worst offenders (Clarity):** `loop_task_dispatch_action` :1012-1325 — one function that
(1) applies loop intent (stop/skip/estop), (2) implements all five `ActionStartCondition`
wait loops, (3) folds `from_global_act_params` in, (4) stamps run_id/submit-order and inits
the action, (5) dispatches under `aiolock` with estop re-check + failure→pause→requeue,
(6) self-registers the result into the global status model (active *and* non-active paths),
(7) validates the returned model, (8) folds `to_global_params` out (list *and* dict forms).
Second worst: `loop_task_dispatch_experiment` :803-1010 (~207 lines, expansion + process-group
bookkeeping + S3 upload + plate gate).

### 1.3 Seams already laid by P1–P4 (what P5 consumes)

- **P1 (`RunDir` + status literals):** `orch.py` imports `RunDir` (:41) and every status
  payload uses `HloStatus.<member>.value` (:677, :693, :863, :879, :1209, :2256, :2267,
  :2301, :2358) — extracted modules inherit zero magic strings.
- **P3 (Domain Integrity):** guarded lifecycle transitions (`guarded_append`/`guarded_replace`
  from `helao.core.models.status_transitions`, used at :1643-1651) mean extracted e-stop/finish
  code cannot silently produce contradictory statuses; the typed-config injection seam
  (`server_api.py:71` `helao_cfg`) and the discriminated sample union reduce what extracted
  modules must know about raw dicts; typed action params + `StopCondition` enum (pilot,
  commit 3dfac0d0) firm up the sim experiments the e2e gate drives.
- **P3 verification artifacts (`.omc/artifacts/p3/`):** `run_e2e.sh` (deterministic
  ORCH+CPSIM+GPSIM OERSIM run), `normalize_runs_tree.py`, `compare_runs.py` (3-part
  byte-invisibility contract), `import_smoke.py`, `corpus_replay.py` — P5's primary gate
  already exists and already exercises clusters B, C, D, F end-to-end.
- **P4 (driver ABC + weaning):** drivers no longer reach through `Base` into orch state, so
  extraction cannot break driver back-references; the PAL call-trace golden-master
  (`helao/deploy/hte/tests/test_pal_golden_master.py`) is the proven template for the
  dispatch-trace harness in §5.3.

---

## 2. The strategic question: is an in-place split of legacy `orch.py` worth doing at all?

The framework rewrite (`helao/framework/`, branch `feat/framework-scaffold`) **already
decomposed this orchestrator**, with the same semantics, into exactly the shape a P5 full
split would target:

| Framework module | Role | Legacy counterpart in `orch.py` |
|---|---|---|
| `domain/orchestration.py` (1533 ln) | **Pure FSM**: `OrchState` dataclass + pure functions `decide_next`, `apply_intent`, `on_status_update`, `dispatch_sequence/experiment`, queue CRUD as pure state transforms | clusters A + B decision logic |
| `domain/commands.py` | Command value objects (`DispatchAction`, `ExpandSequence`, `PersistMeta`, `EstopServers`, `BroadcastGlobalStatus`, `FinishExperiment/Sequence`, `MoveRunDir`) | implicit side effects scattered through B/E |
| `domain/expansion.py` | `unpack_sequence/experiment`, `fold_in_global`, `fold_out_global` (pure) | :599-627, :707-724, :838-854, :1115-1129, :1281-1314 |
| `domain/status.py` | pure global-status aggregation (`actions_idle`, `server_free`, `endpoint_free`, `merge_server_status`) | `GlobalStatusModel` queries in B/C |
| `app/orch_api.py` (1723 ln) | `OrchDriver` async shell driving the FSM through ports (`OrchPorts`: transport/storage/clock/eventsink), heartbeat, `run_dispatch_loop` | clusters B(loop shell) + D + G |
| `adapters/orch_status_subscriber.py` | WS status subscription adapter | cluster D (`subscribe_all`) + C ingestion |
| `models/orchstatus.py` | `OrchStatus`/`LoopStatus`/`LoopIntent` enums | same enums (already shared) |
| `runners/micro_orch.py` | in-process runner over the same FSM | no legacy counterpart (new capability) |

That decomposition is *validated*: the `test` deployment runs on it (`deployment: framework`
launcher path; framework suite ~1705 passing per migration notes), and an hte canary station
has run it. So the honest question is not "how to split `Orch`" but **"who should own the
Separation win — legacy or the framework?"**

### The options

**(a) Full in-place decomposition of legacy `orch.py`** (pure-FSM + command objects + ports,
i.e. re-derive the framework shape inside `helao/core`).
- *For:* maximal CARDS-Separation score on the code that is actually in production.
- *Against:* it is a second implementation of work that already exists one branch over;
  highest-risk change class (control-flow inversion) on the production orchestrator; every
  hour spent here is an hour not spent unblocking the hte framework migration (paused
  2026-07-06, open uvis4 blocker); and when the migration completes, this code is deleted —
  the win is written off. **Double work, twice the review burden, transient payoff.**

**(b) Minimal-seams split** — extract only the 2-3 leaf collaborators (persistence,
status/broadcast, network monitors) + a clarity pass on the worst function; leave the
dispatch state-machine's control flow in place.
- *For:* ~70 % of P5's *practical* value (hotfix blast-radius reduction, testability of the
  restore path and status ingestion, a <100-line dispatch core readable during incidents) at
  ~25 % of the risk and effort; every stage is behavior-preserving and Linux-gated; keeps
  `orch.py` the composition root so nothing external moves.
- *Against:* CARDS-Separation for legacy improves only modestly (orch.py stays ~2.1 k lines;
  the state-machine still owns its side effects). Honest scoring: Separation goes from
  "weak where it counts" to "moderate", not "strong".

**(c) Defer/cancel P5; put the effort into finishing the framework migration.**
- *For:* zero double work; the Separation card is fixed *permanently* by adoption; the hte
  migration is the stated direction and its remaining blockers (uvis4 startup hang, KMOTOR)
  are where scarce attention has the most leverage.
- *Against:* the migration is **gated on live hardware windows and unresolved blockers with
  no committed end date** — pausing P5 means the production orchestrator keeps a 313-line
  dispatch function and an untestable pickle-restore path for the entire window. The recent
  history of this file (e-stop redesign, queue restore, operator queue backport — all
  landed in the last weeks) shows it takes continuous production hotfixes; CARDS explicitly
  warns that weak design + ongoing local edits = erosion. Cancelling P5 concedes erosion in
  the highest-stakes file for an unbounded period.

**(d) Treat the split as a bridge that de-risks the framework cutover.**
- Not a separate scope — a *framing* of (b): choose extraction boundaries and names that
  converge on the framework's (`fold_in_global`/`fold_out_global`, status-subscriber,
  persistence port), and build the dispatch-decision golden-master (§5.3) so that the same
  scripted scenarios that prove P5 behavior-preserving become the **acceptance suite for the
  hte framework orchestrator** (run the trace harness against `OrchDriver` and diff decisions
  against the legacy trace). That converts P5 effort from "refactoring code slated for
  deletion" into "building the equivalence evidence the cutover needs anyway".

### Recommendation

**Adopt (b) executed under (d)'s framing. Explicitly cancel (a) — the full decomposition of
legacy is superseded by framework adoption.** Rationale, ranked:

1. **The production window is unbounded.** hte migration Wave 5 is paused with an open
   blocker; legacy `Orch` is the sole production orchestrator until every hte station cuts
   over. During that window it *will* be hotfixed. Minimal seams are cheap insurance.
2. **Double-work is capped, not eliminated.** Stages S1-S3 extract ~510 lines of *shell*
   code (pickle I/O, HTTP pings, WS plumbing) whose framework counterparts are adapters —
   the extraction is mechanical, not a re-derivation of decision logic. The one place
   framework logic is mirrored (`fold_in/out_global` as pure functions) is ~120 lines and
   directly reduces the worst function.
3. **The golden-master pays twice** (P5 gate now, cutover acceptance later).
4. **P1-P4 already improved this file** (literals, guarded transitions, typed seams); the
   remaining acute pain is concentrated exactly where (b) aims: the untested restore path,
   the intertwined status/broadcast code, and `loop_task_dispatch_action`'s length.

If the human's judgment is that the hte migration will resume and complete within ~1-2
station cycles, drop to S1+S4 only (persistence + clarity pass) — see OQ-1.

---

## 3. Design (for the recommended option)

### 3.1 Extraction style: `base_api.py`-shaped free functions, not collaborator objects

The audit's own reference pattern (`base_api.py` — "decomposed into small free functions
instead of a fat class") is the right shape here, for three verified reasons:

1. **State is shared, not partitionable.** `aiolock`, `interrupt_q`, `globstat_q`,
   `globalstatusmodel`, `nonblocking`, the three deques, and `active_*` are each touched by
   2+ clusters (e.g. `nonblocking` by C's `update_nonblocking` *and* B's
   `finish_active_experiment`; `aiolock` by C's `update_status` *and* B's dispatch). A
   collaborator object owning any of them would force either back-references (a new god-knot)
   or a state-object migration — which is precisely the framework's `OrchState`, i.e. option (a).
2. **117 external attribute reach-ins** (§1.1) freeze the attribute layout. Free functions
   taking `orch` as the first argument leave every attribute where consumers expect it.
3. **Pickle safety.** `export_queues` pickles live model instances (`GlobalStatusModel`,
   `Sequence`/`Experiment`/`Action`, `DequeDict` contents). Moving *functions* is
   pickle-invisible; moving *classes or attributes* is not.

Shape per extracted module (delegators keep bound-method identity for endpoint/WS
registration and `asyncio.create_task(self.<method>)` wiring in `myinit`):

```python
# helao/core/servers/orch_persist.py  (new)
"""Queue persistence for the legacy orchestrator (pickle export/import)."""
def export_queues(orch, timestamp_pck: bool = False) -> str: ...   # body moved verbatim
def import_queues(orch, pck_path: Optional[str] = None) -> str: ...

# orch.py — Orch keeps thin delegators (public surface unchanged)
def export_queues(self, timestamp_pck: bool = False) -> str:
    return orch_persist.export_queues(self, timestamp_pck=timestamp_pck)
```

### 3.2 Target modules (SRP), scope IN

| New module (under `helao/core/servers/`) | Moves (from §1.2) | Framework counterpart (naming convergence) |
|---|---|---|
| `orch_persist.py` | cluster F: `export_queues`, `import_queues` | `ports/storage.py` + `PersistMeta` command |
| `orch_monitor.py` | cluster D: `subscribe_all`, `ping_action_servers`, `active_action_monitor`, `action_server_monitor` | `adapters/orch_status_subscriber.py` + `OrchDriver._heartbeat_*`; reuse `domain/orchestration.pingable_servers`/`parse_status_response` shapes |
| `orch_status_sync.py` | cluster C: `update_status`, `update_nonblocking`, `clear_nonblocking`, `ws_globstat`, `globstat_broadcast_task` | `on_status_update`/`on_nonblocking` + `BroadcastGlobalStatus` |
| `orch_global_params.py` | **new pure functions** `fold_in_global(params, from_global_map, global_params, *, logger_ctx)` and `fold_out_global(result_action, global_params)` extracted from the three duplicated fold blocks (:707-724 seq, :838-854 exp, :1115-1129 act) and the fold-out block (:1281-1314) | `domain/expansion.fold_in_global` / `fold_out_global` (same names, same split) |

Plus **in-file** clarity decomposition (no new module — these helpers mutate too much shared
state to be honest free functions):

`loop_task_dispatch_action` (:1012-1325) becomes an ~40-line coordinator calling private
methods, cut on the seams the function already exhibits:

| New private method | Current lines | Behavior |
|---|---|---|
| `_apply_loop_intent_before_dispatch()` | :1030-1051 | stop/skip/estop intent handling; returns "handled" sentinel |
| `_wait_for_start_condition(A)` | :1058-1111 | the five `ActionStartCondition` wait loops (each an inner `while` over `wait_for_interrupt`) |
| `_stage_action_for_dispatch(A)` | :1115-1157 | fold-in (via `orch_global_params`), run_id, submit-order counters, `init_act` |
| `_dispatch_action_locked(A)` | :1159-1261 | the `aiolock` block: estop re-check, `async_action_dispatcher`, failure→pause→requeue, self-registration into `globalstatusmodel` (active + non-active branches) |
| `_record_dispatch_result(A, result_actiondict)` | :1263-1314 | model validation, error→`estop_loop`, fold-out (via `orch_global_params`) |

Same pass, same PR, `loop_task_dispatch_experiment` (:803-1010) gets the identical
treatment (`_stage_experiment`, `_expand_experiment_actions` (:906-971), `_upload_exp_meta_s3`
(:979-991), plate-gate helper shared with the sequence path).

### 3.3 Scope OUT (explicit non-goals, with reasons)

- **No FSM inversion.** `dispatch_loop_task`'s control flow, the deques-as-state, and the
  interrupt-queue protocol stay exactly as they are. That redesign exists and is tested —
  in the framework. (Cancels the master plan's implied "dispatch state-machine last" stage:
  the state-machine is *never* extracted from legacy.)
- **No queue-CRUD extraction (cluster A).** It is already the most cohesive cluster, is the
  operator backend's primary touch surface, and moving it buys no incident-time clarity.
- **No e-stop extraction (cluster E).** `estop_finish_active`/`_estop_promote*` were
  redesigned and production-verified within the last month (guarded transitions, child-dir
  race guard). Churning freshly-stabilized safety code for layout points is a bad trade.
  `estop_actions(switch: bool)` flag-arg cleanup (audit Clarity finding) is deferred with it.
- **No `Active._finish` decomposition** (`base.py`, ~221 lines — mentioned in the master
  plan's P5 sketch). Different file, different blast radius (every action server, not just
  orchestrators); decide separately (OQ-4).
- **No behavior fixes.** Known quirks ride along unchanged (e.g. `dispatch_loop_task:1467`
  compares `loop_state != OrchStatus.estopped` — a `LoopStatus` field against an
  `OrchStatus` member; it happens to behave correctly only because both are `str` enums with
  the value `"estopped"`. Normalizing it to `LoopStatus.estopped` is a P5b/one-line follow-up,
  not part of a behavior-preserving pass. Log it, don't fix it).

### 3.4 Dependency-injection posture

Injection stays at the `Base`/config seams P3 built (`helao_cfg`, `server_params`); the
extracted free functions receive everything through the `orch` argument. This is deliberate:
introducing constructor-injected collaborator objects into `Orch.__init__` would change
pickle/`vars()` surface and add a second wiring pattern to a class the framework will retire.
`orch.py` remains the composition root; `myinit` (:205-235) still owns all task spawning.

---

## 4. Staging (ordered, each stage independently bootable + committable)

Risk order: pure-addition first, persistence (cold path) next, monitors (background, idle-safe)
next, status ingestion (hot path) next, dispatch clarity pass (hottest) last.

| Stage | Content | Why this order | Boot-safety argument |
|---|---|---|---|
| **S0** | Baseline capture: unit suite, ×2 e2e OERSIM runs (`run_e2e.sh baseline`, `baseline2` — establishes the noise floor), dispatch-trace golden master recorded (§5.3), `import_smoke.py` snapshot, export/import round-trip fixture (`queues.pck` produced by current code, checked into `.omc/artifacts/p5/`) | Evidence before edits (P4 D7 discipline) | no code change |
| **S1** | `orch_global_params.py` (pure functions) + swap the four fold blocks to call them. Smallest semantic surface; de-duplicates 3 copies of the fold-in block | Pure, unit-testable, no async/lock involvement | fold behavior byte-equal (unit: identical dict mutations incl. list-vs-dict `to_global_params` forms and the `_fast_samples_in` exclusion is *not* part of fold — verify untouched) |
| **S2** | `orch_persist.py` (cluster F) + delegators; add the round-trip unit test (export→import on a fake orch; **cross-version test**: S0's pickled fixture imports cleanly post-move) | Cold path — runs only at shutdown/loop-drain/`--restore`; failure mode is visible, not silent | delegator preserves `orch.export_queues` endpoint binding in `orch_api` and the `dispatch_loop_task:1481` / `shutdown:2402` call sites |
| **S3** | `orch_monitor.py` (cluster D) + delegators | Background tasks; read-mostly; worst failure = missed heartbeat (self-healing next tick) | `myinit` still does `asyncio.create_task(self.subscribe_all())` etc. via delegators; `init_success`/`status_summary` attribute writes unchanged |
| **S4** | `orch_status_sync.py` (cluster C) + delegators | Hot path but *ingress-only*: mutates `globalstatusmodel` under the same `aiolock`, pushes to the same queues. Extraction is verbatim-move; the lock acquisition stays inside the moved body so lock ordering vs. `_dispatch_action_locked` is untouched | `orch.update_status` / `orch.update_nonblocking` / `orch.ws_globstat` remain bound methods (orch_api registers them); WS clients unaffected |
| **S5** | In-file decomposition of `loop_task_dispatch_action` → 5 helpers (§3.2), then `loop_task_dispatch_experiment` → 4 helpers | Hottest code, so it goes last with all gates warmed up; no cross-module move at all — pure intra-class extract-method | Coordinator preserves the exact early-return/requeue/lock structure; dispatch-trace golden master (§5.3) must be byte-identical before/after |
| **S6** | Sweep: docstrings/module headers, grep gates (§5.5), line-count report, CARDS re-score note in `CARDS_AUDIT.md` appendix | — | no logic |

Per-stage cadence (CARDS convention): implement → gates green → **one commit per stage** →
Opus review pass → push. No stage starts until the previous stage's review lands. Stages
S1-S4 are individually revertable in isolation; S5 reverts as one commit.

Estimated end state: `orch.py` ≈ 2100 lines / dispatch core function ≤ ~60 lines each;
~510 lines relocated into 4 focused modules with unit tests; zero interface changes.

---

## 5. Verification (P5 is fully Linux-verifiable — the contrast with P4)

P4's production wave had to settle for construction-proofs (`constr`) because its subjects
were Windows/hardware drivers. **P5's subject is pure core code exercised end-to-end by the
`test` deployment sims on this box** — every gate below actually runs the refactored code's
full behavior, not just its importability.

### 5.1 Gate 1 — unit suite (every stage)

`conda run -n helao python run_unit_tests.py` (the launch-blocking gate) plus the standalone
`helao/core/tests/unit_test_*.py` scripts that touch orch behavior (`unit_test_estop_sync.py`,
`unit_test_micro_orch.py`, operator/standalone tests). New unit tests added by P5:
`orch_global_params` fold semantics (S1), persistence round-trip + cross-version pck (S2),
monitor response-parsing (S3, reusing canned `get_status` payload shapes).

### 5.2 Gate 2 — e2e sim byte-invisibility (stages S1, S2, S4, S5; cheap enough to run always)

The P3 harness, unchanged:

```bash
.omc/artifacts/p3/run_e2e.sh p5s<N>        # ORCH+CPSIM+GPSIM, OERSIM enqueue, drain, normalize
conda run -n helao python .omc/artifacts/p3/compare_runs.py baseline p5s<N>
```

Pass = the 3-part contract (identical file manifest; identical normalized non-`.hlo` text —
i.e. every `-act/-exp/-seq.yml`; identical `.hlo` headers + per-key value multisets). This
single gate exercises: subscribe_all, status ingestion, the full dispatch loop across all
three queue levels, global-param fold in/out (OERSIM uses `to_global_params`), finish/move
lifecycle, and WS broadcast — i.e. every cluster P5 touches. Additionally for S2: a
`--restore`-path variant (enqueue → export mid-queue → restart ORCH with
`restore_queues_on_startup` → drain → same diff), which the current harness doesn't cover
and P5 adds as `run_e2e_restore.sh` under `.omc/artifacts/p5/`.

### 5.3 Gate 3 — dispatch-decision golden master (S0 records; S5 must match; the (d) bridge artifact)

Template: the PAL call-trace harness (`helao/deploy/hte/tests/test_pal_golden_master.py` —
`__new__` bypass + fakes + pinned time + recorded ordered trace). P5 analog, new file
`helao/core/tests/test_orch_dispatch_golden_master.py`:

- **Real (unmodified):** `dispatch_loop_task`, `loop_task_dispatch_{sequence,experiment,action}`,
  `wait_for_interrupt`, intent methods, fold logic, `GlobalStatusModel`.
- **Faked:** `async_action_dispatcher` (records `(server, action_name, ordered params,
  start_condition, submit_order)` and returns a canned active/finished action dict per
  scenario script); `async_private_dispatcher` (no-op); `HelaoSyncer.to_s3`; `PLATE_API`
  (`has_access=False`); `write_seq/write_exp/put_lbuf/move_dir` (recording no-ops);
  `Base.__init__` bypassed via `Orch.__new__` + minimal attribute fixture.
- **Scenario matrix (scripted status updates pushed into `interrupt_q`):** (1) plain
  2-experiment sequence, all `no_wait`; (2) every `ActionStartCondition` member incl. the
  unsupported-value fallback; (3) `to_global_params` list-form and dict-form → next action's
  fold-in; (4) `LoopIntent.stop` mid-experiment (pending-action requeue via
  `wait_for_interrupt`); (5) `LoopIntent.skip`; (6) dispatch failure (`error_code != none`)
  → pause + front-requeue; (7) returned-action `error_code` → `estop_loop` path (faked
  `estop_actions`); (8) nonblocking action lifecycle; (9) step-thru flags.
- **Gate:** the ordered decision trace (JSON lines) is byte-identical pre/post each stage.
- **Bridge reuse:** the same scenario scripts, replayed against the framework `OrchDriver`
  (on its branch), produce the legacy-vs-framework decision diff that the hte cutover needs.

### 5.4 Gate 4 — import smoke & construction

`conda run -n helao python .omc/artifacts/p3/import_smoke.py` +
`python -c "import helao.core.servers.orch, helao.core.servers.orch_api, <new modules>"`.

### 5.5 Grep gates (S6)

- No method bodies left behind: moved functions exist exactly once
  (`grep -c "def update_status" orch.py orch_status_sync.py` → delegator + one body).
- No new cross-imports from extracted modules back into `orch.py` (import-cycle guard:
  extracted modules import models/helpers only, never `helao.core.servers.orch`).
- The four fold blocks are gone from `orch.py` (`grep -n "from_global_.*_params.items()" `
  → only `orch_global_params.py`).

---

## 6. Risk + rollback (highest-risk phase; production orchestrator)

| Risk | Exposure | Mitigation |
|---|---|---|
| **Pickle/restore breakage** (`queues.pck` written by old code, read by new) | Operators rely on `--restore` after crashes/hot-reload | No classes or attributes move (free functions only); S0 checked-in pck fixture + S2 cross-version import test; e2e restore-path variant (§5.2) |
| **Bound-method identity loss** (endpoints/WS handlers/`create_task` registered from `self.<method>`) | `orch_api.py` registers `orch.ws_globstat`, `orch.update_status`, …; `myinit` spawns 4 tasks | Delegator methods retained for every moved callable — the class API is unchanged by construction; import smoke + e2e catch a missed one immediately (server won't wire) |
| **Lock/queue reordering** (`aiolock` held by both `update_status` and `_dispatch_action_locked`; `interrupt_q` written by C/D/E, read by B) | Deadlock or missed-interrupt = stuck production run | Verbatim-move rule: `async with self.aiolock` stays *inside* moved bodies; no await added/removed; golden-master scenario (4) specifically covers the interrupt handshake |
| **Silent behavior drift in the S5 extract-method pass** (early returns, `return ErrorCodes.none` vs error propagation, requeue ordering) | Wrong action ordering / lost requeue on a live station | S5 is intra-class only; golden-master byte-equality is the hard gate; Opus review of the S5 diff specifically checks return-path equivalence |
| **Hot-reload interaction** (watcher restarts idle servers whose loaded modules changed) | New modules must appear in `/loaded_modules` | They do automatically (import-graph-based); noted for the reviewer, no action |
| **Merge-window exposure** | hte stations run their deployed branch, not `feat/cards-refactor`; exposure begins at merge to `unstable` + station update | Merge P5 only as a whole (S1-S6 complete); first station update on a maintenance window with `--restore` smoke + one supervised sequence, per P4 wave discipline |
| **Mid-flight hotfix collision** (`orch.py` is the highest-churn file) | Rebase conflicts with production fixes on `unstable` | Rebase `feat/cards-refactor` before each stage lands; delegator-style moves rebase cleanly (small orch.py diffs); if a hotfix touches a cluster mid-extraction, that stage restarts from the rebased file |

**Rollback:** one commit per stage; S1-S4 revert independently (`git revert <sha>` — each
stage's delegators + module are self-contained); S5 reverts as one commit; no nested-repo
commits exist in P5 at all, so rollback is single-repo. Pre-merge, branch reset remains
available. Post-merge worst case: revert the merge commit — no data-format, wire-format, or
config change exists anywhere in P5, so reverted code is immediately compatible with
anything P5-era servers wrote (including `queues.pck`, by the no-moved-classes rule).

---

## 7. Open questions (for the human; append to `.omc/plans/open-questions.md`)

- **OQ-1 (scope vs. migration timeline — the decisive one):** Does the hte framework
  migration have a credible resume-and-finish horizon (uvis4 blocker + KMOTOR)? If yes
  (≤ ~2 station cycles), shrink P5 to **S0+S1+S2+S5** (pure functions, persistence, clarity
  pass — the pieces that pay off even in a short window) and skip S3/S4. If open-ended,
  execute the full S0-S6 as planned. Recommended default: full S0-S6.
- **OQ-2 (naming convergence):** Extracted modules use legacy-idiomatic names
  (`orch_persist`, `orch_monitor`, `orch_status_sync`) with framework-converged *function*
  names (`fold_in_global`, `fold_out_global`). Alternative: mirror framework module names
  outright to make side-by-side diffing trivial. Recommended: as planned (module names must
  not suggest the framework's port/adapter semantics that legacy doesn't have).
- **OQ-3 (restore compatibility contract):** Is cross-version restore (pck written before
  P5, imported after — and the reverse, after a rollback) a *hard requirement* or
  best-effort? The design preserves it by construction; a "hard requirement" answer adds the
  reverse-direction test to S2. Recommended: hard requirement (hot-reload restarts
  orchestrators with `--restore` unconditionally).
- **OQ-4 (`Active._finish`):** The master plan's P5 sketch mentions decomposing
  `Active._finish` (~221 lines, `base.py`). It touches every action server, not just
  orchestrators — different blast radius, different golden master. In P5 (as an S5-style
  in-file clarity pass with the e2e gate) or deferred to a P5b? Recommended: defer to P5b,
  decided after S5's golden-master experience.
- **OQ-5 (dead consumers check before S6):** `orch_api.py:883` defines a second `WaitExec`
  and `:929` a `checkcond` enum near-duplicating framework shapes; and `endpoint_queues_init`
  (orch.py:237-248) is commented-out dead code. Delete dead code in S6, or freeze? Recommended:
  delete the commented block only (zero-risk); leave `orch_api` untouched (out of P5 scope).
