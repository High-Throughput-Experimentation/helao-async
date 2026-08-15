# B3 — `OrchHost` Design

**Sub-project of the legacy separation program** (`2026-08-14-legacy-separation-program-design.md`).
Replaces `OrchAPI` + `Orch` with a hexagon-native host, as B1 replaced `BaseAPI` + `Base`.

**Status:** design. No code.

---

## 1. The measurement that shapes this sub-project

The program spec calls B3 "the largest single item", at 5,371 lines across 11 files. That number
is real but it is the wrong one to plan against. Measured on `unstable` at `03d03084`:

| what | measured |
|---|---|
| `Orch` methods that are ≤2-statement delegations | **73 of 79** |
| `Orch` methods carrying real logic | **6** — `__init__` (97 lines), `myinit` (29), `wait_for_interrupt` (21), `shutdown` (15), `_init_collaborators` (8), `exception_handler` (3) |
| total logic in `orch.py` | **~173 lines of 879** |
| collaborators `Orch` delegates to | **7**, constructed in `_init_collaborators` |
| collaborator source | **3,262 lines** (`orch_dispatch` 1337, `orch_queues` 562, `orch_status_sync` 310, `orch_estop` 307, `orch_persist` 293, `orch_lifecycle` 264, `orch_monitor` 189) |
| what each collaborator holds | **only `self.orch`** — no cached queue, task handle, or model |
| `orch_api.py` route surface | **72 routes** (3 websocket, 69 POST) |
| hexagon reducer already built and grafted | **1,292 lines** (`domain/orchestration.py` 619, `app/orch_effects.py` 405, `app/dispatch_loop.py` 268) |

**`orch.py` is a delegation shell, exactly as `base.py` was after CARDS P6.** That is not a
coincidence — P5 decomposed `Orch` (2622 → 1036) and P6 decomposed `Base`, and B1 was writable as
a delegation shell precisely because P6 had already moved the logic out. B3 inherits the same
gift. The 5,371 lines are not 5,371 lines *to write*.

### 1.1 The number that actually governs B3

Every collaborator reads its state back through `self.orch`. The union of distinct `Orch` members
that the collaborators and `orch_api` require is the contract `OrchHost` must satisfy:

| consumer | distinct `Orch` members read |
|---|---|
| `orch_dispatch` | 58 |
| `orch_queues` | 26 |
| `orch_lifecycle` | 25 |
| `orch_estop` | 20 |
| `orch_persist` | 16 |
| `orch_status_sync` | 10 |
| `orch_monitor` | 10 |
| all collaborators (union) | **95** |
| `orch_api` | 60 |
| **union of both** | **135** |

`Orch`'s own public surface is 71 methods + 65 attributes.

**This is knowable now, and that is the single most important fact about B3.** B1's equivalent
number was discovered *one runtime crash at a time* — `helaodirs`, `begin_session`, `write_act`,
`_write_meta_atomic`, `myinit` — each costing a launch-and-diagnose cycle, and each individually
invisible to seventy passing unit tests. The member-coverage ratchet was written mid-B1, after
the fact, and immediately found 43 gaps. B3 starts with the ratchet, seeded from the measurement
above, before a line of host code exists.

Note the measured set already includes contractual privates — `_ensure_run_id`,
`_rebuild_action_dq`, `_rebuild_experiment_dq`, `_rebuild_sequence_dq`, `_prep_sequence_meta`,
`_resolve_active_run_id`. B1 lost most of a session to exactly one of these
(`_write_meta_atomic`): underscore-prefixed, so a public-members-only scan skipped it, and its
`AttributeError` fired inside a caught block, so every action returned 200 and wrote nothing.
The extraction here counts attribute access on the back-reference rather than filtering by
name, so privates are in the contract by construction.

---

## 2. Decisions

### D-B3.1 — Reuse the seven collaborators natively; do not reimplement them

**Decision.** Move `orch_dispatch`, `orch_queues`, `orch_lifecycle`, `orch_estop`, `orch_persist`,
`orch_status_sync`, `orch_monitor` into `helao/hexagon/app/`, changing their back-reference from
`Orch` to `OrchHost` and nothing else. `OrchHost` constructs them exactly as `_init_collaborators`
does today.

**Why.** They hold only `self.orch` and resolve every piece of state through it at call time — a
property their own module docstrings state as a rule ("holds ONLY `self.orch`"). That makes the
back-reference swappable, which is the whole reason B1 could reuse `EndpointManager`,
`ActionQueueDispatcher` and `MetaFileWriter` unchanged.

The scope difference is the lever for this entire sub-project: **reuse means ~900 lines of new
host code; reimplementation means ~3,400 and a fresh parity argument for each collaborator.** The
bodies are already byte-parity-pinned against their pre-decomposition originals; reimplementing
discards that evidence and buys nothing B7 will not take anyway.

**Consequence for B7.** These seven files move rather than die, so B7's deletion list shrinks by
3,262 lines and gains seven renames. That is a better trade: a move is reviewable as a diff of
zero, a rewrite is not.

### D-B3.2 — The reducer stops being a graft and becomes the loop

**Decision.** `OrchHost` drives `app/dispatch_loop.py` directly. `graft_hexagon_loop` and
`makeOrchApp`'s startup hook are retired at the same commit that the host lands, not left beside
it.

**Why.** The reducer already *is* the dispatch loop on every hexagon station — `makeOrchApp`
constructs a legacy `OrchAPI`, waits for `self.orch = Orch(...)`, then grafts the reducer over the
live object. The graft exists only because there was no native host to own the loop. Once there
is, keeping both is two code paths for one behaviour, and B1 has already shown what that costs:
`makeActionApp` went on grafting the write path onto native hosts after B1 landed, and the
resulting `AttributeError` fired inside the FastAPI startup event where uvicorn reports it only as
`SystemExit(3)` — the server never bound and nothing in the output named the cause.

**`_is_native_host` in `factory.py` is the precedent and should be extended, not duplicated.**

### D-B3.3 — Split B3 in two, at the dispatch seam

**Decision.** Two sub-projects:

- **B3a — host + state + queue surface.** `OrchHost` construction, the 135-member contract, the
  ratchet, `orch_queues`, `orch_persist`, `orch_estop`, `orch_lifecycle`, and **48 routes** — 39
  private plus 9 `/{server_key}/…` action routes — that read or mutate queues without running the
  loop. The remaining 24 are registered here as raising stubs, so the surface is complete and a
  caller fails at the call site rather than on a 404 that reads as a missing server.
- **B3b — the loop.** `orch_dispatch`, `orch_status_sync`, `orch_monitor`, the reducer cut-over
  (D-B3.2), the globstat broadcaster, and the **24 routes** that start, stop, skip, estop, ingest
  status or stream WS.

*(Counted by AST over `orch_api.py`, not by grep: 9 of the 72 have f-string paths that a
same-line string-literal regex misses entirely.)*

**Why.** B1 was one sub-project and it was too big: the host, the route surface, the context, the
session, the executor runner, the middleware and nine deployment modules landed together, and the
write-path defects were only found at the end, when GM captures ran. Task 3 had to be split
mid-flight once the seam showed. The seam here is visible in advance — B3a's gate is
`/openapi.json` plus the ratchet with no loop running at all, which is a genuinely cheaper gate
than GM parity, and B3b is where the concurrency suite and GM-1…GM-6 earn their keep.

`orch_dispatch` alone reads 58 distinct `Orch` members, more than twice any other collaborator.
Landing it in the same change as host construction means a construction bug and a dispatch bug
are indistinguishable at first failure.

### D-B3.4 — No behaviour change, including the known quirks

**Decision.** The post-parity backlog stays untouched: `set_error`, the finish-drain window, the
0.3 s per-client pacing sleep, `/ws_globstat`'s dead sender, `params.limit_vis`. They are
dispositioned in B7.

**Why.** Program spec §5 already says this. Restated here because B3 is the sub-project where the
temptation is strongest — the dispatch loop is where every one of those quirks lives, and each
looks like an obvious fix while reading the code around it. A behaviour change inside a parity
port is indistinguishable from a port bug at the gate.

---

## 3. What `OrchHost` is

```
helao/hexagon/app/orch_host.py      OrchHost(HelaoFastAPI)   — the server
helao/hexagon/app/orch_queues.py    RunQueues                — moved, back-ref swapped
helao/hexagon/app/orch_persist.py   QueuePersister           — moved
helao/hexagon/app/orch_estop.py     EstopController          — moved
helao/hexagon/app/orch_lifecycle.py RunLifecycle             — moved
helao/hexagon/app/orch_dispatch.py  DispatchRunner           — moved (B3b)
helao/hexagon/app/orch_status.py    StatusIngester           — moved (B3b)
helao/hexagon/app/orch_monitor.py   ServerMonitor            — moved (B3b)
```

`OrchHost` subclasses `HelaoFastAPI` as `ActionHost` does, and answers to `host.orch is host` for
the same reason `host.base is host` — `orch_api` reaches `self.orch.<member>` at 60 sites and
deployment code follows that spelling. One object, two names, no indirection invented.

Ports consumed: the existing `ORCH_REQUIRED` set — `config`, `logging`, `clock`, `transport`,
`state_persistence`, `status`, `health`. Unchanged; B3 adds no port.

---

## 4. Gates

**B3a**

1. **Member ratchet** — `OrchHost` covers the measured 135-member contract, with an explicit,
   justified exclusion list. Seeded from the measurement in §1.1 *before* host code is written.
   Fails when the gap grows, not while it merely persists (B1's ratchet design, which worked).
2. **Live `/openapi.json` diff** against a legacy orchestrator — 72 routes, same paths, methods,
   tags and parameter schemas. Not the hand-written checklist: B1 measured that stale (9 routes
   listed, 19 live, and the listed methods were wrong).
3. Queue-mutation round trips: append / prepend / insert / move / remove / drop for all three
   containers, against the paged-index trap already documented in CLAUDE.md — queue handlers add
   the page offset, history must not.
4. `export_queues` / `import_queues` round trip, including a `queues.pck` written by legacy.

**B3b**

5. Concurrency suite (`test_concurrency_live.py`) green against the native host.
6. GM-1…GM-5 at 0 diffs, captured from a **clean root** with the fixed `assert_fresh` — the
   GM-4 baseline contamination found in B1 came from exactly this check missing `RUNS_DIAG`.

   **The program spec says GM-1…GM-6 here and for B1. There is no GM-6**: `harness/capture.py`
   defines five scenarios and `SCENARIOS` has five keys. B1 was gated on GM-1…GM-5 in practice,
   at 0 diffs each. Either the program spec's two rows are stale or a sixth scenario was intended
   and never written; B3a should settle which rather than carry the citation forward. If a GM-6
   is wanted, the honest place to add it is B3a, where the gate is cheap, not B3b.
7. WS frame parity on `/ws_status`, `/ws_data`, `/ws_live`, `/ws_globstat`. The `OrchAPI` and
   `BaseAPI` encoding families are independently frozen (Amendment 2 §3): a native host reproduces
   *its family's* bytes and must not converge them.
8. Estop drill: estop mid-experiment, artifacts land `[finished, estopped]`, deferred promotion
   past the 30 s child-dir window, `clear_estop` recovers.

**Not a gate, and stated so it is not mistaken for one:** no station hardware. B3 is Linux-
verifiable end to end. hte is B5.

---

## 5. Risks

**The 135-member contract is measured from static attribute access, so it is a lower bound.**
Anything reached through `getattr`, a config-named string, or a deployment module the scan did not
read is absent from it. Mitigation: the ratchet is the floor, `/openapi.json` and the concurrency
suite are the ceiling, and B1's lesson stands — a member missing from a native host fails inside a
caught block far more often than it raises.

**`orch_dispatch` is 1,337 lines with 58 back-reference members and it owns the loop.** It is the
single largest correctness surface in the program. D-B3.3 isolates it in B3b for that reason.

**The reducer cut-over (D-B3.2) changes what drives production on five stations.** The graft is
live at amts, uvis4, note1, ccs2 and eche10 today. The cut-over is a same-commit swap, so there is
no window where both drive the loop, but there is also no incremental rollout: the gate has to be
the concurrency suite plus GM, not a station.

**~~Deployment code reads `app.orch`.~~ Measured: it does not.** Zero files under
`helao/deploy/` touch `.orch` — hte and all three private deployments. The only direct
constructors are tests and `MicroOrch`, which is a separate mechanism under `helao/core/runners/`
and is out of scope. The `host.orch is host` property therefore covers `orch_api`'s 60 internal
sites and nothing else needs it. Risk closed before B3a starts.

**`Orch` extends `Base`, but `OrchAPI` does not extend `BaseAPI`.** The native shape must
reproduce that asymmetry: `OrchHost(ActionHost)` inherits the Base half (23 of the 135 members
come free), while the WS encoding stays the `OrchAPI` family — a plain dict on `/ws_status` where
the action family sends an `ActionModel`. `ActionHost` already registers all three WS routes, so
`OrchHost` **must override them** rather than inherit, or B3b silently ships the wrong family to
every Bokeh visualizer and Reflex panel.

---

## 6. What B3 does not do

- Does not delete `orch.py`, `orch_api.py`, or any legacy engine file. B7 does.
- Does not port a deployment. B4 (test), B5 (hte), B6 (private) do.
- Does not change the reducer's decisions, only what drives it.
- Does not touch `helao/ui/` — the operator UIs consume `OrchBackend`, which is already the
  abstraction both Bokeh and Reflex sit behind.
