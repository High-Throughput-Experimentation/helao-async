# Framework SP-DEPLOY-1 — Deployment-Agnostic Generic Server Apps (design)

**Date:** 2026-06-24
**Branch:** `feat/framework-deploy-foundation-apps`
**Cycle:** Deployment cut-over (first of two sub-projects).

## 1. Context

The `test` deployment's configs reference an orchestrator (`async_orch2`), an
operator (`standalone_operator`), and generic visualizer host apps
(`action_visualizer`/`live_visualizer`) — but `test` has no such modules, so the
launcher resolves them from `helao/deploy/hte/` (it even sets
`CONFIG["deployment"]="hte"`). One deployment reaching into another's code means
those modules are **not deployment-specific** — they are deployment-agnostic
generic server entry points that belong in the framework foundation. Future
deployments live in their own dirs/repos and depend only on `helao/framework/`,
never on each other or `hte`.

These shared apps are tiny thin factories (35–64 LOC) that wire already-migrated
framework modules:

| hte module | what it wires | framework modules it should use |
|---|---|---|
| `operator/standalone_operator.py` (`makeBokehApp`) | `HelaoVis` + `RemoteBackend` + `BokehOperator` | `app/vis`, `adapters/operator_backend`, `app/operator/bokeh_operator` |
| `visualizer/live_visualizer.py` (`makeBokehApp`) | `HelaoVis` + `mount_visualizers("live_vis")` | `app/vis`, `adapters/vis_subscriber` |
| `visualizer/action_visualizer.py` (`makeBokehApp`) | `HelaoVis` + `mount_visualizers("action_vis")` | `app/vis`, `adapters/vis_subscriber` |
| `orchestrator/async_orch2.py` (`makeApp`) | `OrchAPI` (legacy) | framework `makeApp(group="orchestrator")` already exists |

The cut-over is decomposed:
1. **SP-DEPLOY-1 (this spec)** — extract the generic **Bokeh** server apps into the
   framework foundation as pure additions (operator + the two visualizer hosts).
2. **SP-DEPLOY-2** — repoint the `test` deployment onto the framework (the new
   generic apps + `data_browser` + the per-instrument `*_vis.py`), wire the
   orchestrator entry (config → libs/action_servers → framework `makeApp`), and
   decide the reference mechanism (thin shims vs launcher framework-path). `hte`
   production migration stays gated.

## 2. Goal & non-goals

**Goal:** Provide framework-hosted, deployment-agnostic generic Bokeh server entry
points — `makeBokehApp` for the operator and for the live/action visualizer hosts —
built on the SP-VIS/SP-ORCH framework modules, launcher-compatible (each module
exposes `makeBokehApp`), unit-tested. Pure addition to `helao/framework/`.

**Non-goals:**
- Editing any `helao/deploy/**` file (that is SP-DEPLOY-2). SP-DEPLOY-1 adds only
  framework modules.
- The orchestrator entry: the framework already provides
  `makeApp(group="orchestrator")` (SP-ORCH-2/3/4). Wiring a deployment's
  experiment/sequence libraries + `action_servers` from config into it is
  config-aware repoint work → SP-DEPLOY-2.
- The reference mechanism (thin per-deployment shims vs a launcher framework-path)
  — deferred to SP-DEPLOY-2 (decision made there).
- `hte` production migration (gated, separate spec).
- Changing the launcher.

## 3. Boundary contract

The new modules live in `helao/framework/app/servers/` — the app layer (Bokeh
wiring). They compose `app/vis`, `app/operator/bokeh_operator`,
`adapters/vis_subscriber`, and `adapters/operator_backend`. App-layer importing
adapters is allowed (the operator app injects the concrete `RemoteBackend` backend
into the UI). AST boundary check stays green.

## 4. Components

New package `helao/framework/app/servers/` (with `__init__.py`).

### 4.1 `app/servers/action_visualizer.py`

`makeBokehApp(doc, confPrefix, server_key, helao_repo_root) -> doc` — port of hte
`action_visualizer.py` with framework imports: build `helao.framework.app.vis.HelaoVis`,
add the header banner, `mount_visualizers(app, "action_vis")` from
`helao.framework.adapters.vis_subscriber`. Signature + banner preserved.

### 4.2 `app/servers/live_visualizer.py`

`makeBokehApp(doc, confPrefix, server_key, helao_repo_root) -> doc` — port of hte
`live_visualizer.py` with framework imports; mounts `"live_vis"`.

### 4.3 `app/servers/standalone_operator.py`

`makeBokehApp(doc, confPrefix, server_key, helao_repo_root) -> doc` — port of hte
`standalone_operator.py` with framework imports: build framework `HelaoVis`, a
`RemoteBackend` (from `adapters/operator_backend`) pointed at `params.orch_key`
(or the lone `group: orchestrator` server) with `params.poll_interval` (default
5.0), and a framework `BokehOperator` (from `app/operator/bokeh_operator`) bound to
that backend; set `doc.operator = BokehOperator(app.vis, backend)`. Signature +
behavior preserved.

### 4.4 Relationship to the existing `app/vis.py` `makeBokehApp`

SP-VIS-1's `app/vis.py` already has a generic `makeBokehApp` that mounts
`"action_vis"`. `app/servers/action_visualizer.py` is the named, launcher-resolvable
entry point (the launcher imports `<module>.makeBokehApp`); it may delegate to the
`app/vis.py` builder or inline the same few lines. Keep one source of the
banner+mount logic if practical (e.g. `app/servers/*` call a shared helper), but do
not over-engineer — these are ~30-line factories.

## 5. Data flow

```
bokeh_launcher → <framework app/servers module>.makeBokehApp(doc, prefix, server_key, root)
  operator:   HelaoVis → RemoteBackend(orch_key) → BokehOperator(vis, backend) → doc.operator
  visualizer: HelaoVis + header → mount_visualizers(app, "live_vis"|"action_vis") → doc roots
```

## 6. Error handling (parity)

- Visualizer hosts: `mount_visualizers` skips servers lacking the vis key / not in
  `limit_vis` (unchanged); a missing target server leaves `connected=False` and the
  subclass returns without mounting (SP-VIS-1 contract).
- Operator: `RemoteBackend` resolves `orch_key` from `params` or the lone
  `group:orchestrator` server (its `_detect_orch_key`); behavior unchanged from the
  ported `RemoteBackend`.

## 7. Test strategy

Tests under `helao/framework/tests/` using a fake Bokeh `Document` + a minimal
`config_loader.CONFIG` (the SP-VIS-1 `test_app_vis.py` pattern — set/restore
`config_loader.CONFIG` and `helao_logging.LOGGER`):

- `test_app_servers_visualizers.py` — for both `action_visualizer` and
  `live_visualizer`: `makeBokehApp(FakeDoc(), "demo", "VIS", "/repo")` returns the
  doc with the header banner root mounted; with a config that has no server
  declaring the vis key, no error and no extra visualizer roots; with one action
  server declaring `action_vis`/`live_vis` pointing at a tiny stub `C_vis` module
  (monkeypatch `import_vis_class`), `mount_visualizers` instantiates it.
- `test_app_servers_operator.py` — `makeBokehApp(FakeDoc(), "demo", "OP", "/repo")`
  against a config with a `group:orchestrator` server: returns the doc, `doc.operator`
  is a framework `BokehOperator`. To avoid `RemoteBackend`'s eager library autoload
  doing real work, use a config with no `experiment_libraries`/`sequence_libraries`
  keys (autoload yields empty maps), or monkeypatch `RemoteBackend` lib loading;
  assert the backend is wired with the resolved `orch_key`.

Full framework suite + AST boundary check stay green.

## 8. API parity

Each module exposes `makeBokehApp(doc, confPrefix, server_key, helao_repo_root)`
(the exact launcher contract). Behavior mirrors the hte originals; only the imports
change (legacy `core` → framework). This lets SP-DEPLOY-2 repoint `test` with a
shim/path change only.

## 9. Risks & mitigations

| Risk | Mitigation |
|---|---|
| `RemoteBackend` autoload does real work in the operator test | Config with empty lib keys / monkeypatch; assert wiring, not a live orch |
| Duplicated banner+mount logic vs `app/vis.py` | Optionally share a helper; keep factories thin; tests cover both entry points |
| `app/servers` importing adapters breaks the boundary | App layer may import adapters (backend injection); AST check covers domain only — stays green |
| Drift from hte behavior | Port-with-import-swap; signature + banner preserved; SP-DEPLOY-2 smoke-tests the wired test deployment |

## 10. Done criteria

- `helao/framework/app/servers/{__init__,action_visualizer,live_visualizer,standalone_operator}.py`
  exist, each exposing `makeBokehApp` on framework modules.
- Unit tests pass under the `helao` env; full framework suite green; AST boundary
  check green.
- No `helao/deploy/**` modified (pure framework addition).
- Ready for SP-DEPLOY-2 (repoint `test`; choose the reference mechanism; wire the
  orchestrator entry).
