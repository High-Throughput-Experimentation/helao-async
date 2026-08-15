# B1 — ActionHost, registration API, and the native action session

**Date:** 2026-08-14
**Parent:** `docs/superpowers/specs/2026-08-14-legacy-separation-program-design.md`
**Baseline:** `unstable` @ `b6a475a0`, plus B0 (`feat/legacy-separation-b0-ui-rehome`)
**Privacy rule:** the private deployments are **Deployment-A/B/C** only.

**Scope change from the program spec:** B1 absorbs what the decomposition listed as B2. The
action lifecycle straddles the two — `setup_and_contain_action` is a host method that returns
an `Active` — so splitting them would put a seam through the middle of one contract. B3–B7
keep their labels; B2 is retired into this spec.

---

## 1. What B1 replaces

`deployment: hexagon` composes the app and grafts a native write path onto it, but the
*hosting* is still legacy: `makeActionApp` imports the deployment module and calls its
`makeApp`, which constructs `BaseAPI`/`Base`. B1 builds the native host that ends that, and
ports every action-server module onto it.

Measured targets, all in `helao/core/servers/`:

| module | lines | B1 disposition |
|---|---|---|
| `base_api.py` | 910 | replaced by `ActionHost` |
| `base.py` (the `Base` half) | 1545 | replaced by `ActionHost` + `ActionSession` |
| `base_status.py` | 406 | replaced (status fold already exists in `hexagon/domain/status_fold.py`) |
| `base_endpoints.py` | 121 | replaced |
| `base_live_buffer.py` | 126 | replaced |
| `base_meta_writer.py` | 172 | already native (`adapters/native/meta_writer.py`) — host binds it directly |
| `base_action_queue.py` | 77 | replaced |
| `base_primitives.py` | 22 | replaced |
| `active_data_file.py` | 449 | already native (`adapters/native/data_file.py`) |
| `active_data_stream.py` | 286 | already native (`adapters/native/data_stream.py`) |
| `active_finalizer.py` | 507 | already native (`adapters/native/finalizer.py`) |
| `active_executor.py` | 221 | `ExecutorRunner` reimplemented natively |

**`Executor` itself is not in scope and does not move.** It lives in
`helao/helpers/executor.py` and is only *re-exported* through `base.py:80`. The 44 `Executor`
subclasses across the deployments keep their bodies and their `_pre_exec` / `_exec` / `_poll` /
`_post_exec` / `_manual_stop` hooks verbatim; only the import source changes. What B1
reimplements is `ExecutorRunner` — the six-method loop driver that starts, polls, and stops
them.

**Roughly half the write path is already native.** The graft routes 100% of write traffic
through `NativeArtifactStoreAdapter`'s collaborators. B1 stops grafting them onto a legacy
`Active` and has the native session own them from construction.

## 2. Two measurements that set the shape

### 2.1 The frozen system-surface checklist is wrong, and a gate that trusts it under-builds

`helao/hexagon/tests/checklists/hte/_baseapi_system_surface.md` lists 9 routes plus 3
WebSocket endpoints, and marks 5 of the 9 `GET`. Captured live from a running SIM action
server on `goldenhex` (2026-08-14), the real surface is **19 routes, every one `POST`**:

```
POST /{key}/estop                    POST /get_status        POST /loaded_modules
POST /attach_client                  POST /hotreload_busy    POST /resend_active
POST /detach_client                  POST /list_executors    POST /shutdown
POST /endpoints                      POST /get_lbuf          POST /stop_executor
POST /get_config                     POST /_raise_exception  POST /_raise_async_exception
POST /test_alert                     POST /test_receive
```
plus the three WebSocket endpoints `ws_status`, `ws_data`, `ws_live`, which do not appear in
`openapi.json` at all and therefore cannot be gated by an OpenAPI diff.

The checklist omits **eight** of these and mis-states the method on five. It says so itself —
its own note records that the runtime `/openapi.json` cross-check "is deferred to P3b/P3e
(needs a launched hexagon server)". That deferral never closed.

**Normative consequence.** B1's gate is a diff against a **live** `/openapi.json` captured
from a legacy server and from the B1 host for the same config, plus an explicit WebSocket
connect test for the three channels. The hand-written checklist is re-frozen from that
capture as B1's first deliverable, and is thereafter evidence rather than authority.

### 2.2 `Active` has 36 public methods; deployments use 18, and 8 carry 96% of the traffic

Measured across all deployment code:

| member | uses | | member | uses |
|---|---|---|---|---|
| `active.action` | 759 | | `active.append_sample` | 27 |
| `active.finish` | 213 | | `active.enqueue_data_nowait` | 21 |
| `active.enqueue_data_dflt` | 133 | | `active.get_realtime_nowait` | 8 |
| `active.driver` | 76 | | `active.finish_hlo_header` | 6 |
| `active.base` | 65 | | `active.write_file` | 4 |
| `active.start_executor` | 62 | | `active.split` | 3 |

with a tail of `track_file` (2), `enqueue_data` (2), `write_file_nowait` (1), `set_estop` (1),
`oneoff_executor` (1), `get_realtime` (1) — **18 members in total.**

A raw grep also reports `active.trace`, `active.items` and `active.server`. All three were
checked and are **measurement artifacts, not session members**: `active.server` is in an
`old/` driver under a deployment's `notes/` tree, `active.items()` is a plain dict named
`active` in a batch converter, and `active.trace` is `job.active` in a PAL test. They are
excluded. This is the shape of error the whole surface count is exposed to, which is why the
plan re-derives it per repo rather than from one tree-wide grep.

The native `ActionSession` implements **exactly the measured 18**, not all 36. The 18 unused
`Active` methods (`substitute`, `finish_all`, `split_and_keep_active`,
`split_and_finish_prev_uuids`, `relocate_files`, `finish_manual_action`,
`send_nonblocking_status`, `add_new_listen_uuid`, `assemble_data_msg`, `log_data_task`,
`log_data_set_output_file`, `set_sample_action_uuid`, `init_datafile`, `myinit`,
`add_status`, `update_act_file`, `executor_done_callback`, `stop_action_task`) are either
internal to the write path — already native, called by the collaborators rather than by
deployment code — or genuinely dead. Each is dispositioned explicitly in the B1 plan.
**"Unused" is a claim that must be re-checked against all four repos**, including
station-local scripts, before a method is left out.

## 3. Locked decisions

- **D-B1.1 — Explicit action context.** A handler receives its action as a parameter:

  ```python
  @host.action()
  async def acquire_data(
      ctx: ActionContext,
      duration: float = -1,
      acquisition_rate: float = 0.2,
      fast_samples_in: list[SampleUnion] = Body([], embed=True),
  ):
      session = await ctx.begin(action_abbr="WsSim")
      ...
  ```

  The legacy path reconstructs an `Action` from FastAPI's resolved kwargs inside
  `wrap_action_endpoint` and stashes it in a `ContextVar` (`ACTION_CTX`, `base_api.py:92`),
  which is why `setup_and_contain_action()` takes no request. B1 removes that hidden state:
  the dependency becomes visible in the signature and a handler becomes callable in a unit
  test without a request. **No `ContextVar`, and no compatibility shim** — a shim would have
  to be deleted in B7 and would let modules stay unported indefinitely.

  Cost, measured: **264 action routes across 40 modules, 266 `setup_and_contain_action` call
  sites, 203 `action_version` usages.**

- **D-B1.2 — `action_version` stays a decorator, not a parameter.** It is applied 203 times
  and its current effect is to inject `action_version` into the request schema. It keeps that
  meaning; only its import moves.

- **D-B1.3 — SUPERSEDED, measured 2026-08-14 while starting Task 5. The session surface is
  37 members, not 18.** The 18 in §2.2 is the *deployment-facing* surface and remains correct
  as far as it goes. It is not the whole contract: the three already-native write
  collaborators (`adapters/native/{data_stream,data_file,finalizer}.py`) each hold a
  back-reference to the session and read **26 members** off it, of which **19 appear nowhere
  in the deployment-facing list**:

  `_build_data_package`, `_finish`, `_get_action_for_file_conn_key`, `_resolve_output_path`,
  `action_list`, `active_uuid`, `add_new_listen_uuid`, `add_status`, `assemble_data_msg`,
  `data_logger`, `file_conn_dict`, `finish_lock`, `finish_manual_action`, `init_datafile`,
  `listen_uuids`, `log_data_set_output_file`, `num_data_queued`, `num_data_written`,
  `write_live_data`

  The two sets overlap on seven (`action`, `base`, `enqueue_data`, `finish`, `get_realtime`,
  `get_realtime_nowait`, `split`), giving a union of 37.

  §2.2's claim that the unused `Active` methods are "either internal to the write path --
  already native, called by the collaborators rather than by deployment code -- or genuinely
  dead" was right about the category and wrong about the consequence: *called by the
  collaborators* means the session must still provide them. A session built to the 18 would
  import, register, serve, and then fail at the first `enqueue_data` — with a plain
  `AttributeError` from inside a collaborator, at the point where an action is writing data.

  **The premise that the native session is much smaller than `Active` is therefore false.**
  The collaborators were written against `Active`'s interface, so the session is essentially
  `Active`'s full surface. Task 5 has two options and must pick one explicitly:

  1. **Implement all 37.** Honest about the coupling, no collaborator changes, and the
     smallest diff — but it means B1 reproduces `Active` rather than replacing it.
  2. **Narrow the collaborators onto a port.** The architecturally correct answer and what
     the hexagon boundary rule implies: the collaborators should depend on a declared port,
     not on whatever `Active` happens to expose. Larger, and it touches three already-parity-
     tested native modules.

  **DECIDED 2026-08-14: option (2).** Task 5 defines an `ActionSessionPort` Protocol carrying
  the 26 collaborator-facing members and re-points `data_stream`, `data_file` and `finalizer`
  at it. Their bodies do not change — only their declared dependency does — so the coupling
  becomes explicit and checkable instead of implicit in whatever `Active` happened to expose.

  Two consequences Task 5 must carry:

  - **The three collaborators' existing parity tests join Task 5's gate.** They are already
    tested against the grafted legacy `Active`; re-pointing them must leave those tests green,
    which is the evidence that the Protocol captures the real interface rather than a guess at
    it.
  - **The Protocol is derived, not authored.** Its members come from the measured set above.
    Adding one by hand later, because something failed at runtime, means the derivation was
    incomplete — re-run it against all three modules rather than patching a member in.

- **D-B1.3-orig (superseded) — The session surface is the measured 18, plus whatever §2.2's disposition adds.**
  Adding a method to `ActionSession` later is cheap; shipping 18 unused ones is a maintenance
  claim B7 would have to re-litigate.

- **D-B1.4 — The host owns no UI and imports no UI.** B0's boundary test bans
  `helao/ui/** -> helao.core.servers`; B1 adds the converse for the host package.

- **D-B1.5 — Wire encodings are frozen per Amendment 2 §3.** `ActionHost` reproduces the
  `BaseAPI` family's encoding — pickled `ActionModel` object on `/ws_status`, pickled
  `DataPackageModel` on `/ws_data`, `{datalab: (value, epoch)}` dict on `/ws_live` — and does
  **not** converge it toward the `OrchAPI` dict family. Converging would blank every remote
  subscriber with no error on either side.

## 4. Architecture

```
helao/hexagon/app/
    action_host.py      ActionHost: FastAPI construction, private-route surface,
                        WS endpoints, queuing middleware, estop exception handler,
                        driver/poller construction, dyn_endpoints hook, RPC mirror
    action_context.py   ActionContext: per-request action, ctx.begin() -> ActionSession
    action_session.py   ActionSession: the measured 18-member surface over the
                        already-native artifact store / data sink collaborators
    executor_runner.py  native replacement for ExecutorRunner's six methods
```

Ports consumed are the existing ones (`artifact_store`, `data_sink`, `status`, `clock`,
`config`, `logging`, `health`, `transport`, `state_persistence`), so `build_wiring` gains
nothing new. `ACTION_REQUIRED` gains no member.

**What the host must reproduce, and where the contract comes from:**

| concern | contract source |
|---|---|
| 19 private/action routes | live `/openapi.json` capture (§2.1) |
| 3 WS channels + encodings | `harness/ws_frames.py` canonical frames, Amendment 2 §3 |
| action lifecycle | GM-1…GM-6 artifact diff |
| queuing middleware | `_make_app_entry_middleware` behaviour, pinned by a concurrency test |
| estop exception handler | system-surface checklist item 3 |
| driver construction | `BaseAPI.__init__` startup body (`base_api.py:667-697`) |
| RPC mirror on `port + 10000` | `zmq_rpc.derive_rpc_port`; composition fails preflight without it |
| `app.base` / `app.driver` / `app.drivers` / `app.server_params` / `app.root_dir` / `app.fault_dir` | `_member_surface.md`, re-derived across all five deployments |

**Driver construction keeps the dual convention.** `HelaoDriver` subclasses receive
`config=server_params`; anything else receives the host (the `Base`-style shim). That is a
standing decision for the `test` deployment's bare-helper sims and is permanent, not a
migration stopgap.

## 5. Scope boundary

B1 ships the host and ports the **`test` deployment only** (9 action modules, 20 action
routes) as its proof. hte (175 routes / 21 modules), Deployment-A (38/8), Deployment-B (31/3)
port in B4–B6 behind hardware gates. This keeps B1 fully Linux-gateable while making it a
real consumer rather than a library with no user.

## 6. Gate

All Linux, no hardware:

1. **Route-surface diff** — `/openapi.json` from a legacy-hosted server and a B1-hosted server
   for the same config are identical after normalizing the server title/description. Captured
   live, not compared against the hand-written checklist.
2. **WebSocket channel test** — all three channels connect and deliver a frame that the real
   decoders (`WsSubscriber`, and the Reflex `ingest` normalizers keyed by `ws_path`) parse,
   byte-compared against `harness/ws_frames.py`.
3. **Artifact parity** — GM-1…GM-6 normalized-identical between legacy-hosted and B1-hosted
   runs of the `test` deployment.
4. **Concurrency suite** green on the B1 host, including the queuing-middleware behaviour and
   the estop path.
5. **Boundary test** — nothing under `helao/hexagon/app/action_*` imports
   `helao.core.servers`.
6. **Re-frozen checklists** — `_baseapi_system_surface.md` regenerated from the live capture,
   with the 8 omissions and 5 method corrections visible in the diff.
7. Full `run_tests.py` sweep green; no new pyright errors against the B0 baseline.

## 7. Risks

- **The unused-`Active`-method claim is the main way B1 under-builds.** §2.2's measurement is
  over the public tree plus the three private repos as they stand today; a method used only by
  a station-local script would not appear. Mitigation: the disposition list is checked against
  all four repos, and `ActionSession` raises `AttributeError` with a message naming B1 rather
  than silently returning `None`.
- **`action_codehash`/`action_codepath`/`action_funcname` are invisible to every existing
  gate.** They are derived from the endpoint function's `__code__` (`base.py:385-394`) and
  written into every action record — and `harness/yaml_pass.py:45` lists
  `("_codehash", "_codepath", "_funcname")` in `DROP_KEY_SUFFIXES`, so the normalizer strips
  them before any GM diff. **GM parity therefore cannot catch a regression in these three
  fields**, and neither can the route-surface diff. B1 adds a dedicated test asserting all
  three against a legacy-hosted capture; without it, the explicit-context port could silently
  blank or shift them in every action record ever written afterwards.
  (The mechanism itself is easy — `_get_action` already takes `endpoint_func` as a parameter
  rather than walking the stack, so the decorator can hand it to `ActionContext` directly.
  The hazard is purely that nothing would notice if it did not.)
- **The queuing middleware is a behaviour, not a route.** Nothing in an OpenAPI diff sees it.
  Its test must drive colliding POSTs and assert serialization order.
- **A missing RPC mirror is silent and slow, not loud.** Without a co-located ZMQ RPC server
  every `async_private_dispatcher` call eats a 3 s probe timeout before falling back to HTTP —
  which reads as "the UI is sluggish", not as a failure.

## 8. Out of scope

`OrchAPI`/`Orch` (B3), the hte and private-deployment ports (B4–B6), deleting the engine
files (B7), and any behaviour fix from the post-parity backlog. B1 reproduces legacy
behaviour including its known quirks; the `set_error`-writes-`errored` case, the finish-drain
window, and the 0.3 s per-client pacing sleep are preserved.
