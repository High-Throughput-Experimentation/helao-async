"""A non-200 reply must exhaust the retry budget, not spin forever.

Both dispatchers' HTTP fallback loop on ``while not success and retry_count <
retries``. The non-200 branch set ``success = False`` and returned to the top
*without touching* ``retry_count``, so the condition never changed: any 404,
422 or 500 became an unbounded tight loop.

It was found the way it would be found in production — a control panel calling
a private endpoint the target server does not have. One page load produced
46,698 requests in fifty seconds, the page rendered blank, and the only symptom
was a wall of identical ERROR lines. Nothing raised, and no caller could set a
bound, because ``retries`` was the parameter that did not apply.

These tests count attempts, which is the property that was wrong. They stub the
HTTP layer rather than binding a socket, so they are fast and hermetic.
"""

import asyncio
from unittest.mock import patch

import httpx
import pytest

from helao.core.error import ErrorCodes
from helao.helpers import dispatcher


def _counting_client(status, counter):
    """An ``httpx.AsyncClient`` factory whose transport answers ``status``."""
    real = httpx.AsyncClient

    def _handler(request):
        counter[0] += 1
        return httpx.Response(status, json={"detail": "Not Found"})

    def _client(*args, **kwargs):
        return real(*args, transport=httpx.MockTransport(_handler), **kwargs)

    return _client


def _run_private(status, retries):
    """Call the private dispatcher against a server replying ``status``."""
    counter = [0]

    with (
        patch.object(httpx, "AsyncClient", _counting_client(status, counter)),
        # No RPC peer, so the call takes the HTTP fallback under test. `new=`
        # with a coroutine function, not `side_effect=`: the target is async,
        # and a sync Mock raises when the dispatcher awaits it.
        patch.object(dispatcher, "_get_rpc_client", new=_no_rpc),
        patch.object(dispatcher.asyncio, "sleep", new=_no_sleep),
    ):
        response, error_code = asyncio.run(
            dispatcher.async_private_dispatcher(
                server_key="SIM",
                host="127.0.0.1",
                port=8002,
                private_action="get_digital_outs",
                timeout=1,
                retries=retries,
            )
        )
    return counter[0], error_code


async def _no_sleep(_seconds):
    """Skip the retry backoff so the test measures attempts, not wall clock."""
    return None


async def _no_rpc(*args, **kwargs):
    """Force the HTTP fallback, which is the path with the bug.

    ``OSError`` specifically: the fast path catches only ``(RPCError,
    TimeoutError, ZMQError, OSError)``, so any other exception propagates
    instead of falling back — and this stub stands in for a peer with no RPC
    dispatcher listening, which is a refused connection.
    """
    raise OSError("no rpc peer")


@pytest.mark.parametrize("status", [404, 422, 500])
@pytest.mark.parametrize("retries", [1, 3])
def test_a_non_200_stops_after_the_retry_budget(status, retries):
    attempts, error_code = _run_private(status, retries)

    assert (
        attempts == retries
    ), f"status {status} with retries={retries} made {attempts} attempts"
    assert error_code == ErrorCodes.http
    print(f"test_a_non_200_stops_after_the_retry_budget[{status},{retries}] PASS")


def test_a_200_is_not_retried():
    attempts, error_code = _run_private(200, retries=3)

    assert attempts == 1, attempts
    assert error_code == ErrorCodes.none
    print("test_a_200_is_not_retried PASS")


def test_the_call_terminates_at_all():
    # The regression in one line: before the fix this never returned.
    async def _bounded():
        return await asyncio.wait_for(
            asyncio.to_thread(_run_private, 404, 2), timeout=10
        )

    attempts, _ = asyncio.run(_bounded())
    assert attempts == 2
    print("test_the_call_terminates_at_all PASS")


def test_an_rpc_handler_error_is_not_resent_over_http():
    """The handler ran and raised; an HTTP re-send runs it again and, on a
    deterministic error, walks the whole HTTP backoff (30+60+90+120 s) for
    nothing. That is how one bad status push stalled note1 ANA's status queue
    for 25 minutes (2026-11-02)."""
    counter = [0]

    class _RaisingClient:
        async def call(self, *args, **kwargs):
            raise dispatcher.RPCHandlerError("TypeError: boom")

    async def _client(*args, **kwargs):
        return _RaisingClient()

    with (
        patch.object(httpx, "AsyncClient", _counting_client(200, counter)),
        patch.object(dispatcher, "_get_rpc_client", new=_client),
        patch.object(dispatcher.asyncio, "sleep", new=_no_sleep),
    ):
        response, error_code = asyncio.run(
            dispatcher.async_private_dispatcher(
                server_key="ORCH",
                host="127.0.0.1",
                port=8002,
                private_action="update_status",
            )
        )
    assert counter[0] == 0, f"handler error fell back to {counter[0]} HTTP POSTs"
    assert response is None and error_code == ErrorCodes.http


@pytest.mark.parametrize("method", ["send_statuspackage", "send_nbstatuspackage"])
def test_status_packages_post_once_per_call(method):
    """Every caller of these wraps them in its own retry loop
    (log_status_task, regular_status_task, send_nonblocking_status), so the
    dispatcher must not retry underneath: 5 x 5 nested attempts with backoff
    held a status queue for ~25 minutes per undeliverable message."""
    from types import SimpleNamespace

    from helao.hexagon.app.action_host import ActionHost

    counter = [0]

    host = SimpleNamespace(
        actionservermodel=SimpleNamespace(get_fastapi_json=lambda **kw: {}),
        server_cfg={"host": "127.0.0.1", "port": 8003},
    )
    kwargs: dict = dict(
        client_servkey="ORCH", client_host="127.0.0.1", client_port=8002
    )
    if method == "send_nbstatuspackage":
        kwargs["actionmodel"] = SimpleNamespace(as_dict=lambda: {})
    with (
        patch.object(httpx, "AsyncClient", _counting_client(500, counter)),
        patch.object(dispatcher, "_get_rpc_client", new=_no_rpc),
        patch.object(dispatcher.asyncio, "sleep", new=_no_sleep),
    ):
        _response, error_code = asyncio.run(getattr(ActionHost, method)(host, **kwargs))
    assert counter[0] == 1, f"{method} made {counter[0]} POSTs"
    assert error_code == ErrorCodes.http
