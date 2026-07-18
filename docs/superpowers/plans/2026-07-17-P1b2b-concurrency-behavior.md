# P1b2b: Concurrency Suite (§10.3 items 1–7) + §9 Behavior Tests on the Hexagon Path — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **EXCEPTION: Task Group B (Tasks 7–12) must execute in the MAIN SESSION** — launched-group runs in background subagents get reaped on idle (known execution constraint inherited from P1b2a).

**Goal:** Close the second half of the master-spec P1 gate (§12 P1): the §10.3 mandatory concurrency suite items 1–7 green against the **real** hexagon dispatch loop over **real** transport (ZMQ RPC + HTTP + WS) with **sim** action servers, plus the §9 cross-cutting behavior tests (logging, config identity, clock/NTP) asserted on the **hexagon composition path** — and land the P1b1 carry: `DispatcherStatusAdapter` `own_host`/`own_port` wiring.

**Architecture:** Two mechanisms, chosen per §10.3 item. (1) **In-process real-transport composition** for the precise-interleaving items (1, 3, 5): boot the REAL `makeOrchApp("ORCH")` + `makeActionApp("SIM", …ws_simulator)` compositions under uvicorn inside the test's event loop (real HTTP + the co-located ZMQ RPC mirrors HelaoFastAPI auto-registers), and inject races via `HexRuntime.handle(event)` from a concurrent asyncio task — the DD-3 injection point (`helao/hexagon/app/dispatch_loop.py:56`, `async def handle(self, event: Event) -> ErrorCodes`, reentrant by design). (2) **Launched-group runtime** for the full-run items (2, 4, 6, 7): drive a real `launch.py <prefix>` group with script drivers, reusing the P1b2a `parity_run.sh` boot/kill pattern (`helao/hexagon/tests/smoke/parity_run.sh`, `kill_group.py`), because these need complete multi-experiment runs and item 6 must kill a live sim server process mid-run. The dispatch loop already exists (P1b1); these tests **validate** it and may surface fidelity fixes — any fix lands in `helao/hexagon/` only.

**Tech Stack:** Python 3.12 in the `helao` conda env; pytest + pytest-asyncio (`@pytest.mark.asyncio`, already configured for `helao/hexagon/tests/`); uvicorn in-process serving (pattern proven in `helao/hexagon/tests/test_adapter_transport.py`); `launch.py` for launched groups; `helao/hexagon/` P1a domain + P1b1 adapters/app/graft; `helao/deploy/test/` sim servers + experiment libraries.

## Recommended Slicing

This plan is large. Recommended split for execution (single document, two clearly separated task groups; the controller decides):

- **P1b2b-1 (Task Group A, Tasks 1–6):** DispatcherStatusAdapter carry + in-process live-group harness + §9 behavior tests + §10.3 items 1/3/5. Pure pytest; subagent-executable.
- **P1b2b-2 (Task Group B, Tasks 7–12):** launched-group scaffolding + §10.3 items 2/4/6/7 + gate verification. **Main session only.**

## Per-item mechanism table

| §10.3 item | Mechanism | Where | Race/trigger injection | Transport under test |
|---|---|---|---|---|
| 1 lost wakeup / double drain | in-process | `test_concurrency_live.py` | burst `runtime.handle(StatusChanged(…))` + `loop_wake.set()` from concurrent task | ZMQ RPC + HTTP (submit/dispatch), real WS on SIM |
| 2 non-default identity | launched group | `conc_items.py item2` + `goldenhexid.yml` | none (full run under renamed orch key `HEXORC`) | full launched stack |
| 3 estop decision↔effect (a/b/c) | in-process | `test_concurrency_live.py` | (a),(b): POST `/estop_orch` over real dispatcher while gated; (c): `runtime.handle(ActionResultErrored(…))` while gated | ZMQ RPC + HTTP |
| 4 serial ≥3-experiment sequence | launched group | `conc_items.py item4` | none (natural run) | full launched stack |
| 5 nonblocking lifecycle | in-process | `test_concurrency_live.py` | adapter → real `/update_nonblocking`; full `TEST_consecutive_noblocking` run | ZMQ RPC + HTTP |
| 6 history-poll hang exit | launched group | `conc_items.py item6` + `goldenhexconc.yml` | SIGKILL the SIM process (pid pickle) mid-action | full launched stack |
| 7 idle drain | launched group | `conc_items.py item7` | none (natural drain, no `/stop`) | full launched stack |

## Global Constraints

- **Zero legacy edits.** Wrap, never patch: no file under `helao/core/`, `helao/helpers/`, or `helao/deploy/` is **modified**. New files under `helao/deploy/test/configs/` (configs only) follow the P1b1 `goldenhex.yml` precedent. If a test can only pass by editing legacy, STOP and escalate — that is a fidelity finding.
- **Any race a test surfaces is fixed in `helao/hexagon/` ONLY** (never legacy).
- **No private-deployment names** in any committed file, comment, log, or docstring — public repo; aliases A/B/C/D only if a private deployment must be referenced. This phase is `test`-deployment only.
- **All Python via `conda run -n helao`** — never the OS python (3.14). Repo root is `/mnt/STORAGE/repos/helao/helao-async`.
- **Tests live under `helao/hexagon/tests/`** (launched-group drivers under `helao/hexagon/tests/smoke/`).
- **This suite is BLOCKING for the orch milestone; every green claim must name the transport used (§10.2).** Task 12 records the per-item transport evidence.
- **`conda run -n helao pyright helao/hexagon` = 0 errors and `black` clean at the end of every task** (run black on changed files right before each commit).
- **Fixture fidelity (§10.1):** routes registered through the real registration code (real `makeOrchApp`/`makeActionApp`, real `HelaoFastAPI` RPC mirror); no hand-rolled fake endpoints; no stub orchs — the orchestrator in every test here is the real legacy `Orch` wrapped by the P1b1 graft.
- **Branch:** create `feat/p1b2b-concurrency-behavior` off `unstable`; do not push without authorization.
- **Port hygiene:** launched groups own 8001/8002/8010 (goldenhex family). In-process tests use 8101 (ORCH) / 8102 (SIM) — RPC mirrors land on 18101/18102 — so a stray launched group never collides with pytest.

---

# Task Group A — P1b2b-1 (in-process; pytest; subagent-executable)

### Task 1: `DispatcherStatusAdapter` own-identity carry (P1b1 follow-up)

The adapter (`helao/hexagon/adapters/legacy/status.py:46`, `def __init__(self, server_key: str, own_host: str = "", own_port: int = 0)`) currently defaults to `own_host=""`/`own_port=0`, and nothing constructs it in the composition — `build_wiring` (`helao/hexagon/app/factory.py:27`) leaves `PortWiring.status = None`. Downstream `clear_nonblocking` bookkeeping is keyed on `(server_key, exec_id, server_host, server_port)` (`helao/core/servers/orch_status_sync.py:145`), so a `""`/`0` identity breaks the nonblocking round-trip §10.3 item 5 needs.

**Files:**
- Modify: `helao/hexagon/app/factory.py` (wire the adapter in `build_wiring`)
- Modify: `helao/hexagon/app/wiring.py:38-39` (add `"status"` to `ORCH_REQUIRED` and `ACTION_REQUIRED`)
- Modify: `helao/hexagon/adapters/legacy/status.py:20-26` (docstring: the "Known gap" paragraph is now closed — rewrite it to say composition supplies `own_host`/`own_port` from the server's config entry)
- Test: `helao/hexagon/tests/test_factory.py` (extend)

**Interfaces:**
- Consumes: `LegacyConfigAdapter.server_cfg(server_key) -> dict` (raises `KeyError` on unknown key — loud); `DispatcherStatusAdapter(server_key, own_host=…, own_port=…)`.
- Produces: `build_wiring(server_key).status` is a `DispatcherStatusAdapter` whose `_own_host`/`_own_port` equal the server's config `host`/`port`. `ORCH_REQUIRED = ("config", "logging", "clock", "transport", "state_persistence", "status")`; `ACTION_REQUIRED = ("config", "logging", "clock", "transport", "status")`. Tasks 2/6 rely on `app.hexagon_wiring.status` being wired.

- [ ] **Step 1: Write the failing test**

Append to `helao/hexagon/tests/test_factory.py` (it already defines the `installed_config` fixture with ORCH at `127.0.0.1:8901`, SIM at `127.0.0.1:8902`):

```python
def test_build_wiring_status_port_carries_own_identity(installed_config):
    """P1b1 carry: the status adapter must be composed with the server's own
    host/port from config (orch_status_sync keys nonblocking bookkeeping on
    them) — never the ''/0 defaults."""
    from helao.hexagon.adapters.legacy.status import DispatcherStatusAdapter
    from helao.hexagon.app.factory import build_wiring
    from helao.hexagon.ports.status import StatusPort

    w = build_wiring("SIM")
    assert isinstance(w.status, DispatcherStatusAdapter)
    assert isinstance(w.status, StatusPort)
    assert w.status._own_host == "127.0.0.1"
    assert w.status._own_port == 8902
    # the composition's consumed set now includes status (fail-loud stays real)
    w.require("config", "logging", "clock", "transport", "status")


@pytest.mark.asyncio
async def test_status_wire_send_carries_composed_identity(
    installed_config, monkeypatch
):
    """send_nonblocking_status must put the COMPOSED host/port on the wire
    (params_dict server_host/server_port), not ''/0."""
    from helao.core.error import ErrorCodes
    from helao.hexagon.app.factory import build_wiring
    import helao.hexagon.adapters.legacy.status as status_mod

    sent = []

    async def _fake_dispatch(
        server_key, host, port, private_action, params_dict, json_dict,
        timeout=60, retries=5,
    ):
        sent.append((private_action, params_dict))
        return {}, ErrorCodes.none

    monkeypatch.setattr(status_mod, "async_private_dispatcher", _fake_dispatch)
    w = build_wiring("SIM")
    assert w.status is not None
    await w.status.send_nonblocking_status(
        "ORCH", "127.0.0.1", 8901, "SIM", "SIM exec_1", None, "active"
    )
    action, params = sent[0]
    assert action == "update_nonblocking"
    assert params == {"server_host": "127.0.0.1", "server_port": 8902}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_factory.py -v -k identity`
Expected: FAIL — `w.status` is `None` (`assert isinstance(None, DispatcherStatusAdapter)`).

- [ ] **Step 3: Implement**

In `helao/hexagon/app/factory.py`, add the import and wire the adapter:

```python
from helao.hexagon.adapters.legacy.status import DispatcherStatusAdapter
```

and change `build_wiring` to:

```python
def build_wiring(server_key: str) -> PortWiring:
    config = from_global_config()  # raises when CONFIG is not installed
    root = config.root()  # KeyError -> loud, like helao_dirs
    log_root = os.path.join(root, "LOGS")
    scfg = config.server_cfg(server_key)  # KeyError -> loud, like the launcher
    return PortWiring(
        config=config,
        logging=LegacyLoggingAdapter(),
        clock=LegacyClockAdapter.from_offset_file(log_root),
        transport=LegacyTransportAdapter(config),
        state_persistence=QueuePckStore(root),
        status=DispatcherStatusAdapter(
            server_key, own_host=scfg["host"], own_port=scfg["port"]
        ),
    )
```

In `helao/hexagon/app/wiring.py`, change the required sets to:

```python
ORCH_REQUIRED = ("config", "logging", "clock", "transport", "state_persistence", "status")
ACTION_REQUIRED = ("config", "logging", "clock", "transport", "status")
```

In `helao/hexagon/adapters/legacy/status.py`, replace the "Known gap (flagged, not silently papered over): …" paragraph (lines 20–26) with:

```
Own identity (closed P1b1 gap): the composition (factory.build_wiring)
constructs this adapter with ``own_host``/``own_port`` taken from the
server's own config entry, so downstream ``clear_nonblocking`` bookkeeping
(keyed on host/port in orch_status_sync) sees the real reporting identity.
The ``""``/``0`` defaults remain only for unit construction convenience.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_factory.py helao/hexagon/tests/test_wiring.py helao/hexagon/tests/test_adapters_misc.py -v`
Expected: PASS (all — including the pre-existing factory tests, which call `w.require(…)` with the old five-name set; that call stays valid because `require` checks the *named* subset).

- [ ] **Step 5: Type/format gate + commit**

```bash
conda run -n helao pyright helao/hexagon
conda run -n helao black helao/hexagon/app/factory.py helao/hexagon/app/wiring.py helao/hexagon/adapters/legacy/status.py helao/hexagon/tests/test_factory.py
git add helao/hexagon/app/factory.py helao/hexagon/app/wiring.py helao/hexagon/adapters/legacy/status.py helao/hexagon/tests/test_factory.py
git commit -m "feat(hexagon): wire DispatcherStatusAdapter own identity in build_wiring (P1b1 carry)"
```

---

### Task 2: In-process real-transport live group harness

The reusable boot for §10.3 items 1/3/5: real ORCH + SIM apps from the factory, served by uvicorn **inside the test's event loop** (same pattern as `test_adapter_transport.py::test_private_dispatch_roundtrip_via_colocated_rpc`, which proved real `HelaoFastAPI` + RPC-mirror boot in-process). One process ⇒ shared `CONFIG` + logging singleton (documented deviation from launched groups; the transport between the two apps is still real ZMQ/HTTP/WS).

**Files:**
- Create: `helao/hexagon/tests/live_group.py`
- Test: `helao/hexagon/tests/test_live_group.py`

**Interfaces:**
- Consumes: `makeOrchApp(server_key)` / `makeActionApp(server_key, legacy_module)` (`helao/hexagon/app/factory.py:40,72`); `app.hexagon_graft` (set by the factory's startup handler *after* `OrchAPI.__init__`'s own startup creates `app.orch`); `HexagonGraft.runtime: HexRuntime`; `async_private_dispatcher(server_key, host, port, private_action, params_dict, json_dict)` (`helao/helpers/dispatcher.py`); `aclose_all_rpc_clients()`.
- Produces (used verbatim by Tasks 3–6):
  - `live_group(tmp_root: str, ntp_offset_s: float = 0.0) -> AsyncContextManager[LiveGroup]` with `LiveGroup(orch, runtime, orch_app, sim_app, world, root)` (dataclass).
  - `ORCH_HOST/ORCH_PORT = "127.0.0.1"/8101`, `SIM_HOST/SIM_PORT = "127.0.0.1"/8102` module constants.
  - `async orch_call(endpoint: str, params: dict | None = None, body: dict | None = None) -> dict` (real dispatcher → ORCH; asserts `ErrorCodes.none`).
  - `build_ws_sequence(n_exps: int, wait_time: float = 1.0, data_duration: float = 2.0) -> Sequence` (each experiment = wait, acquire, wait, acquire — 4 actions, per `simulatews_exp.SIM_websocket_data`).
  - `async wait_parked(orch, timeout_s: float = 120.0) -> None` (loop parked stopped + all queues empty + no active_dict).

- [ ] **Step 1: Write the harness**

`helao/hexagon/tests/live_group.py`:

```python
"""In-process REAL-transport hexagon group for §10.3 precise-interleaving
items (P1b2b: items 1, 3, 5).

Boots the REAL makeOrchApp/makeActionApp compositions under uvicorn inside
the test's event loop — real HTTP routes registered through the real
registration code, and the co-located ZMQ RPC mirrors HelaoFastAPI
auto-registers on http_port+10000 (§10.1 fixture-fidelity; boot pattern
proven by test_adapter_transport.py). Race injection happens via
app.hexagon_graft.runtime.handle(event) from a concurrent task (DD-3).

NOT a stub orch: the orchestrator is the real legacy Orch wrapped by the
P1b1 graft; the SIM is the real ws_simulator makeApp. Single process ==
shared CONFIG dict + logging singleton (a documented deviation from
launched groups; items 2/4/6/7 run against a real launched group instead).

Ports 8101/8102 (RPC mirrors 18101/18102) so a live goldenhex launch on
8001/8002/8010 never collides with pytest."""

import asyncio
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass

import uvicorn

from helao.core.error import ErrorCodes
from helao.helpers import config_loader
from helao.helpers import helao_logging
from helao.helpers.dispatcher import aclose_all_rpc_clients, async_private_dispatcher
from helao.helpers.helao_logging import make_logger
from helao.helpers.premodels import ExperimentPlanMaker, Sequence
from helao.helpers.time_utils import gen_uuid
from helao.hexagon.domain.models import LoopStatus

ORCH_HOST, ORCH_PORT = "127.0.0.1", 8101  # RPC mirror -> 18101
SIM_HOST, SIM_PORT = "127.0.0.1", 8102  # RPC mirror -> 18102

__all__ = [
    "LiveGroup",
    "ORCH_HOST",
    "ORCH_PORT",
    "SIM_HOST",
    "SIM_PORT",
    "build_ws_sequence",
    "live_group",
    "orch_call",
    "wait_parked",
]


@dataclass
class LiveGroup:
    orch: object
    runtime: object  # HexRuntime — untyped to avoid import cycles in tests
    orch_app: object
    sim_app: object
    world: dict
    root: str


def make_world(root: str) -> dict:
    """goldenhex.yml minus the DB server, on the test-local ports."""
    return {
        "dummy": True,
        "simulation": True,
        "run_type": "simulation",
        "root": root,
        "experiment_libraries": [
            "simulatews_exp",
            "helao/deploy/test/experiments/TEST_exp.py",
        ],
        "sequence_libraries": ["helao/deploy/test/sequences/TEST_seq.py"],
        "servers": {
            "ORCH": {
                "host": ORCH_HOST,
                "port": ORCH_PORT,
                "group": "orchestrator",
                "fast": "async_orch2",
                "deployment": "hexagon",
                "params": {},
            },
            "SIM": {
                "host": SIM_HOST,
                "port": SIM_PORT,
                "group": "action",
                "fast": "ws_simulator",
                "deployment": "hexagon",
                "params": {},
            },
        },
    }


async def _serve(app, host: str, port: int):
    cfg = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(cfg)
    task = asyncio.create_task(server.serve())
    for _ in range(200):
        if server.started:
            return server, task
        await asyncio.sleep(0.1)
    raise RuntimeError(f"uvicorn on {host}:{port} never started")


@asynccontextmanager
async def live_group(tmp_root: str, ntp_offset_s: float = 0.0):
    """Boot SIM then ORCH (subscribe_all finds the SIM), reproducing the
    §9.1 ordering: root/LOGS + ntpLastSync.txt + singleton logger exist
    BEFORE any composition import runs. The offset file also keeps Base
    from hitting live NTP in-process."""
    log_dir = os.path.join(tmp_root, "LOGS")
    os.makedirs(log_dir, exist_ok=True)
    with open(os.path.join(log_dir, "ntpLastSync.txt"), "w") as f:
        f.write(f"1752600000.0,{ntp_offset_s}")
    world = make_world(tmp_root)
    prev_cfg = config_loader.CONFIG
    prev_logger = helao_logging.LOGGER
    config_loader.CONFIG = world  # test-scoped install; restored on exit
    if helao_logging.LOGGER is None:
        helao_logging.LOGGER = make_logger("hexlive", log_dir=log_dir)

    from helao.hexagon.app.factory import makeActionApp, makeOrchApp

    sim_app = makeActionApp("SIM", "helao.deploy.test.servers.action.ws_simulator")
    orch_app = makeOrchApp("ORCH")
    sim_server, sim_task = await _serve(sim_app, SIM_HOST, SIM_PORT)
    orch_server, orch_task = await _serve(orch_app, ORCH_HOST, ORCH_PORT)
    try:
        graft = None
        for _ in range(200):  # graft lands on the startup event, after app.orch
            graft = getattr(orch_app, "hexagon_graft", None)
            if graft is not None:
                break
            await asyncio.sleep(0.05)
        assert graft is not None, "hexagon graft never installed at startup"
        yield LiveGroup(
            orch=orch_app.orch,
            runtime=graft.runtime,
            orch_app=orch_app,
            sim_app=sim_app,
            world=world,
            root=tmp_root,
        )
    finally:
        orch_server.should_exit = True
        sim_server.should_exit = True
        await asyncio.wait_for(
            asyncio.gather(orch_task, sim_task, return_exceptions=True), timeout=20
        )
        await aclose_all_rpc_clients()
        config_loader.CONFIG = prev_cfg
        helao_logging.LOGGER = prev_logger


async def orch_call(endpoint: str, params=None, body=None) -> dict:
    """Real-transport call into the live ORCH (ZMQ RPC first, HTTP fallback)."""
    resp, err = await async_private_dispatcher(
        "ORCH", ORCH_HOST, ORCH_PORT, endpoint, params or {}, body or {}
    )
    assert err is ErrorCodes.none, f"/{endpoint} -> {err}"
    return resp


def build_ws_sequence(
    n_exps: int, wait_time: float = 1.0, data_duration: float = 2.0
) -> Sequence:
    """SIM_websocket_data experiments: 4 actions each (wait, acquire, x2)."""
    epm = ExperimentPlanMaker()
    for _ in range(n_exps):
        epm.add(
            "SIM_websocket_data",
            {"wait_time": wait_time, "data_duration": data_duration},
        )
    return Sequence(
        sequence_name="SIM_websocket_data_seq",
        sequence_label="p1b2b",
        sequence_params={"wait_time": wait_time, "data_duration": data_duration},
        planned_experiments=epm.planned_experiments,
        sequence_uuid=gen_uuid(),
        dummy=True,
        simulation=True,
    )


async def wait_parked(orch, timeout_s: float = 120.0) -> None:
    for _ in range(int(timeout_s / 0.25)):
        gsm = orch.globalstatusmodel
        if (
            gsm.loop_state == LoopStatus.stopped
            and not orch.action_dq
            and not orch.experiment_dq
            and not orch.sequence_dq
            and not gsm.active_dict
        ):
            return
        await asyncio.sleep(0.25)
    raise TimeoutError(
        f"group never parked: loop_state={orch.globalstatusmodel.loop_state} "
        f"dq=({len(orch.action_dq)},{len(orch.experiment_dq)},{len(orch.sequence_dq)})"
    )
```

- [ ] **Step 2: Write the failing smoke test**

`helao/hexagon/tests/test_live_group.py`:

```python
"""Live in-process group smoke: a real 1-experiment run drains to
RUNS_FINISHED through the hexagon graft over real transport. This is the
foundation every §10.3 in-process item builds on — if this hangs or fails,
fix the harness FIRST (systematic-debugging), never weaken it to a stub."""

from pathlib import Path

import pytest

from helao.hexagon.domain.models import LoopStatus
from helao.hexagon.tests.live_group import (
    build_ws_sequence,
    live_group,
    orch_call,
    wait_parked,
)


@pytest.mark.asyncio
async def test_live_group_runs_one_experiment_to_finished(tmp_path):
    async with live_group(str(tmp_path)) as g:
        seq = build_ws_sequence(1, wait_time=1.0, data_duration=2.0)
        await orch_call("append_sequence", body={"sequence": seq.as_dict()})
        await orch_call("start")
        await wait_parked(g.orch, timeout_s=180.0)
        assert g.orch.globalstatusmodel.loop_state == LoopStatus.stopped
        finished = list((tmp_path / "RUNS_FINISHED").rglob("*-seq.yml"))
        assert finished, "sequence yml missing from RUNS_FINISHED"
        exp_ymls = list((tmp_path / "RUNS_FINISHED").rglob("*-exp.yml"))
        assert len(exp_ymls) == 1
        # the graft is live: the runtime is the drainer's runtime
        assert g.runtime is g.orch_app.hexagon_graft.runtime
```

- [ ] **Step 3: Run it — expect failure or errors first**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_live_group.py -v -x`
Expected: FAIL initially (module `live_group` not yet importable if Step 1 not saved, or boot issues surface). **Debug notes for the implementer — likely first-boot failures and their sanctioned fixes:**
  - `Orch`/`Base` startup expecting launcher-augmented config keys (`loaded_config_path`, `helao_repo_root`): add them to `make_world` output (`world["loaded_config_path"] = root + "/goldenhex-inproc.yml"`, `world["helao_repo_root"] = str(Path(__file__).resolve().parents[3])`) — config-dict-only change in the harness, not legacy.
  - Live NTP calls despite the offset file: check `Base`'s ntp path; the offset file must exist before `makeOrchApp` runs (it does, Step 1 ordering).
  - Finish path requiring a DB server entry: if the run stalls at finish because a `DB` entry is required, add the legacy sim DB as a third in-process app (`import helao.deploy.test.servers.action.sim_db_server` via its `makeApp("DB")` on port 8110) — extend `make_world` and `live_group` accordingly. Do NOT stub it.

- [ ] **Step 4: Iterate until the smoke passes**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_live_group.py -v -x`
Expected: PASS in ≤ ~180 s. If a hang implicates the hexagon loop itself (not the harness), that is a real §10.3 finding — root-cause and fix in `helao/hexagon/` only.

- [ ] **Step 5: Type/format gate + commit**

```bash
conda run -n helao pyright helao/hexagon
conda run -n helao black helao/hexagon/tests/live_group.py helao/hexagon/tests/test_live_group.py
git add helao/hexagon/tests/live_group.py helao/hexagon/tests/test_live_group.py
git commit -m "test(hexagon): in-process real-transport live group harness (P1b2b)"
```

---

### Task 3: §9 behavior tests on the hexagon composition path

The §9 contracts were pinned against legacy in P0 (`harness/tests/test_legacy_contracts.py`); unit-level port tests exist (`helao/hexagon/tests/test_adapters_runtime_services.py`). This task asserts them through the **composition entry point** (`build_wiring`), which is what the P1 gate means by "§9 behavior tests green on the hexagon path". (The launched-path §9.1 log-file assert rides along in Task 11 — a per-process `<root>/LOGS/<server_key>.log` only exists under the real launcher.)

**Files:**
- Test: `helao/hexagon/tests/test_behavior_hexagon.py` (create)

**Interfaces:**
- Consumes: `build_wiring(server_key) -> PortWiring`; `LegacyLoggingAdapter.file_logger(server_key, log_root)` (raises `ValueError` on falsy root); `LegacyClockAdapter.offset() -> float`, `.now() -> datetime`; `LegacyConfigAdapter.world_cfg()/.server_cfg(key)`; legacy `set_time(offset)` (`helao/helpers/time_utils.py`).
- Produces: nothing downstream; gate evidence only.

- [ ] **Step 1: Write the failing tests**

`helao/hexagon/tests/test_behavior_hexagon.py`:

```python
"""§9 cross-cutting behavior contracts asserted on the HEXAGON composition
path (master spec §9.1–9.3; P1 gate). The P0 twins pinning the same
contracts against legacy live in harness/tests/test_legacy_contracts.py."""

import os
import tempfile
from pathlib import Path

import pytest

from helao.helpers import config_loader
from helao.helpers.time_utils import set_time

OFFSET_S = 120.0


def _world(tmp_path):
    return {
        "root": str(tmp_path),
        "dummy": True,
        "simulation": True,
        "servers": {
            "ORCH": {
                "host": "127.0.0.1",
                "port": 8901,
                "group": "orchestrator",
                "fast": "async_orch2",
                "params": {},
            },
            "SIM": {
                "host": "127.0.0.1",
                "port": 8902,
                "group": "action",
                "fast": "ws_simulator",
                "params": {},
            },
        },
    }


@pytest.fixture()
def hex_world(tmp_path, monkeypatch):
    world = _world(tmp_path)
    log_dir = tmp_path / "LOGS"
    log_dir.mkdir()
    (log_dir / "ntpLastSync.txt").write_text(f"1752600000.0,{OFFSET_S}")
    monkeypatch.setattr(config_loader, "CONFIG", world)
    return world


# --- §9.1 logging: contractual path, tempdir traps dead behind the port -----
def test_s9_1_composition_log_file_lands_under_root_logs(hex_world, monkeypatch):
    from helao.hexagon.app.factory import build_wiring

    mkdtemp_dirs = []
    real_mkdtemp = tempfile.mkdtemp

    def spy_mkdtemp(*a, **k):
        d = real_mkdtemp(*a, **k)
        mkdtemp_dirs.append(d)
        return d

    monkeypatch.setattr(tempfile, "mkdtemp", spy_mkdtemp)
    w = build_wiring("ORCH")
    log_root = os.path.join(hex_world["root"], "LOGS")
    lg = w.logging.file_logger("HEXBEH", log_root)
    lg.info("hexagon §9.1 behavior check")  # type: ignore[attr-defined]
    assert (Path(log_root) / "HEXBEH.log").exists()  # flat file, no subdir
    assert not any(
        (Path(d) / "HEXBEH.log").exists() for d in mkdtemp_dirs
    ), "log file must never land in a temp dir"
    # no parallel LOGS_FW-style directory, ever (§9.1 rule 2)
    assert not (Path(hex_world["root"]) / "LOGS_FW").exists()


def test_s9_1_composition_port_refuses_unresolved_log_root(hex_world):
    from helao.hexagon.app.factory import build_wiring

    w = build_wiring("ORCH")
    with pytest.raises(ValueError):
        w.logging.file_logger("HEXBEH", None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        w.logging.file_logger("HEXBEH", "")


# --- §9.2 config: raw-dict identity through the composition ------------------
def test_s9_2_config_identity_and_restore_aliasing(hex_world):
    from helao.hexagon.app.factory import build_wiring

    w = build_wiring("ORCH")
    # the port hands out views of THE installed dict object
    assert w.config.world_cfg() is config_loader.CONFIG
    assert w.config.world_cfg() is hex_world
    # --restore's same-object aliasing gate: server sub-dict IS the object
    assert w.config.server_cfg("ORCH") is hex_world["servers"]["ORCH"]
    # mutation through the raw dict is visible through the port (no copies)
    hex_world["servers"]["ORCH"]["params"]["marker"] = 1
    assert w.config.server_cfg("ORCH")["params"]["marker"] == 1


# --- §9.3 clock: offset file drives every minted timestamp -------------------
def test_s9_3_clock_offset_file_shifts_composition_time(hex_world):
    from helao.hexagon.app.factory import build_wiring

    w = build_wiring("ORCH")
    assert w.clock.offset() == OFFSET_S
    delta = (w.clock.now() - set_time(0)).total_seconds()
    assert OFFSET_S - 2.0 < delta < OFFSET_S + 2.0


def test_s9_3_clock_missing_offset_file_is_zero(tmp_path, monkeypatch):
    world = _world(tmp_path)
    (tmp_path / "LOGS").mkdir()  # no ntpLastSync.txt
    monkeypatch.setattr(config_loader, "CONFIG", world)
    from helao.hexagon.app.factory import build_wiring

    w = build_wiring("ORCH")
    assert w.clock.offset() == 0.0
```

- [ ] **Step 2: Run tests — expect pass-or-fail split**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_behavior_hexagon.py -v`
Expected: most PASS immediately (the P1b1 adapters were built to these contracts). **Any failure here is a real §9 fidelity finding** — root-cause it (superpowers:systematic-debugging) and fix the adapter/factory in `helao/hexagon/` only. Do not weaken the assert.

- [ ] **Step 3: Type/format gate + commit**

```bash
conda run -n helao pyright helao/hexagon
conda run -n helao black helao/hexagon/tests/test_behavior_hexagon.py
git add helao/hexagon/tests/test_behavior_hexagon.py
git commit -m "test(hexagon): §9 logging/config/clock behavior asserted on the composition path (P1b2b)"
```

---

### Task 4: §10.3 item 1 — lost wakeup / double drain

Status bursts while the loop is mid-effect; single-drainer semantics must hold: no double-popped queue, no duplicated FinishExperiment. Bursts are injected through the sanctioned reentrant entry `runtime.handle(event)` (`HexRuntime.handle`, `dispatch_loop.py:56`) plus `runtime.loop_wake.set()` — exactly the wake path real status ingestion uses.

**Files:**
- Test: `helao/hexagon/tests/test_concurrency_live.py` (create — Tasks 5 and 6 append to it)

**Interfaces:**
- Consumes: Task 2's `live_group`/`orch_call`/`build_ws_sequence`/`wait_parked`; `StatusChanged(any_active: bool)` event (`helao/hexagon/domain/orchestration.py:167`); real Orch surface: `orch.loop_task_dispatch_action`, `orch.finish_active_experiment`, `orch.active_experiment`, `orch.action_history` (dict uuid→meta), `orch.globalstatusmodel.active_dict`.
- Produces: the spy-wrap idiom (instance-level rebinding — the sanctioned wrap seam, per the `graft_hexagon_loop` docstring) reused by Task 5.

- [ ] **Step 1: Write the failing test**

`helao/hexagon/tests/test_concurrency_live.py`:

```python
"""§10.3 mandatory concurrency suite — in-process real-transport items
(1, 3, 5). Real hexagon ORCH (makeOrchApp graft) + real SIM (ws_simulator)
over real ZMQ RPC + HTTP; races injected via HexRuntime.handle from
concurrent tasks (DD-3). Launched-group items (2, 4, 6, 7) live in
helao/hexagon/tests/smoke/conc_items.py."""

import asyncio
from pathlib import Path

import pytest

from helao.hexagon.domain.models import LoopStatus
from helao.hexagon.domain.orchestration import (
    ActionResultErrored,
    CloseOutExperimentCmd,
    FinishThenDispatchExperimentCmd,
    StatusChanged,
)
from helao.hexagon.tests.live_group import (
    SIM_HOST,
    SIM_PORT,
    build_ws_sequence,
    live_group,
    orch_call,
    wait_parked,
)


def _spy_finishers(orch):
    """Instance-rebind counting wrappers (the sanctioned wrap seam): count
    clean experiment finishes only when an experiment was actually active
    (the real finish_active_experiment no-ops otherwise), and count the
    estop finalizer. Returns (clean_finishes, estop_finishes) lists."""
    clean, estop = [], []
    orig_finish = orch.finish_active_experiment
    orig_estop_finish = orch.estop_finish_active

    async def spy_finish(*a, **k):
        if orch.active_experiment is not None:
            clean.append(1)
        return await orig_finish(*a, **k)

    async def spy_estop_finish(*a, **k):
        estop.append(1)
        return await orig_estop_finish(*a, **k)

    orch.finish_active_experiment = spy_finish
    orch.estop_finish_active = spy_estop_finish
    return clean, estop


# =============================================================================
# Item 1: lost wakeup / double drain
# =============================================================================
@pytest.mark.asyncio
async def test_item1_status_burst_no_double_drain(tmp_path):
    """Burst status-shaped events + wakes at the loop while a 2-experiment
    run is mid-flight. Single-drainer semantics: each experiment finishes
    exactly once, every dispatched action is unique, nothing double-pops."""
    async with live_group(str(tmp_path)) as g:
        orch, runtime = g.orch, g.runtime
        clean_finishes, _ = _spy_finishers(orch)
        dispatches = []
        orig_dispatch = orch.loop_task_dispatch_action

        async def spy_dispatch(*a, **k):
            dispatches.append(1)
            return await orig_dispatch(*a, **k)

        orch.loop_task_dispatch_action = spy_dispatch

        seq = build_ws_sequence(2, wait_time=1.0, data_duration=2.0)
        await orch_call("append_sequence", body={"sequence": seq.as_dict()})
        await orch_call("start")

        stop_burst = asyncio.Event()

        async def burst():
            while not stop_burst.is_set():
                any_active = bool(orch.globalstatusmodel.active_dict)
                await runtime.handle(StatusChanged(any_active=any_active))
                runtime.loop_wake.set()  # the lost-wakeup provocation
                await asyncio.sleep(0.005)

        burst_task = asyncio.create_task(burst())
        try:
            await wait_parked(orch, timeout_s=240.0)
        finally:
            stop_burst.set()
            await burst_task

        # no duplicated FinishExperiment: exactly one clean finish per exp
        assert len(clean_finishes) == 2, clean_finishes
        # no double-popped queue: 2 exps x 4 actions, each dispatched once,
        # and each dispatch registered exactly one unique action uuid
        assert len(dispatches) == 8, dispatches
        assert len(orch.action_history) == 8
        # every action reached a finished timestamp (nothing stuck/lost)
        assert all(
            meta.get("action_finished_timestamp")
            for meta in orch.action_history.values()
        )
        # artifacts: exactly one exp yml per experiment, none duplicated
        exp_ymls = list((tmp_path / "RUNS_FINISHED").rglob("*-exp.yml"))
        assert len(exp_ymls) == 2
        assert orch.globalstatusmodel.loop_state == LoopStatus.stopped
```

- [ ] **Step 2: Run it**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_concurrency_live.py::test_item1_status_burst_no_double_drain -v -x`
Expected: PASS if the single-drainer invariant holds (it is structural in `HexDispatchLoop`). A FAIL (duplicate finish, action count ≠ 8, or a hang) is a **real race finding** — root-cause with superpowers:systematic-debugging; fix in `helao/hexagon/` only; keep the test unchanged.

NOTE (assumption to verify on first run): the 8-action count assumes `orch.action_history` gains exactly one entry per dispatched action of this run and the fixture starts empty. If wait actions register differently, adjust the *count source* (e.g., filter `action_history` entries by this sequence's experiment uuids) — never the exactly-once assertion itself.

- [ ] **Step 3: Type/format gate + commit**

```bash
conda run -n helao pyright helao/hexagon
conda run -n helao black helao/hexagon/tests/test_concurrency_live.py
git add helao/hexagon/tests/test_concurrency_live.py
git commit -m "test(hexagon): §10.3 item 1 lost-wakeup/double-drain on real transport (P1b2b)"
```

---

### Task 5: §10.3 item 3 — estop between decision and effect (three sub-races)

Grows the P1b1 DD-3 race seed (`test_dispatch_loop.py::test_estop_funnel_race_seed_single_finalizer`, which used `_ScriptedOrch`) into real-composition tests. Sub-races: (a) estop while blocked on the dispatch lock, (b) estop between the ladder decision and the `FinishThenDispatch` effect, (c) estop during finalization close-out. Assert every time: **single finalizer** (`estop_finish_active` exactly once, clean finish never after estop), `[finished, estopped]` terminal status in the exp yml, no duplicate `finished`.

**Files:**
- Test: `helao/hexagon/tests/test_concurrency_live.py` (append)

**Interfaces:**
- Consumes: Task 4's `_spy_finishers`; `runtime.effects` (`OrchCommandRunner` — instance-attribute rebinding of `.execute` creates the decision↔effect window); commands `FinishThenDispatchExperimentCmd` / `CloseOutExperimentCmd` (both `requires_live_estop_recheck=True`, `helao/hexagon/domain/orchestration.py:230,298`); events `ActionResultErrored(reason)` (unguarded T9 escalation — the ingestion-path estop source usable while the loop is inside finalization); POST `/estop_orch` (acts only while `loop_state == started` — `helao/core/servers/orch_api.py:364`).
- Produces: nothing downstream; gate evidence.

- [ ] **Step 1: Write the three failing tests**

Append to `helao/hexagon/tests/test_concurrency_live.py`:

```python
# =============================================================================
# Item 3: estop between decision and effect — three sub-races (DD-3)
# =============================================================================
def _assert_estopped_exp_yml(root: Path):
    """[finished, estopped] terminal status, exactly once each."""
    import yaml

    exp_ymls = list(Path(root).rglob("*-exp.yml"))
    assert exp_ymls, "estop finalizer produced no experiment yml"
    statuses = [
        yaml.safe_load(p.read_text()).get("experiment_status") for p in exp_ymls
    ]
    assert ["finished", "estopped"] in statuses, statuses
    for st in statuses:
        assert st.count("finished") == 1, st  # no duplicate finished


@pytest.mark.asyncio
async def test_item3a_estop_while_blocked_on_dispatch(tmp_path):
    """(a) estop lands while the drainer is BLOCKED inside the dispatch
    effect (standing for the dispatch lock). Trigger over REAL transport
    (/estop_orch). After release: the in-effect live re-check bails, no new
    action registers, the estop finalizer is sole."""
    async with live_group(str(tmp_path)) as g:
        orch, runtime = g.orch, g.runtime
        clean_finishes, estop_finishes = _spy_finishers(orch)
        gate, entered = asyncio.Event(), asyncio.Event()
        orig_dispatch = orch.loop_task_dispatch_action

        async def gated_dispatch(*a, **k):
            entered.set()
            await gate.wait()
            return await orig_dispatch(*a, **k)

        orch.loop_task_dispatch_action = gated_dispatch
        seq = build_ws_sequence(1, wait_time=5.0, data_duration=2.0)
        await orch_call("append_sequence", body={"sequence": seq.as_dict()})
        await orch_call("start")
        await asyncio.wait_for(entered.wait(), timeout=60)
        n_actions_before = len(orch.action_history)

        await orch_call("estop_orch")  # trigger-site cascade over real HTTP/RPC
        assert orch.globalstatusmodel.loop_state == LoopStatus.estopped
        assert len(estop_finishes) == 1  # finalizer already ran, exactly once

        gate.set()  # release the stalled effect
        await asyncio.sleep(2.0)
        # the released dispatch bailed: nothing new registered or dispatched
        assert len(orch.action_history) == n_actions_before
        assert len(clean_finishes) == 0  # clean close-out never fired
        assert len(estop_finishes) == 1  # STILL the sole finalizer
        assert orch.globalstatusmodel.loop_state == LoopStatus.estopped
        _assert_estopped_exp_yml(tmp_path)


@pytest.mark.asyncio
async def test_item3b_estop_between_decision_and_finish_then_dispatch(tmp_path):
    """(b) estop lands after the reducer decided FinishThenDispatchExperiment
    but before the runner executes it. The runner's live re-check (re-check
    #2) must bail; estop_finish_active stays the SOLE finalizer."""
    async with live_group(str(tmp_path)) as g:
        orch, runtime = g.orch, g.runtime
        clean_finishes, estop_finishes = _spy_finishers(orch)
        window, reached = asyncio.Event(), asyncio.Event()
        orig_execute = runtime.effects.execute

        async def gated_execute(cmd):
            if (
                isinstance(cmd, FinishThenDispatchExperimentCmd)
                and orch.active_experiment is not None
                and not reached.is_set()
            ):
                reached.set()
                await window.wait()  # decision made; effect not yet run
            return await orig_execute(cmd)

        runtime.effects.execute = gated_execute
        seq = build_ws_sequence(2, wait_time=1.0, data_duration=2.0)
        await orch_call("append_sequence", body={"sequence": seq.as_dict()})
        await orch_call("start")
        await asyncio.wait_for(reached.wait(), timeout=120)

        await orch_call("estop_orch")  # lands INSIDE the decision->effect window
        assert orch.globalstatusmodel.loop_state == LoopStatus.estopped
        window.set()
        await asyncio.sleep(2.0)
        assert len(estop_finishes) == 1
        assert len(clean_finishes) == 0  # re-check bailed; no clean finish ever
        assert orch.globalstatusmodel.loop_state == LoopStatus.estopped
        _assert_estopped_exp_yml(tmp_path)


@pytest.mark.asyncio
async def test_item3c_estop_during_finalization_close_out(tmp_path):
    """(c) estop escalation (ActionResultErrored — the unguarded ingestion
    source) lands while the drainer is inside finalization's CloseOut
    effect window. Live re-check #3: the close-out re-checks LIVE loop_state
    and bails; single finalizer."""
    async with live_group(str(tmp_path)) as g:
        orch, runtime = g.orch, g.runtime
        clean_finishes, estop_finishes = _spy_finishers(orch)
        window, reached = asyncio.Event(), asyncio.Event()
        orig_execute = runtime.effects.execute

        async def gated_execute(cmd):
            if isinstance(cmd, CloseOutExperimentCmd) and not reached.is_set():
                reached.set()
                await window.wait()  # finalization decided; close-out pending
            return await orig_execute(cmd)

        runtime.effects.execute = gated_execute
        seq = build_ws_sequence(1, wait_time=1.0, data_duration=2.0)
        await orch_call("append_sequence", body={"sequence": seq.as_dict()})
        await orch_call("start")
        await asyncio.wait_for(reached.wait(), timeout=120)

        # concurrent estop through the reducer at its trigger site (DD-3):
        await runtime.handle(ActionResultErrored(reason="conc item3c"))
        assert orch.globalstatusmodel.loop_state == LoopStatus.estopped
        assert len(estop_finishes) == 1
        window.set()  # release the pending clean close-out
        await asyncio.sleep(2.0)
        assert len(clean_finishes) == 0  # close-out re-checked live and bailed
        assert len(estop_finishes) == 1  # sole finalizer, still
        _assert_estopped_exp_yml(tmp_path)
```

- [ ] **Step 2: Run the three tests**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_concurrency_live.py -v -x -k item3`
Expected: PASS. Any failure = real race finding → systematic-debugging → fix in `helao/hexagon/` only (candidate hotspots per master spec §12 P1 risks: the three live re-checks in `OrchCommandRunner`, the estop funnel in `graft_hexagon_loop`'s `hex_estop_loop`).

NOTE (assumptions to verify on first run): (i) estopped exp ymls are `yaml.safe_load`-able and carry `experiment_status: [finished, estopped]` — if the yml uses tagged dumps, switch the loader to `helao.helpers.yml_tools.yml_load` with the same asserts; (ii) in (c), `ActionResultErrored` is deliberately used because both `/estop_orch` and `EstoppedUuidIngested` are guarded on `loop_state == started`, and during finalization the delta may already have written `stopped` — the unguarded T9 escalation is the faithful ingestion-path stand-in.

- [ ] **Step 3: Type/format gate + commit**

```bash
conda run -n helao pyright helao/hexagon
conda run -n helao black helao/hexagon/tests/test_concurrency_live.py
git add helao/hexagon/tests/test_concurrency_live.py
git commit -m "test(hexagon): §10.3 item 3 estop decision/effect sub-races on real composition (P1b2b)"
```

---

### Task 6: §10.3 item 5 — nonblocking lifecycle end-to-end

Two layers: (i) the hexagon **status adapter's** round-trip over real endpoints — `send_nonblocking_status` → real `/update_nonblocking` → `orch.nonblocking` bookkeeping carries the **composed** host/port (Task 1's carry) → `clear_nonblocking` reaches the real SIM `/stop_executor`; (ii) the **full** nonblocking `/wait` lifecycle (`send_nbstatuspackage` → `update_nonblocking` → clear) via a real `TEST_consecutive_noblocking` run — the flag must survive the endpoint (ac42e9bf/e7534fd3).

**Files:**
- Test: `helao/hexagon/tests/test_concurrency_live.py` (append)

**Interfaces:**
- Consumes: `g.sim_app.hexagon_wiring.status` (`DispatcherStatusAdapter` with `own_host="127.0.0.1"`, `own_port=8102` after Task 1); `orch.nonblocking` (list of `(server_key, exec_id, server_host, server_port)` tuples — `helao/core/servers/orch_status_sync.py:145`); `orch.clear_nonblocking()` (sends `stop_executor` to each tuple's host/port and returns `[(response, error_code), …]`); sequence builder `TEST_consecutive_noblocking(**{"wait_time","cycles","plate_sample_no_list"})` (`helao/deploy/test/sequences/TEST_seq.py`, imported exactly as `harness/capture.py::build_gm2_sequence` does).
- Produces: nothing downstream; gate evidence.

- [ ] **Step 1: Write the failing tests**

Append to `helao/hexagon/tests/test_concurrency_live.py`:

```python
# =============================================================================
# Item 5: nonblocking lifecycle (send_nbstatuspackage -> update_nonblocking
#         -> clear); the flag must survive the endpoint (ac42e9bf/e7534fd3)
# =============================================================================
@pytest.mark.asyncio
async def test_item5_adapter_nonblocking_roundtrip_real_endpoints(tmp_path):
    """Hexagon status adapter -> REAL /update_nonblocking on the live orch:
    the bookkeeping tuple must carry the adapter's composed own host/port
    (the Task 1 carry — never ''/0), and clear_nonblocking must reach the
    real SIM /stop_executor over the dispatcher."""
    from helao.helpers.time_utils import gen_uuid
    from helao.hexagon.tests.live_group import ORCH_HOST, ORCH_PORT

    async with live_group(str(tmp_path)) as g:
        status = g.sim_app.hexagon_wiring.status
        exec_id = "SIM p1b2b-item5"
        act_uuid = gen_uuid()
        await status.send_nonblocking_status(
            "ORCH", ORCH_HOST, ORCH_PORT, "SIM", exec_id, act_uuid, "active"
        )
        expected = ("SIM", exec_id, SIM_HOST, SIM_PORT)
        assert expected in g.orch.nonblocking, g.orch.nonblocking
        # the carry: identity is the REAL composed one, never the defaults
        assert ("SIM", exec_id, "", 0) not in g.orch.nonblocking

        # clear leg: real /stop_executor POST to the SIM's live host/port
        resp_tups = await g.orch.clear_nonblocking()
        assert resp_tups, "clear_nonblocking sent nothing"
        for resp, _err in resp_tups:
            assert resp is not None, "stop_executor never reached the SIM"

        # finished status removes the tuple
        await status.send_nonblocking_status(
            "ORCH", ORCH_HOST, ORCH_PORT, "SIM", exec_id, act_uuid, "finished"
        )
        assert expected not in g.orch.nonblocking


@pytest.mark.asyncio
async def test_item5_nonblocking_wait_full_lifecycle(tmp_path):
    """Full run: TEST_consecutive_noblocking's nonblocking /wait — the
    nonblocking flag survives the endpoint (orch.nonblocking becomes
    non-empty mid-run), every wait finishes, and the registry drains to
    empty at park."""
    from helao.deploy.test.sequences.TEST_seq import TEST_consecutive_noblocking
    from helao.helpers.premodels import Sequence
    from helao.helpers.time_utils import gen_uuid

    params = {"wait_time": 1.0, "cycles": 1, "plate_sample_no_list": [1]}
    async with live_group(str(tmp_path)) as g:
        seq = Sequence(
            sequence_name="TEST_consecutive_noblocking",
            sequence_label="p1b2b-item5",
            sequence_params=params,
            planned_experiments=TEST_consecutive_noblocking(**params),
            sequence_uuid=gen_uuid(),
            dummy=True,
            simulation=True,
        )
        await orch_call("append_sequence", body={"sequence": seq.as_dict()})
        await orch_call("start")

        saw_nonblocking = False
        for _ in range(720):  # 3 min budget; nb wait is wait_time*10 = 10 s
            if g.orch.nonblocking:
                saw_nonblocking = True
            gsm = g.orch.globalstatusmodel
            if (
                saw_nonblocking
                and gsm.loop_state == LoopStatus.stopped
                and not gsm.active_dict
                and not g.orch.action_dq
                and not g.orch.experiment_dq
                and not g.orch.sequence_dq
            ):
                break
            await asyncio.sleep(0.25)

        assert saw_nonblocking, "nonblocking flag never survived the endpoint"
        assert g.orch.nonblocking == [], "registry did not drain"
        # every wait action reached finished (the MINOR-8 stall would show here)
        waits = [
            meta
            for meta in g.orch.action_history.values()
            if meta.get("action_name") == "wait"
        ]
        assert waits, "no wait actions registered"
        assert all(m.get("action_finished_timestamp") for m in waits), waits
```

- [ ] **Step 2: Run the tests**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_concurrency_live.py -v -x -k item5`
Expected: PASS. **Known likely first failure (fix is adapter-local, sanctioned):** legacy `update_nonblocking` formats `actionmodel.action_timestamp` with an f-string (`orch_status_sync.py` — `f"{actionmodel.action_timestamp: %m-%d %H:%M:%S}"`), which raises on `None`. If the adapter's minimal body 500s for that reason, extend `DispatcherStatusAdapter.send_nonblocking_status`'s `json_dict["actionmodel"]` with a real `action_timestamp` (mint via the wiring clock or `datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")` matching the `Action` model's expected format) — a hexagon-only change; document it in the adapter docstring.

- [ ] **Step 3: Type/format gate + commit**

```bash
conda run -n helao pyright helao/hexagon
conda run -n helao black helao/hexagon/tests/test_concurrency_live.py helao/hexagon/adapters/legacy/status.py
git add helao/hexagon/tests/test_concurrency_live.py helao/hexagon/adapters/legacy/status.py
git commit -m "test(hexagon): §10.3 item 5 nonblocking lifecycle over real endpoints (P1b2b)"
```

---

# Task Group B — P1b2b-2 (launched-group; **MAIN SESSION ONLY**)

> Launched groups (`launch.py`) must be driven from the main session: background subagent launches get reaped on idle (P1b2a execution constraint). Each item = launch → drive → assert → kill, one config per launch, fresh root every time.

### Task 7: Launched-group scaffolding — `conc_run.sh`, `conc_items.py` core, `goldenhexconc.yml`

**Files:**
- Create: `helao/deploy/test/configs/goldenhexconc.yml`
- Create: `helao/hexagon/tests/smoke/conc_items.py` (shared core + item drivers land in Tasks 8–11)
- Create: `helao/hexagon/tests/smoke/conc_run.sh`

**Interfaces:**
- Consumes: `launch.py <prefix> --no-hot-reload`; `helao/hexagon/tests/smoke/kill_group.py <root> <prefix>` (pid pickle `STATES/pids_<prefix>_.pck`, entries `pidd[key]["pid"]`); orch private endpoints `/append_sequence` (Body `{"sequence": seq.as_dict()}` embed), `/start`, `/get_orch_state` (returns `loop_state`, `current_stop_message`, queue counts), `/get_histories` (returns `{"action": [(uuid, meta), …], "experiment": …, "sequence": …}` — `helao/core/servers/orch_api.py:38-44,581`), `/list_nonblocking`, `/global_status`; `private_dispatcher(server_key, host, port, endpoint, params_dict, json_dict)` (sync, as `harness/capture.py::orch_post` uses).
- Produces:
  - `conc_run.sh <item> <config_prefix> <root> [orch_key]` — launch/wait/drive/kill wrapper; exits with the driver's exit code (0 PASS / 1 assert fail / 2 driver-or-launch error).
  - `conc_items.py` shared core: `orch_post(orch_key, endpoint, params=None, body=None)`, `get_orch_state(orch_key) -> dict`, `get_histories(orch_key) -> dict`, `wait_until(pred, timeout_s, poll_s=2.0, label="")`, `orch_parked(orch_key) -> bool`, `build_ws_sequence(n_exps, wait_time, data_duration) -> Sequence`, `kill_server(root: Path, prefix: str, key: str) -> None`, and the `ITEMS` registry dispatched by `main()`.

- [ ] **Step 1: Write the config**

`helao/deploy/test/configs/goldenhexconc.yml` (copy of `goldenhex.yml` with a fast heartbeat for item 6 and its own root):

```yaml
# P1b2b CONCURRENCY config (§10.3 launched-group items 4/6/7).
# Copy of goldenhex.yml with a fast orch heartbeat (item 6 needs the
# active_action_monitor to notice a killed SIM quickly) and its own root.
dummy: true
simulation: true
show_debug: true
run_unit_tests: true
experiment_libraries:
  - simulatews_exp
  - helao/deploy/test/experiments/TEST_exp.py
sequence_libraries:
  - helao/deploy/test/sequences/TEST_seq.py
run_type: simulation
root: /home/dan/INST_hlo_hexconc
servers:
  ORCH:
    host: 127.0.0.1
    port: 8001
    group: orchestrator
    fast: async_orch2
    deployment: hexagon
    params:
      heartbeat_interval: 3
    exp_postprocess_libs:
      - append_params
    seq_postprocess_libs:
      - append_params
  SIM:
    host: 127.0.0.1
    port: 8002
    group: action
    fast: ws_simulator
    deployment: hexagon
    live_vis: wssim_live_vis
    params: {}
    hlo_postprocess_libs:
      - hlo_to_csv
  DB:
    host: 127.0.0.1
    port: 8010
    group: action
    fast: sim_db_server
    params:
      aws_bucket: helao-sim
      s3_record: true
```

- [ ] **Step 2: Write the driver core**

`helao/hexagon/tests/smoke/conc_items.py`:

```python
"""§10.3 launched-group concurrency drivers (items 2/4/6/7, P1b2b).

Runs against a LIVE launched group (launch.py <prefix>) — MAIN SESSION only
(background subagent launches get reaped on idle). Invoked by conc_run.sh.
Exit code: 0 PASS, 1 assertion failure, 2 driver error.

Item drivers are registered in ITEMS and appended by Tasks 8-11:
  item2 (non-default identity), item4 (serial >=3 experiments),
  item6 (history-poll hang exit), item7 (idle drain + non-blank history)."""

import argparse
import pickle
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Optional

import psutil

from helao.core.error import ErrorCodes
from helao.helpers.dispatcher import private_dispatcher
from helao.helpers.premodels import ExperimentPlanMaker, Sequence
from helao.helpers.time_utils import gen_uuid

ORCH_HOST, ORCH_PORT = "127.0.0.1", 8001
HIST_TS_FMT = "%m-%d %H:%M:%S"  # orch action_history timestamp format


def orch_post(
    orch_key: str,
    endpoint: str,
    params: Optional[dict] = None,
    body: Optional[dict] = None,
):
    resp, err = private_dispatcher(
        orch_key,
        ORCH_HOST,
        ORCH_PORT,
        endpoint,
        params_dict=params or {},
        json_dict=body or {},
    )
    if err != ErrorCodes.none:
        raise RuntimeError(f"{orch_key} /{endpoint} failed: {err}")
    return resp


def get_orch_state(orch_key: str) -> dict:
    return orch_post(orch_key, "get_orch_state")


def get_histories(orch_key: str) -> dict:
    return orch_post(orch_key, "get_histories")


def orch_parked(orch_key: str) -> bool:
    st = get_orch_state(orch_key)
    loop = str(st.get("loop_state"))
    return loop.endswith("stopped") and not st.get("active_experiment")


def wait_until(
    pred: Callable[[], bool], timeout_s: float, poll_s: float = 2.0, label: str = ""
):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if pred():
            return
        time.sleep(poll_s)
    raise TimeoutError(f"{label or pred.__name__} not met after {timeout_s}s")


def build_ws_sequence(
    n_exps: int, wait_time: float = 2.0, data_duration: float = 4.0
) -> Sequence:
    epm = ExperimentPlanMaker()
    for _ in range(n_exps):
        epm.add(
            "SIM_websocket_data",
            {"wait_time": wait_time, "data_duration": data_duration},
        )
    return Sequence(
        sequence_name="SIM_websocket_data_seq",
        sequence_label="p1b2b-conc",
        sequence_params={"wait_time": wait_time, "data_duration": data_duration},
        planned_experiments=epm.planned_experiments,
        sequence_uuid=gen_uuid(),
        dummy=True,
        simulation=True,
    )


def submit_and_start(orch_key: str, seq: Sequence) -> None:
    orch_post(orch_key, "append_sequence", body={"sequence": seq.as_dict()})
    orch_post(orch_key, "start")


def kill_server(root: Path, prefix: str, key: str) -> None:
    """SIGKILL one server of the launched group (models a hard death)."""
    pck = root / "STATES" / f"pids_{prefix}_.pck"
    pidd = pickle.load(open(pck, "rb"))
    pid = pidd[key]["pid"]
    print(f"[conc] SIGKILL {key} (pid {pid})")
    psutil.Process(pid).kill()


def parse_hist_ts(s: str) -> datetime:
    return datetime.strptime(s.strip(), HIST_TS_FMT)


ITEMS: Dict[str, Callable[[Path, str], int]] = {}
# Tasks 8-11 register: ITEMS["item2"], ITEMS["item4"], ITEMS["item6"], ITEMS["item7"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--item", required=True, choices=sorted(ITEMS) or ["none"])
    ap.add_argument("--root", required=True)
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--orch-key", default="ORCH")
    args = ap.parse_args()
    try:
        rc = ITEMS[args.item](Path(args.root), args.orch_key, args.prefix)
    except AssertionError as e:
        print(f"[conc] {args.item} ASSERT FAIL: {e}")
        return 1
    except Exception as e:  # noqa: BLE001 — driver boundary
        print(f"[conc] {args.item} driver error: {e!r}")
        return 2
    print(f"[conc] {args.item} -> rc {rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
```

NOTE for implementers: `ITEMS` values take `(root, orch_key, prefix)` — Tasks 8–11 register functions with that exact 3-arg signature.

- [ ] **Step 3: Write the launch wrapper**

`helao/hexagon/tests/smoke/conc_run.sh` (same skeleton as the proven `parity_run.sh`):

```bash
#!/usr/bin/env bash
# Launch a HELAO group, run one §10.3 concurrency item driver, kill the
# group. Exit code = driver exit (0 PASS, 1 assert fail, 2 error).
# MAIN SESSION ONLY (subagent background launches get reaped on idle).
#
# Usage: conc_run.sh <item> <config_prefix> <root> [orch_key]
set -u
ITEM="$1"; PREFIX="$2"; ROOT="$3"; ORCH_KEY="${4:-ORCH}"
REPO="$(cd "$(dirname "$0")/../../../.." && pwd)"
cd "$REPO" || exit 2
LAUNCHLOG="/tmp/p1b2b_${PREFIX}_${ITEM}.launch.log"

echo "[conc_run] wiping fresh root $ROOT"
rm -rf "$ROOT"

echo "[conc_run] launching $PREFIX (log: $LAUNCHLOG)"
nohup conda run -n helao python launch.py "$PREFIX" --no-hot-reload > "$LAUNCHLOG" 2>&1 &
LAUNCH_PID=$!

echo "[conc_run] waiting for ports 8001/8002/8010"
UP=0
for i in $(seq 1 90); do
  if conda run -n helao python - <<'PY' 2>/dev/null
import socket, sys
ok = all(socket.socket().connect_ex(("127.0.0.1", p)) == 0 for p in (8001, 8002, 8010))
sys.exit(0 if ok else 1)
PY
  then UP=1; break; fi
  sleep 2
done
if [ "$UP" -ne 1 ]; then
  echo "[conc_run] FAIL ports never came up; launch tail:"; tail -40 "$LAUNCHLOG"
  conda run -n helao python helao/hexagon/tests/smoke/kill_group.py "$ROOT" "$PREFIX"
  kill "$LAUNCH_PID" 2>/dev/null; exit 2
fi
sleep 5  # settle: orch loop parked, action servers registered

echo "[conc_run] driving $ITEM"
conda run -n helao python -m helao.hexagon.tests.smoke.conc_items \
  --item "$ITEM" --root "$ROOT" --prefix "$PREFIX" --orch-key "$ORCH_KEY"
RC=$?

echo "[conc_run] killing group"
conda run -n helao python helao/hexagon/tests/smoke/kill_group.py "$ROOT" "$PREFIX"
kill "$LAUNCH_PID" 2>/dev/null
if [ "$RC" -ne 0 ]; then
  echo "[conc_run] FAIL rc=$RC; launch tail:"; tail -60 "$LAUNCHLOG"
fi
exit $RC
```

Then: `chmod +x helao/hexagon/tests/smoke/conc_run.sh`

- [ ] **Step 4: Sanity-run the scaffold (expect a clean "no items" refusal)**

Run: `conda run -n helao python -m helao.hexagon.tests.smoke.conc_items --item none --root /tmp/x --prefix goldenhexconc 2>&1 | head -3`
Expected: argparse rejects `none` only once real items exist — at this point `ITEMS` is empty so `choices` is `["none"]` and the run exits 2 with a KeyError-driven driver error. Either outcome proves the module imports cleanly under the helao env.

- [ ] **Step 5: Type/format gate + commit**

```bash
conda run -n helao pyright helao/hexagon
conda run -n helao black helao/hexagon/tests/smoke/conc_items.py
git add helao/deploy/test/configs/goldenhexconc.yml helao/hexagon/tests/smoke/conc_items.py helao/hexagon/tests/smoke/conc_run.sh
git commit -m "test(hexagon): launched-group concurrency scaffolding for §10.3 items 2/4/6/7 (P1b2b)"
```

---

### Task 8: §10.3 item 2 — non-default orch `MachineModel` identity, full run

The test-deployment experiment libraries hardcode `ORCH_server = MachineModel(server_name="ORCH", machine_name=gethostname().lower()).as_dict()` (`helao/deploy/test/experiments/simulatews_exp.py:23`), so a renamed orch key needs its own experiment library. The library lives in the **hexagon tree** and is referenced by path from the config (config `experiment_libraries` accepts repo-relative paths — the `helao/deploy/test/experiments/TEST_exp.py` entry in `goldenhex.yml` is the precedent). Under MINOR-8 (status-fold identity rule: finished actions are removed only when `statusmodel.orchestrator == gsm.orchestrator`), a wrongly-stamped self-hosted `/wait` **permanently stalls the run** — so run completion + finished waits IS the assertion.

**Files:**
- Create: `helao/hexagon/tests/smoke/hexid_exp.py` (experiment library targeting `HEXORC`)
- Create: `helao/deploy/test/configs/goldenhexid.yml`
- Modify: `helao/hexagon/tests/smoke/conc_items.py` (register `item2`)

**Interfaces:**
- Consumes: Task 7 core (`orch_post`, `submit_and_start`, `wait_until`, `orch_parked`, `get_histories`); `ActionPlanMaker`/`@experiment` decorator (`helao.helpers.premodels`, `helao.helpers.lib_decorators`) exactly as `simulatews_exp` uses them.
- Produces: `ITEMS["item2"]`.

- [ ] **Step 1: Write the identity experiment library**

`helao/hexagon/tests/smoke/hexid_exp.py` (faithful copy of `simulatews_exp.SIM_websocket_data` with the orchestrator identity renamed — the ONLY delta is `server_name="HEXORC"` and the function name):

```python
"""Non-default-identity experiment library for §10.3 item 2 (P1b2b).

Verbatim copy of helao/deploy/test/experiments/simulatews_exp.py's
SIM_websocket_data with the orchestrator MachineModel renamed to HEXORC:
test libraries hardcode server_name="ORCH", so exercising a non-default
orch identity (MINOR-8) requires a library that targets the renamed key.
Referenced by path from goldenhexid.yml; zero legacy edits."""

__all__ = ["SIM_websocket_data_hexid"]

from socket import gethostname

from helao.core.models.machine import MachineModel
from helao.core.models.process_contrib import ProcessContrib

from helao.helpers.premodels import ActionPlanMaker
from helao.helpers.lib_decorators import experiment


# list valid experiment functions
EXPERIMENTS = __all__

ORCH_HOST = gethostname().lower()
HEXORC_server = MachineModel(server_name="HEXORC", machine_name=ORCH_HOST).as_dict()
SIM_server = MachineModel(server_name="SIM", machine_name=ORCH_HOST).as_dict()


@experiment(version=1)
def SIM_websocket_data_hexid(
    wait_time: float = 3.0,
    data_duration: float = 5.0,
) -> list:
    """Two wait-then-acquire pairs against the websocket simulator, with the
    orchestrator's self-hosted waits addressed to the RENAMED orch identity."""
    apm = ActionPlanMaker()

    apm.add(
        HEXORC_server,
        "wait",
        {"waittime": wait_time},
        process_contrib=[ProcessContrib.action_params],
    )
    apm.add(
        SIM_server,
        "acquire_data",
        {"duration": data_duration},
        process_contrib=[ProcessContrib.files, ProcessContrib.run_use],
        process_finish=True,
    )
    apm.add(
        HEXORC_server,
        "wait",
        {"waittime": wait_time},
        process_contrib=[ProcessContrib.action_params],
    )
    apm.add(
        SIM_server,
        "acquire_data",
        {"duration": data_duration},
        process_contrib=[ProcessContrib.files, ProcessContrib.run_use],
        process_finish=True,
    )

    return apm.planned_actions
```

- [ ] **Step 2: Write the identity config**

`helao/deploy/test/configs/goldenhexid.yml`:

```yaml
# P1b2b IDENTITY config (§10.3 item 2, MINOR-8): goldenhex with the orch
# renamed HEXORC (non-default MachineModel identity) and an experiment
# library that targets the renamed key. Ports unchanged (8001/8002/8010).
dummy: true
simulation: true
show_debug: true
run_unit_tests: true
experiment_libraries:
  - helao/hexagon/tests/smoke/hexid_exp.py
sequence_libraries: []
run_type: simulation
root: /home/dan/INST_hlo_hexid
servers:
  HEXORC:
    host: 127.0.0.1
    port: 8001
    group: orchestrator
    fast: async_orch2
    deployment: hexagon
    params: {}
    exp_postprocess_libs:
      - append_params
    seq_postprocess_libs:
      - append_params
  SIM:
    host: 127.0.0.1
    port: 8002
    group: action
    fast: ws_simulator
    deployment: hexagon
    live_vis: wssim_live_vis
    params: {}
    hlo_postprocess_libs:
      - hlo_to_csv
  DB:
    host: 127.0.0.1
    port: 8010
    group: action
    fast: sim_db_server
    params:
      aws_bucket: helao-sim
      s3_record: true
```

- [ ] **Step 3: Register the item driver**

Append to `helao/hexagon/tests/smoke/conc_items.py` (above the `main()` definition):

```python
def item2_nondefault_identity(root: Path, orch_key: str, prefix: str) -> int:
    """§10.3 item 2: full run under a non-default orch MachineModel
    (HEXORC). MINOR-8 regression mode = permanent stall (status folds from
    self-hosted /wait actions carry the wrong orchestrator identity and are
    never cleared), so completion within the timeout IS the core assert."""
    epm = ExperimentPlanMaker()
    for _ in range(2):
        epm.add(
            "SIM_websocket_data_hexid", {"wait_time": 2.0, "data_duration": 4.0}
        )
    seq = Sequence(
        sequence_name="SIM_websocket_data_hexid_seq",
        sequence_label="p1b2b-item2",
        sequence_params={"wait_time": 2.0, "data_duration": 4.0},
        planned_experiments=epm.planned_experiments,
        sequence_uuid=gen_uuid(),
        dummy=True,
        simulation=True,
    )
    submit_and_start(orch_key, seq)
    wait_until(lambda: orch_parked(orch_key), 600, label="item2 full-run drain")
    hist = get_histories(orch_key)
    acts = [meta for _u, meta in hist["action"]]
    waits = [m for m in acts if m.get("action_name") == "wait"]
    assert len(waits) == 4, f"expected 4 self-hosted waits, got {len(waits)}"
    # self-hosted /wait finish under the renamed identity (MINOR-8)
    assert all(m.get("action_finished_timestamp") for m in waits), waits
    # status folds cleared: nothing lingers active
    st = get_orch_state(orch_key)
    assert str(st.get("loop_state")).endswith("stopped"), st.get("loop_state")
    exps = [meta for _u, meta in hist["experiment"]]
    assert len(exps) == 2, f"expected 2 experiments in history, got {len(exps)}"
    return 0


ITEMS["item2"] = item2_nondefault_identity
```

- [ ] **Step 4: Run it (MAIN SESSION)**

Run: `bash helao/hexagon/tests/smoke/conc_run.sh item2 goldenhexid /home/dan/INST_hlo_hexid HEXORC`
Expected: exit 0. **Likely first failures and their meanings:**
  - Launch aborts on library path: the loader may not accept a `helao/hexagon/...` path in `experiment_libraries`. Fallback (still zero-edit): move `hexid_exp.py` to `helao/deploy/test/experiments/hexid_exp.py` (a NEW file, following the goldenhex.yml new-file precedent) and reference it as `hexid_exp`; update the config.
  - Permanent stall (timeout at 600 s with waits unfinished) = a **real MINOR-8-class finding** in the hexagon path: the orch's self-hosted wait actions are not stamping the HEXORC identity through the graft. Fix in `helao/hexagon/` only.

- [ ] **Step 5: Type/format gate + commit**

```bash
conda run -n helao pyright helao/hexagon
conda run -n helao black helao/hexagon/tests/smoke/conc_items.py helao/hexagon/tests/smoke/hexid_exp.py
git add helao/hexagon/tests/smoke/conc_items.py helao/hexagon/tests/smoke/hexid_exp.py helao/deploy/test/configs/goldenhexid.yml
git commit -m "test(hexagon): §10.3 item 2 non-default orch identity full run (P1b2b)"
```

---

### Task 9: §10.3 item 4 — serial ≥3-experiment sequence

Every experiment must finish (FinishExperiment meta + `clear_nonblocking`) **before** the next dispatches (the 5c43a803 regression class). Evidence source: the orch's `action_history` metas carry `action_timestamp` and `action_finished_timestamp` (format `"%m-%d %H:%M:%S"`, written by the shared uuid-registration side effect — `helao/core/servers/orch_status_sync.py:106-121`) plus `experiment_uuid`, so per-experiment start/finish ordering is directly assertable; `/list_nonblocking` must be empty at park.

**Files:**
- Modify: `helao/hexagon/tests/smoke/conc_items.py` (register `item4`)

**Interfaces:**
- Consumes: Task 7 core; `parse_hist_ts`.
- Produces: `ITEMS["item4"]`.

- [ ] **Step 1: Register the item driver**

Append to `helao/hexagon/tests/smoke/conc_items.py`:

```python
def item4_serial_multi_experiment(root: Path, orch_key: str, prefix: str) -> int:
    """§10.3 item 4: 3-experiment sequence; every experiment's actions all
    FINISH before the next experiment's first action STARTS (5c43a803),
    and the nonblocking registry is clear at park."""
    seq = build_ws_sequence(3, wait_time=2.0, data_duration=4.0)
    submit_and_start(orch_key, seq)
    wait_until(lambda: orch_parked(orch_key), 900, label="item4 3-exp drain")

    hist = get_histories(orch_key)
    acts = [meta for _u, meta in hist["action"]]
    groups: dict = {}
    for meta in acts:  # dict preserves first-seen (dispatch) order
        groups.setdefault(str(meta.get("experiment_uuid")), []).append(meta)
    exp_groups = list(groups.values())
    assert len(exp_groups) == 3, f"expected 3 experiment groups, got {len(exp_groups)}"
    for metas in exp_groups:
        assert all(
            m.get("action_finished_timestamp") for m in metas
        ), f"unfinished action in {metas}"
    for prev, nxt in zip(exp_groups, exp_groups[1:]):
        prev_finish = max(parse_hist_ts(m["action_finished_timestamp"]) for m in prev)
        next_start = min(parse_hist_ts(m["action_timestamp"]) for m in nxt)
        assert next_start >= prev_finish, (
            f"experiment overlap: next started {next_start} "
            f"before previous finished {prev_finish}"
        )
    nb = orch_post(orch_key, "list_nonblocking")
    assert nb == [], f"nonblocking registry not cleared: {nb}"
    exps = [meta for _u, meta in hist["experiment"]]
    assert len(exps) == 3, f"expected 3 experiments in history, got {len(exps)}"
    return 0


ITEMS["item4"] = item4_serial_multi_experiment
```

- [ ] **Step 2: Run it (MAIN SESSION)**

Run: `bash helao/hexagon/tests/smoke/conc_run.sh item4 goldenhexconc /home/dan/INST_hlo_hexconc`
Expected: exit 0 in ≤ ~10 min. An overlap assert = real serialization race in the hexagon ladder (FinishThenDispatchExperimentCmd ordering) — fix in `helao/hexagon/` only. NOTE: the `%m-%d %H:%M:%S` history format is second-granular; `>=` (not `>`) is deliberate.

- [ ] **Step 3: Type/format gate + commit**

```bash
conda run -n helao pyright helao/hexagon
conda run -n helao black helao/hexagon/tests/smoke/conc_items.py
git add helao/hexagon/tests/smoke/conc_items.py
git commit -m "test(hexagon): §10.3 item 4 serial 3-experiment ordering on launched group (P1b2b)"
```

---

### Task 10: §10.3 item 6 — history-poll hang exit (heartbeat monitor is the only stop)

Kill the SIM after the dispatch reply lands but before the action finishes; the orch is then parked waiting for status that never comes. The heartbeat loop (`OrchMonitor.active_action_monitor`, `helao/core/servers/orch_monitor.py:105`) must be the exit: it writes `current_stop_message = "<endpoints> endpoints are unavailable"` and calls `orch.stop()`. `goldenhexconc.yml` sets `heartbeat_interval: 3` so the exit is prompt.

**Files:**
- Modify: `helao/hexagon/tests/smoke/conc_items.py` (register `item6`)

**Interfaces:**
- Consumes: Task 7 core; `kill_server(root, prefix, "SIM")`; `/get_orch_state` (`current_stop_message` field); `/global_status` (`active_dict` — non-empty once the SIM action is dispatched and active).
- Produces: `ITEMS["item6"]`.

- [ ] **Step 1: Register the item driver**

Append to `helao/hexagon/tests/smoke/conc_items.py` (add `import requests` at the module top with the other imports):

```python
def _active_dict_nonempty() -> bool:
    gs = requests.post(
        f"http://{ORCH_HOST}:{ORCH_PORT}/global_status", timeout=10
    ).json()
    return bool(gs.get("active_dict"))


def item6_history_poll_hang_exit(root: Path, orch_key: str, prefix: str) -> int:
    """§10.3 item 6: SIGKILL the SIM while its action is active (dispatch
    reply received, finish status will never come). The heartbeat monitor
    must be the ONLY exit: loop parks stopped with the offline-endpoint
    stop message."""
    # one experiment whose SIM acquire runs long enough to die mid-action
    seq = build_ws_sequence(1, wait_time=1.0, data_duration=60.0)
    submit_and_start(orch_key, seq)
    wait_until(_active_dict_nonempty, 120, poll_s=1.0, label="item6 action active")
    kill_server(root, prefix, "SIM")

    def _stopped_by_heartbeat() -> bool:
        st = get_orch_state(orch_key)
        return str(st.get("loop_state")).endswith("stopped")

    # heartbeat_interval=3 in goldenhexconc.yml; allow several probe cycles
    wait_until(_stopped_by_heartbeat, 120, poll_s=2.0, label="item6 heartbeat stop")
    st = get_orch_state(orch_key)
    msg = str(st.get("current_stop_message"))
    assert "endpoints are unavailable" in msg, (
        f"stop did not come from the heartbeat monitor: {msg!r}"
    )
    return 0


ITEMS["item6"] = item6_history_poll_hang_exit
```

- [ ] **Step 2: Run it (MAIN SESSION)**

Run: `bash helao/hexagon/tests/smoke/conc_run.sh item6 goldenhexconc /home/dan/INST_hlo_hexconc`
Expected: exit 0 in ≤ ~3 min. A timeout at "item6 heartbeat stop" means the hexagon graft's rebound `orch.stop` (the `hex_stop` wrapper in `graft_hexagon_loop`) failed to drain the loop when invoked from the monitor task — a real finding; fix in `helao/hexagon/` only. Note `conc_run.sh`'s kill step tolerates the already-dead SIM (`kill_group.py` skips missing pids).

- [ ] **Step 3: Type/format gate + commit**

```bash
conda run -n helao pyright helao/hexagon
conda run -n helao black helao/hexagon/tests/smoke/conc_items.py
git add helao/hexagon/tests/smoke/conc_items.py
git commit -m "test(hexagon): §10.3 item 6 heartbeat-only exit after SIM kill (P1b2b)"
```

---

### Task 11: §10.3 item 7 — idle drain + non-blank history (+ §9.1 launched log-path asserts)

Natural queue drain must flip `loop_state` via the complete-idle path (7533dbc5) with **no** `/stop` POST, and history entries must be non-blank (2e828981, ac42e9bf, 6b8931ce). Piggybacks the launched-path §9.1 asserts (per-process `<root>/LOGS/<server_key>.log` flat files exist; no per-server subdirs beyond legacy archives; no `LOGS_FW`).

**Files:**
- Modify: `helao/hexagon/tests/smoke/conc_items.py` (register `item7`)

**Interfaces:**
- Consumes: Task 7 core.
- Produces: `ITEMS["item7"]`.

- [ ] **Step 1: Register the item driver**

Append to `helao/hexagon/tests/smoke/conc_items.py`:

```python
def item7_idle_drain_and_history(root: Path, orch_key: str, prefix: str) -> int:
    """§10.3 item 7: natural drain (NO /stop) parks the loop via the
    complete-idle path; history entries are non-blank. Plus the launched-
    path §9.1 asserts: flat per-server log files under <root>/LOGS."""
    seq = build_ws_sequence(1, wait_time=2.0, data_duration=4.0)
    submit_and_start(orch_key, seq)
    # deliberately NO orch_post(..., "stop"): the drain itself must park
    wait_until(lambda: orch_parked(orch_key), 600, label="item7 natural drain")
    st = get_orch_state(orch_key)
    assert str(st.get("loop_state")).endswith("stopped"), st.get("loop_state")
    assert str(st.get("orch_state")).endswith("idle"), st.get("orch_state")

    hist = get_histories(orch_key)
    acts = [meta for _u, meta in hist["action"]]
    assert acts, "action history is empty after a completed run"
    for meta in acts:  # non-blank entries (2e828981/ac42e9bf/6b8931ce)
        assert meta.get("action_name"), meta
        assert meta.get("action_timestamp"), meta
        assert meta.get("action_finished_timestamp"), meta
        assert meta.get("experiment_uuid"), meta

    # §9.1 on the launched hexagon path: flat log files at the contract path
    logs = root / "LOGS"
    for key in (orch_key, "SIM", "DB"):
        assert (logs / f"{key}.log").exists(), f"missing {key}.log under LOGS"
    assert (logs / "ntpLastSync.txt").exists()
    assert not (root / "LOGS_FW").exists(), "parallel log dir must never exist"
    return 0


ITEMS["item7"] = item7_idle_drain_and_history
```

- [ ] **Step 2: Run it (MAIN SESSION)**

Run: `bash helao/hexagon/tests/smoke/conc_run.sh item7 goldenhexconc /home/dan/INST_hlo_hexconc`
Expected: exit 0 in ≤ ~5 min. A hang at "item7 natural drain" = the complete-idle path regression (7533dbc5 class) in the hexagon loop; blank history metas = the ingestion-registration gap (2e828981 class). Both are hexagon-only fixes.

- [ ] **Step 3: Type/format gate + commit**

```bash
conda run -n helao pyright helao/hexagon
conda run -n helao black helao/hexagon/tests/smoke/conc_items.py
git add helao/hexagon/tests/smoke/conc_items.py
git commit -m "test(hexagon): §10.3 item 7 idle drain + non-blank history + §9.1 launched log path (P1b2b)"
```

---

### Task 12: Gate verification & evidence record

The suite is **BLOCKING** for the orch milestone; every green claim names its transport (§10.2).

**Files:**
- Create: `helao/hexagon/tests/smoke/docs/p1b2b-gate-record.md`

**Interfaces:**
- Consumes: everything above.
- Produces: the P1 gate evidence the controller signs off on.

- [ ] **Step 1: Full in-process suite (Group A)**

```bash
conda run -n helao python -m pytest helao/hexagon/tests/ -v
```
Expected: PASS — including the pre-existing P1a/P1b1 tests (no regressions) and the new `test_live_group.py`, `test_behavior_hexagon.py`, `test_concurrency_live.py`. If CONFIG-singleton crosstalk makes the live tests order-sensitive in the full run, run the live files in their own pytest processes and record that (do not mark-skip them):
```bash
conda run -n helao python -m pytest helao/hexagon/tests/test_live_group.py helao/hexagon/tests/test_concurrency_live.py -v
```

- [ ] **Step 2: Launched-group items (Group B, MAIN SESSION, serially)**

```bash
bash helao/hexagon/tests/smoke/conc_run.sh item2 goldenhexid   /home/dan/INST_hlo_hexid HEXORC
bash helao/hexagon/tests/smoke/conc_run.sh item4 goldenhexconc /home/dan/INST_hlo_hexconc
bash helao/hexagon/tests/smoke/conc_run.sh item6 goldenhexconc /home/dan/INST_hlo_hexconc
bash helao/hexagon/tests/smoke/conc_run.sh item7 goldenhexconc /home/dan/INST_hlo_hexconc
```
Expected: exit 0, four times. Record each exit code.

- [ ] **Step 3: Static gates**

```bash
conda run -n helao pyright helao/hexagon
conda run -n helao black --check helao/hexagon
```
Expected: pyright 0 errors; black clean.

- [ ] **Step 4: Write the gate record**

`helao/hexagon/tests/smoke/docs/p1b2b-gate-record.md`:

```markdown
# P1b2b gate record — §10.3 items 1–7 + §9 behavior (hexagon path)

Every row names its transport per master spec §10.2 ("green claims state
the transport/adapters used"). Fill in the actual dates/results.

| Check | Mechanism | Transport | Result |
|---|---|---|---|
| §10.3-1 lost wakeup / double drain | in-process pytest | real ZMQ RPC + HTTP (uvicorn), real WS on SIM | |
| §10.3-2 non-default identity (HEXORC) | launched group (goldenhexid) | full launched stack (ZMQ RPC + HTTP + WS) | |
| §10.3-3a/b/c estop decision↔effect | in-process pytest | real ZMQ RPC + HTTP; estop via /estop_orch (a,b), reducer event (c) | |
| §10.3-4 serial 3-experiment | launched group (goldenhexconc) | full launched stack | |
| §10.3-5 nonblocking lifecycle | in-process pytest | real ZMQ RPC + HTTP (/update_nonblocking, /stop_executor) | |
| §10.3-6 heartbeat-only exit | launched group (goldenhexconc, SIM SIGKILL) | full launched stack | |
| §10.3-7 idle drain + history | launched group (goldenhexconc) | full launched stack | |
| §9.1 logging (composition) | pytest (build_wiring) + item7 launched asserts | n/a / full launched stack | |
| §9.2 config identity | pytest (build_wiring) | n/a | |
| §9.3 clock offset | pytest (build_wiring) | n/a | |
| DispatcherStatusAdapter own identity | pytest + item5 round-trip | real ZMQ RPC + HTTP | |
| pyright helao/hexagon | static | n/a | |
| full hexagon pytest suite | pytest | mixed (see rows) | |
```

- [ ] **Step 5: Commit**

```bash
conda run -n helao black --check helao/hexagon
git add helao/hexagon/tests/smoke/docs/p1b2b-gate-record.md
git commit -m "docs(hexagon): P1b2b gate record — §10.3 items 1–7 + §9 evidence (P1b2b)"
```

---

## Self-Review

**1. Spec coverage.**
- §10.3 item 1 → Task 4 (in-process, burst injection). Item 2 → Task 8 (goldenhexid + hexid library + full-run asserts). Item 3 (a)(b)(c) → Task 5 (three tests: dispatch-gate, decision→effect window on `FinishThenDispatchExperimentCmd`, finalization window on `CloseOutExperimentCmd`; single finalizer + `[finished, estopped]` + no duplicate finished asserted in all three via `_assert_estopped_exp_yml` + spy counters). Item 4 → Task 9 (3 experiments, per-experiment finish-before-next-start ordering from history timestamps, `/list_nonblocking` empty). Item 5 → Task 6 (adapter round-trip over real `/update_nonblocking` + `/stop_executor`, plus full `TEST_consecutive_noblocking` run; flag-survives asserted by mid-run `orch.nonblocking` non-empty). Item 6 → Task 10 (SIGKILL SIM mid-action; heartbeat message `"endpoints are unavailable"` is the asserted exit). Item 7 → Task 11 (no `/stop`; parked stopped + idle; non-blank history metas). Items 8–10 are P2 — explicitly out of scope, consistent with the P1 gate ("items 1–7").
- §9.1/9.2/9.3 → Task 3 (composition path via `build_wiring`) + Task 11 (launched-path log-file asserts). The P0 legacy twins are cross-referenced (`harness/tests/test_legacy_contracts.py`).
- P1b1 carry (`DispatcherStatusAdapter` `own_host`/`own_port`) → Task 1 (wiring + required sets + docstring), exercised live in Task 6/item 5.
- §10.1 fixture fidelity → no stub orchs anywhere; all endpoints registered through real `makeOrchApp`/`makeActionApp`; §10.2 transport naming → Task 12 gate record.
- Gap check: item 3's "no duplicate finished" is asserted at the artifact level (`experiment_status` count) and at the finalizer level (spy counts) — both spec phrasings covered.

**2. Placeholder scan.** No TBD/TODO/"similar to Task N" remain; the `hexid_exp.py` library is written out in full rather than "copy simulatews_exp"; every test/driver block is complete code. Deliberate conditional-fix notes (Task 2 Step 3, Task 5 note, Task 6 known-failure note, Task 8 library-path fallback) are contingency instructions with concrete actions, not placeholders.

**3. Type/name consistency.** `live_group`/`LiveGroup`/`orch_call`/`build_ws_sequence`/`wait_parked` defined in Task 2 and consumed with identical signatures in Tasks 3–6. `_spy_finishers` defined in Task 4, reused in Task 5. `ITEMS` registry signature `(root: Path, orch_key: str, prefix: str) -> int` consistent across Tasks 8–11 and `main()`. `ORCH_REQUIRED`/`ACTION_REQUIRED` tuples in Task 1 match `PortWiring.require` names. `parse_hist_ts`/`HIST_TS_FMT` defined in Task 7, used in Task 9. Config prefixes (`goldenhexconc`, `goldenhexid`) and roots (`/home/dan/INST_hlo_hexconc`, `/home/dan/INST_hlo_hexid`) consistent between configs, run commands, and Task 12.

**Assumptions the reviewer must verify (also in the summary):**
1. **In-process ORCH boot viability (Task 2):** `makeOrchApp` under uvicorn in the pytest process — legacy `Orch`/`Base` startup may need launcher-augmented config keys or a DB server entry; Step 3 lists the sanctioned harness-side fixes. This is the plan's biggest execution risk.
2. **`experiment_libraries` path outside `helao/deploy/` (Task 8):** assumed the loader accepts `helao/hexagon/tests/smoke/hexid_exp.py`; fallback (new file under `helao/deploy/test/experiments/`) documented in-task.
3. **Adapter's minimal nonblocking body vs legacy `update_nonblocking`'s timestamp f-string (Task 6):** may 500 on `action_timestamp=None`; the sanctioned adapter-local fix is documented in-task.
4. **Exp-yml parse (Task 5):** `yaml.safe_load` on `-exp.yml` with `experiment_status: [finished, estopped]`; fallback to `helao.helpers.yml_tools.yml_load` noted.
5. **`action_history` accounting (Tasks 4/9):** one entry per dispatched action with `%m-%d %H:%M:%S` timestamps via the shared uuid-registration side effect; Task 4 notes how to re-scope the count source without weakening exactly-once.
