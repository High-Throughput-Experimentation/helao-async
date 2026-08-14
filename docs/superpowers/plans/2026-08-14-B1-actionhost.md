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
- **Never `pkill -f` a pattern that appears in your own command line** — the shell wrapper contains it and kills itself.
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

**Task 3 — started, then parked deliberately.** A draft `ActionHost` is at
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
