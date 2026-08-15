# B6 — Port the private deployments to the native hosts

**Date:** 2026-08-15
**Parent:** `docs/superpowers/specs/2026-08-14-legacy-separation-program-design.md` (§4, row B6)
**Depends on:** B5 (merged to `unstable` @ `de7c8c4f`)
**Privacy rule:** inherited. The private deployments are **Deployment-A/B/C** only, and no
tracked file in this repo may name them. Each is a separate git repository nested in-tree;
its own commits, tests and checklists live inside it.

---

## 1. What B6 is

B5 left the legacy engine reachable from exactly three places: the three private deployments.
B6 ports them, after which nothing outside `helao/core/servers/` constructs `BaseAPI`,
`OrchAPI`, `Base` or `Active` — which is the precondition B7 needs.

The transform is the one B5 proved, unchanged: `BaseAPI` → `ActionHost`,
`@app.post(f"/{server_key}/x", tags=["action"])` → `@app.action()` with an explicit
`ctx: ActionContext`, `setup_and_contain_action` → `ctx.begin`, `app.base.<member>` →
`app.<member>`. Private routes are untouched. The recipe is written out in
`docs/superpowers/plans/2026-08-15-B5-hte-port.md` and is not restated here.

## 2. Measured surface

Counted at `de7c8c4f`. **The program spec's 8 / 6 / 2 is right for A and C and wrong for B.**

| deployment | modules importing the engine | routes (frozen) | note |
|---|---|---|---|
| **A** | 8 | 59 action / 19 private | one also imports `Base`; one server's routes come from a parent-repo registrar |
| **B** | 3 | 31 action / 0 private | spec said 6; the other three are under `notes/`, which is excluded from every sweep |
| **C** | 2 | 0 action / 21 private | both are thin wrappers; one is already native transitively |

**Two of the thirteen are already ported, transitively, by B5.** Deployment-A's `io_server`
is a 24-line delegation to hte's `nidaqmx_server`, and Deployment-C's `local_analysis_server`
is a delegation to `helao/core/drivers/data/analysis_driver.make_analysis_app`. B5 ported both
targets, so these two modules serve a native host today; what remains in each is a `BaseAPI`
return annotation. That is the same shape hte's `analysis_server` had.

### Gate infrastructure already present

Each deployment carries its own frozen route checklists at `tests/checklists/*.json`, in the
format `harness/endpoints.py` reads — so B5's gate design transfers directly, one gate per
repo, with no name leaking into this repo.

| deployment | content gate today | coverage |
|---|---|---|
| **A** | `test_checklist_content.py` | **1 of 8 modules** (`motion_server` only) |
| **B** | none | 0 of 3 |
| **C** | `test_checklist_content.py` | **2 of 2**, including the marker split |

Deployment-C's is the complete example and the one to copy: it splits each checklist into
AST-visible routes and routes marked `external_registrar` / `dynamic_registration`, checks the
first against extraction and the second against the registrar or the module-level constant the
registration loop iterates, and carries two vacuity probes proving each half can go red.

## 3. What B5 broke here, and what that says

**Deployment-A's `test_p4b_gamry_overlay.py` was red on `unstable` before B6 started.** It
builds the real gamry composition — this deployment's potentiostat takes 15 of its 16 routes
from hte's registrar through `overlay_dyn_endpoints` — against a stubbed app. B5 moved that
registrar to read `app.server.server_name` instead of `app.base.server.server_name` and to
register through `@app.action()`, and the stub carried the legacy two-object shape. Fixed in
that repo.

Runtime was never affected: a live `ActionHost` has `.server` (set by `HelaoFastAPI`, read by
`ActionHost.__init__` itself, so a host missing it could not construct at all), and a real
gamry server builds and registers. This was a test-fake break.

**The lesson is about the gates, not the fix.** Every B5 gate was green while this was red,
because all of them sweep the parent repo and the break was in a nested repo reaching through
an overlay over a parent-repo registrar. Nothing in this repo can see that class of breakage.
Hence D-B6.3.

## 4. Decisions

**D-B6.1 — One gate per repo, living in that repo.** A checklist gate in this repo would have
to name the deployments and their server keys. Each private repo already holds its own
checklists; the gate goes beside them, modelled on Deployment-C's. This repo gains nothing
about B6 except this spec and the plan, both of which use Deployment-A/B/C.

**D-B6.2 — Extend the existing gates before porting, and do not re-freeze.** Deployment-A's
covers 1 of 8 modules and Deployment-B has none; both are seeded to full coverage and shown
green on the untouched source first, exactly as B5 did. `harness/freeze.py` is not re-run:
regenerating a checklist after a port makes the gate pass by construction.

Four of Deployment-A's checklists cannot be checked as-is, for two reasons that are properties
of the manifest and the composition rather than defects:

- `servers.json` records `representative_key: null` for four modules whose frozen paths carry
  a concrete key, so extraction yields `/{server_key}/…` and every route reads as a
  missing/extra pair. The manifest is what is incomplete.
- `potentiostat_server` (15 of 16) and `io_server` (19 of 19) get their routes from a
  parent-repo registrar. They need the `external_registrar` split Deployment-C's gate already
  implements, not a diff against their own source.

**D-B6.3 — A cross-repo gate lands in this repo, deployment-agnostic.** The gamry-overlay
break is a class, not an incident: a parent-repo registrar that a private deployment composes
over can change shape without any parent-repo test noticing. The gate added here walks
whatever `helao/deploy/*` directories are present, skips the tracked ones, and asserts each
remaining deployment's action modules import no engine name — **by directory glob, never by a
written-down list of names**, so it works on a checkout that has none of them and names none
of them either. It is the B4/B5 ratchet generalised, and it is what would have caught this.

**D-B6.4 — Per-station gates, as in B5, and on the same terms.** Deployment-C is
data-processing with no hardware gate at all (recorded in the program's earlier research).
Deployments A and B have station hardware, and their gate is the first-launch checklist B5
established, kept in each repo. B6 does not hold its merges waiting for them.

**D-B6.5 — Each repo branches off `main` and merges on its own.** All three sit on `main`
tracking `origin/main`. Work goes on a branch per repo; nothing is pushed without being asked.

## 5. Decomposition

| # | scope | gate |
|---|---|---|
| **B6.0** | the B5 fallout in Deployment-A — done | that repo's suite green |
| **B6.1** | the cross-repo ratchet in this repo | it fails against the pre-B6 private tree, passes after |
| **B6.2** | Deployment-C: 1 module + 1 annotation | its gate, already at 2/2 |
| **B6.3** | Deployment-B: gate for 3 modules, then port | new gate green before and after |
| **B6.4** | Deployment-A: gate 1→8 modules, then port 8 | new gate green before and after |

C first because it is two files and its gate is already complete; A last because it is the
bulk and the only one with an overlay composition.

## 6. What B6 does not change

- No route path, method, tag or parameter — the per-repo checklists forbid it.
- No config file, and no `deployment:` key.
- No behaviour on disk or on the wire.
- Nothing under any deployment's `notes/`, which is excluded from every sweep.
