# B5 — Port the hte deployment to the native hosts

**Date:** 2026-08-15
**Parent:** `docs/superpowers/specs/2026-08-14-legacy-separation-program-design.md` (§4, row B5)
**Depends on:** B0 (UI re-home), B1 (`ActionHost`), B3 (`OrchHost`), B4 (`test` deployment)
**Baseline:** `unstable` @ `5c05c8d2`
**Privacy rule:** inherited. The private deployments are **Deployment-A/B/C** only.

---

## 1. What B5 is, and the three measurements that reshape it

The program spec sizes B5 as "24 action + 16 visualizer modules + orchestrator + operator,
station by station". Three measurements taken at `5c05c8d2` change that scope materially.

**The visualizers and the operator are already done.** `grep` for `helao.core.servers` across
`helao/deploy/hte/servers/visualizer/` (22 modules) and `servers/operator/` (4 modules)
returns **zero** hits. B0 re-homed `vis` and `vis_subscriber` to `helao/ui/`, and those were
the only engine names those modules ever used. Nothing in B5 touches them. The same is true of
`helao/deploy/hte/experiments/`, `sequences/` and every driver but one.

**The port is a source transform with a mechanical, already-frozen gate.** The remaining
coupling is 23 action modules that import `BaseAPI` (8 of them also `action_version`), one
orchestrator importing `OrchAPI`, and one driver importing `Base`/`Active`. `harness/endpoints.py`
extracts every decorated route by AST — without importing the module, so a Windows-only vendor
import is irrelevant — and `helao/hexagon/tests/checklists/hte/*.json` holds that extraction
frozen from the pre-migration legacy source: **168 action routes and 79 private routes, each
with every parameter's name, annotation and default**. B1 already taught the extractor the
native `@host.action()` form and taught it to strip the injected `ctx`. Measured today, all
23 modules extract at **0 diffs** against their frozen checklists. That file set is the gate,
and it is the reason B5's per-module risk is low despite its size.

**Porting a module flips both of a station's configs at once, so rollback is git.** An hte
station has a legacy `adss3.yml` and a derived `adss3_hex.py`. The `_hex` variant routes
through `helao/deploy/hexagon/servers/action/<module>.py`, which calls `makeActionApp`; the
plain `.yml` imports `helao.deploy.hte.servers.action.<module>` and calls `makeApp` directly.
Both end at the same `makeApp`. Once that function returns an `ActionHost`, **both** configs
serve the native host — the `_hex` path because B1's `_is_native_host` check makes the write
graft a no-op, the `.yml` path because it never had a graft to begin with. Launching the
non-`_hex` config is therefore no longer a rollback for a ported server. The only rollback is
`freeze/pre-legacy-removal_2608` or reverting the commit.

That last point is the one that sets B5's shape. It is not a defect — it is D-S6 arriving —
but it means the work cannot land incrementally on `unstable` while stations are running from
`unstable`.

## 2. Measured surface

| item | count | note |
|---|---|---|
| hte action modules importing `BaseAPI` | 23 | 8 also import `action_version` |
| action routes across them | 168 | `tags=["action"]`, the transform's target |
| private routes across them | 79 | plain `@app.post(..., tags=["private"])` — **no change needed** |
| orchestrator modules importing `OrchAPI` | 1 | `servers/orchestrator/async_orch2.py`, 39 lines |
| hte drivers importing the engine | 1 | `drivers/data/archive_driver.py` (`Base`, `Active`) |
| shared `helao/core/drivers/` modules importing the engine | 2 | **not counted by the program spec** — see D-B5.4 |
| hte visualizer modules importing the engine | 0 | done by B0 |
| hte operator modules importing the engine | 0 | done by B0 |
| modules extracting at 0 checklist diffs today | 23 / 23 | the gate is live and green |
| modules whose `makeApp` builds on Linux today | 16 / 17 station-live | only `biologic_server` fails, on a Windows-only import |

**Those two route counts were wrong when this spec was first written**, and the gate caught
it on its first run against the untouched tree. 175/81 came from grepping the source for
`tags=["action"]`, which counts seven commented-out decorators (in `diapump_server`,
`nidaqmx_server`, `pal_server`, `mfc_server`) and two mentions in `sample_server`'s module
docstring. The AST extractor ignores both; 168/79 is what the frozen record actually holds.
Recorded rather than quietly fixed, because a gate seeded before the work and asserted against
a hand-counted number is exactly how a wrong number gets frozen as a requirement.

### Which stations exercise which module

Parsed from the seven live `helao/deploy/hte/configs/*.yml` (commented-out server blocks
excluded — `tec_server` in `anec.yml` and `analysis_server` in `eche10.yml`/`hispec.yml` are
commented, and counting them would have invented two station gates that do not exist):

| module | stations | module | stations |
|---|---|---|---|
| `sample_server` | 7 | `mfc_server` | 2 |
| `sync_server` | 7 | `kinesis_server` | 2 |
| `galil_motion` | 5 | `co2sensor_server` | 1 |
| `gamry_server2` | 5 | `diapump_server` | 1 |
| `nidaqmx_server` | 5 | `cam_server` | 1 |
| `pal_server` | 3 | `spec_server` | 1 |
| `syringe_server` | 3 | `andor_server` | 1 |
| `galil_io` | 3 | `biologic_server` | 1 |
| `calc_server` | 3 | | |

**Six of the 23 have no live hte station config**: `analysis_server`, `HTEdata_server`,
`o2sensor_server`, `power_supply_server`, `tec_server` (all commented out or archive-only) and
`pdu_server`. Of those, only `pdu_server` turns out to run anywhere — at `uvis4`, whose config
lives in a private deployment; see the correction below. The other five are ported — B7 deletes the engine underneath them regardless — but they
carry **no station gate**, and this spec says so rather than letting a station-count summary
imply coverage they do not have.

## 3. Decisions

**D-B5.1 — The unit of work is the module; the unit of the gate is the station.**
The program spec says "station by station", but no module belongs to one station:
`sample_server` and `sync_server` are on all seven. Porting per station would port a shared
module for the first station and silently ship it to the other six. Work therefore proceeds in
risk-ordered module batches, and a station gate is claimed only when every module in that
station's config is ported.

**D-B5.2 — B5 lands on a branch, `feat/legacy-separation-b5-hte`, and merges once.**
Follows from §1's third measurement: a ported module reaches a station through either config,
so a half-merged B5 on `unstable` would put stations on a partially-native group with no
config-level rollback. The branch keeps `unstable` launchable as it is today for the whole
duration, and a station gates by checking the branch out deliberately. This is what P4 and P5
did, for the same reason.

**D-B5.3 — The frozen route checklist is the primary gate, and B5 never re-freezes it.**
`helao/hexagon/tests/checklists/hte/*.json` is a verbatim record of the pre-migration legacy
surface. Re-running `harness/hte_freeze.py` after a port would overwrite the record with
whatever the port produced and the gate would pass by construction. B5 adds a test that
extracts from the current source and diffs against the frozen JSON; it does not write to that
directory. The gate covers path, method, tags, and every parameter's name, annotation and
default, on all 247 routes — including the ones registered inside `dyn_endpoints`, which are
decorated in source and so are visible to the extractor even though they do not exist on the
app until startup.

**D-B5.4 — `helao/core/drivers/analysis_driver.py` and `sync_driver.py` are in scope.**
The program spec counted 49 deployment modules and missed these two. `analysis_server.py` is a
15-line delegation to `analysis_driver.make_analysis_app`, which is where the `BaseAPI` is
actually constructed; `sync_driver.py` imports `Base` for typing. `helao/core/drivers/`
survives the program (D-S3), so these do not disappear with the engine — they must be ported,
or B7 cannot delete `base.py`. Porting `analysis_server` *is* porting `analysis_driver`.

**D-B5.5 — `archive_driver.py`'s engine import is retyped, not rewritten.**
Measured, `Base` and `Active` appear only as annotations (`action_serv: Base` at line 86,
`myactive: Optional[Active]` at line 622). This is exactly the case B4 resolved for the two
`test` deployment drivers: the annotations are also *wrong*, because an `ActionHost`
constructs the driver and an `ActionSession` is what reaches `myactive`. Retype to
`ActionHost` / `ActionSessionPort` under `TYPE_CHECKING`.

**D-B5.6 — Private routes are not touched.**
`ActionHost` subclasses `HelaoFastAPI`, so `@app.post(f"/{server_key}/x", tags=["private"])`
keeps working unchanged. Only the 168 `tags=["action"]` routes take the `@host.action()` +
`ctx: ActionContext` transform. Rewriting the private routes as well would be 79 unnecessary
diffs against a frozen checklist for no behaviour change.

**D-B5.7 — Progress is tracked by a shrinking ratchet, not a single end-state test.**
B5 spans many commits and pauses at station gates. B4's `test_test_deployment_is_native.py`
asserts an absolute end state, which can only be added when the last module lands. hte gets
the `NOT_YET_PORTED` ratchet instead — the list may only shrink, so a regression that
re-imports `BaseAPI` fails immediately, and the file doubles as the phase's progress record.

**D-B5.8 — The second Linux gate is "`makeApp` still builds", measured at 16/17.**
Every station-live module except `biologic_server` (Windows-only `easy_biologic` at import)
constructs a real FastAPI app under a real config on Linux. That number is asserted, not
assumed: a port that breaks a constructor, a driver signature or an import fails here without
a station. It is deliberately *not* a route-count check — most of these servers register their
action routes in `dyn_endpoints` at startup, so `len(app.routes)` at build time is 24 for a
server with 24 action routes in source, and asserting on it would encode that confusion.

## 4. Decomposition

Six batches, ordered so that the cheapest modules prove the transform and the highest-blast-radius
modules are done while the pattern is fresh and before any station is asked for time.

| batch | modules | routes | why here |
|---|---|---|---|
| **B5.1** pilot | `co2sensor_server`, `cam_server`, `pdu_server`, `o2sensor_server` | 8 action | 78–101 lines each, no `action_version`, no `dyn_endpoints`. Proves the transform and the gate rig end to end. |
| **B5.2** shared core | `sample_server`, `sync_server` | 21 + 0 action, 14 + 8 private | On 7 / 7 stations. Both build on Linux; `sync_server` carries D-B5.4's `sync_driver` retype. |
| **B5.3** motion + IO | `galil_motion`, `galil_io`, `kinesis_server` | 37 action | 5 / 3 / 2 stations. `galil_motion` is the largest action-route count in the deployment (24). |
| **B5.4** electrochemistry | `gamry_server2`, `biologic_server`, `nidaqmx_server`, `power_supply_server` | 37 action | `biologic_server` cannot be built on Linux — checklist gate only, station gate at hispec. |
| **B5.5** fluidics + optics | `pal_server`, `syringe_server`, `mfc_server`, `diapump_server`, `spec_server`, `andor_server` | 44 action | `pal_server` has 17 action routes and its own standalone regression harnesses (see §6). |
| **B5.6** remainder + orchestrator | `calc_server`, `HTEdata_server`, `tec_server`, `analysis_server` (+`analysis_driver`), `archive_driver` retype, `async_orch2` | 21 action | `async_orch2` is a 5-line change mirroring the hexagon orchestrator entrypoint B3b already wrote. The end-state invariant test lands here. |

Each batch is one commit per module plus a gate run. A batch is complete when the checklist
diff is empty for every module in it and the build probe is unchanged.

## 5. Gates

### Linux, per batch — no hardware, run on every commit

1. **Route checklist diff** — `extract_routes` vs the frozen JSON, all 23 modules, 0 diffs.
2. **Build probe** — 16 of 17 station-live modules construct under a real config; `biologic_server` raises `OSError` on its Windows-only import and is recorded as such rather than skipped silently.
3. **Ratchet** — `NOT_YET_PORTED` shrank; no module re-acquired an engine import.
4. **Full hexagon + harness sweep**, per-file with `timeout`, and `run_unit_tests.py`.
5. **`black`** on every changed file, per repo, immediately before `git add`.

### Per station — hardware, cannot run from this environment

Claimed only when every module in that station's config is ported. Seven stations, each:

1. `python -m helao.hexagon.preflight helao/deploy/hte/configs/<station>_hex.py` clean.
2. Launch the group from the branch; every server binds, `supervise_early_exits` reports no child exiting on its own in 90 s.
3. The station's own smoke sequence runs to `RUNS_FINISHED`.
4. On-station golden diff: capture before the branch is checked out, capture after, `harness/parity` at 0 diffs.
5. E-stop drill, reading `LIVE_VIS.log` rather than the UI — P5 recorded that each cascade leg has its own `try/except`, so a failed leg is invisible on screen.

Order: `ccsi2` first (one unique module, `co2sensor_server`, from the pilot batch), then
`eche10`, `anec`, `adss3`, `clad`, `ecms1`, `hispec` last (`biologic_server`'s only station and
the only module with no Linux build gate).

## 6. Known traps, carried forward

- **`pal_server`'s regression harnesses are not in `run_unit_tests.py`.** `test_pal_golden_master.py` and `test_pal_busy_wedge.py` under `helao/deploy/hte/tests/` must be run explicitly in batch B5.5. The golden master is the behaviour gate for that server.
- **A GM baseline must be captured before the port that invalidates it.** B1 hit this: once a module builds a native host there is no legacy build of it left to capture from. Any station golden capture happens *before* the branch is checked out.
- **`galil_motion` has a live diagnostics story.** The identity-transform fallback warnings and TC1 capture merged at `9ba1240e` must survive the port; they are ordinary code in the module, but they are the reason an uncalibrated plate reads as a controller `?` rejection rather than a crash.
- **The `_hex` and `.yml` configs converge for action servers as B5 proceeds.** This is D-S4 arriving early. B5 renames nothing; B7 does.
- **`helao/hexagon/app/orch_*.py` still imports helpers from `helao/core/servers/orch*`** — `move_dir`, `PLATE_API`, `async_action_dispatcher`, `sanitize_sequence_label`, `WaitExec`, `checkcond`, `orch_global_params`. These are engine-file residue that B7 must extract or relocate. B5 neither adds to nor removes from that list; it is recorded here so B7 does not discover it late.

## 6b. What executing it actually found

Recorded because the spec predicted a uniform mechanical transform and three
things were not.

**Three endpoints are two-step, not one.** `MOTOR /run_aligner`,
`NI /cellIV` and `SPEC_T /acquire_spec_extrig` need the Action *without*
opening a session, because a precheck can reject and must answer with an error
code and no artifacts on disk. PAL adds fifteen more of the same shape through
a shared `_pal_start` helper. `ctx.action` is legacy's `setup_action()` and
`ctx.begin(...)` is its `contain_action`, so the port is faithful — but it is
not something a decorator rewrite produces.

**The native session factory was missing one field.** Two of those endpoints
set `sample_global_labels` per file connection, stamping the measured sample
onto its own `.hlo`. Legacy's `setup_and_contain_action` never exposed it —
that is precisely why they dropped to `contain_action` — and the explicit
context has no lower level to drop to. `ActionSession.open` now accepts it,
defaulting to the empty list `FileConnParams` itself declares. Without it the
labels would silently be `[]`: a provenance loss invisible to the route
surface, the wire, and the golden diff of anything that does not measure a
sample.

**`ActionSessionPort` is the collaborator contract, not the deployment
contract.** Ten of the fifteen deployment-facing session members are absent
from it, `write_file` among them. Its docstring says it is derived from what
the three native write collaborators read and warns against hand-adding
members — so `archive_driver` annotates against the concrete `ActionSession`
instead. The existing test that checks the fifteen-member deployment surface
checks the *implementation*, which is why the gap had not surfaced.

**The route extractor did not honour `@host.action(path=...)`.** Three routes
were served at a path that did not match their handler's name
(`get_positions` → `/SAMPLE/get_loaded_positions`, `archive_tray_new` →
`/SAMPLE/archive_tray_new_position`, and every config-declared analysis
endpoint, whose handler is named `_analyze` when the decorator runs). Their
ports must pass `path=` to keep both the route and the operation_id where they
were, and the extractor reported those correct ports as missing/extra pairs
until it learned to read the kwarg.

**The station map in this spec was built from `helao/deploy/hte/configs/*.yml`
and is therefore incomplete.** Three more live stations — `uvis4`, `amts`,
`note1` — run B5-changed hte modules from configs held in private deployments,
resolving to those modules through the launcher's deployment fallback. `uvis4`
alone runs eight of them. The station gate runbook carries all ten; this
section's table does not, and is left as the record of what the hte configs
themselves say.

That also corrects one claim below: `pdu_server` **does** have a station gate,
at `uvis4`. It is the only live consumer of that module anywhere.

**Five modules finish B5 without a station gate**, and no later station adds
one: `analysis_server`, `HTEdata_server`, `o2sensor_server`,
`power_supply_server` and `tec_server` — none appears in any live config, hte
or otherwise. `pdu_server` was originally listed here too and does not belong:
it runs at `uvis4`. `analysis_server` also has no route checklist — its
endpoints are built at runtime — leaving the ratchet and the build probe as its
whole gate.

## 7. What B5 does not change

- No route path, method, tag, or parameter — that is precisely what the frozen checklist gate forbids.
- No WS payload shape (Amendment 2 §3).
- No behaviour on disk or on the wire. The post-parity backlog stays dispositioned in B7.
- No config file. `_hex.py` variants, `deployment:` keys and the `.yml` station configs are untouched; D-S4's rename is B7's.
- Nothing under `helao/deploy/hte/{experiments,sequences,specifications,processors,layouts}/`, and nothing in the 22 visualizer or 4 operator modules.
