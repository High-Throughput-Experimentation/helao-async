# B7a — Relocate the engine survivors

**Date:** 2026-09-29
**Program:** Legacy separation (`2026-08-14-legacy-separation-program-design.md`), sub-project B7, first of three parts
**Branch:** `feat/b7a-relocate-engine-survivors` off `origin/unstable` `bf4fd20f`, merged by PR
**Status:** design approved; plan follows

## 1. What B7a is, and the measurement that shapes it

The program's B7 row reads "delete and rename": the engine files, the graft machinery, the
`helao/deploy/hexagon/` shims, the paired legacy configs, the D-S4/D-S5 renames, and the parity
tests that lose their reference. The B5 station-gate table is now full — eleven rows, seven on
evidence, four waived — so B7 may start. Measured on `bf4fd20f`, though, the engine cannot simply
be deleted: eleven production files outside `helao/core/servers/` still import from it, and two of
the imports are the monkeypatch points the orchestrator golden master rebinds. Deleting the
engine in one step would couple a 6,914-line removal to a relocation of live code and a
station-visible rename, and a failure anywhere in that would be indistinguishable from a failure
everywhere.

B7 therefore splits into three sub-projects, each with its own spec, plan, and branch:

- **B7a — relocate** (this spec). Every symbol native code still borrows from
  `helao/core/servers/` moves to exactly one new home outside it. Behaviour-neutral by
  construction: the same functions run, imported from a different path.
- **B7b — delete.** `helao/core/servers/` goes, with the graft machinery
  (`helao/hexagon/app/active_graft.py`, `sync_graft.py`, the graft paths of
  `factory.makeOrchApp`/`makeActionApp`), the parity tests that lose their reference, the
  checklists re-frozen, and each post-parity backlog item dispositioned on its own.
- **B7c — rename.** Station-visible: D-S4 (`*_hex` configs to bare prefixes, paired legacy ymls
  deleted, `helao/deploy/hexagon/` shims deleted) and D-S5 (`adapters/legacy/` to
  `adapters/shared/`). Blocked on a private deployment whose remote is currently disabled; it
  imports `adapters.legacy.calibration_store` and cannot be repointed until that remote is back.

B7b and B7c get their own specs. This one covers B7a only.

The measurement that governs B7a is the importer list in §2. It is short (eleven files, of which
two are B7b's graft machinery and one is the parity harness), and every entry falls into one of
four kinds — a re-export seam, a re-export of something that already lives elsewhere, a real
definition, or an annotation. Each kind has one treatment (§3), so the work is a table, not a
design.

## 2. Measured surface

All numbers measured on `bf4fd20f` in the B7a worktree unless stated. Where a figure differs from
the one carried into this spec's brief, the brief's figure is given in brackets.

**The engine.** `helao/core/servers/` holds 17 `.py` files (16 modules plus an empty `__init__.py`),
6,914 lines. The program spec's B7 row says 24 files; seven were removed
between the program spec and now (B0's UI re-home and the B5 splits). B6 left the
deployment-construction ratchet (`helao/hexagon/tests/test_external_composition_contract.py`)
at 0 for the tracked deployments, with `MAX_UNPORTED_PRIVATE_MODULES = 13` as the private
ceiling.

**Production importers outside the engine** — AST sweep of `git ls-files '*.py'`, excluding
`helao/core/servers/`, `helao/deploy/`, and test files; 295 files swept, 11 import the engine:

| file | what it imports | where | kind |
|---|---|---|---|
| `helao/hexagon/app/orch_host.py` | `orch_unpack` (module, top); `Active` (`TYPE_CHECKING` only); `orch_api`: `WaitExec`, `checkcond`, `_histories_payload`, `_history_page_payload`, `_queue_object_payload`, `_queue_counts`, `_set_step_flag`, `_status_summary_payload`, `_step_flags_payload` (function-local, lines 574, 654, 1128) | real + annotation | B7a |
| `helao/hexagon/app/orch_dispatch.py` | `orch_global_params.apply_from_globals` / `collect_to_globals` (top, line 121); `orch.async_action_dispatcher` (line 900) and `orch.PLATE_API` (lines 1260, 1284), both function-local by design | real + seam | B7a |
| `helao/hexagon/app/orch_estop.py` | `orch.async_action_dispatcher` (line 107), `orch.move_dir` (line 259), function-local | seam | B7a |
| `helao/hexagon/app/orch_lifecycle.py` | `base.Active` — **a module-top runtime import** (line 44), used only in annotations (lines 266, 271, 406) [brief: "annotation only" — true of the uses, not of the import]; `orch.move_dir` (lines 65, 127), function-local | annotation + seam | B7a |
| `helao/hexagon/app/orch_queues.py` | `orch.sanitize_sequence_label` (lines 134, 195), function-local | real | B7a |
| `helao/hexagon/app/action_host.py` | `base_status.guarded_replace` (line 426, function-local); `base_status` itself only re-exports it from `helao/core/models/status_transitions.py:55` | re-export | B7a |
| `helao/hexagon/app/endpoint_overlay.py` | `base_api.BaseAPI` (top, line 39), annotations only (lines 56, 69, 110) | annotation | B7a |
| `helao/helpers/server_api.py` | `base_api.ActionAPIRoute`, imported inside `HelaoFastAPI.__init__` (line 71) and installed as `self.router.route_class` (line 73) | structural | B7a |
| `helao/hexagon/app/active_graft.py` | `base.Active` (top, line 26), real use | graft | **B7b** |
| `helao/hexagon/app/factory.py` | `orch_api.OrchAPI` inside `makeOrchApp` (line 79), the graft path | graft | **B7b** |
| `harness/ws_frames.py` | `base_status.StatusBroadcaster` (top, line 88), constructed at line 288 to encode the legacy `OrchAPI` WS frame bytes that the parity tests compare against | parity reference | **B7b** — *not in the brief's list* |

`harness/ws_frames.py` is the one importer the brief missed. It is not relocatable: its purpose is
to produce the legacy encoder's bytes, so it dies with the engine (D-S2 re-baselines the harness
against hexagon output; B7b does that). B7a's ratchet carries it on a shrink-only allowlist
(§6) rather than pretending it does not exist.

**The seams.** `helao/core/servers/orch.py` re-exports three names purely so tests have one
place to patch, each with a `# noqa: F401` saying so: `async_action_dispatcher` (real home
`helao/helpers/dispatcher.py`, line 42–44), `move_dir` (real home `helao/helpers/yml_tools.py`,
line 52–54), `PLATE_API` (real home `helao/core/servers/orch_unpack.py:47`, line 37–39).

**Tests that patch or import a seam** — every `setattr`/`monkeypatch.setattr` on an engine
*module* or `import helao.core.servers.orch`, measured by grep:

| test | what it does | how it runs |
|---|---|---|
| `helao/core/tests/test_orch_dispatch_golden_master.py` | binds `orch_module` (line 108); rebinds `orch_module.async_action_dispatcher`, `.move_dir`, `.PLATE_API` (lines 441–464) | standalone script, `--check` mode diffs 9 scenarios (S1–S9) byte-for-byte against the frozen `.omc/artifacts/p5/baseline_S0/`; default mode also runs a double-capture determinism check |
| `helao/core/tests/unit_test_orch_lifecycle.py` | binds `orch_module` (line 35); rebinds `orch_module.move_dir` (lines 130–135) | standalone script |
| `helao/hexagon/tests/test_dispatch_lock_not_held_across_post.py` | `monkeypatch.setattr(orch_mod, "async_action_dispatcher", fn, raising=True)` (lines 86–88) | pytest |
| `helao/core/tests/test_standalone_operator.py` | `from helao.core.servers.orch import sanitize_sequence_label` (line 869, function-local) | standalone script |

Nothing else patches an engine module. `test_dispatch_loop.py:158` and
`test_orch_dispatch_golden_master.py:341/351` `setattr` on an `Orch` *instance*, and
`test_micro_orch_finish.py:143/164` patches an `orch.dispatcher` instance; none of those name a
module and none move.

**Test importers overall.** 33 files under test directories import the engine [brief: 34]; 22
in `helao/core/tests/`, 11 in `helao/hexagon/tests/` (one of them `native_fixtures.py`). All but
the four above are source-parity pins, golden masters, or fixtures that construct the legacy
classes on purpose — B7b's problem, not B7a's.

**What importing the native hosts pulls in today.** In a fresh interpreter,
`import helao.hexagon.app.action_host, helao.hexagon.app.orch_host` leaves exactly two engine
modules in `sys.modules`: `helao.core.servers` and `helao.core.servers.orch_unpack`. That is the
*import-time* number. The *construction-time* number is larger — `HelaoFastAPI.__init__` imports
`base_api`, `OrchHost.__init__` imports the collaborators at lines 234–239 (and with them
`orch_lifecycle`'s top-level `base`), and the route-registration blocks import `orch_api` — and
it has not been measured. The plan's first task measures it; anything it finds that is not in
§4's map is added to the map before any move.

**A duplicate that already exists.** `helao/hexagon/domain/global_params.py` (90 lines) is a
byte-identical port of `orch_global_params.py` with one difference: its `LOGGER` is
`logging.getLogger(__name__)` rather than `helao_logging`. It has one test
(`helao/hexagon/tests/test_global_params.py`) and **no production caller**. It is not the
destination (§3, D-B7a.5): a stdlib logger named `helao.hexagon.domain.global_params` has no
HELAO handler — `make_logger` binds handlers to a named logger with `propagate = False` and never
to the root (`helao/core/servers/CLAUDE.md`) — so the fold-in/fold-out log lines would vanish
from the ORCH log. That is a behaviour change, and B7a makes none.

**Route registration order.** `HelaoFastAPI.__init__` registers no routes — only the
`startup`/`shutdown` event handlers (lines 100–140 of `server_api.py`). `ActionHost.__init__`
rebinds `self.router.route_class = bind_action_route(self)` at line 152, thirteen lines after
`super().__init__` returns at line 138–144, and registers its first route at line 326. Nothing
is registered in between. In the two legacy subclasses the first route follows `super().__init__`
by 44 lines (`OrchAPI`, 183 to 227) and 51 lines (`BaseAPI`, 650 to 701), again with nothing
registered in between. `OrchAPI` has nine `tags=["action"]` endpoints and `BaseAPI` five; both
depend on `ActionAPIRoute` being installed.

## 3. Decisions

**D-B7a.1 — Move and repoint; never duplicate.** Each real definition moves to exactly one new
home. The engine module it came from keeps a one-line re-export (`from <new home> import <name>
# noqa: F401`) so the engine and its 33 test importers work unchanged until B7b deletes them.
Native code imports only from the new home. No definition exists in two places at the end of
B7a; the domain copy of the global-params fold (§2) is retired the same way (D-B7a.5).

**D-B7a.2 — A seam is read at call time from the module that owns it.** Native code never binds
a seam name at import time. It imports the owning module — `from helao.helpers import
dispatcher`, `from helao.helpers import yml_tools`, `from helao.hexagon.app import orch_unpack` —
and reads the attribute where it is used: `dispatcher.async_action_dispatcher(...)`,
`yml_tools.move_dir(...)`, `orch_unpack.PLATE_API`. That gives each seam exactly one patch
point, the real one, and it is the same point in production and under test. The three
`# noqa: F401` re-exports in `orch.py` stay for the engine's own callers and are deleted by
B7b. The four tests in §2 move their patches to the real modules. The rule is enforced by the
red-check (§5), not by review.

**D-B7a.3 — Annotations name the native type.** `Active` in `orch_host.py` and
`orch_lifecycle.py` becomes `ActionSession` (`helao/hexagon/app/action_session.py:52`), the
type those collaborators actually receive from `OrchHost`. `BaseAPI` in `endpoint_overlay.py`
becomes `ActionHost`, the only app that calls it. `orch_lifecycle.py`'s import moves under
`TYPE_CHECKING`, as `orch_host.py`'s already is. No runtime change: annotations are not
evaluated in these modules.

**D-B7a.4 — `HelaoFastAPI` stops knowing about `ActionAPIRoute`.** `server_api.py` is a helper;
it should not import the engine. The install moves to the two classes that need it:
`BaseAPI.__init__` and `OrchAPI.__init__` each set `self.router.route_class = ActionAPIRoute`
immediately after their `super().__init__` returns [brief: `BaseAPI` alone — `OrchAPI` has nine
`tags=["action"]` endpoints and would silently lose their `ActionInvocation` wrapping].
`ActionHost` already installs its own bound `ActionRoute` at the same point and is untouched
except for the docstring at line 28 and the comment at line 145, which describe the import that
no longer runs. §2 measured that no route is registered before any of the three rebinds, so
every route in every host is still built by the class its host chose.

**D-B7a.5 — One copy of the global-params fold, in `app/`.** `orch_global_params.py` moves
verbatim to `helao/hexagon/app/orch_global_params.py`, `helao_logging` `LOGGER` included.
`helao/hexagon/domain/global_params.py` is deleted and `test_global_params.py` repointed at the
app module; its assertions are about fold semantics and do not depend on the logger. Leaving the
domain copy would mean three copies at the end of B7a (engine shim, app, domain) of a function
that has one caller.

**D-B7a.6 — Nothing is deleted from the engine, and nothing station-visible changes.** Configs,
server keys, endpoint paths, log wording, file layouts, and the golden-master byte traces are all
identical before and after. B7a needs no station gate; that is the reason it exists as a
separate sub-project.

## 4. Destination map

| symbol | today | kind | destination |
|---|---|---|---|
| `async_action_dispatcher` | `helpers/dispatcher.py`, re-exported by `orch.py` | seam | native callers `from helao.helpers import dispatcher`, call `dispatcher.async_action_dispatcher(...)`; tests patch `helao.helpers.dispatcher` |
| `move_dir` | `helpers/yml_tools.py`, re-exported by `orch.py` | seam | same pattern via `helao.helpers.yml_tools` |
| `PLATE_API` | `orch_unpack.py:47`, re-exported by `orch.py` | seam | moves with `orch_unpack`; read as `orch_unpack.PLATE_API` at call time |
| `guarded_replace` | `core/models/status_transitions.py:55`, re-exported by `base_status.py:70` | re-export | `action_host.py:426` imports from `status_transitions` |
| `orch_unpack` (`unpack_sequence`, `get_sequence_codehash`, `verify_plate_in_params`, `PLATE_API`) | `core/servers/orch_unpack.py`, 114 lines; imports only `models.orchstatus`, `helpers.plate_api`, `helpers.premodels`, `helao_logging` | real | `helao/hexagon/app/orch_unpack.py`; engine module becomes four re-export lines |
| `apply_from_globals`, `collect_to_globals` | `core/servers/orch_global_params.py`, 101 lines; imports only `helao_logging` | real | `helao/hexagon/app/orch_global_params.py` (D-B7a.5) |
| `sanitize_sequence_label` | `orch.py:60`, 5 lines | real | `helao/hexagon/app/orch_queues.py`, its sole native consumer; `orch.py` re-exports |
| `_histories_payload`, `_history_page_payload`, `_status_summary_payload`, `_step_flags_payload`, `_set_step_flag`, `_queue_counts`, `_queue_object_payload` | `orch_api.py:38–152`; each takes `orch` and reads queues, histories, `status_summary`, `step_thru_*` | real | new `helao/hexagon/app/orch_payloads.py`; `orch_api.py` re-exports all seven. `_prepend_sequences` (line 125) stays: only `OrchAPI` and its test use it |
| `WaitExec`, `checkcond` | `orch_api.py:962–1015`; depend on `helpers.executor.Executor`, `HloStatus`, `ErrorCodes`, `LOGGER` — nothing from the engine | real | new `helao/hexagon/app/orch_wait.py`; `orch_api.py` re-exports both |
| `Active` | `base.py` | annotation | `ActionSession` (D-B7a.3) |
| `BaseAPI` (in `endpoint_overlay.py`) | `base_api.py` | annotation | `ActionHost` (D-B7a.3) |
| `ActionAPIRoute` | `base_api.py:376`, installed by `HelaoFastAPI.__init__` | structural | `HelaoFastAPI` stops installing it; `BaseAPI.__init__` and `OrchAPI.__init__` install it (D-B7a.4) |
| `StatusBroadcaster` (in `harness/ws_frames.py`) | `base_status.py:79` | parity reference | stays; allowlisted in the ratchet until B7b re-baselines the harness |
| `Active`, `OrchAPI` (in `active_graft.py`, `factory.py`) | `base.py`, `orch_api.py` | graft | stays; allowlisted until B7b deletes the graft |

New files: two (`orch_payloads.py`, `orch_wait.py`). Moved files: two (`orch_unpack.py`,
`orch_global_params.py`). Deleted files: one (`domain/global_params.py`). The four tests in §2
are edited in place; the golden master's `orch_module` binding becomes three bindings
(`dispatcher`, `yml_tools`, `orch_unpack`) and its rebind/restore lines 441–464 follow.

Import direction is already engine → `helao.hexagon.app` (`orch.py` lines 30–36 import seven
collaborators from there), so the engine shims importing from `helao/hexagon/app/` introduce no
new cycle. `helao/hexagon/app/__init__.py` is a docstring.

## 5. The patch-seam rule and the red-check

A seam that native code binds at import time is a seam that cannot be patched after the fact,
and a seam left on the old module is one that patches nothing. Both failures are silent: the
golden master would still run, still produce nine traces, and still diff clean against a
baseline that was itself captured through an unpatched path — the comparison would prove
nothing. The red-check turns that into a loud failure and is a gate, not a review item.

**Red-check, dispatch golden master.** With the four native seam reads repointed and the test
still patching `helao.core.servers.orch`:

1. Run `test_orch_dispatch_golden_master.py --check`. It **must fail** — the stubs are on a
   module nothing reads, so the real `async_action_dispatcher` is called against servers that do
   not exist and the traces diverge or the run errors. A pass here means native code is still
   reading the old seam, or the test never intercepted anything.
2. Move the patches to `helao.helpers.dispatcher`, `helao.helpers.yml_tools`,
   `helao.hexagon.app.orch_unpack`. Run `--check` again: all nine scenarios `PASS`, byte-identical
   to `baseline_S0/`. Run the default mode: the double-capture determinism check passes.

The same two steps for `unit_test_orch_lifecycle.py`'s `move_dir` stub (fail on
`helao.core.servers.orch`, pass on `helao.helpers.yml_tools`) and for
`test_dispatch_lock_not_held_across_post.py` (`raising=True` on the old module still finds the
re-export, so the red step is the assertion failing, not the patch).

`baseline_S0/` is never regenerated. If a scenario diffs, the move is wrong.

## 6. The ratchet

New test `helao/hexagon/tests/test_engine_import_ratchet.py`, two halves, both at 0 before merge.

**Static half.** `git ls-files -z '*.py'` (the same source of truth
`test_no_legacy_app_attribute.py:40` uses; it lists the tracked deployments `hte` and `test`
and never a private one, so no deployment exclusion is needed), minus `helao/core/servers/` and
test files (`/tests/` directories, `test_*.py`, `unit_test_*.py`). Parse each with `ast`; any
`Import` or `ImportFrom` whose module is `helao.core.servers` or starts with
`helao.core.servers.` is an offender, wherever it sits — module top, function body, or under
`TYPE_CHECKING`. The sweep must visit more than 500 files (600 today, measured on `bf4fd20f`) or the test fails as
vacuous. A frozen allowlist holds the B7b files — `helao/hexagon/app/active_graft.py`,
`helao/hexagon/app/factory.py`, `harness/ws_frames.py` — and is shrink-only: an allowlisted file
that no longer imports the engine fails the test, so B7b cannot leave a stale entry behind. The
assertion is `offenders - allowlist == set()`.

`test_boundaries.py` already bans the engine from `adapters/native/`; this ratchet extends the
ban to everything outside the engine and is the test B7b runs first.

**Runtime half.** In a fresh subprocess (`sys.executable`, worktree on `PYTHONPATH`), build an
`ActionHost` and an `OrchHost` under a minimal `helao_cfg` — the `goldenhex` server entries are
enough — and assert `[m for m in sys.modules if m.startswith("helao.core.servers")] == []`. A
subprocess because the parent pytest process already has the engine loaded by other files.
Today the import-time count is 2; the construction-time count is unmeasured and is the plan's
first task. Anything that count turns up which §4 does not cover is added to §4 before it is
moved — a transitive import through a helper is a real importer, not noise.

Private deployments are out of scope for both halves (D-B6.1: one gate per repo, living in that
repo). The tracked deployments are swept by the static half through `git ls-files`, and B6's
`test_external_composition_contract.py` keeps its own ceiling.

## 7. Gates

Linux only; no hardware. Run in this order, each on the branch head.

1. **Ratchet at 0, both halves** — `pytest helao/hexagon/tests/test_engine_import_ratchet.py`,
   static offenders equal to the allowlist exactly, runtime `sys.modules` empty of the engine for
   both hosts.
2. **Dispatch golden master byte-identical** — `--check` mode, nine of nine `PASS` against
   `baseline_S0/`; default mode's determinism check passes; and the red-check of §5 recorded as
   having failed first, for all three tests.
3. **Route checklists, no new diffs** — the B5 `extract_routes` checklists compared with the
   frozen JSON. The `andor` checklist has been failing on `unstable` since PR #217 (`366995c8`,
   `/ANDOR/calibrate_wl` and its siblings; expected delta recorded in the B5 runbook at
   "Expected delta: `/ANDOR/calibrate_wl`"). B7a leaves it failing and records it; it is not
   B7a's to fix. Every other checklist: 0 diffs.
4. **Full `python run_tests.py`** — 297 files. The set of failing files must equal today's
   baseline of 12: the harness freeze and the hte checklist (both the `andor` drift), five
   `bruker_gadds`/capture files that need GSASII, two test-issue files in a second private
   deployment's tree, and three path/ledger/sources assertions in a private deployment. Any file
   not in that set blocks. `ENV` results are not failures.
5. **`python run_unit_tests.py` PASS; `pyright` no new errors** on every changed file, compared
   against the same file on `bf4fd20f`.
6. **Launch smoke** — `python launch.py goldenhex` (ORCH through the `deployment: hexagon` shim, which builds a native `OrchHost`; SIM and SYNC
   native from the test deployment): every server binds, `supervise_early_exits` reports no child
   exiting in 90 s, one `goldenhex` sequence reaches `RUNS_FINISHED`, `CTRL-x` tears the group
   down and `STATES/pids_goldenhex_.pck` is cleared. This gate exists because D-B7a.4 touches the
   construction of every host in the process, native and legacy, and a route class that fails to
   install shows up only when a request arrives.
7. **`black`** on every changed file immediately before `git add`.

## 8. Risks

- **A seam left on the old module intercepts nothing.** Loud, by the red-check: the golden
  master fails when patched on `helao.core.servers.orch` after the repoint. If it passes,
  stop — either a native read was missed or the scenario never exercised the seam.
- **A test that was never really intercepting.** The same red-check catches it from the other
  side: a test whose "fail on old seam" step does not fail was not testing what it claimed. The
  plan records the failing output for each of the three tests before recording the pass.
- **A transitive engine import the runtime ratchet finds that §4 does not cover.** Import-time
  is 2 modules; construction-time is unknown. The plan measures before moving, and adds to the
  map rather than to the allowlist — the allowlist is for B7b's files only.
- **`ActionAPIRoute` removal reaching a route registered before a rebind.** Measured not to
  happen today (§2: no route between `super().__init__` and the rebind in any of the three
  hosts), but nothing enforces it. The plan adds one assertion to the runtime ratchet: after
  construction, every `route.__class__` on each host is the class that host installed. On
  `OrchAPI` and `BaseAPI` it is `ActionAPIRoute`; on `ActionHost` it is the bound
  `BoundActionRoute`.
- **A moved module's logger changing its name.** `make_logger(__file__)` keys on the file, so a
  module that moves logs under the same stem (`orch_unpack`, `orch_global_params`). The two new
  files log under `orch_payloads` and `orch_wait` where the legacy code logged under
  `orch_api`; only `WaitExec._poll`'s progress line is affected, and it is not in any golden
  trace. Recorded here so no later reader mistakes it for a regression.
- **Engine shim cycles.** `helao/core/servers/orch_unpack.py` becoming `from
  helao.hexagon.app.orch_unpack import ...` is imported by `orch.py` line 28 and 37, which
  already imports `helao.hexagon.app.*` at lines 30–36. No new direction; the runtime half of the
  ratchet would surface a cycle as an `ImportError` in the subprocess.

## 9. What B7a does not do

- Does not touch the graft machinery: `active_graft.py`, `sync_graft.py`, `factory.makeOrchApp`
  and `makeActionApp`'s graft paths. They keep importing the engine under the allowlist; B7b
  deletes them.
- Deletes nothing from `helao/core/servers/`. Every module stays importable and every re-export
  keeps working; the 33 test importers run unchanged.
- Does not rename anything a station sees — no D-S4 (`*_hex` configs, paired ymls,
  `helao/deploy/hexagon/` shims) and no D-S5 (`adapters/legacy` → `adapters/shared`). B7c.
- Does not disposition the post-parity backlog: the `set_error` quirk, the finish-drain window,
  the 0.3 s per-client pacing sleep, the dead `/ws_globstat` sender, `params.limit_vis`. Each is
  an item in B7b's spec, decided individually.
- Does not fix the `andor` checklist drift from PR #217. Gate 3 records it as pre-existing.
- Does not re-baseline `harness/` (D-S2, B7b) or touch `harness/ws_frames.py` beyond the
  allowlist entry.
- Does not run a station gate. Behaviour-neutral by construction; the Linux gates in §7 are the
  whole gate.

## 10. Done

B7a is done when:

- nothing outside `helao/core/servers/` and its tests imports the engine, except the three
  allowlisted B7b files, and the ratchet proves it in both halves;
- the engine still works through its re-exports — every engine test importer passes as before;
- the dispatch golden master is byte-identical on nine scenarios and failed first on the old
  seam;
- gates 3–7 hold, with the `andor` drift and the 12-file baseline recorded rather than hidden;
- B7b can delete `helao/core/servers/` with only tests, the graft machinery, and the harness
  encoder left to clean up — no live code path in its way.

Branch `feat/b7a-relocate-engine-survivors`, merged to `unstable` by PR.

## Amendment 1 (2026-09-29): what planning measured

The implementation plan (`docs/superpowers/plans/2026-09-29-B7a-relocate-engine-survivors.md`,
"Spec deviations and open questions") dry-ran the whole change on `415c0bb2` and found points
where this spec was wrong, or could not be carried out as written. The plan's defaults are
adopted. Where the two disagree, the plan governs, and these are the changes that alter a
decision or a gate:

- **Gate 2 (golden master) becomes "unchanged", not "green".** The dispatch golden master is
  already red on `415c0bb2`: 7 PASS, and deterministic DELTAs on S2 and S7, which predate this
  branch (recorded at `658c94dc` too). The gate is now that the `--check` output and all nine
  fresh traces are byte-identical to a capture taken on `415c0bb2`.
- **The §5 red step hangs rather than failing.** With the patch left on the old seam, the real
  dispatcher retries against `127.0.0.1:8001-8003`. Every red run is wrapped in `timeout` and
  counts as red on rc≠0 with output that differs from the reference. Ports 8000–8003 must be
  free before a red run.
- **A fifth test moves.** `unit_test_orch_unpack.py` patches `PLATE_API` by plain assignment.
  The §2 grep missed it because it looked only for `setattr`/`patch`.
- **The `orch_unpack` re-export carries five names**, `seq_unpacker` included.
- **D-B7a.3 adds two pyright errors in legacy `orch.py`.** Legacy `Orch` passes an `Active` into
  the shared `RunLifecycle`. The user approved suppressing both with
  `# pyright: ignore[reportArgumentType]` on the two engine argument lines. B7b deletes those
  lines anyway.
- **Gate 4's baseline is re-measured, not assumed.** A worktree has no private deployments,
  so its failing set is 3 files, not 12.
- **Gate 3 is an exact set of five failing checklist test IDs** (andor, biologic and nidaqmx
  drift), not "andor only".
- **Gate 6 stops the group with SIGTERM**, which runs the same `teardown_group()` as CTRL-x. A
  finished sequence may be found in `RUNS_SYNCED`.
- **The §8 route-class assertion checks `APIRoute` instances only.** The legacy hosts are
  probed in a separate subprocess, because building them loads the engine.
