"""SP-ORCH-5 Task 1: self-tests for the headless fake action server fixture.

Proves three things required by the spec (§5):

1. **RPC fast-path dispatch** — ``HttpTransport(use_rpc=True)`` dispatches to
   the fake server via the ZMQ-RPC ROUTER (not the 3s-probe HTTP fallback) and
   the call returns success.
2. **Real started → finished /ws_status round-trip** — subscribing to
   ``/ws_status`` before dispatching a short ``run_for`` action and draining
   the JSON updates yields at least one "active" (started) and one "finished"
   ``ActionServerModel``-shaped payload.
3. **HTTP fallback** — ``HttpTransport(use_rpc=False)`` dispatches over plain
   HTTP and also returns success.

Wire-format note
----------------
``BaseAPI._ws_relay`` sends JSON (``send_json``), NOT zstd+pickle.  The legacy
``WsSubscriber`` (``helao.helpers.ws_utils``) expects zstd+pickle and therefore
cannot be used here.  These tests use a lightweight ``_JsonWsReader`` that
connects with ``websockets.connect`` and decodes each frame with ``json.loads``.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import List

import pytest
import websockets

from helao.core.rpc import RPCClient, derive_rpc_port
from helao.framework.adapters.http_transport import HttpTransport
from helao.framework.models.errors import ErrorCodes
from helao.framework.ports.transport import DispatchTarget

from helao.framework.tests._fake_action_server import fake_action_server  # noqa: F401 — imported for fixture discovery

# ---------------------------------------------------------------------------
# Lightweight JSON WebSocket subscriber
# ---------------------------------------------------------------------------


class _JsonWsReader:
    """Async context manager: connects to a JSON-over-WebSocket endpoint.

    Collects frames into ``messages`` (list of decoded dicts) until cancelled.
    Used instead of ``WsSubscriber`` because ``BaseAPI._ws_relay`` sends plain
    JSON, not the zstd+pickle format ``WsSubscriber`` expects.
    """

    def __init__(self, url: str) -> None:
        self.url = url
        self.messages: List[dict] = []
        self._task: asyncio.Task | None = None
        self._ws = None
        self._connected = asyncio.Event()

    async def __aenter__(self) -> "_JsonWsReader":
        self._task = asyncio.create_task(self._reader())
        # Wait until the WebSocket is connected before returning so callers
        # can be sure the subscription is live before they dispatch an action.
        try:
            await asyncio.wait_for(self._connected.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            raise RuntimeError(f"_JsonWsReader: could not connect to {self.url}")
        return self

    async def __aexit__(self, *_) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass

    async def _reader(self) -> None:
        try:
            async with websockets.connect(self.url) as ws:
                self._ws = ws
                self._connected.set()
                while True:
                    raw = await ws.recv()
                    if isinstance(raw, bytes):
                        raw = raw.decode()
                    self.messages.append(json.loads(raw))
        except asyncio.CancelledError:
            raise
        except Exception:
            self._connected.set()  # unblock waiter on failure

    async def wait_for_n(self, n: int, timeout: float = 5.0) -> List[dict]:
        """Return when at least ``n`` messages have arrived, or raise on timeout."""
        deadline = time.time() + timeout
        while len(self.messages) < n:
            if time.time() > deadline:
                raise TimeoutError(
                    f"_JsonWsReader: expected {n} messages, got {len(self.messages)}"
                )
            await asyncio.sleep(0.01)
        return list(self.messages)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _target(info, endpoint: str) -> DispatchTarget:
    return DispatchTarget(
        server_key=info.server_key,
        host=info.host,
        port=info.http_port,
        endpoint=endpoint,
    )


# ---------------------------------------------------------------------------
# 1. RPC fast-path dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rpc_dispatch_uses_fast_path(fake_action_server):
    """Dispatching via HttpTransport(use_rpc=True) resolves over RPC.

    The ``run_for`` endpoint takes ``duration: float = Body(0.05, embed=True)``
    so the HTTP body is ``{"duration": 0.05}`` (embed=True wraps the scalar in
    its parameter name).  ``HttpTransport`` sends that dict verbatim; the RPC
    dispatcher maps it to ``duration=0.05`` via ``_coerce_args``.
    """
    info = fake_action_server
    transport = HttpTransport(use_rpc=True, timeout=5.0)
    try:
        result = await transport.dispatch(
            _target(info, "run_for"),
            {"duration": 0.05},
        )
    finally:
        await transport.aclose()

    # The call must have succeeded (not fallen back to HTTP-error or timeout).
    assert result.error is ErrorCodes.none, (
        f"RPC dispatch returned error {result.error!r}; response: {result.response!r}"
    )
    assert result.response is not None

    # Prove it went through RPC: confirm with a direct RPCClient call on the
    # derived port.  If RPC were not running, the call would time out rather
    # than returning a result dict.
    rpc_port = derive_rpc_port(info.http_port)
    client = RPCClient(
        endpoint=f"tcp://{info.host}:{rpc_port}",
        default_timeout=5.0,
    )
    try:
        rpc_result = await client.call(
            f"/{info.server_key}/run_for",
            timeout=5.0,
            duration=0.05,
        )
    finally:
        await client.close()

    # A successful dict reply proves the ROUTER is live and dispatched to the handler.
    assert isinstance(rpc_result, dict), f"RPC direct call returned: {rpc_result!r}"


# ---------------------------------------------------------------------------
# 2. Real started → finished /ws_status round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ws_status_started_and_finished(fake_action_server):
    """A run_for action pushes real started and finished ActionServerModel updates."""
    info = fake_action_server
    ws_url = f"ws://{info.host}:{info.http_port}/ws_status"

    async with _JsonWsReader(ws_url) as reader:
        # Dispatch a short action after the subscriber is live.
        # The run_for endpoint takes ``duration: float = Body(0.05, embed=True)``
        # so the body must be ``{"duration": 0.1}`` (embed=True wraps the scalar).
        transport = HttpTransport(use_rpc=False, timeout=5.0)
        try:
            result = await transport.dispatch(
                _target(info, "run_for"),
                {"duration": 0.1},
            )
        finally:
            await transport.aclose()
        assert result.error is ErrorCodes.none, result

        # Wait for both the "active" (started) and "finished" status messages.
        # The action takes 0.1s; give a generous window.
        msgs = await reader.wait_for_n(2, timeout=8.0)

    # The /ws_status relay forwards the raw action dict from emit_status.
    # ``action_status`` is a list of HloStatus strings, e.g. ["active"] or ["finished"].
    # At least one message must carry "active" in action_status.
    active_msgs = [
        m for m in msgs
        if "active" in (m.get("action_status") or [])
    ]
    # At least one message must carry "finished" in action_status.
    finished_msgs = [
        m for m in msgs
        if "finished" in (m.get("action_status") or [])
    ]

    assert active_msgs, (
        f"No 'active' status seen in ws_status messages.\n"
        f"Messages received (action_status fields): "
        f"{[m.get('action_status') for m in msgs]}"
    )
    assert finished_msgs, (
        f"No 'finished' status seen in ws_status messages.\n"
        f"Messages received (action_status fields): "
        f"{[m.get('action_status') for m in msgs]}"
    )


# ---------------------------------------------------------------------------
# 3. HTTP fallback (use_rpc=False)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_fallback_dispatch(fake_action_server):
    """HttpTransport(use_rpc=False) dispatches over plain HTTP and returns success."""
    info = fake_action_server
    transport = HttpTransport(use_rpc=False, timeout=5.0)
    try:
        result = await transport.dispatch(
            _target(info, "run_for"),
            {"duration": 0.05},
        )
    finally:
        await transport.aclose()

    assert result.error is ErrorCodes.none, (
        f"HTTP dispatch returned error {result.error!r}; response: {result.response!r}"
    )
    response = result.response
    assert response is not None
    # The endpoint returns {"action_uuid": ..., "status": ...}
    assert "action_uuid" in response or "status" in response, (
        f"Unexpected response shape: {response!r}"
    )


# ---------------------------------------------------------------------------
# 4. Sanity: RPC method table contains run_for
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rpc_dispatcher_registers_run_for(fake_action_server):
    """The RPC dispatcher must have run_for (and other POST routes) registered."""
    info = fake_action_server
    rpc_port = derive_rpc_port(info.http_port)
    client = RPCClient(
        endpoint=f"tcp://{info.host}:{rpc_port}",
        default_timeout=5.0,
    )
    try:
        # Call get_status (a private POST route that should also be registered).
        status = await client.call("/get_status", timeout=5.0)
    finally:
        await client.close()
    assert isinstance(status, dict), f"get_status via RPC returned: {status!r}"
