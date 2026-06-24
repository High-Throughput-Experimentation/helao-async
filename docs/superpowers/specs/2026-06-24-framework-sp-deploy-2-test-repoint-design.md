# Framework SP-DEPLOY-2 — Test Deployment Repoint (design)

**Date:** 2026-06-24
**Branch:** `feat/framework-deploy-test-repoint`
**Cycle:** Deployment cut-over (second sub-project; integration capstone).

## 1. Context

SP-DEPLOY-1 extracted the generic Bokeh server apps into
`helao/framework/app/servers/` (operator + live/action visualizer hosts).
SP-DEPLOY-2 repoints the **`test`** deployment onto the framework so it stops
reaching into `hte`, and proves the wired deployment launches end-to-end.

Decisions (user): **launcher framework-path resolution** (no per-deployment shims)
and **launch the test group** for real smoke. Production `hte` migration stays
gated (master design §8).

Two facts discovered:
- The launcher already supports a per-server `deployment:` override
  (`fast_launcher.py:78`, `bokeh_launcher.py:91` — "where the app module
  physically lives; may differ when a generic app is reused"). The path template is
  `helao.deploy.{deployment}.servers.{group}.{module}`.
- The launcher populates the **legacy** `helao.helpers.config_loader.CONFIG`
  (`fast_launcher.py:53-55`), but the framework `HelaoVis` / data_browser read the
  **separate** `helao.framework.support.config_loader.CONFIG`, which is `None` at
  launch. The framework apps would fail without a bridge. (Same root as the
  SP-DEPLOY-1 operator carry-forward: `RemoteBackend.import_autolibs` also reads the
  legacy `CONFIG`.)

## 2. Goal & non-goals

**Goal:** Launch the `test` orchestration group on the framework: a launcher
`deployment: framework` resolution path → `helao.framework.app.servers.<module>`;
a framework config-global bridge so framework apps see the loaded config; framework
orchestrator + data_browser entry points; repointed `test` configs and
per-instrument `*_vis.py`; and a live bring-up smoke.

**Non-goals:**
- `hte` production migration (gated; this only repoints `test` sims).
- Changing the wire protocol, the framework domain/app modules (reuse as built).
- Removing the legacy `core` modules (they stay for `hte` until its gated cycle).
- Rich browser-driven UI assertion (best-effort headless bring-up; the human can
  open the operator/visualizer in a browser).

## 3. Components

### 3.1 Launcher framework-path resolution (shared infra — careful, additive)

In **both** `fast_launcher.py` and `bokeh_launcher.py`, add a backward-compatible
branch: when a server entry sets `deployment: framework`, resolve the app module
from `helao.framework.app.servers.{module}` instead of
`helao.deploy.{deployment}.servers.{group}.{module}`. All existing configs (no
`deployment: framework`) resolve exactly as before — a pure additive branch, no
change to the deploy-path default or the auto-detect glob.

### 3.2 Framework config-global bridge (the integration fix)

When the launcher loads the config (it sets `helao.helpers.config_loader.CONFIG`),
also publish it to the framework global:
`helao.framework.support.config_loader.CONFIG = helao.helpers.config_loader.CONFIG`.
Do this once in each launcher's config-resolution path (a 2-line addition, guarded
so it only sets when the framework global is unset / mirrors the legacy one). This
makes framework `HelaoVis`, the orchestrator entry, and `import_autolibs`-consuming
backends all see the loaded config. (Both globals reference the same `Munch`.)

> Alternative considered: make `framework.support.config_loader` delegate to the
> legacy global. Rejected — keeps the two modules independent; the launcher is the
> single place that already owns config publication, so it bridges once.

### 3.3 Framework orchestrator entry — `app/servers/orchestrator.py`

`makeApp(server_key) -> FastAPI` (the launcher's 1-arg contract). Reads the
(now-bridged) framework `CONFIG`: builds the `sequence_lib`/`experiment_lib` from
the config's `experiment_libraries`/`sequence_libraries` (reusing the framework's
library loader / `import_autolibs` seam), derives `action_servers` from
`CONFIG["servers"]`, and calls `factory.makeApp(server_key, group="orchestrator",
sequence_lib=..., experiment_lib=..., action_servers=...)`. This is the orchestrator
config→libs/action_servers wiring SP-DEPLOY-1 deferred, plus it lets the SP-ORCH-4
heartbeat populate `status_summary` (now `action_servers` is supplied).

### 3.4 Framework data_browser entry — `app/servers/data_browser.py`

`makeBokehApp(doc, confPrefix, server_key, helao_repo_root) -> doc` — framework
`HelaoVis` + framework `build_document` (from `app/data_browser`). Mirrors the
current test `data_browser.py` shim with framework imports.

### 3.5 Repoint `test` configs

In `helao/deploy/test/configs/{test,demo0,demo1,ws_demo}.yml`, add
`deployment: framework` to the orchestrator (`async_orch2` → `orchestrator`),
operator (`standalone_operator`), generic visualizer (`action_visualizer`/
`live_visualizer`), and `data_browser` server entries, and update each `fast:`/
`bokeh:` value to the framework module name where it differs (e.g.
`fast: orchestrator`). The per-instrument `action_vis`/`live_vis` keys (pointing at
the test `*_vis.py`) are unchanged.

### 3.6 Repoint `test` per-instrument `*_vis.py`

`gpsim_live_vis.py`, `oersim_vis.py`, `wssim_live_vis.py`: change imports
`helao.core.servers.vis` → `helao.framework.app.vis`,
`helao.core.servers.vis_subscriber` → `helao.framework.adapters.vis_subscriber`,
`helao.core.models.hlostatus` → `helao.framework.models.hlostatus` (and any other
`helao.core` model imports → framework). The `C_vis` subclass bodies are unchanged.
Also repoint the test `data_browser.py` shim (or drop it in favor of the §3.4
framework entry referenced via `deployment: framework`).

### 3.7 Resolve the SP-DEPLOY-1 operator carry-forwards

- `import_autolibs` legacy-CONFIG: resolved by §3.2 (the legacy global is populated
  at launch; the framework global mirrors it). Verify the operator backend autoload
  works at launch.
- `RemoteBackend.subscribe` needs a running loop: satisfied under the bokeh server
  (a live event loop). No code change; confirmed by the launch smoke.

## 4. Test / smoke strategy

1. **Unit/wiring tests** under `helao/framework/tests/`:
   - Launcher framework-path resolution: a unit test that the resolver builds
     `helao.framework.app.servers.<module>` when `deployment == "framework"` and the
     legacy deploy path otherwise (extract the path-resolution into a tiny pure
     helper if needed to test without spawning processes).
   - Config-global bridge: after the launcher's load step, both
     `config_loader.CONFIG` globals reference the same object.
   - `app/servers/orchestrator.py` `makeApp` builds an orchestrator app from a
     minimal CONFIG (empty libs ok) with `action_servers` derived from `servers`.
   - `app/servers/data_browser.py` `makeBokehApp` smoke (fake doc + CONFIG), mirrors
     the SP-VIS-2 data_browser app test.
2. **Live bring-up smoke** (the user-requested "launch the test group"):
   `python launch.py <test prefix>` for a sims-only config; confirm every server
   reaches a healthy/ready state (the launcher's readiness + an HTTP probe of each
   FastAPI server's health/openapi, and that each Bokeh app serves a document
   without error); then terminate the group (`CTRL-x` / process teardown). Capture
   the launch log. Browser-driven operator interaction is best-effort/manual.
3. Full framework suite + AST boundary check stay green; **existing non-framework
   deployment resolution is unchanged** (a config without `deployment: framework`
   resolves as before — covered by the resolver unit test).

## 5. Error handling

- Unknown framework module under `deployment: framework` → clear ImportError naming
  `helao.framework.app.servers.<module>` (mirror the existing deploy-path error).
- Missing libs/action_servers in CONFIG → orchestrator entry builds with empty maps
  (heartbeat no-op; dispatch with no libs is a config error surfaced at run).

## 6. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Launcher change breaks ALL deployments (incl. production hte) | Additive branch only; default path unchanged; resolver unit test asserts non-framework configs resolve exactly as before |
| Framework apps see no config at launch | §3.2 bridge publishes the loaded config to the framework global; live smoke confirms bring-up |
| Operator autoload / subscribe fail at launch | §3.7 + live smoke; autoload reads the bridged legacy CONFIG, subscribe gets the bokeh loop |
| Live launch not fully verifiable headless | Assert FastAPI readiness + Bokeh document-serves-without-error via HTTP; browser UI is best-effort/manual; report exactly what was verified |
| Repointed `*_vis.py` mounted correctly | Bring-up smoke + the SP-VIS vis_subscriber tests already cover the base classes |

## 7. Done criteria

- Launcher resolves `deployment: framework` → `helao.framework.app.servers.<module>`
  (both launchers), default path unchanged; framework config global bridged.
- `app/servers/orchestrator.py` + `app/servers/data_browser.py` entries exist.
- `test` configs + `*_vis.py` repointed to the framework; no remaining
  `helao.core.servers` import in `helao/deploy/test/**`.
- Unit/wiring tests pass; full framework suite green; boundary green.
- The `test` group launches and all servers come up (smoke log captured); teardown
  clean.
- `hte` and `helao/core` untouched (gated).
