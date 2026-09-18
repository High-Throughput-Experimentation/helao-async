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
from aiohttp import web

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


async def _serve(handler, port: int):
    app = web.Application()
    app.router.add_post(f"/{SERVER}/{ACTION}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    return runner


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
        return web.json_response({"action_uuid": "abc", "ok": True})

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
        return web.json_response({"detail": "nope"}, status=422)

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

    Decoding the body before checking the status raised

        aiohttp.client_exceptions.ContentTypeError: 500, message='Attempt to
        decode JSON with unexpected mimetype: text/plain; charset=utf-8'

    which arrived at the generic except arm looking like a transport failure:
    a stack trace, a retry sleep, and the server's own error message
    discarded. Seen on every /get_status poll at teardown, when the action
    server's driver was already disconnected.
    """
    port = _free_port()
    calls = []
    body = "RuntimeError: GamryComAdapter is not connected"

    async def handler(request):
        calls.append(1)
        return web.Response(status=500, text=body)

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
    # own message: decoding first raised ContentTypeError and threw it away.
    assert any(
        body in rec.getMessage() for rec in caplog.records
    ), "the 500's text/plain body never reached the log"
