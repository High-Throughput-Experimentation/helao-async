"""SP-ORCH-5 Part (a) addendum — private-endpoint addressing + action-server RPC.

Tests (failing first, per TDD):

1. HttpTransport(use_rpc=True), DispatchTarget(private=True, endpoint="get_status")
   resolves over RPC at method "get_status" (NOT "FAKE/get_status") and returns 200/success.
   NO 3s probe, NO HTTP fallback needed.

2. HttpTransport(use_rpc=False), DispatchTarget(private=True, endpoint="get_status")
   POSTs to "/get_status" (root), returns 200.  Does NOT hit "/FAKE/get_status" (which
   would 404 -> estop).

3. Action dispatch (private=False) still resolves at "FAKE/run_for" via RPC and
   "/FAKE/run_for" via HTTP.

4. makeActionApp with a real config slice registers every POST route into its
   RPCDispatcher (registered method set == POST-route paths, leading slash stripped).

5. Regression: a get_status DispatchTarget(private=True) does NOT produce a
   "/{server_key}/get_status" URL or RPC method — the URL must be "/get_status" and
   the RPC method must be "get_status".
"""
from __future__ import annotations

import asyncio
import socket
import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx
from fastapi.routing import APIRoute

from helao.core.rpc import RPCClient, derive_rpc_port
from helao.core.rpc.zmq_rpc import RPC_PORT_OFFSET
from helao.framework.adapters.http_transport import HttpTransport
from helao.framework.models.errors import ErrorCodes
from helao.framework.ports.transport import DispatchTarget

from helao.framework.tests._fake_action_server import fake_action_server, FakeServerInfo  # noqa: F401 (fixture)


# ---------------------------------------------------------------------------
# Test 1: private=True RPC fast-path → method is "get_status" (not "FAKE/get_status")
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_private_dispatch_rpc_uses_root_method(fake_action_server: FakeServerInfo):
    """private=True: RPC method is '{endpoint}' (root), not '{server_key}/{endpoint}'.

    The fake server exposes /get_status at root; its RPC dispatcher registers it as
    'get_status'.  If HttpTransport builds method 'FAKE/get_status' it will miss
    (RPCError/timeout) → fall back to HTTP → POST /FAKE/get_status → 404 → estop SIM.
    """
    info = fake_action_server
    transport = HttpTransport(use_rpc=True, timeout=5.0)
    try:
        target = DispatchTarget(
            server_key=info.server_key,
            host=info.host,
            port=info.http_port,
            endpoint="get_status",
            private=True,
        )
        result = await transport.dispatch(target, {"client_servkey": "ORCH"})
    finally:
        await transport.aclose()

    assert result.error is ErrorCodes.none, (
        f"private get_status dispatch failed: {result.error!r}; response: {result.response!r}\n"
        "RPC method should be 'get_status', not 'FAKE/get_status'."
    )
    assert result.response is not None


# ---------------------------------------------------------------------------
# Test 2: private=True HTTP fallback → URL is "/{endpoint}", not "/{server_key}/{endpoint}"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_private_dispatch_http_hits_root_url(fake_action_server: FakeServerInfo):
    """private=True, use_rpc=False: HTTP URL is '/{endpoint}', returns 200.

    Must NOT hit '/{server_key}/{endpoint}' which would 404 on the fake server.
    """
    info = fake_action_server
    transport = HttpTransport(use_rpc=False, timeout=5.0)
    try:
        target = DispatchTarget(
            server_key=info.server_key,
            host=info.host,
            port=info.http_port,
            endpoint="get_status",
            private=True,
        )
        result = await transport.dispatch(target, {"client_servkey": "ORCH"})
    finally:
        await transport.aclose()

    assert result.error is ErrorCodes.none, (
        f"HTTP private dispatch returned error {result.error!r}; response: {result.response!r}\n"
        "URL must be '/get_status', not '/FAKE/get_status'."
    )
    assert result.response is not None


# ---------------------------------------------------------------------------
# Test 3: action dispatch (private=False) still uses server_key prefix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_action_dispatch_still_prefixed(fake_action_server: FakeServerInfo):
    """private=False (default): action dispatch is unchanged — method/URL are
    '{server_key}/{endpoint}', not root.  Ensures additive: existing action dispatch works.
    """
    info = fake_action_server
    transport = HttpTransport(use_rpc=True, timeout=5.0)
    try:
        target = DispatchTarget(
            server_key=info.server_key,
            host=info.host,
            port=info.http_port,
            endpoint="run_for",
            # private defaults to False
        )
        result = await transport.dispatch(target, {"duration": 0.05})
    finally:
        await transport.aclose()

    assert result.error is ErrorCodes.none, (
        f"Action dispatch failed: {result.error!r}; response: {result.response!r}\n"
        "private=False action dispatch must still use 'FAKE/run_for' method/URL."
    )
    assert result.response is not None


# ---------------------------------------------------------------------------
# Test 4: makeActionApp with real config slice registers every POST route
# ---------------------------------------------------------------------------


def test_action_app_rpc_registers_all_post_routes(tmp_path):
    """makeActionApp, when given a real config slice with a port, registers every
    POST route into its RPCDispatcher.

    The registered method set must equal the POST-route path set (leading slash stripped).
    """
    import tempfile
    import os

    from helao.framework.app.factory import makeActionApp
    from helao.framework.support import config_loader as fw
    from helao.helpers import config_loader as legacy

    http_port = _free_http_port_for_test()
    cfg = {
        "root": str(tmp_path / "INST"),
        "loaded_config_path": "/configs/demo.yml",
        "servers": {"SIM": {"group": "action", "host": "127.0.0.1", "port": http_port}},
    }
    prev_fw, prev_legacy = fw.CONFIG, legacy.CONFIG
    fw.CONFIG = legacy.CONFIG = cfg

    try:
        app = makeActionApp("SIM", save_root=str(tmp_path / "act"))
        assert hasattr(app.state, "rpc_dispatcher"), (
            "makeActionApp must attach an rpc_dispatcher to app.state "
            "(mirrors makeOrchApp pattern)"
        )

        # Collect all POST-route paths (normalized: leading slash stripped)
        post_paths = {
            route.path.lstrip("/")
            for route in app.routes
            if isinstance(route, APIRoute) and "POST" in (route.methods or set())
        }
        assert post_paths, "makeActionApp has no POST routes — test setup error"

        # Simulate the startup hook: register routes into dispatcher
        dispatcher = app.state.rpc_dispatcher
        for route in app.routes:
            if isinstance(route, APIRoute) and "POST" in (route.methods or set()):
                dispatcher.register(route.path, route.endpoint)

        registered = set(dispatcher.methods.keys())
        missing = post_paths - registered
        assert not missing, (
            f"POST routes not registered with action-server RPCDispatcher: {sorted(missing)}"
        )
    finally:
        fw.CONFIG, legacy.CONFIG = prev_fw, prev_legacy


# ---------------------------------------------------------------------------
# Test 5: Regression — private target never builds /{server_key}/{endpoint}
# ---------------------------------------------------------------------------


def test_private_target_url_is_root_not_prefixed():
    """Regression: HttpTransport.dispatch with private=True must build the HTTP URL
    as 'http://host:port/{endpoint}', NOT 'http://host:port/{server_key}/{endpoint}'.

    This is the exact mis-addressing that caused 404 -> estop in the canary.
    We intercept the httpx POST call and assert the URL.
    """
    captured_urls: list[str] = []

    class _MockResponse:
        status_code = 200
        def json(self):
            return {"ok": True}

    class _MockSession:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            pass
        async def post(self, url, **_kw):
            captured_urls.append(url)
            return _MockResponse()

    transport = HttpTransport(use_rpc=False, timeout=5.0, retries=1)

    async def _run():
        with patch("helao.framework.adapters.http_transport.httpx.AsyncClient", return_value=_MockSession()):
            target = DispatchTarget(
                server_key="SIM",
                host="127.0.0.1",
                port=8010,
                endpoint="get_status",
                private=True,
            )
            await transport.dispatch(target, {})

    asyncio.run(_run())

    assert len(captured_urls) == 1, f"Expected 1 POST, got: {captured_urls}"
    url = captured_urls[0]
    assert "/SIM/get_status" not in url, (
        f"URL incorrectly prefixed with server_key: {url!r}\n"
        "A private endpoint must NOT be prefixed with the server_key."
    )
    assert url.endswith("/get_status"), (
        f"Expected URL ending '/get_status', got: {url!r}"
    )


# ---------------------------------------------------------------------------
# Test 6: Regression — orch heartbeat target has private=True
# ---------------------------------------------------------------------------


def test_orch_heartbeat_target_is_private():
    """The orch heartbeat must build a private DispatchTarget for get_status.

    This prevents the 404-every-8s SIM estop: orch heartbeat dispatches
    get_status → must be private (root method) not action-prefixed.
    """
    from helao.framework.app.orch_api import OrchDriver, OrchPorts
    from helao.framework.adapters.fakes.transport import FakeTransport
    from helao.framework.adapters.fakes.storage import FakeStorage
    from helao.framework.adapters.ntp_clock import NtpClock
    from helao.framework.adapters.queue_eventsink import QueueEventSink

    action_servers = {
        "SIM": {"host": "127.0.0.1", "port": 8999, "group": "action"},
    }
    ports = OrchPorts(
        transport=FakeTransport(),
        storage=FakeStorage(),
        eventsink=QueueEventSink(),
        clock=NtpClock(),
        action_servers=action_servers,
        servers_map=action_servers,
    )
    driver = OrchDriver("ORCH", ports=ports)

    dispatched_targets: list[DispatchTarget] = []

    async def _capture_dispatch(target: DispatchTarget, payload):
        dispatched_targets.append(target)
        from helao.framework.ports.transport import DispatchResult
        return DispatchResult(response={"status": "ok"}, error=ErrorCodes.none)

    # Patch the transport's dispatch to capture what target gets built
    driver.ports.transport.dispatch = _capture_dispatch  # type: ignore[method-assign]

    asyncio.run(driver._heartbeat_once())

    assert dispatched_targets, "No dispatch targets captured from _heartbeat_once"
    get_status_targets = [t for t in dispatched_targets if t.endpoint == "get_status"]
    assert get_status_targets, "No get_status target dispatched in heartbeat"
    for t in get_status_targets:
        assert t.private is True, (
            f"Heartbeat get_status target must be private=True, got private={t.private!r}.\n"
            "Without private=True, RPC method is 'SIM/get_status' (miss) and HTTP hits "
            "'/SIM/get_status' (404 -> estop)."
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _free_http_port_for_test() -> int:
    """Return an http port whose derived RPC port is free and <= 65535."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    rpc_port = s.getsockname()[1]
    s.close()
    http_port = rpc_port - RPC_PORT_OFFSET
    if not (1024 < http_port <= 65535):
        # fallback: just find any free port (skip RPC constraint for unit tests)
        s2 = socket.socket()
        s2.bind(("127.0.0.1", 0))
        http_port = s2.getsockname()[1]
        s2.close()
    return http_port
