# Legacy Separation — Program Design

**Date:** 2026-08-14
**Relates to:** `docs/superpowers/specs/2026-07-16-framework-hexagonal-rewrite-design.md` (master
spec), as amended by `2026-08-04-hexagonal-rewrite-ui-amendment.md` (Amendment 1) and
`2026-08-08-hexagonal-rewrite-amendment-2.md` (Amendment 2).
**Baseline:** `unstable` @ `b6a475a0`.
**Checkpoint:** `freeze/pre-legacy-removal_2608` in the parent repo and in each private
deployment repo, taken at this baseline. It is the rollback for the whole program.
**Privacy rule:** inherited from the master spec §8 preamble. The private deployments are
**Deployment-A/B/C** only.

---

## 1. What this program is, and the measurement that defines it

Five stations run configs whose servers carry `deployment: hexagon`. The intent of this
program is to remove everything that is not hexagon: the legacy engine, the paired legacy
configs, the coexistence machinery, and the parity tests that lose their reference once there
is only one implementation left.

The first measurement changes what that sentence means.

**`deployment: hexagon` is a graft over the legacy engine, not a replacement of it.**
`helao/hexagon/app/factory.py`:

- `makeActionApp` (factory.py:91) imports the legacy deployment module and calls its
  `makeApp`, which constructs `BaseAPI`/`Base` from `helao/core/servers/base_api.py`. The
  graft then rebinds `contain_action` and `meta_writer` at startup.
- `makeOrchApp` (factory.py:60) does `from helao.core.servers.orch_api import OrchAPI`,
  constructs it, and grafts the hexagon reducer loop onto the live legacy `Orch`.
- `makeVisApp` (factory.py:158) imports the legacy Bokeh module unmodified.
- `active_graft.py` states it directly: *"legacy BaseAPI keeps hosting the routes"*, *"NO
  legacy source is modified"*.

So `base.py` (1545 lines), `base_api.py` (910), `orch.py` (879), `orch_api.py` (1015) and
their 20 satellites are **the running engine on every hexagon station today**. What the graft
has made native is the write path (artifact store, data sink, meta writer), the WS publish
bridge, and the dispatch reducer. The *hosting* — routes, status queues, live buffer, action
queue, the `Active` surface — is still legacy.

The consequence is that separation is not a deletion project. It is the completion of the
rewrite. Deleting the 24 engine files requires first building the hexagon-native hosts that
replace them, and porting the 49 deployment server modules that construct `BaseAPI` today.

## 2. Measured surface

| area | size |
|---|---|
| legacy engine (`base*.py`, `active_*.py`, `orch*.py`) | 24 files, 11,123 lines |
| deployment modules constructing the engine | 49 (24 hte, 9 test, 8 Deployment-A, 6 Deployment-B, 2 Deployment-C) |
| `helao/hexagon/adapters/legacy/` | 17 files |
| `helao/core/tests/` | 95 files, 37,363 lines |
| `harness/` parity rig | 39 files, 7,468 lines |
| paired legacy station configs | 7 hte `.yml` plus the `test` golden rig |

The deployment coupling to the engine is narrow. Across all 49 modules the only engine
imports are `BaseAPI` (46 sites), `action_version`, `Base`/`Active`/`Executor` (11), and
`OrchAPI` (1). Everything else those modules import from `helao/core/servers/` is UI —
`vis` (28), `vis_subscriber` (22) — which survives the program.

The contract a replacement must satisfy is checked in at
`helao/hexagon/tests/checklists/hte/_member_surface.md`, `_baseapi_system_surface.md`, and
7,128 lines of per-server route JSON.

**One of those three is not trustworthy, measured 2026-08-14 while speccing B1.**
`_baseapi_system_surface.md` lists 9 routes and marks 5 of them `GET`. A live capture from a
running action server shows **19 routes, every one `POST`** — it omits eight and mis-states
the method on five. Its own note says the runtime `/openapi.json` cross-check was "deferred to
P3b/P3e"; that deferral never closed. **Every phase gate in this program diffs a live
`/openapi.json`, not that file**, and each phase re-freezes it from its own capture. The
per-server route JSON and `_member_surface.md` are AST- and grep-derived and are not affected.

## 3. Decisions

These are settled and are not re-litigated by a sub-project plan.

- **D-S1 — Removal gate.** The five verified stations plus `freeze/pre-legacy-removal_2608`
  are sufficient. Legacy does not stay in-tree waiting for the remaining stations; a station
  that breaks recovers from the freeze branch. The freeze branch is protected in the parent
  repo by the pre-existing `freeze/*` rule; the private repos' rules are added out of band.
- **D-S2 — The parity harness survives.** `harness/` is re-baselined against hexagon output
  and kept as a self-regression suite, along with the frozen endpoint checklists. Only the
  legacy-capture paths and the A-versus-B parity framing are removed. The differ is what
  catches an artifact-layout regression before a station does.
- **D-S3 — The UI survivors move to `helao/ui/`.** `palette`, `bokeh_theme`, `vis`,
  `vis_subscriber`, `reflex/`, `data_browser/`, `operator/`, `io_control*`, `motion_control*`
  leave `helao/core/servers/` for a package grouped by stack. `helao/core/` keeps `models`,
  `drivers`, `rpc`, `runners`, `error`.
- **D-S4 — Configs return to bare prefixes.** `eche10_hex.py` becomes `eche10.py` once the
  paired legacy `.yml` is gone, matching the in-place flip Deployment-A and Deployment-B
  already did. This changes launch commands, `STATES` pid/queue filenames, and station
  runbooks; that cost is accepted rather than carrying a `_hex` suffix that distinguishes
  nothing.
- **D-S5 — `adapters/legacy/` becomes `adapters/shared/`.** Measured, it imports no engine
  code at all — only `helao/helpers`, `helao/core/error` and the driver ABC — while
  `hexagon/app/factory.py` and three native adapters depend on it in production. The name is
  wrong, not the code. Renaming it is what stops a later reader deleting a live dependency.
- **D-S6 — Clean-room hosts.** The native `ActionHost`/`OrchHost` are written from the domain
  and ports, and the 49 deployment modules are ported to the new registration API. The
  alternatives considered were a native host exporting the legacy names (so deployment
  modules change one import line) and relocating the engine into the hexagon tree to
  decompose later. Both are cheaper; neither produces the target architecture, and the
  second leaves the legacy code alive under a new path.

## 4. Decomposition

Each sub-project gets its own design spec and implementation plan. B1–B3 must land before B4,
which is their first real consumer.

| # | sub-project | scope | gate |
|---|---|---|---|
| **B0** | UI re-home | the survivors listed in D-S3 move to `helao/ui/`; 122 parent files / 452 occurrences, plus 6 / 9 / 8 files in Deployment-A/B/C | Linux: full suite, palette sweep, bundle rebuild, headless render |
| **B1** | `ActionHost` + registration API + native action session | the native replacement for `BaseAPI`/`Base` and for `Active`, plus the explicit-context registration API and a native `ExecutorRunner`; ports the `test` deployment as its proof. **Absorbs the sub-project this table originally listed as B2** — `setup_and_contain_action` is a host method returning an `Active`, so the seam would have run through the middle of one contract. See `2026-08-14-B1-actionhost-design.md` | live `/openapi.json` diff (**not** the hand-written checklist — measured stale, see below); WS frame parity; GM-1…GM-6; concurrency suite |
| ~~B2~~ | *retired* | folded into B1 | — |
| **B3** | `OrchHost` | replace `OrchAPI` + `Orch` over the existing reducer (`app/dispatch_loop.py`, `app/orch_effects.py`, `domain/orchestration.py`). Largest single item: `orch_dispatch` 1337 + `orch_api` 1015 + `orch` 879 + 7 satellites | concurrency suite; orch route checklist; GM-1…GM-6 |
| **B4** | port `test` deployment | 9 action + 4 visualizer modules onto the new API; goldens re-baseline here | Linux, full harness, no hardware |
| **B5** | port hte | 24 action + 16 visualizer + orchestrator + operator, station by station | per station: route checklist, smoke sequence, on-station golden diff |
| **B6** | port Deployment-A/B/C | 8 / 6 / 2 action modules | per station |
| **B7** | delete and rename | 24 engine files, the graft machinery, `helao/deploy/hexagon/` shims, paired legacy configs; D-S4 and D-S5 renames; strip the parity tests that lose their reference | full suite; endpoint checklists re-frozen |

**B0 is first** because it is mechanical, independent of the host work, and touches all four
repos — far cheaper to land while nothing else is in flight than to merge across later. It
also moves the survivors out of `helao/core/servers/` before that directory is dismantled,
so B7 deletes a directory rather than picking through one.

## 5. What this program does not change

- No locked decision of the master spec §3, and no artifact-inventory row of §5.
- No WS payload shape. Amendment 2 §3's rule stands: the `BaseAPI` and `OrchAPI` encoding
  families are independently frozen, and a native host reproduces its family's bytes rather
  than converging them.
- No behaviour visible on disk or on the wire. The post-parity backlog (the `set_error`
  quirk, the finish-drain window, the 0.3 s per-client pacing sleep, `/ws_globstat`'s dead
  sender, `params.limit_vis`) is dispositioned in B7, not opportunistically during a port.

## 6. Deferred past the programme

Work this programme deliberately does not do, recorded here so it is not rediscovered as a
surprise. Unlike the post-parity backlog above, these are not B7 items — they wait until the
migration is finished.

### A quarantine state for records that can never sync

**There is none today, and that is by design as far as it goes.** A record whose sync raises
is logged by the `syncer` worker and dropped; the yml stays in `RUNS_FINISHED`; and
`sweep_pending` re-enqueues everything in `RUNS_FINISHED` at every SYNC start. So a record
that cannot succeed fails identically at every launch, forever, leaving only a log line. There
is no failure marker, no strike count, and no retry cap on that path — the cap that exists is
on S3 upload attempts, not on a record that throws.

The design rationale holds: **the sweep cannot distinguish "will never succeed" from "was
interrupted"**, and the second case is the one it exists to recover. Quarantining on first
failure would silently strand work that a restart would have completed.

What makes it worth revisiting is that the failure is invisible until someone reads the logs.
The 2026-08-15 case — a station whose run trees moved one level deeper, stranding three records
behind absolute paths recorded in their sidecars — had been failing at every startup since
July and surfaced only because an operator happened to look. That root cause is fixed
(`fix(sync): record sidecar paths relative to the record`), but the *class* is not: any
never-succeeding record behaves the same way.

Shape to consider, not yet decided:

- a `RUNS_FAILED` tree, moved into after N consecutive failures of the same record, so the
  backlog is visible in the filesystem rather than only in logs;
- or a strike count in the `.prg`, which keeps the record in place and needs no new tree;
- either way, a route that lists quarantined records and one that returns them to
  `RUNS_FINISHED` after a repair.

The trade to settle first is what N should be and whether "consecutive" is measured per
process or persisted — a strike count that resets on restart counts restarts, not failures.

**Why after the migration and not during.** B7 deletes the legacy engine, and the syncer is
one of the few components both engines share. A behavioural change to it during the port would
land in the middle of the one comparison the programme depends on: a station's before/after run
tree, diffed across a git revision. Changing when records move between trees changes exactly
that diff.
