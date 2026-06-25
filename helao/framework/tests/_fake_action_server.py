"""Headless fake action server fixture for SP-ORCH-5 integration tests.

Provides a *real* framework action server (``BaseAPI``) running in-process over
**two** transports simultaneously:

* **HTTP / WebSocket** — via uvicorn on an OS-assigned ephemeral port (a real
  TCP socket, not ASGI-transport, so WebSocket upgrade and ``/ws_status`` push
  work without any in-process shim).
* **ZMQ-RPC** — an ``RPCDispatcher`` ROUTER socket bound on
  ``derive_rpc_port(http_port)`` with every POST route registered, mirroring the
  orch's startup wiring so ``HttpTransport(use_rpc=True)`` can hit the fast path.

The server exposes one action endpoint ``/{server_key}/run_for`` backed by a
``SleepExecutor`` that calls ``asyncio.sleep(duration)`` then finishes, pushing
genuine ``/ws_status`` started→finished ``ActionServerModel`` JSON updates via
the ``BaseAPI._ws_relay`` path.

Public API
----------
``fake_action_server`` — a ``pytest.fixture`` (function scope) that yields a
:class:`FakeServerInfo` named-tuple::

    FakeServerInfo(server_key, host, http_port)

The ``run_for`` action accepts a ``RunAction`` body; ``duration`` is read from
``action_params`` (default ``0.05`` seconds).

``_free_http_port()`` — helper that returns an HTTP port whose derived RPC port
is also free and within valid range (``<= 65535``).

``FakeServerInfo`` — a ``NamedTuple`` with ``server_key``, ``host``,
``http_port`` fields.

Task 2 note
-----------
The RPC dispatcher is exposed on ``app.state.rpc_dispatcher`` (mirrors the
orch's pattern) so Task 2 can assert the registered method set. The fixture
yields with the server started; tests should not call startup/shutdown themselves.
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from typing import NamedTuple

import pytest
import uvicorn

from fastapi import Body as _Body

from helao.core.rpc import RPCDispatcher, derive_rpc_port
from helao.core.rpc.zmq_rpc import RPC_PORT_OFFSET
from helao.framework.app.base_api import ACTION_CTX, BaseAPI
from helao.framework.domain.executor import Executor
from helao.framework.models.errors import ErrorCodes


# ---------------------------------------------------------------------------
# Port helpers
# ---------------------------------------------------------------------------


def _free_http_port() -> int:
    """Return an HTTP port whose derived RPC port is free and ≤ 65535.

    Strategy (mirrors ``test_app_orch_rpc_server.py``): bind the *RPC* socket
    first (so we know it's free), then derive the HTTP port downward.  The RPC
    socket is released immediately; a tiny TOCTOU window exists but is
    acceptable for test fixtures.
    """
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    rpc_port = s.getsockname()[1]
    s.close()
    http_port = rpc_port - RPC_PORT_OFFSET
    assert 1024 < http_port <= 65535, f"derived http_port {http_port} out of range"
    assert derive_rpc_port(http_port) <= 65535
    return http_port


# ---------------------------------------------------------------------------
# SleepExecutor — the fake action executor
# ---------------------------------------------------------------------------


class SleepExecutor(Executor):
    """Executor that sleeps ``duration`` seconds then finishes.

    ``duration`` is read from ``active.action.action_params['duration']``
    (default ``0.05`` s) so callers can pass short durations for fast tests.
    """

    def __init__(self, active, **kwargs):
        super().__init__(active, oneoff=True, **kwargs)

    async def _exec(self) -> dict:
        duration = float(self.active.action.action_params.get("duration", 0.05))
        await asyncio.sleep(duration)
        return {"data": {"slept": duration}, "error": ErrorCodes.none}


# ---------------------------------------------------------------------------
# App factory — creates a BaseAPI with the run_for endpoint + RPC dispatcher
# ---------------------------------------------------------------------------


def _make_fake_action_app(server_key: str, save_root: str) -> "BaseAPI":
    """Build a ``BaseAPI`` with one ``run_for`` action and a co-located RPC dispatcher."""
    app = BaseAPI(server_key=server_key, save_root=save_root)

    # Attach the (initially unbound) RPC dispatcher — mirrors orch_api pattern.
    rpc = RPCDispatcher(server_key=server_key)
    app.state.rpc_dispatcher = rpc

    # --- run_for action endpoint -------------------------------------------
    # Tagged ``["action"]`` so ``ActionAPIRoute`` auto-wraps it via
    # ``wrap_action_endpoint``, which injects ``action: RunAction = Body(embed=True)``
    # and populates ACTION_CTX.  The orch dispatch payload
    # ``{**action_params, "action": action.as_dict()}`` feeds both the flat
    # ``duration`` param and the embedded RunAction through this wrapper.
    # ``init_act()`` fills missing uuid/timestamps for direct test calls that
    # send only ``{"duration": x}`` without an embedded ``"action"`` key.

    @app.post(f"/{server_key}/run_for", tags=["action"])
    async def run_for(duration: float = _Body(-1, embed=True)) -> dict:
        """Sleep ``duration`` seconds then finish.

        Driven through ``ACTION_CTX`` → ``setup_and_contain_action`` →
        ``SleepExecutor`` → ``start_executor``.  Returns immediately; the
        executor loop runs in the background so ``/ws_status`` carries real
        started → finished updates.
        """
        ctx = ACTION_CTX.get(None)
        if ctx is None:
            return {"error": "no ACTION_CTX"}
        ctx.action.action_name = ctx.action.action_name or "run_for"
        ctx.action.init_act()
        active = await app.base.setup_and_contain_action(ctx)
        active.action.action_params["duration"] = duration
        executor = SleepExecutor(active=active)
        active.start_executor(executor)
        return {"action_uuid": str(active.action.action_uuid), "status": "active", "duration": duration}

    # --- RPC startup: register all POST routes and bind ROUTER socket --------

    @app.on_event("startup")
    async def _start_rpc() -> None:
        from fastapi.routing import APIRoute

        for route in app.routes:
            if isinstance(route, APIRoute) and "POST" in (route.methods or set()):
                rpc.register(route.path, route.endpoint)
        # rpc_port is set by FakeActionServer.start() before startup fires;
        # fall back to deriving from server_cfg if available.
        port = getattr(app.state, "_rpc_port", None)
        if port is None:
            # derive from server_cfg set at fixture construction time
            port = derive_rpc_port(app.state._http_port)
        await rpc.serve(host="127.0.0.1", port=port)

    @app.on_event("shutdown")
    async def _stop_rpc() -> None:
        await rpc.close()

    return app


# ---------------------------------------------------------------------------
# FakeServerInfo — what the fixture yields
# ---------------------------------------------------------------------------


class FakeServerInfo(NamedTuple):
    """Connection coordinates yielded by the ``fake_action_server`` fixture."""

    server_key: str
    host: str
    http_port: int


# ---------------------------------------------------------------------------
# _RunningServer — uvicorn runner (mirrors test_adapters_http_transport.py)
# ---------------------------------------------------------------------------


class _RunningServer:
    """Manages a uvicorn server running in a background daemon thread."""

    def __init__(self, app, host: str, port: int) -> None:
        self.host = host
        self.port = port
        config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level="warning",
            loop="asyncio",
        )
        self.server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self, timeout: float = 15.0) -> None:
        self._thread.start()
        deadline = time.time() + timeout
        while not self.server.started and time.time() < deadline:
            time.sleep(0.02)
        if not self.server.started:
            raise RuntimeError(
                f"uvicorn fake action server did not start on port {self.port}"
            )

    def stop(self) -> None:
        self.server.should_exit = True
        self._thread.join(timeout=10)


# ---------------------------------------------------------------------------
# pytest fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_action_server(tmp_path):
    """Pytest fixture: a real in-process framework action server.

    Yields a :class:`FakeServerInfo` ``(server_key, host, http_port)`` with:

    * An HTTP server at ``http://host:http_port`` with endpoint
      ``POST /{server_key}/run_for`` and WebSocket ``/ws_status``.
    * A ZMQ-RPC ROUTER on ``derive_rpc_port(http_port)`` with every POST route
      registered (so ``HttpTransport(use_rpc=True)`` hits the fast path).

    Teardown cancels the RPC dispatcher and stops uvicorn cleanly.
    """
    import tempfile

    server_key = "FAKE"
    host = "127.0.0.1"
    http_port = _free_http_port()
    rpc_port = derive_rpc_port(http_port)

    save_root = str(tmp_path / "fake_server")

    app = _make_fake_action_app(server_key, save_root)
    # Stash the ports so the startup hooks can read them.
    app.state._http_port = http_port
    app.state._rpc_port = rpc_port

    srv = _RunningServer(app, host, http_port)
    srv.start()

    yield FakeServerInfo(server_key=server_key, host=host, http_port=http_port)

    srv.stop()
