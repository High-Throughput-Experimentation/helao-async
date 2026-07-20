# hte BaseAPI system-surface checklist (spec §8.2)

Every hexagon hte action-server adapter MUST provide this shared surface.
These routes/behaviors are registered at runtime by `BaseAPI`/`Base`
(`helao/core/servers/base_api.py`, `helao/core/servers/base.py`) — the
static AST extractor in `harness/endpoints.py` cannot see them (they are not
`@app.<method>(...)` decorators on the module's own functions), so they are
enumerated here by hand as a sign-off checklist rather than frozen JSON.
The runtime `/openapi.json` cross-check against a launched server is
deferred to P3b/P3e (needs a launched hexagon server; not Linux-freezable
in this Linux-only P3-pre pass).

## Routes

- [ ] `GET /get_config`
- [ ] `GET /get_status`
- [ ] `POST /attach_client`
- [ ] `POST /stop_executor`
- [ ] `POST /{key}/estop`
- [ ] `POST /shutdown`
- [ ] `GET /get_lbuf`
- [ ] `GET /list_executors`
- [ ] `GET /loaded_modules`

## WebSocket endpoints

- [ ] `ws_status` — status broadcast websocket
- [ ] `ws_data` — data broadcast websocket
- [ ] `ws_live` — live-value broadcast websocket

## Behavioral contracts

- [ ] **Action-lifecycle POST contract** — every `/<key>/<action>` POST route
      builds an `Action` model from the request, runs it through
      `setup_and_contain_action`, and produces hlo output + status-WS
      updates per the standard lifecycle (not ad hoc per-server logic).
- [ ] **Queuing middleware** — the HTTP dispatch path queues/serializes
      concurrent action POSTs the same way legacy `Base` does.
- [ ] **Estop exception handler** — an HTTP exception raised inside an
      action route triggers estop + stop-executors, matching legacy
      behavior (not a bare 500).
- [ ] **Co-located RPC mirror** — every hexagon FastAPI server co-locates a
      ZMQ RPC server on `derive_rpc_port(port)` (composition must fail
      preflight if absent; see `.omc/notepad` memory
      "Framework server needs RPC server").

## Notes

- This checklist is the §8.2 "system surface" gate input; it complements
  (does not replace) the per-server static endpoint checklists frozen in
  Task 1 (`helao/hexagon/tests/checklists/hte/<module>.json`).
- Sign-off happens per adapter during P3b, cross-checked against a live
  `/openapi.json` where a sim-launchable config exists (`gamry.yml`).
