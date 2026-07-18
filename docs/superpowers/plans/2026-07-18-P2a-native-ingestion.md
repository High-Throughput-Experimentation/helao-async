# P2a — Native Status/Health Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the legacy `StatusIngester` short-circuit (`helao/core/servers/orch_status_sync.py:265-291`) with a hexagon ingestion runner + health monitor that fold reported `ActionServerModel`s into the (kept) legacy `GlobalStatusModel` and emit the domain events the reducer already handles but never receives (`StatusChanged`, `EstoppedUuidIngested`, `ErroredUuidIngested`, `HeartbeatFailed`, `DriverHealthUnrecovered`); the reducer's `apply_state_delta` becomes the sole `orch_state` writer (DD-2), and the item-6 dead-peer exit lands pure-hexagon (`HeartbeatFailed → PruneDeadActions`, decision Q3), flipping the item-6 characterization tripwire into a real behavioral assertion.

**Architecture:** Everything lands in `helao/hexagon/` — a new app-layer module `ingestion.py` (`HexStatusIngestion` owning the `update_status`/`update_nonblocking` bodies + `HexHealthMonitor` replacing the legacy heartbeat task), a new `LegacyHealthAdapter` (first consumer of the P1a `HealthPort` Protocol), a `PruneDeadActions` command in the pure reducer plus its executor in `orch_effects.py`, and a graft-style instance rebind in `dispatch_loop.graft_hexagon_loop` (the same sanctioned wrap seam that already rebinds `start/stop/estop_loop`). The fold still targets the legacy `GlobalStatusModel` via `update_global_with_acts` — replacing the status model is NOT P2a. `ws_globstat`/`globstat_broadcast_task`/`clear_nonblocking` stay on legacy, untouched.

**Tech Stack:** Python 3.12 in the `helao` conda env; pytest + pytest-asyncio for the hexagon tree (`helao/hexagon/tests/`); launched-group validation via `helao/hexagon/tests/smoke/conc_run.sh` (curl-only readiness); pyright (authoritative) + black.

## Global Constraints

- **ZERO legacy edits** (graft/instance-rebind + hexagon-side only — NEVER edit `helao/core`|`helao/helpers`|`helao/deploy`; the dead-peer exit is pure-hexagon per Q3).
- **No private-deployment names** (public repo).
- **All Python via `conda run -n helao`.**
- **`pyright helao/hexagon` = 0 errors and black clean at each task.**
- **The §10.3 concurrency suite (esp. items 1–7 + the flipped item-6) is the regression net** — test-first where the risk is aiolock/interrupt_q ordering (biggest risk #1 in scope §3).
- **DD-2 double-writer window must be closed atomically** (risk #3): the `apply_state_delta` orch_state write-back and the `update_status`/`update_nonblocking` instance rebind land in the SAME task/commit — the rebind is what removes the legacy `StatusIngester`'s `orch_state` writes (`orch_status_sync.py:279-284`, the only `orch_state` writers in `helao/core/servers/`, verified by grep) at the same instant the reducer takes them.
- **Two-lock-owner invariant:** `orch.aiolock` is acquired by exactly two owners — status ingestion (`HexStatusIngestion.update_status`) and the dispatch critical section. The health monitor and the `PruneDeadActions` executor never acquire it (asserted by test).
- **Wire behavior unchanged:** `update_nonblocking` keeps the timestamp-format quirk (f-string `%`-format raises `TypeError` on a `None` `action_timestamp` — the third drift documented in `adapters/legacy/status.py:33-41`) and the `list.remove` `ValueError` on unknown exec_ids (spec §7.4) — both reproduced, pinned by test, no wire change. `clear_nonblocking` is not rebound at all.
- Plan-only sizing note: P2a fits one plan (8 tasks); no slicing recommended. Tasks 1–7 are pure-pytest (subagent-executable in-process); Task 8 (launched concurrency gate incl. the item-6 flip validation) is **MAIN SESSION ONLY** — background subagent launches get reaped on idle, and launched runs must use `conc_run.sh`'s curl-only readiness.

## Sanctioned behavior deltas (P2a — §9-style, documented improvements, not parity bugs)

1. **Item-6 dead-peer exit (THE improvement):** legacy parks FOREVER after a mid-action server kill (P1b2b investigation verdict: the monitor fires `stop` but the drainer stays blocked in the history-poll / `orch_wait_for_all_actions`, nothing prunes `active_dict`). P2a: the orch parks `stopped` with the `"... endpoints are unavailable"` stop message and an empty `active_dict`. The item-6 tripwire flips to assert this.
2. **Heartbeat alert wording:** legacy alerts `"ORCH STOPPED ~ <msg>"` via `LOGGER.alert` after `stop()`; the reducer path alerts `<msg>` via `AlertOperator` (`wiring.logging.alert`). `current_stop_message` wording is IDENTICAL (`"<ends> endpoints are unavailable"`); only the alert-channel prefix differs.
3. **`orch_state` under estop:** legacy never wrote `orch_state = estopped` (only `loop_state`); with DD-2 write-back the reducer's `_estop_transition` now also lands `orch_state = estopped` on the live model until the next status fold overwrites it with idle/busy (the legacy elif chain falls through to idle/busy when `loop_state != started`, and the reducer's `StatusChanged` reproduces that overwrite). Transient, observable only via `/global_status` between estop and the next fold.
4. **Pruned actions appear in history:** `PruneDeadActions` registers the dead action uuids into `action_history` with a terminal `finished` status and a synthesized `action_finished_timestamp` (legacy never records anything for them). This is what un-blocks the history poll and keeps item-7-style non-blank-history asserts coherent.

Everything else is behavior-identical by construction (verbatim body ports + same event interleaving: events are emitted inside `aiolock` exactly where the legacy inline block ran; the unconditional trailing `interrupt_q.put(globalstatusmodel)` wake is preserved).

## File Structure

| File | Role |
|---|---|
| `helao/hexagon/adapters/legacy/health.py` (create) | `LegacyHealthAdapter` — HealthPort adapter (HEAD-probe wrap + late-bound orch for ping/status_summary) |
| `helao/hexagon/app/ingestion.py` (create) | `HexStatusIngestion` (update_status/update_nonblocking bodies), `action_history_meta` helper, `HexHealthMonitor` |
| `helao/hexagon/app/wiring.py` (modify) | `PortWiring.health` slot; `ORCH_REQUIRED` grows `"health"` |
| `helao/hexagon/app/factory.py` (modify) | `build_wiring` constructs `LegacyHealthAdapter` |
| `helao/hexagon/domain/orchestration.py` (modify) | `HeartbeatFailed.dead_action_uuids`; `PruneDeadActions` command; reducer emission |
| `helao/hexagon/app/orch_effects.py` (modify) | DD-2 orch_state write-back; `PruneDeadActions` executor + `pruned_uuids`; history-poll health-aware break; `execute_retry_driver_health` |
| `helao/hexagon/app/dispatch_loop.py` (modify) | graft rebind of `update_status`/`update_nonblocking`; heartbeat task swap; `DriverHealthUnrecovered` feed in `HexRuntime` |
| `helao/hexagon/tests/test_adapter_health.py` (create) | adapter unit tests |
| `helao/hexagon/tests/test_ingestion.py` (create) | ingestion + monitor unit tests (real `GlobalStatusModel`/`Action` models — fixture fidelity §10.1) |
| `helao/hexagon/tests/test_orchestration.py` (modify) | reducer additions |
| `helao/hexagon/tests/test_orch_effects.py` (modify) | DD-2 delta + prune executor + poll-break + two-lock-owner tests; `_StubOrch` grows the rebind surface |
| `helao/hexagon/tests/test_dispatch_loop.py` (modify) | graft-rebind + driver-health-event tests |
| `helao/hexagon/tests/smoke/conc_items.py` (modify) | item-6 FLIP to real behavioral assertion |

---

### Task 1: `LegacyHealthAdapter` + `health` wiring slot

**Files:**
- Create: `helao/hexagon/adapters/legacy/health.py`
- Modify: `helao/hexagon/app/wiring.py` (add `health` field + `ORCH_REQUIRED`)
- Modify: `helao/hexagon/app/factory.py:28-42` (`build_wiring` wires the adapter)
- Test: `helao/hexagon/tests/test_adapter_health.py`

**Interfaces:**
- Consumes: `helao.hexagon.ports.auxiliary.HealthPort` (P1a Protocol, `ports/auxiliary.py:53-64`); `helao.helpers.dispatcher.endpoints_available(req_list) -> (all_available, [(url, [state])])`.
- Produces: `LegacyHealthAdapter` with `bind_orch(orch) -> None`, `async endpoints_available(urls: List[str]) -> List[Tuple[str, bool]]`, `async ping_action_servers() -> Dict[str, str]`, `status_summary() -> Dict[str, str]`. `PortWiring.health: Optional[HealthPort]`. `ORCH_REQUIRED` includes `"health"`. Task 6's monitor consumes `endpoints_available`; Task 6's graft calls `bind_orch`.

- [ ] **Step 1: Write the failing tests**

Create `helao/hexagon/tests/test_adapter_health.py`:

```python
"""HealthPort adapter: port-shape conversion of the legacy HEAD-probe
helper, late-bound orch for ping/status_summary, fail-loud unbound access,
and the ORCH_REQUIRED/wiring growth (P2a Task 1)."""

import pytest

from helao.hexagon.adapters.legacy.health import LegacyHealthAdapter
from helao.hexagon.app.wiring import ORCH_REQUIRED, PortWiring, UnwiredPortError
from helao.hexagon.ports.auxiliary import HealthPort


def test_adapter_satisfies_health_port_protocol():
    assert isinstance(LegacyHealthAdapter(), HealthPort)


def test_orch_required_includes_health_and_wiring_has_slot():
    assert "health" in ORCH_REQUIRED
    w = PortWiring()
    assert w.health is None
    with pytest.raises(UnwiredPortError, match="health"):
        w.require("health")


def test_unbound_ping_and_summary_fail_loud():
    ad = LegacyHealthAdapter()
    with pytest.raises(RuntimeError, match="not bound"):
        ad.status_summary()


@pytest.mark.asyncio
async def test_endpoints_available_converts_to_port_shape(monkeypatch):
    async def fake_probe(req_list):
        # legacy helper shape: (all_available, [(url, [state]), ...])
        return False, [("http://h:1/S/bad", ["could not connect"])]

    monkeypatch.setattr(
        "helao.hexagon.adapters.legacy.health.legacy_endpoints_available",
        fake_probe,
    )
    ad = LegacyHealthAdapter()
    out = await ad.endpoints_available(["http://h:1/S/ok", "http://h:1/S/bad"])
    assert out == [("http://h:1/S/ok", True), ("http://h:1/S/bad", False)]


def test_status_summary_extracts_driver_status_from_bound_orch():
    class _O:
        status_summary = {"SIM": ("idle", "ok"), "MOTOR": ("idle", "unknown")}

    ad = LegacyHealthAdapter()
    ad.bind_orch(_O())
    assert ad.status_summary() == {"SIM": "ok", "MOTOR": "unknown"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_adapter_health.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'helao.hexagon.adapters.legacy.health'`

- [ ] **Step 3: Write the implementation**

Create `helao/hexagon/adapters/legacy/health.py`:

```python
"""HealthPort adapter (first consumer of the P1a ``HealthPort`` Protocol,
ports/auxiliary.py) — P2a.

``endpoints_available`` wraps the legacy HEAD-probe helper
(``helao.helpers.dispatcher.endpoints_available``) and converts its
``(all_available, [(url, [state]), ...])`` return into the port's declared
``[(url, ok), ...]`` shape (adapter-local conversion; the port is P1a-owned
and unchanged). ``ping_action_servers``/``status_summary`` need the live
``Orch``'s ``ServerMonitor`` and ``status_summary`` attribute, which do not
exist at ``build_wiring`` time — the adapter is constructed unbound and
``graft_hexagon_loop`` binds the orch at startup (fail loud before that;
same late-binding rationale as ``_LazyServerLogger``). ``status_summary``
values on the orch are ``(status_str, driver_status)`` tuples; the port
wants the driver status string ('unknown' gates dispatch), so the adapter
projects the second element."""

from typing import Dict, List, Tuple

from helao.helpers.dispatcher import (
    endpoints_available as legacy_endpoints_available,
)

__all__ = ["LegacyHealthAdapter"]


class LegacyHealthAdapter:
    def __init__(self):
        self._orch = None

    def bind_orch(self, orch) -> None:
        self._orch = orch

    def _require_orch(self):
        if self._orch is None:
            raise RuntimeError(
                "LegacyHealthAdapter is not bound to a live Orch yet "
                "(graft_hexagon_loop binds it at startup)"
            )
        return self._orch

    async def endpoints_available(self, urls: List[str]) -> List[Tuple[str, bool]]:
        _, unavail = await legacy_endpoints_available(list(urls))
        bad = {u for u, _ in unavail}
        return [(u, u not in bad) for u in urls]

    # ping_action_servers/status_summary are Protocol-SATISFIERS with a
    # provisional projection: NOTHING consumes them in P2a (the monitor uses
    # only endpoints_available; the driver-health gate reads
    # orch.status_summary directly at orch_effects.py:206). Revisit the
    # projections when they gain a real consumer.
    async def ping_action_servers(self) -> Dict[str, str]:
        orch = self._require_orch()
        summary = await orch.server_monitor.ping_action_servers()
        return {k: status_str for k, (status_str, _driver) in summary.items()}

    def status_summary(self) -> Dict[str, str]:
        orch = self._require_orch()
        return {k: driver for k, (_status, driver) in orch.status_summary.items()}
```

Modify `helao/hexagon/app/wiring.py` — three edits:

1. Import (extend the existing auxiliary import line):

```python
from helao.hexagon.ports.auxiliary import HealthPort, StatePersistencePort
```

2. `ORCH_REQUIRED` (replace the tuple at `wiring.py:38-45`):

```python
ORCH_REQUIRED = (
    "config",
    "logging",
    "clock",
    "transport",
    "state_persistence",
    "status",
    "health",  # P2a: HexHealthMonitor + driver-health gate consume it
)
```

3. `PortWiring` field (add after `sample_state: Optional[SampleStatePort] = None`):

```python
    health: Optional[HealthPort] = None
```

Modify `helao/hexagon/app/factory.py` — add the import and wire it in `build_wiring`:

```python
from helao.hexagon.adapters.legacy.health import LegacyHealthAdapter
```

and in the `PortWiring(...)` construction inside `build_wiring` add:

```python
        health=LegacyHealthAdapter(),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_adapter_health.py helao/hexagon/tests/test_wiring.py helao/hexagon/tests/test_factory.py -v`
Expected: all PASS (the existing `test_wiring.py:35-36` asserts survive the growth: `ACTION_REQUIRED ⊆ ORCH_REQUIRED ∪ {transport}` still holds).

- [ ] **Step 5: pyright + black + commit**

```bash
conda run -n helao pyright helao/hexagon
conda run -n helao black helao/hexagon/adapters/legacy/health.py helao/hexagon/app/wiring.py helao/hexagon/app/factory.py helao/hexagon/tests/test_adapter_health.py
git add helao/hexagon/adapters/legacy/health.py helao/hexagon/app/wiring.py helao/hexagon/app/factory.py helao/hexagon/tests/test_adapter_health.py
git commit -m "feat(hexagon): LegacyHealthAdapter + health wiring slot (P2a T1)"
```

---

### Task 2: Domain — `HeartbeatFailed.dead_action_uuids` + `PruneDeadActions`

**Files:**
- Modify: `helao/hexagon/domain/orchestration.py` (event at `:134-139`, command block, `step()` at `:532-539`, `Command` union, `__all__`)
- Test: `helao/hexagon/tests/test_orchestration.py`

**Interfaces:**
- Consumes: existing reducer structures (`OrchestrationState`, `step`, `SetStopMessage`, `AlertOperator`).
- Produces: `HeartbeatFailed(message: str, dead_action_uuids: Tuple[str, ...] = ())`; `PruneDeadActions(action_uuids: Tuple[str, ...])` (frozen dataclass command). Task 5's executor and Task 6's monitor use these exact names/fields.

- [ ] **Step 1: Write the failing tests**

Append to `helao/hexagon/tests/test_orchestration.py` (it imports the module as `fsm` — match that idiom; if it imports names directly, add `PruneDeadActions`, `HeartbeatFailed`, `SetStopMessage`, `AlertOperator` to the imports instead):

```python
def test_heartbeat_failed_with_dead_uuids_orders_prune():
    """P2a item-6: a HeartbeatFailed carrying the dead server's active
    uuids must order PruneDeadActions AFTER the stop message + alert."""
    state = fsm.OrchestrationState(loop_state=LoopStatus.started)
    msg = "SIM/acquire endpoints are unavailable"
    new, cmds = fsm.step(
        state, fsm.HeartbeatFailed(message=msg, dead_action_uuids=("u-1", "u-2"))
    )
    assert new.loop_intent == LoopIntent.stop
    assert cmds == (
        fsm.SetStopMessage(message=msg),
        fsm.AlertOperator(message=msg),
        fsm.PruneDeadActions(action_uuids=("u-1", "u-2")),
    )


def test_heartbeat_failed_without_dead_uuids_is_unchanged_t12():
    """Back-compat: the no-uuid form keeps the exact pre-P2a T12 result."""
    state = fsm.OrchestrationState(loop_state=LoopStatus.started)
    new, cmds = fsm.step(state, fsm.HeartbeatFailed(message="m"))
    assert new.loop_intent == LoopIntent.stop
    assert cmds == (fsm.SetStopMessage(message="m"), fsm.AlertOperator(message="m"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_orchestration.py -v -k heartbeat`
Expected: FAIL with `TypeError: HeartbeatFailed.__init__() got an unexpected keyword argument 'dead_action_uuids'`

- [ ] **Step 3: Implement**

In `helao/hexagon/domain/orchestration.py`:

1. Replace the `HeartbeatFailed` dataclass (`:134-139`):

```python
@dataclass(frozen=True)
class HeartbeatFailed:
    """active_action_monitor probe failure (T12 + alert). P2a: carries the
    dead server's active action uuids (stringified) so the reducer can order
    a PruneDeadActions — the pure-hexagon dead-peer exit (decision Q3)."""

    message: str
    dead_action_uuids: Tuple[str, ...] = ()
```

2. Add the command after `InterruptWake` (`:330-333`):

```python
@dataclass(frozen=True)
class PruneDeadActions:
    """Dead-peer exit (item-6, P2a): pop the uuids from active_dict (global
    AND per-endpoint, like /clear_actives), bucket them finished-terminal,
    register history — makes legacy orch_wait_for_all_actions's
    actions_idle() true WITHOUT editing it (decision Q3)."""

    action_uuids: Tuple[str, ...]
```

3. Add `PruneDeadActions,` to the `Command` union and to `__all__` (next to `InterruptWake`).

4. Replace the `HeartbeatFailed` branch in `step()` (`:532-539`):

```python
    if isinstance(event, HeartbeatFailed):  # T12 (+ P2a dead-peer prune)
        cmds: Tuple[Command, ...] = (
            SetStopMessage(message=event.message),
            AlertOperator(message=event.message),
        )
        if event.dead_action_uuids:
            cmds = cmds + (PruneDeadActions(action_uuids=event.dead_action_uuids),)
        return replace(state, loop_intent=LoopIntent.stop), cmds
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_orchestration.py -v`
Expected: all PASS (existing reducer tests untouched by the default-valued field).

- [ ] **Step 5: pyright + black + commit**

```bash
conda run -n helao pyright helao/hexagon
conda run -n helao black helao/hexagon/domain/orchestration.py helao/hexagon/tests/test_orchestration.py
git add helao/hexagon/domain/orchestration.py helao/hexagon/tests/test_orchestration.py
git commit -m "feat(hexagon): HeartbeatFailed dead uuids + PruneDeadActions command (P2a T2)"
```

---

### Task 3: `HexStatusIngestion` — the ingestion runner bodies

**Files:**
- Create: `helao/hexagon/app/ingestion.py` (this task: `action_history_meta` + `HexStatusIngestion`; Task 6 appends `HexHealthMonitor` to the same file)
- Test: `helao/hexagon/tests/test_ingestion.py`

**Interfaces:**
- Consumes: `HexRuntime.handle(event)` (only as an awaited callable — tests use a spy); legacy live-orch surface at call time: `orch.aiolock`, `orch.globalstatusmodel` (`update_global_with_acts`/`find_hlostatus_in_finished`/`active_dict`/`loop_state`), `orch.register_action_uuid`, `orch.put_lbuf`, `orch.interrupt_q`, `orch.nonblocking`, `orch.active_experiment`, `orch.active_sequence`.
- Produces: `HexStatusIngestion(orch, runtime)` with `async update_status(actionservermodel=None) -> bool` and `async update_nonblocking(actionmodel, server_host, server_port) -> dict` (signatures endpoint-compatible with `orch_api.py:266-318`: `update_status` is called with the `actionservermodel=` keyword; `update_nonblocking` positionally). Module-level `action_history_meta(orch, act_model) -> dict` (Task 5's executor imports it function-locally).

- [ ] **Step 1: Write the failing tests**

Create `helao/hexagon/tests/test_ingestion.py`. Fixture fidelity (§10.1): real `GlobalStatusModel`/`ActionServerModel`/`EndpointModel`/`Action` models, never hand-rolled dicts.

```python
"""HexStatusIngestion (P2a T3): verbatim fold parity against the legacy
StatusIngester bodies, the elif-chain event selection evaluated on LIVE
loop_state, lock-held emission, and the two update_nonblocking wire quirks
(None-timestamp TypeError; unknown-exec_id ValueError)."""

import asyncio
from datetime import datetime
from uuid import uuid4

import pytest

from helao.core.models.hlostatus import HloStatus
from helao.core.models.machine import MachineModel
from helao.core.models.orchstatus import LoopStatus, OrchStatus
from helao.core.models.server import (
    ActionServerModel,
    EndpointModel,
    GlobalStatusModel,
)
from helao.helpers.premodels import Action
from helao.hexagon.app.ingestion import HexStatusIngestion, action_history_meta
from helao.hexagon.domain.orchestration import (
    ErroredUuidIngested,
    EstoppedUuidIngested,
    StatusChanged,
)

ORCH_M = MachineModel(server_name="ORCH", machine_name="testhost")
# Action.url is a COMPUTED read-only property (helao/core/models/action.py:
# 167-170): f"http://{action_server.hostname}:{action_server.port}/
# {action_server.server_name}/{action_name}" — NOT a settable field. The
# fixture's MachineModel MUST carry hostname/port or actmod.url computes to
# "http://None:None/SIM/..." and every url string-match downstream (the T6
# monitor probe, the launched item-6) silently misses.
SIM_M = MachineModel(
    server_name="SIM", machine_name="testhost", hostname="127.0.0.1", port=8002
)


class _RuntimeSpy:
    """Records events; also snapshots whether aiolock was held at emission."""

    def __init__(self, orch=None):
        self.orch = orch
        self.events = []
        self.locked_at_emit = []

    async def handle(self, event):
        self.events.append(event)
        if self.orch is not None:
            self.locked_at_emit.append(self.orch.aiolock.locked())


class _IngestOrch:
    """Call-time legacy-orch surface for ingestion (real GlobalStatusModel)."""

    def __init__(self):
        self.aiolock = asyncio.Lock()
        self.globalstatusmodel = GlobalStatusModel(orchestrator=ORCH_M)
        self.interrupt_q = asyncio.Queue()
        self.nonblocking = []
        self.active_experiment = None
        self.active_sequence = None
        self.registered = {}
        self.lbuf = []

    def register_action_uuid(self, action_uuid, action_dict):
        self.registered[action_uuid] = action_dict

    async def put_lbuf(self, live_dict):
        self.lbuf.append(live_dict)


def _act(uuid, statuses):
    # no url= kwarg: url is a computed property (see SIM_M note above);
    # pydantic would silently ignore the kwarg
    return Action(
        action_uuid=uuid,
        action_name="acquire",
        action_status=list(statuses),
        action_server=SIM_M,
        orchestrator=ORCH_M,
        action_timestamp=datetime.now(),
    )


def test_act_fixture_url_matches_monitor_probe_target():
    """Guards the whole T6/item-6 chain: if the MachineModel loses its
    hostname/port, actmod.url no longer matches the probe target and the
    dead-peer detection silently never fires."""
    act = _act(uuid4(), [HloStatus.active])
    assert act.url == "http://127.0.0.1:8002/SIM/acquire"


def _asm(act, active=True, last=None):
    ep = EndpointModel(endpoint_name="acquire")
    if active:
        ep.active_dict[act.action_uuid] = act
    else:
        ep.nonactive_dict.setdefault(HloStatus.finished, {})[act.action_uuid] = act
    return ActionServerModel(
        action_server=SIM_M, endpoints={"acquire": ep}, last_action_uuid=last
    )


def _make():
    orch = _IngestOrch()
    spy = _RuntimeSpy(orch)
    return orch, spy, HexStatusIngestion(orch, spy)


@pytest.mark.asyncio
async def test_none_model_returns_false_without_side_effects():
    orch, spy, ing = _make()
    assert await ing.update_status(actionservermodel=None) is False
    assert spy.events == [] and orch.interrupt_q.empty()


@pytest.mark.asyncio
async def test_active_fold_emits_busy_statuschanged_and_wakes():
    orch, spy, ing = _make()
    u = uuid4()
    assert await ing.update_status(actionservermodel=_asm(_act(u, [HloStatus.active])))
    assert u in orch.globalstatusmodel.active_dict
    assert spy.events == [StatusChanged(any_active=True)]
    assert spy.locked_at_emit == [True]  # emitted INSIDE aiolock (parity)
    assert orch.interrupt_q.get_nowait() is orch.globalstatusmodel
    # DD-2: ingestion itself no longer writes orch_state
    assert orch.globalstatusmodel.orch_state == OrchStatus.idle


@pytest.mark.asyncio
async def test_finished_fold_emits_idle_and_puts_lbuf():
    orch, spy, ing = _make()
    u = uuid4()
    await ing.update_status(actionservermodel=_asm(_act(u, [HloStatus.active])))
    fin = _act(u, [HloStatus.active, HloStatus.finished])
    await ing.update_status(actionservermodel=_asm(fin, active=False, last=u))
    assert spy.events[-1] == StatusChanged(any_active=False)
    assert orch.lbuf == [{u: {"status": HloStatus.finished.name}}]
    # last_action_uuid registration ran with the formatted-timestamp meta
    assert orch.registered[u]["action_name"] == "acquire"
    assert orch.registered[u]["action_timestamp"].strip()


@pytest.mark.asyncio
async def test_estopped_uuid_while_started_emits_estop_event_only():
    orch, spy, ing = _make()
    orch.globalstatusmodel.loop_state = LoopStatus.started
    u = uuid4()
    est = _act(u, [HloStatus.active, HloStatus.finished, HloStatus.estopped])
    await ing.update_status(actionservermodel=_asm(est, active=False))
    assert len(spy.events) == 1
    ev = spy.events[0]
    assert isinstance(ev, EstoppedUuidIngested)
    assert ev.reason.startswith("E-STOP due to action uuid(s): ")
    assert str(u) in ev.reason


@pytest.mark.asyncio
async def test_estopped_uuid_while_stopped_falls_through_to_statuschanged():
    """Legacy elif chain: the estop branch is guarded on started — a
    stopped-loop fold with estopped uuids lands idle/busy instead."""
    orch, spy, ing = _make()
    u = uuid4()
    est = _act(u, [HloStatus.active, HloStatus.finished, HloStatus.estopped])
    await ing.update_status(actionservermodel=_asm(est, active=False))
    assert spy.events == [StatusChanged(any_active=False)]


@pytest.mark.asyncio
async def test_errored_uuid_while_started_emits_errored_event():
    orch, spy, ing = _make()
    orch.globalstatusmodel.loop_state = LoopStatus.started
    u = uuid4()
    err = _act(u, [HloStatus.active, HloStatus.finished, HloStatus.errored])
    await ing.update_status(actionservermodel=_asm(err, active=False))
    assert spy.events == [ErroredUuidIngested()]


@pytest.mark.asyncio
async def test_update_nonblocking_active_appends_and_wakes():
    orch, spy, ing = _make()
    u = uuid4()
    act = _act(u, [HloStatus.active])
    act.exec_id = "acquire exec1"
    out = await ing.update_nonblocking(act, "127.0.0.1", 8002)
    assert out == {"success": True}
    assert orch.nonblocking == [("SIM", "acquire exec1", "127.0.0.1", 8002)]
    assert u in orch.registered
    assert not orch.interrupt_q.empty()


@pytest.mark.asyncio
async def test_update_nonblocking_unknown_exec_id_raises_valueerror():
    """Spec §7.4 wire quirk: list.remove on an unknown exec_id raises —
    reproduced, not guarded."""
    orch, _spy, ing = _make()
    u = uuid4()
    act = _act(u, [HloStatus.finished])
    act.exec_id = "acquire exec1"
    with pytest.raises(ValueError):
        await ing.update_nonblocking(act, "127.0.0.1", 8002)


@pytest.mark.asyncio
async def test_update_nonblocking_none_timestamp_raises_typeerror():
    """status.py third-drift quirk: the %-format f-string rejects None."""
    orch, _spy, ing = _make()
    act = _act(uuid4(), [HloStatus.active])
    act.exec_id = "acquire exec1"
    act.action_timestamp = None
    with pytest.raises(TypeError):
        await ing.update_nonblocking(act, "127.0.0.1", 8002)


def test_action_history_meta_matches_legacy_shape():
    orch = _IngestOrch()
    act = _act(uuid4(), [HloStatus.active])
    meta = action_history_meta(orch, act)
    assert set(meta) == {
        "action_name",
        "action_params",
        "action_status",
        "action_server",
        "action_timestamp",
        "action_finished_timestamp",
        "experiment_name",
        "experiment_uuid",
        "sequence_name",
        "sequence_label",
        "sequence_uuid",
    }
    assert meta["action_server"] == "SIM"
    assert meta["action_finished_timestamp"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_ingestion.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'helao.hexagon.app.ingestion'`

- [ ] **Step 3: Write the implementation**

Create `helao/hexagon/app/ingestion.py`:

```python
"""Hexagon status ingestion (P2a): native replacement for the legacy
``StatusIngester`` short-circuit (helao/core/servers/orch_status_sync.py).

``HexStatusIngestion.update_status``/``update_nonblocking`` own the endpoint
bodies once ``graft_hexagon_loop`` rebinds them onto the live legacy ``Orch``
(instance rebind — the sanctioned wrap seam; NO legacy source edit). The
fold still lands in the legacy ``GlobalStatusModel`` via
``update_global_with_acts`` (replacing the status model is NOT P2a); the
inline estop/error/idle/busy REACTION (orch_status_sync.py:265-285) moves
into domain events — ``EstoppedUuidIngested`` / ``ErroredUuidIngested`` /
``StatusChanged`` — handled by the pure reducer, whose ``apply_state_delta``
is the sole ``orch_state`` writer (DD-2). The legacy elif chain is
replicated HERE with live ``loop_state`` so exactly ONE event fires per fold
(the reducer's own started-guards are a second net, not the selector).

Lock/queue ownership (two-owner invariant; the orch_status_sync.py:23-43 map
carries over): ``aiolock`` is acquired by ``update_status`` (ingestion) and
the dispatch critical section — nobody else; events are emitted INSIDE the
lock exactly where the legacy inline block ran, so the interleaving
guarantees (and the estop cascade running under the lock, as legacy
``estop_loop`` did) are unchanged. ``interrupt_q`` is written here (the
unconditional trailing ``globalstatusmodel`` put) and by the health monitor;
``globstat_q`` stays on the legacy broadcaster (``ws_globstat``/
``globstat_broadcast_task`` are NOT rebound). ``clear_nonblocking`` is NOT
rebound either — its wire behavior is untouched.

Wire quirks reproduced, not fixed (spec §7.4): ``update_nonblocking``'s
%-format f-string raises ``TypeError`` on a ``None`` ``action_timestamp``
(the status-adapter "third drift"), and ``list.remove`` raises ``ValueError``
on an unknown exec_id. Like the legacy ``StatusIngester``, this class caches
no shared mutable state — it holds only the ``orch``/``runtime`` refs and
resolves every attribute at call time (``import_queues`` reassignment of
``globalstatusmodel`` is always observed)."""

from typing import Optional

from helao.hexagon.app.orch_effects import _LazyServerLogger
from helao.hexagon.domain.models import HloStatus, LoopStatus
from helao.hexagon.domain.orchestration import (
    ErroredUuidIngested,
    EstoppedUuidIngested,
    StatusChanged,
)

LOGGER = _LazyServerLogger()

__all__ = ["HexStatusIngestion", "action_history_meta"]


def action_history_meta(orch, act_model) -> dict:
    """The legacy register_action_uuid meta dict, byte-identical output
    (orch_status_sync.py duplicated this block in update_nonblocking and
    update_status; factored once here, also reused by the PruneDeadActions
    executor). Deliberately keeps the legacy %-format f-string: a ``None``
    ``action_timestamp`` raises TypeError, same as the legacy endpoint."""
    matching_experiment = (
        orch.active_experiment is not None
        and orch.active_experiment.experiment_uuid == act_model.experiment_uuid
    )
    return {
        "action_name": act_model.action_name,
        "action_params": act_model.action_params,
        "action_status": act_model.action_status,
        "action_server": act_model.action_server.server_name,
        "action_timestamp": f"{act_model.action_timestamp: %m-%d %H:%M:%S}",
        "action_finished_timestamp": (
            f"{act_model.action_finished_timestamp: %m-%d %H:%M:%S}"
            if act_model.action_finished_timestamp is not None
            else None
        ),
        "experiment_name": (
            orch.active_experiment.experiment_name if matching_experiment else None
        ),
        "experiment_uuid": act_model.experiment_uuid,
        "sequence_name": (
            orch.active_sequence.sequence_name
            if orch.active_sequence is not None and matching_experiment
            else None
        ),
        "sequence_label": (
            orch.active_sequence.sequence_label
            if orch.active_sequence is not None and matching_experiment
            else None
        ),
        "sequence_uuid": (
            orch.active_sequence.sequence_uuid
            if orch.active_sequence is not None and matching_experiment
            else None
        ),
    }


class HexStatusIngestion:
    """Owns the rebound ``update_status``/``update_nonblocking`` bodies."""

    def __init__(self, orch, runtime):
        self.orch = orch
        self.runtime = runtime

    async def update_nonblocking(
        self, actionmodel, server_host: str, server_port: int
    ) -> dict:
        """Verbatim port of StatusIngester.update_nonblocking (no aiolock,
        same as legacy): register the uuid, append/remove the executor
        registry entry (ValueError quirk propagates), wake the loop."""
        orch = self.orch
        orch.register_action_uuid(
            actionmodel.action_uuid, action_history_meta(orch, actionmodel)
        )
        server_key = actionmodel.action_server.server_name
        server_exec_id = (server_key, actionmodel.exec_id, server_host, server_port)
        if "active" in actionmodel.action_status:
            orch.nonblocking.append(server_exec_id)
        else:
            orch.nonblocking.remove(server_exec_id)
        # put an empty object in interrupt_q to trigger orch dispatch loop
        await orch.interrupt_q.put(orch.globalstatusmodel)
        return {"success": True}

    async def update_status(self, actionservermodel=None) -> bool:
        """Fold + register (verbatim legacy), then emit exactly one domain
        event per the legacy elif chain instead of mutating orch_state."""
        orch = self.orch

        if actionservermodel is None:
            return False

        async with orch.aiolock:
            if actionservermodel.last_action_uuid is not None:
                # find last action uuid in action server model:
                for (
                    endpoint_name,
                    endpoint_model,
                ) in actionservermodel.endpoints.items():
                    for status, act_dict in endpoint_model.nonactive_dict.items():
                        for act_uuid, act_model in act_dict.items():
                            if act_uuid == actionservermodel.last_action_uuid:
                                orch.register_action_uuid(
                                    act_uuid, action_history_meta(orch, act_model)
                                )
                                break

            recent_nonactive = orch.globalstatusmodel.update_global_with_acts(
                actionservermodel=actionservermodel
            )
            for act_uuid, act_status in recent_nonactive:
                await orch.put_lbuf({act_uuid: {"status": act_status}})

            estop_uuids = orch.globalstatusmodel.find_hlostatus_in_finished(
                hlostatus=HloStatus.estopped,
            )
            error_uuids = orch.globalstatusmodel.find_hlostatus_in_finished(
                hlostatus=HloStatus.errored,
            )

            if (
                estop_uuids
                and orch.globalstatusmodel.loop_state == LoopStatus.started
            ):
                # message shape matches the grafted hex_estop_loop's
                # "E-STOP <reason>" (legacy: estop_loop(reason=...))
                await self.runtime.handle(
                    EstoppedUuidIngested(
                        reason=f"E-STOP due to action uuid(s): {estop_uuids}"
                    )
                )
            elif (
                error_uuids
                and orch.globalstatusmodel.loop_state == LoopStatus.started
            ):
                await self.runtime.handle(ErroredUuidIngested())
            else:
                any_active = bool(orch.globalstatusmodel.active_dict)
                if any_active:
                    LOGGER.info(
                        f"running_states: {orch.globalstatusmodel.active_dict}"
                    )
                await self.runtime.handle(StatusChanged(any_active=any_active))

            # now push it to the interrupt_q (unconditional legacy tail wake)
            await orch.interrupt_q.put(orch.globalstatusmodel)

            return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_ingestion.py -v`
Expected: all PASS. Field-name facts baked into the fixtures (verified against source, do not re-derive): `Action.orchestrator` is a real field (`server.py:263` compares it), `Action.url` is a READ-ONLY computed `@property` (`helao/core/models/action.py:167-170`) built from `action_server.hostname`/`port`/`server_name` + `action_name` — which is why `SIM_M` carries `hostname="127.0.0.1", port=8002` and `_act` takes no `url=` kwarg; `test_act_fixture_url_matches_monitor_probe_target` pins this. If it fails, fix the `MachineModel` construction, never by trying to set `url`.

- [ ] **Step 5: pyright + black + commit**

```bash
conda run -n helao pyright helao/hexagon
conda run -n helao black helao/hexagon/app/ingestion.py helao/hexagon/tests/test_ingestion.py
git add helao/hexagon/app/ingestion.py helao/hexagon/tests/test_ingestion.py
git commit -m "feat(hexagon): HexStatusIngestion runner — fold + event emission (P2a T3)"
```

---

### Task 4: DD-2 atomic hand-off — `apply_state_delta` orch_state write-back + graft rebind

**Files:**
- Modify: `helao/hexagon/app/orch_effects.py:105-131` (`apply_state_delta`)
- Modify: `helao/hexagon/app/dispatch_loop.py:144-228` (`HexagonGraft` fields + `graft_hexagon_loop` rebind set)
- Test: `helao/hexagon/tests/test_orch_effects.py` (delta test + `_StubOrch` growth), `helao/hexagon/tests/test_dispatch_loop.py` (rebind test)

**Interfaces:**
- Consumes: `HexStatusIngestion` (Task 3).
- Produces: `HexagonGraft.ingestion: Optional[HexStatusIngestion]`; `orch.update_status`/`orch.update_nonblocking` rebound to the ingestion runner; `apply_state_delta` writes `orch_state` deltas back. Task 6 extends the same graft with the monitor.

**ATOMICITY (Global Constraint):** both edits land in THIS one task/commit. The rebind removes the legacy `orch_state` writers at the same instant the write-back activates — no double-writer window.

**Deferred proof note:** from this task on, `update_status` emits `EstoppedUuidIngested` through the real runtime while HOLDING `orch.aiolock`. The re-entrancy regression test proving the estop cascade never re-acquires the lock (`test_estop_cascade_under_aiolock_does_not_deadlock`) lands in Task 6 where its `_MonitorOrch` fixture lives — Task 8's full-suite gate covers the combination.

- [ ] **Step 1: Write the failing tests**

Append to `helao/hexagon/tests/test_orch_effects.py`:

```python
@pytest.mark.asyncio
async def test_apply_state_delta_writes_orch_state_back_dd2():
    """P2a DD-2: the reducer delta is now the SOLE orch_state writer.
    Unguarded overwrite is deliberate legacy parity: the legacy inline
    chain always overwrote orch_state with idle/busy on a fold."""
    orch = _StubOrch()
    old = OrchestrationState(orch_state=OrchStatus.idle)
    new = OrchestrationState(orch_state=OrchStatus.busy)
    await apply_state_delta(orch, old, new)
    assert orch.globalstatusmodel.orch_state == OrchStatus.busy


@pytest.mark.asyncio
async def test_apply_state_delta_skips_unchanged_orch_state():
    orch = _StubOrch()
    orch.globalstatusmodel.orch_state = OrchStatus.busy  # live drifted
    st = OrchestrationState(orch_state=OrchStatus.idle)
    await apply_state_delta(orch, st, st)  # no delta -> no write
    assert orch.globalstatusmodel.orch_state == OrchStatus.busy
```

(Ensure `OrchestrationState` and `OrchStatus` are in this file's imports; add them if missing.)

Append to `helao/hexagon/tests/test_dispatch_loop.py`:

```python
@pytest.mark.asyncio
async def test_graft_rebinds_status_ingestion_endpoints():
    """P2a: graft_hexagon_loop extends the instance-rebind set with
    update_status/update_nonblocking (DD-2 atomic hand-off)."""
    orch = _ScriptedOrch()
    graft = graft_hexagon_loop(orch, PortWiring(logging=_AlertSpy()))
    assert graft.ingestion is not None
    assert orch.update_status.__func__ is type(graft.ingestion).update_status
    assert (
        orch.update_nonblocking.__func__
        is type(graft.ingestion).update_nonblocking
    )
    assert "update_status" in graft.originals
    await graft.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_orch_effects.py helao/hexagon/tests/test_dispatch_loop.py -v -k "dd2 or unchanged_orch_state or rebinds_status"`
Expected: FAIL — delta tests fail on the missing write-back (`orch_state` stays `idle`); the graft test fails with `AttributeError: 'HexagonGraft' object has no attribute 'ingestion'`.

- [ ] **Step 3: Implement**

1. `helao/hexagon/app/orch_effects.py` — replace `apply_state_delta` (`:105-131`) with:

```python
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
    orch_state written back since P2a (the ingestion rebind removed the
    legacy StatusIngester's inline writers at the same instant — sole-writer
    property). The orch_state write is deliberately UNGUARDED against a live
    estopped value: the legacy inline chain always overwrote orch_state with
    idle/busy on any fold (its estop branch is started-guarded), so the
    reducer's StatusChanged must keep doing the same."""
    gsm = orch.globalstatusmodel
    if not skip_loop_state and new.loop_state != old.loop_state:
        live = gsm.loop_state
        if live == LoopStatus.estopped and old.loop_state != LoopStatus.estopped:
            LOGGER.info("concurrent E-STOP observed; loop_state write suppressed")
        else:
            gsm.loop_state = new.loop_state
    if new.orch_state != old.orch_state:
        gsm.orch_state = new.orch_state
    if new.loop_intent != old.loop_intent:
        intender = {
            LoopIntent.stop: orch.intend_stop,
            LoopIntent.skip: orch.intend_skip,
            LoopIntent.estop: orch.intend_estop,
            LoopIntent.none: orch.intend_none,
        }[new.loop_intent]
        await intender()
```

2. `helao/hexagon/app/dispatch_loop.py` — add the import:

```python
from helao.hexagon.app.ingestion import HexStatusIngestion
```

add the field to `HexagonGraft` (after `originals`):

```python
    ingestion: Optional[HexStatusIngestion] = None
```

(add `Optional` to the `typing` import line), and modify `graft_hexagon_loop`: construct + attach the runner, save originals tolerantly (test stubs lack the legacy delegators), and rebind. Replace the construction/originals block at the top of the function with:

```python
    effects = OrchCommandRunner(orch, wiring)
    runtime = HexRuntime(orch, effects)
    loop = HexDispatchLoop(runtime)
    ingestion = HexStatusIngestion(orch, runtime)
    graft = HexagonGraft(
        runtime=runtime, loop=loop, effects=effects, ingestion=ingestion
    )
    for name in (
        "start",
        "start_loop",
        "stop",
        "skip",
        "estop_loop",
        "clear_estop",
        "clear_error",
        "update_status",
        "update_nonblocking",
    ):
        graft.originals[name] = getattr(orch, name, None)
```

and immediately after the existing `orch.clear_error = hex_clear_error` line add:

```python
    # P2a DD-2 atomic hand-off: this rebind removes the legacy
    # StatusIngester's inline orch_state writes at the same instant the
    # reducer's apply_state_delta write-back takes them — no double-writer
    # window. clear_nonblocking / ws_globstat / globstat_broadcast_task stay
    # legacy (out of P2a scope).
    orch.update_status = ingestion.update_status
    orch.update_nonblocking = ingestion.update_nonblocking
```

- [ ] **Step 4: Run the FULL suite to verify pass (rebind touches everything)**

Run: `conda run -n helao python -m pytest helao/hexagon/tests -x -q --ignore=helao/hexagon/tests/test_concurrency_live.py --ignore=helao/hexagon/tests/test_live_group.py`
Expected: all PASS (existing graft/effect/estop tests must survive the rebind and the orch_state write-back; `test_estop_policy.py` asserts around estop state — if one pins `orch_state` staying idle under estop, update it to the documented delta #3 with a comment referencing this plan).

- [ ] **Step 5: pyright + black + commit**

```bash
conda run -n helao pyright helao/hexagon
conda run -n helao black helao/hexagon/app/orch_effects.py helao/hexagon/app/dispatch_loop.py helao/hexagon/tests/test_orch_effects.py helao/hexagon/tests/test_dispatch_loop.py
git add -A helao/hexagon
git commit -m "feat(hexagon): DD-2 atomic hand-off — ingestion rebind + orch_state write-back (P2a T4)"
```

---

### Task 5: `PruneDeadActions` executor + health-aware history-poll break

**Files:**
- Modify: `helao/hexagon/app/orch_effects.py` (`OrchCommandRunner.__init__`, `DispatchHeadAction` branch at `:151-167`, new `PruneDeadActions` branch, imports)
- Test: `helao/hexagon/tests/test_orch_effects.py`

**Interfaces:**
- Consumes: `PruneDeadActions(action_uuids)` (Task 2); `action_history_meta` (Task 3, imported function-locally to avoid an import cycle — `ingestion.py` imports `_LazyServerLogger` from this module).
- Produces: `OrchCommandRunner.pruned_uuids: set` (stringified uuids) — the history poll breaks on membership; the executor moves uuids out of `gsm.active_dict` AND every `server_dict` endpoint `active_dict` (else the next fold's `_sort_status` would resurrect them — `server.py:262-264`), buckets them `finished`-terminal, registers history. Task 6's monitor relies on `actions_idle()` being true after the prune.

- [ ] **Step 1: Write the failing tests**

Append to `helao/hexagon/tests/test_ingestion.py` (it already has the real-model builders; the executor tests need them):

```python
from uuid import UUID

from helao.hexagon.app.orch_effects import OrchCommandRunner
from helao.hexagon.app.wiring import PortWiring
from helao.hexagon.domain.orchestration import PruneDeadActions


class _CountingLock:
    """asyncio.Lock wrapper counting acquisitions (two-owner invariant)."""

    def __init__(self):
        self._lock = asyncio.Lock()
        self.acquisitions = 0

    def locked(self):
        return self._lock.locked()

    async def __aenter__(self):
        self.acquisitions += 1
        return await self._lock.__aenter__()

    async def __aexit__(self, *exc):
        return await self._lock.__aexit__(*exc)


@pytest.mark.asyncio
async def test_prune_dead_actions_unblocks_actions_idle_and_registers():
    orch, spy, ing = _make()
    u = uuid4()
    # fold an active action in (populates gsm.active_dict AND server_dict)
    await ing.update_status(actionservermodel=_asm(_act(u, [HloStatus.active])))
    gsm = orch.globalstatusmodel
    assert not gsm.actions_idle()
    runner = OrchCommandRunner(orch, PortWiring())
    await runner.execute(PruneDeadActions(action_uuids=(str(u),)))
    assert gsm.actions_idle()  # global active_dict pruned
    # per-endpoint active_dict pruned too (else the next fold resurrects it)
    for asm in gsm.server_dict.values():
        for ep in asm.endpoints.values():
            assert u not in ep.active_dict
    # terminal status injected + finished-bucketed + history registered
    pruned = gsm.nonactive_dict[HloStatus.finished][u]
    assert HloStatus.finished in pruned.action_status
    assert pruned.action_finished_timestamp is not None
    assert u in orch.registered
    assert orch.registered[u]["action_finished_timestamp"] is not None
    assert str(u) in runner.pruned_uuids


@pytest.mark.asyncio
async def test_prune_unknown_uuid_is_a_noop():
    orch, _spy, _ing = _make()
    runner = OrchCommandRunner(orch, PortWiring())
    await runner.execute(PruneDeadActions(action_uuids=(str(uuid4()),)))
    assert orch.registered == {}


@pytest.mark.asyncio
async def test_two_lock_owner_invariant_prune_never_takes_aiolock():
    """aiolock owners are ingestion + dispatch critical section ONLY: one
    update_status = exactly one acquisition; the prune adds none."""
    orch, spy, ing = _make()
    orch.aiolock = _CountingLock()
    u = uuid4()
    await ing.update_status(actionservermodel=_asm(_act(u, [HloStatus.active])))
    assert orch.aiolock.acquisitions == 1
    runner = OrchCommandRunner(orch, PortWiring())
    await runner.execute(PruneDeadActions(action_uuids=(str(u),)))
    assert orch.aiolock.acquisitions == 1
```

Append to `helao/hexagon/tests/test_orch_effects.py`:

```python
@pytest.mark.asyncio
async def test_dispatch_head_action_poll_breaks_on_pruned_uuid():
    """P2a health-aware exit (Q3): the history poll must not spin forever
    when the dispatched uuid was pruned as dead."""
    orch = _StubOrch()
    orch.last_dispatched_action_uuid = "dead-uuid"
    orch.action_history = {}  # never fed — the legacy hang mode
    runner = OrchCommandRunner(orch, PortWiring(logging=_AlertSpy()))
    runner.pruned_uuids.add("dead-uuid")
    rc = await asyncio.wait_for(runner.execute(DispatchHeadAction()), timeout=3.0)
    assert rc == ErrorCodes.none
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_ingestion.py helao/hexagon/tests/test_orch_effects.py -v -k "prune or two_lock or breaks_on_pruned"`
Expected: prune tests FAIL at the final `AssertionError: unhandled reducer command: PruneDeadActions(...)`; the poll test FAILS with `asyncio.TimeoutError`.

- [ ] **Step 3: Implement**

In `helao/hexagon/app/orch_effects.py`:

1. Add imports: `PruneDeadActions` to the `domain.orchestration` import block; add to the top of the file:

```python
from datetime import datetime
from uuid import UUID
```

2. `OrchCommandRunner.__init__` (`:135-138`) — add the pruned registry:

```python
    def __init__(self, orch, wiring: PortWiring):
        self.orch = orch
        self.wiring = wiring
        self.policy = DispatchPolicy()
        # P2a: stringified uuids pruned by PruneDeadActions — the
        # DispatchHeadAction history poll's health-aware exit (Q3)
        self.pruned_uuids: set = set()
```

3. `DispatchHeadAction` branch — replace the poll (`:160-161`) with:

```python
            # history poll (orch_dispatch.py:621-622) — ingestion registers
            # the uuid. P2a health-aware exit (Q3): a dead peer's pruned
            # uuid breaks the poll (the prune also registers history, so
            # either condition releases it).
            while orch.last_dispatched_action_uuid not in orch.action_history.keys():
                if str(orch.last_dispatched_action_uuid) in self.pruned_uuids:
                    break
                await asyncio.sleep(0.2)
```

4. Add the executor branch just before the final `raise AssertionError(...)`:

```python
        if isinstance(cmd, PruneDeadActions):
            # item-6 dead-peer exit (Q3, pure-hexagon): move the dead
            # server's uuids out of EVERY active_dict (global + per-endpoint,
            # like /clear_actives — a global-only pop would be resurrected by
            # the next fold's _sort_status) into the finished bucket with a
            # terminal status, and register them in action_history so the
            # history poll and non-blank-history asserts hold. Runs WITHOUT
            # aiolock: fully synchronous on the event loop, and taking the
            # lock here would add a third owner (invariant: ingestion +
            # dispatch critical section only).
            from helao.hexagon.app.ingestion import action_history_meta

            now = datetime.now()
            for uuid_str in cmd.action_uuids:
                act_uuid = UUID(uuid_str)
                act = gsm.active_dict.pop(act_uuid, None)
                for asm in gsm.server_dict.values():
                    for epm in asm.endpoints.values():
                        ep_act = epm.active_dict.pop(act_uuid, None)
                        if act is None and ep_act is not None:
                            act = ep_act
                self.pruned_uuids.add(uuid_str)
                if act is None:
                    LOGGER.warning(
                        f"PruneDeadActions: uuid {uuid_str} not in any "
                        "active_dict; nothing to prune"
                    )
                    continue
                if HloStatus.finished not in act.action_status:
                    # guarded-status idiom (action.py:172), not a raw append
                    act.append_action_status(HloStatus.finished)
                if act.action_finished_timestamp is None:
                    act.action_finished_timestamp = now
                if HloStatus.finished not in gsm.nonactive_dict:
                    gsm.nonactive_dict[HloStatus.finished] = {}
                gsm.nonactive_dict[HloStatus.finished][act_uuid] = act
                if act.action_timestamp is not None:
                    orch.register_action_uuid(
                        act_uuid, action_history_meta(orch, act)
                    )
                LOGGER.warning(
                    f"pruned dead-peer action {uuid_str} "
                    f"({act.action_server.server_name}/{act.action_name})"
                )
            return None
```

Note the `test_prune_unknown_uuid_is_a_noop` expectation: `registered` stays empty but `pruned_uuids` still records the uuid (harmless; the poll break must work even if the fold never landed).

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_ingestion.py helao/hexagon/tests/test_orch_effects.py -v`
Expected: all PASS.

- [ ] **Step 5: pyright + black + commit**

```bash
conda run -n helao pyright helao/hexagon
conda run -n helao black helao/hexagon/app/orch_effects.py helao/hexagon/tests/test_ingestion.py helao/hexagon/tests/test_orch_effects.py
git add helao/hexagon/app/orch_effects.py helao/hexagon/tests/test_ingestion.py helao/hexagon/tests/test_orch_effects.py
git commit -m "feat(hexagon): PruneDeadActions executor + health-aware history-poll exit (P2a T5)"
```

---

### Task 6: `HexHealthMonitor` + heartbeat swap + `DriverHealthUnrecovered` feed

**Files:**
- Modify: `helao/hexagon/app/ingestion.py` (append `HexHealthMonitor`)
- Modify: `helao/hexagon/app/dispatch_loop.py` (graft: bind health adapter, cancel legacy heartbeat task, start monitor; `HexRuntime`: exhaustion → `DriverHealthUnrecovered`)
- Modify: `helao/hexagon/app/orch_effects.py` (`RetryDriverHealth` branch → `execute_retry_driver_health` returning the remainder; `DRIVER_HEALTH_RETRY_DELAY_S` seam)
- Test: `helao/hexagon/tests/test_ingestion.py`, `helao/hexagon/tests/test_dispatch_loop.py`

**Interfaces:**
- Consumes: `HealthPort.endpoints_available` (Task 1); `HeartbeatFailed(message, dead_action_uuids)` + `StatusChanged` (Task 2/3); `PruneDeadActions` executor (Task 5); `HexRuntime.handle`.
- Produces: `HexHealthMonitor(orch, runtime, health)` with `start()`, `async close()`, `async probe_once()`; `HexagonGraft.health_monitor: Optional[HexHealthMonitor]`; `OrchCommandRunner.execute_retry_driver_health(cmd) -> Tuple[str, ...]` (remaining unknown drivers); module constant `DRIVER_HEALTH_RETRY_DELAY_S = 5`.
- Also delivered here (required-fix regression tests, real-runtime/non-spy): the dead-peer RACE test proving the prune → `StatusChanged` → wake ordering parks the REAL `HexRuntime`+`HexDispatchLoop` stop-drain without a hang, and the estop-under-`aiolock` re-entrancy test proving the `EstoppedUuidIngested` cascade never re-acquires `orch.aiolock` (retro-covers Task 4's rebind — the behavior exists from T4, the fixtures live here).

- [ ] **Step 1: Write the failing tests**

Append to `helao/hexagon/tests/test_ingestion.py`:

```python
from helao.core.models.orchstatus import LoopIntent
from helao.hexagon.app.dispatch_loop import HexDispatchLoop, HexRuntime
from helao.hexagon.app.ingestion import HexHealthMonitor
from helao.hexagon.domain.orchestration import StartRequested


class _FakeHealth:
    def __init__(self, bad=()):
        self.bad = set(bad)

    async def endpoints_available(self, urls):
        return [(u, u not in self.bad) for u in urls]

    async def ping_action_servers(self):
        return {}

    def status_summary(self):
        return {}


class _AlertSpy:
    def __init__(self):
        self.alerts = []

    def alert(self, msg):
        self.alerts.append(msg)


class _MonitorOrch(_IngestOrch):
    """Full-enough legacy surface for HexRuntime over a real GSM. The
    drain/estop members are FAITHFUL ports of the legacy bodies (not
    conveniences): the two required-fix regression tests below exercise the
    real WaitAllActionsIdle executor and the real estop cascade against
    them, and their hang modes only exist if these behave like legacy."""

    def __init__(self):
        super().__init__()
        self.heartbeat_interval = 0.05
        self.ignore_heartbeats = []
        self.current_stop_message = ""
        self.active_run_id = "RUN"
        self.action_dq, self.experiment_dq, self.sequence_dq = [], [], []
        self.status_summary = {}
        self.step_thru_actions = False
        self.step_thru_experiments = False
        self.step_thru_sequences = False

    # all four intend_* put the intent on interrupt_q, like the real
    # Orch (orch.py:536-571) — the drain path's intend_none wake matters
    async def intend_stop(self):
        self.globalstatusmodel.loop_intent = LoopIntent.stop
        await self.interrupt_q.put(self.globalstatusmodel.loop_intent)

    async def intend_skip(self):
        self.globalstatusmodel.loop_intent = LoopIntent.skip
        await self.interrupt_q.put(self.globalstatusmodel.loop_intent)

    async def intend_estop(self):
        self.globalstatusmodel.loop_intent = LoopIntent.estop
        await self.interrupt_q.put(self.globalstatusmodel.loop_intent)

    async def intend_none(self):
        self.globalstatusmodel.loop_intent = LoopIntent.none
        await self.interrupt_q.put(self.globalstatusmodel.loop_intent)

    async def orch_wait_for_all_actions(self):
        # faithful port of orch.py:443-455: returns IMMEDIATELY (no yield!)
        # once actions_idle(); otherwise parks on the interrupt queue — the
        # exact mechanism the dead-peer race can starve (required fix 2)
        while not self.globalstatusmodel.actions_idle():
            await self.interrupt_q.get()

    def export_queues(self, timestamp_pck: bool = False):
        return None  # finalization's ExportQueuesCmd lands here

    async def estop_actions(self, switch: bool):
        return None  # EstopFanout target; must not need aiolock

    async def estop_finish_active(self):
        return None  # FinishActiveEstopped target; must not need aiolock


def _monitor_setup(bad):
    orch = _MonitorOrch()
    wiring = PortWiring(logging=_AlertSpy())
    effects = OrchCommandRunner(orch, wiring)
    runtime = HexRuntime(orch, effects)
    mon = HexHealthMonitor(orch, runtime, _FakeHealth(bad=bad))
    return orch, wiring, effects, mon


@pytest.mark.asyncio
async def test_monitor_dead_peer_prunes_sets_message_and_goes_idle():
    """The full item-6 chain in-process: probe -> HeartbeatFailed(+uuids)
    -> stop intent + stop message + alert + prune -> StatusChanged fold
    (DD-2 write-back -> orch_state idle) -> interrupt wake."""
    orch, wiring, effects, mon = _monitor_setup(
        bad={"http://127.0.0.1:8002/SIM/acquire"}
    )
    gsm = orch.globalstatusmodel
    gsm.loop_state = LoopStatus.started
    u = uuid4()
    ing = HexStatusIngestion(orch, _RuntimeSpy(orch))
    await ing.update_status(actionservermodel=_asm(_act(u, [HloStatus.active])))
    while not orch.interrupt_q.empty():
        orch.interrupt_q.get_nowait()  # drain the fold wakes

    await mon.probe_once()

    assert orch.current_stop_message == "SIM/acquire endpoints are unavailable"
    assert gsm.loop_intent == LoopIntent.stop
    assert gsm.actions_idle()
    assert gsm.orch_state == OrchStatus.idle  # StatusChanged wrote back
    assert str(u) in effects.pruned_uuids
    assert wiring.logging.alerts == ["SIM/acquire endpoints are unavailable"]
    assert not orch.interrupt_q.empty()  # the wake that releases the drain


@pytest.mark.asyncio
async def test_monitor_noop_when_loop_not_started_or_all_healthy():
    orch, _w, effects, mon = _monitor_setup(bad=set())
    orch.globalstatusmodel.loop_state = LoopStatus.started
    await mon.probe_once()  # no active endpoints -> no-op
    orch2, _w2, effects2, mon2 = _monitor_setup(
        bad={"http://127.0.0.1:8002/SIM/acquire"}
    )
    await mon2.probe_once()  # loop stopped -> no probe at all
    assert effects.pruned_uuids == set() and effects2.pruned_uuids == set()
    assert orch.current_stop_message == "" and orch2.current_stop_message == ""


@pytest.mark.asyncio
async def test_monitor_respects_ignore_heartbeats():
    orch, _w, effects, mon = _monitor_setup(
        bad={"http://127.0.0.1:8002/SIM/acquire"}
    )
    orch.ignore_heartbeats = ["SIM/acquire"]
    orch.globalstatusmodel.loop_state = LoopStatus.started
    ing = HexStatusIngestion(orch, _RuntimeSpy(orch))
    await ing.update_status(
        actionservermodel=_asm(_act(uuid4(), [HloStatus.active]))
    )
    await mon.probe_once()
    assert orch.current_stop_message == ""
    assert effects.pruned_uuids == set()


@pytest.mark.asyncio
async def test_dead_peer_race_real_loop_parks_without_hang():
    """REQUIRED-FIX-2 regression: the monitor's prune -> StatusChanged ->
    interrupt-wake ORDERING is load-bearing. The real WaitAllActionsIdle
    executor (orch_effects.py:217-227) loops `while loop_state != stopped:
    await orch_wait_for_all_actions(); if orch_state == idle: break`, and
    orch_wait_for_all_actions returns IMMEDIATELY without yielding once
    actions_idle() is true — so a window where active_dict is pruned but
    orch_state has not landed idle lets the drainer spin without a yield,
    starving the event loop so the StatusChanged coroutine that would set
    orch_state=idle can never be scheduled: the failure mode is a HANG,
    not an assertion failure. This test parks the REAL HexRuntime +
    HexDispatchLoop in the stop-drain with an active action, fires ONE
    probe, and requires the park to complete under a hard timeout."""
    orch, wiring, effects, mon = _monitor_setup(
        bad={"http://127.0.0.1:8002/SIM/acquire"}
    )
    gsm = orch.globalstatusmodel
    u = uuid4()
    ing = HexStatusIngestion(orch, _RuntimeSpy(orch))
    await ing.update_status(actionservermodel=_asm(_act(u, [HloStatus.active])))
    while not orch.interrupt_q.empty():
        orch.interrupt_q.get_nowait()  # drain the fold wakes

    runtime = mon.runtime  # the REAL HexRuntime built by _monitor_setup
    loop = HexDispatchLoop(runtime)
    loop.start()
    # pre-seed intent=stop so the first LoopIterate takes T5 (DrainForStop
    # -> WaitAllActionsIdle) without ever touching a dispatch effect
    gsm.loop_intent = LoopIntent.stop
    orch.action_dq = ["a0"]  # has_work for T1; never dispatched (drain wins)
    await runtime.handle(StartRequested())
    await asyncio.sleep(0.1)
    # drainer is now parked inside orch_wait_for_all_actions on the
    # interrupt queue with one active action; loop_state is still started
    assert gsm.loop_state == LoopStatus.started

    await mon.probe_once()

    async def _parked():
        while not (
            gsm.loop_state == LoopStatus.stopped
            and gsm.orch_state == OrchStatus.idle
        ):
            await asyncio.sleep(0.02)

    await asyncio.wait_for(_parked(), timeout=5.0)
    assert orch.current_stop_message == "SIM/acquire endpoints are unavailable"
    assert gsm.actions_idle()
    assert str(u) in effects.pruned_uuids
    await loop.close()


@pytest.mark.asyncio
async def test_estop_cascade_under_aiolock_does_not_deadlock():
    """REQUIRED-FIX-3 regression: update_status emits EstoppedUuidIngested
    via `await runtime.handle(...)` while HOLDING orch.aiolock (legacy
    parity — the inline block called estop_loop under the lock,
    orch_status_sync.py:274-275). Legacy was safe because its estop path
    took no lock; the hexagon cascade (ClearActiveRunId, EstopFanout,
    FinishActiveEstopped, SetStopMessage, AlertOperator + apply_state_delta)
    is DIFFERENT code and must never re-acquire aiolock — if any of it did,
    this await chain deadlocks. Runs the REAL HexRuntime (non-spy) through
    a fold carrying an estopped uuid under a hard timeout."""
    orch, wiring, effects, mon = _monitor_setup(bad=set())
    gsm = orch.globalstatusmodel
    gsm.loop_state = LoopStatus.started
    ing = HexStatusIngestion(orch, mon.runtime)  # REAL runtime, no spy
    u = uuid4()
    est = _act(u, [HloStatus.active, HloStatus.finished, HloStatus.estopped])
    ok = await asyncio.wait_for(
        ing.update_status(actionservermodel=_asm(est, active=False)),
        timeout=5.0,
    )
    assert ok is True
    assert gsm.loop_state == LoopStatus.estopped
    assert gsm.orch_state == OrchStatus.estopped  # DD-2 write-back
    assert orch.current_stop_message.startswith("E-STOP due to action uuid(s):")
    assert orch.active_run_id is None  # ClearActiveRunId ran
    assert not orch.aiolock.locked()  # lock released cleanly after the fold
```

Append to `helao/hexagon/tests/test_dispatch_loop.py`:

```python
@pytest.mark.asyncio
async def test_graft_swaps_heartbeat_task_when_health_wired():
    class _FakeHealth:
        def __init__(self):
            self.bound = None

        def bind_orch(self, orch):
            self.bound = orch

        async def endpoints_available(self, urls):
            return [(u, True) for u in urls]

        async def ping_action_servers(self):
            return {}

        def status_summary(self):
            return {}

    async def _forever():
        await asyncio.sleep(3600)

    orch = _ScriptedOrch()
    orch.heartbeat_interval = 3600
    orch.ignore_heartbeats = []
    orch.heartbeat_monitor = asyncio.get_running_loop().create_task(_forever())
    health = _FakeHealth()
    graft = graft_hexagon_loop(
        orch, PortWiring(logging=_AlertSpy(), health=health)
    )
    await asyncio.sleep(0.05)
    assert health.bound is orch
    assert orch.heartbeat_monitor.cancelled() or orch.heartbeat_monitor.done()
    assert graft.health_monitor is not None
    await graft.close()


@pytest.mark.asyncio
async def test_graft_without_health_skips_monitor():
    orch = _ScriptedOrch()
    graft = graft_hexagon_loop(orch, PortWiring(logging=_AlertSpy()))
    assert graft.health_monitor is None
    await graft.close()


@pytest.mark.asyncio
async def test_driver_health_exhaustion_feeds_unrecovered_event(monkeypatch):
    """P2a: RetryDriverHealth exhaustion now constructs the
    DriverHealthUnrecovered event (same stop-message wording via the
    reducer) instead of the executor calling stop() directly."""
    import helao.hexagon.app.orch_effects as fx

    monkeypatch.setattr(fx, "DRIVER_HEALTH_RETRY_DELAY_S", 0.01)
    orch = _ScriptedOrch(n_acts=1, n_exps=0, n_seqs=0)
    orch.status_summary = {"MOTOR": ("idle", "unknown")}
    runtime, loop = _make(orch)
    loop.start()
    from helao.hexagon.domain.orchestration import StartRequested

    await runtime.handle(StartRequested())
    for _ in range(300):
        if orch.current_stop_message:
            break
        await asyncio.sleep(0.01)
    assert orch.current_stop_message == "unknown driver states: MOTOR"
    await loop.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_ingestion.py helao/hexagon/tests/test_dispatch_loop.py -v -k "monitor or heartbeat_task or exhaustion or skips_monitor or dead_peer_race or estop_cascade"`
Expected: FAIL with `ImportError: cannot import name 'HexHealthMonitor'` (fails the whole `test_ingestion.py` collection, including the two required-fix regression tests) / `AttributeError: ... 'health_monitor'` / `AttributeError: module ... has no attribute 'DRIVER_HEALTH_RETRY_DELAY_S'`.

Note on the two required-fix regression tests: `test_dead_peer_race_real_loop_parks_without_hang` and `test_estop_cascade_under_aiolock_does_not_deadlock` guard HANG failure modes — if either times out during Step 4 instead of passing, that is the interleaving/re-entrancy bug they exist to catch (not a flaky test): debug with superpowers:systematic-debugging before touching the timeout.

- [ ] **Step 3: Implement**

1. Append to `helao/hexagon/app/ingestion.py` (add `HeartbeatFailed` to the `domain.orchestration` import; add `import asyncio` at top; add `"HexHealthMonitor"` to `__all__`):

```python
class HexHealthMonitor:
    """Replaces the legacy heartbeat task (ServerMonitor.active_action_
    monitor): same probe cadence (orch.heartbeat_interval), same active-url
    collection, same last-two-path-segment trim + ignore_heartbeats filter,
    same "<ends> endpoints are unavailable" stop-message wording. The
    REACTION differs by design (P2a sanctioned delta): instead of a direct
    orch.stop() + LOGGER.alert, it emits HeartbeatFailed (reducer T12: stop
    intent + SetStopMessage + AlertOperator) carrying the dead endpoints'
    active uuids so PruneDeadActions can clear them; then a StatusChanged
    fold (apply_state_delta writes orch_state=idle, DD-2) and an interrupt
    wake, in THAT order, so a parked orch_wait_for_all_actions wakes to an
    already-idle orch_state (no hot-spin in WaitAllActionsIdle). Never
    acquires aiolock (two-owner invariant): every mutation happens in the
    synchronous PruneDeadActions executor on this event loop."""

    def __init__(self, orch, runtime, health):
        self.orch = orch
        self.runtime = runtime
        self.health = health
        self._task = None

    def start(self) -> None:
        self._task = asyncio.get_running_loop().create_task(
            self.run_forever(), name="hexagon_health_monitor"
        )

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()

    async def run_forever(self) -> None:
        orch = self.orch
        while True:
            try:
                await self.probe_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.error("health monitor probe failed", exc_info=True)
            await asyncio.sleep(orch.heartbeat_interval)

    async def probe_once(self) -> None:
        orch = self.orch
        gsm = orch.globalstatusmodel
        if gsm.loop_state != LoopStatus.started:
            return
        active_items = list(gsm.active_dict.items())
        active_endpoints = [actmod.url for _uuid, actmod in active_items]
        if not active_endpoints:
            return
        unique_endpoints = list(set(active_endpoints))
        results = await self.health.endpoints_available(unique_endpoints)
        bad_urls = [url for url, ok in results if not ok]
        # legacy trim + ignore filter (orch_monitor.py:117-119)
        kept_bad_urls = [
            url
            for url in bad_urls
            if "/".join(url.strip("/").split("/")[-2:])
            not in orch.ignore_heartbeats
        ]
        if not kept_bad_urls:
            return
        bad_ends = [
            "/".join(url.strip("/").split("/")[-2:]) for url in kept_bad_urls
        ]
        dead_uuids = tuple(
            str(act_uuid)
            for act_uuid, actmod in active_items
            if actmod.url in kept_bad_urls
        )
        msg = f"{', '.join(bad_ends)} endpoints are unavailable"
        LOGGER.warning(msg)
        await self.runtime.handle(
            HeartbeatFailed(message=msg, dead_action_uuids=dead_uuids)
        )
        if dead_uuids:
            # post-prune fold BEFORE the wake: apply_state_delta (sole
            # orch_state writer, DD-2) must land idle before a parked
            # orch_wait_for_all_actions re-checks it
            await self.runtime.handle(
                StatusChanged(any_active=bool(gsm.active_dict))
            )
            await orch.interrupt_q.put(orch.globalstatusmodel)
```

2. `helao/hexagon/app/orch_effects.py` — add the module constant below `LOGGER = _LazyServerLogger()`:

```python
# driver-health retry cadence (verbatim orch_dispatch._exec_driver_health:
# <=5 x 5 s); module-level so tests can compress it without patching asyncio
DRIVER_HEALTH_RETRY_DELAY_S: float = 5.0
```

Delete the whole `if isinstance(cmd, RetryDriverHealth):` branch from `execute()` (`:195-215`) — a stray `execute(RetryDriverHealth)` now hits the terminal `AssertionError`, which is correct (only `HexRuntime` may run it) — and add this method to `OrchCommandRunner`:

```python
    async def execute_retry_driver_health(
        self, cmd: RetryDriverHealth
    ) -> "Tuple[str, ...]":
        """Verbatim orch_dispatch._exec_driver_health retry cadence, MINUS
        the exhaustion stop: the remainder is returned so HexRuntime can
        feed the DriverHealthUnrecovered event (P2a — the reducer's
        SetStopMessage wording is identical to the removed direct write)."""
        orch = self.orch
        na_drivers = list(cmd.na_drivers)
        retries = 0
        while retries < 5 and na_drivers:
            LOGGER.info(
                f"unknown driver states: {', '.join(na_drivers)}, "
                "retrying in 5 seconds"
            )
            await asyncio.sleep(DRIVER_HEALTH_RETRY_DELAY_S)
            na_drivers = [
                k for k, (_, v) in orch.status_summary.items() if v == "unknown"
            ]
            retries += 1
        return tuple(na_drivers)
```

(add `Tuple` to a `typing` import in the file).

3. `helao/hexagon/app/dispatch_loop.py` — import `DriverHealthUnrecovered` and `HexHealthMonitor` (extend the existing import blocks), replace the `RetryDriverHealth` special case in `HexRuntime._apply_and_execute` (`:68-78`) with:

```python
            if isinstance(cmd, RetryDriverHealth):
                remaining = await self.effects.execute_retry_driver_health(cmd)
                if remaining:
                    # P2a: exhaustion is now the DriverHealthUnrecovered
                    # event (reducer T12: stop intent + identical
                    # "unknown driver states: ..." stop message)
                    rc3 = await self._apply_and_execute(
                        derive_state(self.orch),
                        DriverHealthUnrecovered(na_drivers=remaining),
                    )
                    if rc3 is not ErrorCodes.none:
                        rc = rc3
                # one-shot ladder fall-through with na_drivers masked —
                # mirrors orch_dispatch._loop's non-continue driver-health
                # path (re-asking next_step with them still unknown would
                # livelock; masking == calling ladder_step directly)
                masked = replace(derive_state(self.orch), na_drivers=())
                rc2 = await self._apply_and_execute(masked, LoopIterate())
                if rc2 is not ErrorCodes.none:
                    rc = rc2
                continue
```

then add the `health_monitor` field to `HexagonGraft` (after `ingestion`):

```python
    health_monitor: Optional[HexHealthMonitor] = None
```

extend `HexagonGraft.close()`:

```python
    async def close(self) -> None:
        if self.health_monitor is not None:
            await self.health_monitor.close()
        await self.loop.close()
```

and in `graft_hexagon_loop`, after the `orch.update_nonblocking = ingestion.update_nonblocking` rebind and before `loop.start()`:

```python
    if wiring.health is not None:
        bind = getattr(wiring.health, "bind_orch", None)
        if bind is not None:
            bind(orch)
        # instance-level task swap (not a source edit): the legacy
        # heartbeat task was created by myinit before this graft runs
        legacy_hb = getattr(orch, "heartbeat_monitor", None)
        if legacy_hb is not None:
            legacy_hb.cancel()
        graft.health_monitor = HexHealthMonitor(orch, runtime, wiring.health)
        graft.health_monitor.start()
```

- [ ] **Step 4: Run the FULL in-process suite**

Run: `conda run -n helao python -m pytest helao/hexagon/tests -x -q --ignore=helao/hexagon/tests/test_concurrency_live.py --ignore=helao/hexagon/tests/test_live_group.py`
Expected: all PASS.

- [ ] **Step 5: pyright + black + commit**

```bash
conda run -n helao pyright helao/hexagon
conda run -n helao black helao/hexagon/app/ingestion.py helao/hexagon/app/orch_effects.py helao/hexagon/app/dispatch_loop.py helao/hexagon/tests/test_ingestion.py helao/hexagon/tests/test_dispatch_loop.py
git add -A helao/hexagon
git commit -m "feat(hexagon): HexHealthMonitor heartbeat swap + DriverHealthUnrecovered feed (P2a T6)"
```

---

### Task 7: FLIP the item-6 tripwire to the real behavioral assertion

**Files:**
- Modify: `helao/hexagon/tests/smoke/conc_items.py:197-257` (replace `item6_history_poll_hang_exit` wholesale)

**Interfaces:**
- Consumes: existing driver helpers in the same file (`build_ws_sequence`, `submit_and_start`, `wait_until`, `kill_server`, `get_orch_state`, `_active_dict_nonempty`, `orch_post`, `ORCH_HOST`, `ORCH_PORT`, `requests`); the P2a runtime chain (Tasks 1–6).
- Produces: `ITEMS["item6"]` now a real behavioral assertion. **Runtime validation is Task 8 (launched, MAIN SESSION); this task is the code change + static check only.**

- [ ] **Step 1: Replace the tripwire (this IS the "write the failing test" step — it fails against pre-P2a behavior by construction; the P1b2b tripwire documented exactly that)**

Replace the entire `item6_history_poll_hang_exit` function AND its `ITEMS["item6"] = ...` registration (`conc_items.py:197-257`) with:

```python
def item6_dead_peer_health_exit(root: Path, orch_key: str, prefix: str) -> int:
    """§10.3 item 6 (dead-peer heartbeat exit) — REAL behavioral assertion
    since P2a (this used to be the P1b2b characterization TRIPWIRE of the
    known hang; the flip is item 3 of the P2a acceptance gate).

    Killing an action server mid-action now makes the hexagon health
    monitor emit HeartbeatFailed(+dead uuids) -> stop intent + the
    "... endpoints are unavailable" stop message + PruneDeadActions, so
    the wrapped-legacy orch_wait_for_all_actions unblocks and the orch
    PARKS stopped with an empty active_dict.

    SANCTIONED BEHAVIOR DELTA (improvement over legacy — see the P2a plan's
    "Sanctioned behavior deltas" and p2-decisions.md Q3): legacy parks
    FOREVER here (the P1b2b investigation showed the monitor fires but
    nothing prunes active_dict or releases the history poll). This is a
    deliberate §9-style delta, not a parity bug."""
    seq = build_ws_sequence(1, wait_time=1.0, data_duration=60.0)
    submit_and_start(orch_key, seq)
    wait_until(_active_dict_nonempty, 120, poll_s=1.0, label="item6 action active")
    kill_server(root, prefix, "SIM")

    def _stopped() -> bool:
        return str(get_orch_state(orch_key).get("loop_state")).endswith("stopped")

    # heartbeat_interval is 3 s in goldenhexconc.yml; probe + prune + drain
    # must park the orch well inside this window
    wait_until(_stopped, 120, poll_s=2.0, label="item6 park after dead-peer kill")

    st = get_orch_state(orch_key)
    msg = str(st.get("current_stop_message"))
    assert (
        "endpoints are unavailable" in msg
    ), f"stop message missing offline text: {msg!r}"
    gs = requests.post(
        f"http://{ORCH_HOST}:{ORCH_PORT}/global_status", timeout=10
    ).json()
    assert not gs.get("active_dict"), (
        f"active_dict not pruned after dead-peer kill: {gs.get('active_dict')}"
    )
    return 0


ITEMS["item6"] = item6_dead_peer_health_exit
```

Also update the module docstring's item list (line 9): `item6 (history-poll hang exit)` → `item6 (dead-peer health exit)`.

- [ ] **Step 2: Static check (no launched run in this task)**

Run: `conda run -n helao python -c "from helao.hexagon.tests.smoke.conc_items import ITEMS; assert set(ITEMS) == {'item2','item4','item6','item7'}; print('items ok')"`
Expected: `items ok`

- [ ] **Step 3: black + commit**

```bash
conda run -n helao black helao/hexagon/tests/smoke/conc_items.py
git add helao/hexagon/tests/smoke/conc_items.py
git commit -m "test(hexagon): flip item-6 tripwire to real dead-peer behavioral assertion (P2a T7)"
```

---

### Task 8: Acceptance gate — full §10.3 launched suite with item-6 flipped (MAIN SESSION ONLY)

**Files:** none created — verification only. Launched groups get reaped when run from background subagents; every `conc_run.sh` invocation below MUST run in the main session and relies on the script's curl-only readiness probe (do not add per-poll `conda run` probes).

**Acceptance criteria (all must hold; this is the P2a gate from scope §2/§3):**

- [ ] **Step 1: Static gates**

```bash
conda run -n helao pyright helao/hexagon        # expected: 0 errors
conda run -n helao black --check helao/hexagon  # expected: clean
```

- [ ] **Step 2: Full in-process pytest suite — §9 behavior tests, boundary test, §10.3 items 1/3/5 (in-process real-transport), all unit additions**

```bash
conda run -n helao python -m pytest helao/hexagon/tests -q
```
Expected: 0 failures. This includes `test_behavior_hexagon.py` (§9 green), `test_boundaries.py` (boundary green), `test_concurrency_live.py` (items 1/3/5 on real ZMQ+HTTP), and the two-lock-owner invariant test (`test_two_lock_owner_invariant_prune_never_takes_aiolock`).

- [ ] **Step 3: Launched §10.3 items (main session, one at a time)**

```bash
bash helao/hexagon/tests/smoke/conc_run.sh item2 goldenhexid /home/dan/INST_hlo_hexid HEXORC
bash helao/hexagon/tests/smoke/conc_run.sh item4 goldenhexconc /home/dan/INST_hlo_hexconc
bash helao/hexagon/tests/smoke/conc_run.sh item6 goldenhexconc /home/dan/INST_hlo_hexconc
bash helao/hexagon/tests/smoke/conc_run.sh item7 goldenhexconc /home/dan/INST_hlo_hexconc
```
Expected: rc 0 for each. **item6 is the flip validation** — if it times out at `item6 park after dead-peer kill`, debug with `superpowers:systematic-debugging` starting from the orch log (`/home/dan/INST_hlo_hexconc/LOGS/ORCH.log`): look for the `pruned dead-peer action` warning (prune ran) vs the `... endpoints are unavailable` warning alone (prune command not ordered → check `dead_action_uuids` population in `HexHealthMonitor.probe_once`).

- [ ] **Step 4: GM byte parity note**

GM-1..GM-4 byte parity must be UNCHANGED (ingestion is behavior, not artifacts). Per the P2a task contract the **controller re-runs these** — do not run them from this plan; report readiness to the controller instead.

- [ ] **Step 5: Report**

Report each command's exit status verbatim (no summarized "all green" without the outputs). If anything fails: fix, re-run the affected gate, and re-run Step 2 before re-claiming.

---

## Self-Review

**1. Spec/scope coverage** (p2-scope.md §3 + §5, p2-decisions.md, task contract):
- Ingestion runner owning `update_status`/`update_nonblocking` bodies, folding via `update_global_with_acts` (status model kept), emitting `EstoppedUuidIngested`/`ErroredUuidIngested`/`StatusChanged` in place of `orch_status_sync.py:265-285` → Tasks 3+4. ✓
- `update_nonblocking` timestamp quirk + `list.remove` ValueError quirk pinned, no wire change; `clear_nonblocking`/`ws_globstat`/`globstat_broadcast_task` untouched → Task 3 (tests + docstring). ✓
- HealthPort adapter (first consumer of `ports/auxiliary.py:53-64`) bridging heartbeat + driver-health → Tasks 1+6 (`endpoints_available` consumed by the monitor; driver-health exhaustion now constructs `DriverHealthUnrecovered`; `HeartbeatFailed` carries server/uuid identity via `dead_action_uuids` + message). ✓
- Item-6 dead-peer: `PruneDeadActions` command + executor, `active_dict` pruned at BOTH levels so legacy `orch_wait_for_all_actions.actions_idle()` turns true without editing it (Q3), health-aware break in the `DispatchHeadAction` history-poll, tripwire FLIPPED → Tasks 2+5+7, validated Task 8. Documented as a sanctioned behavior delta (deltas section), not a parity bug. ✓
- Rewire: graft rebind set extended; `apply_state_delta` sole `orch_state` writer with atomic hand-off (single commit, Task 4); `ORCH_REQUIRED` grows `health` (fail-loud meaningful — factory wires a real adapter) → Tasks 1+4. ✓
- Gate: §10.3 items 1–7 with item-6 flipped, items 1/3/5 in-process, GM-1..4 unchanged (controller re-runs), §9 green, pyright 0, boundary green, two-lock-owner invariant asserted → Tasks 5 (invariant test) + 8. ✓
- Remaining reducer events: `DispatchFailed`/`PlateGateFailed` are dispatch-side (constructed by the dispatch fold / plate gate, which stay wrapped-legacy through P2 per scope §4 "Native orch app" deferral) — P2a makes them *constructible* but the wrapped `loop_task_dispatch_action` keeps its internal fold; no task claims otherwise. `ActionResultErrored` likewise stays on the wrapped dispatch path. This matches scope §3 "Keeps".
- Interleaving parity (risk #1): events emitted inside `aiolock` exactly where the inline block ran; unconditional trailing `interrupt_q.put` preserved; monitor orders prune → `StatusChanged` → wake. The two hang-mode risks are pinned by REAL-runtime regression tests in T6: `test_dead_peer_race_real_loop_parks_without_hang` (the prune/StatusChanged/wake ordering vs the non-yielding `orch_wait_for_all_actions` return — event-loop-starvation hang) and `test_estop_cascade_under_aiolock_does_not_deadlock` (the `EstoppedUuidIngested` cascade running under the held `aiolock` — re-entrancy deadlock). ✓
- `Action.url` is a computed read-only `@property` (`action.py:167-170`), NOT a field: every url-reading fixture builds `MachineModel(..., hostname="127.0.0.1", port=8002)` and never passes `url=`; `test_act_fixture_url_matches_monitor_probe_target` (T3) pins the computed value the T6 monitor and launched item-6 string-match against. ✓

**2. Placeholder scan:** no TBD/TODO/"similar to Task N"/"add error handling" placeholders; every code step shows the complete code; test code is complete and runnable. ✓

**3. Type/name consistency:** `HexStatusIngestion(orch, runtime)` (T3) = graft construction (T4); `action_history_meta(orch, act_model)` (T3) = executor's function-local import (T5); `HeartbeatFailed(message, dead_action_uuids)` / `PruneDeadActions(action_uuids)` (T2) = monitor emission (T6) + executor match (T5); `OrchCommandRunner.pruned_uuids` (T5) = poll break (T5) + monitor/race test asserts (T6); `execute_retry_driver_health(cmd) -> Tuple[str, ...]` (T6) = `HexRuntime` caller (T6); `DRIVER_HEALTH_RETRY_DELAY_S` defined and monkeypatched under the same name; `HexagonGraft.ingestion`/`health_monitor` fields consistent across T4/T6 tests; T5 uses the guarded `append_action_status` (`action.py:172`), matching the codebase's guarded-status idiom; T1 asserts `UnwiredPortError` specifically. ✓
