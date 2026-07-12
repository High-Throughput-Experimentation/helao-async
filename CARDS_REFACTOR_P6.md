# CARDS Refactor — P6: `Base` / `Active` decomposition (`helao/core/servers/base.py`)

**Status:** DRAFT plan (not started). Prereq-gated — see §7.
**Weakest cards targeted:** Separation (weakest), Clarity (tied). Same fix as P5, applied to the other core god-class.
**Branch:** a fresh `feat/cards-base-refactor` off `unstable` **after** P5 (`feat/cards-refactor`) merges and soaks — see §7.
**Model routing:** Fable = plan/spec, Sonnet = implementers, Opus = review/controller (same as P4/P5, [[model-routing]]).

---

## 1. Why P6 exists

The CARDS audit named *god-classes* (plural) as the root of the weakest cards, and cited the in-tree `base_api.py` decomposition as the model. P5 removed one (`Orch`, 2622→1036). `base.py` is the other, and it is the same tier:

- `base.py` = **2557 lines**, two god-classes:
  - **`Base`** (~1054 lines, 47 methods) — the parent of **every action server** (via `BaseAPI`).
  - **`Active`** (~1362 lines, 41 methods — *larger than `Base`*) — instantiated for **every action in every deployment**.
- Hot-path confirmation: `base.py` is the #2 most-touched file in the repo (project-memory hot paths); `active.` is referenced in **91 files** across all deployments, `self.base.` in **25**.

`Base`/`Active` fuse the exact concerns the audit flagged — networking (endpoint/WS), broadcast (status), persistence (hlo/meta file output), state-machine (action finish/split lifecycle), and data streaming — in two classes. Decomposing them is the largest remaining Separation/Clarity win in `helao/core`.

## 2. Why P6 is riskier than P5 (and must be gated, not rushed)

| Axis | P5 (`Orch`) | P6 (`Base`/`Active`) |
|---|---|---|
| Blast radius | orchestrator servers only | **every action server + every action, all deployments** |
| Frozen external surface | 117 `orch.*` reach-ins, concentrated in `orch_api.py` | **`active.*` = 26 members × 91 files; `self.base.*` = 48 members × 25 files** — spread across every deployment's drivers/executors/experiments |
| Behavior harness | existed after S0 (dispatch golden master) | **none exists** — must be built first (P6-S0) |
| Hardest concern | dispatch FSM (decision trace, pinnable) | **`Active` data-enqueue → file-output → finish/split** (async timing, hlo file bytes, data-loss risk) — harder to pin than decisions |
| Prod-proof | P5 shape not yet soaked | P6 stacks on P5; must wait for P5 soak |

Consequence: **P6 is its own phase with its own harness, staged smallest-blast-first, and gated behind a P5 production soak.** Do not treat it as a P5b follow-on.

## 3. Current-state recon (responsibility clusters)

### 3.1 `Base` (helao/core/servers/base.py:111–1165) — 8 clusters

| Cluster | Methods | Target collaborator |
|---|---|---|
| **A. Endpoint/URL setup** | `dyn_endpoints_init`, `endpoint_queues_init`, `init_endpoint_status`, `get_endpoint_urls` | `EndpointManager` (coordinate w/ `base_api.py`, §6) |
| **B. Action containment** | `_get_action`, `setup_action`, `setup_and_contain_action`, `contain_action`, `get_active_info` | stays on `Base` (composition root) — thin, calls collaborators |
| **C. Status WS + broadcast** | `send_statuspackage`, `send_nbstatuspackage`, `attach_client`, `detach_client`, `_ws_relay`, `ws_status`, `ws_data`, `ws_live`, `detach_subscribers`, `replace_status` | `StatusBroadcaster` (direct analog of P5 `StatusIngester`) |
| **D. Live buffer** | `live_buffer_task`, `_stamp_lbuf_dict`, `put_lbuf`, `put_lbuf_nowait`, `get_lbuf`, `get_realtime`, `get_realtime_nowait` | `LiveBuffer` |
| **E. Status tasks** | `regular_status_task`, `log_status_task` | `StatusBroadcaster` (bg tasks) |
| **F. Action-queue dispatch** | `_dispatch_queued_action`, `process_unified_queue`, `process_endpoint_queue` | `ActionQueueDispatcher` |
| **G. File / meta output** | `_write_meta_atomic`, `write_act`, `write_exp`, `write_seq`, `new_file_conn_key`, `dflt_file_conn_key` | `MetaFileWriter` |
| **H. Executor / estop mgmt** | `stop_executor`, `stop_all_executor_prefix`, `estop_actives` | stays on `Base` (short; coupled to `actives` dict) |
| Lifecycle/misc | `__init__`, `exception_handler`, `myinit`, `print_message`, `shutdown`, `get_main_error`, `import_postprocessors` | stays on `Base` |

### 3.2 `Active` (base.py:1166–2528) — 6 clusters

| Cluster | Methods | Target collaborator |
|---|---|---|
| **A. Executor orchestration** | `executor_done_callback`, `start_executor`, `oneoff_executor`, `action_loop_task`, `stop_action_task` | `ExecutorRunner` |
| **B. Data file init/header** | `myinit`, `init_datafile`, `finish_hlo_header`, `log_data_set_output_file`, `_resolve_output_path` | `DataFileWriter` |
| **C. Data enqueue/stream** | `write_live_data`, `enqueue_data_dflt`, `_build_data_package`, `enqueue_data`, `enqueue_data_nowait`, `assemble_data_msg`, `add_new_listen_uuid`, `log_data_task`, `get_realtime`, `get_realtime_nowait` | `DataStreamer` |
| **D. File I/O** | `write_file`, `write_file_nowait`, `track_file`, `relocate_files`, `update_act_file` | `DataFileWriter` (shares w/ B) |
| **E. Status / sample** | `add_status`, `set_estop`, `set_error`, `send_nonblocking_status`, `set_sample_action_uuid`, `append_sample` | stays on `Active` (thin) + `SampleTracker` (optional) |
| **F. Finish/split lifecycle** | `split_and_keep_active`, `split_and_finish_prev_uuids`, `finish_all`, `split`, `substitute`, `finish`, `_finish`, `finish_manual_action` | **`ActionFinalizer`** (hardest, highest value, most data-loss-prone) |

### 3.3 Existing seam (lowers risk)
`Active` already holds a `.base` back-reference (`active.base`, 71 refs) and is constructed at a **single site** (`base.py:475` `self.actives[uuid] = Active(...)`). So the P5 collaborator idiom — collaborator holds one back-ref, reads state at call time — is already latent. Collaborators hang off `Base`/`Active` composition roots; `Active` collaborators read `self.active.base.<x>` / `self.active.<x>` at call time.

## 4. Design principles (inherited verbatim from P5 §3.1)

1. **Frozen external surface.** Every one of the 26 `active.*` members and 48 `self.base.*` members survives as a thin delegator with identical signature. Collaborators add structure *behind* the surface. This is stricter than P5 (surface is 5× wider and spread across 91 deployment files).
2. **Call-time state resolution.** Collaborators hold exactly one back-ref (`self.base` / `self.active`) and read shared mutables at call time. No caching of `actives`, buffers, queues, file handles, or status dicts in `__init__`.
3. **Locking/await verbatim.** Every `async with`, every await, every queue op moves byte-for-byte; ordering preserved.
4. **No behavior fixes ride along.** Quirks preserved; fixes are separate follow-ups.
5. **Pickle/wire safety.** `Active` is not pickled the way orch queues are, but the hlo file bytes + status wire packets ARE the contract — the harness (§5) freezes them.

## 5. Behavior-preservation harness (P6-S0 — build FIRST, before any extraction)

P5 was only safe because S0 froze behavior first. P6 needs two harnesses because Base/Active aren't a pure decision trace:

- **P6-S0a — `Active` output golden master.** Drive a real `Active` through a scripted action lifecycle (setup → enqueue_data (multiple chunks) → write_file → finish/split) against fakes for the server/dispatch edges (RecordingBase pattern, mirroring the PAL/Orch harnesses). Freeze: the hlo file bytes (header + data multisets, reuse `compare_runs`'s multiset rule for async chunk noise), the `-act.yml`/meta bytes, the status/nonblocking wire packets, and the finish/split state transitions. `--check` byte/multiset-diffs vs a frozen baseline.
- **P6-S0b — action-server e2e.** Reuse the OERSIM `.omc/artifacts/p3` harness (already exercises Base/Active end-to-end through real action servers). Controller-run milestone gate (index-collapsed `compare_runs`, as used to close P5's S7/S8). This is the fleet-level net.

Both must be green on pre-P6 code and frozen before P6-S1.

## 6. Staging (smallest blast radius first; hardest last — mirrors P5 S1→S8)

| Stage | Work | Blast / risk | Gate |
|---|---|---|---|
| **P6-S0** | Build P6-S0a Active golden master + freeze; confirm P6-S0b e2e baseline | none (test-only) | harnesses green + frozen |
| **P6-S1** | `Base` → `LiveBuffer` (cluster D) | low, self-contained | S0a/S0b + `unit_test_base_api` |
| **P6-S2** | `Base` → `StatusBroadcaster` (clusters C+E) | low — direct `StatusIngester` analog | + StatusBroadcaster unit test |
| **P6-S3** | `Base` → `MetaFileWriter` (cluster G) | medium — file bytes | S0a byte-gate |
| **P6-S4** | `Base` → `ActionQueueDispatcher` (cluster F) + `EndpointManager` (cluster A, w/ `base_api` coord §6.1) | medium | S0b e2e milestone |
| **P6-S5** | `Active` → `DataFileWriter` (clusters B+D) | medium-high — hlo header/file bytes | S0a byte-gate |
| **P6-S6** | `Active` → `DataStreamer` (cluster C) | **high** — async enqueue/timing, data-loss-prone | S0a multiset + S0b e2e milestone |
| **P6-S7** | `Active` → `ExecutorRunner` (cluster A) | high — executor lifecycle/task mgmt | S0a + S0b |
| **P6-S8** | `Active` → `ActionFinalizer` (cluster F: finish/split/substitute) | **highest** — the finish/split state machine; lands last, alone | S0a state-transition + S0b e2e milestone; also `Active._finish` P5b item folds in here |
| **P6-S9** | Sweep: docstrings + lock/ownership map, grep gates, dead-code, line-count, CARDS re-score | none | S0a + S0b + full suite |

Per stage (P5 discipline): one commit → Opus review → fix Critical/Important → the stage's gate green → push. `Active` stages (S5–S8) each run the S0b e2e milestone because their bugs are timing/data-shaped, not trace-shaped.

## 6.1 `base_api.py` coordination
`base_api.py` (871 lines: `ActionInvocation`, `ActionAPIRoute`, `BaseAPI`) already owns request→action plumbing. P6 must NOT re-fragment: `EndpointManager` (S4) absorbs the endpoint-setup that logically belongs with `BaseAPI`'s routing, and clusters that `base_api` already handles stay there. Audit `base_api`↔`Base` boundaries in S0 before S4.

## 7. Prerequisites / gating (do NOT start P6 until all hold)

1. **P5 merged to `unstable` and soaked** ≥1 production cycle (the whole-branch reviewer's production gate; also the P5b estop-extraction gate). P6 stacks on P5's collaborator idiom — proving it in prod first de-risks P6.
2. **P6-S0 harnesses built + frozen** (§5).
3. Fresh branch `feat/cards-base-refactor` off post-P5 `unstable`.
4. Station smoke of at least one hardware action server is scheduled (P6 changes the class every hardware driver rides on — a sim-only proof is necessary but not sufficient before hte production).

## 8. Risk + rollback
- One commit per stage; S1–S7 revert independently; S8 (finalizer) reverts onto the S7 shape.
- The 91-file `active.*` surface means a missed delegator breaks deployments silently — the grep gate (`active.<member>` set unchanged; every member resolves to a delegator or `Base`-inherited attr) is mandatory each stage.
- Blast radius = fleet: never merge a P6 stage to `unstable` without both S0a green AND an S0b e2e milestone on the `Active` stages.

## 9. Open questions (resolve before P6-S1)
- **OQ-P6-1:** `Active` collaborator residence — hang collaborators off `Active` (per-action, N instances) vs off `Base` (shared, stateless, take `active` as arg)? Per-action objects are heavier (one set per live action); shared-stateless mirrors P5 better. **Rec: shared-stateless collaborators on `Base`, methods take `active`** — avoids per-action allocation churn.
- **OQ-P6-2:** Is the hlo-file-bytes contract frozen at the *byte* level or the *parsed-multiset* level? (async flush chunking is nondeterministic — P5 e2e already treats it as multiset noise). **Rec: parsed-multiset for data lines, byte for headers/meta**, reusing `compare_runs`.
- **OQ-P6-3:** `DummyBase` (base.py:2529) — fold into the decomposition or leave? **Rec: leave; it's a test shim.**
- **OQ-P6-4:** Does P6 wait for the full P5 soak, or can the low-blast Base stages (S1–S2, status/live-buffer) start on a soak-parallel track? **Rec: wait — one gate, no partial start.**

---

*This is a DRAFT. No code exists. Execution is gated per §7. Aliasing rule from [[cards-deployment-aliases]] applies (parent repo is public; never name private deployments).*
