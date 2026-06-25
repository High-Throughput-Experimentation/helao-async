# SP-ORCH-5 — Framework orchestrator real dispatch + status + built-in actions (design)

**Date:** 2026-06-25
**Branch:** `feat/framework-sp-orch-5-real-dispatch`
**Cycle:** Gated hte production migration — orchestrator completion. **Gates the whole hte
migration**: the canary Gate B revealed the framework orchestrator cannot drive real
hardware.

## 1. The problem (root cause, evidence-confirmed)

Running an experiment through the framework orchestrator (canary `power_supply_test`) did
not estop but also never dispatched the `wait` action. Investigation found the production
framework orchestrator is **not wired for real dispatch**:

1. **FakeTransport in production.** `app/servers/orchestrator.py:makeApp` →
   `factory.makeApp(group="orchestrator")` is called with **no `transport=`**, so
   `factory.makeOrchestratorApp` wires `FakeTransport()`. `HttpTransport`
   (`adapters/http_transport.py`, RPC-fast-path + httpx fallback) exists but is never
   wired to the orch. So the orch never HTTP/RPC-dispatches to real action servers.
2. **Synthesized completion.** `orch_api.py:196-200` calls `_synthesize_finished_status`
   the instant a dispatch returns success — it fakes the "finished" status rather than
   waiting for the action server's real completion. No real action-completion tracking.
3. **No inbound status.** `/ws_status` on the orch is an *outbound* relay (operator
   consumer). Nothing subscribes to action servers' `/ws_status` to feed
   `OrchDriver.on_status_update`. The only caller of `on_status_update` is the synth path.
4. **Wrong target port.** `_dispatch_target_for(action)` reads host/port off the action's
   `action_server` `MachineModel`, but experiment library targets (e.g.
   `MachineModel(server_name="ORCH")`) carry no port → falls back to `8000` (ORCH is 8001).

Net: the orch fake-drives. The canary "worked" (operator renders, vis plots) only because
FakeTransport silently accepts + synth-finishes. The "test deploy runs on framework"
milestone never exercised real timed multi-action dispatch — it was FakeTransport too.

`orch_sub_wait` "no estop, no dispatch" = (1)+(2)+(4); the missing `/ORCH/wait` endpoint is
a *separate* gap (part c) that only matters once 1-4 are fixed.

## 2. Goal & non-goals

**Goal:** the framework orchestrator dispatches to real action servers over ZMQ-RPC
(every ORCH endpoint RPC-reachable) with HTTP fallback, waits for genuine action
completion via real status ingestion, and hosts its own built-in action endpoints
(`wait`/`cancel_wait`/`interrupt`/`estop`) as a real action server (full-Base parity, the
user's choice).

**Non-goals:** changing the FSM decision logic (`decide_next`/`on_status_update` ladder
stay as-is — they're already correct); touching `helao/core` or `helao/deploy` (pure
framework work; the canary config already points at the framework orch); the remaining hte
config rollout (Wave 4) or hardware bring-up (Wave 5).

## 3. Decisions (user)

- Staged: **(a) real transport + (b) real status ingestion FIRST**, verify, **then (c)
  built-in actions**.
- **ZMQ-RPC must be available for EVERY ORCH API endpoint** (alongside HttpTransport).
- Verification: a **headless fake action server** (a real framework `BaseAPI` action
  server fixture) so dispatch + status round-trip is testable without hardware.

## 4. Components & tasks

### Part (a) — Real transport + RPC-for-every-endpoint

**a1. Config-driven target resolution.** Replace `_dispatch_target_for` host/port lookup so
it resolves from the CONFIG `servers` map by `server_key` (= `action_server.server_name`),
falling back to the MachineModel only when absent. Must resolve the **orchestrator's own**
entry too (ORCH→8001), so self-dispatch (part c) targets the right port. Add the full
`servers` map (not just the heartbeat `action_servers` subset, which excludes
group≠action) to `OrchPorts`/the resolver.

**a2. Wire HttpTransport in production.** `app/servers/orchestrator.py:makeApp` constructs
`HttpTransport(use_rpc=True)` and passes it into `factory.makeApp(..., transport=...)`.
`FakeTransport` stays the default for unit tests / in-process runners (no `transport=`).
Guard: only build HttpTransport when a real CONFIG slice is present.

**a3. RPC for every ORCH endpoint.** The orch already co-locates an `RPCDispatcher` whose
startup loop walks all POST routes and registers them as RPC methods, then binds the
derived RPC port. Confirm/extend so EVERY ORCH API endpoint (control + operator-private +
the part-c action endpoints, which are POST routes added before the startup loop runs) is
registered. Add a test asserting the registered RPC method set == the app's POST-route set.

**a4.** HttpTransport's RPC fast-path already keys on `{server_key}/{endpoint}` at
`derive_rpc_port(port)`; verify dispatch to a real RPC server resolves via RPC (not the
3s-probe HTTP fallback). Covered by the part-(a)/(b) integration test (§5).

### Part (b) — Real status ingestion

**b1. Status subscriber.** On orch startup, for each action server in the CONFIG `servers`
map (group==action), start a `WsSubscriber` (`helao.helpers.ws_utils.WsSubscriber`, the
accepted seam — same class the operator/vis reuse) against `ws_status`. Decode each
message into an `ActionServerModel` and call `await driver.on_status_update(asm)` (already
exists, `orch_api.py:383`). One long-lived asyncio task per server, cancelled on shutdown;
a dropped/reconnecting socket must not kill the orch (log + retry).

**b2. Stop faking completion for real dispatch.** Gate `_synthesize_finished_status`: only
synthesize when the transport is a `FakeTransport` (in-process/test). With `HttpTransport`,
the dispatch returns "action started"; real completion arrives via b1's subscriber. So the
loop genuinely waits (the `decide_next` WAIT path already gates on `actions_idle`). Thread
this as an explicit flag on `OrchPorts`/the driver (e.g. `synthesize_completion: bool`),
set False when a real transport is wired — do NOT sniff the class at the dispatch site.

**b3.** Confirm `merge_server_status` + the `actions_idle` gate advance correctly when a
real finished status arrives (the headless test in §5 asserts the loop waits then
advances).

### Part (c) — Orchestrator built-in actions (full-Base parity) — AFTER a+b verified

**c1.** Give the orch app a framework `Base`/`FrameworkBase` (the action lifecycle:
`setup_and_contain_action`, `start_executor`, status push) — the same `app.state.base`
action servers get via `makeActionApp`. Wire its status push into the orch's eventsink so
its own action status flows to b1's ingestion path (or directly to `on_status_update`).

**c2.** Port `WaitExec` (legacy `core/servers/orch_api.py`) onto
`helao.framework.domain.executor.Executor`.

**c3.** Register `/{ORCH}/wait`, `/cancel_wait`, `/interrupt`, `/estop` as real action
endpoints on `makeOrchApp` using `base.setup_and_contain_action()` + the executor, matching
legacy semantics. These are POST routes added before the RPC startup loop → auto RPC-
registered (part a3).

**c4.** With a+b: orch dispatches the `wait` action to itself over RPC/HTTP at the correct
port; `WaitExec` sleeps `waittime`; real finished status flows back via b1 → FSM advances.

## 5. Test strategy (headless fake action server)

Build a pytest fixture: a **real** framework action server (`makeActionApp` /
`FrameworkBase`) exposing one executor-backed action that takes a `duration` and pushes
real `/ws_status` started→finished, launched in-process (uvicorn on an ephemeral port, or
ASGI transport for HTTP + a real ZMQ RPC bind for the RPC path).

- **Part (a):** orch with `HttpTransport` dispatches an action to the fake server; assert
  it arrives over **RPC** (not HTTP fallback) and the server ran it. Assert target
  host/port resolved from config (incl. ORCH-self → correct port). Assert every ORCH POST
  route is RPC-registered (a3).
- **Part (b):** dispatch a `duration=N` action; assert the orch does NOT mark it finished
  until the fake server pushes the real finished status (loop sits in WAIT, then advances).
  Assert `_synthesize_finished_status` is NOT used under the real transport.
- **Part (c):** enqueue an `orch_sub_wait`-style experiment; assert the orch dispatches the
  `wait` to itself, the `WaitExec` runs, real finished status returns, loop advances.
  Reuse the existing headless `expansion.unpack_experiment` regression harness.
- Full framework suite + boundary stay green throughout.

## 6. Boundary

`domain/` stays pure (FSM/`on_status_update` unchanged). Transport, WS subscriber, Base,
and RPC live in `adapters/`/`app/`. `WaitExec` is an `Executor` subclass — `domain/` if it
has no I/O (asyncio.sleep only) else `adapters/`; place per the boundary test.

## 7. Done criteria

- (a) Production orch uses `HttpTransport` (RPC + HTTP fallback); targets resolve from
  config (incl. ORCH-self port); every ORCH endpoint RPC-registered; FakeTransport remains
  the test/in-process default.
- (b) Orch ingests real action-server `/ws_status` → `on_status_update`; no synthesized
  completion under a real transport; the loop waits for genuine completion.
- (c) Orch hosts `wait`/`cancel_wait`/`interrupt`/`estop` as real action endpoints via a
  framework Base + ported `WaitExec`.
- Headless fake-action-server tests cover all three parts; full suite + boundary green.
- After merge: the user re-launches the canary for a genuine Gate B (real `orch_sub_wait`
  and a real POWER_SUPPLY action both dispatch + complete).
