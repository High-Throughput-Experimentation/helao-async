"""An action's POST must not be killed by a clock, and must never be re-sent.

A blocking action holds its POST open for the whole action. ``galil_motion``'s
``move`` is the live example: it awaits the motion inside the endpoint, so the
response arrives when the axes stop. At eche10 that is 688399 counts at
10000 counts/s -- 69 s -- against what used to be a 60 s *total* timeout.

What the clock did when it won is the actual defect. The dispatcher counted the
timeout as a retryable error and re-POSTed a *running* action; the action server
queued the duplicate behind the original and ran it; both actions carried the
same ``orch_submit_order``, so both wrote ``2__0__MOTOR__move`` and the second
overwrote the first's ``-act.yml`` and ``.hlo``. The surviving record read
``error_code: none`` with no sign that anything had been re-commanded.

So: no total timeout (the connect budget stays bounded), and nothing that
happened after the request reached the server is retried.
"""

import asyncio
import logging
import socket

import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

from helao.core.models.machine import MachineModel
from helao.helpers.dispatcher import async_action_dispatcher
from helao.helpers.premodels import Action
from helao.core.error import ErrorCodes

SERVER = "MOTOR"
ACTION = "move"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _action() -> Action:
    return Action(
        action_name=ACTION,
        action_server=MachineModel(server_name=SERVER, machine_name="testhost"),
        action_params={},
    )


class _Runner:
    """A uvicorn server running in this loop; ``cleanup()`` stops it."""

    def __init__(self, server, task):
        self.server, self.task = server, task

    async def cleanup(self):
        self.server.should_exit = True
        await asyncio.wait_for(self.task, 10)


async def _serve(handler, port: int):
    app = Starlette(routes=[Route(f"/{SERVER}/{ACTION}", handler, methods=["POST"])])
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    task = asyncio.create_task(server.serve())
    for _ in range(200):
        if server.started:
            break
        await asyncio.sleep(0.05)
    assert server.started
    return _Runner(server, task)


@pytest.mark.asyncio
async def test_a_slow_action_is_not_timed_out_or_resent():
    port = _free_port()
    calls = []

    async def handler(request):
        calls.append(1)
        # Longer than the connect budget below. Under the old ClientTimeout
        # (total=timeout) this raised TimeoutError at 1 s and the dispatcher
        # re-POSTed, which is how a second move reached the hardware.
        await asyncio.sleep(2.0)
        return JSONResponse({"action_uuid": "abc", "ok": True})

    runner = await _serve(handler, port)
    try:
        world_cfg = {"servers": {SERVER: {"host": "127.0.0.1", "port": port}}}
        response, error_code = await async_action_dispatcher(
            world_cfg, _action(), timeout=1, retries=5
        )
    finally:
        await runner.cleanup()

    assert error_code == ErrorCodes.none
    assert response == {"action_uuid": "abc", "ok": True}
    assert len(calls) == 1, f"action was dispatched {len(calls)} times"


@pytest.mark.asyncio
async def test_a_non_200_is_not_retried():
    port = _free_port()
    calls = []

    async def handler(request):
        calls.append(1)
        return JSONResponse({"detail": "nope"}, status_code=422)

    runner = await _serve(handler, port)
    try:
        world_cfg = {"servers": {SERVER: {"host": "127.0.0.1", "port": port}}}
        _response, error_code = await async_action_dispatcher(
            world_cfg, _action(), timeout=1, retries=5
        )
    finally:
        await runner.cleanup()

    # The server answered, so it saw the request. Re-sending a 422 fails
    # identically; re-sending a 500 may duplicate an action that already began.
    assert error_code == ErrorCodes.http
    assert len(calls) == 1, f"action was dispatched {len(calls)} times"


@pytest.mark.asyncio
async def test_an_unreachable_peer_still_fails_within_the_connect_budget():
    # Nothing listening: the request never reaches a server, so retrying is
    # safe -- and the connect budget still has to bound it.
    port = _free_port()
    world_cfg = {"servers": {SERVER: {"host": "127.0.0.1", "port": port}}}
    started = asyncio.get_running_loop().time()
    response, error_code = await async_action_dispatcher(
        world_cfg, _action(), timeout=1, retries=1
    )
    elapsed = asyncio.get_running_loop().time() - started

    assert response is None
    assert error_code != ErrorCodes.none
    # RPC probe (<=1 s) + one connect attempt (<=1 s) + no backoff on the last
    # retry. Generous, because the point is "bounded", not a tuned number.
    assert elapsed < 15, f"took {elapsed:.1f}s against a dead port"


@pytest.mark.asyncio
async def test_a_plain_text_500_is_reported_not_swallowed_as_transport_noise(
    caplog,
):
    """FastAPI returns an unhandled endpoint exception as text/plain.

    Decoding the body before checking the status raised (``ContentTypeError``
    under aiohttp, ``JSONDecodeError`` under httpx), which arrived at the
    generic except arm looking like a transport failure: a stack trace, a
    retry sleep, and the server's own error message discarded. Seen on every
    /get_status poll at teardown, when the action server's driver was already
    disconnected.
    """
    port = _free_port()
    calls = []
    body = "RuntimeError: GamryComAdapter is not connected"

    async def handler(request):
        calls.append(1)
        return PlainTextResponse(body, status_code=500)

    runner = await _serve(handler, port)
    try:
        world_cfg = {"servers": {SERVER: {"host": "127.0.0.1", "port": port}}}
        with caplog.at_level(logging.ERROR):
            response, error_code = await async_action_dispatcher(
                world_cfg, _action(), timeout=1, retries=5
            )
    finally:
        await runner.cleanup()

    assert error_code == ErrorCodes.http
    assert response is None
    assert len(calls) == 1
    # Checking the status before decoding the body is what keeps the server's
    # own message: decoding first raised and threw it away.
    assert any(
        body in rec.getMessage() for rec in caplog.records
    ), "the 500's text/plain body never reached the log"


@pytest.mark.asyncio
async def test_a_proxy_in_the_environment_is_not_used(monkeypatch):
    """Station servers talk to each other directly.

    httpx honours ``HTTP_PROXY``/``ALL_PROXY`` unless told not to (aiohttp
    did not), so a proxy variable on a station would route its own-host
    dispatches and the pre-dispatch HEAD probe through the proxy.
    """
    from helao.helpers.dispatcher import endpoints_available

    dead = f"http://127.0.0.1:{_free_port()}"
    for var in ("HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.setenv(var, dead)
    for var in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(var, raising=False)

    port = _free_port()

    async def handler(request):
        return JSONResponse({"ok": True})

    runner = await _serve(handler, port)
    try:
        world_cfg = {"servers": {SERVER: {"host": "127.0.0.1", "port": port}}}
        response, error_code = await async_action_dispatcher(
            world_cfg, _action(), timeout=1, retries=1
        )
        # HEAD on a POST-only route answers 405: reached, not "could not connect".
        _ok, unavailable = await endpoints_available(
            [f"http://127.0.0.1:{port}/{SERVER}/{ACTION}"]
        )
    finally:
        await runner.cleanup()

    assert error_code == ErrorCodes.none and response == {"ok": True}
    assert unavailable[0][1] == ["client error"], unavailable


@pytest.mark.asyncio
async def test_a_request_the_server_received_is_never_resent():
    """A server that reads the request and then drops the connection may have
    started the action: that must be reported, not re-POSTed. Only a failure
    before the request left (connect) is retried."""
    hits = []

    async def _drop(reader, writer):
        await reader.read(65536)
        hits.append(1)
        writer.close()

    srv = await asyncio.start_server(_drop, "127.0.0.1", 0)
    port = srv.sockets[0].getsockname()[1]
    try:
        world_cfg = {"servers": {SERVER: {"host": "127.0.0.1", "port": port}}}
        response, error_code = await async_action_dispatcher(
            world_cfg, _action(), timeout=1, retries=5
        )
    finally:
        srv.close()
        await srv.wait_closed()

    assert response is None and error_code == ErrorCodes.http
    assert len(hits) == 1, f"a received request was sent {len(hits)} times"


@pytest.mark.asyncio
async def test_a_nan_in_the_body_is_sent_not_refused():
    """httpx's ``json=`` refuses NaN/Inf (``allow_nan=False``) before sending;
    aiohttp sent them and the servers accept them."""
    from helao.helpers.dispatcher import async_private_dispatcher

    port = _free_port()
    got = []

    async def handler(request):
        got.append(await request.body())
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/priv", handler, methods=["POST"])])
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    runner = _Runner(server, asyncio.create_task(server.serve()))
    for _ in range(200):
        if server.started:
            break
        await asyncio.sleep(0.05)
    try:
        response, error_code = await async_private_dispatcher(
            "S", "127.0.0.1", port, "priv", json_dict={"x": float("inf")}, retries=1
        )
    finally:
        await runner.cleanup()

    assert error_code == ErrorCodes.none and response == {"ok": True}
    assert got == [b'{"x": Infinity}']


@pytest.mark.asyncio
async def test_host_names_resolve_through_the_os_resolver(monkeypatch):
    """A station's own name may exist only in the OS resolver (hosts file,
    adapter names), not in DNS. aiohttp with aiodns asked DNS directly and
    could not reach anec-03's own servers (2026-11-11)."""
    import socket

    from helao.helpers.dispatcher import endpoints_available

    real = socket.getaddrinfo
    name = "helao-selftest.invalid"

    def _os_only(host, *a, **kw):
        if host in (name, name.encode()):
            host = "127.0.0.1"
        return real(host, *a, **kw)

    monkeypatch.setattr(socket, "getaddrinfo", _os_only)
    port = _free_port()

    async def handler(request):
        return JSONResponse({"ok": True})

    runner = await _serve(handler, port)
    try:
        world_cfg = {"servers": {SERVER: {"host": name, "port": port}}}
        response, error_code = await async_action_dispatcher(
            world_cfg, _action(), timeout=1, retries=1
        )
        _ok, unavailable = await endpoints_available(
            [f"http://{name}:{port}/{SERVER}/{ACTION}"]
        )
    finally:
        await runner.cleanup()

    assert error_code == ErrorCodes.none and response == {"ok": True}
    assert unavailable[0][1] == ["client error"], unavailable
