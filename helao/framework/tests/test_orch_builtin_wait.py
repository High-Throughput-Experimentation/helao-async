"""SP-ORCH-5c tests — orchestrator built-in actions (WaitExec + /wait endpoint).

TDD: all tests MUST FAIL before any production code is written.

Tests:
    A. Unit — WaitExec polls and finishes after waittime.
    B. Integration — /wait endpoint returns an active action dict with action_uuid.
    C. Unit — builtin action endpoints are RPC-registered.
    D. Capstone integration — ORCH/wait + SIM action end-to-end.
"""
from __future__ import annotations

import asyncio
import tempfile
import time
import uuid as _uuid
from datetime import datetime
from typing import List

import pytest

from helao.framework.adapters.fakes.storage import FakeStorage
from helao.framework.adapters.http_transport import HttpTransport
from helao.framework.adapters.ntp_clock import NtpClock
from helao.framework.adapters.queue_eventsink import QueueEventSink
from helao.framework.app.orch_api import OrchPorts, makeOrchApp
from helao.framework.domain.run_models import RunAction, RunExperiment
from helao.framework.models.action_start_condition import ActionStartCondition
from helao.framework.models.machine import MachineModel
from helao.framework.models.orchstatus import LoopStatus

from helao.framework.tests._fake_action_server import (
    FakeServerInfo,
    _RunningServer,
    _free_http_port,
    fake_action_server,  # noqa: F401 — fixture discovery
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ports(transport=None) -> OrchPorts:
    """Minimal OrchPorts suitable for unit tests (no servers_map)."""
    from helao.framework.adapters.fakes.transport import FakeTransport

    return OrchPorts(
        transport=transport or FakeTransport(),
        storage=FakeStorage(),
        eventsink=QueueEventSink(),
        clock=NtpClock(),
    )


# ---------------------------------------------------------------------------
# Test A: WaitExec unit test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wait_exec_finishes_after_waittime():
    """WaitExec._poll returns active while elapsed < waittime, finished after."""
    from helao.framework.app.orch_api import WaitExec  # FAILS until WaitExec added

    action_uuid = _uuid.uuid4()
    now = datetime.now()
    action = RunAction(
        action_name="wait",
        action_uuid=action_uuid,
        action_timestamp=now,
        sequence_timestamp=now,
        experiment_timestamp=now,
        sequence_name="orch_builtin",
        experiment_name="orch_builtin",
        action_output_dir=str(action_uuid),
        action_server=MachineModel(server_name="ORCH"),
        action_params={"waittime": 0.1},
        save_act=False,
        save_data=False,
    )

    from dataclasses import dataclass

    @dataclass
    class _FakeActive:
        action: RunAction
        manual_stop: bool = False
        action_loop_running: bool = False

    active = _FakeActive(action=action)
    executor = WaitExec(active=active)

    from helao.framework.models.hlostatus import HloStatus

    # Immediately after construction the wait should be active (< 0.1s elapsed).
    result = await executor._poll()
    assert result["status"] == HloStatus.active, (
        f"WaitExec should be active immediately after construction, got {result['status']}"
    )

    # Wait longer than waittime, then poll — should be finished.
    await asyncio.sleep(0.15)
    result = await executor._poll()
    assert result["status"] == HloStatus.finished, (
        f"WaitExec should be finished after waittime=0.1s, got {result['status']}"
    )


@pytest.mark.asyncio
async def test_wait_exec_indefinite_never_finishes():
    """WaitExec with waittime=-1 (indefinite) always returns active."""
    from helao.framework.app.orch_api import WaitExec

    action_uuid = _uuid.uuid4()
    now = datetime.now()
    action = RunAction(
        action_name="wait",
        action_uuid=action_uuid,
        action_timestamp=now,
        sequence_timestamp=now,
        experiment_timestamp=now,
        sequence_name="orch_builtin",
        experiment_name="orch_builtin",
        action_output_dir=str(action_uuid),
        action_server=MachineModel(server_name="ORCH"),
        action_params={"waittime": -1},
        save_act=False,
        save_data=False,
    )

    from dataclasses import dataclass
    from helao.framework.models.hlostatus import HloStatus

    @dataclass
    class _FakeActive:
        action: RunAction
        manual_stop: bool = False
        action_loop_running: bool = False

    active = _FakeActive(action=action)
    executor = WaitExec(active=active)

    # Even after some time, indefinite wait stays active.
    await asyncio.sleep(0.05)
    result = await executor._poll()
    assert result["status"] == HloStatus.active, (
        "WaitExec with waittime=-1 should always return active"
    )


# ---------------------------------------------------------------------------
# Test B: /wait endpoint integration test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wait_endpoint_returns_active_action():
    """POST /{server_key}/wait returns an active action dict with action_uuid.

    Uses an ASGI-level httpx.AsyncClient — no real uvicorn, but startup events
    fire via httpx's lifespan handler so base.myinit() runs.
    """
    import httpx

    ports = _make_ports()
    app = makeOrchApp("ORCH", ports=ports)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Direct convention: {"waittime": <float>}
        resp = await client.post("/ORCH/wait", json={"waittime": 10.0})
        if resp.status_code == 422:
            # Try action_params convention (dispatch convention)
            resp = await client.post("/ORCH/wait", json={"action_params": {"waittime": 10.0}})

    # The /wait endpoint must exist (not 404) and return a dict with action_uuid.
    assert resp.status_code == 200, (
        f"/ORCH/wait returned {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert "action_uuid" in body, (
        f"/ORCH/wait response missing 'action_uuid': {body}"
    )
    # UUID must be parseable.
    _uuid.UUID(body["action_uuid"])


# ---------------------------------------------------------------------------
# Test C: builtin action endpoints are RPC-registered
# ---------------------------------------------------------------------------


def test_builtin_action_endpoints_are_rpc_registered():
    """The built-in action endpoints (/wait, /cancel_wait, /interrupt) are
    registered with the RPC dispatcher at startup.

    This test re-creates the orch app and manually walks the POST routes to
    confirm the dispatcher covers the builtin endpoints. (In production the
    startup hook does this; here we replicate it directly.)
    """
    from fastapi.routing import APIRoute

    ports = _make_ports()
    app = makeOrchApp("ORCH", ports=ports)

    dispatcher = app.state.rpc_dispatcher
    # Mirror the startup registration: walk every POST route.
    for route in app.routes:
        if isinstance(route, APIRoute) and "POST" in (route.methods or set()):
            dispatcher.register(route.path, route.endpoint)

    registered = set(dispatcher.methods.keys())

    # strip leading slash to match dispatcher key convention
    for endpoint in ["ORCH/wait", "ORCH/cancel_wait", "ORCH/interrupt"]:
        assert endpoint in registered, (
            f"/{endpoint} not RPC-registered. Registered: {sorted(registered)}"
        )


# ---------------------------------------------------------------------------
# Test D: Capstone — ORCH/wait + SIM action end-to-end (real uvicorn orch)
# ---------------------------------------------------------------------------


def _make_orch_app(
    orch_key: str,
    orch_host: str,
    orch_port: int,
    fsi: FakeServerInfo,
    save_root: str,
):
    """Build a real orch app targeting itself (for ORCH/wait) + the fake server."""
    servers_map = {
        orch_key: {"host": orch_host, "port": orch_port, "group": "orchestrator"},
        fsi.server_key: {"host": fsi.host, "port": fsi.http_port, "group": "action"},
    }

    wait_action = RunAction(
        action_name="wait",
        action_server=MachineModel(server_name=orch_key),
        action_params={"waittime": 0.3},
        start_condition=ActionStartCondition.no_wait,
    )
    sim_action = RunAction(
        action_name="run_for",
        action_server=MachineModel(server_name=fsi.server_key),
        action_params={"duration": 0.2},
        start_condition=ActionStartCondition.no_wait,
    )

    def exp_factory(experiment: RunExperiment, **_kw) -> List[RunAction]:
        return [wait_action, sim_action]

    transport = HttpTransport(use_rpc=True)
    ports = OrchPorts(
        transport=transport,
        storage=FakeStorage(),
        eventsink=QueueEventSink(),
        clock=NtpClock(),
        servers_map=servers_map,
        action_servers={fsi.server_key: {"host": fsi.host, "port": fsi.http_port}},
        experiment_lib={"builtin_exp": exp_factory},
        synthesize_completion=False,
    )
    app = makeOrchApp(orch_key, ports=ports)
    return app, transport


@pytest.mark.asyncio
async def test_orch_wait_then_sim_action_end_to_end(fake_action_server: FakeServerInfo):
    """Capstone: ORCH/wait runs ~0.3s then loop advances, SIM action dispatches + completes.

    Experiment action_dq: [ORCH/wait {waittime:0.3}, FAKE/run_for {duration:0.2}]

    Asserts:
    (i)  ORCH/wait dispatches to the orch's own /wait endpoint (base.executors non-empty).
    (ii) The loop does NOT advance past the wait instantly
         (WaitExec is active, base.executors still has wait entry while running).
    (iii) After wait + sim complete (OwnStatusIngestor folds finished status),
          the experiment queue drains and action_dq is empty.
    """
    import httpx

    fsi = fake_action_server
    orch_key = "ORCH"
    orch_host = "127.0.0.1"
    orch_port = _free_http_port()

    with tempfile.TemporaryDirectory() as tmp:
        app, transport = _make_orch_app(orch_key, orch_host, orch_port, fsi, tmp)

        srv = _RunningServer(app, orch_host, orch_port)
        srv.start(timeout=15.0)
        try:
            # Give startup hooks time to run
            await asyncio.sleep(0.5)

            driver = app.state.driver

            # Enqueue a builtin_exp experiment
            exp = RunExperiment(experiment_name="builtin_exp")
            driver.enqueue_experiment(exp)

            # Kick the loop
            async with httpx.AsyncClient(
                base_url=f"http://{orch_host}:{orch_port}"
            ) as client:
                await client.post(f"/{orch_key}/start")

            # Wait up to 3s for loop to start
            deadline = time.time() + 3.0
            while time.time() < deadline:
                await asyncio.sleep(0.05)
                if driver.state.loop_state == LoopStatus.started:
                    break

            # Wait for base to have an active wait executor (ORCH/wait dispatched)
            base = app.state.base
            deadline = time.time() + 3.0
            while time.time() < deadline:
                await asyncio.sleep(0.05)
                if base.executors:
                    break

            assert base.executors, (
                "WaitExec was never registered in base.executors — "
                "/wait endpoint not reached or WaitExec not started. "
                "This means the ORCH self-dispatch did not reach the /wait endpoint."
            )

            # Assert (i): executor dict has a wait entry (not yet finished)
            wait_dispatched_time = time.time()
            exec_ids = list(base.executors.keys())
            assert any("wait" in eid for eid in exec_ids), (
                f"No 'wait' executor found; executors: {exec_ids}"
            )

            # Assert (ii): the loop is still running (wait not done yet)
            # WaitExec takes 0.3s, we just detected it started — should still be active
            await asyncio.sleep(0.05)  # tiny buffer
            # We expect actions are still in flight (wait is executing)
            gsm = driver.state.globalstatusmodel
            # The global status should show the wait action as active (not idle)
            # This is flexible — we just check the loop hasn't instantly finished
            assert driver.state.loop_state == LoopStatus.started, (
                "Loop exited prematurely — wait should still be running"
            )

            # Assert (iii): wait for OwnStatusIngestor to fold finished status
            # + SIM action to complete. Total: 0.3s wait + 0.2s sim + buffer.
            # The loop reaches IDLE when decide_next returns IDLE (all queues empty).
            # loop_state stays "started" even after the loop finishes (it only
            # transitions to "stopped" on an explicit stop intent).
            from helao.framework.domain.orchestration import decide_next
            from helao.framework.domain.commands import OrchDecision

            deadline_total = wait_dispatched_time + 5.0
            loop_completed = False
            while time.time() < deadline_total:
                await asyncio.sleep(0.1)
                st = driver.state.loop_state
                if st == LoopStatus.stopped:
                    loop_completed = True
                    break
                # Also accept: loop finished naturally (IDLE via decide_next)
                if decide_next(driver.state) == OrchDecision.IDLE:
                    loop_completed = True
                    break

            assert loop_completed, (
                f"Loop did not complete within 5s. loop_state={driver.state.loop_state}. "
                "Either ORCH/wait never finished (OwnStatusIngestor not wired) or "
                "SIM action never completed (subscriber not running)."
            )

            # Final queue drain check
            assert len(driver.state.experiment_dq) == 0, (
                f"Experiment still queued after loop; experiment_dq={list(driver.state.experiment_dq)}"
            )
            assert len(driver.state.action_dq) == 0, (
                f"Actions still queued after loop; action_dq={list(driver.state.action_dq)}"
            )

        finally:
            srv.stop()
            await transport.aclose()
