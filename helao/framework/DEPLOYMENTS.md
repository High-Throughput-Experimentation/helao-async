# Deployments & the framework

How a deployment relates to `helao/framework/` — the deployment-agnostic foundation.

## The split

**`helao/framework/`** is the foundation. Hexagonal layers, no deployment specifics:

- `domain/` — pure business logic (action lifecycle, orchestration FSM, sync deciders, data_browser transforms). No I/O.
- `ports/` — abstract seams (`driver`, `transport`, `storage`, `eventsink`, `clock`, …).
- `adapters/` — concrete I/O impls of the ports (fs storage, http/zmq transport, NTP clock, bokeh ws-subscriber, operator backend, loaders).
- `app/` — the only layer where FastAPI/Bokeh live: `base_api` (`Base`/`BaseAPI`), `orch_api` (`OrchDriver` + ZMQ RPC server), `vis` (`Vis`/`HelaoVis`/`makeBokehApp`), `operator/bokeh_operator`, `factory.makeApp`, and **`app/servers/`** — generic, ready-to-launch server entry points (orchestrator, standalone_operator, live/action visualizer hosts, data_browser).
- `support/` — vendored cross-cutting utils (config_loader, logging, dispatcher, helao_dirs, time, codehash, …).
- `models/` — the unified pydantic domain models.

**`helao/deploy/<name>/`** is one deployment. It holds only what is genuinely
deployment-specific:

| In a deployment | What it is |
|---|---|
| `configs/*.yml` | the server group: which servers, hosts/ports, libraries, vis wiring |
| `drivers/` | hardware backends (vendor code) implementing the `HelaoDriver` port |
| `servers/action/*.py` | thin `makeApp(server_key)` factories wrapping a driver via framework `BaseAPI` |
| `experiments/`, `sequences/` | the science — the action/experiment/sequence library code |
| `servers/visualizer/*_vis.py` | per-instrument `C_vis` subclasses of framework `VisSubscriber` |
| (optional) custom operator, `processors/`, `specifications/`, `layouts/` | anything truly bespoke |

## The contract

A deployment depends **only on `helao/framework/`**. Never on another deployment,
never on each other, never on legacy `helao/core` once migrated.

**Smell test:** if two deployments would copy it, it belongs in the framework, not in a
deployment. (A deployment reaching into another deployment's code is the signal that the
borrowed code is actually deployment-agnostic and should move into the foundation.)

## Generic server apps: `deployment: framework`

A deployment does **not** write its own orchestrator/operator/visualizer-host modules.
Those generic apps live in `helao/framework/app/servers/`. A config references them by
adding `deployment: framework` to the server entry:

```yaml
servers:
  ORCH:
    group: orchestrator
    fast: orchestrator          # -> helao.framework.app.servers.orchestrator.makeApp
    deployment: framework
    host: 127.0.0.1
    port: 8001
  OPERATOR:
    group: operator
    bokeh: standalone_operator  # -> helao.framework.app.servers.standalone_operator.makeBokehApp
    deployment: framework
    host: 127.0.0.1
    port: 5001
    params: {orch_key: ORCH}
```

The launchers (`fast_launcher.py` / `bokeh_launcher.py`) resolve `deployment: framework`
→ `helao.framework.app.servers.<module>`; any other value uses the per-deployment path
`helao.deploy.<deployment>.servers.<group>.<module>` (the unchanged default). For a
framework-hosted visualizer, `CONFIG["deployment"]` stays the real deployment so the
per-instrument `*_vis.py` still resolve from that deployment.

So a deployment writes only its unique parts (drivers + science + config + bespoke UIs)
and inherits the rest from the foundation.

## Parent-tracked vs private deployments

`test` and `hte` are tracked in this repo. **Other deployments are private — separate git
repos nested under `helao/deploy/` and git-ignored by the parent** (invisible to parent
`git status`; commit inside the deployment dir with its own git).

Mapping is identical regardless of who owns the repo: every deployment is a
`helao/deploy/<name>/` directory built against `helao/framework/`. A private deployment
migrates onto the framework with the **same pattern** as `test`/`hte` — but **in its own
repo, on its own branch, on its own schedule**:

1. import-swap its `servers/` + `drivers/` from `helao.core`/`helao.helpers` → `helao.framework.*`
2. repoint configs: `deployment: framework` for the generic apps
3. repoint per-instrument `*_vis.py` to the framework vis base classes
4. hardware smoke + cut-over, gated

Because the framework is stable and deployment-agnostic, each deployment migrates
independently — no coordination with the parent repo or other deployments.

## End state

The framework is the shared, versioned foundation; every deployment — parent-tracked or
private — is a thin consumer of it: **drivers + science + config**, nothing generic. New
deployments live in their own `helao/deploy/<name>/` dir and depend only on
`helao/framework/`.

See also: `docs/superpowers/specs/2026-06-22-helao-framework-core-rewrite-design.md`
(the rewrite design) and the `test` cut-over (`SP-DEPLOY-1/2`) which established the
generic-app + `deployment: framework` pattern.
