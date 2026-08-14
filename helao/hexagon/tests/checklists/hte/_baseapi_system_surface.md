# hte BaseAPI system-surface checklist (spec §8.2)

Every hexagon hte action-server adapter MUST provide this shared surface.

## The route list moved, and why

**The authoritative route surface is now `_baseapi_system_surface.json`**, captured live from
a running action server by `harness/openapi_capture.py`. This file keeps only the *behavioral*
contracts, which no OpenAPI diff can express.

The route list that used to live here was hand-written, and it was wrong. Measured
2026-08-14 against a SIM action server launched on `goldenhex`, the real surface is **19
routes, every one `POST`** — 16 private, plus the server's own action routes and
`/<key>/estop`. The old list:

- named **9** routes, omitting eight: `_raise_exception`, `_raise_async_exception`,
  `detach_client`, `endpoints`, `hotreload_busy`, `resend_active`, `test_alert`,
  `test_receive`;
- marked **five** of the nine `GET` — `get_config`, `get_status`, `get_lbuf`,
  `list_executors`, `loaded_modules` — all of which are `POST`.

This was not a drift nobody could have known about: the note at the bottom of the old file
recorded that the runtime `/openapi.json` cross-check "is deferred to P3b/P3e (needs a
launched hexagon server; not Linux-freezable in this Linux-only P3-pre pass)". That deferral
never closed, and in the meantime the file read as authority. **Do not restore the old list
from git history believing it was ever correct.**

A host replacement gated on the old list would have shipped missing eight routes and with the
wrong method on five, and passed.

## Regenerating the JSON

```bash
export PATH=/home/dan/miniforge3/envs/helao/bin:$PATH
export PYTHONPATH=<repo root>          # absolute; a relative "." breaks child processes
python launch.py goldenhex             # SIM answers after ~30-60s; do not shorten the wait
python -c "from harness import openapi_capture as oc; \
  oc.capture_to_file('http://127.0.0.1:8002', \
  'helao/hexagon/tests/checklists/hte/_baseapi_system_surface.json')"
```

`launch.py` spawns a bare `python`, so the env must be on `PATH` — invoking it by absolute
path leaves every child on the OS interpreter and they die with `No module named 'uvicorn'`
while the launcher itself still looks healthy.

## WebSocket endpoints — invisible to the JSON

- [ ] `ws_status` — status broadcast websocket
- [ ] `ws_data` — data broadcast websocket
- [ ] `ws_live` — live-value broadcast websocket

**These do not appear in `openapi.json` at all**, so a surface diff reporting "identical"
says nothing whatsoever about them. They need their own connect-and-decode test, byte-compared
against `harness/ws_frames.py`. Their encodings are frozen per Amendment 2 §3: the `BaseAPI`
family carries a pickled `ActionModel` on `ws_status` and a pickled `DataPackageModel` on
`ws_data`, where the `OrchAPI` family carries dicts. The two families may not be converged.

## Behavioral contracts — what a route list cannot express

- [ ] **Action-lifecycle POST contract** — every `/<key>/<action>` POST route builds an
      `Action` from the request, runs it through the action lifecycle, and produces hlo output
      plus status-WS updates (not ad hoc per-server logic).
- [ ] **Queuing middleware** — the HTTP dispatch path serializes colliding action POSTs.
      Nothing in a surface diff sees this: serialized and concurrent execution both return
      200, so it must be asserted on the observed interleaving.
- [ ] **HEAD short-circuit** — the endpoint checker probes with `session.head()`. A host
      without the short-circuit answers 405 and the probe reads the server as unhealthy.
- [ ] **Estop exception handler** — an HTTP exception raised inside an action route triggers
      estop + stop-executors, matching legacy behavior, not a bare 500.
- [ ] **Co-located RPC mirror** — every hexagon FastAPI server co-locates a ZMQ RPC server on
      `derive_rpc_port(port)`. Its absence is silent, not loud: every `async_private_dispatcher`
      call falls back to HTTP after a 3 s probe timeout, presenting as a sluggish UI rather
      than a failure. Composition must fail preflight instead.
- [ ] **Action code identity** — `action_codehash`, `action_codepath` and `action_funcname`
      are written into every action record and are stripped by the golden normalizer
      (`harness/yaml_pass.py` `DROP_KEY_SUFFIXES`). **No GM diff and no surface diff can see a
      regression in these three**; they need a dedicated test.

## Notes

- This checklist complements (does not replace) the per-server static endpoint checklists in
  `helao/hexagon/tests/checklists/hte/<module>.json`, which are AST-derived and unaffected by
  the drift described above.
- `_member_surface.md` is grep-derived and likewise unaffected.
