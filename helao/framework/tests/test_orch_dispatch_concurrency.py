"""SP-ORCH-5c concurrency + correctness tests for the single Event-driven loop.

These tests exercise the PRODUCTION dispatch path (a real uvicorn orch with a
``HttpTransport`` and ``synthesize_completion=False``, fed by genuine ``/ws_status``
status), NOT the in-process synthesize fast path. They reproduce the races the
adversarial review found against the old spawn-on-status design and confirm the
single-loop redesign fixes them:

* ``wait_for_all`` gating: a SIM action with the DEFAULT start_condition must not
  dispatch until a preceding ORCH/wait finishes (old code double-dispatched or
  stalled).
* lost-wakeup / concurrent status: own-wait + external SIM statuses landing close
  together must not stall and must finish the experiment exactly once.
* single-drainer: each action dispatches exactly once (no concurrent loop double-pop).
* non-default orchestrator identity (MINOR-8): a finished self-hosted wait must be
  removed from ``active_dict`` even when the GSM orchestrator is a real (non-default)
  identity.

All waits use condition-polling with timeouts (never fixed sleeps assuming timing),
durations are small (<= 0.3s).
"""
from __future__ import annotations

import asyncio
import tempfile
import time
from typing import List

import pytest

from helao.framework.adapters.fakes.storage import FakeStorage
from helao.framework.adapters.http_transport import HttpTransport
from helao.framework.adapters.ntp_clock import NtpClock
from helao.framework.adapters.queue_eventsink import QueueEventSink
from helao.framework.app.orch_api import OrchPorts, makeOrchApp
from helao.framework.domain import status as status_facade
from helao.framework.domain.commands import DispatchAction, FinishExperiment, OrchDecision
from helao.framework.domain.orchestration import decide_next
from helao.framework.domain.run_models import RunAction, RunExperiment
from helao.framework.models.action_start_condition import ActionStartCondition
from helao.framework.models.machine import MachineModel

from helao.framework.tests._fake_action_server import (
    FakeServerInfo,
    _RunningServer,
    _free_http_port,
    fake_action_server,  # noqa: F401 — fixture discovery
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _poll_until(predicate, timeout: float, interval: float = 0.02) -> bool:
    """Poll ``predicate`` until it is truthy or ``timeout`` elapses."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return predicate()


class _CommandSpy:
    """Wraps ``driver._execute`` to count emitted command instances by type.

    Counts are taken at the point ``_execute`` is invoked, so a double-dispatch
    or double-finish from two concurrent loops would be visible as inflated
    counts.
    """

    def __init__(self, driver) -> None:
        self.driver = driver
        self._orig = driver._execute
        self.dispatched_uuids: List[str] = []
        self.finish_experiment_count = 0
        driver._execute = self._wrapped

    async def _wrapped(self, commands):
        for cmd in commands:
            if isinstance(cmd, DispatchAction):
                self.dispatched_uuids.append(str(cmd.action.action_uuid))
            elif isinstance(cmd, FinishExperiment):
                self.finish_experiment_count += 1
        return await self._orig(commands)


def _build_orch_app(
    orch_key: str,
    orch_host: str,
    orch_port: int,
    fsi: FakeServerInfo,
    save_root: str,
    actions: List[RunAction],
    *,
    orchestrator_identity: MachineModel | None = None,
):
    """Build a real production-path orch app with a given experiment action list."""
    servers_map = {
        orch_key: {"host": orch_host, "port": orch_port, "group": "orchestrator"},
        fsi.server_key: {"host": fsi.host, "port": fsi.http_port, "group": "action"},
    }

    def exp_factory(experiment: RunExperiment, **_kw) -> List[RunAction]:
        # return fresh deep copies so re-expansion never reuses stamped uuids
        return [a.model_copy(deep=True) for a in actions]

    transport = HttpTransport(use_rpc=True)
    ports = OrchPorts(
        transport=transport,
        storage=FakeStorage(),
        eventsink=QueueEventSink(),
        clock=NtpClock(),
        servers_map=servers_map,
        action_servers={fsi.server_key: {"host": fsi.host, "port": fsi.http_port}},
        experiment_lib={"builtin_exp": exp_factory},
        synthesize_completion=False,  # PRODUCTION path: wait for real status
    )

    state = None
    if orchestrator_identity is not None:
        from helao.framework.domain.orchestration import OrchState
        from helao.framework.models.server import GlobalStatusModel

        state = OrchState()
        state.globalstatusmodel = GlobalStatusModel(orchestrator=orchestrator_identity)

    app = makeOrchApp(orch_key, ports=ports, state=state, save_root=save_root)
    return app, transport


async def _run_orch_experiment(app, transport, orch_key, orch_host, orch_port):
    """Start the orch app, enqueue a builtin_exp, kick the loop. Returns the driver."""
    import httpx

    srv = _RunningServer(app, orch_host, orch_port)
    srv.start(timeout=15.0)
    await asyncio.sleep(0.4)  # let startup hooks run

    driver = app.state.driver
    driver.enqueue_experiment(RunExperiment(experiment_name="builtin_exp"))

    async with httpx.AsyncClient(base_url=f"http://{orch_host}:{orch_port}") as client:
        await client.post(f"/{orch_key}/start")

    return driver, srv


# ---------------------------------------------------------------------------
# Test 1: wait_for_all gating — SIM must not dispatch until ORCH/wait finishes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wait_for_all_gates_sim_until_wait_finishes(fake_action_server: FakeServerInfo):
    """[ORCH/wait{0.3}, SIM run_for] with DEFAULT wait_for_all on SIM.

    The SIM action must NOT dispatch until the wait finishes, then must dispatch
    exactly once, then the queues drain and the experiment finishes.
    """
    fsi = fake_action_server
    orch_key, orch_host, orch_port = "ORCH", "127.0.0.1", _free_http_port()

    wait_action = RunAction(
        action_name="wait",
        action_server=MachineModel(server_name=orch_key),
        action_params={"waittime": 0.3},
        start_condition=ActionStartCondition.no_wait,
    )
    sim_action = RunAction(
        action_name="run_for",
        action_server=MachineModel(server_name=fsi.server_key),
        action_params={"duration": 0.1},
        # DEFAULT start condition is wait_for_all — set explicitly for clarity.
        start_condition=ActionStartCondition.wait_for_all,
    )

    with tempfile.TemporaryDirectory() as tmp:
        app, transport = _build_orch_app(
            orch_key, orch_host, orch_port, fsi, tmp, [wait_action, sim_action]
        )
        driver = app.state.driver
        spy = _CommandSpy(driver)
        try:
            driver, srv = await _run_orch_experiment(
                app, transport, orch_key, orch_host, orch_port
            )

            # The wait must dispatch first (and only it) while it is running.
            assert await _poll_until(lambda: len(spy.dispatched_uuids) >= 1, 3.0), (
                "ORCH/wait never dispatched"
            )
            # While the wait is still active, the SIM (wait_for_all) must NOT have
            # dispatched yet — exactly one dispatch so far.
            gsm = driver.state.globalstatusmodel
            # confirm we are mid-wait (an action is active)
            if not status_facade.actions_idle(gsm):
                assert len(spy.dispatched_uuids) == 1, (
                    "SIM dispatched before the wait finished (wait_for_all gating broke "
                    f"or double-dispatch): dispatched={spy.dispatched_uuids}"
                )

            # Eventually both dispatch and the experiment finishes.
            assert await _poll_until(
                lambda: decide_next(driver.state) == OrchDecision.IDLE, 6.0
            ), f"experiment did not drain; loop_state={driver.state.loop_state}"

            assert len(driver.state.action_dq) == 0
            assert len(driver.state.experiment_dq) == 0
            # exactly two distinct actions dispatched, each once
            assert len(spy.dispatched_uuids) == 2, (
                f"expected 2 dispatches, got {spy.dispatched_uuids}"
            )
            assert len(set(spy.dispatched_uuids)) == 2, (
                f"an action was dispatched more than once: {spy.dispatched_uuids}"
            )
            assert spy.finish_experiment_count == 1, (
                f"FinishExperiment emitted {spy.finish_experiment_count} times (want 1)"
            )
        finally:
            srv.stop()
            await transport.aclose()


# ---------------------------------------------------------------------------
# Test 2: lost-wakeup / concurrent status — two status sources close together
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_status_no_stall_single_finish(fake_action_server: FakeServerInfo):
    """Own-wait + external SIM statuses land close together (concurrent).

    Both actions use no_wait so they dispatch back-to-back and their finished
    statuses arrive nearly simultaneously, driving two status sources into the
    FSM at once. Assert: no stall (experiment drains) and FinishExperiment is
    emitted EXACTLY once (no double-finish from two concurrent loops; no lost
    wakeup leaving a permanent WAIT).
    """
    fsi = fake_action_server
    orch_key, orch_host, orch_port = "ORCH", "127.0.0.1", _free_http_port()

    wait_action = RunAction(
        action_name="wait",
        action_server=MachineModel(server_name=orch_key),
        action_params={"waittime": 0.1},
        start_condition=ActionStartCondition.no_wait,
    )
    sim_action = RunAction(
        action_name="run_for",
        action_server=MachineModel(server_name=fsi.server_key),
        action_params={"duration": 0.1},
        start_condition=ActionStartCondition.no_wait,
    )

    with tempfile.TemporaryDirectory() as tmp:
        app, transport = _build_orch_app(
            orch_key, orch_host, orch_port, fsi, tmp, [wait_action, sim_action]
        )
        driver = app.state.driver
        spy = _CommandSpy(driver)
        try:
            driver, srv = await _run_orch_experiment(
                app, transport, orch_key, orch_host, orch_port
            )

            assert await _poll_until(
                lambda: decide_next(driver.state) == OrchDecision.IDLE, 6.0
            ), (
                f"loop stalled (lost wakeup?); loop_state={driver.state.loop_state}, "
                f"decision={decide_next(driver.state)}, "
                f"active={list(driver.state.globalstatusmodel.active_dict.keys())}"
            )

            assert spy.finish_experiment_count == 1, (
                f"FinishExperiment emitted {spy.finish_experiment_count} times "
                "(double-finish from concurrent loops?)"
            )
            assert len(driver.state.action_dq) == 0
            assert len(driver.state.experiment_dq) == 0
        finally:
            srv.stop()
            await transport.aclose()


# ---------------------------------------------------------------------------
# Test 3: single-drainer — each action dispatched exactly once
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_drainer_each_action_dispatched_once(fake_action_server: FakeServerInfo):
    """Three SIM actions; assert each is dispatched exactly once (one drainer).

    Two concurrent loops would double-pop the dq and dispatch the same action
    twice (or out of order). With the single Event-driven loop each uuid appears
    exactly once.
    """
    fsi = fake_action_server
    orch_key, orch_host, orch_port = "ORCH", "127.0.0.1", _free_http_port()

    actions = [
        RunAction(
            action_name="run_for",
            action_server=MachineModel(server_name=fsi.server_key),
            action_params={"duration": 0.05},
            start_condition=ActionStartCondition.wait_for_all,
        )
        for _ in range(3)
    ]

    with tempfile.TemporaryDirectory() as tmp:
        app, transport = _build_orch_app(
            orch_key, orch_host, orch_port, fsi, tmp, actions
        )
        driver = app.state.driver
        spy = _CommandSpy(driver)
        try:
            driver, srv = await _run_orch_experiment(
                app, transport, orch_key, orch_host, orch_port
            )

            assert await _poll_until(
                lambda: decide_next(driver.state) == OrchDecision.IDLE, 8.0
            ), f"experiment did not drain; dispatched={spy.dispatched_uuids}"

            assert len(spy.dispatched_uuids) == 3, (
                f"expected 3 dispatches, got {len(spy.dispatched_uuids)}: "
                f"{spy.dispatched_uuids}"
            )
            assert len(set(spy.dispatched_uuids)) == 3, (
                f"an action was dispatched more than once (concurrent drainers?): "
                f"{spy.dispatched_uuids}"
            )
            assert spy.finish_experiment_count == 1
        finally:
            srv.stop()
            await transport.aclose()


# ---------------------------------------------------------------------------
# Test 4: non-default orchestrator identity (MINOR-8) — finished wait removed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_default_orchestrator_identity_wait_removed(fake_action_server: FakeServerInfo):
    """With a NON-default GSM orchestrator identity, a finished ORCH/wait must be
    removed from active_dict (actions_idle becomes True).

    Reproduces MINOR-8: ``_sort_status`` only removes a finished UUID when
    ``statusmodel.orchestrator == self.orchestrator``. If the /wait action keeps
    the default MachineModel() while the GSM holds the real identity, the finished
    wait is never removed → permanent WAIT stall. Stamping the orch identity on
    the wait action fixes it. This test FAILS against the unstamped code.
    """
    fsi = fake_action_server
    orch_key, orch_host, orch_port = "ORCH", "127.0.0.1", _free_http_port()

    # A real, NON-default orchestrator identity (matches what a real config sets).
    orch_identity = MachineModel(
        server_name=orch_key, machine_name="prod-box", hostname=orch_host, port=orch_port
    )

    # Single ORCH/wait action so success hinges solely on self-status removal.
    wait_action = RunAction(
        action_name="wait",
        action_server=MachineModel(server_name=orch_key),
        action_params={"waittime": 0.2},
        start_condition=ActionStartCondition.no_wait,
    )

    with tempfile.TemporaryDirectory() as tmp:
        app, transport = _build_orch_app(
            orch_key, orch_host, orch_port, fsi, tmp, [wait_action],
            orchestrator_identity=orch_identity,
        )
        driver = app.state.driver
        # sanity: GSM really holds the non-default identity
        assert driver.state.globalstatusmodel.orchestrator == orch_identity
        try:
            driver, srv = await _run_orch_experiment(
                app, transport, orch_key, orch_host, orch_port
            )

            gsm = driver.state.globalstatusmodel
            # The finished wait MUST leave active_dict -> actions_idle True ->
            # the experiment drains. Under the unstamped code this never happens.
            assert await _poll_until(
                lambda: status_facade.actions_idle(gsm)
                and decide_next(driver.state) == OrchDecision.IDLE,
                6.0,
            ), (
                "finished wait was NOT removed from active_dict under a non-default "
                f"orchestrator identity (MINOR-8 stall); active_dict="
                f"{list(gsm.active_dict.keys())}, decision={decide_next(driver.state)}"
            )
            assert len(driver.state.action_dq) == 0
            assert len(driver.state.experiment_dq) == 0
        finally:
            srv.stop()
            await transport.aclose()
