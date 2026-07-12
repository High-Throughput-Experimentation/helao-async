# CARDS Refactor — P5 Design Plan: splitting the `Orch` god-class

> Deployment aliasing: this doc lives in the **public** parent repo, so private deployments
> are referred to as **Deployment-A/B/C/D**. Public deployments keep their names (`hte`, `test`).
> The alias key is held privately, out of the repo. No config YAML content is reproduced here.

**Status:** DESIGN PLAN (no code yet). All line references verified on branch
`feat/cards-refactor` (2026-07-11); `helao/core/servers/orch.py` is 2622 lines at HEAD
(the audit's "2545 lines" predates the P1/P3 and e-stop-artifact commits that landed on
this branch).

**Decision (2026-07-11, user):** execute the **full in-place decomposition (option a)**,
including inversion of the dispatch state-machine into a dedicated collaborator. Legacy
`helao/core` / `helao/deploy` is the **permanent** target of the CARDS program; CARDS
improves this code in place, full stop. All scoping in this plan follows from that single
premise.

---

## 0. Executive summary

`Orch` (`helao/core/servers/orch.py:80-2623`, 80 methods) fuses seven concerns: queue CRUD,
the dispatch state-machine, network subscription/heartbeats, global-status ingestion + WS
broadcast, e-stop policy, queue persistence, and composition-root wiring. The worst single
function is `loop_task_dispatch_action` (`orch.py:1012-1325`, ~313 lines).

**Plan:** decompose all extractable concerns into cohesive collaborators under
`helao/core/servers/` — `RunQueues` (queue CRUD), `QueuePersister` (pickle export/import),
`ServerMonitor` (subscription + heartbeats), `StatusIngester` (status ingestion + WS
broadcast), pure global-param fold functions, `unpack`/expansion helpers, `RunLifecycle`
(sequence/experiment close-out), and — the centerpiece and highest-risk stage —
`DispatchPolicy` + `DispatchRunner`, a proper state-machine inversion of
`dispatch_loop_task` / `loop_task_dispatch_{sequence,experiment,action}`. E-stop (cluster E)
stays in `orch.py` for P5 (freshly redesigned + production-verified safety code; see §3.5).
`Orch` becomes a thin composition root: it constructs the collaborators, keeps every state
attribute at its current name, and keeps every public method as a thin delegator, so the
frozen external surface (§1.1) and pickle compatibility (§3.3) are preserved by construction.

Staging is strictly risk-ordered (S0 baseline → pure functions → persistence → monitors →
status sync → queue CRUD → unpack/lifecycle → in-file dispatch decomposition → FSM inversion
→ sweep), one commit + Opus review per stage, each stage bootable and independently
revertable.

P5 is **fully Linux-verifiable** (unlike P4's hardware waves): every gate — unit suite, e2e
OERSIM run-tree byte-invisibility diff (plus a `--restore` queues.pck variant), and a
dispatch-decision golden master — runs on this box. The golden master is a pure
**behavior-preservation gate**: the recorded decision trace must be byte-identical before
and after every stage.

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
  imports the class.
- **Private deployments: zero direct `Orch`/`OrchAPI` consumers** (verified by grep across
  all nested repos, 2026-07-11). P5 is parent-repo-only; no nested-repo commits.
- `Base` (superclass) supplies `aiolock`, `put_lbuf`, `write_seq`/`write_exp`, `helaodirs`,
  `ntp_offset`, `orch_key/host/port` — all seams P5 leaves in place.

### 1.2 Concern clusters (method inventory, line refs at HEAD)

The final column maps each cluster to its target collaborator from §3.2.

| # | Cluster | Methods (orch.py lines) | ~LOC | Coupling notes | Target (§3.2) |
|---|---------|-------------------------|-----:|----------------|---------------|
| **A** | **Queue CRUD & composition** | `register_obj_uuid` :250, `register_action_uuid` :269, `track_action_uuid` :273; `_prep_sequence_meta` :1832, `_ensure_run_id` :1845, `_resolve_active_run_id` :1855; `add_sequence` :1862, `add_split_sequences` :1873, `prepend_sequences` :1943; `_rebuild_{sequence,experiment,action}_dq` + `move_/remove_` ×6 :1964-2034; `add_experiment` :2036; `list_*`/`get_*`/`drop_experiment_inds` :2081-2138; `supplement_error_action` :2140, `replace_action` :2169, `append_action` :2202; `clear_{sequences,experiments,actions}` :1817-1830 | ~500 | Pure deque/state ops; heavily reached-into by `orch_api`/operator backend | `RunQueues` (`orch_queues.py`) — S5 |
| **B** | **Dispatch state-machine** (expansion + run lifecycle) | `wait_for_interrupt` :277; `unpack_sequence` :599, `get_sequence_codehash` :611, `seq_unpacker` :615, `verify_plate_in_params` :629; `loop_task_dispatch_sequence` :661-801 (~140), `loop_task_dispatch_experiment` :803-1010 (~207), **`loop_task_dispatch_action` :1012-1325 (~313)**, `dispatch_loop_task` :1327-1493 (~166); `orch_wait_for_all_actions` :1495; `start` :1512, `start_loop` :1528, `stop_loop` :1575, `skip` :1754, `stop` :1767, `intend_{skip,stop,estop,none}` :1762-1797; `finish_active_sequence` :2224-2281, `finish_active_experiment` :2283-2371, `write_active_{experiment_exp,sequence_seq}` :2373-2385; `start_wait` :2407, `dispatch_wait_task` :2411 | ~1250 | The load-bearing core. Mutates deques, `globalstatusmodel`, `global_params`, `active_*`; acquires `aiolock`; talks to `async_action_dispatcher`, `HelaoSyncer.to_s3`, `PLATE_API`, postprocessors, `move_dir` | split four ways: fold functions (`orch_global_params.py`, S1), unpack helpers (`orch_unpack.py`, S6), `RunLifecycle` (`orch_lifecycle.py`, S6), `DispatchPolicy`+`DispatchRunner` (`orch_dispatch.py`, S7-S8) |
| **C** | **Status ingestion + WS broadcast** | `update_status` :458-576 (~118), `update_nonblocking` :366-437, `clear_nonblocking` :439-456; `ws_globstat` :578-592, `globstat_broadcast_task` :594-597 | ~230 | Holds `aiolock`; mutates `globalstatusmodel`, `nonblocking`, histories; feeds `interrupt_q` + `globstat_q`; can trigger `estop_loop` | `StatusIngester` (`orch_status_sync.py`) — S4 |
| **D** | **Network subscription & heartbeats** | `subscribe_all` :311-364, `active_action_monitor` :2440-2463, `ping_action_servers` :2465-2513, `action_server_monitor` :2515-2519 | ~160 | Reads `world_cfg["servers"]`; `async_private_dispatcher`/`endpoints_available`; writes `init_success`, `status_summary`; calls `self.stop()` | `ServerMonitor` (`orch_monitor.py`) — S3 |
| **E** | **E-stop policy & finalization** | `estop_loop` :1543, `estop_actions(switch)` :1579, `estop_finish_active` :1625, `_estop_promote_all` :1699, `_estop_promote` :1706, `clear_estop` :1799, `clear_error` :1810 | ~270 | Recently redesigned (no fabricated artifacts; guarded transitions; co-located child-dir race guard). Production-critical, freshly verified | stays in `orch.py` (P5); P5b candidate (§3.5, OQ-7) |
| **F** | **Queue persistence** | `export_queues` :2521-2555, `import_queues` :2557-2622; export call sites `dispatch_loop_task` :1481, `shutdown` :2387-2405 | ~120 | Pickle of deques + active/last exp/seq + `globalstatusmodel` + histories to `STATES/queues.pck`; consumed by `--restore` / `restore_queues_on_startup` and hot-reload | `QueuePersister` (`orch_persist.py`) — S2 |
| **G** | **Composition root & task wiring** | `__init__` :97-194, `exception_handler` :196, `myinit` :205-235 | ~140 | Spawns the 4 background tasks + Base tasks; imports exp/seq libs; optional `HelaoSyncer` | stays in `orch.py` — becomes the *only* substantive content besides E |

Module-level: `sanitize_sequence_label` :66, `PLATE_API = HTEPlateAPI()` :77 (module-global
service handle used by cluster B's plate verification — relocation rule in §3.4).

**Worst offenders (Clarity):** `loop_task_dispatch_action` :1012-1325 — one function that
(1) applies loop intent (stop/skip/estop), (2) implements all five `ActionStartCondition`
wait loops, (3) folds `from_global_act_params` in, (4) stamps run_id/submit-order and inits
the action, (5) dispatches under `aiolock` with estop re-check + failure→pause→requeue,
(6) self-registers the result into the global status model (active *and* non-active paths),
(7) validates the returned model, (8) folds `to_global_params` out (list *and* dict forms).
Second worst: `loop_task_dispatch_experiment` :803-1010 (~207 lines, expansion + process-group
bookkeeping + S3 upload + plate gate).

**Shared-state hazards verified for the collaborator design (§3.3):**
- `import_queues` **reassigns** `globalstatusmodel`, `active_*`, `last_*` (payload dict →
  attributes) while *appending in place* to the deques.
- `loop_task_dispatch_experiment` **reassigns** `action_dq` (`orch.py:933`,
  `self.action_dq = zdeque([])`).
- Consequence: no collaborator may cache the *identity* of any shared mutable attribute at
  construction; all shared state is resolved through the `orch` back-reference at call time.

### 1.3 Seams already laid by P1–P4 (what P5 consumes)

- **P1 (`RunDir` + status literals):** `orch.py` imports `RunDir` (:41) and every status
  payload uses `HloStatus.<member>.value` (:677, :693, :863, :879, :1209, :2256, :2267,
  :2301, :2358) — extracted modules inherit zero magic strings.
- **P3 (Domain Integrity):** guarded lifecycle transitions (`guarded_append`/`guarded_replace`
  from `helao.core.models.status_transitions`, used at :1643-1651) mean extracted
  finish/close-out code cannot silently produce contradictory statuses; the typed-config
  injection seam (`server_api.py:71` `helao_cfg`) and the discriminated sample union reduce
  what extracted modules must know about raw dicts; typed action params + `StopCondition`
  enum (pilot, commit 3dfac0d0) firm up the sim experiments the e2e gate drives.
- **P3 verification artifacts (`.omc/artifacts/p3/`):** `run_e2e.sh` (deterministic
  ORCH+CPSIM+GPSIM OERSIM run), `normalize_runs_tree.py`, `compare_runs.py` (3-part
  byte-invisibility contract), `import_smoke.py`, `corpus_replay.py` — P5's primary gate
  already exists and already exercises clusters B, C, D, F end-to-end.
- **P4 (driver ABC + weaning):** drivers no longer reach through `Base` into orch state, so
  extraction cannot break driver back-references; the PAL call-trace golden-master
  (`helao/deploy/hte/tests/test_pal_golden_master.py`) is the proven template for the
  dispatch-trace harness in §5.3.
- **Existing enums:** `OrchStatus` / `LoopStatus` / `LoopIntent` already live in
  `helao/core/models/orchstatus.py` (:8, :24, :40) — the dispatch FSM (§3.6) consumes these
  as its state alphabet; no new enums are needed for loop state.

---

## 2. Decision

**Option (a) — full in-place decomposition — is the executed scope.** The user has directed
maximum Separation on the production orchestrator: every extractable concern becomes a
cohesive collaborator, *including* inversion of the dispatch state-machine, which is the
highest-value and highest-risk piece. Alternatives (minimal seams, deferral) are closed;
`helao/core` is the permanent home of this orchestrator and the only place the Separation
win can be realized. The only concern deliberately left in `orch.py` besides the composition
root is e-stop (cluster E), for the stability reasons argued in §3.5 — and that is a
sequencing choice within option (a), not a scope reduction (OQ-7 schedules its extraction).

---

## 3. Design — the full decomposition

### 3.1 Constraints that shape every choice

1. **Frozen external surface.** 117 `.orch.<attr>` reach-ins (§1.1) + bound-method
   registration (`orch_api` registers `orch.update_status`, `orch.ws_globstat`, …; `myinit`
   does `asyncio.create_task(self.<method>())`). Therefore: every state attribute stays on
   `Orch` at its current name, and every current public method survives as a thin delegator
   on `Orch`. Collaborators add structure *behind* the surface; nothing external moves.
2. **Pickle safety.** `export_queues` pickles a dict of live model instances
   (`GlobalStatusModel`, `Sequence`/`Experiment`/`Action`, deque contents) keyed by short
   names (`active_exp`, `last_seq`, …). Rules: (i) no pickled *class* moves modules;
   (ii) the payload dict's keys and value types are frozen; (iii) collaborators are never
   part of the payload (they hold behavior and an `orch` reference, not payload state).
   Under these rules a pck written before any stage imports after it, and vice versa.
3. **Call-time state resolution.** Because `import_queues` and `orch.py:933` *reassign*
   shared attributes (§1.2), collaborators hold exactly one reference — the `orch` instance —
   and read `self.orch.<attr>` at call time. No collaborator caches `globalstatusmodel`, a
   deque, or `global_params` at construction. This single rule makes reassignment-safe
   sharing mechanical and reviewable by grep (§5.5).
4. **Locking stays verbatim.** `aiolock` remains a `Base` attribute; every
   `async with self.orch.aiolock` moves *inside* the moved body, byte-for-byte. No await is
   added or removed in any extraction stage except S8, where the golden master (§5.3) is the
   hard gate. Lock/queue ownership after P5: `aiolock` — acquired by `StatusIngester`
   (ingestion) and `DispatchRunner` (dispatch critical section); `interrupt_q` — written by
   `StatusIngester`/`ServerMonitor`/e-stop, read by `DispatchRunner`; `globstat_q` — written
   by `StatusIngester`, drained by its own broadcast task. This map is documented in each
   module docstring.
5. **No behavior fixes ride along.** Known quirks are logged, not fixed (e.g.
   `dispatch_loop_task:1467` compares a `LoopStatus` field against `OrchStatus.estopped`; it
   behaves correctly only because both are `str` enums with value `"estopped"`. Normalizing
   it is a one-line P5b follow-up, not part of a behavior-preserving pass).

### 3.2 Collaborator map (SRP boundaries + names)

All new modules live beside `orch.py` under `helao/core/servers/` (sibling-module style,
matching `orch_api.py`; `orch.py` keeps its import path so `from helao.core.servers.orch
import Orch` is untouched). Names are legacy-idiomatic — they describe what the code does in
this codebase's vocabulary.

| New module | Collaborator | Absorbs (from §1.2) | State touched (via `orch` ref) |
|---|---|---|---|
| `orch_global_params.py` | pure functions `apply_from_globals(params, from_global_map, global_params, *, logger_ctx)` and `collect_to_globals(result_action, global_params)` | the three duplicated fold-in blocks (:707-724 seq, :838-854 exp, :1115-1129 act) and the fold-out block (:1281-1314) | none (pure; caller passes dicts) |
| `orch_persist.py` | `QueuePersister` | cluster F: `export_queues`, `import_queues` | deques, `active_*`/`last_*`, `globalstatusmodel`, histories (read for export, written by import) |
| `orch_monitor.py` | `ServerMonitor` | cluster D: `subscribe_all`, `ping_action_servers`, `active_action_monitor`, `action_server_monitor` | `world_cfg`, `init_success`, `status_summary`, `interrupt_q`; calls `orch.stop()` |
| `orch_status_sync.py` | `StatusIngester` | cluster C: `update_status`, `update_nonblocking`, `clear_nonblocking`, `ws_globstat`, `globstat_broadcast_task` | `aiolock`, `globalstatusmodel`, `nonblocking`, histories, `interrupt_q`, `globstat_q`; can trigger `orch.estop_loop` |
| `orch_queues.py` | `RunQueues` | cluster A: all queue CRUD, uuid tracking, `_prep_sequence_meta`/run-id helpers, list/get/clear/move/remove/rebuild, `supplement_error_action`/`replace_action`/`append_action` | the three deques + uuid trackers (which **remain attributes on `Orch`**; see OQ-6) |
| `orch_unpack.py` | free functions: `unpack_sequence`, `seq_unpacker`, `get_sequence_codehash`, `verify_plate_in_params`; hosts `PLATE_API` (§3.4) | cluster B's expansion helpers (:599-659) | none beyond what's passed in (near-pure; `PLATE_API` is the one service handle) |
| `orch_lifecycle.py` | `RunLifecycle` | cluster B's close-out: `finish_active_sequence`, `finish_active_experiment`, `write_active_experiment_exp`, `write_active_sequence_seq`, `start_wait`/`dispatch_wait_task` | `active_*`/`last_*`, deques (via `RunQueues`), `nonblocking`, syncer handoff, `move_dir`, `write_seq`/`write_exp` |
| `orch_dispatch.py` | `DispatchPolicy` (pure decisions) + `DispatchRunner` (async shell) + a small closed union of step dataclasses | cluster B's loop: `dispatch_loop_task`, `loop_task_dispatch_{sequence,experiment,action}`, `wait_for_interrupt`, `orch_wait_for_all_actions`, `start_loop`/`stop_loop` internals, intent application | everything the loop touches today, always via `orch.` at call time; §3.6 |

`orch.py` after P5 = module-level `sanitize_sequence_label` + `Orch` containing: `__init__`
(constructs the eight collaborators, wires state attributes exactly as today),
`exception_handler`, `myinit` (spawns the same four background tasks through delegators),
cluster E (e-stop, unchanged), and ~75 one-to-three-line delegator methods. Estimated
~800-900 lines (from 2622); ~1700+ lines relocated into eight focused, unit-testable modules.

### 3.3 Delegator + pickle mechanics (how the frozen surface survives)

```python
# orch.py — composition root (S2 example; identical shape for every collaborator)
class Orch(Base):
    def __init__(self, app):
        ...existing attribute setup, unchanged...
        self.queue_persister = QueuePersister(self)
        self.status_ingester = StatusIngester(self)
        ...

    def export_queues(self, timestamp_pck: bool = False) -> str:
        return self.queue_persister.export_queues(timestamp_pck=timestamp_pck)

    async def update_status(self, actionservermodel=None):
        return await self.status_ingester.update_status(actionservermodel)
```

- Delegators keep bound-method identity semantics for endpoint/WS registration and
  `asyncio.create_task(self.<method>())` in `myinit` — `orch_api.py` and the operator
  backend see a class whose API is unchanged by construction.
- The new instance attributes (`queue_persister`, `status_ingester`, …) are additive;
  `export_queues` builds its payload dict explicitly (it does not pickle `self`), so extra
  attributes cannot leak into `queues.pck`. Verified by the S0 fixture + S2 cross-version
  test (§5.1).
- Collaborators never import `helao.core.servers.orch` (import-cycle grep gate, §5.5); they
  import models/helpers and receive the orch instance by injection.

### 3.4 Module-global relocation rule

`PLATE_API = HTEPlateAPI()` (:77) moves to `orch_unpack.py` (its only substantive consumer);
`orch.py` re-imports it (`from helao.core.servers.orch_unpack import PLATE_API`) so the
existing patch point `helao.core.servers.orch.PLATE_API` keeps working for tests and any
out-of-tree monkeypatching. `sanitize_sequence_label` stays in `orch.py` (used by cluster-A
code paths that remain reachable through `RunQueues`, which imports it — acceptable
one-direction import).

### 3.5 E-stop (cluster E): leave in `orch.py` for P5 — justified

Extract-or-leave decision: **leave**, for P5.

- `estop_finish_active` / `_estop_promote*` / `clear_estop` were redesigned within the last
  month (no fabricated artifacts, guarded transitions via `status_transitions`, co-located
  child-dir race guard) and are **production-verified**. Churning freshly-stabilized
  safety-critical code for layout points is the worst risk/benefit trade in this file.
- E-stop is *invoked from* three collaborators (`StatusIngester` on error status,
  `DispatchRunner` on dispatch failure, `ServerMonitor` indirectly via `stop()`), so during
  P5 it is safest as a stable method set on the shared `orch` object all three already hold.
- It is already the most cohesive non-A cluster (~270 lines, 7 methods, clear entry points).

After the S8 inversion has soaked in production for one station cycle, extracting cluster E
into `orch_estop.py` (`EstopController`) is a mechanical S2-style move — scheduled as the
first P5b item (OQ-7). This is sequencing within option (a), not scope reduction.

### 3.6 The dispatch state-machine inversion (S7 + S8) — the centerpiece

Today the FSM is implicit: `dispatch_loop_task` (:1327-1493) is a `while` loop whose state
lives in `loop_state` (`LoopStatus`), `loop_intent` (`LoopIntent`), the relative fill of the
three deques, and `globalstatusmodel` queries, with transitions buried inside three
100-300-line `loop_task_dispatch_*` bodies that interleave decisions with side effects
(HTTP dispatch, file writes, S3 upload, deque mutation, status registration).

The inversion separates **deciding** from **doing**:

**`DispatchPolicy` (pure).** A class of pure functions over a read-only snapshot:

```python
@dataclass(frozen=True)
class DispatchSnapshot:          # built by the runner, under the same read points as today
    loop_state: LoopStatus
    loop_intent: LoopIntent
    n_seqs: int; n_exps: int; n_acts: int
    head_action_start_condition: Optional[ActionStartCondition]
    endpoint_free: bool; server_free: bool; actions_idle: bool   # globalstatusmodel queries
    active_experiment_present: bool; active_sequence_present: bool
    step_thru_flags: ...        # existing step-thru booleans, verbatim

class DispatchPolicy:
    def next_step(self, snap: DispatchSnapshot) -> DispatchStep: ...
    def apply_intent(self, snap: DispatchSnapshot) -> Optional[DispatchStep]: ...
```

`DispatchStep` is a small closed union of dataclasses naming what the loop can do next —
`LaunchAction`, `PopExperiment`, `PopSequence`, `RequeueActionFront`, `PauseLoop(reason)`,
`CloseOutExperiment`, `CloseOutSequence`, `AwaitInterrupt(predicate_spec)`, `IdleWait`,
`ExitLoop(reason)`. The five `ActionStartCondition` wait loops become `AwaitInterrupt` steps
whose predicate spec the policy owns (which condition, against which server/endpoint) and
whose *awaiting* the runner performs — the policy never blocks.

**`DispatchRunner` (async shell).** Owns the loop task and all effects:

- builds snapshots (reading `orch.` state at the exact points the current code reads it —
  same lock discipline, same ordering);
- executes steps: `async_action_dispatcher` calls, the `aiolock` dispatch critical section
  with estop re-check and failure→pause→requeue, `globalstatusmodel` self-registration
  (active and non-active branches), returned-model validation and error→`orch.estop_loop`,
  fold-in/fold-out via `orch_global_params`, run_id/submit-order stamping and `init_act`,
  experiment expansion via `orch_unpack` + process-group bookkeeping + `HelaoSyncer.to_s3`
  + plate gate, close-out via `RunLifecycle`, mid-loop `export_queues` (:1481 call site);
- performs all `wait_for_interrupt` awaits and interrupt-queue draining.

**What stays on `Orch` (delegators):** `start`, `start_loop`, `stop_loop`, `stop`, `skip`,
`intend_{skip,stop,estop,none}`, `wait_for_interrupt`, `orch_wait_for_all_actions` — the
operator backend and `orch_api` call these today and must keep working unmodified.
`loop_state`/`loop_intent` remain `Orch` attributes (reach-ins + pickle histories), mutated
only through runner/intent methods.

**Two-stage landing (risk containment):**
- **S7 (in-file extract-method, no move, no inversion):** `loop_task_dispatch_action`
  becomes an ~40-line coordinator over five private methods cut on the seams the function
  already exhibits: `_apply_loop_intent_before_dispatch` (:1030-1051),
  `_wait_for_start_condition` (:1058-1111), `_stage_action_for_dispatch` (:1115-1157),
  `_dispatch_action_locked` (:1159-1261), `_record_dispatch_result` (:1263-1314). Same pass:
  `loop_task_dispatch_experiment` → `_stage_experiment`, `_expand_experiment_actions`
  (:906-971), `_upload_exp_meta_s3` (:979-991), plate-gate helper shared with the sequence
  path. Golden master byte-identical.
- **S8 (the inversion):** the S7 helpers migrate into `DispatchRunner` effect methods; the
  decision logic distilled out of them becomes `DispatchPolicy`; `dispatch_loop_task`'s
  `while` body becomes `snap = self._snapshot(); step = policy.next_step(snap); await
  self._execute(step)`. Golden master byte-identical — this is the single hardest gate in
  the whole CARDS program and the reason S8 is last.

The pure `DispatchPolicy` finally makes the dispatch *decision table* unit-testable: the
scenario matrix in §5.3 gains direct policy-level tests (snapshot in → step out) on top of
the end-to-end trace equality.

### 3.7 Scope OUT (explicit non-goals, with reasons)

- **No e-stop extraction in P5** (§3.5; first P5b item, OQ-7).
- **No `Active._finish` decomposition** (`base.py`, ~221 lines). Different file, different
  blast radius (every action server, not just orchestrators); decide separately (OQ-2).
- **No `orch_api.py` internal cleanup** (its duplicate `WaitExec` :883 / `checkcond` :929
  and general shape are P5b/OQ-3 material; P5 must not grow its own surface area).
- **No behavior fixes** (§3.1 rule 5).
- **No config, wire-format, or data-format changes of any kind** — this is what makes
  post-merge rollback trivially safe (§6).

### 3.8 Dependency-injection posture

Collaborators are constructed inside `Orch.__init__` with the orch back-reference —
injection stays at the `Base`/config seams P3 built (`helao_cfg`, `server_params`); no new
wiring pattern, no config keys, no launcher changes. `orch.py` remains the composition root;
`myinit` (:205-235) still owns all task spawning (now via delegators). Test construction
uses the same `Orch.__new__` + attribute-fixture bypass the golden master uses (§5.3), plus
direct construction of individual collaborators with a fake orch for unit tests — the
collaborator boundary is exactly what makes those unit tests possible for the first time.

---

## 4. Staging (ordered, each stage independently bootable + committable)

Risk order: evidence first; pure-addition next; persistence (cold path); monitors
(background, idle-safe); status ingestion (hot path, verbatim move); queue CRUD (wide but
shallow); unpack + lifecycle (prepares the loop); in-file dispatch decomposition; the FSM
inversion **last**, as the highest-risk stage with every gate warmed up; sweep.

| Stage | Content | Why this order | Boot-safety argument |
|---|---|---|---|
| **S0** | Baseline capture: unit suite, ×2 e2e OERSIM runs (`run_e2e.sh baseline`, `baseline2` — noise floor), dispatch-trace golden master recorded (§5.3), `import_smoke.py` snapshot, export/import round-trip fixture (`queues.pck` produced by current code, checked into `.omc/artifacts/p5/`) | Evidence before edits (P4 D7 discipline) | no code change |
| **S1** | `orch_global_params.py` (pure `apply_from_globals`/`collect_to_globals`) + swap the four fold blocks to call them; de-duplicates 3 copies of the fold-in block | Smallest semantic surface; pure, unit-testable, no async/lock involvement | fold behavior byte-equal (unit: identical dict mutations incl. list-vs-dict `to_global_params` forms; the `_fast_samples_in` exclusion is *not* part of fold — verify untouched) |
| **S2** | `orch_persist.py` / `QueuePersister` + delegators; round-trip unit test (export→import on a fake orch); **cross-version test**: S0's pickled fixture imports cleanly post-move, and an S2-written pck imports under stashed S0 code | Cold path — runs only at shutdown/loop-drain/`--restore`; failure mode is visible, not silent | delegator preserves `orch.export_queues` endpoint binding in `orch_api` and the `dispatch_loop_task:1481` / `shutdown:2402` call sites |
| **S3** | `orch_monitor.py` / `ServerMonitor` + delegators | Background tasks; read-mostly; worst failure = missed heartbeat (self-healing next tick) | `myinit` still does `asyncio.create_task(self.subscribe_all())` etc. via delegators; `init_success`/`status_summary` attribute writes unchanged |
| **S4** | `orch_status_sync.py` / `StatusIngester` + delegators | Hot path but *ingress-only*: mutates `globalstatusmodel` under the same `aiolock`, pushes to the same queues; extraction is verbatim-move | `orch.update_status` / `orch.update_nonblocking` / `orch.ws_globstat` remain bound methods (orch_api registers them); WS clients unaffected; lock acquisition stays inside moved bodies |
| **S5** | `orch_queues.py` / `RunQueues` + delegators for all cluster-A methods | Wide (~25 methods) but shallow — pure deque/state ops with no async or lock; operator backend + orch_api exercise it constantly, so breakage is loud and immediate in e2e | deques + uuid trackers stay as `Orch` attributes; `RunQueues` reads them call-time (§3.1 rule 3); every list/get/move/remove endpoint delegates |
| **S6** | `orch_unpack.py` (expansion helpers + `PLATE_API` relocation w/ re-import, §3.4) and `orch_lifecycle.py` / `RunLifecycle` (finish/write/wait-action) + delegators | Shrinks the dispatch-loop bodies' callees before touching the loop itself; close-out logic gains its first unit tests | finish/write delegators preserve orch_api + loop call sites; e2e finish/move lifecycle is directly diffed by Gate 2 |
| **S7** | In-file extract-method decomposition of `loop_task_dispatch_action` → 5 helpers and `loop_task_dispatch_experiment` → 4 helpers (§3.6); no move, no inversion | Names the seams the inversion will cut; golden master proves the cut lines are behavior-neutral before any code moves | intra-class only; coordinator preserves the exact early-return/requeue/lock structure |
| **S8** | **The FSM inversion**: `orch_dispatch.py` — `DispatchPolicy` + `DispatchRunner` + `DispatchStep` union; loop/intent/wait methods become delegators; policy-level unit tests for the full decision table | Highest risk, so it lands last, alone, with all gates green and warmed | `start/stop/skip/intend_*` delegators keep operator + orch_api working; `loop_state`/`loop_intent` stay `Orch` attributes; golden master byte-equality is the hard gate |
| **S9** | Sweep: docstrings/module headers incl. the lock-ownership map (§3.1 rule 4), grep gates (§5.5), dead-code decision (OQ-3), line-count report, CARDS re-score note in `CARDS_AUDIT.md` appendix | — | no logic |

Per-stage cadence (CARDS convention): implement → gates green → **one commit per stage** →
Opus review pass → push. No stage starts until the previous stage's review lands. S1-S7
revert independently in isolation (`git revert <sha>` — each stage's delegators + module are
self-contained); S8 reverts as one commit back onto the S7 shape.

Estimated end state: `orch.py` ≈ 800-900 lines (composition root + delegators + e-stop);
~1700+ lines relocated into 8 focused modules with unit tests; zero interface changes; zero
config/data-format changes.

---

## 5. Verification (P5 is fully Linux-verifiable — the contrast with P4)

P4's production wave had to settle for construction-proofs (`constr`) because its subjects
were Windows/hardware drivers. **P5's subject is pure core code exercised end-to-end by the
`test` deployment sims on this box** — every gate below actually runs the refactored code's
full behavior, not just its importability.

### 5.1 Gate 1 — unit suite (every stage)

`conda run -n helao python run_unit_tests.py` (the launch-blocking gate) plus the standalone
`helao/core/tests/unit_test_*.py` scripts that touch orch behavior
(`unit_test_estop_sync.py`, operator/standalone tests). New unit tests added by P5:
`orch_global_params` fold semantics (S1); persistence round-trip + **both-direction**
cross-version pck (S2); monitor response-parsing on canned `get_status` payload shapes (S3);
`RunQueues` CRUD invariants incl. move/remove/rebuild ordering (S5); `RunLifecycle`
close-out transitions against the P3 guarded-transition table (S6); `DispatchPolicy`
decision-table tests — snapshot in, step out, over the full §5.3 scenario matrix (S8).

### 5.2 Gate 2 — e2e sim byte-invisibility (every stage from S1 on)

The P3 harness, unchanged:

```bash
.omc/artifacts/p3/run_e2e.sh p5s<N>        # ORCH+CPSIM+GPSIM, OERSIM enqueue, drain, normalize
conda run -n helao python .omc/artifacts/p3/compare_runs.py baseline p5s<N>
```

Pass = the 3-part contract (identical file manifest; identical normalized non-`.hlo` text —
i.e. every `-act/-exp/-seq.yml`; identical `.hlo` headers + per-key value multisets). This
single gate exercises: subscribe_all, status ingestion, the full dispatch loop across all
three queue levels, global-param fold in/out (OERSIM uses `to_global_params`), finish/move
lifecycle, and WS broadcast — i.e. every cluster P5 touches. Additionally from S2 on: a
**`--restore`-path variant** (enqueue → export mid-queue → restart ORCH with
`restore_queues_on_startup` → drain → same diff), which the current harness doesn't cover
and P5 adds as `run_e2e_restore.sh` under `.omc/artifacts/p5/`.

### 5.3 Gate 3 — dispatch-decision golden master (S0 records; byte-identical after every stage; the hard gate for S7/S8)

A pure **behavior-preservation gate**. Template: the PAL call-trace harness
(`helao/deploy/hte/tests/test_pal_golden_master.py` — `__new__` bypass + fakes + pinned time
+ recorded ordered trace). P5 analog, new file
`helao/core/tests/test_orch_dispatch_golden_master.py`:

- **Real (unmodified at S0; refactored thereafter):** `dispatch_loop_task`,
  `loop_task_dispatch_{sequence,experiment,action}`, `wait_for_interrupt`, intent methods,
  fold logic, `GlobalStatusModel`.
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
  For S8 additionally: the same matrix is re-expressed as direct `DispatchPolicy` unit tests
  (snapshot → step), so the decision table is pinned at two levels.

### 5.4 Gate 4 — import smoke & construction

`conda run -n helao python .omc/artifacts/p3/import_smoke.py` +
`python -c "import helao.core.servers.orch, helao.core.servers.orch_api, <new modules>"`.

### 5.5 Grep gates (S9)

- No method bodies left behind: moved functions exist exactly once
  (`grep -c "def update_status" orch.py orch_status_sync.py` → delegator + one body).
- No import cycles: extracted modules never import `helao.core.servers.orch`
  (`grep -rn "servers.orch\b" helao/core/servers/orch_*.py` → only the `PLATE_API`
  re-import direction allowed in `orch.py` itself, §3.4).
- Call-time resolution rule (§3.1 rule 3): no collaborator `__init__` binds a shared mutable
  (`grep -n "self\.\(globalstatusmodel\|.*_dq\|global_params\)\s*=" orch_*.py` → empty
  outside `orch.py`).
- The four fold blocks are gone from `orch.py` (`grep -n "from_global_.*_params.items()"`
  → only `orch_global_params.py`).
- No `DispatchStep` execution outside `DispatchRunner._execute` (single-dispatch-site rule).

---

## 6. Risk + rollback (highest-risk phase of the CARDS program; production orchestrator)

Honesty first: **option (a) is the most invasive path available for this file.** The S8
inversion rewrites the control flow of the code that sequences every production run, in the
highest-churn file in the repo, with no second implementation to diff against. What makes it
tractable is that S1-S7 progressively shrink the loop bodies to named, individually-gated
seams *before* the inversion touches control flow, and that the golden master pins the
complete decision behavior byte-for-byte at every stage — the inversion lands as the last,
smallest possible control-flow diff, not as a big-bang rewrite.

| Risk | Exposure | Mitigation |
|---|---|---|
| **S8 semantic drift** (decision reordering, snapshot-vs-live-read divergence, early-return/requeue equivalence) | Wrong action ordering, lost requeue, or a stuck loop on a live station — the worst outcome P5 can produce | S7 first names every seam with the golden master green; snapshots are built at the exact read points (and under the same lock points) as current code; golden-master byte-equality + policy-level decision-table tests + e2e drain are all hard gates; S8 is one revertable commit |
| **Pickle/restore breakage** (`queues.pck` written by old code, read by new, or vice versa after rollback) | Operators rely on `--restore` after crashes/hot-reload | No pickled classes or payload keys move (§3.1 rule 2); S0 checked-in pck fixture + S2 both-direction cross-version tests; e2e restore-path variant (§5.2) |
| **Bound-method identity loss** (endpoints/WS handlers/`create_task` registered from `self.<method>`) | `orch_api.py` registers `orch.ws_globstat`, `orch.update_status`, …; `myinit` spawns 4 tasks | Delegator methods retained for every moved callable — the class API is unchanged by construction; import smoke + e2e catch a missed one immediately (server won't wire) |
| **Lock/queue reordering** (`aiolock` held by both `StatusIngester.update_status` and the runner's dispatch critical section; `interrupt_q` written by C/D/E, read by the runner) | Deadlock or missed-interrupt = stuck production run | Verbatim-move rule (§3.1 rule 4): lock acquisitions stay inside moved bodies; no await added/removed outside S8; golden-master scenario (4) covers the interrupt handshake; lock-ownership map in module docstrings |
| **Stale-reference bugs** (collaborator caches a deque/`globalstatusmodel` identity that `import_queues` or `orch.py:933` later reassigns) | Silent split-brain state after a restore or mid-run deque reset | Call-time resolution rule (§3.1 rule 3) + its grep gate (§5.5); restore e2e variant exercises exactly this path |
| **Hot-reload interaction** (watcher restarts idle servers whose loaded modules changed) | New modules must appear in `/loaded_modules` | They do automatically (import-graph-based); noted for the reviewer, no action |
| **Merge-window exposure** | hte stations run their deployed branch; exposure begins at merge to `unstable` + station update | Merge P5 only as a whole (S0-S9 complete); first station update on a maintenance window with `--restore` smoke + one supervised sequence, per P4 wave discipline |
| **Mid-flight hotfix collision** (`orch.py` is the highest-churn file) | Rebase conflicts with production fixes on `unstable` | Rebase `feat/cards-refactor` before each stage lands; delegator-style moves rebase cleanly (small orch.py diffs); if a hotfix touches a cluster mid-extraction, that stage restarts from the rebased file; a hotfix touching the *loop* while S7/S8 are in flight pauses S8 until the fix is absorbed and the golden master re-recorded |

**Rollback:** one commit per stage; S1-S7 revert independently; S8 reverts as one commit
back onto the fully-gated S7 shape; no nested-repo commits exist in P5 at all, so rollback
is single-repo. Pre-merge, branch reset remains available. Post-merge worst case: revert the
merge commit — no data-format, wire-format, or config change exists anywhere in P5, so
reverted code is immediately compatible with anything P5-era servers wrote (including
`queues.pck`, by the frozen-payload rule).

---

## 7. Open questions (for the human; append to `.omc/plans/open-questions.md`)

- **OQ-1 (restore compatibility contract):** Is cross-version restore (pck written before
  P5, imported after — and the reverse, after a rollback) a *hard requirement* or
  best-effort? The design preserves it by construction; a "hard requirement" answer keeps
  the both-direction test in S2. Recommended: hard requirement (hot-reload restarts
  orchestrators with `--restore` unconditionally).
- **OQ-2 (`Active._finish`):** The master plan's P5 sketch mentions decomposing
  `Active._finish` (~221 lines, `base.py`). It touches every action server, not just
  orchestrators — different blast radius, different golden master. In P5 (as an S7-style
  in-file clarity pass with the e2e gate) or deferred to a P5b? Recommended: defer to P5b,
  decided after S8's golden-master experience.
- **OQ-3 (dead consumers check before S9):** `orch_api.py:883` defines a second `WaitExec`
  and `:929` a `checkcond` enum; and `endpoint_queues_init` (orch.py:237-248) is
  commented-out dead code. Delete dead code in S9, or freeze? Recommended: delete the
  commented block only (zero-risk); leave `orch_api` untouched (out of P5 scope).
- **OQ-4 (`DispatchPolicy` interface granularity):** One policy class returning
  `DispatchStep` values for all three queue levels (as designed, §3.6), or three per-level
  policies (sequence/experiment/action) composed by the runner? And are the
  `ActionStartCondition` wait predicates policy-owned *specs* (as designed) or runner-coded
  waits the policy merely names? Recommended: single policy + step values + policy-owned
  wait specs — one decision table, directly unit-testable; split later only if it grows.
- **OQ-5 (concurrency/locking ownership):** P5 leaves `aiolock`, `interrupt_q`, and
  `globstat_q` on `Orch`/`Base`, shared by `StatusIngester` and `DispatchRunner` under the
  documented ownership map (§3.1 rule 4). Should a later pass move coordination into a
  dedicated object (e.g. a small `DispatchGate` owning lock + interrupt queue)? Recommended:
  leave shared on `Orch` through P5; revisit in P5b once the S8 shape has soaked — moving
  the lock is a semantics change, not a layout change.
- **OQ-6 (run-deque residence):** The design keeps the three deques (and uuid trackers) as
  plain `Orch` attributes borrowed call-time by `RunQueues` (§3.1 rule 3), because
  reach-ins, pickle payload, and the `orch.py:933` reassignment all touch them. Alternative:
  `RunQueues` owns them with forwarding properties on `Orch`. Recommended: as designed
  (attributes stay on `Orch`); revisit only if a later pass proves property forwarding
  behavior-equal under the restore harness.
- **OQ-7 (e-stop extraction timing):** Cluster E stays in `orch.py` for P5 (§3.5). Schedule
  its extraction (`orch_estop.py` / `EstopController`, incl. the `estop_actions(switch)`
  flag-arg cleanup from the audit) as the first P5b item after one production soak cycle of
  the S8 shape? Recommended: yes — P5b, not P5.
