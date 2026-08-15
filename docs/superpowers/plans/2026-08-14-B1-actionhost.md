# B1 ActionHost Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the hexagon-native `ActionHost`, its explicit-context registration API, and the native action session — then port the `test` deployment onto them, so no `test` action server constructs `BaseAPI` any more.

**Architecture:** A new `helao/hexagon/app/action_*` family replaces `BaseAPI`/`Base`/`Active`/`ExecutorRunner`. Handlers receive an explicit `ActionContext` parameter instead of reading a `ContextVar`. The already-native write collaborators (`adapters/native/{data_file,data_stream,finalizer,meta_writer}.py`) are owned by the session from construction rather than grafted onto a legacy `Active` at startup. `Executor` itself does not move.

**Tech Stack:** Python 3.14 in the `helao` conda env, FastAPI/Starlette, pytest, ZMQ RPC, black, pyright.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-14-B1-actionhost-design.md`. Program spec: `docs/superpowers/specs/2026-08-14-legacy-separation-program-design.md`.
- Python is `/home/dan/miniforge3/envs/helao/bin/python`. **Never** the OS python, and **never** via `conda run` (it buffers output and, with a stdin heredoc, silently swallows stdout entirely — that is recorded in `_member_surface.md`).
- **`PYTHONPATH` must be an absolute path**, not `.`. The Reflex backend and any child spawned with a different cwd resolve a relative entry against *their* cwd. Use `PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async`.
- **To launch anything, put the env on `PATH`**: `PATH=/home/dan/miniforge3/envs/helao/bin:$PATH python launch.py <prefix>`. `launch.py` spawns a bare `python`; invoking it by absolute path leaves every child on the OS interpreter and they die with `No module named 'uvicorn'` while the launcher itself looks fine.
- **Never run the test tree as one pytest session** — it hangs and ignores SIGINT. Per file, or `run_tests.py`.
- **Never `pgrep -f` / `pkill -f` a pattern that appears in your own command line.** The
  harness wraps each command in a shell whose command line contains the *entire script text*,
  so the pattern matches the wrapper. This bit twice: `pkill -f "launch.py"` killed its own
  shell, and later a wait-loop on `pgrep -f "gm_native.sh"` matched itself and blocked for its
  full 40-minute timeout without ever running the parity step it was gating. Match on a pid
  captured at spawn time, or on a marker file, not on a name the script itself mentions.
- In zsh, **never use `path` as a loop variable**; it is tied to `PATH` and clobbers it.
- `black` on changed files immediately before `git add`.
- **Never name a private deployment in a tracked parent-repo file.** B1 touches only the public tree.
- Wire encodings are frozen per Amendment 2 §3: reproduce the `BaseAPI` family's encodings, never converge them toward `OrchAPI`'s dict family.
- Branch: `feat/legacy-separation-b1-actionhost`, cut from the B0 branch (B1 depends on `helao/ui/` existing).

---

## File Structure

**New:**

```
helao/hexagon/app/action_context.py     ActionContext + the @host.action() decorator + action_version
helao/hexagon/app/action_session.py     ActionSession — the measured 18-member surface
helao/hexagon/app/action_host.py        ActionHost — FastAPI app, 19 routes, 3 WS, middleware,
                                        estop handler, driver/poller construction, RPC mirror
helao/hexagon/app/executor_runner.py    native ExecutorRunner (start/loop/stop)
harness/openapi_capture.py              capture a live /openapi.json to a normalized JSON file
helao/hexagon/tests/test_action_context.py
helao/hexagon/tests/test_action_session.py
helao/hexagon/tests/test_action_host_surface.py
helao/hexagon/tests/test_executor_runner.py
helao/hexagon/tests/test_action_code_identity.py
```

**Modified:** the 8 `test`-deployment action modules; `helao/hexagon/app/factory.py` (a `makeActionApp` that no longer imports a legacy module); `helao/hexagon/tests/checklists/hte/_baseapi_system_surface.md` (re-frozen).

**Not touched:** `helao/helpers/executor.py`, every `helao/core/servers/` engine file (deleted in B7, still serving legacy configs until then).

---

## Task 1: Live OpenAPI capture, and re-freeze the system surface

The spec's §2.1 finding is that the checked-in checklist omits 8 routes and mis-states 5 methods. Fixing it is the first deliverable because every later task is gated against it.

**Files:**
- Create: `harness/openapi_capture.py`
- Modify: `helao/hexagon/tests/checklists/hte/_baseapi_system_surface.md`
- Test: `helao/hexagon/tests/test_action_host_surface.py`

**Interfaces:**
- Produces: `openapi_capture.capture(base_url: str) -> dict` returning `{"routes": [{"path": str, "method": str, "tags": list[str]}, ...]}` sorted by `(path, method)`, and `capture_to_file(base_url, path)`. Tasks 3 and 8 consume both.

- [ ] **Step 1: Write the failing test**

Create `helao/hexagon/tests/test_action_host_surface.py`:

```python
"""The action-server system surface, captured live rather than asserted by hand.

`_baseapi_system_surface.md` was hand-written and its own note records that the
runtime `/openapi.json` cross-check was "deferred to P3b/P3e". That deferral
never closed, and the file drifted: measured 2026-08-14 against a running SIM
server it omits 8 routes and marks 5 POST routes as GET. This module pins the
real surface so a host that under-builds it cannot pass.
"""

import json
from pathlib import Path
from typing import Final

from harness import openapi_capture

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
FROZEN: Final[Path] = (
    REPO_ROOT / "helao/hexagon/tests/checklists/hte/_baseapi_system_surface.json"
)

#: Every route BaseAPI/Base registers on an action server, captured live from a
#: SIM server on `goldenhex` (2026-08-14). Action-tagged routes are the server's
#: own and are excluded; `/{key}/estop` is included because the host registers it.
EXPECTED_PRIVATE: Final[frozenset[str]] = frozenset(
    {
        "/_raise_async_exception",
        "/_raise_exception",
        "/attach_client",
        "/detach_client",
        "/endpoints",
        "/get_config",
        "/get_lbuf",
        "/get_status",
        "/hotreload_busy",
        "/list_executors",
        "/loaded_modules",
        "/resend_active",
        "/shutdown",
        "/stop_executor",
        "/test_alert",
        "/test_receive",
    }
)

#: Not in openapi.json at all -- websockets are invisible to an OpenAPI diff, so
#: they need their own connect test (Task 8).
EXPECTED_WEBSOCKETS: Final[tuple[str, ...]] = ("ws_status", "ws_data", "ws_live")


def test_every_private_route_is_a_post() -> None:
    """The frozen checklist marked five of these GET. They are all POST."""
    frozen = json.loads(FROZEN.read_text())
    methods = {r["method"] for r in frozen["routes"] if r["path"] in EXPECTED_PRIVATE}
    assert methods == {"post"}, f"non-POST private routes: {methods}"


def test_frozen_surface_matches_the_expected_private_set() -> None:
    frozen = json.loads(FROZEN.read_text())
    got = {r["path"] for r in frozen["routes"] if "private" in (r["tags"] or [])}
    assert got == EXPECTED_PRIVATE, (
        f"missing: {sorted(EXPECTED_PRIVATE - got)}\n"
        f"unexpected: {sorted(got - EXPECTED_PRIVATE)}"
    )


def test_capture_normalizes_deterministically() -> None:
    """Two captures of the same document compare equal."""
    doc = {
        "paths": {
            "/b": {"post": {"tags": ["private"]}},
            "/a": {"post": {"tags": ["action"]}},
        }
    }
    assert openapi_capture.normalize(doc) == openapi_capture.normalize(doc)
    assert [r["path"] for r in openapi_capture.normalize(doc)["routes"]] == ["/a", "/b"]
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/hexagon/tests/test_action_host_surface.py -q
```

Expected: collection error — `harness.openapi_capture` does not exist.

- [ ] **Step 3: Write `harness/openapi_capture.py`**

```python
"""Capture a live server's route surface to a normalized, diffable form.

The static extractor in `harness/endpoints.py` sees only `@app.<method>(...)`
decorators on a module's own functions; it cannot see the routes BaseAPI/Base
register at runtime, which is exactly the surface a host replacement must
reproduce. This module reads them from a launched server instead.

WebSockets do not appear in `openapi.json` and are therefore NOT covered here --
they need a connect test. A surface diff that reports "identical" says nothing
about ws_status/ws_data/ws_live.
"""

import json
from typing import Any

import requests

__all__ = ["normalize", "capture", "capture_to_file"]


def normalize(doc: dict[str, Any]) -> dict[str, Any]:
    """Reduce an OpenAPI document to a sorted, comparable route list."""
    routes = []
    for path, ops in (doc.get("paths") or {}).items():
        for method, op in ops.items():
            routes.append(
                {
                    "path": path,
                    "method": method.lower(),
                    "tags": sorted(op.get("tags") or []),
                }
            )
    routes.sort(key=lambda r: (r["path"], r["method"]))
    return {"routes": routes}


def capture(base_url: str, timeout: float = 10.0) -> dict[str, Any]:
    resp = requests.get(f"{base_url.rstrip('/')}/openapi.json", timeout=timeout)
    resp.raise_for_status()
    return normalize(resp.json())


def capture_to_file(base_url: str, path, timeout: float = 10.0) -> dict[str, Any]:
    captured = capture(base_url, timeout=timeout)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(captured, fh, indent=1, sort_keys=True)
        fh.write("\n")
    return captured
```

- [ ] **Step 4: Capture the real surface from a launched legacy server**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
export PATH=/home/dan/miniforge3/envs/helao/bin:$PATH
export PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async
nohup python launch.py goldenhex > /tmp/b1_cap.log 2>&1 &
disown
for i in $(seq 1 40); do curl -s -o /dev/null -m 2 http://127.0.0.1:8002/openapi.json && break; sleep 4; done
python -c "
from harness import openapi_capture as oc
d = oc.capture_to_file('http://127.0.0.1:8002', 'helao/hexagon/tests/checklists/hte/_baseapi_system_surface.json')
print(len(d['routes']), 'routes captured')
"
```

Expected: `19 routes captured`. SIM takes about 60 s to answer — do not shorten the poll loop.

Tear down by PID (**not** `pkill -f`, which matches this shell):
```bash
kill -INT $(pgrep -f "launch.py goldenhex" | head -1); sleep 10
```

- [ ] **Step 5: Rewrite the markdown checklist to point at the captured JSON**

Replace the Routes and WebSocket sections of
`helao/hexagon/tests/checklists/hte/_baseapi_system_surface.md` with a note that the
authoritative surface is now `_baseapi_system_surface.json`, captured live, and that the
markdown holds only the four **behavioral** contracts (action-lifecycle POST contract, queuing
middleware, estop exception handler, co-located RPC mirror) which no OpenAPI diff can express.
State in the file that the previous hand-written list omitted 8 routes and mis-stated 5
methods, so nobody restores it from git history believing it was correct.

- [ ] **Step 6: Verify and commit**

```bash
PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/hexagon/tests/test_action_host_surface.py -q
```
Expected: 3 passed.

```bash
/home/dan/miniforge3/envs/helao/bin/black -q harness/openapi_capture.py helao/hexagon/tests/test_action_host_surface.py
git add -A && git commit -m "feat(harness): capture the action-server surface live, re-freeze the checklist

The hand-written _baseapi_system_surface.md omitted 8 routes and marked 5 POST
routes as GET; its own note admits the runtime cross-check was deferred and never
closed. The authoritative surface is now a live capture. WebSockets stay out of
scope here on purpose: they are absent from openapi.json, so a surface diff that
reports identical says nothing about them."
```

---

## Task 2: `ActionContext` and the registration decorator

**Files:**
- Create: `helao/hexagon/app/action_context.py`
- Test: `helao/hexagon/tests/test_action_context.py`

**Interfaces:**
- Consumes: `helao.hexagon.domain.models.Action`.
- Produces: `ActionContext` with `.action: Action`, `.endpoint_func`, and `async begin(**kw) -> ActionSession`; `build_action(kwargs, default_params, endpoint_func) -> Action`; `action_version(n)` decorator; `collect_default_params(sig) -> dict`. Tasks 3 and 7 consume all four.

- [ ] **Step 1: Write the failing test**

Create `helao/hexagon/tests/test_action_context.py`:

```python
"""The explicit action context (D-B1.1).

Legacy reconstructs an Action from FastAPI's resolved kwargs and stashes it in a
ContextVar, which is why setup_and_contain_action() takes no request. B1 makes
the dependency a parameter instead, so a handler is callable without a request --
which is what these tests do.
"""

import inspect

import pytest

from helao.hexagon.app.action_context import (
    action_version,
    build_action,
    collect_default_params,
)
from helao.hexagon.domain.models import Action


def test_an_orchestrator_envelope_is_used_as_the_base_action() -> None:
    """The orchestrator POSTs a full Action; it must not be rebuilt from scratch."""
    envelope = Action(action_name="acquire_data")
    envelope.action_params["duration"] = 5.0
    got = build_action({"action": envelope, "duration": 5.0}, {}, None)
    assert got is envelope
    assert got.action_params["duration"] == 5.0


def test_loose_kwargs_fold_into_action_params() -> None:
    got = build_action({"duration": 2.0, "rate": 0.5}, {}, None)
    assert got.action_params == {"duration": 2.0, "rate": 0.5}


def test_an_envelope_value_wins_over_a_loose_kwarg() -> None:
    """The dispatcher already resolved these; a default must not overwrite one."""
    envelope = Action(action_name="x")
    envelope.action_params["duration"] = 9.0
    got = build_action({"action": envelope, "duration": 1.0}, {}, None)
    assert got.action_params["duration"] == 9.0


def test_defaults_not_supplied_by_the_caller_are_recorded() -> None:
    """The ZMQ-RPC fast path does not synthesize FastAPI defaults."""
    got = build_action({}, {"duration": -1, "rate": 0.2}, None)
    assert got.action_params == {"duration": -1, "rate": 0.2}


def test_a_missing_envelope_yields_a_blank_action_without_raising() -> None:
    """An action-tagged query endpoint reached over RPC supplies no envelope.

    Legacy logs this at debug and proceeds with a blank Action; raising here
    would break PAL's list_new_samples and its kin.
    """
    assert isinstance(build_action({}, {}, None), Action)


def test_code_identity_is_taken_from_the_endpoint_function() -> None:
    """These three fields are stripped by the golden normalizer, so nothing else
    in the suite would notice if they went blank. See test_action_code_identity."""

    def sample_endpoint():
        return None

    got = build_action({}, {}, sample_endpoint)
    assert got.action_funcname == "sample_endpoint"
    assert got.action_codehash
    assert got.action_codepath.endswith("test_action_context.py")


def test_action_version_marks_the_function() -> None:
    @action_version(3)
    def handler():
        return None

    assert getattr(handler, "_helao_action_version") == 3


def test_collect_default_params_reads_the_signature() -> None:
    def handler(a, b=2, c="x"):
        return None

    assert collect_default_params(inspect.signature(handler)) == {"b": 2, "c": "x"}
```

- [ ] **Step 2: Run to verify it fails**

```bash
PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/hexagon/tests/test_action_context.py -q
```
Expected: collection error, `helao.hexagon.app.action_context` not found.

- [ ] **Step 3: Implement `action_context.py`**

Port the logic of `base_api._build_action_from_kwargs` (`base_api.py:96-170`) and
`_collect_default_params`, and the code-identity block of `Base._get_action`
(`base.py:385-394`) — reading the legacy source for exact behaviour, including the
envelope-wins rule and the benign blank-Action fallback. `ActionContext` is a small dataclass
holding `action`, `endpoint_func` and the host; `begin(**kw)` delegates to the host to build
an `ActionSession` (Task 5) and is left raising `NotImplementedError` until then — Task 5's
first step replaces it.

Do **not** add a `ContextVar`. Do **not** add a `setup_and_contain_action()` shim.

- [ ] **Step 4: Run to verify it passes**

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
/home/dan/miniforge3/envs/helao/bin/black -q helao/hexagon/app/action_context.py helao/hexagon/tests/test_action_context.py
git add -A && git commit -m "feat(hexagon): explicit ActionContext, no ContextVar

Ports _build_action_from_kwargs' behaviour verbatim -- envelope wins over a
loose kwarg, RPC-omitted defaults are still recorded, and a missing envelope
yields a blank Action rather than raising (PAL's action-tagged query endpoints
reach the host over RPC with no envelope at all)."
```

---

## Task 3: `ActionHost` — app construction and the private surface

**Files:**
- Create: `helao/hexagon/app/action_host.py`
- Test: extend `helao/hexagon/tests/test_action_host_surface.py`

**Interfaces:**
- Consumes: `build_wiring` and `ACTION_REQUIRED` from `helao/hexagon/app/wiring.py`; `ActionContext` from Task 2.
- Produces: `ActionHost(server_key, server_title, description, version, driver_classes=None, dyn_endpoints=None, poller_class=None)` — deliberately the same constructor arity as `BaseAPI.__init__`, since that part of the contract has no reason to change. Exposes `.base` (itself — the member name 21 hte modules use), `.driver`, `.drivers`, `.server_params`, `.root_dir`, `.fault_dir`, and the `@host.action()` decorator. Task 7 consumes all of it.

- [ ] **Step 1: Add the surface test against a host instance**

Append to `test_action_host_surface.py` a test that builds an `ActionHost` with a stub wiring, reads `host.openapi()`, normalizes it with `openapi_capture.normalize`, and asserts its private route set equals `EXPECTED_PRIVATE` and every method is `post`. This is the test that fails while the host is incomplete, and it needs no launched server.

- [ ] **Step 2: Run to verify it fails**

Expected: `helao.hexagon.app.action_host` not found.

- [ ] **Step 3: Implement the host**

Reproduce, reading `base_api.py:602-900` for exact behaviour:
- the 16 private routes and `/{server_key}/estop`, all `POST`, all tagged as the capture shows;
- the three WebSocket endpoints with the **`BaseAPI` family's** encodings (pickled `ActionModel` on `ws_status`, pickled `DataPackageModel` on `ws_data`, `{datalab: (value, epoch)}` on `ws_live`) — Amendment 2 §3 forbids converging these toward `OrchAPI`'s dict family;
- driver construction with the dual convention: `HelaoDriver` subclasses get `config=self.server_params`, anything else gets the host;
- `poller_class` attached to the first driver with `polling_time` from the server config;
- the `dyn_endpoints` hook, invoked after drivers are built;
- `root_dir`/`fault_dir` + `faulthandler` wiring;
- the co-located ZMQ RPC mirror on `derive_rpc_port(port)` — **a missing mirror is silent**: every `async_private_dispatcher` call falls back to HTTP after a 3 s probe timeout, which reads as a sluggish UI, not as a failure. Fail composition loudly instead.

- [ ] **Step 4: Run to verify it passes**

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(hexagon): ActionHost app construction and private route surface

Same constructor arity as BaseAPI -- that part of the contract had no reason to
change. WS encodings reproduce the BaseAPI family and are not converged toward
OrchAPI's dict family (Amendment 2 §3): every remote subscriber decodes exactly
one shape, so converging would blank them with no error on either side.

The RPC mirror is constructed loudly. Its absence is otherwise invisible -- a
3s probe timeout per private dispatch, presenting as a slow UI."
```

---

## Task 4: Queuing middleware and the estop exception handler

Neither is a route, so **nothing in a surface diff sees either of them**.

**Files:**
- Modify: `helao/hexagon/app/action_host.py`
- Test: `helao/hexagon/tests/test_action_host_behaviour.py` (new)

**Interfaces:**
- Produces: no new public names; the host gains the middleware and handler.

- [ ] **Step 1: Write the failing tests**

Driven through a real ASGI transport, not by inspecting attributes. The serialization test
must assert the *interleaving*, because two serialized requests and two concurrent ones both
return 200:

```python
import asyncio

import httpx
import pytest


@pytest.mark.asyncio
async def test_colliding_action_posts_serialize() -> None:
    """Two POSTs to one action endpoint must not overlap.

    Both orderings return 200, so the assertion has to be on the recorded
    interleaving. `events` records entry/exit; serialized execution can only
    produce enter/exit/enter/exit, never enter/enter/exit/exit.
    """
    events: list[str] = []
    host = _host_with_slow_action(events, delay=0.25)  # fixture below

    transport = httpx.ASGITransport(app=host)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        await asyncio.gather(
            client.post("/TEST/slow_action", json={}),
            client.post("/TEST/slow_action", json={}),
        )

    assert events == ["enter", "exit", "enter", "exit"], events


@pytest.mark.asyncio
async def test_an_exception_in_an_action_route_triggers_estop() -> None:
    """Legacy estops and stops executors; a bare 500 would leave hardware running."""
    host = _host_with_raising_action()
    transport = httpx.ASGITransport(app=host)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        await client.post("/TEST/boom", json={})
    assert host.base.estop_triggered is True
    assert host.base.stopped_executors, "executors were not stopped"


@pytest.mark.asyncio
async def test_head_requests_short_circuit() -> None:
    """The endpoint checker probes with session.head(); a host without the
    short-circuit answers 405 and the probe reads the server as unhealthy."""
    host = _host_with_slow_action([], delay=0)
    transport = httpx.ASGITransport(app=host)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.head("/TEST/slow_action")
    assert resp.status_code == 200
```

- [ ] **Step 2: Run to verify they fail**

- [ ] **Step 3: Implement**

Port `_make_app_entry_middleware` (`base_api.py:97-175`) and
`_make_http_exception_handler`. Keep the `HEAD`-request short-circuit: the endpoint checker
issues `session.head()` and a host without it answers 405 to a liveness probe.

- [ ] **Step 4: Run to verify they pass**

- [ ] **Step 5: Commit**

---

## Task 5: `ActionSession` — the measured 18-member surface

**Files:**
- Create: `helao/hexagon/app/action_session.py`
- Modify: `helao/hexagon/app/action_context.py` (`begin` stops raising)
- Test: `helao/hexagon/tests/test_action_session.py`

**Interfaces:**
- Consumes: `NativeArtifactStoreAdapter.collaborators_for` / `meta_writer_for` (already native), `data_sink`, `status`, `clock` ports.
- Produces: `ActionSession` with exactly `action`, `finish`, `enqueue_data_dflt`, `driver`, `base`, `start_executor`, `append_sample`, `enqueue_data_nowait`, `get_realtime_nowait`, `finish_hlo_header`, `write_file`, `split`, `track_file`, `enqueue_data`, `write_file_nowait`, `set_estop`, `oneoff_executor`, `get_realtime` — the 18 members deployment code actually uses. Task 7 consumes it.

- [ ] **Step 1: Re-derive the member list across all four repos**

The spec's 18 come from the public tree plus the three private repos. Before implementing,
confirm nothing was missed — a member used once, in one station's module, is a station outage
in B5/B6:

```bash
cd /mnt/STORAGE/repos/helao/helao-async
grep -rhoE "\bactive\.[a-z_]+" --include="*.py" helao/deploy 2>/dev/null | sort | uniq -c | sort -rn
```

Exclude confirmed artifacts (`active.trace` is `job.active` in a PAL test, `active.items()` is
a plain dict in a batch converter, `active.server` is in an `old/` driver under a `notes/`
tree). **Record the resulting list in the commit message**, so a later reader can tell a
deliberate omission from an oversight.

- [ ] **Step 2: Write the failing tests**

One test per member, asserting behaviour against the native collaborators — not that the
attribute merely exists. Plus one negative test: an unimplemented `Active` method raises
`AttributeError` whose message names B1 and the disposition list, rather than returning `None`.

- [ ] **Step 3: Run to verify they fail**

- [ ] **Step 4: Implement**

Read `base.py:994-1459` for the delegator bodies. The three write collaborators and the meta
writer are already native — the session **constructs** them rather than swapping them in after
`__init__` the way `active_graft.py` has to. That removes the graft's mandatory
`__init__`/`myinit` timing window, which exists only because the legacy `Active` builds its own
collaborators first.

- [ ] **Step 5: Run to verify they pass**

- [ ] **Step 6: Commit**

---

## Task 6: Native `ExecutorRunner`

**Files:**
- Create: `helao/hexagon/app/executor_runner.py`
- Test: `helao/hexagon/tests/test_executor_runner.py`

**Interfaces:**
- Consumes: `helao.helpers.executor.Executor` — **unchanged and not moved**.
- Produces: `ExecutorRunner` with `start_executor`, `oneoff_executor`, `action_loop_task`, `stop_action_task`, `executor_done_callback`.

- [ ] **Step 1: Write the failing tests**

Drive a real `Executor` subclass through both paths — `oneoff=True` runs `_exec` once;
`oneoff=False` loops `_poll` until it returns `HloStatus.finished` — and assert
`_pre_exec`/`_post_exec` fire exactly once each and `_manual_stop` runs on
`stop_action_task`.

- [ ] **Step 2: Run to verify they fail**
- [ ] **Step 3: Implement**, reading `active_executor.py:59-221`.
- [ ] **Step 4: Run to verify they pass**
- [ ] **Step 5: Commit**

---

## Task 7: Port the `test` deployment

8 modules, 20 action routes. Measured per module: `gpsim_server` 6, `cpsim_server` 4,
`archive_simulator` 3, `motion_simulator` 2, `ws_simulator` 2, `analysis_simulator` 1,
`control_sim` 1, `pstat_simulator` 1.

**Files:**
- Modify: all 8 of `helao/deploy/test/servers/action/*.py`
- Modify: `helao/hexagon/app/factory.py` — `makeActionApp` stops importing a legacy module for hosts that are already native

**Interfaces:**
- Consumes: everything from Tasks 2–6.

- [ ] **Step 1: Port `ws_simulator.py` first and diff its surface**

It is the smallest full example (2 routes, a driver, an `Executor`). The port is mechanical:

```python
from helao.hexagon.app.action_host import ActionHost
from helao.hexagon.app.action_context import ActionContext
from helao.helpers.executor import Executor

def makeApp(server_key):
    host = ActionHost(
        server_key=server_key,
        server_title=server_key,
        description="Websocket simulator",
        version=1.0,
        driver_classes=[WsSim],
    )

    @host.action()
    async def acquire_data(
        ctx: ActionContext,
        duration: float = -1,
        acquisition_rate: float = 0.2,
        fast_samples_in: list[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = Body([], embed=True),
    ):
        session = await ctx.begin(action_abbr="WsSim")
        executor = WsExec(
            active=session,
            oneoff=False,
            poll_rate=session.action.action_params["acquisition_rate"],
        )
        return session.start_executor(executor)

    return host
```

`WsSim` and `WsExec` bodies are **unchanged** — `WsExec` reaches `self.active.base.get_lbuf(...)`, and `session.base` is one of the 18 members for exactly this reason.

- [ ] **Step 2: Diff that one server's surface, legacy versus ported**

Launch `goldenhex` on the pre-port commit, capture `http://127.0.0.1:8002` to
`/tmp/sim_legacy.json`; launch on the ported commit, capture to `/tmp/sim_b1.json`; compare.
Expected: identical, including the `action` body parameter — if the orchestrator's `Action`
envelope stops appearing in the schema, every dispatched action silently becomes a blank
`Action`.

- [ ] **Step 3: Port the remaining 7 modules**

One commit per module, each with its own surface diff. `gpsim_server` last — it carries the
recorded percent-log hang (a `logger` call with no placeholder plus an unguarded
`helao_logging.emit()` kills the priming task and hangs the OERSIM sims), so a failure there
is likelier to be pre-existing than caused by the port. Check that against the pre-port commit
before debugging it as a regression.

- [ ] **Step 4: Verify no `test` action module constructs `BaseAPI`**

```bash
grep -rn "BaseAPI" --include="*.py" helao/deploy/test/servers/action/ | grep -v __pycache__
```
Expected: no output.

- [ ] **Step 5: Commit**

---

## Task 8: Gate

- [ ] **Step 1: Code-identity test** — the one thing no other gate can see

Create `helao/hexagon/tests/test_action_code_identity.py`. `harness/yaml_pass.py:45` lists
`("_codehash", "_codepath", "_funcname")` in `DROP_KEY_SUFFIXES`, so the normalizer strips
all three before any GM diff: **GM parity cannot catch a regression in these fields, and
neither can the surface diff.** Assert that a B1-hosted action record carries the same
`action_funcname`, a non-empty `action_codehash`, and an `action_codepath` of the same shape
as a legacy-hosted one for the same endpoint.

- [ ] **Step 2: WebSocket frame parity**

Connect to all three channels on a B1-hosted server and assert the frames decode with the
**real** consumers — `WsSubscriber`, and the Reflex `ingest` normalizers keyed by `ws_path` —
byte-compared against `harness/ws_frames.py`. Assert the cross-pair case too: each normalizer
over the other channel's frame yields nothing. "Returns empty" must never read as a pass.

- [ ] **Step 3: GM-1…GM-5 artifact parity**

One scenario per launch, fresh root between scenarios and between baseline captures:

```bash
python -m harness.capture --scenario GM-1 --out /home/dan/helao_goldens/GM-1/b1
python -m harness.parity --golden /home/dan/helao_goldens/GM-1/legacy --candidate /home/dan/helao_goldens/GM-1/b1
```
Expected: no differences. Repeat for GM-2…GM-5.

- [ ] **Step 4: Concurrency suite** on the B1 host.

- [ ] **Step 4b: Boundary test** (spec gate item 5)

Extend `helao/hexagon/tests/test_boundaries.py` so the four new `app/action_*` modules may not
import `helao.core.servers`. Walk the AST, matching string constants as well as imports — the
host resolves nothing dynamically today, but a later `import_module("helao.core.servers...")`
is exactly the edge B7 would discover too late. Include the vacuity guard the B0 boundary test
needed: assert the module list is non-empty and names `action_host.py`, or a mis-typed glob
passes by reaching nothing.

- [ ] **Step 4c: Full-server surface diff** (spec gate item 1)

Task 7 diffs each server as it is ported. Repeat once at the end for **every** `test`
deployment server at once, legacy versus B1, so a route lost from one module while another was
being ported cannot slip through the per-module diffs.

- [ ] **Step 5: Full sweep and type check**

```bash
PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async /home/dan/miniforge3/envs/helao/bin/python run_unit_tests.py
PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async /home/dan/miniforge3/envs/helao/bin/python run_tests.py 2>&1 | tail -20
```
Expected: `ALL GREEN`.

pyright: compare against the B0 baseline the same way B0 did — clone the B0 branch to a plain
path, add the three private repos, run with `--outputjson`, and diff error counts per file
**excluding `.claude/`** (pyrightconfig has no `exclude`, so stale worktrees otherwise add
~1400 phantom errors). Gate: zero files with more errors.

- [ ] **Step 6: Launch checks**

`goldenhex`, `goldenhexvis` and `goldenhexreflex` all come up with no `supervise_early_exits`
report. Poll for readiness — SIM and SYNC take about 60 s, and a 120 s timeout tears down
mid-startup and looks like a failure.

- [ ] **Step 7: Commit and report**

---

## Merge

Parent repo only — B1 touches no private deployment. Merge after B0.

## Rollback

`freeze/pre-legacy-removal_2608`, and the `deployment:` key: every legacy config still routes
to `BaseAPI` until B7 deletes it, so a `test` station reverts by pointing at its legacy config.

---

## Execution status (2026-08-14)

Branch `feat/legacy-separation-b1-actionhost`, cut from B0. **Tasks 1 and 2 complete and
verified; Tasks 3–8 not started.**

**Task 1 — done.** `harness/openapi_capture.py` captures a live server's route surface;
`_baseapi_system_surface.json` frozen from a running SIM server on `goldenhex` (19 routes, 16
private, all POST); the markdown checklist rewritten to hold only the behavioural contracts,
with the drift documented so nobody restores the old list from history believing it correct.
3 tests.

**Task 2 — done.** `helao/hexagon/app/action_context.py`: explicit `ActionContext`,
`build_action`, `collect_default_params`, `action_version`. No ContextVar, no shim. 10 tests.

One behaviour measured while testing and worth knowing before Task 8: `get_filehash` shells
out to `git log -n 1 -- <file>` and returns `""` for a file with no commit touching it yet, so
**every action recorded from an uncommitted working file carries an empty
`action_codehash`**. Legacy does the same and B1 preserves it — but it means Task 8's
code-identity test must compare a *committed* file, or it will assert emptiness against
emptiness and pass while proving nothing.

**Task 3a — done (commit `e7809be9`).** `helao/hexagon/app/action_host.py`: construction,
the 16 private routes, the 5 shared debug routes reimplemented natively rather than imported
from the engine, 3 WS channels with the frozen `BaseAPI`-family encodings, `/{key}/estop`,
dual-convention driver construction, poller-before-disconnect shutdown. 8 tests assert the
**constructed** host's surface equals the live legacy capture — no launched server needed, so
a host that under-builds the surface fails in the normal suite. Nothing stubbed: `executors`
and `_actives` are real registries, empty until Tasks 5/6, and every route reading them is
correct at both stages.

**Task 3b — core done (commit `df3bb19d`), remainder open.**
`helao/hexagon/app/action_route.py`: strips `ctx` from the FastAPI-visible signature,
synthesizes `action`/`action_version` when absent, injects an `ActionContext` at call time,
and binds to its host via a per-host subclass (a module global would have several hosts in
one process building contexts against the wrong server). `ActionHost.action()` registers
routes; `begin_session` raises `NotImplementedError` until Task 5 rather than returning None,
so a ported module cannot import, register and serve only to fail on first dispatch.
8 tests.

**Still open in 3b:** the queuing middleware and estop exception handler (originally Task 4)
and the executor registry (Task 6) — both need to land before an action route can actually
serve traffic.

**Original Task 3 note, kept for the record —** A draft `ActionHost` is at
`$CLAUDE_JOB_DIR/tmp/b1_wip/action_host.py.draft`. It is **not** on the branch, because it
cannot be finished without pieces that belong to Tasks 4 and 5:

- `estop_actives()` needs the session (Task 5) to finalize in-flight actions;
- `attach_status_client` / `detach_status_client` / `actionservermodel` need the status port
  bound the way Task 4 wires it;
- `stop_executor_by_id` needs the executor registry (Task 6);
- it references a `helao/hexagon/app/action_route.py` (the route class that builds the context
  and hands it to the handler) which is Task 4's first deliverable.

Leaving it on the branch would have meant committing a module that does not import, with five
methods that do not exist — a stub that reads as progress. The draft is worth resuming rather
than rewriting: the route surface, the WS registration with the frozen `BaseAPI`-family
encodings, the dual-convention driver construction, the poller-before-disconnect shutdown
ordering, and the estop route are all written against the measured legacy behaviour.

**Task 3 should be re-planned as two tasks**, which is what the attempt showed: the host's
*route surface* is separable from the host's *state* (`actionservermodel`, the client
registry, the executor registry, the live buffer). The surface half can land and be gated on
the captured JSON with no session at all; the state half belongs with Tasks 4–6.

---

## Task 5 — blocked on a decision (2026-08-14)

Step 1 (re-derive the member list) ran and **confirmed the deployment-facing 18 exactly**,
across all four repos, with the same three artifacts excluded. Implementation did **not**
start, because Step 1 also surfaced something that invalidates the task's premise.

**The three already-native write collaborators read 26 members off their session
back-reference, 19 of which are not in the 18.** Measured from
`adapters/native/{data_stream,data_file,finalizer}.py`:

```
_build_data_package  _finish              _get_action_for_file_conn_key  _resolve_output_path
action_list          active_uuid          add_new_listen_uuid           add_status
assemble_data_msg    data_logger          file_conn_dict                finish_lock
finish_manual_action init_datafile        listen_uuids                  log_data_set_output_file
num_data_queued      num_data_written     write_live_data
```

Union with the deployment-facing 18 (overlapping on `action`, `base`, `enqueue_data`,
`finish`, `get_realtime`, `get_realtime_nowait`, `split`) is **37 members**.

A session built to 18 would import, register, serve, and fail at the first `enqueue_data`
with a bare `AttributeError` raised from inside a collaborator, at the moment an action is
writing data. The spec said these were "internal to the write path — already native, called
by the collaborators rather than by deployment code", which was right about the category and
wrong about the consequence.

**The decision Task 5 needs, before any code:**

1. **Implement all 37.** No collaborator changes, smallest diff, honest about the coupling —
   but B1 then reproduces `Active` rather than replacing it, and D-B1.3's "much smaller than
   `Active`" premise is simply dropped.
2. **Narrow the collaborators onto an `ActionSessionPort` Protocol** carrying the 26
   collaborator-facing members, bodies unchanged. Makes the coupling explicit and checkable
   and is what the hexagon boundary rule implies — but it edits three modules that are
   already parity-tested, so their tests become part of Task 5's gate.

Recommended: **2**, scoped to the Protocol only. Recorded in the spec as the supersession of
D-B1.3.

### Task 5 progress — the port is derived and landed; re-pointing is blocked

**Done:** `helao/hexagon/ports/action_session.py` — `ActionSessionPort`, derived by AST walk
from the three collaborators: 9 async methods, 7 sync methods, 10 attributes, 26 total, with
`Active`'s own signatures so a legacy `Active` satisfies it structurally. Three tests
**re-run the derivation** rather than trusting the file, so a member added to a collaborator
without being added to the port fails in the suite; one guards against a mis-rooted AST walk
passing vacuously; one asserts legacy `Active` still satisfies the port, since the graft is
what production runs until B7.

**Blocked:** re-pointing the collaborators' `active` parameter at the Protocol. All three are
**verbatim re-bodies of their legacy twins** and are black force-excluded as a pair
(`pyproject.toml` force-exclude covers `adapters/native/{meta_writer,data_file,data_stream,
finalizer,sync_driver}.py` *and* `core/servers/{base_meta_writer,active_data_file,
active_data_stream,active_finalizer}.py`). Adding `active: ActionSessionPort` to
`__init__` edits one half of a pinned pair.

**Resolve before editing them**, in this order:

1. Establish what the pin actually enforces — a whole-file comparison against the legacy twin,
   or a marked region. Grep found the "verbatim re-body" claim in the module and test
   docstrings but no explicit region markers, so this is currently unknown, and the answer
   decides everything below.
2. If whole-file: annotate **without touching the pinned body** — a `TYPE_CHECKING`-guarded
   module-level alias, or the annotation on the class attribute rather than the `__init__`
   parameter. The Protocol's value is static checkability; it does not require the annotation
   to sit on the parameter.
3. If a marked region and `__init__` sits outside it: annotate the parameter directly, and
   mirror into the legacy twin only if the pin compares both halves.

Do **not** edit a pinned mirror to make a type annotation land. The pin exists because these
bodies drifted from their legacy twins before, and the drift is what the parity tests catch.

---

## Task 6 — measured, not started (2026-08-14)

`ExecutorRunner`'s five methods were extracted from `active_executor.py` and read. The loop
body (`action_loop_task`, ~60 lines) is the only substantial one; the other four are short.
**It requires nine session members and three host members, and four of them do not exist
yet** — the same shape of gap that the port derivation and the construction test each caught
one layer earlier.

**On the session** (`self.active.*`): `base`, `action`, `enqueue_data_nowait`, `finish` — all
present. Plus, **not present**:

| member | kind | note |
|---|---|---|
| `action_task` | attribute | the created task handle |
| `action_loop_running` | attribute | the poll loop's own flag |
| `manual_stop` | attribute | set by `stop_action_task` |
| `send_nonblocking_status` | async method | called twice for a nonblocking action; **it is in the "unused by deployments" list the spec excluded** |

`action_loop_task`, `executor_done_callback` and `stop_action_task` are session methods that
delegate to the runner, mirroring how `split`/`finish` delegate to the finalizer.

**On the host** (`self.active.base.*`): `executors` — present. Plus, **not present**:

| member | kind | note |
|---|---|---|
| `local_action_task_queue` | list | serializes non-concurrent executors by action uuid |
| `aloop` | event loop | `create_task` target; legacy captures the running loop at startup |

**One thing to get right, easy to get wrong:** `action_loop_task` registers
`base.executors[executor.exec_id] = self.active` — the **session**, not the executor. So
`ActionHost.stop_executor_by_id` calling `.stop_action_task()` on the dict value is correct,
but the local variable naming there (`executor`) is misleading and should be renamed when
Task 6 lands.

**Also still missing on the host, for drivers rather than the runner:** `put_lbuf`,
`put_lbuf_nowait`, `get_lbuf` and the `_stamp_lbuf_dict` helper they share.
`ws_simulator`'s driver calls `self.base.put_lbuf(...)` in its poll loop and `WsExec` calls
`self.active.base.get_lbuf(...)`, so Task 7 cannot port that module without them.

**The recurring lesson, now three for three.** Each layer's requirement was only visible by
measuring the layer above it: the collaborators' 26 were invisible from the deployment-facing
18; the constructor's two host members were invisible from the class-level surface tests; and
the runner's four are invisible from both. Measure the caller before implementing the callee —
the spec's member lists are a floor, never a ceiling.

---

## 3b remainder — measured, blocked on a subsystem (2026-08-14)

`_make_app_entry_middleware` and `_make_http_exception_handler` were extracted and read.
The exception handler is four lines and is unblocked. **The queuing middleware is not**: it
depends on an endpoint-status subsystem the host does not have.

**What the middleware reads that does not exist yet:**

| member | source in legacy | note |
|---|---|---|
| `actionservermodel.endpoints[endpoint].active_dict` | `base_endpoints.py` (121 lines) | the per-endpoint busy check — the middleware's entire branch condition |
| `endpoint_queues[endpoint]` | `base_action_queue.py` (77 lines) | where a colliding action is parked |
| `local_action_queue` | `base_action_queue.py` | **distinct from `local_action_task_queue`**, which Task 6 added — one queues *actions* awaiting dispatch, the other serializes *executors*. Two similarly-named queues with different jobs; conflating them would deadlock or double-dispatch |

So 3b's remainder is really "port `base_endpoints.py` + `base_action_queue.py`", ~200 lines
plus the endpoint registration that populates them at startup (`init_endpoint_status`,
`endpoint_queues_init`, and `get_endpoint_urls`, which `/endpoints` already returns a
different shape for).

**Done in this pass**, because it was safe and the reading surfaced it:

- `host.actives` renamed from `_actives` — legacy's estop handler iterates `srv.actives`, and
  a private name would have quietly failed to match when the handler lands.
- `host.stop_executor` added as legacy's spelling, delegating to `stop_executor_by_id`.
- `stop_executor_by_id`'s local renamed `executor` → `session`, with a comment: the dict holds
  the **session**, which is what carries `stop_action_task`. The old name actively misled.

**Sequencing note for whoever picks this up.** The exception handler can land immediately —
it needs only `actives`, `executors` and `stop_executor`, all of which now exist. The
middleware should wait for the endpoint subsystem rather than being stubbed against a fake
busy-check, because "is this endpoint busy" returning a constant is indistinguishable from
working until two actions collide on a station.

### Task 7 — ws_simulator ported; a config consequence to handle before the next module

`helao/deploy/test/servers/action/ws_simulator.py` now builds an `ActionHost`, its two
handlers take `ctx: ActionContext`, and it constructs no `BaseAPI`. 5 tests, including a
source assertion that no legacy engine name survives and a full private-surface check.
`WsSim` and `WsExec` bodies are unchanged apart from one type hint.

**Porting a module breaks every config that routes it through the hexagon graft, and this
was not anticipated in the plan.** `goldenhex.yml` carries `deployment: hexagon` on SIM, which
resolves to `helao/deploy/hexagon/servers/action/ws_simulator.py` — the shim that calls
`makeActionApp`, imports the module, and grafts `graft_active_write_path(app.base, wiring)`
onto it at startup. `app.base` is now an `ActionHost`, which has no `contain_action`, so the
graft raises at startup rather than at import.

**Seventeen configs reference `ws_simulator`**, including two in private deployment repos.
Those that route it *without* `deployment: hexagon` (`golden.yml`, `test.yml`, …) already work
— the ported module is self-contained and serves the native host directly. Those that route it
*with* the key need it removed for that server, because the module is hexagon now and does not
want wrapping.

**The GM-parity consequence is the important one.** `golden.yml` was the legacy baseline for
this module; after the port it serves the native host too, so there is no longer a legacy
`ws_simulator` to capture from. **GM baselines for any ported module must be captured from a
pre-port commit** — `795c977a` (Task 1) is the last commit where `ws_simulator` still builds a
`BaseAPI`. Capture GM-1…GM-5 there before porting further modules, or the gate has nothing to
compare against.

Not yet done for this module: removing `deployment: hexagon` from the configs that carry it,
and a launched-server run. Nothing on this branch has yet served a request under uvicorn — the
tests drive the host through ASGI transport, which exercises routing, middleware and context
injection but not the RPC mirror, the WebSocket channels, or artifact writes to disk.

### GM legacy baselines captured (2026-08-14)

All five captured from `795c977a` — the last commit where `ws_simulator` still builds a
`BaseAPI`, and therefore the last point at which a legacy baseline for the `test` deployment
can be produced at all.

| set | files | size | location |
|---|---|---|---|
| GM-1 | 30 | 304K | `/home/dan/helao_goldens/GM-1/legacy` |
| GM-2 | 16 | 216K | `/home/dan/helao_goldens/GM-2/legacy` |
| GM-3 | 6 | 68K | `/home/dan/helao_goldens/GM-3/legacy` |
| GM-4 | 78 | 692K | `/home/dan/helao_goldens/GM-4/legacy` |
| GM-5 | 31 | 340K | `/home/dan/helao_goldens/GM-5/legacy` |

Each carries a `provenance.yml` recording `legacy_git_sha: 795c977acea1…`, the launch command,
the masked WsSim columns (`epoch_s`, `series_0..5` — the simulator's random values), the
`*WsSim*.hlo` row-count tolerance of 3, and the scenario's sequence params. Content includes
the S3 payloads the recording sink captured, the raw `.hlo`/`.csv` bodies, and the
action/process/experiment records — these are real runs, not empty trees.

**These live outside the repo** (`/home/dan/helao_goldens/`), consistent with the master spec's
Q2 note that goldens are repo-adjacent rather than tracked. They are not backed up; re-creating
them requires checking out `795c977a` again, which stays possible as long as that commit is
reachable — one more reason not to rebase this branch.

Task 8 compares against these with:

```bash
python -m harness.parity --golden /home/dan/helao_goldens/GM-1/legacy \
                         --candidate /home/dan/helao_goldens/GM-1/b1
```

**Two operational notes from the capture run**, both likely to recur:

- The capture rig **refuses a root containing prior run artifacts**, so every scenario needs
  `rm -rf` on the root and its own launch. One scenario per launch is a rig constraint, not a
  preference.
- `kill -INT` on the launcher left **ORCH still holding port 8001** after the harness timed out
  a foreground loop mid-scenario. The launcher exited while a child survived, which is what
  `PDEATHSIG` is supposed to prevent — plausibly because the launcher was killed by the harness
  rather than exiting through its own teardown path. Recovery was `ss -lptn 'sport = :8001'` to
  find the orphan and `kill -TERM` it. Worth knowing before blaming a port-in-use on a stale
  pid file.

### Task 7 — six more modules ported; control_sim and two others outstanding

Ported and verified building with the right route counts and `ctx` correctly hidden from the
exposed signature: `analysis_simulator` (1 route), `archive_simulator` (3), `cpsim_server` (4),
`motion_simulator` (2), `pstat_simulator` (1). With `ws_simulator` (2) that is **6 of 9
modules**.

**`control_sim` is ported but NOT verified.** It registers its action route from inside a
`dyn_endpoints` callback, and with a driver present that callback still yields zero
`/SRV/...` routes. Two things are tangled here and want separating before it is trusted:

1. **`dyn_endpoints` is sync but `init_endpoint_status` awaits it** — in legacy *and* in the
   port. Python calls it first (so registration happens) and then raises on `await None`.
   Legacy hides this: `dyn_endpoints_init` wraps the call in an un-awaited `asyncio.gather`,
   so the exception is discarded. The port reproduces both the call and the swallow, but any
   direct `await init_endpoint_status(...)` surfaces it.
2. Even so, no route appeared. Either `register_control_routes` registers under a different
   prefix, or it registers nothing when the simulated driver exposes no `dev_do` entries.

Do not "fix" the sync/async mismatch before establishing which. The swallow is legacy
behaviour that a station may depend on, and the missing route may be unrelated to it.

**All nine modules are now ported.** `gpsim_server` (6 action + 18 private) and
`sim_db_server` (0 action + 24 private) both build as `ActionHost`s with `ctx` correctly
hidden. `gpsim_server`'s recorded percent-log hang did not surface during the port; it is a
runtime path, so it stays a watch item for the first launched run rather than a resolved one.

`sim_db_server` was missed by the original survey because it declares no action routes while
still constructing a `BaseAPI` — **"modules with action routes" and "modules to port" are
different sets**, and only the second one matters. Count from `grep BaseAPI`, not from
`tags=["action"]`.

`grep BaseAPI` across `helao/deploy/test/servers/action/` now returns only explanatory prose in
`control_sim`'s docstrings. The `deploy/test` suite is ALL GREEN.

### Config cleanup done, and the native stack launches (2026-08-14)

`deployment: hexagon` removed from SIM (`ws_simulator`) and SYNC (`sim_db_server`) in
`goldenhex`, `goldenhexconc`, `goldenhexgraft`, `goldenhexid` and `goldenhexvis`. Those
modules are hexagon now; grafting onto them would call `makeActionApp` and reach for
`app.base.contain_action`, which an `ActionHost` does not have.

The key **stays** where it is still correct: on `async_orch2` (the orchestrator is legacy until
B3) and on the bokeh UI servers. `goldenhexgraft`'s purpose is unaffected — it proves the
*bokeh* generic graft as a public stand-in for a private deployment's flip, and that mechanism
is still needed for B4–B6.

**First launched run of the native stack.** `python launch.py goldenhex --no-hot-reload`:
all three servers up in ~28 s, **0 early exits**. The ERROR lines in the log are
`run_unit_tests.py`, which `launch.py` runs pre-launch and which exercises dispatcher error
paths deliberately.

**Gate item 1 passes on a live server:**

```
native SIM routes : 19
frozen legacy     : 19
missing: []   extra: []   VERDICT: IDENTICAL
```

The native `ActionHost` serves the same 19 routes, with the same methods and tags, as the
legacy `BaseAPI` capture taken from `795c977a`. This is the first evidence that the port
preserves the wire surface rather than merely passing unit tests.

**Still unproven:** WS frame parity, artifact parity (GM candidates), and the RPC mirror under
load. The legacy GM baselines are on disk; producing candidates needs a native run driven
through `harness.capture`, which is the next step.

### RESOLVED: the native hosts outlived their launcher (launcher teardown, not ActionHost)

Tearing down that first native launch with `kill -INT` on the launcher left **SIM (8002) and
SYNC (8010) still serving**, while ORCH (8001, still legacy) exited cleanly. Recovery was
`ss -lptn 'sport = :<port>'` then `kill -TERM`.

`grep "action shutdown"` on the launch log returns **nothing** — `ActionHost._shutdown` never
ran. That matters beyond tidiness: `_shutdown` is what stops the driver poller *before*
disconnecting the driver, and on real hardware a poller left running against a closed handle
is the failure this project has already fixed once.

**Do not conclude it is a B1 defect yet.** The same teardown on the *legacy* stack during the
GM capture run left the opposite set alive — ORCH survived while SIM and SYNC exited. An
inconsistent survivor set points at a race in launcher teardown when it is signalled from a
non-tty context, not at the host. Two candidate causes, and they are distinguishable:

1. `launch.py`'s teardown POSTs `/shutdown` and then signals; if the POST is what normally
   triggers `_shutdown`, a native host that answered it would have logged "action shutdown".
   It did not, so either the POST never arrived or the route did not reach the handler.
2. `PDEATHSIG` should have killed the children regardless. It did not, which is the same
   symptom seen in the GM run and is documented in CLAUDE.md as something that *should not*
   happen.

**How to settle it:** tear down with `CTRL-x` in a real terminal (the sanctioned path) and see
whether "action shutdown" appears. If it does, this is a harness artifact of `kill -INT` from
a background job. If it does not, `ActionHost` is not wired to the launcher's shutdown route
and that is a B1 blocker for any hardware station.

**Resolved 2026-08-14 by probing the route directly**, which distinguishes the two candidates
without needing a real terminal:

```
POST http://127.0.0.1:8002/shutdown   -> http=200
log: SIM :: _shutdown @ action_host.py:829 - action shutdown
SIM still serving afterwards
```

`ActionHost` **is** wired to the shutdown route and `_shutdown` does run. The process staying
up is *correct and matches legacy exactly*: `base_api.py:834`'s `post_shutdown` also just
`await shutdown_event()` and relies on the launcher to terminate the process afterwards.

So the orphaned servers are a **launcher-teardown / PDEATHSIG** problem — the same class seen
on the *legacy* stack during the GM capture run, where the opposite servers survived. Not a
B1 defect, and not a hardware blocker for this branch. It remains worth chasing on its own,
since CLAUDE.md documents PDEATHSIG as something that should make it impossible.

*Correction to the first report of this probe: `grep -c "action shutdown"` returned 3, but that
was counting this plan document's own prose alongside the log. The real log has one such line.
Grep a log path, not a directory that contains the write-up about it.*

### Defect found by the GM candidate run: ActionHost lacked `helaodirs`

All five native captures reported RIG DID NOT COME UP. Cause, from the launch log:

```
File "helao/core/drivers/data/sync_driver.py", line 2203, in __init__
  super().__init__(self.config_dict, self.base.helaodirs)
AttributeError: 'ActionHost' object has no attribute 'helaodirs'
```

`helaodirs` **is in the frozen `_member_surface.md` list**
(`base.(helaodirs|world_cfg|server_cfg|actionservermodel|dflt|aloop|put_lbuf|fast_urls)`). I
ported six of those eight and missed this one and `dflt`. Fixed by resolving it exactly as
legacy does — `helao_dirs(self.world_cfg, self.server.server_name)` at construction.
`dflt` is still outstanding.

**The more important lesson is how it stayed hidden.** An earlier launch was reported here as
"all three servers up in ~28 s, 0 early exits". That was almost certainly an **orphaned SYNC
from a previous run still holding port 8010** — the readiness probe counted a live port and
called the group healthy while the new SYNC had already crashed. This is precisely the hazard
CLAUDE.md documents: stale servers hold the ports and a new group "silently keeps serving the
*old* processes' code".

**A port check is not a health check.** Re-verified afterwards on a rig proven fresh (SYNC
started, zero `Application startup failed`), and additionally proved the server under test was
the native one by reading its own `/loaded_modules` for `hexagon/app/action_host` rather than
trusting that a launch had replaced what was listening. The route-surface IDENTICAL verdict
survives that re-check. Future runs should assert identity from `/loaded_modules`, not from a
port answering.

### GM parity, first full run (2026-08-14)

All five rigs came up with SIM and SYNC confirmed native via `/loaded_modules`. Four captured;
GM-5 aborted with `RuntimeError: GM-5: no RUNS_SYNCED zip after quiesce`.

| scenario | result |
|---|---|
| GM-1 | **FAIL — 91 diffs** |
| GM-2 | **PASS — 0 diffs** |
| GM-3 | **FAIL — 5 diffs** |
| GM-4 | **FAIL — 154 diffs** |
| GM-5 | no candidate (capture aborted) |

**GM-2 passing with 0 diffs is real and reproducible** — it passed on the previous run too. The
native write path produces byte-identical artifacts for that scenario.

**Two distinct failure signatures:**

1. **GM-3 (5 diffs): the entire `RUNS_DIAG` tree is absent from the candidate.** That is the
   *manual action* path — `seq--acquire_data__manual`.
2. **GM-1 and GM-4: diffs concentrated in `RUNS_SYNCED` (34/56), `S3_SIM` (25/40) and
   `PROCESSES` (5/9)**, overwhelmingly "golden present, candidate absent", plus 9 files each
   that exist only in the candidate. GM-5's abort — no RUNS_SYNCED zip — is the same leg.

**Concrete suspected cause for signature 1, and probably a contributor to signature 2.**
`action_context.build_action` ports `base_api._build_action_from_kwargs` faithfully but ports
**none of `Base._get_action`'s additional processing** (`base.py:355-394`). Missing:

- `action.action_name = action_name`
- the `fast_samples_in` → `samples_in` conversion, including `object_to_sample` and the
  `action_uuid` back-fill
- `action.action_abbr` defaulting to `action_name`
- **the `run_type is None` block that sets `orchestrator = MachineModel(server_name="MANUAL")`**
  — which is what routes a manually-dispatched action to `RUNS_DIAG`

Only the code-identity tail of `_get_action` was ported. `ActionSession.__init__` picked up
`action_server`, `dummy` and `simulation`, which is why this looked complete.

**Next step is to port the rest of `_get_action` into `build_action`**, then re-run. Do not
assume it explains all 245 diffs — signature 2 may additionally be a sync-timing or
sync-completeness problem, and GM-5's abort should be re-tested separately after the action
record is correct, since missing `samples_in` plausibly changes what the syncer has to ship.

**Note on the golden directory**: `/home/dan/helao_goldens/` also holds `GM-C1__ORBIS_QUANT`,
`GM-C2__XRDS`, `GM-C3__EASYXAFS_GAIA`, `mutation-work` and `p6-fixtures` from earlier phases.
Only `GM-1`…`GM-5` belong to B1.

### Re-run after porting `_get_action`: diff counts UNCHANGED (91 / 0 / 5 / 154)

**The prediction recorded before this run was wrong.** GM-3 did not go to zero; nothing moved.

The fix itself *is* live and correct — a GM-1 candidate `-act.yml` now carries
`run_type: simulation`, which it could not have before. So `_get_action`'s missing processing
was a genuine gap worth closing, but it was **not the cause of any observed diff**.

What the run actually established, by looking at the candidates rather than the counts:

1. **GM-3's candidate contains exactly one file — `provenance.yml`.** The legacy set has six.
   The native manual-action scenario produces **no artifacts at all**. Its "5 diffs" were never
   a partial mismatch; they are its entire expected output missing. This is a distinct defect
   from anything diagnosed so far, and the MANUAL/`RUNS_DIAG` routing hypothesis did not
   explain it — a manual action that writes nothing never reaches the routing decision.
2. **GM-1 and GM-4 write action records correctly** but diverge in `RUNS_SYNCED`, `S3_SIM` and
   `PROCESSES`, unchanged at 91 and 154. GM-5 still aborts with no RUNS_SYNCED zip. These three
   are one family: the **sync/S3 leg**, untouched by anything B1 has fixed.

**Two open defects, now cleanly separated:**

- **D1 — the manual-action path writes nothing** (GM-3). Start by establishing whether the
  action is dispatched at all under `goldenhex`, whether it completes, and whether `save_act`
  survives the port — not by reasoning about routing.
- **D2 — the sync/S3 leg is incomplete** (GM-1, GM-4, GM-5). Overwhelmingly "golden present,
  candidate absent", so the syncer ships less than legacy did. GM-5's abort is the cleanest
  reproduction and the smallest scenario, so diagnose there first.

**Method note.** Three consecutive fixes were guided by reading legacy source and reasoning
about what a diff implied. The first two were right; this one was right about the code and
wrong about the cause. The step that actually produced information here was listing the
candidate directory — one file versus six — which took seconds and would have redirected the
work before the fix was written. **Look at the artifact before theorising about the writer.**
