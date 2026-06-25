"""SP-ORCH-5c — /wait endpoint crash on empty-args RPC call.

TDD: these tests MUST FAIL against the current Body(None) code, then pass after
the fix (Body({}) + isinstance guard + no-op on empty payload).

Tests
-----
E1. Empty-args RPC call to wait does NOT raise and does NOT start a WaitExec.
    - Reproduces the live crash: Body(None) → "argument of type 'Body' is not iterable".
    - After the fix: returns a benign no-op ack dict, base.executors stays empty.

E2. Real action dispatch over RPC: full wait action (action_params.waittime=0.3)
    → WaitExec runs ~0.3s, action completes (waittime honored, NOT the default).
    - Uses a real in-process orch with RPC dispatcher bound + RPCClient.

E3. Both tests run 3 times for determinism.
"""
from __future__ import annotations

import asyncio
import tempfile
import time
import uuid as _uuid
from datetime import datetime

import pytest

from helao.core.rpc import RPCClient, derive_rpc_port
from helao.framework.adapters.fakes.storage import FakeStorage
from helao.framework.adapters.ntp_clock import NtpClock
from helao.framework.adapters.queue_eventsink import QueueEventSink
from helao.framework.app.orch_api import OrchPorts, makeOrchApp
from helao.framework.domain.run_models import RunAction
from helao.framework.models.machine import MachineModel
from helao.framework.models.hlostatus import HloStatus

from helao.framework.tests._fake_action_server import (
    _RunningServer,
    _free_http_port,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_orch_with_rpc(tmp_path: str):
    """Build a real orch app with a running RPC dispatcher.

    Returns (app, orch_host, orch_port, rpc_port).
    """
    orch_key = "ORCH"
    orch_host = "127.0.0.1"
    orch_port = _free_http_port()
    rpc_port = derive_rpc_port(orch_port)

    ports = OrchPorts(
        transport=None,
        storage=FakeStorage(),
        eventsink=QueueEventSink(),
        clock=NtpClock(),
    )
    app = makeOrchApp(orch_key, ports=ports, save_root=tmp_path)

    # Inject server config so _start_rpc() binds the ROUTER socket.
    # (Without a CONFIG slice _start_rpc is skipped; we wire it manually here.)
    from fastapi.routing import APIRoute

    @app.on_event("startup")
    async def _bind_rpc_for_test() -> None:
        rpc = app.state.rpc_dispatcher
        for route in app.routes:
            if isinstance(route, APIRoute) and "POST" in (route.methods or set()):
                rpc.register(route.path, route.endpoint)
        await rpc.serve(host=orch_host, port=rpc_port)

    return app, orch_host, orch_port, rpc_port


# ---------------------------------------------------------------------------
# E1 — empty-args RPC call must NOT crash, must NOT start a WaitExec
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("_run", range(3))
async def test_wait_empty_args_rpc_no_crash_no_executor(_run):
    """E1: RPCClient.call('ORCH/wait') with NO kwargs must not raise TypeError
    and must not register any executor.

    Reproduces the live crash:
        TypeError: argument of type 'Body' is not iterable
    triggered by `"action_params" in body` when body is the Body(None) sentinel.

    After the fix the endpoint returns a benign no-op ack dict (status='noop')
    and base.executors remains empty.
    """
    with tempfile.TemporaryDirectory() as tmp:
        app, orch_host, orch_port, rpc_port = _make_orch_with_rpc(tmp)

        srv = _RunningServer(app, orch_host, orch_port)
        srv.start(timeout=15.0)
        try:
            # Give startup hooks time to fire (RPC dispatcher bind included)
            await asyncio.sleep(0.5)

            client = RPCClient(f"tcp://{orch_host}:{rpc_port}")
            try:
                # No kwargs → req.args={} → _coerce_args Pass2 skipped →
                # Pass3 only handles Body({}) NOT Body(None) → crash pre-fix.
                result = await client.call("ORCH/wait", timeout=5.0)
            finally:
                await client.close()

            # Must return a dict (no exception raised).
            assert isinstance(result, dict), (
                f"Expected dict response from empty-args /wait RPC call, got {result!r}"
            )

            # Must be a no-op ack (not a real wait action started).
            status = result.get("status", "")
            assert status == "noop", (
                f"Empty-args /wait should return status='noop', got status={status!r}. "
                f"Full result: {result}"
            )

            # No executor must have been registered.
            base = app.state.base
            assert not base.executors, (
                f"Empty-args /wait must not register a WaitExec; "
                f"base.executors={base.executors}"
            )
        finally:
            srv.stop()


# ---------------------------------------------------------------------------
# E2 — full action dispatch over RPC: waittime honored (~0.3s), not the default
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("_run", range(3))
async def test_wait_real_action_rpc_honors_waittime(_run):
    """E2: dispatching a full wait action (action_params.waittime=0.3) over real
    RPC starts a WaitExec that runs ~0.3s and completes.

    Verifies that the real orch self-dispatch path (RunAction.as_dict()) still
    works after the fix and that the waittime is honored (the action is still
    active after 0.1s and finishes within 0.7s from dispatch).
    """
    with tempfile.TemporaryDirectory() as tmp:
        app, orch_host, orch_port, rpc_port = _make_orch_with_rpc(tmp)

        srv = _RunningServer(app, orch_host, orch_port)
        srv.start(timeout=15.0)
        try:
            await asyncio.sleep(0.5)

            now = datetime.now()
            action_uuid = _uuid.uuid4()
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
                action_params={"waittime": 0.3},
                save_act=False,
                save_data=False,
            )
            payload = action.as_dict()

            client = RPCClient(f"tcp://{orch_host}:{rpc_port}")
            try:
                result = await client.call("ORCH/wait", timeout=5.0, **payload)
            finally:
                await client.close()

            dispatch_time = time.time()

            # Must return a real action response (not noop).
            assert isinstance(result, dict), (
                f"Expected dict from /wait RPC, got {result!r}"
            )
            assert result.get("status") != "noop", (
                f"Full action dispatch must NOT return noop; result={result}"
            )
            assert "action_uuid" in result, (
                f"Full action dispatch must return action_uuid; result={result}"
            )

            # After 0.1s the WaitExec should still be active (waittime=0.3s).
            await asyncio.sleep(0.1)
            base = app.state.base
            assert base.executors, (
                "WaitExec should still be running at t+0.1s (waittime=0.3s); "
                f"base.executors={base.executors}"
            )

            # Within 0.7s total the executor must finish (0.3s wait + headroom).
            deadline = dispatch_time + 0.7
            finished = False
            while time.time() < deadline:
                await asyncio.sleep(0.05)
                if not base.executors:
                    finished = True
                    break

            assert finished, (
                f"WaitExec did not finish within 0.7s; "
                f"base.executors still={base.executors}"
            )
        finally:
            srv.stop()
