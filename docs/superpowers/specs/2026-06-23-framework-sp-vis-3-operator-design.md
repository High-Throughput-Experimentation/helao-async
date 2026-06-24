# Framework SP-VIS-3 — Operator UI Port (design)

**Date:** 2026-06-23
**Branch:** `feat/framework-vis-operator`
**Cycle:** Operator / data_browser Bokeh UI migration (third and final sub-project;
see `2026-06-23-framework-sp-vis-1-foundation-design.md` for the cycle decomposition).

## 1. Context

The Bokeh UI migration cycle (full port into framework layers) decomposed into:

1. **SP-VIS-1 Foundation** — DONE. `app/vis.py`, `adapters/vis_subscriber.py`, `support/helao_dirs.py`.
2. **SP-VIS-2 data_browser** — DONE. `domain/data_browser.py`, `adapters/data_browser/*`, `app/data_browser.py`.
3. **SP-VIS-3 Operator UI** — this spec.

The legacy operator lives in `helao/core/servers/operator/` and is already cleanly
layered behind an abstraction:

| Legacy module | Responsibility | LOC |
|---|---|---|
| `bokeh_operator.py` | `BokehOperator` — the Bokeh operator UI; talks ONLY to an injected `OrchBackend` | 2800 |
| `orch_backend.py` | `OrchBackend` (ABC seam) + `RemoteBackend` (drives a remote orch over OrchAPI HTTP/RPC + Base status WS) | 301 |
| `helao_operator.py` | `HelaoOperator` — a sync programmatic orch client (private_dispatcher) | 149 |

`BokehOperator(vis, backend)` receives a backend instance; `RemoteBackend` calls
~25 orchestrator private endpoints (`list_sequences`, `list_experiments`,
`list_actions`, `get_queue_object`, `get_histories`, `get_status_summary`,
`get_orch_state`, `add_sequence`, `add_split_sequences`, `prepend_sequences`,
`move_sequence`, `remove_sequence`, `start`/`stop`/`skip`/`estop`, `clear_*`,
`set_step_flag`, …) via `async_private_dispatcher`, plus a status WebSocket.

## 2. Goal & non-goals

**Goal:** Port the operator (UI + orch backend port/adapter + programmatic client)
into the framework `ports/`, `adapters/`, and `app/` layers, standing on
SP-VIS-1's `app/vis.py`, with the existing test suite ported. Pure addition.

**Scope decision — wire-protocol-only.** The operator is presentation that speaks a
wire protocol; it is orthogonal to which orchestrator implements that protocol.
`RemoteBackend` dispatches HTTP/WS to whatever orchestrator the config's
`orch_key` resolves (the legacy orch today). The framework `app/orch_api.py`
currently exposes only `start`/`stop`/`skip`/`estop`/`clear_estop`/`globstat` —
**not** the ~25 endpoints `RemoteBackend` calls. Closing that gap is a **separate
framework-orch-completion concern, explicitly out of scope here**. The
`OrchBackend` ABC isolates this: the UI is fully exercised in tests via a
`FakeBackend`, and a real framework orch can be wired later without touching the UI.

**Non-goals:**
- Adding the missing endpoints to framework `app/orch_api.py` (separate orch cycle).
- Rewiring deploy operator servers (`standalone_operator.py`, `gcld_operator.py`)
  — they keep importing legacy `core/`; cut-over is the deployment-migration cycle.
- Splitting the 2800-LOC `bokeh_operator.py` (port as-is; restructuring a monolithic
  Bokeh UI mid-port is high-risk and unrelated to the layer move).
- Extracting the operator's pure helpers (run-id sharing, prepend ordering, queue
  payload shaping) into `domain/` — they stay inline (port-as-is).
- Porting `premodels.Sequence/Experiment`, `to_json.parse_bokeh_input`,
  `import_autolibs` — reused as strangler-fig seams (see §4.5).
- Any change to legacy `core/servers/operator/**`.

## 3. Boundary contract (from master design §3)

- `ports/` — abstract seams; pure (`abc`/`typing` only). `OrchBackend` lives here.
- `adapters/` — implement ports / do I/O (HTTP dispatch, WebSocket, library autoload).
  `RemoteBackend`, `HelaoOperator` live here. Never imported BY `domain/`.
- `app/` — Bokeh wiring. `BokehOperator` lives here, depends on the **injected**
  `OrchBackend` port (type only) + `app/vis.py` + framework models; it does **not**
  import `adapters/` (the deployment `makeBokehApp` injects the concrete backend).

The AST boundary check (`helao/framework/tests/test_boundaries.py`) must stay green.
`app/` importing `ports/` and `app/vis` is fine; `app/operator` importing `adapters/`
is to be avoided (backend is injected).

## 4. Components

### 4.1 `helao/framework/ports/operator_backend.py`

Ports the `OrchBackend` ABC from `orch_backend.py` verbatim — the abstract seam the
UI consumes. Imports only `abc`/`typing`. Declares the full abstract surface
(`unpack_sequence`, `get_step_flags`, `set_step_flag`, `list_sequences`,
`list_experiments`, `list_actions`, `get_queue_object`, `get_histories`,
`get_status_summary`, `get_orch_state`, `add_sequence`, `add_split_sequences`,
`prepend_sequences`, `move_sequence`, `remove_sequence`, `start`, `stop`, `skip`,
`estop`, `clear_sequences`, `clear_experiments`, `clear_actions`, `subscribe`,
`close`) plus the documented class attributes (`sequence_lib`, `experiment_lib`,
`sequence_codehash`, `experiment_codehash`).

### 4.2 `helao/framework/adapters/operator_backend.py`

Ports `RemoteBackend(OrchBackend)` from `orch_backend.py` near-verbatim. Import
repoints:
- `OrchBackend` ← `helao.framework.ports.operator_backend`.
- `async_private_dispatcher` ← `helao.framework.support.dispatcher`.
- `ErrorCodes` ← `helao.framework.models.errors`.
- **Seams (reused from legacy):** `helao.helpers.import_autolibs.import_autolibs`,
  `helao.helpers.ws_utils.WsSubscriber`.

Public surface preserved: `RemoteBackend(vis, orch_key=None, poll_interval=5.0)`,
`_call`, the list/state/mutation methods, `subscribe`, `close`,
`_detect_orch_key`. Normalized-plain-dict return contract unchanged.

### 4.3 `helao/framework/adapters/helao_operator.py`

Ports `HelaoOperator` from `helao_operator.py`. Import repoints:
- `private_dispatcher` ← `helao.framework.support.dispatcher` (present, alongside `async_private_dispatcher`).
- `read_config`/`CONFIG` ← `helao.framework.support.config_loader`.
- `ErrorCodes` ← `helao.framework.models.errors`.
- **Seam:** `helao.helpers.premodels.Sequence/Experiment` (type hints / `as_dict`).

Public surface preserved: `HelaoOperator(config_arg, orch_key="ORCH")`, `request`,
`start`, `stop`, `orch_state`, `get_active_experiment`, `get_active_sequence`,
`add_experiment`, `add_sequence`, `get_latest_sequences`/`_experiments`/`_actions`.

### 4.4 `helao/framework/app/operator/bokeh_operator.py` (+ `__init__.py`)

Ports `BokehOperator` (2800 LOC) as-is. Import repoints only:
- `Vis` ← `helao.framework.app.vis`.
- `LoopStatus` ← `helao.framework.models.orchstatus`.
- `md5_string` ← `helao.framework.support.time_utils`.
- `OrchBackend` (type hint, if referenced) ← `helao.framework.ports.operator_backend`.
- **Seams:** `helao.helpers.premodels.Sequence/Experiment`,
  `helao.helpers.to_json.parse_bokeh_input`.

`BokehOperator(vis, backend)` constructor and all widget/callback/layout logic
unchanged. No `makeBokehApp` is added here (deployment wiring is out of scope); the
class is the unit deployment factories instantiate.

### 4.5 Strangler-fig seams (reused legacy, not ported)

`helao.helpers.premodels.Sequence/Experiment`, `helao.helpers.to_json.parse_bokeh_input`,
`helao.helpers.import_autolibs.import_autolibs`, `helao.helpers.ws_utils.WsSubscriber`.
Imported from `helpers/`, not `core/`; none crosses the domain boundary. Porting
`premodels` belongs to the models/orchestration cycle, not this UI port.

## 5. Data flow

```
deployment makeBokehApp (later) → BokehOperator(vis, RemoteBackend(vis, orch_key))
   BokehOperator [app/operator]  ── calls ──▶  OrchBackend port  [ports]
                                                     ▲ implemented by
   RemoteBackend [adapters] ── async_private_dispatcher / WsSubscriber ──▶ orchestrator (legacy today)
   ── normalized plain dicts ──▶ Bokeh tables/plots/state on vis.doc
```

## 6. Error handling (parity)

- `RemoteBackend._call` returns `None`/empty on dispatch failure; list methods
  default to `[]` (unchanged normalized-dict contract).
- `HelaoOperator.request` returns an `unreachable`-marked dict and
  `ErrorCodes.not_available` when the orch is unreachable (unchanged).
- `BokehOperator` callback/exception handling unchanged (port-as-is).

## 7. Test strategy

Port the existing standalone suite `helao/core/tests/test_standalone_operator.py`
(1111 LOC) to pytest under `helao/framework/tests/`, repointed at the framework
modules. It is `FakeBackend`-driven and needs no live orchestrator:

- `_MockBackend` / `_FakeOrch` / `_FakeVisOp` / `_FakeGlobalStatus` fixtures reused.
- `RemoteBackend.__new__(RemoteBackend)` + a fake `_dispatch` for dispatch/serialize
  tests (bypasses library autoload).
- Legacy `premodels.Experiment` reused as a seam in the test (matches §4.5).

Group by layer for clarity:
- `test_adapters_operator_backend.py` — `RemoteBackend` dispatch + serialize +
  prepend + queue-object payload + endpoint-helper shapes.
- `test_app_operator.py` — `BokehOperator` accepts a backend; tables from backend;
  plate API disabled by default; run-id sharing / resolve-active / split / prepend
  order; plan-buffer append-and-wrap.

**Drop** `test_shim_exposes_makebokehapp` (asserts the legacy deploy shim, untouched
here). Tests run under the `helao` conda env (3.12).

The AST boundary check must stay green: `ports/operator_backend.py` pure;
`app/operator/bokeh_operator.py` imports no `adapters/`.

## 8. API parity

Public names preserved (later deployment cut-over = import-path change only):
`OrchBackend`, `RemoteBackend`, `HelaoOperator`, `BokehOperator`, and each class's
documented method surface.

## 9. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Framework orch lacks the endpoints RemoteBackend calls | Out of scope (§2); RemoteBackend speaks the wire protocol to the running (legacy) orch; UI tested via FakeBackend |
| 2800-LOC UI port introduces drift | Import-repoint-only port (no logic edits); ported suite + parity tests; legacy left untouched |
| `app/operator` accidentally imports `adapters` | Backend injected via constructor; boundary AST test guards `app`→`adapters` |
| Seam imports read as boundary leaks | Documented (§4.5); from `helpers/`, not `core/`; not from `domain/` |
| `import_autolibs` pulls heavy deployment imports at construction | RemoteBackend autoload is unchanged from legacy; unit tests bypass it via `__new__` |

## 10. Done criteria

- `ports/operator_backend.py`, `adapters/{operator_backend,helao_operator}.py`,
  `app/operator/{__init__,bokeh_operator}.py` exist with parity APIs.
- Ported pytest suite passes under `helao` env; full framework suite still green;
  AST boundary check still green.
- No legacy `core/**` or `deploy/**` file modified (pure addition).
- Spec committed. Completes the Operator/data_browser Bokeh UI migration cycle
  (framework-orch endpoint completion + deployment cut-over remain separate cycles).
