"""Tests for the real HttpTransport adapter.

The HTTP dispatch/probe paths run against a real in-process uvicorn server on
a free localhost port (a faithful network round-trip). The RPC fast-path is
exercised indirectly via the fallback (RPC dispatcher absent -> HTTP succeeds),
and the error-mapping helpers are unit-tested directly.

Path coverage notes:
- EXERCISED: HTTP success -> DispatchResult(response, ErrorCodes.none);
  non-2xx -> ErrorCodes.http (no raise); connection failure -> not_available
  (no raise); retry/backoff invoked on transient failure; probe classification
  (available / could-not-connect / client-error); RPC->HTTP fallback.
- NOT EXERCISED end-to-end: a live ZMQ RPC dispatcher returning a successful
  result (standing up a ROUTER server in-test is heavy and the RPC client is
  already covered by helao.core.rpc's own suite). The RPC error->fallback edge
  and error classification are covered via classify_transport_error and the
  fallback test.
"""
import asyncio
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from helao.core.rpc import RPCError
from helao.framework.adapters.http_transport import (
    HttpTransport,
    classify_http_status,
    classify_probe_status,
    classify_transport_error,
)
from helao.framework.models.errors import ErrorCodes
from helao.framework.ports.transport import DispatchTarget, Transport


# --------------------------------------------------------------------------
# In-process uvicorn server fixture
# --------------------------------------------------------------------------


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _RunningServer:
    def __init__(self, app, port: int) -> None:
        self.port = port
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        self.server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self) -> None:
        self._thread.start()
        deadline = time.time() + 10
        while not self.server.started and time.time() < deadline:
            time.sleep(0.02)
        if not self.server.started:
            raise RuntimeError("uvicorn test server did not start")

    def stop(self) -> None:
        self.server.should_exit = True
        self._thread.join(timeout=10)


async def _echo(request: Request) -> JSONResponse:
    if request.method == "HEAD":
        return JSONResponse({})
    body = await request.json()
    return JSONResponse({"echo": body, "path": request.url.path})


async def _boom(request: Request) -> JSONResponse:
    return JSONResponse({"detail": "kaboom"}, status_code=500)


@pytest.fixture(scope="module")
def server():
    app = Starlette(
        routes=[
            Route("/svc/echo", _echo, methods=["POST", "HEAD"]),
            Route("/svc/boom", _boom, methods=["POST", "HEAD"]),
        ]
    )
    srv = _RunningServer(app, _free_port())
    srv.start()
    yield srv
    srv.stop()


def _target(server, endpoint: str) -> DispatchTarget:
    return DispatchTarget(
        server_key="svc", host="127.0.0.1", port=server.port, endpoint=endpoint
    )


# --------------------------------------------------------------------------
# Protocol conformance
# --------------------------------------------------------------------------


def test_satisfies_protocol():
    transport: Transport = HttpTransport()
    assert isinstance(transport, Transport)


# --------------------------------------------------------------------------
# dispatch over HTTP (RPC disabled to isolate the HTTP path)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_http_success_returns_response_and_none(server):
    transport = HttpTransport(use_rpc=False)
    result = await transport.dispatch(_target(server, "echo"), {"hello": "world"})
    assert result.error is ErrorCodes.none
    assert result.response == {"echo": {"hello": "world"}, "path": "/svc/echo"}


@pytest.mark.asyncio
async def test_dispatch_http_non_2xx_maps_to_http_without_raising(server):
    transport = HttpTransport(use_rpc=False)
    result = await transport.dispatch(_target(server, "boom"), {})
    assert result.error is ErrorCodes.http
    assert result.response == {"detail": "kaboom"}


@pytest.mark.asyncio
async def test_dispatch_connection_failure_maps_to_not_available(server):
    # Point at a port nobody is listening on.
    transport = HttpTransport(use_rpc=False, retries=2, timeout=2.0)
    transport._backoff = _no_sleep  # type: ignore[assignment]
    target = DispatchTarget(
        server_key="svc", host="127.0.0.1", port=_free_port(), endpoint="echo"
    )
    result = await transport.dispatch(target, {})
    assert result.response is None
    assert result.error is ErrorCodes.not_available


@pytest.mark.asyncio
async def test_dispatch_retries_with_backoff_then_succeeds(server, monkeypatch):
    # Patch the adapter's httpx.AsyncClient so the first two POSTs raise a
    # transient transport error, then the real client takes over.
    real_client = httpx.AsyncClient
    state = {"calls": 0}

    class FlakyClient:
        def __init__(self, *a, **kw):
            self._inner = real_client(*a, **kw)

        async def __aenter__(self):
            await self._inner.__aenter__()
            return self

        async def __aexit__(self, *a):
            await self._inner.__aexit__(*a)

        async def post(self, *a, **kw):
            state["calls"] += 1
            if state["calls"] <= 2:
                raise httpx.ConnectError("transient")
            return await self._inner.post(*a, **kw)

    monkeypatch.setattr(
        "helao.framework.adapters.http_transport.httpx.AsyncClient", FlakyClient
    )

    transport = HttpTransport(use_rpc=False, retries=5, timeout=2.0)
    waits: list[float] = []

    async def record_backoff(seconds: float) -> None:
        waits.append(seconds)

    transport._backoff = record_backoff  # type: ignore[assignment]

    result = await transport.dispatch(_target(server, "echo"), {"k": 1})
    assert result.error is ErrorCodes.none
    assert result.response == {"echo": {"k": 1}, "path": "/svc/echo"}
    # Two transient failures -> two backoff sleeps with linear growth.
    assert len(waits) == 2
    assert waits[0] < waits[1]


@pytest.mark.asyncio
async def test_dispatch_exhausts_retries_returns_classified_error(server, monkeypatch):
    real_client = httpx.AsyncClient

    class AlwaysFail:
        def __init__(self, *a, **kw):
            self._inner = real_client(*a, **kw)

        async def __aenter__(self):
            await self._inner.__aenter__()
            return self

        async def __aexit__(self, *a):
            await self._inner.__aexit__(*a)

        async def post(self, *a, **kw):
            raise httpx.ConnectError("down")

    monkeypatch.setattr(
        "helao.framework.adapters.http_transport.httpx.AsyncClient", AlwaysFail
    )
    transport = HttpTransport(use_rpc=False, retries=3, timeout=1.0)
    transport._backoff = _no_sleep  # type: ignore[assignment]
    result = await transport.dispatch(_target(server, "echo"), {})
    assert result.response is None
    assert result.error is ErrorCodes.not_available


# --------------------------------------------------------------------------
# RPC -> HTTP fallback (no RPC dispatcher running -> falls back to HTTP)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rpc_unavailable_falls_back_to_http(server):
    # use_rpc=True but no RPC dispatcher on the derived port -> the DEALER call
    # times out after the probe timeout and the HTTP fallback succeeds.
    transport = HttpTransport(use_rpc=True, retries=2, timeout=1.0)
    try:
        result = await transport.dispatch(_target(server, "echo"), {"k": "v"})
        assert result.error is ErrorCodes.none
        assert result.response == {"echo": {"k": "v"}, "path": "/svc/echo"}
    finally:
        await transport.aclose()


# --------------------------------------------------------------------------
# probe classification
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_probe_all_available(server):
    transport = HttpTransport()
    result = await transport.probe([_target(server, "echo")])
    assert result.available is True
    assert result.unavailable == []


@pytest.mark.asyncio
async def test_probe_classifies_unavailable(server):
    transport = HttpTransport(probe_timeout=2.0)
    targets = [
        _target(server, "echo"),  # 2xx -> available
        _target(server, "boom"),  # 500 -> server error
        DispatchTarget(  # dead port -> could not connect
            server_key="svc", host="127.0.0.1", port=_free_port(), endpoint="echo"
        ),
    ]
    result = await transport.probe(targets)
    assert result.available is False
    reasons = dict(result.unavailable)
    assert reasons["svc/boom"] == "server error"
    assert any("could not connect" == r for _, r in result.unavailable)


# --------------------------------------------------------------------------
# error-mapping helpers (unit)
# --------------------------------------------------------------------------


def test_classify_http_status():
    assert classify_http_status(200) is ErrorCodes.none
    assert classify_http_status(204) is ErrorCodes.none
    assert classify_http_status(404) is ErrorCodes.http
    assert classify_http_status(500) is ErrorCodes.http


def test_classify_probe_status():
    assert classify_probe_status(200) is None
    assert classify_probe_status(404) == "client error"
    assert classify_probe_status(503) == "server error"
    assert classify_probe_status(302) == "no success"


def test_classify_transport_error():
    assert classify_transport_error(asyncio.TimeoutError()) is ErrorCodes.timeout
    assert (
        classify_transport_error(httpx.ConnectTimeout("x")) is ErrorCodes.timeout
    )
    assert classify_transport_error(RPCError("bad")) is ErrorCodes.cmd_error
    assert (
        classify_transport_error(httpx.ConnectError("refused"))
        is ErrorCodes.not_available
    )
    assert classify_transport_error(OSError()) is ErrorCodes.not_available
    assert classify_transport_error(ValueError("?")) is ErrorCodes.unspecified


# --------------------------------------------------------------------------
# pub/sub stubs
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_reports_unwired_stub():
    from helao.framework.ports.transport import Message

    transport = HttpTransport()
    result = await transport.publish(Message(name="status", payload={}))
    assert result.delivered is False
    assert result.error is not None


def test_subscribe_records_handler():
    transport = HttpTransport()

    async def handler(_msg):
        return None

    transport.subscribe(handler)
    assert transport._handlers == [handler]


async def _no_sleep(seconds: float) -> None:
    return None
