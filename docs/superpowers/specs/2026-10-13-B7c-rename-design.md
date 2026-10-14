# B7c — Retire the hexagon routing layer and the `legacy` names

**Date:** 2026-10-13
**Program:** Legacy separation (`2026-08-14-legacy-separation-program-design.md`), sub-project B7, third of three parts
**Branch:** parent `feat/b7c-rename` off `unstable` `7592729b`, one PR, ordered commits. Each of
Deployment-A/B/C gets its own `feat/b7c-rename` branch off its `main`. The fourth private
deployment has no B7c surface and is not touched.
**Recovery point:** `freeze/pre-b7c-rename_2610`, taken at `7592729b` in the parent and at the current
`main` head of Deployment-A/B/C (Q7)
**Status:** design approved with one user decision recorded below; reviewed (approve-with-fixes,
fixes applied); this spec records the measurements and settles what the approval left open

## 1. What B7c is, and the measurement that reshapes it

B7c is the program's D-S4 and D-S5: configs go back to bare prefixes, and `adapters/legacy/`
becomes `adapters/shared/`. B7b (§10) left it everything with the word "graft" or "hexagon
routing" in it: the `helao/deploy/hexagon/` shim package, `hexconfig.py`, the `fast: graft` /
`bokeh: graft` / `legacy_module:` / `deployment: hexagon` config vocabulary, and the
`makeActionApp` / `makeVisApp` compositions those keys route to.

**D-S4 as written cannot be done.** It says to delete each paired legacy `.yml` and rename
`<x>_hex` to `<x>`. Every variant is two lines, `config = hexagon_variant(<base>)`, so the base is
the only file holding the station's ports, params and `root:`. Deleting it deletes the station.

**User decision (settled):** keep the bases. Move the `WsPublishBridge` startup hook, which only
`factory.makeActionApp` adds today, into `ActionHost` itself, so every action server gets it. A
base config is then behaviourally equivalent to its variant. B7c deletes the variants,
`hexconfig.py`, the whole shim package and the routing keys, and stations launch bare prefixes
(`./helao.sh eche10`).

That decision rests on an equivalence claim, and §3 checks it item by item. The finding that
matters most comes out of the measurement, not the code read: **the "legacy" bases already run
through the hexagon shims today, by accident.** The launcher's auto-detection globs
`helao/deploy/*/servers/<group>/<module>.py`. When the module exists in more than one deployment
and none of them is the config's own, it takes the first match in sorted order and logs a
warning. `hexagon` sorts before `hte`. So every base config outside `hte` that names a module
the shim package mirrors (`async_orch2`, `standalone_operator`, `action_visualizer`,
`live_visualizer`, `ws_simulator`, and private configs naming `hte` action modules) is served
by the hexagon shim. Measured: **81 server entries in 23 non-variant configs** (§2.4). The hte
station bases are not affected, because hte is their own deployment.

Two consequences follow:

- Deleting the shim package changes what those 81 entries import, even though no config line
  changes. For 70 of them the new resolution is the module the shim wrapped, by construction.
  The other 11 are not: they name `ws_simulator`, which exists in `test` *and* in Deployment-A.
  With `hexagon` gone, sorted order picks Deployment-A's module on any host that has
  Deployment-A checked out. D-B7c.5 pins those entries.
- The bridge's absence is not new. Those 81 entries already have it, and the 7 hte station
  bases launched bare already run without it. §3 shows why it carries no traffic either way.

## 2. Measured surface

All parent figures were measured on `cc07dbd7` in this worktree. Private figures come from each
nested repo's `main` in the main checkout. The resolution figures come from a read-only script
that loads every config with `read_config` and applies `fast_launcher.py:102–152`'s rule.

### 2.1 The variants

| repo | variants | base | base servers routed to hexagon | grafted in the variant |
|---|---|---|---|---|
| parent `hte` | 7 (`adss3`, `anec`, `ccsi2`, `clad`, `eche10`, `ecms3`, `hispec` `_hex.py`) | `<x>.yml` | 0 | 1 each (the `control_visualizer` visualizer) |
| parent `test` | `test_hex.py` | `test.yml` | 0 by key; 3 by fallback (orchestrator, operator, visualizer; §2.4) | 2 |
| Deployment-C | 2 | `.yml` | 2/6 and 1/15 by key | 2 and 3 |
| Deployment-B | 1 | `.yml` | 3/10 by key | 3 |
| Deployment-A | 1 (`.py`) | a `.py` base | 4/9 by key, all `fast: graft` | 5 |

That makes **12 variant files**, 11 of them named `*_hex.py`. The fourth private deployment has
none.

### 2.2 Literal routing keys outside the variants

- **Deployment-C:** 6 live configs carry `fast: graft` + `legacy_module:`, and 1 live config
  carries neither. 2 more grafted configs sit under `configs/archive/`, where they cannot be
  launched today: the launcher's glob root is the config's great-grandparent, which for an
  archive config is the deployment directory itself. Its `tests/smoke/configs/` has 4 files, 2
  of them grafted.
- **Deployment-B:** 2 live configs grafted (3 servers each), and one more config with no routing
  keys. Its smoke dir has 10 files, 5 of them grafted.
- **Deployment-A:** the `.py` base (4 `fast: graft`) and a second config with none. Its smoke
  dir has 27 files, 13 of them grafted.
- **Parent `test`:** `goldenhex`, `goldenhexconc`, `goldenhexid`, `goldenhexvis`, `goldenhexgraft`
  and `goldenhexreflex` carry `deployment: hexagon` (`goldenhexgraft` has 2 `bokeh: graft`). Only
  `goldenhexgraft` has `legacy_module:`.
- **Parent `hte`:** `htehexreflex.yml`, one `reflex:` server with `deployment: hexagon`.
- **`helao/hexagon/tests/smoke/`:**
  - `configs/` holds 63 files. 31 of them are `*hex.yml` copies of a baseline that carries
    `deployment: hte`, and each differs from it only in the routing key:
    - 19 `<x>hex.yml`, diffed against `<x>.yml` by 19 `*_canary.{bat,sh}` scripts;
    - 12 `<x>goldhex.yml`, diffed against `<x>gold.yml` by 12 `*_diff.{bat,sh}` drivers and
      `golden_diff.bat`. Their artifacts come from the generic `golden_capture.py` and 11
      `golden_capture_<x>.py` modules, each with a `test_golden_capture*.py`.
  - `samplegraft.yml` is the one grafted file.
- **Nested drivers of the same shape:**
  - Deployment-A: 9 pair canaries (it has 10 canaries; one is not a pair), 2 diff drivers, 4
    capture modules with 4 `test_golden_capture_*` tests;
  - Deployment-B: 3 canaries, 2 diff drivers, 2 capture modules;
  - Deployment-C: 2 canaries.

### 2.3 Readers of the vocabulary

| reader | what it does with it |
|---|---|
| `fast_launcher.py:106,173`, `bokeh_launcher.py:122,182` | nothing hexagon-specific: `deployment: hexagon` reaches the shims purely by directory name |
| `reflex_bundle.py:195–212` (`app_module_for`) | `deployment: hexagon` selects `helao.hexagon.app.reflex_host` via `HELAO_REFLEX_APP_MODULE` |
| `reflex_launcher.py:327–358,586–614`, `build_reflex_bundle.py:137–156`, `run_browser_parity.py`, `_app/helao_ui/helao_ui.py` | the same env-var seam |
| `helao/hexagon/hexconfig.py` (239 lines) | builds the variants |
| `helao/hexagon/preflight.py:103–109, 221–243, 245–353, 356–392` | shim completeness, graft target, reflex facade, checklist presence (hexagon servers only) |
| `helao/hexagon/app/factory.py:82–115, 117–151, 154–180` | `makeActionApp(server_key, legacy_module)`, `makeVisApp(legacy_module, …)`, `_refresh_loaded_modules` |
| `helao/core/drivers/data/analysis_driver.py:175–299, 1477–1482` | `legacy_module` is candidate 1 of three when resolving the analyses package |
| the 3 `graft.py` shims | read `legacy_module:` from `CONFIG` |

`helao/deploy/hexagon/` has 38 tracked files:

- 25 action shims, of which 23 wrap `hte` modules and 2 wrap `test` (`sim_db_server`,
  `ws_simulator`);
- `action/graft.py`;
- 3 visualizer files and 2 operator files;
- `orchestrator/async_orch2.py`;
- the package `__init__`s.

`.gitignore:27` un-ignores it.

### 2.4 What resolves through the shims today without asking to

These are non-variant configs whose servers carry no `deployment:` key and fall back, by sorted
glob, to a hexagon shim:

| repo | configs | entries |
|---|---|---|
| parent `test` | 11 | 30 (orchestrator, operator, both visualizers) |
| parent `hte` | 2 (`htereflex`, `htehexreflex`) | 8 (`ws_simulator` ×4 each) |
| Deployment-A | 2 | 6 |
| Deployment-B | 3 | 16 |
| Deployment-C | 5 | 21 |

After the shim package is deleted, the same rule picks:

- **the wrapped module**, for every entry except `ws_simulator`. The module is then unique (in
  `hte`), or the only non-hexagon candidate.
- **for `ws_simulator`, Deployment-A's module.** That covers `htereflex` and `htehexreflex` (4
  servers each) and one Deployment-B config (3 servers): **11 entries**. It happens wherever
  Deployment-A is checked out: the candidates are `[Deployment-A, test]`, neither is the
  config's own, and sorted order wins. Today those entries reach `test.ws_simulator` through
  the shim.
- **`hte` for `data_browser`** in one Deployment-C config, as it already does today (`[hte, test]`,
  unchanged by B7c).

`orchestrator/async_orch2.py` in the shim package and `hte/servers/orchestrator/async_orch2.py`
have identical `makeApp` bodies: `OrchHost(server_key, server_key, "Orchestrator", version=3.0)`.
`test` has no orchestrator package, so after deletion `test` configs resolve to `hte`'s.

**A latent ambiguity of the same kind:** `calc_server` exists in `hexagon`, the fourth private
deployment, `hte` and Deployment-A. No measured config hits it today, but which module a config
outside those deployments would get depends on which repos are checked out (§9).

### 2.5 `adapters/legacy/`

There are 16 modules plus `__init__.py`. Parent importers:

- **non-test (7):** `factory.py`, `adapters/native/{artifact_store, galil_motion_native,
  sync_adapter}.py`, `hte/drivers/motion/galil_motion_driver.py`, `hte/drivers/robot/pal_driver.py`,
  `harness/ws_frames.py`;
- **tests (19):** including two under `helao/deploy/hte/tests/`.

`helao/hexagon/adapters/__init__.py`'s docstring names the `legacy/` subpackage as well.

**Nested importers: 2, not 0.** In Deployment-A, its motion action server and one test import
`adapters.legacy.calibration_store`, and one other test names the path in a docstring.

### 2.6 Tests touching the surface (parent)

- **Shim / factory / graft:** `test_factory.py` (including the bridge asserts at 393–402),
  `test_vis_graft.py`, `test_hte_action_shims.py`, `test_hte_vis_import.py`, `test_db_shim.py`
  (bridge assert at 54), `test_vis_hexagon_producer_parity.py`,
  `test_hte_canary_reference_is_gone.py`, `test_engine_import_ratchet.py` (its factory probe),
  `live_group.py` (8 users).
- **Variants:** `test_hexconfig.py` (asserts a base is *not* fully flipped, l.114),
  `test_preflight.py` (`KNOWN_HEXAGON_CONFIGS` names the 8 public variants),
  `harness/tests/test_station_golden_capture.py:66,95–97`,
  `smoke/station_golden_capture.py:118` (`ext = "py" if prefix.endswith("_hex")`),
  `smoke/eche10_golden_diff.bat` (5 refs).
- **Reflex:** `test_reflex_host.py`, `test_reflex_bundle.py`, `test_reflex_entry_resolver.py`,
  `test_reflex_launcher.py`, `test_reflex_gate_config.py`.
- **`legacy_module` / `deployment` keys:** `test_analysis_resolution.py`, `test_browser_parity.py`,
  `test_vis_gate_config.py`, `test_db_gate_config.py`.
- **Private station names in docstrings:** `test_sync_loop_starvation.py`,
  `test_sync_parent_requeue.py`. Each names a private `_hex` station; see Q12.

In the nested repos:

- Deployment-A's and Deployment-B's `tests/test_config_preflight.py` assert that the graft
  checklist is non-vacuous.
- Several `CLAUDE.md`s describe the variants and the graft: Deployment-B `CLAUDE.md:23–43`,
  Deployment-A's, and Deployment-C's root and `drivers/` ones.
- So do the `HEXAGON_SHIM_NOTE.md` / `HEXAGON_SHIM_BLOCKER.md` files, Deployment-B's two
  `AT_STATION_*.md`, and the `_member_surface.md` checklists (B, C).
- Deployment-A has three loose hits: a smoke config whose comment names
  `helao.deploy.hexagon`, a hardware-scope note that names `legacy_module`, and the test
  docstring from §2.5. §5.1 and §5.3 assign them.

### 2.7 Prefix-keyed state

`launch.py:1347` names the pid file `pids_{confPrefix}_{extraopt}.pck`. At 1978 the detach marker
is keyed on `confPrefix` too, and live-member detection matches `<launcher> <confPrefix>
<server_key>` in the process cmdline. **A group still running under `<x>_hex` is invisible to a
`<x>` launch.** That launch would not refuse; its servers would fail to bind ports the old group
still holds. `STATES/queues.pck` is keyed on `root:` and `loaded_modules_<server_key>.json` on
the server key, so neither moves: `./helao.sh eche10 --restore` imports the queues an
`eche10_hex` group exported.

Runbooks naming prefixes: `docs/superpowers/notes/2026-08-15-B5-station-gate-runbook.md` (13
hits), `2026-08-08-P7-station-rollout-runbook.md` (4), and `docs/config-schema.md` (7) for the keys.

### 2.8 Checklists

`helao/hexagon/tests/checklists/hte/` has 27 frozen per-server checklists. Two cases matter for
D-B7c.6:

- One live Deployment-C config runs `xafs_server`, which resolves to `hte`, and `hte` has no
  `xafs_server.json`. Today's preflight never checks it, because the server is not
  hexagon-routed.
- 12 `cpsim_server` entries in `htereflex`/`htehexreflex`, and 3 in private configs, fail the
  checklist lookup if it searches the config's own directory as well as the owner's.

## 3. The equivalence claim, item by item

What a variant gives a server, beyond what its base gives it:

| # | variant adds | where | carries traffic? | B7c disposition |
|---|---|---|---|---|
| E1 | `WsPublishBridge` bound to `wiring.status` at startup | `factory.py:100–114` | **No.** Nothing outside tests calls `StatusPort.publish_status/data/live` (grep of every non-test `.py`, parent and nested). The host's own WS path, `status_q` → `WsPublisher`, is identical either way. | moves into `ActionHost` (D-B7c.1) |
| E2 | a second `build_wiring`, assigned to `app.hexagon_wiring` after the host's `__init__` built its own (`factory.py:94,97–98`) | factory | No. The host's `meta_writer` is bound to the first wiring and sessions read the second. `NativeArtifactStoreAdapter` holds no per-host state (`meta_writer_for`/`collaborators_for` construct fresh), and both clocks read the same offset file. | gone; one wiring per host |
| E3 | build-time `TypeError` if `makeApp` returns a non-`ActionHost` | `factory.py:92–96` | No. Every target is native (B7b D-B7b.2) | gone; `_is_native_host` deleted |
| E4 | `makeVisApp`: per-session `build_wiring` + `VIS_REQUIRED`, `doc.hexagon_wiring` | `factory.py:146–148` | No. Nothing reads `doc.hexagon_wiring` | gone, along with `VIS_REQUIRED` (D-B7c.3) |
| E5 | `_refresh_loaded_modules` per Bokeh session | `factory.py:154–180` | It fixes a hole that only shim routing creates. Bare launch imports the real module in `bokeh_launcher`, before the startup snapshot | gone |
| E6 | `reflex_host` facade: same `app` object, plus module-level `WIRING`, `ReflexAppUiHost`, and fail-loud `build_wiring` | `reflex_host.py` | No. Nothing reads `WIRING`, and the app object is `helao.ui.reflex.app.app` itself | gone (D-B7c.4) |
| E7 | `CONFIG["deployment"] = "hexagon"` in every routed process | launchers | See below | becomes the real deployment |
| E8 | orchestrator via the shim `async_orch2` | §2.4 | Identical `makeApp` body | resolves to `hte`'s |

**E7, measured.** Five readers of `CONFIG["deployment"]` exist:

- **`deployment_version`** (launchers) has no reader.
- **`hooks/loader._resolve_path`** tries `<deployment>/processors` first, then `hte`, then a sorted
  glob. No processor basename appears in two deployments, so the result is unchanged.
- **`import_autolibs`** tries the config's own path first, so for every in-tree config the
  result is unchanged.
- **`ui/shared/discovery.deployment_search_order`** used to put the `hexagon` package first, which
  holds no panel modules. Now the real deployment comes first, which is the documented
  override order.
- **`analysis_driver.resolve_analyses_package`**: `fast_launcher` sets `CONFIG["deployment"]` to
  the deployment it resolved the server's module from (`fast_launcher.py:154`). After B7c that
  deployment is the module's owner, which is what candidate 1 (the owner of `legacy_module`)
  used to compute. So candidate 2 now yields what candidate 1 did.

**Residual differences, accepted:**

- A startup log line per routed server goes away: `fast_launcher`'s multiple-candidate warning
  for the 81 §2.4 entries.
- Bokeh/Reflex sessions no longer re-validate the config per session. The launcher validated it
  at startup, and nothing reads the result.
- Every Reflex bundle rebuilds once, because the stamp hashes parent `HEAD`
  (`helao/ui/reflex/CLAUDE.md`). Any parent pull already does that.

## 4. Decisions

**D-S1, amended.** The recovery point for B7c is `freeze/pre-b7c-rename_2610`, in the parent and in
each of Deployment-A/B/C. `freeze/pre-engine-delete_2609` and `freeze/pre-legacy-removal_2608`
remain. Rolling back means checking out the freeze branch in every repo the station uses, then
launching `<x>_hex`.

**D-B7c.1 — The bridge is bound in `ActionHost.__init__`, not in a startup hook.**
`status_q`/`data_q`/`live_q` are created in `__init__` (`action_host.py:263–265`), and
`WsPublishBridge` only stores the three references. The "queues are live only once the app has
started" premise in `ws_publish.py`'s docstring and `factory.py:100–102` is stale, so the
startup-ordering constraint goes with it. Immediately after the queues:

```python
self.hexagon_ws_bridge = None
if self._binds_ws_bridge and isinstance(wiring.status, DispatcherStatusAdapter):
    self.hexagon_ws_bridge = WsPublishBridge(self.status_q, self.data_q, self.live_q)
    wiring.status.bind_publish_bridge(self.hexagon_ws_bridge)
```

- **`_binds_ws_bridge`** is a class attribute: `True` on `ActionHost` and `False` on `OrchHost`,
  its only subclass. That keeps P2b-2's D3 ("ACTION apps only; `OrchHost` serves its own
  `/ws_*` relays"), and an orchestrator never had a bridge on any route.
- **The `isinstance` guard** replaces factory's `UnwiredPortError`. `build_wiring` always yields a
  `DispatcherStatusAdapter`, so the raise was unreachable in production. A test that injects
  `FakeStatusPush` (which has no `bind_publish_bridge`) gets `None`, as it does today on the
  non-factory path.
- **Double publish cannot happen.** The bridge is a sink for an unused port. The host keeps its
  only real producer (`status_q.put` in the session and `log_status_task`), and the bridge adds
  none.
- **Already-flipped servers** stop being bound twice. Today `build_wiring` runs twice under
  `makeActionApp`, but the bridge is bound once, to the second wiring. After B7c it is bound
  once, to the only wiring.

**D-B7c.2 — Config rewrite rule.** It applies to every tracked, launchable config in all four
repos, smoke included. Per server entry:

1. `fast|bokeh: graft` + `legacy_module: helao.deploy.<D>.servers.<G>.<M>` → `fast|bokeh: <M>`.
   The `deployment:` key follows step 3.
2. `fast|bokeh: <M>` + `deployment: hexagon` (a named shim). The target is the shim's
   `LEGACY_MODULE` (deployment `<D>`), or `hte` for the orchestrator. Keep `<M>` and apply step 3.
3. `deployment:` is written as `<D>` **only if** the launcher's auto-detection, run with the
   shim package gone, would not pick `<D>` unambiguously. That is the case when `<D>` is not
   the config's own deployment and `<M>` exists in more than one deployment, or when the config
   lives outside `helao/deploy/*/configs/` (all smoke configs). Otherwise the key is dropped.
4. `reflex:` + `deployment: hexagon` → drop the key (D-B7c.4).
5. `legacy_module:` never survives. Neither does a server-level `deployment: hexagon`, in either
   YAML or `.py` dict form.

Variant `.py` files are deleted. The bases are not edited, except where step 3 applies. Measured,
the 7 hte bases and `test.yml` need **no edit at all**: their 3 fallback entries resolve
uniquely to `hte` once the shims go. Deployment-C's unlaunchable `configs/archive/` configs are
deleted, not rewritten (Q11).

**D-B7c.3 — Remove the factory compositions and their dead companions.**

- **Deleted:** `makeActionApp`, `makeVisApp`, `_refresh_loaded_modules`, `_is_native_host`, and
  `VIS_REQUIRED` in `wiring.py`. No caller is left once the shims go.
- **Kept:** `build_wiring`, `factory.py`'s only surviving export, which `ActionHost.__init__` and
  nothing else calls. The module docstring is rewritten to "composition root: builds the port
  wiring every host consumes". `BokehServerUiHost` also stays, because `hte`'s `galil_motion`
  still uses it.
- **`legacy_module` is removed, not renamed.** There is nothing for a renamed key to mean once a
  server's code key names its module directly.
- **`analysis_driver`:**
  - `resolve_analyses_package` and `load_analysis_classes` lose the `legacy_module` parameter
    and candidate 1;
  - `_deployment_of_module` is deleted if candidate 1 was its only caller;
  - the call at 1477–1482 stops reading `server_cfg.get("legacy_module")`;
  - candidates 2 and 3 stay, since §3 E7 shows they cover what 1 did.

**D-B7c.4 — The Reflex hexagon seam is collapsed, not kept inert.**

- **Deleted:** `helao/hexagon/app/reflex_host.py` (`ReflexAppUiHost` and `WIRING` with it),
  `HEXAGON_APP_MODULE`, `HEXAGON_DEPLOYMENT`, and the hexagon branch of `app_module_for`.
- **Then also deleted:** with that branch gone, `app_module_for` returns a constant. So it,
  `APP_MODULE_ENV`, `import_app_module`'s indirection, and the env plumbing in
  `reflex_launcher`, `reflex_bundle`, `build_reflex_bundle` and `run_browser_parity` go too.
  `_app/helao_ui/helao_ui.py` imports `helao.ui.reflex.app` directly.
- **Why:** the seam was built so that hexagon routing could be removed by deleting one key. That
  has now happened, and the seam has no other user.
- **The stamp cost is nil.** B7c moves parent `HEAD`, which rebuilds every bundle anyway.
- Q4 records the alternative.

**D-B7c.5 — Ambiguous resolution becomes a preflight error.** `preflight` gains the launcher's
resolution rule, **without editing any launcher**, which keep their warning.

- **An issue:** a server whose module resolves to more than one deployment, none of them the
  config's own, with no explicit `deployment:`. A module that resolves to none is an issue too.
- **Effect:** this is what pins the 11 `ws_simulator` entries (§2.4) to `deployment: test`, and
  the Deployment-C `data_browser` entry to `deployment: hte`. Both values are already what each
  entry runs today.
- **Its test does not depend on which private repos are checked out.** The unit test builds a
  synthetic `helao/deploy/` tree in `tmp_path`, with one module in two non-config deployments.
  It asserts the issue, then asserts that adding `deployment:` clears it.

**D-B7c.6 — Preflight is re-scoped, keeps its module path, and stays the gate private repos run.**
`helao.hexagon.preflight` keeps its name and CLI, and its four gates become:

1. **Config sanity**, unchanged.
2. **Module resolution**, which replaces shim completeness:
   - every `fast:`/`bokeh:` must resolve to exactly one module on disk under D-B7c.5;
   - any `legacy_module:`, `graft` code key or `deployment: hexagon` is an issue, and its
     message cites the D-B7c.2 rule.
3. **Checklist presence, reported rather than enforced (Q15).**
   - **Which checklist:** the one for the module's **owning** deployment only, never the
     config's own directory.
   - **Which servers:** the gate fails only for an action server whose owning deployment has a
     checklist directory *and* whose module had a checklist at `7592729b` but no longer does.
     Every other action server with no checklist is listed in the output as `no checklist`,
     not failed.
   - **Why:** `xafs_server` and the 15 `cpsim_server` entries (§2.8) would otherwise fail a gate
     that today's preflight never applied to them.
   - **Scope limit:** B7c freezes no new checklists.
4. **Library collisions**, unchanged.

**Deleted from preflight:** `HEXAGON_SERVERS`, `_shim_completeness`, `_graft_target_issues`,
`_reflex_host_issues`, `_hexagon_reflex_app_module`, the graft branch of
`_checklist_module`/`_owning_deployment`, and `HEXAGON = "hexagon"`. `_lib_module_path` loses its
`!= HEXAGON` guard.

**D-B7c.7 — `adapters/legacy/` → `adapters/shared/` by `git mv`, nothing else in the move
commit.**

- 17 files. Every `helao.hexagon.adapters.legacy` and `adapters/legacy` string in parent code,
  tests and live docs is rewritten mechanically. So is the `legacy/` mention in
  `adapters/__init__.py`'s docstring.
- Class names (`LegacyClockAdapter`, `LegacyTransportAdapter`, …) are **not** renamed. D-S5
  names the package, the class renames would touch about 60 more lines with no reader benefit,
  and they would make the move commit unreviewable as a rename (Q13).
- No `adapters/legacy` alias module is left in the parent. Deployment-A bridges the gap on its
  own side (D-B7c.10).

**D-B7c.8 — Pair drivers whose configs die are deleted; single-config captures survive.**
After D-B7c.2, every `*hex.yml` smoke copy is identical to its baseline except for comments and
`root:`. Any diff against it is hex-vs-hex: the vacuous case its own header warns about. Per
D-S2 ("the harness survives as a self-regression; the A-versus-B framing is removed"):

- **Deleted, parent:**
  - the 31 `*hex.yml` copies and `samplegraft.yml`;
  - the 19 pair canaries;
  - the 12 `*_diff.{bat,sh}` drivers and `golden_diff.bat`.
- **Kept, parent:**
  - the `<x>.yml` and `<x>gold.yml` baselines, carrying `deployment: hte`;
  - `golden_capture.py`, the 11 `golden_capture_<x>.py` modules and their
    `test_golden_capture*.py`. Each still has a single-config target, `<x>gold`. Their
    docstrings and any `goldhex` defaults are rewritten to that target.
  - `openapi_diff.py`, which §7 uses.
- **Nested, by the same rule:**
  - Deployment-A: delete the 9 pair canaries, the 2 diff drivers and the `*hex`/`*goldhex`
    copies. Keep the canary that is not a pair and each capture module that still has a
    single-config target; any capture module and test without one is deleted.
  - Deployment-B: delete the 3 canaries, the 2 diff drivers and the copies; capture modules as
    in Deployment-A.
  - Deployment-C: delete the 2 canaries and the copies.
  - In all three, delete the `HEXAGON_SHIM_*.md` notes.
- **Leftovers fail a test.** D-B7c.11's static half fails any tracked file under a
  `tests/smoke/` directory that names a `*hex` or `*goldhex` config that no longer exists.
- Q3 covers the alternative.

**D-B7c.9 — Test-only configs keep their names.** `goldenhex*`, `htehexreflex` and the smoke
baselines are fixture names that 9–27 files reference, not station prefixes. They get the
D-B7c.2 strip and keep their names. `goldenhexvis` vs `goldenvis` and `goldenhexreflex` vs
`goldenreflex` then differ only in `root:` and a `doc_name`; they are kept, because harness tests
key on both (Q2).

**D-B7c.10 — Cross-repo order: nested first, parent, then nested clean-up.**

- **N1, each nested repo, before the parent.**
  - Configs, smoke drivers and docs, per D-B7c.2 and D-B7c.8. Every N1 config resolves on
    **current** `unstable`: its servers name their real module, which routes directly to an
    `ActionHost` today. The only loss is E1, which carries no traffic.
  - Deployment-A's motion action server and its test import
    `helao.hexagon.adapters.shared.calibration_store` inside `try:`, with
    `except ModuleNotFoundError:` falling back to `...adapters.legacy.calibration_store`.
  - So no window exists in which a station holding either parent fails to import it.
- **P, parent.** It can merge only after all N1s, because it deletes the shims those configs
  route through.
- **N2, after P.**
  - Deployment-A drops the fallback and the `adapters/legacy` docstring mention.
  - Deployment-A and B tighten `test_config_preflight` to the new gate 2's non-vacuity.
  - Deployment-A's `CLAUDE.md:142–143` rule, "this repo commits SECOND", applies to exactly this.
  - Only N2's final heads must satisfy the ratchet.

**D-B7c.11 — The ratchet.** A new `helao/hexagon/tests/test_hexagon_routing_ratchet.py` has two
halves, both at zero with no allowlist except the historical-docs globs.

- **Static.**
  - **Files scanned:** the parent's `git ls-files`, plus each `helao/deploy/<d>/` present on
    disk that is neither `hte` nor `test`. For those, use `git -C <d> ls-files` when `<d>/.git`
    exists. Otherwise (gate 5's `git archive` copies) walk the tree, skipping `.git/`,
    `__pycache__/`, and any file that is not UTF-8 text with a `.py/.yml/.yaml/.bat/.sh/.md/.toml/.json`
    suffix.
  - **Patterns:**
    - `legacy_module`;
    - `["']?(fast|bokeh|reflex)["']?\s*:\s*["']?graft\b`;
    - `["']?deployment["']?\s*:\s*["']?hexagon\b`, which covers the YAML and `.py`-dict forms;
    - `helao[./]deploy[./]hexagon` and `adapters[./]legacy`;
    - `\blegacy/` within `helao/hexagon/adapters/`;
    - `hexagon_variant`, `hexconfig`, `makeActionApp`, `makeVisApp`, `reflex_host`,
      `VIS_REQUIRED`;
    - a config file named `*_hex.py`;
    - under any `tests/smoke/` directory, a `\b\w+(gold)?hex\b` token naming a config that does
      not exist in that repo's `tests/smoke/configs/`.
  - **Excluded:** `docs/superpowers/{specs,plans}/**`, nested `docs/**` (provenance, per
    D-B7b.10), and this test file.
- **Runtime.** In a fresh subprocess with `PYTHONPATH` set to the repo root,
  `find_spec("helao.deploy.hexagon") is None` and
  `find_spec("helao.hexagon.adapters.legacy") is None`. Both fail on a stale `__pycache__`
  directory, which is correct (D-B7b.9). The message gives `rm -rf` and `rmdir /s /q` for both
  paths.

`.gitignore:27` (`!helao/deploy/hexagon/`) is removed in the delete commit, so a resurrected
directory is ignored rather than tracked.

## 5. Commit sequence

### 5.0 Task 0 — baselines (no commit)

On `7592729b`, in the bare worktree (B7b §7 gate-5 procedure for private copies):

- **F0 / F0p.** The failing set of `run_tests.py` without, then with, the private copies.
- **R0, the resolved composition** of every config in all four repos, computed with all private
  copies present. For each server it records:
  - the code key;
  - the resolved import target: a shim maps to its `LEGACY_MODULE`, the orchestrator shim to
    `hte.async_orch2`, a graft to its `legacy_module`;
  - the entry's dict minus `fast/bokeh/reflex/deployment/legacy_module`.

  Variants are recorded under their base's name. The script is plan scratch, not tracked.
- **O0, live `/openapi.json`** of every action server in `goldenhexgraft` and `goldenhexvis`
  (Linux, sims), through `harness/openapi_capture`.

### 5.1 Nested N1 (×3, before P)

One commit per repo:

- the D-B7c.2 rewrite of live and smoke configs, deletion of the variant, and (Deployment-C)
  deletion of `configs/archive/` configs;
- D-B7c.8 deletions;
- `test_config_preflight.py` keeps asserting `PREFLIGHT OK` and drops the graft-count assertion;
- edits to `CLAUDE.md`, `AT_STATION_*.md`, `_member_surface.md`, and canary-script prefixes;
- Deployment-A only:
  - the `try`/`except` import (D-B7c.10);
  - the smoke-config comment naming `helao.deploy.hexagon`;
  - the hardware-scope note naming `legacy_module`.

Check: that repo's tests pass against **current** `unstable` (a `git archive` copy into a scratch
`unstable` worktree), and R(after) equals R0 for every surviving config.

### 5.2 Parent P

1. **Bridge into `ActionHost`** (D-B7c.1).
   - In the same commit, `makeActionApp` loses its startup hook **and** `factory.py:97–98`
     (`app.hexagon_wiring = wiring`, `app.hexagon_ws_bridge = None`). Both run after
     `__init__`, so leaving them would report `None` for a host that has a bridge.
   - `test_factory.py:393–402` and `test_db_shim.py:54` are ported to read the host's own
     bridge; §6 later deletes or ports those files.
   - `test_ws_publish_bridge.py` gains three cases: a host built by `build_wiring` has a bound
     bridge whose queues are the host's own; an `OrchHost` has `hexagon_ws_bridge is None`; an
     injected `FakeStatusPush` wiring yields `None`.
   - Check: the full sweep equals F0.
2. **Configs.**
   - Delete the 8 public variants.
   - Apply the D-B7c.2 strip to the `goldenhex*` configs, `htehexreflex`, and the surviving smoke
     baselines.
   - Add `deployment: test` to the `ws_simulator` entries in `htereflex`/`htehexreflex`.
   - Apply the D-B7c.8 deletions and the capture-module rewrites.
   - Check: R(after) equals R0, and every surviving config preflights on the **old** preflight.
3. **Delete the routing layer.**
   - delete `helao/deploy/hexagon/` with `rm -rf`, the `.gitignore` line, and `hexconfig.py`;
   - make D-B7c.3's factory, `wiring.py` and `analysis_driver` edits;
   - make the D-B7c.4 Reflex collapse;
   - rewrite preflight per D-B7c.5/6, including the synthetic-tree ambiguity test.
   - Tests follow §6.
4. **`adapters/legacy` → `adapters/shared`** (D-B7c.7). Rename only; check `git diff -M --stat`
   shows 17 renames at ≥90 % similarity.
5. **Ratchet, docs, stale references.**
   - add D-B7c.11;
   - update `docs/config-schema.md` and the two runbooks (§8);
   - update root `CLAUDE.md`, `helao/hexagon/app/CLAUDE.md` and any directory `CLAUDE.md` that
     names a shim or `_hex` prefix;
   - fix the docstrings that describe current behaviour through a deleted symbol, under
     D-B7b.10's rule: `ws_publish.py`, `status.py:68–71,143–165`, `action_host.py:271`,
     `orch_host.py:1402`, `ws_frames.py:297`, `ingestion.py`, `ui_host.py`, and
     `adapters/__init__.py`.

### 5.3 Nested N2 (after P)

- **Deployment-A:** drop the `adapters.legacy` fallback, and the docstring mention in its
  transport test.
- **Deployment-A and B:** `test_config_preflight.py` asserts that gate 2 resolved ≥1 server, so
  the check is not vacuous.

Check: gate 5 on the merged parent, and the ratchet over the N2 heads.

## 6. Test dispositions (parent)

| file | disposition |
|---|---|
| `test_factory.py` | keep the `build_wiring` cases, port the bridge cases to D-B7c.1's host-level asserts (commit 1), and delete the `makeActionApp`/`makeVisApp` cases (commit 3) |
| `test_db_shim.py` | bridge assert ported in commit 1; file deleted in commit 3 |
| `test_vis_graft.py`, `test_hte_action_shims.py`, `test_hte_vis_import.py`, `test_hte_canary_reference_is_gone.py`, `test_hexconfig.py`, `test_reflex_host.py` | delete. Each pins a deleted module. `test_hte_vis_import`'s "every hte visualizer imports" assertion moves into `test_vis_gate_config.py` if that file does not already have it |
| `test_vis_hexagon_producer_parity.py` | port: build the host with the hte module's `makeApp` directly. The producer comparison does not depend on the shim |
| `live_group.py` | import `hte...async_orch2.makeApp` and `test...ws_simulator.makeApp` directly, and drop `"deployment": "hexagon"` |
| `test_engine_import_ratchet.py` | the native probe builds `ActionHost` through the hte module's `makeApp`, not `makeActionApp` |
| `test_preflight.py` | `KNOWN_HEXAGON_CONFIGS` becomes `KNOWN_STATION_CONFIGS` = the 7 hte bases + `test`. Add one positive and one negative case per new gate-2 rule (ambiguous on a synthetic tree, unresolved, leftover `legacy_module`), and a gate-3 case showing a missing checklist is reported, not failed |
| `test_analysis_resolution.py` | delete the candidate-1 cases; keep 2 and 3 |
| `test_reflex_bundle.py`, `test_reflex_entry_resolver.py`, `test_reflex_launcher.py`, `test_reflex_gate_config.py`, `test_browser_parity.py` | delete the hexagon-routing cases; keep the rest |
| `test_vis_gate_config.py`, `test_db_gate_config.py` | update for stripped configs |
| `smoke/test_golden_capture*.py` (12) | kept; point at the `<x>gold` target (D-B7c.8) |
| `station_golden_capture.py`, `test_station_golden_capture.py`, `eche10_golden_diff.bat` | the prefix is `eche10`; the `endswith("_hex")` branch goes and the config path comes from `read_config` |
| `test_sync_loop_starvation.py`, `test_sync_parent_requeue.py` | docstring station names → "a private station" (Q12) |
| tests importing `adapters.legacy` (19) | import path only (commit 4) |

**A plan-authored test has to fail first.** For each new assertion, the plan records its red run
against the unfixed code: bridge-bound, `OrchHost`-unbound, preflight-ambiguous, both ratchet
halves, and the smoke-leftover rule (`plan-authored-tests-must-be-falsifiable`).

## 7. Gates

These run on the branch head, in addition to each commit's check.

1. **Ratchet**, both halves at zero (D-B7c.11), over P and the N2 heads.
2. **Resolved composition.** R(after) is computed on the P head with N1 heads copied in **and all
   private copies present**. It must equal R0 for every surviving config, keyed by base name.
   - That covers ports, params and `root:` for all 12 stations.
   - The only allowed difference is the explicit `deployment:` values D-B7c.5 adds, each equal
     to the R0 target's deployment.
   - It must also show `test.ws_simulator` for every `htereflex`/`htehexreflex` `ws_simulator`
     entry, with Deployment-A present. This is the check that the 11-entry flip did not happen;
     gates 6 and 8 cannot see it.
3. **Preflight `OK` on every surviving config in all four repos**, with gate 2 non-vacuous: ≥1
   server resolved per config. Gate-3 `no checklist` lines are recorded in the PR, not failed.
4. **Full `run_tests.py` in the bare worktree.** The failing set equals F0 less deleted files.
5. **Private copies** (B7b §7 gate 5 procedure): the failing set equals F0p less deleted files.
   Afterwards `git -C <wt> status --short` must be empty.
6. **Route surface, Linux live.**
   - Launch `goldenhexgraft` and `goldenhexvis` (stripped), capture O1, and run
     `openapi_diff.py` O0 O1. The diff must be empty for every action server, and every Bokeh
     server returns HTTP 200 on its document.
   - One `goldenhexgraft` sequence reaches `RUNS_FINISHED`/`RUNS_SYNCED`.
   - This passes largely by construction, because a shim returned the wrapped module's own
     `ActionHost`. Its value is catching a broken launch, not a route difference.
7. **`run_unit_tests.py` passes; `pyright --outputjson`** on the changed files reports no new
   errors. `filesAnalyzed` must equal the count of surviving changed `.py` files and be >0
   (`pyright-vacuous-in-worktrees`).
8. **Station, user-run, before merge: eche10.**
   - Task 0 at the station, on the pre-B7c checkout: capture every action server's
     `/openapi.json` under `eche10_hex`.
   - Cut over per §8, then capture under `eche10`. `openapi_diff.py` must be empty for every
     server.
   - One short sequence reaches `RUNS_SYNCED`.
   - `CTRL-x` tears down, and `STATES/pids_eche10_.pck` is cleared.
   - The other hte stations and Deployment-A/B/C stations cut over at their next use, recovering
     per D-S1 if they need to.
9. **`black`** on every changed file, in its own repo, immediately before each `git add`.

## 8. Station cut-over

1. **Before pulling *any* repo, stop *every* running group on the station (`CTRL-x`)**, `_hex`
   or not. If a group was detached (`CTRL-d`), reconnect with `./helao.sh <prefix> --reconnect`
   first. There are three reasons:
   - Bare-launched private bases also run through shims (§2.4).
   - The hot-reload watcher works per repo, so it would restart idle servers into a deleted
     shim or a `fast: graft` key: an `ImportError`.
   - A running `_hex` group is invisible to a `<x>` launch (§2.7).
2. Pull the parent and every nested repo the station uses.
3. Run `rm -rf helao/deploy/hexagon helao/hexagon/adapters/legacy`, or on Windows `cmd`
   `rmdir /s /q helao\deploy\hexagon` and `rmdir /s /q helao\hexagon\adapters\legacy`. That
   clears untracked `__pycache__`; the ratchet's runtime half fails until it is done.
4. Run `python -m helao.hexagon.preflight <x>` on the exact config the station will launch. That
   catches an untracked station-local copy that still carries routing keys. It must print
   `PREFLIGHT OK`.
5. Run `./helao.sh <x> --restore` (Windows: `helao.bat <x> --restore`). Queues exported under
   `<x>_hex` are imported (§2.7). Expect one Reflex bundle rebuild.
6. The stale `STATES/pids_<x>_hex_.pck` is harmless and may be deleted.
7. Rollback: stop the group, check out `freeze/pre-b7c-rename_2610` in every repo, and launch
   `<x>_hex`.

Runbook edits:

- **The B5 and P7 runbooks:** replace `<x>_hex` launch lines with `<x>` and add steps 1, 3 and 4
  above as a dated "after B7c" block. Earlier dated sections are left as provenance.
- **`docs/config-schema.md`:** drop `legacy_module`, `graft` and `deployment: hexagon`. Document
  `deployment:` as "the deployment that owns the module, required only when auto-detection is
  ambiguous (preflight says so)".

## 9. Risks

- **A station pulls B7c with any group running.** Hot reload restarts servers into an
  `ImportError`. Mitigation: §8 step 1 in the PR description and runbooks; the failure is loud.
- **A `<x>` launch beside a forgotten `<x>_hex` group.** Its servers fail to bind, and the old
  group keeps serving. Mitigation: §8 step 1. A cross-prefix port check in `launch.py` is out of
  scope (Q14).
- **An untracked station-local config still carrying routing keys.** §8 step 4 catches it before
  launch.
- **The `ws_simulator` fallback flip (§2.4).** Without D-B7c.5, three configs would silently
  serve Deployment-A's simulator on any host with Deployment-A checked out. Preflight makes it
  an error, and gate 2 asserts the resolved module with Deployment-A present.
- **Latent ambiguity that depends on which repos are present** (`calc_server`, §2.4). D-B7c.5
  catches it only where the colliding repos are checked out when preflight runs. A host with a
  different set of private repos can resolve differently. Gate 2 and §8 step 4 run with the
  station's actual set.
- **Stale `__pycache__`** makes `helao.deploy.hexagon` importable as a namespace package. The
  ratchet's runtime half fails, and §8 step 3 fixes it. At launch no `.py` exists, so the
  launcher's glob ignores it.
- **A gate that ran the main checkout's code** (B7b §9). Every gate asserts `helao.__file__` is
  under the worktree.
- **A nested N1 that silently depends on new parent behaviour.** Its check runs against
  current `unstable`, not against P. Deployment-A's `try`/`except` import is exercised on both.
- **Equivalence asserted, not observed, on private stations.** Gate 2 proves composition
  identity, and gate 6 shows sims launch. Hardware-route identity is observed on eche10 only.
  D-S1 is the backstop for the rest.

## 10. What B7c does not do

- **No launcher edits.** `launch.py`, `fast_launcher.py`, `bokeh_launcher.py` and
  `config_loader.py` keep their resolution rules and their ambiguity *warning*.
- **No class renames** inside `adapters/shared/` (`Legacy*Adapter`), and no rename of
  `helao.hexagon.preflight`, `hexagon_wiring` or `hexagon_ws_bridge`.
- **No renames of test fixture configs** (`goldenhex*`, `htehexreflex`, smoke baselines), and no
  merging of the now-near-duplicate golden pairs.
- **No new frozen checklists**, including for `xafs_server` and `cpsim_server` (Q15).
- **No change to** `StatusPort`'s publish members, `WsPublishBridge`, the WS frame encoding,
  `params.limit_vis`, the 0.3 s sleep or the finish-drain window.
- **No edits to** provenance text in specs, plans or nested `docs/`, or to frozen checklists.
- **The fourth private deployment** is not touched.
- **No new freeze rule** for the private repos beyond creating the branch (D-S1's out-of-band
  rule stands).

## 11. Done

B7c is done when:

- `helao/deploy/hexagon/`, `hexconfig.py`, `reflex_host.py`, `makeActionApp`, `makeVisApp` and
  `VIS_REQUIRED` are gone and cannot be imported.
- No tracked config in any repo carries `legacy_module`, a `graft` code key or
  `deployment: hexagon` in any form, and no `_hex` variant exists.
- Every `ActionHost` other than `OrchHost` binds the WS bridge in `__init__`.
- `adapters/shared/` replaces `adapters/legacy/` in all four repos' code, with no fallback left in
  Deployment-A.
- Preflight resolves every server the way the launcher does, and rejects ambiguity.
- Gates 1–9 hold. Gate 8 (eche10 on `eche10`) is recorded in the PR before merge, and the
  N1/P/N2 merge order is recorded in each PR.

## 12. Open questions

Each question has a default, which the plan adopts unless the user overrides it.

- **Q1: landing order.** **Default:** N1 ×3 → P → N2, as D-B7c.10 sets out. The alternative,
  parent first with a temporary shim alias, would put the vocabulary back that the ratchet
  forbids.
- **Q2: test-only `hex` names.** **Default:** keep the names and strip the keys (D-B7c.9).
  Renaming them touches 9–27 referencing files each, for no behaviour change.
- **Q3: smoke pairs and their drivers.** **Default:** delete each pair driver whose config dies,
  and keep a capture module only where it still has a single-config target (D-B7c.8).
  Alternative: keep every canary as a single-config launch-and-capture smoke, which means
  rewriting about 34 scripts for coverage that gates 6 and 8 already give.
- **Q4: the Reflex env seam.** **Default:** collapse it (D-B7c.4). Alternative: keep
  `HELAO_REFLEX_APP_MODULE` as an inert seam. It has no user.
- **Q5: the bridge on `OrchHost`.** **Default:** not bound (`_binds_ws_bridge = False`), which
  preserves P2b-2 D3. Binding it would be harmless, since nothing publishes, but it would be a
  new behaviour with no reader.
- **Q6: per-session config re-validation for Bokeh/Reflex** (E4/E6). **Default:** drop it. The
  launcher validates at startup, and nothing consumed the per-session wiring.
- **Q7: the freeze branch.** **Default:** `freeze/pre-b7c-rename_2610` in all four changing
  repos, pushed before P merges. A private repo whose push is denied records its local head
  in the PR instead.
- **Q8: Deployment-A's `adapters.shared` transition.** **Default:** N1 adds a `try`/`except
  ModuleNotFoundError` import that works on either parent, and N2 removes it (D-B7c.10). No
  alias exists in the parent, and there is no window. Alternative: merge N2 seconds after P
  with no fallback, which leaves a window on any station that pulls only the parent.
- **Q9: explicit `deployment:` everywhere vs only where needed.** **Default:** only where needed
  (D-B7c.2 step 3), so that hte bases stay unedited and preflight enforces the rest. Always
  writing it would touch every config in four repos.
- **Q10: preflight's home and name.** **Default:** stays `helao.hexagon.preflight`. Moving it
  changes the CLI that nested tests and runbooks invoke.
- **Q11: `configs/archive/` in Deployment-C.** **Default:** delete the archive configs. They
  cannot be launched today (§2.2), so rewriting them would only produce more unlaunchable files
  for the ratchet to scan.
- **Q12: private station names in two parent test docstrings.** **Default:** replace them with
  "a private station" in commit 5. They predate B7c, and this is a privacy fix B7c is already
  touching.
- **Q13: `Legacy*Adapter` class names.** **Default:** unchanged (§10). D-S5 names the package.
  Renaming the classes is a follow-up, if anyone wants it.
- **Q14: a cross-prefix running-group check in `launch.py`.** **Default:** no, because the
  runbook covers it. It would be the first launcher edit in the program for a one-time cut-over.
- **Q15: checklist gate scope.** **Default:** look up only the owning deployment's checklist
  directory. Fail only when a checklist that existed at `7592729b` is gone; report any other
  missing checklist without failing; freeze no new checklists in B7c (D-B7c.6 gate 3).
  Alternative: freeze `xafs_server` and `cpsim_server` checklists now. That needs live captures
  B7c's gates do not otherwise require.
