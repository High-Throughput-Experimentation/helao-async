# P1b1: hexagon adapters + app + dispatch loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fill `helao/hexagon/adapters/` and `helao/hexagon/app/` with legacy-wrapping adapters, a fail-loud composition factory (with co-located RPC), and the single-drainer dispatch loop that drives the P1a reducer — so that a hexagon-composed server group launches on Linux and runs one sequence end-to-end (smoke).

**Architecture:** P1b1 is the second slice of master-spec phase P1 (`docs/superpowers/specs/2026-07-16-framework-hexagonal-rewrite-design.md`, §12 P1; §4.4 adapters; §4.5 app/composition; §7 wire contract). Strategy is **wrapped-legacy composition**: the hexagon orchestrator app constructs the legacy `OrchAPI`/`Orch` (all endpoints, status ingestion, artifact writers, queue machinery run unmodified legacy code — behavior identical by construction), then **replaces only the dispatch loop**: instance-level rebinding routes `start/stop/skip/estop_loop/clear_estop/clear_error` through a pure-reducer runtime (`helao.hexagon.domain.orchestration.step`), and a single long-lived Event-parked task executes the returned commands by thin delegation onto the wrapped legacy `Orch` methods. Outbound adapters (Config/Logging/Clock/Transport/ArtifactStore/DataSink/Sync/Status/Hardware/StatePersistence/SampleState) implement the P1a port Protocols by wrapping legacy behavior; the factory raises at startup on any unwired port. The GM-1..5 golden **parity** gate and the §10.3 concurrency suite are **P1b2 — not in this plan** (the smoke here proves wiring, not byte-parity), but every seam is designed so P1b2 drops in cleanly (see "P1b2 preview" at the end).

**Tech Stack:** Python 3.12 (conda env `helao`), FastAPI/uvicorn + zmq.asyncio (via legacy `HelaoFastAPI`), pydantic v2, pytest (hexagon tree only), pyright (authoritative), black 88. P0 harness (`harness/capture.py`) reused for the smoke.

## Global Constraints

Copied verbatim from the master spec + project rules. Every task's requirements implicitly include this section.

- **Environment:** all commands run inside the `helao` conda env (`conda run -n helao …`), Python 3.12, `PYTHONPATH` at repo root. Never use the OS python.
- **Formatting:** run `black <changed_files>` (default settings, line length 88) as the final step before **every** commit.
- **Type checking:** `pyright` (`pyrightconfig.json`, basic mode) is authoritative; 0 new errors on `helao/hexagon/` is a gate. Do not remove `# type: ignore` directives pyright needs.
- **Package:** `helao/hexagon/` (locked). NOT `helao/framework/` — that is the abandoned tree; if a stale untracked `helao/framework/` exists on disk it must never be staged.
- **ZERO legacy edits:** no existing file outside `helao/hexagon/` is modified, with exactly two sanctioned additions (not edits): the new shim package `helao/deploy/hexagon/` + config `helao/deploy/test/configs/goldenhex.yml`, and ONE `.gitignore` un-ignore line (`!helao/deploy/hexagon/`). Adapters **wrap** legacy behavior (import + delegate, or instance-level rebinding at composition time); they never modify legacy source.
- **Co-located RPC is mandatory** (spec §7.1): every hexagon FastAPI server serves an RPC dispatcher on `derive_rpc_port(http_port) = http_port + 10000` mirroring every POST route. P1b1 inherits this from legacy `HelaoFastAPI` (`helao/helpers/server_api.py:87-119`, including the ROUTER bind-to-configured-host with `0.0.0.0` fallback from commits 8dc8a0a8/7e737137) and **verifies** it with a behavior test.
- **Single-drainer dispatch loop** (KEEP #2/#3): one long-lived asyncio task parked on an `asyncio.Event` owns every queue-draining command; **in-process self-ops** — the loop never issues an RPC/HTTP request to its own server; all effects are direct method calls on the wrapped `Orch`.
- **Fail loud:** app composition RAISES at startup on any unwired port (no fake defaults); fakes keep their WARNING banners; the Logging adapter RAISES instead of falling back to `tempfile.mkdtemp()` (F3).
- **Raw-dict config identity** (spec §9.2): the Config adapter hands out views of the **same** dict object `install_global_config` published; `CONFIG["servers"][key] is server_cfg` must hold (the `--restore` in-place mutation gate rides on it).
- **Privacy:** NO private-deployment names/aliases anywhere in code, tests, configs, comments, or commits (public repo). Say "a private deployment" / Deployment-A/B/C.
- **Git hygiene:** `git add` specific files only — never `-A`/`-a`/`.`; never stage untracked `helao/framework/`; branch `feat/hexagon-p1b1` off `unstable`; do not push without explicit authorization.
- **Domain/ports are LOCKED (P1a):** no file under `helao/hexagon/domain/` or `helao/hexagon/ports/` is modified; their AST allow-lists in the boundary test stay locked. Only the adapters/app/tests layer rules are extended.
- **Tests:** `conda run -n helao python -m pytest helao/hexagon/tests -q`. The legacy no-pytest convention elsewhere is unchanged. Note: importing legacy modules in a bare pytest process (no launcher) triggers legacy's module-top `make_logger(__file__)` tempdir loggers — that is pre-existing legacy import behavior, not a P1b1 regression; the F3 guard applies to the Logging **port** and to launched servers (asserted in the smoke).

**P1b1 gate (end of plan):** boundary test (extended) green; all adapter conformance/behavior tests green; loop unit tests green (incl. the estop-during-effect race seed); pyright 0 new errors; black clean; **SMOKE**: `goldenhex.yml` (ORCH + SIM on `deployment: hexagon`, DB on legacy sim_db_server) launches via `launch.py`, runs GM-1 end-to-end through the P0 capture rig (`--config-prefix goldenhex`), produces a RUNS_* tree + PROCESSES `-prc.yml`s + RUNS_SYNCED zip, quiesces, and shuts down cleanly. **Explicitly NOT P1b1:** GM-1..5 normalized parity diffs, §10.3 concurrency suite, §9 behavior tests on the hexagon path — all P1b2.

---

## Design decisions locked for this plan

### DD-1: Wrapped-legacy composition

The hexagon orch app = legacy `OrchAPI` constructed by the hexagon factory + a **graft**: after `OrchAPI`'s own startup handler builds `app.orch = Orch(fastapp=self)`, a second startup handler (registered later, so it runs later) rebinds six instance methods (`start`, `start_loop`, `stop`, `skip`, `estop_loop`, `clear_estop`, `clear_error`) to route through the reducer runtime, and starts the single-drainer loop task. Legacy code explicitly supports instance-level patching (see `orch_estop.py` docstring: "an instance-level patch of `orch.estop_actions` stays observable"). Everything else — status ingestion (`StatusIngester` under `orch.aiolock`), queue CRUD, `finish_active_*` artifact writes, `seq_unpacker`, heartbeat monitor, `/wait` self-hosted executors (in-process via legacy `Base.stop_executor` — KEEP #3 inherited) — runs unmodified legacy code.

### DD-2: State ownership and delta application

`OrchestrationState` is **derived fresh from live orch state** before every `step()` call (call-time state resolution, the same rule `DispatchRunner._snapshot` follows). The returned state is applied as a **delta, state-first** (before commands), with these rules:

| Field | Application rule |
|---|---|
| `loop_state` | Written to `orch.globalstatusmodel.loop_state` **unless** (a) the live value is `estopped` and the reducer's input state was not `estopped` (a concurrent E-STOP landed between derive and apply — never clobber it; only T10 `ClearEstopRequested`, whose input state IS `estopped`, may overwrite), or (b) the command set contains `WaitAllActionsIdle` (T5 drain: the verbatim legacy drain body owns the `stopped` write **after** waiting for actions idle — pre-writing would skip the drain). |
| `loop_intent` | Applied via the legacy `orch.intend_stop()/intend_skip()/intend_estop()/intend_none()` methods so the `interrupt_q` wake side effect is preserved. |
| `orch_state` | **NOT written back in P1b1.** Legacy's `StatusIngester` is the sole `orch_state` owner (legacy `estop_loop` never sets `orch_state` — verified against `orch_status_sync`); the reducer's `orch_state` field is loop-internal bookkeeping until the hexagon ingestion path lands (P1b2/P2). |

### DD-3: live-estop re-check — the chosen approach (spec §4.2.2)

**Chosen: option (a), re-read-live in the effect runner — with estop executing at its trigger site through the same reducer.**

- Control events (`StartRequested`, `StopRequested`, `SkipRequested`, `EstopRequested`, `ClearEstopRequested`, `ClearErrorRequested`) are handled **synchronously at their trigger site** (endpoint task, status-ingestion task) via `HexRuntime.handle(event)` — the reducer is pure and reentrant, so any task may call it. The E-STOP state flip and cascade therefore run **concurrent with the loop, exactly as legacy's ingester-task `estop_loop` does**.
- The five marked commands (`DispatchHeadAction`, `FinishThenDispatch{Experiment,Sequence}Cmd`, `CloseOut{Experiment,Sequence}Cmd`) re-read `orch.globalstatusmodel.loop_state` (and, for close-outs, the live queue/active state via `should_close_out_*`) **immediately before executing**, mirroring the three legacy guard sites verbatim.
- **Why not full serialization (option b):** serializing the estop cascade behind the loop's in-flight command deadlocks — a dispatch effect blocked in `wait_for_interrupt` (start-condition wait) is only released by the cascade's own fan-out finalizing actions and pushing status; if the cascade waits for the command, neither proceeds. Legacy resolves this with concurrency + guards; we keep that shape. The single-drainer invariant survives intact: **only the loop task ever executes queue-draining commands** (`DispatchHeadAction`/`FinishThenDispatch*`/`CloseOut*` arise only from `LoopIterate`); the trigger-site path executes only the estop/clear cascade commands (`EstopFanout`, `FinishActiveEstopped`, `Clear*`, …), whose legacy bodies are idempotent (`estop_finish_active`'s guarded `_mark_estopped`).
- **P1b2 testability of BOTH races:** because the re-checks are one function (`OrchCommandRunner` guard sites) and the flip is one call (`HexRuntime.handle(EstopRequested(...))` from any task), P1b2 can inject the flip (i) while the loop is blocked on `orch.aiolock` inside the wrapped `_dispatch_action_locked`, and (ii) between the reducer's `FinishThenDispatch` decision and the effect / during finalization close-out — asserting a single finalizer and `[finished, estopped]` terminal status. A P1b1 unit test already seeds race (ii).
- Carry-note (`mark_estopped` async race): concurrent double-triggering of `estop_finish_active` (ingester + endpoint) has the same exposure as legacy and is absorbed by legacy's idempotent `guarded_replace`/`guarded_append` in `_mark_estopped`; the P1b1 race-seed test asserts single execution through the runtime, P1b2's suite covers the concurrent case.

### DD-4: Reducer events NOT fed in P1b1 (wrapped-effect composites)

`orch.loop_task_dispatch_action()` is wrapped whole — popleft, start-condition wait, in-lock dispatch, result fold, error requeue all happen inside legacy code. Consequently the fine-grained events `DispatchFailed`, `PlateGateFailed`, `HeartbeatFailed`, `DriverHealthUnrecovered`, `ActionResultErrored`, `EstoppedUuidIngested`, `ErroredUuidIngested`, `StatusChanged` are **not fed** in P1b1: their legacy equivalents run inside the wrapped composites (e.g. head-requeue inside the dispatch fold; the ingester's estop branch funnels through the rebound `orch.estop_loop` → `EstopRequested`). The runner mirrors legacy's `_loop` epilogue instead: a non-`none` error code from a dispatch effect triggers `await orch.intend_stop()`. `RequeueHeadAction` is therefore unreachable and its effect is a WARNING log (executing it would double-insert). Decomposing these composites onto native events is P1b2/P2 work; the reducer already supports them (P1a-tested).

### DD-5: Known, documented, artifact-invisible divergences

All of these affect only log wording or in-memory ordering, never disk/wire bytes; each is noted at its code site:

1. Estop sequence: `intend_none` (via the state delta) runs before the fan-out; legacy runs it after (`estop_loop` body order). Both orders precede `estop_finish_active` (the artifact writer).
2. `StopLoop` under estop: legacy double-calls `intend_stop` (once in `stop_loop()`, once in the `error_code is not none` epilogue); the reducer sets intent once.
3. Skip/estop queue-clear log wording ("skipping to next experiment" / "estopping") collapses to one `ClearActionQueue` effect log.
4. `hex_start` refusal wording comes from the reducer (`"experiment list is empty"` matches legacy; `"clear E-STOP first"` replaces legacy's "already running" for the estopped case — strictly more accurate).
5. T10 `clear_estop`: `loop_state=stopped` is applied (state-first) before `estop_actions(switch=False)`; legacy sets it after. The loop is parked either way.
6. Estop interrupt wake: legacy `estop_loop` calls `intend_none()` (which puts `interrupt_q`); when the intent was already `none` the reducer's delta skips that call, so the graft's `hex_estop_loop` puts `interrupt_q` explicitly after the cascade — same wake, explicit site.

### DD-6: Launcher routing without launcher edits

`fast_launcher.py` already honors a per-server `deployment:` key with any name and skips the glob (`fast_launcher.py:89`): `deployment: hexagon` imports `helao.deploy.hexagon.servers.<group>.<fast>`. So the hexagon route is a new **shim package** `helao/deploy/hexagon/` whose modules' `makeApp(server_key)` delegate to `helao.hexagon.app.factory` — zero launcher edits, per-config atomic cut-over preserved (flip the key back to roll back). `.gitignore` excludes `helao/deploy/*` except `hte`/`test`; one un-ignore line (`!helao/deploy/hexagon/`) makes the shims trackable.

### DD-7: Deferred (NOT P1b1 — carried to the P1b2 preview)

TransformXY lift; ActionPlanMaker frame-inspection removal; Timer port; Status port's `publish_status/publish_data/publish_live` WS-publisher bridge (adapter raises a documented `HexagonDeferred` error — the smoke's WS channels run on legacy Base relays); AnalysisArtifact adapter (P6 consumer); aux adapters PlateInfo/Library/Health/Notify (no P1b1 consumer — the wrapped legacy machinery provides those behaviors internally); rerouting action-server write paths through the ArtifactStore/DataSink adapters at runtime (P1b1 builds + tests the adapters; legacy internals still carry the smoke's traffic — parity re-verification when traffic moves is exactly the P1b2/P2 gate).

## File Structure

```
helao/hexagon/
├── adapters/
│   ├── __init__.py                        # (exists, stays empty)
│   ├── fakes/
│   │   └── __init__.py                    # RELOCATED from tests/fakes.py (Task 2)
│   └── legacy/
│       ├── __init__.py
│       ├── config.py                      # LegacyConfigAdapter (raw-dict identity)
│       ├── logging_adapter.py             # LegacyLoggingAdapter (fail-loud, no mkdtemp)
│       ├── clock.py                       # LegacyClockAdapter (NTP offset file)
│       ├── transport.py                   # LegacyTransportAdapter (ZMQ+HTTP dispatchers)
│       ├── artifact_store.py              # LegacyArtifactStoreAdapter (Base/Active writers)
│       ├── data_sink.py                   # ActiveDataSinkAdapter (Active delegation)
│       ├── sync.py                        # LegacySyncAdapter (HelaoSyncer delegation)
│       ├── status.py                      # DispatcherStatusAdapter (wire-level status push)
│       ├── hardware.py                    # LegacyDriverHardwareAdapter (HelaoDriver passthrough)
│       ├── state_persistence.py           # QueuePckStore (queues.pck contract)
│       └── sample_state.py                # SampleShimAdapter (flattening facade over the shim)
├── app/
│   ├── __init__.py                        # (exists, stays empty)
│   ├── wiring.py                          # PortWiring + UnwiredPortError (fail-loud primitive)
│   ├── orch_effects.py                    # derive_state, apply_state_delta, OrchCommandRunner
│   ├── dispatch_loop.py                   # HexRuntime, HexDispatchLoop, graft_hexagon_loop
│   └── factory.py                         # makeOrchApp / makeActionApp / makeVisApp
└── tests/
    ├── test_boundaries.py                 # EXTENDED (Task 1)
    ├── test_fakes.py                      # import path updated (Task 2)
    ├── test_wiring.py                     # Task 3
    ├── test_adapters_runtime_services.py  # Task 4 (config/logging/clock)
    ├── test_adapter_transport.py          # Task 5 (incl. co-located RPC timing)
    ├── test_adapters_data.py              # Task 6 (artifact_store/data_sink)
    ├── test_adapters_misc.py              # Task 7 (sync/status/hardware/persistence/sample)
    ├── test_orch_effects.py               # Task 8
    ├── test_dispatch_loop.py              # Task 9
    └── test_factory.py                    # Task 10

helao/deploy/hexagon/                      # launcher shim package (DD-6)
├── __init__.py
└── servers/
    ├── __init__.py
    ├── orchestrator/
    │   ├── __init__.py
    │   └── async_orch2.py                 # makeApp -> factory.makeOrchApp
    └── action/
        ├── __init__.py
        └── ws_simulator.py                # makeApp -> factory.makeActionApp(test ws sim)

helao/deploy/test/configs/goldenhex.yml    # smoke config (Task 11)
.gitignore                                 # + "!helao/deploy/hexagon/" (Task 10)
```

---

### Task 1: Extend the AST boundary test for adapters/app/tests

**Files:**
- Modify: `helao/hexagon/tests/test_boundaries.py`

**Interfaces:**
- Consumes: the existing walker (`iter_violations`, `_allowed`, `_walk_layer`) — P1a, unchanged in mechanism.
- Produces: layer rules used by every later task: `adapters/` may import anything **except** `helao.hexagon.app` and `helao.hexagon.tests`; `app/` may import anything **except** `helao.hexagon.tests`; `domain/`/`ports/` allow-lists untouched (locked).

- [ ] **Step 1: Create the branch**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
git checkout unstable && git pull && git checkout -b feat/hexagon-p1b1
```

- [ ] **Step 2: Write the failing tests** — append to `helao/hexagon/tests/test_boundaries.py`:

```python
def test_checker_flags_adapters_importing_app_and_tests(tmp_path):
    """Mutation self-test: adapters/ may import legacy helao.* and vendors,
    but never the app layer (composition inversion) nor test code."""
    victim = HEXAGON_ROOT / "adapters" / "_boundary_selftest_tmp.py"
    victim.write_text(
        "import httpx\n"  # vendors ARE allowed in adapters
        "from helao.core.servers.base import Base\n"  # legacy allowed
        "from helao.hexagon.app import factory\n"  # banned
        "from helao.hexagon.tests import fakes\n"  # banned
    )
    try:
        hits = iter_violations(victim)
        assert {m for _, m, _ in hits} == {
            "helao.hexagon.app",
            "helao.hexagon.tests",
        }
    finally:
        victim.unlink()


def test_checker_flags_app_importing_tests(tmp_path):
    """Mutation self-test: app/ may import adapters+ports+domain+anything,
    but never test code (fakes are opt-in via adapters/fakes, spec §10.2)."""
    victim = HEXAGON_ROOT / "app" / "_boundary_selftest_tmp.py"
    victim.write_text(
        "import fastapi\n"
        "from helao.hexagon.adapters.fakes import FakeClock\n"  # allowed (opt-in)
        "from helao.hexagon.tests.test_orchestration import x\n"  # banned
    )
    try:
        hits = iter_violations(victim)
        assert {m for _, m, _ in hits} == {"helao.hexagon.tests.test_orchestration"}
    finally:
        victim.unlink()


def test_app_layer_clean():
    bad = [v for f in _walk_layer("app") for v in iter_violations(f)]
    assert not bad, f"app boundary violations: {bad}"
```

- [ ] **Step 3: Run to verify they fail**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_boundaries.py -q`
Expected: 2 FAIL (`test_checker_flags_adapters_importing_app_and_tests`, `test_checker_flags_app_importing_tests`) — current `_allowed` returns True for everything in `app`, and misses the `tests` ban in `adapters`. `test_app_layer_clean` passes (app is empty).

- [ ] **Step 4: Extend `_allowed`** — replace the current `if layer in ("app", "tests", "root")` block in `_allowed` with:

```python
def _allowed(module: str, layer: str) -> bool:
    top = module.split(".")[0]
    if layer in ("tests", "root"):
        return True
    if layer == "app":
        # composition root: anything EXCEPT test code (fakes live in
        # adapters/fakes and are opt-in; tests/ must never leak into prod)
        return not (
            module == f"{HEXAGON_PKG}.tests"
            or module.startswith(f"{HEXAGON_PKG}.tests.")
        )
    if layer == "adapters":
        # ports+domain+vendor+legacy helao.* allowed; never app (inversion)
        # and never tests
        return not (
            module == f"{HEXAGON_PKG}.app"
            or module.startswith(f"{HEXAGON_PKG}.app.")
            or module == f"{HEXAGON_PKG}.tests"
            or module.startswith(f"{HEXAGON_PKG}.tests.")
        )
    # domain / ports (LOCKED — do not touch below this line)
    if top in VENDOR_BANNED:
        return False
    if top in _STDLIB:
        return top not in STDLIB_DENY
    prefixes = DOMAIN_ALLOW_PREFIXES if layer == "domain" else PORTS_ALLOW_PREFIXES
    if layer == "domain" and top in DOMAIN_THIRD_PARTY:
        return True
    return any(module == p or module.startswith(p + ".") for p in prefixes)
```

Also update the module docstring's layer-rules block to:

```
- adapters/: anything EXCEPT helao.hexagon.app and helao.hexagon.tests
- app/     : anything EXCEPT helao.hexagon.tests
- tests/   : anything (fakes moved to adapters/fakes in P1b1)
```

- [ ] **Step 5: Run to verify all pass**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_boundaries.py -q`
Expected: all PASS (existing P1a tests + 3 new).

- [ ] **Step 6: Full suite + commit**

```bash
conda run -n helao python -m pytest helao/hexagon/tests -q   # expected: all pass
conda run -n helao black helao/hexagon/tests/test_boundaries.py
git add helao/hexagon/tests/test_boundaries.py
git commit -m "test(hexagon): extend AST boundary rules for adapters/app layers (P1b1 T1)"
```

---

### Task 2: Relocate fakes to `adapters/fakes/`

**Files:**
- Create: `helao/hexagon/adapters/fakes/__init__.py` (content moved from `helao/hexagon/tests/fakes.py`)
- Delete: `helao/hexagon/tests/fakes.py`
- Modify: `helao/hexagon/tests/test_fakes.py` (import path)

**Interfaces:**
- Consumes: nothing new.
- Produces: `from helao.hexagon.adapters.fakes import FakeClock, FakeTransport, FakeArtifactStore, FakeDataSink, FakeStatusPush, FakeStatePersistence` — the import path every later test and (opt-in only, never default) composition uses. WARNING banners preserved verbatim.

- [ ] **Step 1: Move the module**

```bash
mkdir -p helao/hexagon/adapters/fakes
git mv helao/hexagon/tests/fakes.py helao/hexagon/adapters/fakes/__init__.py
```

- [ ] **Step 2: Update the module docstring** — in `helao/hexagon/adapters/fakes/__init__.py`, replace the first docstring paragraph line `TEST-ONLY in P1a. Each fake logs a WARNING banner at construction so a` with:

```python
"""In-memory port fakes (spec §10.2): OPT-IN test doubles, never wired by
default composition.

Each fake logs a WARNING banner at construction so a "green on fakes" run is
visible in output; production composition (app/wiring.py) raises on unwired
ports and never defaults to these.
"""
```

(keep everything below the docstring byte-identical).

- [ ] **Step 3: Update the one importer** — in `helao/hexagon/tests/test_fakes.py` replace:

```python
from helao.hexagon.tests import fakes
```

with:

```python
from helao.hexagon.adapters import fakes
```

- [ ] **Step 4: Verify no stale importers remain, run the suite**

```bash
grep -rn "hexagon.tests.fakes\|hexagon.tests import fakes" helao/ --include="*.py" | grep -v __pycache__   # expected: no output
conda run -n helao python -m pytest helao/hexagon/tests -q                                                # expected: all pass (boundary test now walks adapters/fakes: vendor-free stdlib imports, still clean)
```

- [ ] **Step 5: Commit**

```bash
conda run -n helao black helao/hexagon/adapters/fakes/__init__.py helao/hexagon/tests/test_fakes.py
git add helao/hexagon/adapters/fakes/__init__.py helao/hexagon/tests/test_fakes.py
git rm --cached helao/hexagon/tests/fakes.py 2>/dev/null || true   # git mv already staged the rename; this is a no-op guard
git commit -m "refactor(hexagon): relocate port fakes to adapters/fakes (opt-in, P1b1 T2)"
```

---

### Task 3: Fail-loud composition primitive (`app/wiring.py`)

**Files:**
- Create: `helao/hexagon/app/wiring.py`
- Test: `helao/hexagon/tests/test_wiring.py`

**Interfaces:**
- Consumes: port Protocols from `helao.hexagon.ports.*` (P1a, exact names: `ConfigPort`, `LoggingPort`, `ClockPort`, `TransportPort`, `StatePersistencePort`, `ArtifactStorePort`, `DataSinkPort`, `SyncPort`, `StatusPort`, `HardwarePort`, `SampleStatePort`).
- Produces: `UnwiredPortError(RuntimeError)`; `HexagonDeferred(NotImplementedError)`; `@dataclass PortWiring` with one `Optional[...]` slot per port and `require(*names: str) -> None` (raises `UnwiredPortError` listing every missing name); constants `ORCH_REQUIRED: tuple[str, ...] = ("config", "logging", "clock", "transport", "state_persistence")` and `ACTION_REQUIRED: tuple[str, ...] = ("config", "logging", "clock", "transport")`.

- [ ] **Step 1: Write the failing test** — `helao/hexagon/tests/test_wiring.py`:

```python
"""Fail-loud composition primitive (spec §10.2 / §4.5: composition RAISES on
any unwired port — there are no default fakes)."""

import pytest

from helao.hexagon.app.wiring import (
    ACTION_REQUIRED,
    ORCH_REQUIRED,
    PortWiring,
    UnwiredPortError,
)
from helao.hexagon.adapters.fakes import FakeClock, FakeTransport


def test_require_raises_listing_every_missing_port():
    w = PortWiring(clock=FakeClock())
    with pytest.raises(UnwiredPortError) as ei:
        w.require("config", "clock", "transport")
    msg = str(ei.value)
    assert "config" in msg and "transport" in msg
    assert "clock" not in msg  # wired ports are not reported


def test_require_passes_when_all_wired():
    w = PortWiring(clock=FakeClock(), transport=FakeTransport())
    w.require("clock", "transport")  # no raise


def test_require_rejects_unknown_port_name():
    with pytest.raises(UnwiredPortError):
        PortWiring().require("no_such_port")


def test_required_sets_are_frozen_tuples():
    assert set(ACTION_REQUIRED) <= set(ORCH_REQUIRED) | {"transport"}
    assert "state_persistence" in ORCH_REQUIRED
```

- [ ] **Step 2: Run to verify it fails**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_wiring.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'helao.hexagon.app.wiring'`.

- [ ] **Step 3: Implement** — `helao/hexagon/app/wiring.py`:

```python
"""Fail-loud port wiring (spec §4.5, F2b countermeasure).

Composition RAISES at startup on any port a composition consumes but has no
adapter for — there is no silent default and no fake fallback (fakes are
opt-in via helao.hexagon.adapters.fakes and self-announce with WARNING
banners). ``require()`` names the composition's consumed set; ports without a
P1b1 consumer are simply not in the required set yet (they gain consumers in
P1b2/P2 and join the set then).
"""

from dataclasses import dataclass, fields
from typing import Optional

from helao.hexagon.ports.artifact_store import ArtifactStorePort
from helao.hexagon.ports.clock import ClockPort
from helao.hexagon.ports.config import ConfigPort
from helao.hexagon.ports.data_sink import DataSinkPort
from helao.hexagon.ports.hardware import HardwarePort
from helao.hexagon.ports.logging import LoggingPort
from helao.hexagon.ports.sample_state import SampleStatePort
from helao.hexagon.ports.status import StatusPort
from helao.hexagon.ports.sync import SyncPort
from helao.hexagon.ports.transport import TransportPort
from helao.hexagon.ports.auxiliary import StatePersistencePort

__all__ = [
    "ACTION_REQUIRED",
    "HexagonDeferred",
    "ORCH_REQUIRED",
    "PortWiring",
    "UnwiredPortError",
]


class UnwiredPortError(RuntimeError):
    """A consumed port has no adapter wired — composition must not start."""


class HexagonDeferred(NotImplementedError):
    """A port member whose legacy bridge is deliberately deferred to a later
    slice (documented at the raise site) — loud, never silent."""


# Ports each P1b1 composition genuinely consumes (fail-loud is meaningful,
# not vacuous). Extended as adapters gain runtime consumers in P1b2/P2.
ORCH_REQUIRED = ("config", "logging", "clock", "transport", "state_persistence")
ACTION_REQUIRED = ("config", "logging", "clock", "transport")


@dataclass
class PortWiring:
    """One Optional slot per P1a port Protocol. ``None`` == unwired."""

    config: Optional[ConfigPort] = None
    logging: Optional[LoggingPort] = None
    clock: Optional[ClockPort] = None
    transport: Optional[TransportPort] = None
    state_persistence: Optional[StatePersistencePort] = None
    artifact_store: Optional[ArtifactStorePort] = None
    data_sink: Optional[DataSinkPort] = None
    sync: Optional[SyncPort] = None
    status: Optional[StatusPort] = None
    hardware: Optional[HardwarePort] = None
    sample_state: Optional[SampleStatePort] = None

    def require(self, *names: str) -> None:
        known = {f.name for f in fields(self)}
        unknown = [n for n in names if n not in known]
        if unknown:
            raise UnwiredPortError(f"unknown port name(s): {sorted(unknown)}")
        missing = [n for n in names if getattr(self, n) is None]
        if missing:
            raise UnwiredPortError(
                "composition has unwired port(s): "
                f"{sorted(missing)} — wire a real adapter (fakes are opt-in "
                "and never a default; spec §10.2)"
            )
```

- [ ] **Step 4: Run to verify it passes**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_wiring.py helao/hexagon/tests/test_boundaries.py -q`
Expected: all PASS (boundary: `app/wiring.py` imports only ports — legal for app).

- [ ] **Step 5: Pyright + commit**

```bash
conda run -n helao pyright helao/hexagon/app/wiring.py   # expected: 0 errors
conda run -n helao black helao/hexagon/app/wiring.py helao/hexagon/tests/test_wiring.py
git add helao/hexagon/app/wiring.py helao/hexagon/tests/test_wiring.py
git commit -m "feat(hexagon): fail-loud PortWiring composition primitive (P1b1 T3)"
```

---

### Task 4: Runtime-services adapters — Config, Logging, Clock

**Files:**
- Create: `helao/hexagon/adapters/legacy/__init__.py` (empty with docstring `"""Legacy-wrapping adapters (P1b): import + delegate, never modify."""`)
- Create: `helao/hexagon/adapters/legacy/config.py`
- Create: `helao/hexagon/adapters/legacy/logging_adapter.py`
- Create: `helao/hexagon/adapters/legacy/clock.py`
- Test: `helao/hexagon/tests/test_adapters_runtime_services.py`

**Interfaces:**
- Consumes: `helao.helpers.config_loader` (module-global `CONFIG`, `install_global_config`), `helao.helpers.helao_logging.make_logger(logger_name, log_dir=None, email_config={}, log_level=20)`, `helao.helpers.time_utils.read_saved_offset(file_path) -> (ntp_last_sync, ntp_offset)` and `set_time(offset: float = 0) -> datetime`.
- Produces:
  - `LegacyConfigAdapter(world_cfg: dict)` implementing `ConfigPort`: `world_cfg() -> dict` (the SAME object), `server_cfg(server_key) -> dict` (identity view), `server_params(server_key) -> dict`, `root() -> str` (raises `KeyError` when absent).
  - `LegacyLoggingAdapter(logger=None)` implementing `LoggingPort`: `file_logger(server_key: str, log_root: str) -> object` raising `ValueError` on falsy `log_root`; `info/warning/error/alert` delegating to the wrapped logger (default: the `helao_logging.LOGGER` singleton at call time).
  - `LegacyClockAdapter(offset_s: float = 0.0)` + classmethod `from_offset_file(log_root: str) -> "LegacyClockAdapter"` implementing `ClockPort`: `now() -> datetime` (= `set_time(offset)`), `now_ns() -> int` (= `time.time_ns() + int(offset*1e9)`), `offset() -> float`.

- [ ] **Step 1: Write the failing tests** — `helao/hexagon/tests/test_adapters_runtime_services.py`:

```python
"""Config (raw-dict identity), Logging (fail-loud), Clock (NTP offset)."""

import logging as std_logging
from datetime import datetime, timedelta

import pytest

from helao.hexagon.adapters.legacy.clock import LegacyClockAdapter
from helao.hexagon.adapters.legacy.config import LegacyConfigAdapter
from helao.hexagon.adapters.legacy.logging_adapter import LegacyLoggingAdapter
from helao.hexagon.ports.clock import ClockPort
from helao.hexagon.ports.config import ConfigPort
from helao.hexagon.ports.logging import LoggingPort


# --- Config: raw-dict identity (spec §9.2) --------------------------------
def _world():
    return {
        "root": "/tmp/hex_t4",
        "servers": {"ORCH": {"host": "127.0.0.1", "port": 8001, "params": {"a": 1}}},
    }


def test_config_conformance_and_identity():
    cfg = _world()
    a = LegacyConfigAdapter(cfg)
    assert isinstance(a, ConfigPort)
    assert a.world_cfg() is cfg  # SAME object, every call
    assert a.world_cfg() is a.world_cfg()
    assert a.server_cfg("ORCH") is cfg["servers"]["ORCH"]  # --restore gate
    # in-place mutation through the view is visible in the source dict
    a.server_cfg("ORCH")["restore_queues_on_startup"] = True
    assert cfg["servers"]["ORCH"]["restore_queues_on_startup"] is True


def test_config_server_params_and_root():
    a = LegacyConfigAdapter(_world())
    assert a.server_params("ORCH") == {"a": 1}
    assert a.root() == "/tmp/hex_t4"
    with pytest.raises(KeyError):
        LegacyConfigAdapter({"servers": {}}).root()


# --- Logging: FAIL LOUD (F3) -----------------------------------------------
def test_logging_conformance():
    assert isinstance(LegacyLoggingAdapter(), LoggingPort)


def test_file_logger_raises_without_log_root(monkeypatch):
    import tempfile

    def _trap(*a, **k):  # the mkdtemp fallback must be unreachable
        raise AssertionError("tempfile.mkdtemp reached through the Logging port")

    monkeypatch.setattr(tempfile, "mkdtemp", _trap)
    a = LegacyLoggingAdapter()
    with pytest.raises(ValueError):
        a.file_logger("ORCH", "")
    with pytest.raises(ValueError):
        a.file_logger("ORCH", None)  # type: ignore[arg-type]


def test_file_logger_writes_contractual_path(tmp_path):
    a = LegacyLoggingAdapter()
    lg = a.file_logger("HEXT4", str(tmp_path))
    lg.info("hexagon logging adapter behavior test")  # type: ignore[attr-defined]
    logfile = tmp_path / "HEXT4.log"
    assert logfile.is_file()  # <log_root>/<server_key>.log, flat (spec §9.1)


def test_level_methods_delegate():
    rec: list = []

    class _Spy:
        def info(self, m):
            rec.append(("info", m))

        def warning(self, m):
            rec.append(("warning", m))

        def error(self, m, exc_info=False):
            rec.append(("error", m, exc_info))

        def alert(self, m):
            rec.append(("alert", m))

    a = LegacyLoggingAdapter(logger=_Spy())
    a.info("i"), a.warning("w"), a.error("e", exc_info=True), a.alert("a")
    assert rec == [("info", "i"), ("warning", "w"), ("error", "e", True), ("alert", "a")]


# --- Clock ------------------------------------------------------------------
def test_clock_conformance_and_offset_math():
    a = LegacyClockAdapter(offset_s=2.0)
    assert isinstance(a, ClockPort)
    assert a.offset() == 2.0
    # now() is set_time(offset): ~2 s ahead of the naive wall clock
    delta = a.now() - datetime.now()
    assert timedelta(seconds=1.5) < delta < timedelta(seconds=2.5)
    span = a.now_ns() - a.now_ns()
    assert span <= 0  # monotone non-decreasing call order sanity
    assert abs(a.now_ns() - (a.now().timestamp() * 1e9)) < 0.5e9


def test_clock_from_offset_file(tmp_path):
    # ntpLastSync.txt format written by time_utils.get_ntp_time: "<ts>,<offset>"
    (tmp_path / "ntpLastSync.txt").write_text("1752700000.0,1.25")
    a = LegacyClockAdapter.from_offset_file(str(tmp_path))
    assert a.offset() == 1.25


def test_clock_from_missing_offset_file(tmp_path):
    a = LegacyClockAdapter.from_offset_file(str(tmp_path))  # no file -> offset 0.0
    assert a.offset() == 0.0
```

- [ ] **Step 2: Run to verify failure**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_adapters_runtime_services.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'helao.hexagon.adapters.legacy'`.

Note: before writing the clock test's file format, confirm what `read_saved_offset` expects: `sed -n '105,130p' helao/helpers/time_utils.py`. If the on-disk format differs from `"<ts>,<offset>"`, adjust ONLY the test fixture line to write the real format (the adapter delegates to `read_saved_offset` either way).

- [ ] **Step 3: Implement the three adapters**

`helao/hexagon/adapters/legacy/config.py`:

```python
"""ConfigPort adapter (spec §9.2): raw-dict identity, wrap-not-modify.

Hands out views of the SAME dict object install_global_config published.
Never validates into a copy: pydantic HelaoConfig drops launcher-added keys
(loaded_config_path, deployment, ...) and breaks --restore's same-object
aliasing CONFIG["servers"][key] is server.server_cfg.
"""

from helao.hexagon.ports.config import ConfigPort

__all__ = ["LegacyConfigAdapter", "from_global_config"]


class LegacyConfigAdapter:
    def __init__(self, world_cfg: dict):
        if not isinstance(world_cfg, dict):
            raise TypeError("world_cfg must be the raw config dict")
        self._cfg = world_cfg

    def world_cfg(self) -> dict:
        return self._cfg

    def server_cfg(self, server_key: str) -> dict:
        return self._cfg["servers"][server_key]

    def server_params(self, server_key: str) -> dict:
        return self.server_cfg(server_key).get("params", {}) or {}

    def root(self) -> str:
        return self._cfg["root"]  # KeyError when undefined, like helao_dirs


def from_global_config() -> LegacyConfigAdapter:
    """Adapter over the launcher-installed module-global CONFIG (fail loud)."""
    from helao.helpers import config_loader

    if config_loader.CONFIG is None:
        raise RuntimeError(
            "config_loader.CONFIG is not installed; launch via fast_launcher/"
            "bokeh_launcher (or install_global_config) before composing"
        )
    return LegacyConfigAdapter(config_loader.CONFIG)


_PORT_CHECK: type[ConfigPort] = ConfigPort  # keeps the import purposeful for pyright
```

`helao/hexagon/adapters/legacy/logging_adapter.py`:

```python
"""LoggingPort adapter (spec §9.1, F3): ONE module, FAIL LOUD.

Wraps legacy helao.helpers.helao_logging — nothing is vendored. The two
legacy tempdir traps (make_logger(log_dir=None) -> mkdtemp(); OSError ->
mkdtemp()) are unreachable through this port: file_logger RAISES on a falsy
log root. Contractual path: <log_root>/<server_key>.log (flat file).
"""

from typing import Optional

from helao.helpers import helao_logging

__all__ = ["LegacyLoggingAdapter"]


class LegacyLoggingAdapter:
    def __init__(self, logger=None):
        self._logger = logger

    def _log(self):
        # call-time resolution so the launcher-installed singleton is seen
        return self._logger if self._logger is not None else helao_logging.LOGGER

    def file_logger(self, server_key: str, log_root: Optional[str]) -> object:
        if not log_root:
            raise ValueError(
                "Logging port refuses a file logger without a resolved log "
                "root (F3: the legacy mkdtemp() fallback is banned); pass "
                "<config root>/LOGS"
            )
        return helao_logging.make_logger(
            logger_name=server_key, log_dir=log_root
        )

    def info(self, msg: str) -> None:
        lg = self._log()
        if lg is not None:
            lg.info(msg)

    def warning(self, msg: str) -> None:
        lg = self._log()
        if lg is not None:
            lg.warning(msg)

    def error(self, msg: str, exc_info: bool = False) -> None:
        lg = self._log()
        if lg is not None:
            lg.error(msg, exc_info=exc_info)

    def alert(self, msg: str) -> None:
        lg = self._log()
        if lg is not None:
            lg.alert(msg)  # ALERT level 60 (email/webhook listeners, throttled)
```

`helao/hexagon/adapters/legacy/clock.py`:

```python
"""ClockPort adapter (spec §9.3): NTP offset arithmetic over legacy helpers.

Offset source: <root>/LOGS/ntpLastSync.txt (written by launch's get_ntp_time,
read via time_utils.read_saved_offset). now() mints via set_time(offset) —
the exact call every legacy *_timestamp uses; now_ns() matches Base's
get_realtime_nowait arithmetic (epoch ns + offset seconds * 1e9).
"""

import os
import time

from helao.helpers.time_utils import read_saved_offset, set_time

__all__ = ["LegacyClockAdapter"]


class LegacyClockAdapter:
    def __init__(self, offset_s: float = 0.0):
        self._offset = float(offset_s)

    @classmethod
    def from_offset_file(cls, log_root: str) -> "LegacyClockAdapter":
        path = os.path.join(log_root, "ntpLastSync.txt")
        if not os.path.exists(path):
            return cls(0.0)
        _last_sync, offset = read_saved_offset(path)
        return cls(float(offset or 0.0))

    def now(self):
        return set_time(offset=self._offset)

    def now_ns(self) -> int:
        return time.time_ns() + int(self._offset * 1e9)

    def offset(self) -> float:
        return self._offset
```

- [ ] **Step 4: Run to verify pass**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_adapters_runtime_services.py helao/hexagon/tests/test_boundaries.py -q`
Expected: all PASS. If `read_saved_offset`'s return shape differs (it may return a dict or a single float — verify against `helao/helpers/time_utils.py:105`), fix `from_offset_file`'s unpacking to match the real helper; the test asserting `offset() == 1.25` stands.

- [ ] **Step 5: Pyright + commit**

```bash
conda run -n helao pyright helao/hexagon/adapters/legacy/   # expected: 0 errors
conda run -n helao black helao/hexagon/adapters/legacy/ helao/hexagon/tests/test_adapters_runtime_services.py
git add helao/hexagon/adapters/legacy/__init__.py helao/hexagon/adapters/legacy/config.py helao/hexagon/adapters/legacy/logging_adapter.py helao/hexagon/adapters/legacy/clock.py helao/hexagon/tests/test_adapters_runtime_services.py
git commit -m "feat(hexagon): Config/Logging/Clock legacy adapters (P1b1 T4)"
```

---

### Task 5: Transport adapter + co-located RPC verification

**Files:**
- Create: `helao/hexagon/adapters/legacy/transport.py`
- Test: `helao/hexagon/tests/test_adapter_transport.py`

**Interfaces:**
- Consumes: `helao.helpers.dispatcher.async_action_dispatcher(world_config_dict, A, params={}, timeout=60, retries=5) -> (resp|None, ErrorCodes)`, `async_private_dispatcher(server_key, host, port, private_action, params_dict, json_dict, timeout=60, retries=5) -> (resp|None, ErrorCodes)`, `check_endpoint(url) -> int` (HTTP status code, no timeout param — the adapter adds one via `asyncio.wait_for`); `ConfigPort` from Task 4.
- Produces: `LegacyTransportAdapter(config: ConfigPort)` implementing `TransportPort` exactly: `dispatch_action(action, params=None, timeout=60, retries=5)`, `dispatch_private(server_key, host, port, private_action, params_dict=None, json_dict=None, timeout=60, retries=5)`, `check_endpoint(url, timeout=3.0) -> bool`.

- [ ] **Step 1: Write the failing tests** — `helao/hexagon/tests/test_adapter_transport.py`:

```python
"""Transport adapter: ZMQ-first + HTTP-fallback wrap, and the MANDATORY
co-located RPC mirror (spec §7.1) verified against a REAL HelaoFastAPI —
fixture-fidelity rule §10.1: routes registered through the real registration
code, never hand-rolled fakes."""

import asyncio
import time

import pytest

from helao.hexagon.adapters.legacy.config import LegacyConfigAdapter
from helao.hexagon.adapters.legacy.transport import LegacyTransportAdapter
from helao.hexagon.ports.transport import TransportPort
from helao.core.error import ErrorCodes

HOST, PORT = "127.0.0.1", 8123  # RPC mirror -> 18123


def _world():
    return {
        "root": "/tmp/hex_t5",
        "dummy": True,
        "simulation": True,
        "servers": {
            "T5SRV": {"host": HOST, "port": PORT, "group": "action", "fast": "x"}
        },
    }


def test_transport_conformance():
    a = LegacyTransportAdapter(LegacyConfigAdapter(_world()))
    assert isinstance(a, TransportPort)


@pytest.mark.asyncio
async def test_check_endpoint_false_on_dead_peer():
    a = LegacyTransportAdapter(LegacyConfigAdapter(_world()))
    assert await a.check_endpoint(f"http://{HOST}:59998/nothing", timeout=1.0) is False


@pytest.mark.asyncio
async def test_private_dispatch_roundtrip_via_colocated_rpc():
    """Spin a REAL HelaoFastAPI (which auto-mirrors POST routes onto the
    ROUTER at http_port+10000), dispatch to it, and assert the fast path:
    a correct reply well under the 3 s probe timeout (the plain-FastAPI
    failure mode this contract exists to prevent — the operator
    blank-render incident, spec §7.1)."""
    import uvicorn
    from helao.helpers import config_loader

    world = _world()
    if config_loader.CONFIG is None:
        config_loader.install_global_config(world)

    from helao.helpers.server_api import HelaoFastAPI

    app = HelaoFastAPI(helao_srv="T5SRV", title="t5", description="", version="1")

    @app.post("/echo_probe")
    def echo_probe(value: int):
        return {"value": value, "server": "T5SRV"}

    cfg = uvicorn.Config(app, host=HOST, port=PORT, log_level="warning")
    server = uvicorn.Server(cfg)
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.1)
        assert server.started

        a = LegacyTransportAdapter(LegacyConfigAdapter(world))
        t0 = time.monotonic()
        resp, err = await a.dispatch_private(
            "T5SRV", HOST, PORT, "echo_probe", params_dict={"value": 7}
        )
        elapsed = time.monotonic() - t0
        assert err is ErrorCodes.none
        assert resp == {"value": 7, "server": "T5SRV"}
        assert elapsed < 2.5, (
            f"private dispatch took {elapsed:.2f}s — RPC mirror missing? "
            "(3 s probe timeout burned before HTTP fallback)"
        )
        assert await a.check_endpoint(f"http://{HOST}:{PORT}/echo_probe") is True
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=10)
        from helao.core.rpc.zmq_rpc import aclose_all_rpc_clients

        await aclose_all_rpc_clients()
```

Note: `pytest-asyncio` must be present in the helao env (`conda run -n helao python -c "import pytest_asyncio"`); if missing, `conda run -n helao pip install pytest-asyncio` and add `asyncio_mode = auto` is NOT set — keep explicit `@pytest.mark.asyncio`. Verify the teardown helper name with `grep -n "def aclose_all_rpc_clients" helao/core/rpc/zmq_rpc.py`; if it differs, use the actual exported teardown.

- [ ] **Step 2: Run to verify failure**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_adapter_transport.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'helao.hexagon.adapters.legacy.transport'`.

- [ ] **Step 3: Implement** — `helao/hexagon/adapters/legacy/transport.py`:

```python
"""TransportPort adapter (spec §4.3.5/§7): wraps the legacy dispatchers.

ZMQ-first RPC on derive_rpc_port(http_port)=http_port+10000 with the 3 s
probe timeout as down-detector, HTTP fallback with the legacy retry/backoff —
all inside helao.helpers.dispatcher; this adapter is thin delegation. The
co-located RPC SERVER side (ROUTER bind to the configured host with 0.0.0.0
fallback, commits 8dc8a0a8/7e737137) lives in HelaoFastAPI and is inherited
by every hexagon-composed app; test_adapter_transport pins the fast path.
NEVER self-RPC from inside the dispatch loop (KEEP #3) — the loop calls orch
methods directly; this adapter is for PEER dispatch only.
"""

import asyncio
from typing import Optional, Tuple

from helao.helpers.dispatcher import (
    async_action_dispatcher,
    async_private_dispatcher,
    check_endpoint,
)
from helao.hexagon.domain.models import Action, ErrorCodes
from helao.hexagon.ports.config import ConfigPort

__all__ = ["LegacyTransportAdapter"]


class LegacyTransportAdapter:
    def __init__(self, config: ConfigPort):
        self._config = config

    async def dispatch_action(
        self,
        action: Action,
        params: Optional[dict] = None,
        timeout: float = 60,
        retries: int = 5,
    ) -> Tuple[Optional[dict], ErrorCodes]:
        return await async_action_dispatcher(
            self._config.world_cfg(),
            action,
            params=params or {},
            timeout=timeout,
            retries=retries,
        )

    async def dispatch_private(
        self,
        server_key: str,
        host: str,
        port: int,
        private_action: str,
        params_dict: Optional[dict] = None,
        json_dict: Optional[dict] = None,
        timeout: float = 60,
        retries: int = 5,
    ) -> Tuple[Optional[dict], ErrorCodes]:
        return await async_private_dispatcher(
            server_key,
            host,
            port,
            private_action,
            params_dict or {},
            json_dict or {},
            timeout=timeout,
            retries=retries,
        )

    async def check_endpoint(self, url: str, timeout: float = 3.0) -> bool:
        try:
            code = await asyncio.wait_for(check_endpoint(url), timeout=timeout)
        except Exception:
            return False
        return 200 <= int(code) < 400
```

Verify the positional/keyword shape of `async_private_dispatcher` against `helao/helpers/dispatcher.py` (`grep -n "async def async_private_dispatcher" -A8 helao/helpers/dispatcher.py`) and match it exactly (params_dict/json_dict may be keyword-only).

- [ ] **Step 4: Run to verify pass**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_adapter_transport.py -q`
Expected: 3 PASS (the roundtrip test takes ~1-2 s). If the RPC roundtrip returns via HTTP fallback instead (elapsed ≥ 3 s), the RPC mirror did not bind — debug `HelaoFastAPI._rpc_startup` wiring before proceeding; do NOT relax the elapsed assertion.

- [ ] **Step 5: Pyright + commit**

```bash
conda run -n helao pyright helao/hexagon/adapters/legacy/transport.py   # expected: 0 errors
conda run -n helao black helao/hexagon/adapters/legacy/transport.py helao/hexagon/tests/test_adapter_transport.py
git add helao/hexagon/adapters/legacy/transport.py helao/hexagon/tests/test_adapter_transport.py
git commit -m "feat(hexagon): Transport legacy adapter + co-located RPC fast-path test (P1b1 T5)"
```

---

### Task 6: ArtifactStore + DataSink adapters

**Files:**
- Create: `helao/hexagon/adapters/legacy/artifact_store.py`
- Create: `helao/hexagon/adapters/legacy/data_sink.py`
- Test: `helao/hexagon/tests/test_adapters_data.py`

**Interfaces:**
- Consumes: legacy `Base.write_act/write_exp/write_seq` (async, same names); `Active` members `enqueue_data`, `enqueue_data_nowait`, `enqueue_data_dflt`, `get_realtime_nowait`, `finish_hlo_header` (SYNC on Active — wrapped async), `write_file`, `write_file_nowait`, `track_file`, `append_sample`, `split`, `set_estop`, `finish`, `substitute`; `Active.base.put_lbuf/put_lbuf_nowait/get_lbuf`; `helao.helpers.yml_tools.move_dir(hobj, base=None, retry_delay=5)`; `helao.helpers.file_utils.zip_dir(target_dir, filename)`.
- Produces:
  - `LegacyArtifactStoreAdapter(base, active=None)` implementing `ArtifactStorePort`; `for_action(active) -> LegacyArtifactStoreAdapter` (same base, bound Active). Stream/one-shot/finish members require the bound Active and raise `UnwiredPortError` otherwise.
  - `ActiveDataSinkAdapter(active)` implementing `DataSinkPort` (pure delegation; lbuf members via `active.base` — the ONE sanctioned reach-in, since the port exists to replace scattered reach-ins).
- **P1b1 runtime note (DD-7):** these adapters are built, conformance- and delegation-tested, and exposed on the wiring; the smoke's traffic still flows through legacy internals. Rerouting write paths is P1b2/P2 under the parity gate.

- [ ] **Step 1: Write the failing tests** — `helao/hexagon/tests/test_adapters_data.py`:

```python
"""ArtifactStore + DataSink adapters: Protocol conformance + verbatim
delegation onto recording stubs (real-Base/Active integration is exercised
by the Task 12 smoke through the launched group)."""

import asyncio

import pytest

from helao.hexagon.adapters.errors import UnwiredPortError
from helao.hexagon.adapters.legacy.artifact_store import LegacyArtifactStoreAdapter
from helao.hexagon.adapters.legacy.data_sink import ActiveDataSinkAdapter
from helao.hexagon.ports.artifact_store import ArtifactStorePort
from helao.hexagon.ports.data_sink import DataSinkPort


class _Rec:
    """Attribute-recording stand-in: every method records (name, args, kwargs)."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def _record(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if name in ("split",):
                return []
            return f"<{name}>"

        return _record


class _AsyncRec(_Rec):
    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        async def _record(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if name in ("split",):
                return []
            return f"<{name}>"

        return _record


class _StubActive(_AsyncRec):
    def __init__(self):
        super().__init__()
        self.base = _Rec()  # sync members: put_lbuf_nowait / get_lbuf / ...

    # sync-on-Active members the adapter must NOT await
    def enqueue_data_nowait(self, datamodel, action=None):
        self.calls.append(("enqueue_data_nowait", (datamodel, action), {}))

    def get_realtime_nowait(self, epoch_ns=None, offset=None):
        self.calls.append(("get_realtime_nowait", (epoch_ns, offset), {}))
        return 123

    def finish_hlo_header(self, file_conn_keys=None, realtime=None):
        self.calls.append(("finish_hlo_header", (file_conn_keys, realtime), {}))

    def write_file_nowait(self, *args, **kwargs):
        self.calls.append(("write_file_nowait", args, kwargs))
        return kwargs.get("filename")

    def set_estop(self, action=None):
        self.calls.append(("set_estop", (action,), {}))


def test_conformance():
    active = _StubActive()
    assert isinstance(ActiveDataSinkAdapter(active), DataSinkPort)
    assert isinstance(LegacyArtifactStoreAdapter(base=_AsyncRec()), ArtifactStorePort)


@pytest.mark.asyncio
async def test_data_sink_delegates_verbatim():
    active = _StubActive()
    sink = ActiveDataSinkAdapter(active)
    await sink.enqueue_data("dm")
    sink.enqueue_data_nowait("dm2")
    assert sink.get_realtime_nowait() == 123
    await sink.finish_hlo_header(file_conn_keys=None, realtime=9)
    sink.write_file_nowait("s", "t", filename="f.csv")
    sink.set_estop()
    await sink.append_sample(["smp"], IO="in")
    assert await sink.split() == []
    names = [c[0] for c in active.calls]
    assert names == [
        "enqueue_data",
        "enqueue_data_nowait",
        "get_realtime_nowait",
        "finish_hlo_header",
        "write_file_nowait",
        "set_estop",
        "append_sample",
        "split",
    ]


@pytest.mark.asyncio
async def test_data_sink_lbuf_routes_via_base():
    active = _StubActive()
    sink = ActiveDataSinkAdapter(active)
    sink.put_lbuf_nowait({"k": 1})
    sink.get_lbuf("k")
    assert [c[0] for c in active.base.calls] == ["put_lbuf_nowait", "get_lbuf"]


@pytest.mark.asyncio
async def test_artifact_store_meta_and_promotion_delegate():
    base = _AsyncRec()
    store = LegacyArtifactStoreAdapter(base=base)
    await store.write_act("A")
    await store.write_exp("E")
    await store.write_seq("S")
    assert [c[0] for c in base.calls] == ["write_act", "write_exp", "write_seq"]


@pytest.mark.asyncio
async def test_artifact_store_stream_members_require_bound_active():
    store = LegacyArtifactStoreAdapter(base=_AsyncRec())
    with pytest.raises(UnwiredPortError):
        await store.write_one_shot("A", "data", "csv__file", "f.csv", None)
    with pytest.raises(UnwiredPortError):
        await store.finish("A")


@pytest.mark.asyncio
async def test_artifact_store_bound_active_delegates():
    base, active = _AsyncRec(), _StubActive()
    store = LegacyArtifactStoreAdapter(base=base).for_action(active)
    await store.write_one_shot("A", "data", "csv__file", "f.csv", "h")
    await store.close_streams("A")   # -> Active.substitute (close-every-hlo)
    await store.finish("A")          # -> Active.finish (join-drain-close)
    names = [c[0] for c in active.calls]
    assert names == ["write_file", "substitute", "finish"]
```

- [ ] **Step 2: Run to verify failure**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_adapters_data.py -q`
Expected: FAIL — `ModuleNotFoundError` on both adapter modules.

- [ ] **Step 3: Implement**

`helao/hexagon/adapters/legacy/data_sink.py`:

```python
"""DataSinkPort adapter (spec §4.3.2): verbatim delegation onto a legacy
Active. Thread-safety contract rides on the wrapped members themselves
(the *_nowait members and get_realtime_nowait are the legacy thread-safe
surface the NI-DAQmx callback already uses). The lbuf members route via
active.base — the ONE sanctioned base reach-in; this port exists precisely
to replace the 72 scattered active.action / 18 full-Base reach-ins."""

from typing import List, Optional, Union
from uuid import UUID

from helao.hexagon.domain.models import (
    Action,
    DataModel,
    FileConnParams,
    HloFileGroup,
)

__all__ = ["ActiveDataSinkAdapter"]


class ActiveDataSinkAdapter:
    def __init__(self, active):
        self._active = active

    # --- data stream ---
    async def enqueue_data(self, datamodel: DataModel, action: Optional[Action] = None) -> None:
        await self._active.enqueue_data(datamodel, action)

    def enqueue_data_nowait(self, datamodel: DataModel, action: Optional[Action] = None) -> None:
        self._active.enqueue_data_nowait(datamodel, action)

    async def enqueue_data_dflt(self, datadict: dict) -> None:
        await self._active.enqueue_data_dflt(datadict)

    def get_realtime_nowait(
        self, epoch_ns: Optional[int] = None, offset: Optional[float] = None
    ) -> int:
        return self._active.get_realtime_nowait(epoch_ns, offset)

    async def finish_hlo_header(
        self,
        file_conn_keys: Optional[List[UUID]] = None,
        realtime: Optional[int] = None,
    ) -> None:
        # legacy Active.finish_hlo_header is sync (base.py:1091); the port is
        # async-first — plain call inside the coroutine keeps semantics.
        self._active.finish_hlo_header(file_conn_keys, realtime)

    # --- file output ---
    async def write_file(self, output_str, file_type, filename=None,
                         file_group=HloFileGroup.aux_files, header=None,
                         sample_str=None, file_sample_label=None,
                         json_data_keys=None, action=None):
        return await self._active.write_file(
            output_str, file_type, filename, file_group, header,
            sample_str, file_sample_label, json_data_keys, action,
        )

    def write_file_nowait(self, output_str, file_type, filename=None,
                          file_group=HloFileGroup.aux_files, header=None,
                          sample_str=None, file_sample_label=None,
                          json_data_keys=None, action=None):
        return self._active.write_file_nowait(
            output_str, file_type, filename=filename, file_group=file_group,
            header=header, sample_str=sample_str,
            file_sample_label=file_sample_label,
            json_data_keys=json_data_keys, action=action,
        )

    async def track_file(self, file_type, file_path, samples, action=None) -> None:
        await self._active.track_file(file_type, file_path, samples, action)

    # --- sample bookkeeping / lifecycle ---
    async def append_sample(self, samples, IO, action=None) -> None:
        await self._active.append_sample(samples, IO=IO, action=action)

    async def split(self, uuid_list=None,
                    new_fileconnparams: Optional[FileConnParams] = None):
        return await self._active.split(uuid_list, new_fileconnparams)

    def set_estop(self, action: Optional[Action] = None) -> None:
        self._active.set_estop(action)

    # --- live buffer (via active.base) ---
    async def put_lbuf(self, payload: dict) -> None:
        await self._active.base.put_lbuf(payload)

    def put_lbuf_nowait(self, payload: dict) -> None:
        self._active.base.put_lbuf_nowait(payload)

    def get_lbuf(self, key: str) -> tuple:
        return self._active.base.get_lbuf(key)
```

`helao/hexagon/adapters/legacy/artifact_store.py`:

```python
"""ArtifactStorePort adapter (spec §4.3.3): wraps the legacy writers.

Meta ymls delegate to Base.write_act/write_exp/write_seq (atomic tmp +
os.replace, file_type first key, trailing newline — all inside legacy
base_meta_writer). Streamed/one-shot/finish members delegate to a BOUND
legacy Active (per-action handle via for_action). write_data_line feeds the
legacy data queue (Active.enqueue_data with a DataModel keyed by
file_conn_key) so the parity-critical lazy-open / %% / hlo_json_dumps chain
runs UNMODIFIED legacy code; close_streams maps to Active.substitute (the
"close every open HLO file" legacy seam); finish maps to Active.finish
(join-drain-close protocol §5.4). Promotion/zip delegate to
yml_tools.move_dir / file_utils.zip_dir."""

from pathlib import Path
from typing import Optional
from uuid import UUID

from helao.helpers.file_utils import zip_dir
from helao.helpers.yml_tools import move_dir
from helao.hexagon.adapters.errors import UnwiredPortError
from helao.hexagon.domain.models import Action, DataModel, Experiment, Sequence

__all__ = ["LegacyArtifactStoreAdapter"]
```

**Boundary note (do this first, it matters):** adapters must NOT import `helao.hexagon.app` (Task 1 rule) — so `UnwiredPortError` cannot come from `app.wiring`. Define the exceptions in the adapters layer and re-export from `app/wiring.py`: create `helao/hexagon/adapters/errors.py`:

```python
"""Shared adapter-layer errors (importable by adapters AND app)."""

__all__ = ["HexagonDeferred", "UnwiredPortError"]


class UnwiredPortError(RuntimeError):
    """A consumed port/handle has no adapter wired — refuse to proceed."""


class HexagonDeferred(NotImplementedError):
    """A member whose legacy bridge is deliberately deferred to a later
    slice (documented at the raise site) — loud, never silent."""
```

then in `app/wiring.py` replace the two class definitions with `from helao.hexagon.adapters.errors import HexagonDeferred, UnwiredPortError` (keep both in `__all__` — the re-export keeps Task 3's tests green; this task's test file already imports from `adapters.errors`). Continue the adapter:

```python
class LegacyArtifactStoreAdapter:
    def __init__(self, base, active=None):
        self._base = base
        self._active = active

    def for_action(self, active) -> "LegacyArtifactStoreAdapter":
        """Per-action handle bound to a live legacy Active."""
        return LegacyArtifactStoreAdapter(self._base, active=active)

    def _require_active(self):
        if self._active is None:
            raise UnwiredPortError(
                "stream/one-shot/finish members need an Active-bound handle; "
                "use for_action(active)"
            )
        return self._active

    # --- meta ymls ---
    async def write_act(self, action: Action) -> None:
        await self._base.write_act(action)

    async def write_exp(self, experiment: Experiment) -> None:
        await self._base.write_exp(experiment)

    async def write_seq(self, sequence: Sequence) -> None:
        await self._base.write_seq(sequence)

    # --- streamed hlo ---
    async def write_data_line(
        self, action: Action, file_conn_key: UUID, payload: object
    ) -> None:
        active = self._require_active()
        # the legacy streaming seam: DataModel keyed by file_conn_key; the
        # legacy log_data_task performs lazy open + header + %% + json line
        await active.enqueue_data(
            DataModel(data={file_conn_key: payload}, errors=[]), action
        )

    async def close_streams(self, action: Action) -> None:
        await self._require_active().substitute()

    # --- one-shot ---
    async def write_one_shot(
        self,
        action: Action,
        output_str: str,
        file_type: str,
        filename: Optional[str],
        header: Optional[str],
    ) -> Optional[str]:
        return await self._require_active().write_file(
            output_str, file_type, filename, header=header, action=action
        )

    # --- finish + promotion ---
    async def finish(self, action: Action) -> None:
        await self._require_active().finish()

    async def move_dir(self, hobj: object) -> bool:
        return bool(await move_dir(hobj, base=self._base))

    async def zip_dir(self, dir_path: Path) -> Path:
        target = Path(dir_path)
        out = target.with_suffix(".zip")
        zip_dir(target, out)
        return out
```

Check `Active.write_file`'s positional order against `helao/core/servers/base.py:1251` before finalizing the `write_one_shot` call (header may be keyword-only relative to file_group); match the real signature, keep the test's expectation (`write_file` recorded once).

- [ ] **Step 4: Run everything to verify pass**

Run: `conda run -n helao python -m pytest helao/hexagon/tests -q`
Expected: all PASS (incl. Task 3's wiring tests via the re-export, and the boundary walk over the new modules — `adapters/errors.py` and both adapters import no `app.*`).

- [ ] **Step 5: Pyright + commit**

```bash
conda run -n helao pyright helao/hexagon/adapters/ helao/hexagon/app/wiring.py   # expected: 0 errors
conda run -n helao black helao/hexagon/adapters/errors.py helao/hexagon/adapters/legacy/artifact_store.py helao/hexagon/adapters/legacy/data_sink.py helao/hexagon/app/wiring.py helao/hexagon/tests/test_adapters_data.py helao/hexagon/tests/test_wiring.py
git add helao/hexagon/adapters/errors.py helao/hexagon/adapters/legacy/artifact_store.py helao/hexagon/adapters/legacy/data_sink.py helao/hexagon/app/wiring.py helao/hexagon/tests/test_adapters_data.py helao/hexagon/tests/test_wiring.py
git commit -m "feat(hexagon): ArtifactStore + DataSink legacy adapters (P1b1 T6)"
```

---

### Task 7: Sync, StatePersistence, Status, Hardware, SampleState adapters

**Files:**
- Create: `helao/hexagon/adapters/legacy/sync.py`
- Create: `helao/hexagon/adapters/legacy/state_persistence.py`
- Create: `helao/hexagon/adapters/legacy/status.py`
- Create: `helao/hexagon/adapters/legacy/hardware.py`
- Create: `helao/hexagon/adapters/legacy/sample_state.py`
- Test: `helao/hexagon/tests/test_adapters_misc.py`

**Interfaces:**
- Consumes: `HelaoSyncer` instance surface (`enqueue_yml`, `sync_yml`, `finish_pending`, `reset_sync` (SYNC in legacy), `to_s3`, `to_api`, `list_pending`, `task_queue.qsize()`); `queues.pck` file contract (`orch_persist.QueuePersister` shape: `STATES/queues.pck`, timestamped variant `queues_<%y%m%d.%H%M%S>.pck`, consumed-pck archived as `queues_imported_<ts>.pck`); `async_private_dispatcher` (Task 5 adapter reuses it; status adapter uses it directly); `helao.core.drivers.helao_driver.HelaoDriver`; `helao.deploy.hte.drivers.robot.sample_shim.SampleArchiveShim` (`unified_db` nested sub-client).
- Produces:
  - `LegacySyncAdapter(syncer)` implementing `SyncPort` (thin delegation; `reset_sync`/`list_pending` sync-in-async bridges; `n_queue() -> int` = `syncer.task_queue.qsize()`).
  - `QueuePckStore(root: str)` implementing `StatePersistencePort`: `export_queues(payload: dict, timestamp_pck: bool = False) -> Path`, `import_queues() -> Optional[dict]` (archives the consumed pck).
  - `DispatcherStatusAdapter(server_key: str)` implementing `StatusPort` push members over the real wire calls (`/update_status`, `/update_nonblocking`); `publish_*` raise `HexagonDeferred` (DD-7).
  - `LegacyDriverHardwareAdapter(driver: HelaoDriver)` implementing `HardwarePort` via `asyncio.to_thread` offload + `getattr` mapping (`arm→setup`, `start→measure`, `drain→get_data`, `abort→stop`).
  - `SampleShimAdapter(shim)` implementing `SampleStatePort` — the **flattening facade** (P1a carry-note): flat `get_samples/new_samples/update_samples` delegate to the shim's nested `.unified_db`.

- [ ] **Step 1: Write the failing tests** — `helao/hexagon/tests/test_adapters_misc.py`:

```python
"""Sync / StatePersistence / Status / Hardware / SampleState adapters."""

import asyncio
import pickle
from pathlib import Path

import pytest

from helao.core.drivers.helao_driver import DriverResponse, HelaoDriver
from helao.hexagon.adapters.errors import HexagonDeferred
from helao.hexagon.adapters.legacy.hardware import LegacyDriverHardwareAdapter
from helao.hexagon.adapters.legacy.sample_state import SampleShimAdapter
from helao.hexagon.adapters.legacy.state_persistence import QueuePckStore
from helao.hexagon.adapters.legacy.status import DispatcherStatusAdapter
from helao.hexagon.adapters.legacy.sync import LegacySyncAdapter
from helao.hexagon.ports.auxiliary import StatePersistencePort
from helao.hexagon.ports.hardware import HardwarePort
from helao.hexagon.ports.sample_state import SampleStatePort
from helao.hexagon.ports.status import StatusPort
from helao.hexagon.ports.sync import SyncPort


# --- Sync -------------------------------------------------------------------
class _StubSyncer:
    def __init__(self):
        self.calls = []

        class _Q:
            @staticmethod
            def qsize():
                return 3

        self.task_queue = _Q()

    async def enqueue_yml(self, upath, rank=0, rank_limit=-5):
        self.calls.append(("enqueue_yml", upath, rank, rank_limit))

    async def sync_yml(self, yml_path, retries=3, rank=5, force_s3=False,
                       force_api=False, compress=False):
        self.calls.append(("sync_yml", yml_path))
        return {"ok": True}

    async def finish_pending(self):
        self.calls.append(("finish_pending",))
        return []

    def reset_sync(self, sync_path):  # SYNC in legacy
        self.calls.append(("reset_sync", sync_path))
        return True

    async def to_s3(self, msg, target, retries=5, compress=False):
        self.calls.append(("to_s3", target))
        return True

    async def to_api(self, req_model, meta_type, retries=5):
        return True  # stub by decision (spec §1.3)

    def list_pending(self, omit_manual_exps=True):
        return ["p"]


@pytest.mark.asyncio
async def test_sync_adapter_delegates():
    stub = _StubSyncer()
    a = LegacySyncAdapter(stub)
    assert isinstance(a, SyncPort)
    await a.enqueue_yml("x.yml", rank=1)
    assert (await a.sync_yml(Path("y.yml"))) == {"ok": True}
    assert await a.reset_sync("z") is True
    assert a.list_pending() == ["p"]
    assert a.n_queue() == 3
    assert [c[0] for c in stub.calls] == ["enqueue_yml", "sync_yml", "reset_sync"]


# --- StatePersistence: the queues.pck file contract --------------------------
def test_queue_pck_roundtrip_and_consume_archive(tmp_path):
    (tmp_path / "STATES").mkdir()
    store = QueuePckStore(str(tmp_path))
    assert isinstance(store, StatePersistencePort)
    payload = {"seq": [1], "exp": [], "act": [], "globalstatusmodel": None}
    p = store.export_queues(payload)
    assert p == tmp_path / "STATES" / "queues.pck"
    assert pickle.load(open(p, "rb")) == payload
    out = store.import_queues()
    assert out == payload
    # consumed pck archived, not replayable (core-01 §2 rule)
    assert not p.exists()
    assert list((tmp_path / "STATES").glob("queues_imported_*.pck"))
    assert store.import_queues() is None


def test_queue_pck_timestamped_export(tmp_path):
    (tmp_path / "STATES").mkdir()
    p = QueuePckStore(str(tmp_path)).export_queues({"a": 1}, timestamp_pck=True)
    assert p.name.startswith("queues_") and p.name.endswith(".pck")
    assert p.name != "queues.pck"


# --- Status: wire-level push (publish_* deferred loudly) ----------------------
@pytest.mark.asyncio
async def test_status_conformance_and_deferred_publish():
    a = DispatcherStatusAdapter(server_key="ORCH")
    assert isinstance(a, StatusPort)
    with pytest.raises(HexagonDeferred):
        await a.publish_status({})


@pytest.mark.asyncio
async def test_status_attach_and_send_record_clients(monkeypatch):
    from helao.core.error import ErrorCodes

    sent = []

    async def _fake_dispatch(server_key, host, port, private_action,
                             params_dict, json_dict, timeout=60, retries=5):
        sent.append((server_key, host, port, private_action, params_dict, json_dict))
        return {}, ErrorCodes.none

    import helao.hexagon.adapters.legacy.status as status_mod

    monkeypatch.setattr(status_mod, "async_private_dispatcher", _fake_dispatch)
    a = DispatcherStatusAdapter(server_key="SIM")
    assert await a.attach_client("ORCH", "127.0.0.1", 8001) is True
    await a.send_nonblocking_status(
        "ORCH", "127.0.0.1", 8001, "SIM", "exec1", None, "finished"
    )
    assert sent[0][3] == "update_nonblocking"
    await a.detach_client("ORCH", "127.0.0.1", 8001)
    assert a.clients == []


# --- Hardware: HelaoDriver passthrough + disconnected construct ---------------
class _SimDriver(HelaoDriver):
    def __init__(self, config: dict = {}):
        super().__init__(config=config)
        self.calls = []

    def connect(self) -> DriverResponse:
        self.calls.append("connect")
        return DriverResponse()

    def get_status(self) -> DriverResponse:
        self.calls.append("get_status")
        return DriverResponse()

    def stop(self) -> DriverResponse:
        self.calls.append("stop")
        return DriverResponse()

    def reset(self) -> DriverResponse:
        self.calls.append("reset")
        return DriverResponse()

    def disconnect(self) -> DriverResponse:
        self.calls.append("disconnect")
        return DriverResponse()


@pytest.mark.asyncio
async def test_hardware_passthrough_and_mapping():
    drv = _SimDriver(config={})  # disconnected construct: no I/O in __init__
    a = LegacyDriverHardwareAdapter(drv)
    assert isinstance(a, HardwarePort)
    await a.connect()
    await a.get_status()
    await a.abort()      # -> legacy ABC stop()
    await a.reset()
    await a.disconnect()
    assert drv.calls == ["connect", "get_status", "stop", "reset", "disconnect"]
    with pytest.raises(AttributeError):
        await a.arm()    # _SimDriver has no setup(); fail loud, no silent no-op


# --- SampleState: flattening facade over the shim ------------------------------
class _StubUnifiedDB:
    def __init__(self, log):
        self._log = log

    async def get_samples(self, samples=None):
        self._log.append(("get_samples", samples))
        return ["g"]

    async def new_samples(self, samples=None):
        self._log.append(("new_samples", samples))
        return ["n"]

    async def update_samples(self, samples=None):
        self._log.append(("update_samples", samples))


class _StubShim:
    def __init__(self):
        self.log = []
        self.unified_db = _StubUnifiedDB(self.log)

    async def tray_query_sample(self, tray=None, slot=None, vial=None):
        self.log.append(("tray_query_sample", tray, slot, vial))
        return ("none", None)


@pytest.mark.asyncio
async def test_sample_state_flattens_unified_db():
    shim = _StubShim()
    a = SampleShimAdapter(shim)
    assert isinstance(a, SampleStatePort)
    assert await a.get_samples(["s"]) == ["g"]       # flat -> shim.unified_db
    assert await a.new_samples(["s"]) == ["n"]
    await a.update_samples(["s"])
    await a.tray_query_sample(tray=1)                 # 1:1 pass-through
    assert [e[0] for e in shim.log] == [
        "get_samples", "new_samples", "update_samples", "tray_query_sample",
    ]
```

- [ ] **Step 2: Run to verify failure**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_adapters_misc.py -q`
Expected: FAIL — `ModuleNotFoundError` on the five adapter modules.

- [ ] **Step 3: Implement the five adapters**

`helao/hexagon/adapters/legacy/sync.py`:

```python
"""SyncPort adapter (spec §4.3.4): thin delegation onto a live HelaoSyncer
(helao/core/drivers/data/sync_driver.py). All pipeline semantics (locks,
children gate, priority floor, process reconcile, .prg lifecycle) stay inside
the wrapped legacy driver. reset_sync/list_pending are sync in legacy —
bridged without behavior change."""

from pathlib import Path
from typing import Union

__all__ = ["LegacySyncAdapter"]


class LegacySyncAdapter:
    def __init__(self, syncer):
        self._syncer = syncer

    async def enqueue_yml(self, upath: Union[str, Path], rank: int = 0,
                          rank_limit: int = -5) -> None:
        await self._syncer.enqueue_yml(upath, rank=rank, rank_limit=rank_limit)

    async def sync_yml(self, yml_path: Path, retries: int = 3, rank: int = 5,
                       force_s3: bool = False, force_api: bool = False,
                       compress: bool = False) -> dict:
        return await self._syncer.sync_yml(
            yml_path, retries=retries, rank=rank, force_s3=force_s3,
            force_api=force_api, compress=compress,
        )

    async def finish_pending(self) -> list:
        return await self._syncer.finish_pending()

    async def reset_sync(self, sync_path: str) -> bool:
        return bool(self._syncer.reset_sync(sync_path))

    async def to_s3(self, msg, target: str, retries: int = 5,
                    compress: bool = False) -> bool:
        return await self._syncer.to_s3(msg, target, retries=retries,
                                        compress=compress)

    async def to_api(self, req_model: dict, meta_type: str,
                     retries: int = 5) -> bool:
        return await self._syncer.to_api(req_model, meta_type, retries=retries)

    def list_pending(self, omit_manual_exps: bool = True) -> list:
        return self._syncer.list_pending(omit_manual_exps=omit_manual_exps)

    def n_queue(self) -> int:
        return int(self._syncer.task_queue.qsize())
```

`helao/hexagon/adapters/legacy/state_persistence.py`:

```python
"""StatePersistencePort adapter: the queues.pck FILE contract (core-01 §2).

Reproduces orch_persist.QueuePersister's on-disk shape without holding an
orch back-reference (the port is payload-in/payload-out): STATES/queues.pck,
timestamped exports queues_<%y%m%d.%H%M%S>.pck, and the consumed-pck
archiving rule (a successfully imported queues.pck is renamed
queues_imported_<ts>.pck so hot-reload's unconditional --restore cannot
replay it). Building the payload from a live Orch stays the caller's job —
in P1b1 the ExportQueuesCmd effect delegates to orch.export_queues (the
wrapped legacy path); this adapter carries the contract for compositions
that have no legacy Orch (P2)."""

import os
import pickle
from datetime import datetime
from pathlib import Path
from typing import Optional

__all__ = ["QueuePckStore"]


class QueuePckStore:
    def __init__(self, root: str):
        self._states = Path(root) / "STATES"

    def export_queues(self, payload: dict, timestamp_pck: bool = False) -> Path:
        name = (
            f"queues_{datetime.now().strftime('%y%m%d.%H%M%S')}.pck"
            if timestamp_pck
            else "queues.pck"
        )
        path = self._states / name
        with open(path, "wb") as f:
            pickle.dump(payload, f)
        return path

    def import_queues(self) -> Optional[dict]:
        path = self._states / "queues.pck"
        if not path.exists():
            return None
        with open(path, "rb") as f:
            payload = pickle.load(f)
        archived = self._states / (
            f"queues_imported_{datetime.now().strftime('%y%m%d.%H%M%S')}.pck"
        )
        os.replace(path, archived)
        return payload
```

`helao/hexagon/adapters/legacy/status.py`:

```python
"""StatusPort adapter: wire-level status push over the legacy dispatcher.

Wraps the SAME wire calls base_status's broadcaster makes: private
/update_status (full/filtered ActionServerModel) and /update_nonblocking.
Keeps its own client registry (attach/detach). The WS publish_* members
(WsPublisher / _ws_relay zstd-pickle) are deliberately deferred (DD-7) —
they raise HexagonDeferred loudly; in the P1b1 wrapped-legacy composition
the live WS channels run on legacy Base relays."""

from typing import List, Tuple
from uuid import UUID

from helao.helpers.dispatcher import async_private_dispatcher
from helao.hexagon.adapters.errors import HexagonDeferred
from helao.hexagon.domain.models import ActionServerModel

__all__ = ["DispatcherStatusAdapter"]


class DispatcherStatusAdapter:
    def __init__(self, server_key: str):
        self._server_key = server_key
        self.clients: List[Tuple[str, str, int]] = []

    async def attach_client(self, client_servkey: str, client_host: str,
                            client_port: int, retry_limit: int = 5) -> bool:
        key = (client_servkey, client_host, client_port)
        if key not in self.clients:
            self.clients.append(key)
        return True

    async def detach_client(self, client_servkey: str, client_host: str,
                            client_port: int) -> None:
        try:
            self.clients.remove((client_servkey, client_host, client_port))
        except ValueError:
            pass  # legacy detach tolerates unknown clients

    async def send_status(self, asm: ActionServerModel, retries: int = 5) -> None:
        for client_servkey, host, port in list(self.clients):
            for _ in range(retries):
                resp, _err = await async_private_dispatcher(
                    client_servkey, host, port, "update_status",
                    {}, {"actionservermodel": asm.as_dict()},
                )
                if resp is not None:
                    break

    async def send_nonblocking_status(self, client_servkey: str,
                                      client_host: str, client_port: int,
                                      server_key: str, exec_id: str,
                                      act_uuid: UUID, status: str,
                                      retries: int = 3) -> None:
        for _ in range(retries):
            resp, _err = await async_private_dispatcher(
                client_servkey, client_host, client_port,
                "update_nonblocking",
                {
                    "server_key": server_key,
                    "executor_id": exec_id,
                    "action_uuid": str(act_uuid),
                    "status": status,
                },
                {},
            )
            if resp is not None:
                break

    async def publish_status(self, payload: dict) -> None:
        raise HexagonDeferred("WS publish bridge is P1b2 (DD-7)")

    async def publish_data(self, payload: dict) -> None:
        raise HexagonDeferred("WS publish bridge is P1b2 (DD-7)")

    async def publish_live(self, payload: dict) -> None:
        raise HexagonDeferred("WS publish bridge is P1b2 (DD-7)")
```

Before finalizing, check the real `/update_nonblocking` endpoint's parameter names (`grep -n "update_nonblocking" -A8 helao/core/servers/orch_api.py`) and use those exact keys in `params_dict`.

`helao/hexagon/adapters/legacy/hardware.py`:

```python
"""HardwarePort adapter (spec §4.3.1): HelaoDriver passthrough.

Wraps any legacy HelaoDriver with explicit thread offload (the ABC's sync
methods must never block the event loop). Lifecycle mapping uses the legacy
naming conventions (arm->setup, start->measure, drain->get_data,
abort->stop); a driver lacking a mapped method raises AttributeError at call
time — fail loud, never a silent no-op. Per-driver mapping refinement is P3
work; the disconnected-construct rule (no I/O in __init__) is the driver's
own contract, inherited unchanged."""

import asyncio

from helao.core.drivers.helao_driver import DriverResponse, HelaoDriver

__all__ = ["LegacyDriverHardwareAdapter"]

_METHOD_MAP = {
    "arm": ("setup",),
    "start": ("measure", "start_channel", "start"),
    "drain": ("get_data",),
    "abort": ("stop",),
    "cleanup": ("cleanup",),
    "estop": ("estop",),
    "shutdown": ("shutdown",),
}


class LegacyDriverHardwareAdapter:
    def __init__(self, driver: HelaoDriver):
        self._driver = driver

    def _resolve(self, port_name: str):
        for legacy_name in _METHOD_MAP[port_name]:
            fn = getattr(self._driver, legacy_name, None)
            if callable(fn):
                return fn
        raise AttributeError(
            f"{type(self._driver).__name__} has no legacy method for "
            f"'{port_name}' (tried {_METHOD_MAP[port_name]})"
        )

    async def connect(self) -> DriverResponse:
        return await asyncio.to_thread(self._driver.connect)

    async def get_status(self) -> DriverResponse:
        return await asyncio.to_thread(self._driver.get_status)

    async def arm(self, **setup_params) -> DriverResponse:
        return await asyncio.to_thread(self._resolve("arm"), **setup_params)

    async def start(self, **measure_params) -> DriverResponse:
        return await asyncio.to_thread(self._resolve("start"), **measure_params)

    async def drain(self, **kwargs) -> DriverResponse:
        return await asyncio.to_thread(self._resolve("drain"), **kwargs)

    async def abort(self, **kwargs) -> DriverResponse:
        return await asyncio.to_thread(self._resolve("abort"), **kwargs)

    async def cleanup(self, **kwargs) -> DriverResponse:
        return await asyncio.to_thread(self._resolve("cleanup"), **kwargs)

    async def reset(self) -> DriverResponse:
        return await asyncio.to_thread(self._driver.reset)

    async def disconnect(self) -> DriverResponse:
        return await asyncio.to_thread(self._driver.disconnect)

    async def estop(self, switch: bool) -> DriverResponse:
        return await asyncio.to_thread(self._resolve("estop"), switch)

    async def shutdown(self) -> DriverResponse:
        return await asyncio.to_thread(self._resolve("shutdown"))
```

`helao/hexagon/adapters/legacy/sample_state.py`:

```python
"""SampleStatePort adapter (spec §4.3.11): the SampleArchiveShim itself,
plus the FLATTENING facade (P1a review carry-note): the port is flat, but
the shim exposes get_samples/new_samples/update_samples on the nested
.unified_db sub-client — this adapter flattens that seam. Everything else is
1:1 pass-through of the shim's public methods."""

from typing import Any, List, Optional, Tuple

from helao.hexagon.domain.models import Action, ErrorCodes

__all__ = ["SampleShimAdapter"]


class SampleShimAdapter:
    def __init__(self, shim):
        self._shim = shim

    # -- tray --
    async def tray_query_sample(self, tray=None, slot=None, vial=None):
        return await self._shim.tray_query_sample(tray=tray, slot=slot, vial=vial)

    async def tray_get_next_full(self, after_tray=None, after_slot=None,
                                 after_vial=None):
        return await self._shim.tray_get_next_full(
            after_tray=after_tray, after_slot=after_slot, after_vial=after_vial
        )

    async def tray_new_position(self, req_vol: float = 2.0):
        return await self._shim.tray_new_position(req_vol=req_vol)

    async def tray_update_position(self, tray=None, slot=None, vial=None,
                                   sample=None, dilute: bool = False):
        return await self._shim.tray_update_position(
            tray=tray, slot=slot, vial=vial, sample=sample, dilute=dilute
        )

    # -- custom positions --
    async def custom_query_sample(self, custom=None):
        return await self._shim.custom_query_sample(custom=custom)

    async def custom_update_position(self, custom=None, sample=None,
                                     dilute: bool = False):
        return await self._shim.custom_update_position(
            custom=custom, sample=sample, dilute=dilute
        )

    async def custom_dest_allowed(self, custom=None):
        return await self._shim.custom_dest_allowed(custom=custom)

    async def custom_assembly_allowed(self, custom=None):
        return await self._shim.custom_assembly_allowed(custom=custom)

    async def custom_is_destroyed(self, custom=None):
        return await self._shim.custom_is_destroyed(custom=custom)

    # -- creation --
    async def new_ref_samples(self, samples_in=None, sample_out_type: Any = "",
                              sample_position: str = "",
                              action: Optional[Action] = None,
                              combine_liquids: bool = False,
                              combine_gases: bool = False):
        return await self._shim.new_ref_samples(
            samples_in=samples_in, sample_out_type=sample_out_type,
            sample_position=sample_position, action=action,
            combine_liquids=combine_liquids, combine_gases=combine_gases,
        )

    # -- FLATTENED unified_db sub-surface --
    async def get_samples(self, samples: Optional[list] = None) -> list:
        return await self._shim.unified_db.get_samples(samples=samples)

    async def new_samples(self, samples: Optional[list] = None) -> list:
        return await self._shim.unified_db.new_samples(samples=samples)

    async def update_samples(self, samples: Optional[list] = None) -> None:
        return await self._shim.unified_db.update_samples(samples=samples)
```

Boundary note: this adapter takes the shim as a constructor argument and does NOT import `helao.deploy.hte...` at module top (keeps the adapter importable without the hte tree; the composition that constructs the real shim lives in later phases). Verify the shim's exact keyword names against `helao/deploy/hte/drivers/robot/sample_shim.py` before finalizing.

- [ ] **Step 4: Run to verify pass**

Run: `conda run -n helao python -m pytest helao/hexagon/tests -q`
Expected: all PASS.

- [ ] **Step 5: Pyright + commit**

```bash
conda run -n helao pyright helao/hexagon/adapters/   # expected: 0 errors
conda run -n helao black helao/hexagon/adapters/legacy/ helao/hexagon/tests/test_adapters_misc.py
git add helao/hexagon/adapters/legacy/sync.py helao/hexagon/adapters/legacy/state_persistence.py helao/hexagon/adapters/legacy/status.py helao/hexagon/adapters/legacy/hardware.py helao/hexagon/adapters/legacy/sample_state.py helao/hexagon/tests/test_adapters_misc.py
git commit -m "feat(hexagon): Sync/StatePersistence/Status/Hardware/SampleState adapters (P1b1 T7)"
```

---

### Task 8: Orch effect runner (`app/orch_effects.py`)

**Files:**
- Create: `helao/hexagon/app/orch_effects.py`
- Test: `helao/hexagon/tests/test_orch_effects.py`

**Interfaces:**
- Consumes: the P1a reducer's `Command` union (`helao.hexagon.domain.orchestration`, exact members listed in its `__all__`); `DispatchPolicy.evaluate_step_thru`, `should_close_out_experiment(n_acts, active_exp_present, loop_state)`, `should_close_out_sequence(n_exps, n_acts, active_seq_present, loop_state)` from `helao.hexagon.domain.dispatch_policy`; the legacy `Orch` surface (verified against `helao/core/servers/orch.py` + `orch_dispatch.py`): `globalstatusmodel.{loop_state,loop_intent,orch_state,clear_in_finished(hlostatus=...)}`, `action_dq/experiment_dq/sequence_dq`, `active_experiment/active_sequence`, `active_run_id`, `status_summary` (`{key: (ts, "unknown"|...)}`), `step_thru_*`, `current_stop_message`, `last_dispatched_action_uuid`, `action_history` (DequeDict), `interrupt_q`, and the async methods `loop_task_dispatch_action/experiment/sequence`, `finish_active_experiment/sequence`, `orch_wait_for_all_actions`, `intend_stop/skip/estop/none`, `estop_actions(switch)`, `estop_finish_active`, `stop()`, plus sync `export_queues(timestamp_pck)`; `LoggingPort` (Task 4) for `AlertOperator`.
- Produces (used by Task 9):
  - `derive_state(orch) -> OrchestrationState` — fresh live snapshot.
  - `async apply_state_delta(orch, old, new, *, skip_loop_state=False) -> None` — DD-2 rules.
  - `class OrchCommandRunner(orch, wiring: PortWiring)` with `async execute(cmd) -> Optional[ErrorCodes]` — one branch per reducer command, thin legacy delegation, live re-checks per DD-3.

- [ ] **Step 1: Write the failing tests** — `helao/hexagon/tests/test_orch_effects.py`:

```python
"""Effect runner: reducer commands -> thin legacy delegation, DD-2 delta
rules, DD-3 live re-checks. Uses a recording stub orch (app-layer unit
tests; the launched smoke exercises the real Orch)."""

import asyncio
from types import SimpleNamespace

import pytest

from helao.core.error import ErrorCodes
from helao.hexagon.adapters.fakes import FakeClock  # noqa: F401 (banner sanity)
from helao.hexagon.app.orch_effects import (
    OrchCommandRunner,
    apply_state_delta,
    derive_state,
)
from helao.hexagon.app.wiring import PortWiring
from helao.hexagon.domain.models import HloStatus, LoopIntent, LoopStatus, OrchStatus
from helao.hexagon.domain.orchestration import (
    AlertOperator,
    ClearActionQueue,
    ClearActiveRunId,
    ClearEstoppedFromFinished,
    CloseOutExperimentCmd,
    DispatchHeadAction,
    EstopFanout,
    ExportQueuesCmd,
    FinishActiveEstopped,
    FinishThenDispatchExperimentCmd,
    InterruptWake,
    OrchestrationState,
    RequeueHeadAction,
    SetStopMessage,
    WaitAllActionsIdle,
)


class _GSM:
    def __init__(self):
        self.loop_state = LoopStatus.stopped
        self.loop_intent = LoopIntent.none
        self.orch_state = OrchStatus.idle
        self.cleared = []

    def clear_in_finished(self, hlostatus):
        self.cleared.append(hlostatus)


class _StubOrch:
    """Records every effect; async methods mirror the legacy Orch surface."""

    def __init__(self):
        self.globalstatusmodel = _GSM()
        self.action_dq, self.experiment_dq, self.sequence_dq = [], [], []
        self.active_experiment = None
        self.active_sequence = None
        self.active_run_id = "RUN"
        self.status_summary = {}
        self.step_thru_actions = False
        self.step_thru_experiments = False
        self.step_thru_sequences = False
        self.current_stop_message = ""
        self.last_dispatched_action_uuid = "u1"
        self.action_history = {"u1": {}}
        self.interrupt_q = asyncio.Queue()
        self.calls = []
        self.dispatch_rc = ErrorCodes.none

    async def loop_task_dispatch_action(self):
        self.calls.append("loop_task_dispatch_action")
        return self.dispatch_rc

    async def loop_task_dispatch_experiment(self):
        self.calls.append("loop_task_dispatch_experiment")
        return ErrorCodes.none

    async def loop_task_dispatch_sequence(self):
        self.calls.append("loop_task_dispatch_sequence")
        return ErrorCodes.none

    async def finish_active_experiment(self):
        self.calls.append("finish_active_experiment")

    async def finish_active_sequence(self):
        self.calls.append("finish_active_sequence")

    async def orch_wait_for_all_actions(self):
        self.calls.append("orch_wait_for_all_actions")
        self.globalstatusmodel.orch_state = OrchStatus.idle

    async def intend_stop(self):
        self.calls.append("intend_stop")
        self.globalstatusmodel.loop_intent = LoopIntent.stop
        await self.interrupt_q.put("stop")

    async def intend_skip(self):
        self.calls.append("intend_skip")
        self.globalstatusmodel.loop_intent = LoopIntent.skip
        await self.interrupt_q.put("skip")

    async def intend_estop(self):
        self.calls.append("intend_estop")
        self.globalstatusmodel.loop_intent = LoopIntent.estop
        await self.interrupt_q.put("estop")

    async def intend_none(self):
        self.calls.append("intend_none")
        self.globalstatusmodel.loop_intent = LoopIntent.none
        await self.interrupt_q.put("none")

    async def estop_actions(self, switch: bool):
        self.calls.append(f"estop_actions:{switch}")

    async def estop_finish_active(self):
        self.calls.append("estop_finish_active")

    async def stop(self, reset_run_id: bool = False):
        self.calls.append("stop")

    def export_queues(self, timestamp_pck: bool = False):
        self.calls.append(f"export_queues:{timestamp_pck}")
        return "/tmp/queues.pck"


class _AlertSpy:
    def __init__(self):
        self.alerts = []

    def info(self, m): ...
    def warning(self, m): ...
    def error(self, m, exc_info=False): ...

    def alert(self, m):
        self.alerts.append(m)

    def file_logger(self, server_key, log_root):
        raise AssertionError("unused")


def _runner(orch):
    spy = _AlertSpy()
    return OrchCommandRunner(orch, PortWiring(logging=spy)), spy


# --- derive_state -------------------------------------------------------------
def test_derive_state_reads_live_values():
    orch = _StubOrch()
    orch.action_dq = ["a"]
    orch.status_summary = {"PSTAT": (0.0, "unknown"), "MOTOR": (0.0, "ok")}
    orch.globalstatusmodel.loop_state = LoopStatus.started
    s = derive_state(orch)
    assert (s.n_acts, s.n_exps, s.n_seqs) == (1, 0, 0)
    assert s.na_drivers == ("PSTAT",)
    assert s.loop_state == LoopStatus.started


# --- apply_state_delta (DD-2) ---------------------------------------------------
@pytest.mark.asyncio
async def test_delta_routes_intent_through_legacy_intenders():
    orch = _StubOrch()
    old = derive_state(orch)
    new = OrchestrationState(loop_state=old.loop_state, loop_intent=LoopIntent.stop)
    await apply_state_delta(orch, old, new)
    assert "intend_stop" in orch.calls
    assert orch.interrupt_q.qsize() == 1  # wake preserved


@pytest.mark.asyncio
async def test_delta_never_clobbers_concurrent_estop():
    orch = _StubOrch()
    orch.globalstatusmodel.loop_state = LoopStatus.started
    old = derive_state(orch)  # sampled while started
    orch.globalstatusmodel.loop_state = LoopStatus.estopped  # concurrent E-STOP
    new = OrchestrationState(loop_state=LoopStatus.stopped)
    await apply_state_delta(orch, old, new)
    assert orch.globalstatusmodel.loop_state == LoopStatus.estopped  # preserved


@pytest.mark.asyncio
async def test_delta_t10_may_leave_estop():
    orch = _StubOrch()
    orch.globalstatusmodel.loop_state = LoopStatus.estopped
    old = derive_state(orch)  # input state IS estopped -> T10 transition
    new = OrchestrationState(loop_state=LoopStatus.stopped)
    await apply_state_delta(orch, old, new)
    assert orch.globalstatusmodel.loop_state == LoopStatus.stopped


@pytest.mark.asyncio
async def test_delta_t5_exception_skips_loop_state():
    orch = _StubOrch()
    orch.globalstatusmodel.loop_state = LoopStatus.started
    old = derive_state(orch)
    new = OrchestrationState(loop_state=LoopStatus.stopped)
    await apply_state_delta(orch, old, new, skip_loop_state=True)
    assert orch.globalstatusmodel.loop_state == LoopStatus.started  # drain body owns it


# --- OrchCommandRunner ----------------------------------------------------------
@pytest.mark.asyncio
async def test_dispatch_head_action_happy_path():
    orch = _StubOrch()
    runner, _ = _runner(orch)
    rc = await runner.execute(DispatchHeadAction())
    assert rc is ErrorCodes.none
    assert orch.calls == ["loop_task_dispatch_action"]


@pytest.mark.asyncio
async def test_dispatch_head_action_live_recheck_bails_under_estop():
    orch = _StubOrch()
    orch.globalstatusmodel.loop_state = LoopStatus.estopped
    runner, _ = _runner(orch)
    rc = await runner.execute(DispatchHeadAction())
    assert rc is ErrorCodes.estop
    assert orch.calls == []  # never dispatched


@pytest.mark.asyncio
async def test_finish_then_dispatch_exp_recheck_and_order():
    orch = _StubOrch()
    runner, _ = _runner(orch)
    rc = await runner.execute(FinishThenDispatchExperimentCmd())
    assert rc is ErrorCodes.none
    assert orch.calls == ["finish_active_experiment", "loop_task_dispatch_experiment"]
    orch2 = _StubOrch()
    orch2.globalstatusmodel.loop_state = LoopStatus.estopped
    runner2, _ = _runner(orch2)
    assert (await runner2.execute(FinishThenDispatchExperimentCmd())) is ErrorCodes.estop
    assert orch2.calls == []  # estop_finish_active stays SOLE finalizer


@pytest.mark.asyncio
async def test_close_out_experiment_guard_rechecked_live():
    orch = _StubOrch()
    orch.active_experiment = object()
    runner, _ = _runner(orch)
    await runner.execute(CloseOutExperimentCmd())
    assert orch.calls == ["finish_active_experiment"]
    orch2 = _StubOrch()
    orch2.active_experiment = object()
    orch2.globalstatusmodel.loop_state = LoopStatus.estopped  # live re-check #3
    runner2, _ = _runner(orch2)
    await runner2.execute(CloseOutExperimentCmd())
    assert orch2.calls == []


@pytest.mark.asyncio
async def test_estop_cascade_commands():
    orch = _StubOrch()
    runner, spy = _runner(orch)
    await runner.execute(ClearActiveRunId())
    assert orch.active_run_id is None
    await runner.execute(EstopFanout(switch=False))
    await runner.execute(FinishActiveEstopped())
    await runner.execute(SetStopMessage(message="E-STOP unit"))
    await runner.execute(AlertOperator(message="E-STOP unit"))
    assert orch.calls == ["estop_actions:False", "estop_finish_active"]
    assert orch.current_stop_message == "E-STOP unit"
    assert spy.alerts == ["E-STOP unit"]  # AlertOperator consumes the Logging PORT


@pytest.mark.asyncio
async def test_wait_all_actions_idle_drain_owns_stop_write():
    orch = _StubOrch()
    orch.globalstatusmodel.loop_state = LoopStatus.started
    runner, _ = _runner(orch)
    await runner.execute(WaitAllActionsIdle())
    assert orch.globalstatusmodel.loop_state == LoopStatus.stopped
    assert "orch_wait_for_all_actions" in orch.calls
    assert "intend_none" in orch.calls


@pytest.mark.asyncio
async def test_misc_effects():
    orch = _StubOrch()
    orch.action_dq = ["a", "b"]
    orch.sequence_dq = ["s"]
    runner, _ = _runner(orch)
    await runner.execute(ClearActionQueue())
    assert orch.action_dq == []
    await runner.execute(ExportQueuesCmd(timestamped=True))
    assert "export_queues:True" in orch.calls
    await runner.execute(ClearEstoppedFromFinished())
    assert orch.globalstatusmodel.cleared == [HloStatus.estopped]
    await runner.execute(InterruptWake(message="cleared_estop"))
    assert orch.interrupt_q.qsize() == 1
    # RequeueHeadAction is unreachable in P1b1 (DD-4): logged, not executed
    await runner.execute(RequeueHeadAction())
    assert orch.action_dq == []
```

- [ ] **Step 2: Run to verify failure**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_orch_effects.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'helao.hexagon.app.orch_effects'`.

- [ ] **Step 3: Implement** — `helao/hexagon/app/orch_effects.py`:

```python
"""Reducer-command effect runner over a wrapped legacy Orch (P1b1 DD-1..DD-5).

Every effect is THIN DELEGATION onto the legacy Orch surface (behavior
identical by construction); the five marked commands re-read live state
immediately before executing (DD-3, spec §4.2.2 option (a)) — the same three
guard sites orch_dispatch.py carries. State deltas follow DD-2. Never issues
an RPC/HTTP call to its own server (KEEP #3)."""

import asyncio
import logging
from typing import Optional

from helao.hexagon.app.wiring import PortWiring
from helao.hexagon.domain.dispatch_policy import (
    DispatchPolicy,
    should_close_out_experiment,
    should_close_out_sequence,
)
from helao.hexagon.domain.models import (
    ErrorCodes,
    HloStatus,
    LoopIntent,
    LoopStatus,
    OrchStatus,
)
from helao.hexagon.domain.orchestration import (
    AlertOperator,
    ClearActionQueue,
    ClearActiveRunId,
    ClearErroredFromFinished,
    ClearEstoppedFromFinished,
    CloseOutExperimentCmd,
    CloseOutSequenceCmd,
    Command,
    CreateDispatchLoopTask,
    DispatchHeadAction,
    EstopFanout,
    ExportQueuesCmd,
    FinishActiveEstopped,
    FinishThenDispatchExperimentCmd,
    FinishThenDispatchSequenceCmd,
    InterruptWake,
    OrchestrationState,
    RefuseStart,
    ReleaseServersEstop,
    RequeueHeadAction,
    RetryDriverHealth,
    SetStopMessage,
    WaitAllActionsIdle,
)

LOGGER = logging.getLogger(__name__)

__all__ = ["OrchCommandRunner", "apply_state_delta", "derive_state"]


def derive_state(orch) -> OrchestrationState:
    """Fresh live snapshot (call-time state resolution, DD-2)."""
    gsm = orch.globalstatusmodel
    return OrchestrationState(
        loop_state=gsm.loop_state,
        loop_intent=gsm.loop_intent,
        orch_state=gsm.orch_state,
        n_seqs=len(orch.sequence_dq),
        n_exps=len(orch.experiment_dq),
        n_acts=len(orch.action_dq),
        active_experiment_present=orch.active_experiment is not None,
        active_sequence_present=orch.active_sequence is not None,
        na_drivers=tuple(
            k for k, (_, v) in orch.status_summary.items() if v == "unknown"
        ),
        step_thru_actions=orch.step_thru_actions,
        step_thru_experiments=orch.step_thru_experiments,
        step_thru_sequences=orch.step_thru_sequences,
    )


async def apply_state_delta(
    orch,
    old: OrchestrationState,
    new: OrchestrationState,
    *,
    skip_loop_state: bool = False,
) -> None:
    """DD-2: state-first delta. loop_state guarded against concurrent E-STOP
    (only a transition whose INPUT state was estopped — T10 — may overwrite a
    live estopped value); T5 exception via skip_loop_state; loop_intent routed
    through the legacy intend_* methods (interrupt_q wake preserved);
    orch_state deliberately NOT written back (legacy ingester owns it)."""
    gsm = orch.globalstatusmodel
    if not skip_loop_state and new.loop_state != old.loop_state:
        live = gsm.loop_state
        if live == LoopStatus.estopped and old.loop_state != LoopStatus.estopped:
            LOGGER.info("concurrent E-STOP observed; loop_state write suppressed")
        else:
            gsm.loop_state = new.loop_state
    if new.loop_intent != old.loop_intent:
        intender = {
            LoopIntent.stop: orch.intend_stop,
            LoopIntent.skip: orch.intend_skip,
            LoopIntent.estop: orch.intend_estop,
            LoopIntent.none: orch.intend_none,
        }[new.loop_intent]
        await intender()


class OrchCommandRunner:
    def __init__(self, orch, wiring: PortWiring):
        self.orch = orch
        self.wiring = wiring
        self.policy = DispatchPolicy()

    async def execute(self, cmd: Command) -> Optional[ErrorCodes]:
        orch = self.orch
        gsm = orch.globalstatusmodel

        if isinstance(cmd, CreateDispatchLoopTask):
            return None  # owned by HexRuntime (wakes the parked loop task)

        if isinstance(cmd, RefuseStart):
            LOGGER.info(cmd.reason)
            return None

        if isinstance(cmd, DispatchHeadAction):
            # live re-check #1 (outer twin of the in-lock guard the wrapped
            # _dispatch_action_locked already carries)
            if gsm.loop_state == LoopStatus.estopped:
                return ErrorCodes.estop
            rc = await orch.loop_task_dispatch_action()
            # history poll (orch_dispatch.py:621-622) — ingestion registers
            # the uuid; the heartbeat monitor is the only exit on a dead peer
            while orch.last_dispatched_action_uuid not in orch.action_history.keys():
                await asyncio.sleep(0.2)
            pause = self.policy.evaluate_step_thru(derive_state(orch).snapshot())
            if pause is not None:
                orch.current_stop_message = pause.reason
                LOGGER.warning(pause.reason)
                await orch.stop()
            return rc

        if isinstance(cmd, FinishThenDispatchExperimentCmd):
            if gsm.loop_state == LoopStatus.estopped:  # live re-check #2
                LOGGER.info(
                    "orchestrator estopped, not finishing/dispatching experiment"
                )
                return ErrorCodes.estop
            LOGGER.info("finishing last experiment")
            await orch.finish_active_experiment()
            LOGGER.info("!!!dispatching next experiment")
            return await orch.loop_task_dispatch_experiment()

        if isinstance(cmd, FinishThenDispatchSequenceCmd):
            if gsm.loop_state == LoopStatus.estopped:  # live re-check #2
                LOGGER.info(
                    "orchestrator estopped, not finishing/dispatching sequence"
                )
                return ErrorCodes.estop
            LOGGER.info("finishing last sequence")
            await orch.finish_active_sequence()
            LOGGER.info("!!!dispatching next sequence")
            return await orch.loop_task_dispatch_sequence()

        if isinstance(cmd, RetryDriverHealth):
            # verbatim orch_dispatch._exec_driver_health (<=5 x 5 s)
            na_drivers = list(cmd.na_drivers)
            retries = 0
            while retries < 5 and na_drivers:
                LOGGER.info(
                    f"unknown driver states: {', '.join(na_drivers)}, "
                    "retrying in 5 seconds"
                )
                await asyncio.sleep(5)
                na_drivers = [
                    k
                    for k, (_, v) in orch.status_summary.items()
                    if v == "unknown"
                ]
                retries += 1
            if na_drivers:
                orch.current_stop_message = (
                    f"unknown driver states: {', '.join(na_drivers)}"
                )
                LOGGER.warning(orch.current_stop_message)
                await orch.stop()
            return None

        if isinstance(cmd, WaitAllActionsIdle):
            # verbatim DrainForStop body — OWNS the stopped write (DD-2 T5)
            LOGGER.info("stopping orchestrator")
            while gsm.loop_state != LoopStatus.stopped:
                await orch.orch_wait_for_all_actions()
                if gsm.orch_state == OrchStatus.idle:
                    await orch.intend_none()
                    LOGGER.info("got stop")
                    gsm.loop_state = LoopStatus.stopped
                    break
            return None

        if isinstance(cmd, RequeueHeadAction):
            # DD-4: unreachable in P1b1 (requeue lives inside the wrapped
            # dispatch fold); executing would double-insert — log loudly.
            LOGGER.warning(
                "RequeueHeadAction ignored in P1b1 wrapped-legacy composition"
            )
            return None

        if isinstance(cmd, ClearActionQueue):
            orch.action_dq.clear()
            return None

        if isinstance(cmd, SetStopMessage):
            orch.current_stop_message = cmd.message
            return None

        if isinstance(cmd, AlertOperator):
            self.wiring.require("logging")
            LOGGER.warning(cmd.message)
            self.wiring.logging.alert(cmd.message)  # type: ignore[union-attr]
            return None

        if isinstance(cmd, EstopFanout):
            await orch.estop_actions(switch=cmd.switch)
            return None

        if isinstance(cmd, ClearActiveRunId):
            orch.active_run_id = None
            return None

        if isinstance(cmd, FinishActiveEstopped):
            try:
                await orch.estop_finish_active()
            except Exception:
                LOGGER.error(
                    "error finalizing estopped experiment/sequence", exc_info=True
                )
            return None

        if isinstance(cmd, CloseOutExperimentCmd):
            if should_close_out_experiment(  # live re-check #3
                len(orch.action_dq),
                orch.active_experiment is not None,
                gsm.loop_state,
            ):
                LOGGER.info("finishing final experiment")
                await orch.finish_active_experiment()
            return None

        if isinstance(cmd, CloseOutSequenceCmd):
            if should_close_out_sequence(  # live re-check #3
                len(orch.experiment_dq),
                len(orch.action_dq),
                orch.active_sequence is not None,
                gsm.loop_state,
            ):
                LOGGER.info("finishing final sequence")
                await orch.finish_active_sequence()
            return None

        if isinstance(cmd, ExportQueuesCmd):
            if any(
                len(x) > 0
                for x in (orch.sequence_dq, orch.experiment_dq, orch.action_dq)
            ):
                orch.export_queues(timestamp_pck=cmd.timestamped)
            return None

        if isinstance(cmd, ClearEstoppedFromFinished):
            gsm.clear_in_finished(hlostatus=HloStatus.estopped)
            return None

        if isinstance(cmd, ClearErroredFromFinished):
            gsm.clear_in_finished(hlostatus=HloStatus.errored)
            return None

        if isinstance(cmd, ReleaseServersEstop):
            await orch.estop_actions(switch=False)
            return None

        if isinstance(cmd, InterruptWake):
            await orch.interrupt_q.put(cmd.message)
            return None

        raise AssertionError(f"unhandled reducer command: {cmd!r}")
```

- [ ] **Step 4: Run to verify pass**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_orch_effects.py helao/hexagon/tests/test_boundaries.py -q`
Expected: all PASS.

- [ ] **Step 5: Pyright + commit**

```bash
conda run -n helao pyright helao/hexagon/app/orch_effects.py   # expected: 0 errors
conda run -n helao black helao/hexagon/app/orch_effects.py helao/hexagon/tests/test_orch_effects.py
git add helao/hexagon/app/orch_effects.py helao/hexagon/tests/test_orch_effects.py
git commit -m "feat(hexagon): reducer-command effect runner over legacy Orch (P1b1 T8)"
```

---

### Task 9: Single-drainer dispatch loop + graft (`app/dispatch_loop.py`)

**Files:**
- Create: `helao/hexagon/app/dispatch_loop.py`
- Test: `helao/hexagon/tests/test_dispatch_loop.py`

**Interfaces:**
- Consumes: `step`, the event dataclasses (`StartRequested`, `StopRequested`, `SkipRequested`, `EstopRequested`, `ClearEstopRequested`, `ClearErrorRequested`, `LoopIterate`, `UncaughtLoopException`), and `CreateDispatchLoopTask`/`RetryDriverHealth` from `helao.hexagon.domain.orchestration`; `DispatchPolicy`/`ExitLoop` from `helao.hexagon.domain.dispatch_policy`; Task 8's `derive_state`, `apply_state_delta`, `OrchCommandRunner`; `PortWiring`.
- Produces (used by Task 10):
  - `class HexRuntime(orch, effects)` — `loop_wake: asyncio.Event`; `async handle(event) -> ErrorCodes` (reducer + DD-2 delta + command execution + legacy `_loop` error epilogue; reentrant, callable from any task for control events — DD-3).
  - `class HexDispatchLoop(runtime)` — `start()`, `async close()`, `async run_forever()`; the ONLY invoker of `handle(LoopIterate())`.
  - `graft_hexagon_loop(orch, wiring) -> HexagonGraft` — rebinds `start/start_loop/stop/skip/estop_loop/clear_estop/clear_error` on the live legacy `Orch` instance and starts the loop task; `HexagonGraft` dataclass exposes `runtime`, `loop`, `effects`, `originals: dict`.

- [ ] **Step 1: Write the failing tests** — `helao/hexagon/tests/test_dispatch_loop.py`:

```python
"""Single-drainer loop: park/unpark, ladder-to-park mini-run, refusals,
estop funnel + race seed (DD-3), graft rebinding. Uses the Task 8 stub orch
extended with a scripted dispatch that drains its own queues."""

import asyncio

import pytest

from helao.core.error import ErrorCodes
from helao.hexagon.app.dispatch_loop import HexDispatchLoop, HexRuntime, graft_hexagon_loop
from helao.hexagon.app.orch_effects import OrchCommandRunner, derive_state
from helao.hexagon.app.wiring import PortWiring
from helao.hexagon.domain.models import LoopIntent, LoopStatus, OrchStatus
from helao.hexagon.domain.orchestration import StartRequested

from helao.hexagon.tests.test_orch_effects import _AlertSpy, _StubOrch


class _ScriptedOrch(_StubOrch):
    """Dispatch effects consume the scripted queues so a run drains."""

    def __init__(self, n_acts=2, n_exps=1, n_seqs=1):
        super().__init__()
        self.action_dq = [f"a{i}" for i in range(n_acts)]
        self.experiment_dq = [f"e{i}" for i in range(n_exps)]
        self.sequence_dq = [f"s{i}" for i in range(n_seqs)]
        self.block_dispatch = None  # optional asyncio.Event to stall mid-effect

    async def loop_task_dispatch_action(self):
        self.calls.append("loop_task_dispatch_action")
        if self.block_dispatch is not None:
            await self.block_dispatch.wait()
        self.action_dq.pop(0)
        return ErrorCodes.none

    async def loop_task_dispatch_experiment(self):
        self.calls.append("loop_task_dispatch_experiment")
        self.experiment_dq.pop(0)
        self.active_experiment = object()
        self.action_dq.append("a_from_exp")
        return ErrorCodes.none

    async def loop_task_dispatch_sequence(self):
        self.calls.append("loop_task_dispatch_sequence")
        self.sequence_dq.pop(0)
        self.active_sequence = object()
        self.experiment_dq.append("e_from_seq")
        return ErrorCodes.none

    async def finish_active_experiment(self):
        self.calls.append("finish_active_experiment")
        self.active_experiment = None

    async def finish_active_sequence(self):
        self.calls.append("finish_active_sequence")
        self.active_sequence = None


def _make(orch):
    runtime = HexRuntime(orch, OrchCommandRunner(orch, PortWiring(logging=_AlertSpy())))
    loop = HexDispatchLoop(runtime)
    return runtime, loop


@pytest.mark.asyncio
async def test_start_with_empty_queues_refuses_and_stays_parked():
    orch = _ScriptedOrch(n_acts=0, n_exps=0, n_seqs=0)
    runtime, loop = _make(orch)
    loop.start()
    await runtime.handle(StartRequested())
    await asyncio.sleep(0.05)
    assert orch.globalstatusmodel.loop_state == LoopStatus.stopped
    assert orch.calls == []  # nothing dispatched
    await loop.close()


@pytest.mark.asyncio
async def test_full_mini_run_drains_and_parks():
    orch = _ScriptedOrch(n_acts=1, n_exps=1, n_seqs=1)
    runtime, loop = _make(orch)
    loop.start()
    await runtime.handle(StartRequested())
    for _ in range(200):  # ~2 s budget
        if orch.globalstatusmodel.loop_state == LoopStatus.stopped and not (
            orch.action_dq or orch.experiment_dq or orch.sequence_dq
        ):
            break
        await asyncio.sleep(0.01)
    assert orch.globalstatusmodel.loop_state == LoopStatus.stopped
    assert not (orch.action_dq or orch.experiment_dq or orch.sequence_dq)
    # ladder order held: actions before exp-finish before seq-finish
    assert orch.calls.index("loop_task_dispatch_action") < orch.calls.index(
        "finish_active_experiment"
    )
    # finalization closed out the last experiment+sequence exactly once each
    assert orch.calls.count("finish_active_sequence") == 1
    assert orch.active_experiment is None and orch.active_sequence is None
    await loop.close()


@pytest.mark.asyncio
async def test_estop_funnel_race_seed_single_finalizer():
    """DD-3 race seed (P1b2 grows this into §10.3 item 3): estop lands while
    the loop is BLOCKED inside a dispatch effect; the cascade runs at the
    trigger site; the in-flight marked command's follow-up iterate bails; the
    estop finalizer runs exactly once and clean close-out never fires."""
    orch = _ScriptedOrch(n_acts=2)
    orch.active_experiment = object()
    orch.block_dispatch = asyncio.Event()
    runtime, loop = _make(orch)
    loop.start()
    await runtime.handle(StartRequested())
    for _ in range(100):
        if "loop_task_dispatch_action" in orch.calls:
            break
        await asyncio.sleep(0.01)
    # trigger-site estop while the loop is stalled mid-effect
    from helao.hexagon.domain.orchestration import EstopRequested

    await runtime.handle(EstopRequested(reason="race seed"))
    assert orch.globalstatusmodel.loop_state == LoopStatus.estopped
    assert orch.calls.count("estop_finish_active") == 1
    orch.block_dispatch.set()  # release the stalled effect
    await asyncio.sleep(0.2)
    # SOLE finalizer: the clean finish_active_experiment never ran
    assert orch.calls.count("finish_active_experiment") == 0
    assert orch.globalstatusmodel.loop_state == LoopStatus.estopped  # parked estopped
    await loop.close()


@pytest.mark.asyncio
async def test_graft_rebinds_control_methods():
    orch = _ScriptedOrch(n_acts=1)

    async def _noop():  # legacy originals to capture
        return None

    for name in ("start", "start_loop", "stop", "skip", "estop_loop",
                 "clear_estop", "clear_error"):
        setattr(orch, name, _noop)
    graft = graft_hexagon_loop(orch, PortWiring(logging=_AlertSpy()))
    try:
        assert set(graft.originals) == {
            "start", "start_loop", "stop", "skip", "estop_loop",
            "clear_estop", "clear_error",
        }
        await orch.start()  # rebound: routes through the reducer
        for _ in range(200):
            if not orch.action_dq:
                break
            await asyncio.sleep(0.01)
        assert not orch.action_dq
        assert orch.current_stop_message == ""  # legacy start() clears banner
        # skip while parked mirrors legacy: clears action_dq only
        orch.action_dq = ["x"]
        await orch.skip()
        assert orch.action_dq == []
    finally:
        await graft.loop.close()
```

- [ ] **Step 2: Run to verify failure**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_dispatch_loop.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'helao.hexagon.app.dispatch_loop'`.

- [ ] **Step 3: Implement** — `helao/hexagon/app/dispatch_loop.py`:

```python
"""Single-drainer dispatch loop + legacy-Orch graft (spec §4.5, KEEP #2/#3).

ONE long-lived asyncio task parked on an Event owns every queue-draining
command (DispatchHeadAction / FinishThenDispatch* / CloseOut* arise only
from LoopIterate, which only this task feeds): double-drain (F2b) is
structurally impossible. Control events run at their trigger site through
the same pure reducer (DD-3): E-STOP is concurrent with the loop exactly as
legacy's ingester-task estop_loop is, and the marked commands' live
re-checks are the race guard. In-process self-ops (KEEP #3): nothing here
ever dispatches an RPC/HTTP request to its own server — every effect is a
direct method call on the wrapped legacy Orch."""

import asyncio
import logging
from dataclasses import dataclass, field, replace
from typing import Callable, Dict

from helao.hexagon.app.orch_effects import (
    OrchCommandRunner,
    apply_state_delta,
    derive_state,
)
from helao.hexagon.app.wiring import PortWiring
from helao.hexagon.domain.dispatch_policy import DispatchPolicy, ExitLoop
from helao.hexagon.domain.models import ErrorCodes, LoopStatus
from helao.hexagon.domain.orchestration import (
    ClearErrorRequested,
    ClearEstopRequested,
    CreateDispatchLoopTask,
    EstopRequested,
    Event,
    LoopIterate,
    RetryDriverHealth,
    SkipRequested,
    StartRequested,
    StopRequested,
    UncaughtLoopException,
    WaitAllActionsIdle,
    step,
)

LOGGER = logging.getLogger(__name__)
_POLICY = DispatchPolicy()

__all__ = ["HexDispatchLoop", "HexRuntime", "HexagonGraft", "graft_hexagon_loop"]


class HexRuntime:
    """Pure-reducer runtime: derive live state, step, apply delta, execute."""

    def __init__(self, orch, effects: OrchCommandRunner):
        self.orch = orch
        self.effects = effects
        self.loop_wake = asyncio.Event()

    async def handle(self, event: Event) -> ErrorCodes:
        return await self._apply_and_execute(derive_state(self.orch), event)

    async def _apply_and_execute(self, old, event) -> ErrorCodes:
        new, commands = step(old, event)
        skip_loop_state = any(isinstance(c, WaitAllActionsIdle) for c in commands)
        await apply_state_delta(
            self.orch, old, new, skip_loop_state=skip_loop_state
        )
        rc = ErrorCodes.none
        for cmd in commands:
            if isinstance(cmd, CreateDispatchLoopTask):
                self.loop_wake.set()  # the long-lived task IS the loop (T1)
                continue
            if isinstance(cmd, RetryDriverHealth):
                await self.effects.execute(cmd)
                # one-shot ladder fall-through with na_drivers masked —
                # mirrors orch_dispatch._loop's non-continue driver-health
                # path (re-asking next_step with them still unknown would
                # livelock; masking == calling ladder_step directly)
                masked = replace(derive_state(self.orch), na_drivers=())
                rc2 = await self._apply_and_execute(masked, LoopIterate())
                if rc2 is not ErrorCodes.none:
                    rc = rc2
                continue
            cmd_rc = await self.effects.execute(cmd)
            if cmd_rc is not None and cmd_rc is not ErrorCodes.none:
                rc = cmd_rc
        if rc is not ErrorCodes.none:
            # legacy _loop epilogue (orch_dispatch.py:583-585)
            LOGGER.error(f"stopping orch with error code: {rc}")
            await self.orch.intend_stop()
        return rc


class HexDispatchLoop:
    """The single drainer: parked on loop_wake; sole feeder of LoopIterate."""

    def __init__(self, runtime: HexRuntime):
        self.runtime = runtime
        self._task = None
        self._closed = False

    def start(self) -> None:
        self._task = asyncio.get_running_loop().create_task(
            self.run_forever(), name="hexagon_dispatch_loop"
        )

    async def close(self) -> None:
        self._closed = True
        self.runtime.loop_wake.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except asyncio.TimeoutError:
                self._task.cancel()

    async def run_forever(self) -> None:
        while True:
            await self.runtime.loop_wake.wait()
            self.runtime.loop_wake.clear()
            if self._closed:
                return
            await self._run_started_phase()

    async def _run_started_phase(self) -> None:
        orch = self.runtime.orch
        LOGGER.info("--- started operator orch ---")  # run() :1116 wording
        LOGGER.info(f"current orch status: {orch.globalstatusmodel.orch_state}")
        try:
            while True:
                live = derive_state(orch)
                exiting = isinstance(
                    _POLICY.next_step(live.snapshot()), ExitLoop
                )
                await self.runtime.handle(LoopIterate())
                if exiting:
                    # that iterate ran the reducer's finalization
                    # (close-outs + stopped-unless-estopped + export) —
                    # mirror of DispatchRunner.run's _finalize-then-return
                    return
        except Exception:
            LOGGER.error("serious orch exception occurred")
            LOGGER.error("ERROR: ", exc_info=True)
            try:  # T13: exception -> estop, like DispatchRunner.run
                await self.runtime.handle(
                    UncaughtLoopException(reason="dispatch loop exception")
                )
            except Exception:
                LOGGER.error("estop after loop exception failed", exc_info=True)


@dataclass
class HexagonGraft:
    runtime: HexRuntime
    loop: HexDispatchLoop
    effects: OrchCommandRunner
    originals: Dict[str, Callable] = field(default_factory=dict)

    async def close(self) -> None:
        await self.loop.close()


def graft_hexagon_loop(orch, wiring: PortWiring) -> HexagonGraft:
    """Rebind the legacy Orch's control methods onto the reducer runtime and
    start the single-drainer loop. Instance-level rebinding is the sanctioned
    wrap seam (orch_estop.py docstring: instance patches stay observable);
    NO legacy source is modified."""
    effects = OrchCommandRunner(orch, wiring)
    runtime = HexRuntime(orch, effects)
    loop = HexDispatchLoop(runtime)
    graft = HexagonGraft(runtime=runtime, loop=loop, effects=effects)
    for name in ("start", "start_loop", "stop", "skip", "estop_loop",
                 "clear_estop", "clear_error"):
        graft.originals[name] = getattr(orch, name)

    async def hex_start():
        await runtime.handle(StartRequested())
        orch.current_stop_message = ""  # legacy start() clears the banner

    async def hex_start_loop():
        await runtime.handle(StartRequested())
        return orch.globalstatusmodel.loop_state

    async def hex_stop(reset_run_id: bool = False):
        # guard structure mirrors orch.py:541-556 verbatim
        if orch.globalstatusmodel.loop_state == LoopStatus.started:
            await runtime.handle(StopRequested())
        elif orch.globalstatusmodel.loop_state == LoopStatus.estopped:
            LOGGER.info("orchestrator E-STOP flag was raised; nothing to stop")
        else:
            LOGGER.info("orchestrator is not running")
        if reset_run_id:
            LOGGER.info("resetting active_run_id on stop")
            orch.active_run_id = None

    async def hex_skip():
        # mirrors orch.py:528-534
        if orch.globalstatusmodel.loop_state == LoopStatus.started:
            await runtime.handle(SkipRequested())
        else:
            LOGGER.info("orchestrator not running, clearing action queue")
            orch.action_dq.clear()

    async def hex_estop_loop(reason: str = ""):
        # legacy estop_loop message shape ("E-STOP" + optional suffix);
        # cascade runs HERE at the trigger site through the reducer (DD-3)
        msg = f"E-STOP{' ' + reason if reason else ''}"
        await runtime.handle(EstopRequested(reason=msg))
        # legacy estop_loop's intend_none() wakes the interrupt queue; the
        # reducer's none->none intent delta skips that call, so wake
        # explicitly (a dispatch effect parked in wait_for_interrupt must
        # re-check and observe the estop) — DD-5 item 6
        await orch.interrupt_q.put("estop")

    async def hex_clear_estop():
        await runtime.handle(ClearEstopRequested())

    async def hex_clear_error():
        await runtime.handle(ClearErrorRequested())

    orch.start = hex_start
    orch.start_loop = hex_start_loop
    orch.stop = hex_stop
    orch.skip = hex_skip
    orch.estop_loop = hex_estop_loop
    orch.clear_estop = hex_clear_estop
    orch.clear_error = hex_clear_error
    loop.start()
    return graft
```

Implementation note: `graft_hexagon_loop` (and therefore `HexDispatchLoop.start`) must be called from a running event loop — the FastAPI startup hook and the pytest-asyncio tests both satisfy this; calling it from sync context raises `RuntimeError` from `get_running_loop()`, which is the desired fail-loud behavior.

- [ ] **Step 4: Run to verify pass**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_dispatch_loop.py helao/hexagon/tests -q`
Expected: all PASS. The race-seed test is the critical one: `estop_finish_active` exactly once, `finish_active_experiment` zero times, loop parked `estopped`.

- [ ] **Step 5: Pyright + commit**

```bash
conda run -n helao pyright helao/hexagon/app/   # expected: 0 errors
conda run -n helao black helao/hexagon/app/dispatch_loop.py helao/hexagon/tests/test_dispatch_loop.py
git add helao/hexagon/app/dispatch_loop.py helao/hexagon/tests/test_dispatch_loop.py
git commit -m "feat(hexagon): single-drainer dispatch loop + legacy Orch graft (P1b1 T9)"
```

---

### Task 10: App factory + launcher shim package

**Files:**
- Create: `helao/hexagon/app/factory.py`
- Create: `helao/deploy/hexagon/__init__.py`, `helao/deploy/hexagon/servers/__init__.py`, `helao/deploy/hexagon/servers/orchestrator/__init__.py`, `helao/deploy/hexagon/servers/orchestrator/async_orch2.py`, `helao/deploy/hexagon/servers/action/__init__.py`, `helao/deploy/hexagon/servers/action/ws_simulator.py`
- Modify: `.gitignore` (ONE line)
- Test: `helao/hexagon/tests/test_factory.py`

**Interfaces:**
- Consumes: `helao.core.servers.orch_api.OrchAPI(server_key, server_title, description, version, driver_classes=None)` (constructs `Orch` inside its OWN startup handler — the graft hook must be a LATER-registered startup handler); legacy sim module `helao.deploy.test.servers.action.ws_simulator.makeApp(server_key)`; `helao.helpers.config_loader.CONFIG`; Tasks 3-9 products.
- Produces:
  - `build_wiring(server_key: str) -> PortWiring` — real legacy adapters from the installed CONFIG (fail loud when CONFIG is None or `root` missing).
  - `makeOrchApp(server_key: str) -> OrchAPI` — wiring (require `ORCH_REQUIRED`) + `OrchAPI` + graft-on-startup + loop-close-on-shutdown; `app.hexagon_wiring` / `app.hexagon_graft` attributes.
  - `makeActionApp(server_key: str, legacy_module: str) -> HelaoFastAPI` — wiring (require `ACTION_REQUIRED`) + the legacy module's `makeApp(server_key)` (co-located RPC inherited) + `app.hexagon_wiring`.
  - `makeVisApp(*args, **kwargs)` — raises `HexagonDeferred` ("visualizer hosting is P2") — a scoped deferral, tested, never silent.
  - Launcher shims: `helao.deploy.hexagon.servers.orchestrator.async_orch2.makeApp(server_key)` → `makeOrchApp`; `helao.deploy.hexagon.servers.action.ws_simulator.makeApp(server_key)` → `makeActionApp(server_key, "helao.deploy.test.servers.action.ws_simulator")`.

- [ ] **Step 1: Write the failing tests** — `helao/hexagon/tests/test_factory.py`:

```python
"""Composition factory: fail-loud wiring, OrchAPI construction with graft
hooks, action-app wrap, vis deferral, launcher shim delegation. Construction
level only — full lifecycle is the Task 12 launched smoke."""

import pytest

from helao.hexagon.adapters.errors import HexagonDeferred
from helao.hexagon.app.wiring import UnwiredPortError


def _world(tmp_path):
    return {
        "root": str(tmp_path),
        "dummy": True,
        "simulation": True,
        "servers": {
            "ORCH": {"host": "127.0.0.1", "port": 8901, "group": "orchestrator",
                     "fast": "async_orch2", "params": {}},
            "SIM": {"host": "127.0.0.1", "port": 8902, "group": "action",
                    "fast": "ws_simulator", "params": {}},
        },
    }


@pytest.fixture()
def installed_config(tmp_path, monkeypatch):
    from helao.helpers import config_loader

    world = _world(tmp_path)
    (tmp_path / "LOGS").mkdir()
    monkeypatch.setattr(config_loader, "CONFIG", world)
    return world


def test_build_wiring_fail_loud_without_config(monkeypatch):
    from helao.helpers import config_loader
    from helao.hexagon.app.factory import build_wiring

    monkeypatch.setattr(config_loader, "CONFIG", None)
    with pytest.raises(RuntimeError):
        build_wiring("ORCH")


def test_build_wiring_produces_real_adapters(installed_config):
    from helao.hexagon.app.factory import build_wiring
    from helao.hexagon.ports.clock import ClockPort
    from helao.hexagon.ports.config import ConfigPort
    from helao.hexagon.ports.logging import LoggingPort
    from helao.hexagon.ports.transport import TransportPort

    w = build_wiring("ORCH")
    assert isinstance(w.config, ConfigPort)
    assert isinstance(w.logging, LoggingPort)
    assert isinstance(w.clock, ClockPort)
    assert isinstance(w.transport, TransportPort)
    assert w.config.world_cfg() is installed_config  # raw-dict identity end-to-end
    w.require("config", "logging", "clock", "transport", "state_persistence")


def test_make_orch_app_constructs_with_graft_hooks(installed_config):
    from helao.core.servers.orch_api import OrchAPI
    from helao.hexagon.app.factory import makeOrchApp

    app = makeOrchApp("ORCH")
    assert isinstance(app, OrchAPI)
    assert app.hexagon_wiring is not None
    routes = {r.path for r in app.routes}
    # BaseAPI/OrchAPI system surface present (spec §8.2 spot checks)
    for path in ("/start", "/stop", "/estop_orch", "/clear_estop",
                 "/append_sequence", "/global_status", "/update_status"):
        assert path in routes, path
    assert app.rpc_dispatcher is not None  # co-located RPC registry exists


def test_make_action_app_wraps_legacy_module(installed_config):
    from helao.helpers.server_api import HelaoFastAPI
    from helao.hexagon.app.factory import makeActionApp

    app = makeActionApp("SIM", "helao.deploy.test.servers.action.ws_simulator")
    assert isinstance(app, HelaoFastAPI)
    assert app.hexagon_wiring is not None
    routes = {r.path for r in app.routes}
    assert "/SIM/acquire_data" in routes  # real legacy action route survived


def test_make_vis_app_defers_loudly():
    from helao.hexagon.app.factory import makeVisApp

    with pytest.raises(HexagonDeferred):
        makeVisApp("LIVE")


def test_launcher_shims_delegate():
    import helao.deploy.hexagon.servers.action.ws_simulator as sim_shim
    import helao.deploy.hexagon.servers.orchestrator.async_orch2 as orch_shim
    from helao.hexagon.app import factory

    assert orch_shim.makeApp.__module__ == "helao.deploy.hexagon.servers.orchestrator.async_orch2"
    assert sim_shim.LEGACY_MODULE == "helao.deploy.test.servers.action.ws_simulator"
    assert orch_shim.FACTORY is factory.makeOrchApp
```

- [ ] **Step 2: Run to verify failure**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_factory.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'helao.hexagon.app.factory'`.

- [ ] **Step 3: Implement the factory** — `helao/hexagon/app/factory.py`:

```python
"""Hexagon composition root (spec §4.5).

The ONLY layer that constructs FastAPI objects and wires adapters into
ports. Fail loud (F2b): build_wiring raises without an installed CONFIG;
each makeApp requires its composition's consumed port set BEFORE building
the app — a missing adapter aborts startup, never a silent fake. The
co-located RPC mirror (spec §7.1) is inherited from legacy HelaoFastAPI's
startup hook (ROUTER on http_port+10000, configured-host bind with 0.0.0.0
fallback). Launcher routing: helao/deploy/hexagon/ shim modules call these
factories via the per-server `deployment: hexagon` config key — zero
launcher edits, per-config atomic cut-over/rollback."""

import os
from importlib import import_module

from helao.hexagon.adapters.errors import HexagonDeferred
from helao.hexagon.adapters.legacy.clock import LegacyClockAdapter
from helao.hexagon.adapters.legacy.config import from_global_config
from helao.hexagon.adapters.legacy.logging_adapter import LegacyLoggingAdapter
from helao.hexagon.adapters.legacy.state_persistence import QueuePckStore
from helao.hexagon.adapters.legacy.transport import LegacyTransportAdapter
from helao.hexagon.app.wiring import ACTION_REQUIRED, ORCH_REQUIRED, PortWiring

__all__ = ["build_wiring", "makeActionApp", "makeOrchApp", "makeVisApp"]


def build_wiring(server_key: str) -> PortWiring:
    config = from_global_config()  # raises when CONFIG is not installed
    root = config.root()  # KeyError -> loud, like helao_dirs
    log_root = os.path.join(root, "LOGS")
    return PortWiring(
        config=config,
        logging=LegacyLoggingAdapter(),
        clock=LegacyClockAdapter.from_offset_file(log_root),
        transport=LegacyTransportAdapter(config),
        state_persistence=QueuePckStore(root),
    )


def makeOrchApp(server_key: str):
    from helao.core.servers.orch_api import OrchAPI
    from helao.hexagon.app.dispatch_loop import graft_hexagon_loop

    wiring = build_wiring(server_key)
    wiring.require(*ORCH_REQUIRED)

    app = OrchAPI(
        server_key,
        server_key,
        "Hexagon-composed orchestrator (wrapped legacy Orch + reducer loop)",
        version=3.0,
        driver_classes=None,
    )
    app.hexagon_wiring = wiring
    app.hexagon_graft = None

    # Registered AFTER OrchAPI.__init__'s own startup handler, so it runs
    # AFTER `self.orch = Orch(fastapp=self)` + myinit (Starlette preserves
    # registration order): the graft sees the live legacy Orch.
    @app.on_event("startup")
    async def _hexagon_graft_startup():
        app.hexagon_graft = graft_hexagon_loop(app.orch, wiring)

    @app.on_event("shutdown")
    async def _hexagon_graft_shutdown():
        if app.hexagon_graft is not None:
            await app.hexagon_graft.close()

    return app


def makeActionApp(server_key: str, legacy_module: str):
    wiring = build_wiring(server_key)
    wiring.require(*ACTION_REQUIRED)
    app = import_module(legacy_module).makeApp(server_key)
    app.hexagon_wiring = wiring
    return app


def makeVisApp(*args, **kwargs):
    raise HexagonDeferred(
        "visualizer/operator hosting via hexagon vis adapters is P2 "
        "(master spec §12); keep bokeh entries on their legacy deployment"
    )
```

- [ ] **Step 4: Create the launcher shim package + .gitignore line**

`helao/deploy/hexagon/__init__.py`:

```python
"""Launcher shim deployment for hexagon-composed servers (P1b1 DD-6).

Config entries opt in per server with `deployment: hexagon`; modules here
only delegate to helao.hexagon.app.factory — no server logic lives in this
package. Rollback = flip the key back to the legacy deployment."""
```

`helao/deploy/hexagon/servers/__init__.py`, `helao/deploy/hexagon/servers/orchestrator/__init__.py`, `helao/deploy/hexagon/servers/action/__init__.py`: empty files.

`helao/deploy/hexagon/servers/orchestrator/async_orch2.py`:

```python
"""Hexagon orchestrator entrypoint: same module/fast name as the legacy
async_orch2 so a config flips ONLY the `deployment:` key."""

from helao.hexagon.app.factory import makeOrchApp

__all__ = ["makeApp"]

FACTORY = makeOrchApp


def makeApp(server_key):
    return FACTORY(server_key)
```

`helao/deploy/hexagon/servers/action/ws_simulator.py`:

```python
"""Hexagon-composed websocket simulator: wraps the test deployment's real
ws_simulator makeApp through the hexagon factory (fail-loud wiring +
co-located RPC via HelaoFastAPI)."""

from helao.hexagon.app.factory import makeActionApp

__all__ = ["makeApp"]

LEGACY_MODULE = "helao.deploy.test.servers.action.ws_simulator"


def makeApp(server_key):
    return makeActionApp(server_key, LEGACY_MODULE)
```

`.gitignore` — insert directly under the existing `!helao/deploy/test/` line:

```
!helao/deploy/hexagon/
```

- [ ] **Step 5: Run to verify pass**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_factory.py helao/hexagon/tests -q`
Expected: all PASS. (`test_make_orch_app_constructs_with_graft_hooks` constructs OrchAPI without running startup — no Orch is built, no ports bound.)

- [ ] **Step 6: Pyright + commit**

```bash
conda run -n helao pyright helao/hexagon/app/factory.py helao/deploy/hexagon/   # expected: 0 errors
conda run -n helao black helao/hexagon/app/factory.py helao/deploy/hexagon/ helao/hexagon/tests/test_factory.py
git status --short   # REVIEW: only the intended files; never stage helao/framework/
git add helao/hexagon/app/factory.py helao/hexagon/tests/test_factory.py .gitignore
git add helao/deploy/hexagon/__init__.py helao/deploy/hexagon/servers/__init__.py helao/deploy/hexagon/servers/orchestrator/__init__.py helao/deploy/hexagon/servers/orchestrator/async_orch2.py helao/deploy/hexagon/servers/action/__init__.py helao/deploy/hexagon/servers/action/ws_simulator.py
git commit -m "feat(hexagon): composition factory + launcher shim deployment (P1b1 T10)"
```

---

### Task 11: Smoke config `goldenhex.yml`

**Files:**
- Create: `helao/deploy/test/configs/goldenhex.yml`

**Interfaces:**
- Consumes: the P0 `golden.yml` shape (same ports 8001/8002/8010 so `harness/capture.py`'s hardcoded ORCH/SIM/DB endpoints work unmodified); the `deployment: hexagon` launcher key (DD-6).
- Produces: the config prefix `goldenhex` used by Task 12's launch + capture (`--config-prefix goldenhex`).

- [ ] **Step 1: Write the config** — `helao/deploy/test/configs/goldenhex.yml`:

```yaml
# P1b1 SMOKE config (hexagon-composed ORCH + SIM; legacy sim DB).
# Copy of golden.yml minus the bokeh servers (vis/operator hosting is P2),
# with `deployment: hexagon` flipping ORCH and SIM onto the hexagon factory.
# Ports match golden.yml so harness/capture.py works unmodified.
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
root: /home/dan/INST_hlo_hexsmoke
servers:
  ORCH:
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

- [ ] **Step 2: Offline sanity — config resolves and shims import**

```bash
conda run -n helao python -c "
from helao.helpers.config_loader import read_config
cfg = read_config('goldenhex')
assert cfg['servers']['ORCH']['deployment'] == 'hexagon'
assert cfg['servers']['SIM']['deployment'] == 'hexagon'
import importlib
importlib.import_module('helao.deploy.hexagon.servers.orchestrator.async_orch2')
importlib.import_module('helao.deploy.hexagon.servers.action.ws_simulator')
print('goldenhex OK')
"
```

Expected: `goldenhex OK`.

- [ ] **Step 3: Commit**

```bash
git add helao/deploy/test/configs/goldenhex.yml
git commit -m "feat(hexagon): goldenhex smoke config (hexagon ORCH+SIM, legacy sim DB) (P1b1 T11)"
```

---

### Task 12: P1b1 SMOKE gate — launch + run GM-1 end-to-end

**Files:**
- Create: `helao/hexagon/tests/smoke/__init__.py` (empty)
- Create: `helao/hexagon/tests/smoke/kill_group.py`
- Create: `helao/hexagon/tests/smoke/assert_smoke_tree.py`
- No test file: this task's verification IS the launched run (the sim-live gate rule, spec §10.2(d)).

**Interfaces:**
- Consumes: `launch.py goldenhex --no-hot-reload`; `harness/capture.py` (`--scenario GM-1 --config-prefix goldenhex`) — it waits for 8001/8002/8010, builds the GM-1 `SIM_websocket_data` sequence, submits via `private_dispatcher(... "append_sequence" ...)` + `"start"`, quiesces on `/global_status` + DB `/n_queue`+`/tasks`, snapshots, writes a provenance manifest.
- Produces: the recorded smoke evidence: capture output dir + assertion script output + clean-shutdown proof. **This is a wiring gate, NOT a parity claim** — transport used: real ZMQ RPC + HTTP + WS (no fakes anywhere in the composition; any fake would print its WARNING banner).

- [ ] **Step 1: Write the helper scripts**

`helao/hexagon/tests/smoke/kill_group.py`:

```python
"""Terminate a launched goldenhex group via its pid pickle (the same
STATES/pids_<prefix>_<extraopt>.pck contract launch.py maintains)."""

import pickle
import sys
import time

import psutil


def main(root: str, prefix: str = "goldenhex") -> int:
    pck = f"{root}/STATES/pids_{prefix}_.pck"
    try:
        pidd = pickle.load(open(pck, "rb"))
    except FileNotFoundError:
        print(f"no pid pickle at {pck}; nothing to kill")
        return 0
    procs = []
    for key, entry in pidd.items():
        pid = entry.get("pid") if isinstance(entry, dict) else None
        if pid and psutil.pid_exists(pid):
            p = psutil.Process(pid)
            print(f"terminating {key} (pid {pid})")
            p.terminate()
            procs.append(p)
    _gone, alive = psutil.wait_procs(procs, timeout=10)
    for p in alive:
        print(f"SIGKILL {p.pid}")
        p.kill()
    time.sleep(1)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
```

(Verify the pickle's value shape against `launch.py`'s `Pidd` — `{server_key: {host, port, pid}}` per core-05 §1 — before first use; adjust the `entry.get("pid")` access if it differs.)

`helao/hexagon/tests/smoke/assert_smoke_tree.py`:

```python
"""P1b1 smoke assertions: the GM-1 run left a complete, quiesced tree.
Wiring proof only — normalized parity diffs are P1b2."""

import sys
from pathlib import Path


def main(root: str) -> int:
    root_p = Path(root)
    failures = []

    def check(cond: bool, msg: str):
        (print(f"  OK  {msg}") if cond else failures.append(msg))

    # 1. sequence shipped end-to-end: RUNS_SYNCED holds the destructive zip
    zips = list((root_p / "RUNS_SYNCED").rglob("*.zip"))
    check(len(zips) >= 1, f"RUNS_SYNCED sequence zip present ({zips})")

    # 2. process leg ran: GM-1 = 2 experiments x 2 process groups -> 4 prc ymls
    prcs = list((root_p / "PROCESSES").rglob("*-prc.yml"))
    check(len(prcs) == 4, f"PROCESSES has 4 -prc.yml (got {len(prcs)})")

    # 3. recorded S3 sink got payloads (sim DB s3_record mode)
    s3 = list((root_p / "S3_SIM").rglob("*")) if (root_p / "S3_SIM").is_dir() else []
    check(len(s3) > 0, "S3_SIM recorded uploads present")

    # 4. quiesced: nothing stranded in RUNS_ACTIVE
    active = list((root_p / "RUNS_ACTIVE").rglob("*.yml"))
    check(len(active) == 0, f"RUNS_ACTIVE empty (got {active})")

    # 5. logging contract (F3): flat per-server logs under <root>/LOGS
    for key in ("ORCH", "SIM", "DB"):
        check((root_p / "LOGS" / f"{key}.log").is_file(), f"LOGS/{key}.log exists")

    # 6. the hexagon loop actually ran (its parked/started log line)
    orch_log = (root_p / "LOGS" / "ORCH.log").read_text(errors="replace")
    check("--- started operator orch ---" in orch_log, "hexagon loop started")
    check("FAKE PORT IN USE" not in orch_log, "no fake adapters in composition")
    check("Traceback" not in orch_log, "no tracebacks in ORCH.log")

    if failures:
        print("\nSMOKE FAILURES:")
        for f in failures:
            print(f"  FAIL {f}")
        return 1
    print("\nP1b1 smoke tree: ALL CHECKS PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
```

Note on check 3: `sim_db_server`'s recorder path is `<root>/S3_SIM/<bucket>/<key>` per the P0 spec §6.3; confirm the actual dir name in `helao/deploy/test/servers/action/sim_db_server.py` and adjust the path if the P0 implementation placed it elsewhere. Note on check 2: confirm the golden GM-1 capture also produced 4 prc files (look in the existing P0 golden store manifest); if the count differs, pin the smoke to the SAME count the legacy golden shows.

- [ ] **Step 2: Launch the hexagon group** (fresh root; nothing else on ports 8001/8002/8010)

```bash
rm -rf /home/dan/INST_hlo_hexsmoke
cd /mnt/STORAGE/repos/helao/helao-async
nohup conda run -n helao python launch.py goldenhex --no-hot-reload > /tmp/hexsmoke_launch.log 2>&1 &
sleep 30 && tail -20 /tmp/hexsmoke_launch.log
```

Expected: banner + three servers launched, no tracebacks. If a server dies at startup, its log is `/home/dan/INST_hlo_hexsmoke/LOGS/<KEY>.log` — an `UnwiredPortError` there means the factory refused composition (fix the wiring, that is the fail-loud design working).

- [ ] **Step 3: Run GM-1 through the P0 capture rig**

```bash
mkdir -p /home/dan/hexsmoke_captures
conda run -n helao python -m harness.capture \
  --scenario GM-1 \
  --root /home/dan/INST_hlo_hexsmoke \
  --out /home/dan/hexsmoke_captures/gm1_p1b1 \
  --config-prefix goldenhex \
  --notes "P1b1 smoke: hexagon ORCH+SIM, wrapped-legacy adapters, single-drainer loop; WIRING GATE ONLY, no parity claim"
```

Expected: `captured GM-1 -> /home/dan/hexsmoke_captures/gm1_p1b1` and exit 0. The capture's own quiesce (loop_state == "stopped", queues drained, DB `/n_queue`+`/tasks` zero, RUNS_ACTIVE settled) is part of the gate — a hung loop or unfinished sync fails here.

- [ ] **Step 4: Assert the tree**

```bash
conda run -n helao python helao/hexagon/tests/smoke/assert_smoke_tree.py /home/dan/INST_hlo_hexsmoke
```

Expected: `P1b1 smoke tree: ALL CHECKS PASS`, exit 0.

- [ ] **Step 5: Clean shutdown**

```bash
conda run -n helao python helao/hexagon/tests/smoke/kill_group.py /home/dan/INST_hlo_hexsmoke
sleep 3
conda run -n helao python -c "
import requests
for port in (8001, 8002, 8010):
    try:
        requests.get(f'http://127.0.0.1:{port}/docs', timeout=1)
        raise SystemExit(f'port {port} still up')
    except requests.exceptions.ConnectionError:
        pass
print('group down cleanly')
"
```

Expected: `group down cleanly`. Also confirm no strays: `ps aux | grep -E "fast_launcher|goldenhex" | grep -v grep` → empty.

- [ ] **Step 6: Full suite regression + record the gate**

```bash
conda run -n helao python -m pytest helao/hexagon/tests -q          # expected: all pass
conda run -n helao pyright helao/hexagon/                            # expected: 0 errors
```

Append a short gate record to the END of this plan file (under "Gate record") with: date, git SHA, capture output path, assertion output summary, and the sentence "transport: real ZMQ RPC + HTTP + WS; no fakes in composition" (spec §10.2(c): done-claims name the transport used).

- [ ] **Step 7: Commit**

```bash
conda run -n helao black helao/hexagon/tests/smoke/
git add helao/hexagon/tests/smoke/__init__.py helao/hexagon/tests/smoke/kill_group.py helao/hexagon/tests/smoke/assert_smoke_tree.py docs/superpowers/plans/2026-07-17-P1b1-adapters-app-loop.md
git commit -m "test(hexagon): P1b1 smoke gate — hexagon group runs GM-1 end-to-end (P1b1 T12)"
```

Do NOT commit the capture output or the smoke root (both live outside the repo). Do NOT push.

---

## Self-review (run after writing, fixed inline)

1. **Spec/brief coverage.**
   - Boundary-test extension + mutation self-tests → Task 1. Fakes relocation (opt-in, banners kept) → Task 2. Fail-loud composition primitive → Task 3 (+ `adapters/errors.py` refinement in Task 6).
   - Adapters: ArtifactStore (T6), DataSink (T6), Sync (T7), Transport + co-located RPC + bind-fix verification (T5), Status push (T7; WS publish deferred loudly per DD-7), Clock/NTP (T4), Logging fail-loud no-mkdtemp (T4), Config raw-dict identity (T4), Hardware passthrough (T7), StatePersistence (T7), SampleState flattening facade (T7 — P1a carry-note addressed). Each has conformance (isinstance vs Protocol) + behavior/delegation tests; the deepest "vs wrapped legacy" behavior test is T5's live HelaoFastAPI RPC roundtrip; T4's file-logger writes a real file at the contractual path.
   - app/factory (makeApp family, fail-loud, co-located RPC, `deployment:` routing) → T10-T11. Single-drainer loop + live-estop re-check semantics + in-process self-ops → T8-T9 (DD-2/DD-3 documented; race seed test in T9). Windows `loop_factory`/`set_event_loop` fix (9ad2c372): lives in the launchers, which P1b1 reuses unmodified — nothing to port, noted here so the checklist row is accounted for. SMOKE gate → T12.
2. **Placeholder scan.** No TBD/TODO-later steps. Deliberate raises are scoped decisions, each tested and routed to P1b2 in DD-7 (`HexagonDeferred` on `publish_*` and `makeVisApp`; WARNING-log on unreachable `RequeueHeadAction` per DD-4). Verification sub-steps that say "check the real signature before finalizing" (T4 `read_saved_offset` return shape, T5 dispatcher kwargs + RPC-client teardown name, T6 `Active.write_file` order, T7 `/update_nonblocking` param names + shim kwarg names, T12 pid-pickle shape / S3_SIM dir / prc count) are recon-then-adjust instructions with the expected answer stated — not open design work.
3. **Type consistency.** Adapter method signatures were transcribed from the landed P1a Protocols (`ports/*.py` read directly): `ConfigPort.world_cfg/server_cfg/server_params/root`; `LoggingPort.file_logger(server_key, log_root)`; `ClockPort.now/now_ns/offset`; `TransportPort.dispatch_action/dispatch_private/check_endpoint(url, timeout=3.0)`; `ArtifactStorePort` incl. `move_dir(hobj) -> bool` and `zip_dir(dir_path) -> Path`; `DataSinkPort`'s `_nowait` thread-safe trio; `SyncPort` incl. async `reset_sync` (sync-in-legacy bridged) and `n_queue()`; `StatePersistencePort.export_queues(payload, timestamp_pck=False) -> Path` / `import_queues() -> Optional[dict]`; `StatusPort` incl. `send_nonblocking_status(..., retries=3)`; `HardwarePort`'s full async lifecycle; `SampleStatePort`'s flat `get_samples/new_samples/update_samples`. Reducer command/event names were transcribed from `domain/orchestration.py`'s `__all__`. Cross-task names hold: `PortWiring`/`UnwiredPortError`/`HexagonDeferred` (T3→T6 move→T8/T9/T10), `derive_state`/`apply_state_delta`/`OrchCommandRunner` (T8→T9), `HexRuntime`/`HexDispatchLoop`/`graft_hexagon_loop`/`HexagonGraft` (T9→T10), `build_wiring`/`makeOrchApp`/`makeActionApp`/`makeVisApp` (T10→T11→T12), config prefix `goldenhex` (T11→T12).
4. **Gate honesty.** T12 asserts wiring outcomes only (tree exists, quiesced, clean shutdown, no fakes, no tracebacks); nowhere does this plan claim byte parity — that claim is reserved for P1b2's harness run IDs.

## P1b2 preview (design hooks left ready)

- **GM-1..GM-5 golden PARITY** over exactly this composition: re-run the P0 capture rig against `goldenhex` and diff with `python -m harness.parity --golden <legacy set> --candidate <hexagon capture>` — the smoke already produces harness-shaped captures with provenance manifests, so P1b2 adds only the diff runs + fixes. Gate = normalized-identical for all five scenarios, run IDs recorded.
- **§10.3 concurrency suite** on the real transport: items 1-7 against the launched group; item 3 (estop between decision and effect) extends T9's race seed to BOTH races — (a) estop while blocked on `orch.aiolock` inside the wrapped locked dispatch, (b) estop between the reducer decision and the `FinishThenDispatch*`/close-out effect — asserting single finalizer + `[finished, estopped]`; item 6 (history-poll hang exit via heartbeat) exercises the T8 history-poll verbatim port.
- **§9 behavior tests on the hexagon path**: logging path/rotation/no-tmp (the smoke's check 5 grows into the paired-offset-capture clock test), config-identity `--restore` round-trip through the grafted orch, `queues.pck` export/import against `QueuePckStore`.
- **Deferred bridges** (DD-7): Status `publish_*` WS bridge (zstd-pickle frame parity, decoded with the real `WsSubscriber` per §10.1(3)); native ingestion events (`StatusChanged`/`EstoppedUuidIngested` fed from a hexagon ingestion runner instead of the legacy `StatusIngester` short-circuit) — at which point the reducer's `orch_state` write-back rule (DD-2) is revisited; aux ports (PlateInfo/Library/Health/Notify) gain adapters when their first hexagon consumer lands.
- **Not P1b2 either** (later phases per master spec): TransformXY lift (D6, P3), ActionPlanMaker frame-inspection removal, Timer port, rerouting action-server write paths through ArtifactStore/DataSink at runtime (P2, under GM parity).

## Gate record

**Date:** 2026-07-17
**Git SHA:** 66c074b4b6a12a776f67d8b03ce396683ceb2f38 (P1b1 T11, base for this gate; T12's own commit follows)
**Config:** `goldenhex` (hexagon ORCH+SIM via `deployment: hexagon`, legacy sim DB), root `/home/dan/INST_hlo_hexsmoke`

**Launch:** `python launch.py goldenhex --no-hot-reload` — ORCH/SIM/DB all reached `/docs` 200 within ~40s, zero tracebacks in any of the three `LOGS/<KEY>.log` files.

**Capture:** `python -m harness.capture --scenario GM-1 --root /home/dan/INST_hlo_hexsmoke --out /home/dan/hexsmoke_captures/gm1_p1b1 --config-prefix goldenhex` -> `captured GM-1 -> /home/dan/hexsmoke_captures/gm1_p1b1`, exit 0. Capture's own quiesce (loop stopped, DB `/n_queue`+`/tasks` drained, RUNS_ACTIVE settled) passed inside the rig.

**Assertion:** `assert_smoke_tree.py /home/dan/INST_hlo_hexsmoke` -> **ALL CHECKS PASS** (RUNS_SYNCED zip present; PROCESSES has 4 `-prc.yml`, matching the P0 GM-1 golden's count exactly; S3_SIM recorded uploads present; RUNS_ACTIVE empty; LOGS/{ORCH,SIM,DB}.log all present; hexagon loop-started line present; no fake-adapter banner; no tracebacks).

**Shutdown:** `kill_group.py` terminated all three pids cleanly; ports 8001/8002/8010 confirmed down; `ps aux` shows no stray `fast_launcher`/`goldenhex` processes.

**Regression:** `pytest helao/hexagon/tests -q` -> 170 passed. `pyright helao/hexagon/` -> 10 pre-existing errors (all in `test_adapters_data.py`/`test_adapters_runtime_services.py`, T6/T7 typed-params test fixtures passing bare `Literal` strings where `DataModel`/`Action`/`Experiment`/`Sequence` are expected) confirmed present with T12's two edits stashed out, i.e. NOT introduced by this gate; carried forward as pre-existing debt outside T12 scope.

**Real bug found + fixed (in scope, non-legacy):** `helao/hexagon/app/dispatch_loop.py` and `helao/hexagon/app/orch_effects.py` (T9/T8) bound `LOGGER = logging.getLogger(__name__)` (stdlib) instead of the project's launcher-installed `helao_logging.LOGGER` singleton convention. A stdlib `getLogger(__name__)` call always returns a valid Logger object, so it never raised — it silently dropped every dispatch-loop/effects log record (including the loop's own "started operator orch" line) instead of routing to `<root>/LOGS/ORCH.log`, because `helao_logging.make_logger` attaches the file handler only to the specifically-named per-server logger instance with `propagate = False`. Fixed by introducing a small `_LazyServerLogger` shim (mirrors `LegacyLoggingAdapter._log()`'s call-time resolution) that both modules now share; verified the "--- started operator orch ---" line lands in `ORCH.log` post-fix, all 170 hexagon tests still pass, and the fix is a no-op (does not raise) when `helao_logging.LOGGER` is unset (bare unit-test import path).

**Transport:** real ZMQ RPC + HTTP + WS; no fakes in composition.

