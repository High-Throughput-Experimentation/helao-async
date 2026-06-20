# Migrate to Standalone-Only BokehOperator

Date: 2026-06-19
Status: Approved (design), pending implementation plan

## Goal

Make the standalone Bokeh operator the **only** `BokehOperator` implementation.
Deprecate and remove the integrated (in-orchestrator) operator and its
`LocalBackend`, strip all operator/Bokeh dependencies from the orchestrator, and
launch the operator as a normal `group: operator` Bokeh server in every in-scope
config.

## Background

Two operator code paths exist today:

- **Integrated**: `Orch.start_operator()` starts a Bokeh `Server` inside the
  orchestrator process. `makeBokehApp()` builds
  `BokehOperator(vis, LocalBackend(orch))`. `LocalBackend` calls `Orch` methods
  in-process; `_OpShim` + `Orch.update_operator()` push live updates via an
  in-process `asyncio.Queue`. Enabled by `ORCH.params.enable_op` /
  `bokeh_port`.
- **Standalone**: a `group: operator` Bokeh server
  (`helao/deploy/hte/servers/operator/standalone_operator.py`) builds
  `BokehOperator(vis, RemoteBackend(...))`. `RemoteBackend` talks to the
  orchestrator over HTTP + the Base status WebSocket, with a poll fallback.

Both backends implement all 25 methods of the `OrchBackend` ABC
(`helao/core/servers/operator/orch_backend.py`) with identical signatures —
**confirmed full feature parity**. The standalone path additionally
auto-imports `sequence_lib`/`experiment_lib` and self-discovers the orch server.

## Decisions (locked)

1. **Scope**: deployments `hte`, `test`, `priv`, `lila`, `mea`. **Exclude
   `lila_gl`.** `priv`, `lila`, `mea` are separate nested git repos and get
   their own commits.
2. **Module home**: keep the single copy
   `helao/deploy/hte/servers/operator/standalone_operator.py`. The bokeh
   launcher globs `helao/deploy/*/servers/<group>/<bokeh>.py` across
   deployments, so every config's `bokeh: standalone_operator` resolves to this
   one file (already true for `test`).
3. **Cleanup depth**: full strip of integrated-operator machinery. **Keep** the
   `OrchBackend` ABC as the documented contract `RemoteBackend` implements.
4. **Operator server key**: `OPERATOR`.
5. **Operator port**: reclaim the **same port the integrated operator used in
   that config** (its old `bokeh_port`). This avoids new collisions — in
   `hte`/`mea`/3 `priv` configs port 5001 is the `VIS` server and the operator
   used 5002.

## Architecture (after)

One operator path. The operator is an ordinary `group: operator` Bokeh server
launched by `bokeh_launcher.py` (LAUNCH_ORDER places `operator` right after
`orchestrator`). It is fully decoupled from the orchestrator process and
communicates only over HTTP + the orchestrator's Base-provided status
WebSocket. The orchestrator imports no Bokeh and no operator code.

## Changes by area

### 1. `helao/core/servers/orch.py` — strip
- Remove imports: `from bokeh.server.server import Server`,
  `from ...operator.bokeh_operator import BokehOperator`, and the lazy
  `from ...operator.orch_backend import LocalBackend`.
- Delete methods `start_operator()` and `makeBokehApp()`.
- Delete the `myinit()` branch that calls `start_operator()` (the
  `if self.op_enabled:` gate).
- Delete attributes `self.bokehapp`, `self.orch_op`, `self.op_enabled`.
- Delete `update_operator()` and **all** its call sites
  (`await self.update_operator(True)` — ~8 occurrences).
- **Keep**: `step_thru_*` flags, `status_summary`, the queue deques, and every
  control/list method + FastAPI endpoint — `RemoteBackend` drives these over
  HTTP and reads live state over the status WebSocket.

### 2. `helao/core/servers/operator/orch_backend.py` — strip
- Delete `_OpShim` and `LocalBackend`.
- Remove imports only those two used.
- **Keep** `OrchBackend` (ABC) and `RemoteBackend`.

### 3. `helao/helpers/config_loader.py`
- `OrchServerParams`: keep an `enable_op` field (deprecated, ignored) so the
  untouched `lila_gl` config still validates; ensure no code reads `enable_op`
  or `bokeh_port`. If the model forbids extra keys, leaving the field in place
  is what prevents a validation error on legacy configs.

### 4. Configs — per config (in-scope only)
For each config that had `ORCH.params.enable_op`:
- Remove `enable_op` and `bokeh_port` from the orchestrator `params`.
- Add an operator server entry whose port **equals the removed `bokeh_port`**:

```yaml
OPERATOR:
  group: operator
  bokeh: standalone_operator
  host: <same host as the orchestrator server>
  port: <reclaimed bokeh_port>
  params:
    orch_key: <orchestrator server key, e.g. ORCH>
    poll_interval: 5
```

For `.py` configs (`lila/electrode-demo.py`, `lila/simulation.py`) add the
equivalent dict entry.

`test/configs/test.yml` special case: it already has a `STANDALONE_OP` entry on
port 5004 plus `ORCH` `enable_op/bokeh_port: 5001`. Rename `STANDALONE_OP` →
`OPERATOR`, set its port to **5001** (the reclaimed orch `bokeh_port`), and
remove `enable_op/bokeh_port` from `ORCH`.

#### Per-config operator port (reclaimed)

| Deployment | Configs | Operator port |
|---|---|---|
| hte | adss, adss3, anec, ccsi1, ccsi2, clad, eche4, eche5, eche6, eche7, eche8, eche10, ecms1, ecms2, hispec, partialccsi1, power_supply_test, uvis, xrfs1 | 5002 |
| mea | amts | 5002 |
| priv | icpm1, note1, xrfs_priv1 | 5002 |
| priv | test_alert, uvis4 | 5001 |
| lila | electrode-demo, simulation | 5001 |
| test | test, demo0, ws_demo | 5001 |
| test | demo1 | 5011 |

Implementation must, per config: read the actual orch server key and host
(don't assume `ORCH`/host), confirm the reclaimed port is not already taken by a
non-operator server, and confirm `group: operator` uniqueness rules in
`launch.py` are satisfied (unique key, unique host:port).

### 5. Tests — `helao/core/tests/test_standalone_operator.py`
- Delete the `LocalBackend`/`_OpShim`-based cases (`test_local_backend_move_remove`,
  `test_local_backend_get_queue_object`, and any other test importing
  `LocalBackend` or `_OpShim`).
- Keep `RemoteBackend`, `BokehOperator`, and orch queue-mutation tests.

## Testing / verification

- `python helao/core/tests/test_standalone_operator.py` → all pass.
- `python helao/deploy/test/tests/test_data_browser.py` → all pass.
- `python run_unit_tests.py` → exit 0.
- Grep: no remaining references to `LocalBackend`, `_OpShim`,
  `update_operator`, `start_operator`, or `makeBokehApp` in `orch.py`; orch.py
  has no `bokeh` import.
- Each in-scope config loads via `read_config` without validation error.
- Smoke (manual): launch `test` config; confirm the operator serves on 5001 and
  connects to the orchestrator (queue/start/stop work end to end).

## Risks / mitigations

- **Port collisions**: avoided by reclaiming the exact prior operator port per
  config; implementation still verifies the port is otherwise free.
- **Update latency**: the in-process push (`update_operator`) is gone;
  `RemoteBackend` relies on the status WebSocket plus a 5 s poll. Acceptable;
  matches the already-shipped standalone behavior.
- **Legacy `enable_op` in untouched configs** (`lila_gl`): kept as an ignored
  field in `OrchServerParams` so those configs still validate.
- **Nested-repo commits** (`priv`, `lila`, `mea`): each requires `cd` into the
  deployment and a commit on its own remote/branch.

## Out of scope

- `lila_gl` deployment.
- `helao/core/servers/operator/helao_operator.py` (separate non-Bokeh operator;
  untouched).
- Any change to `BokehOperator` UI behavior.
