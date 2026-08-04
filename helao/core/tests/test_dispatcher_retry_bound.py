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

import pytest

from helao.core.error import ErrorCodes
from helao.helpers import dispatcher


class _FakeResponse:
    def __init__(self, status, counter):
        self.status = status
        self._counter = counter

    async def json(self):
        return {"detail": "Not Found"}

    async def __aenter__(self):
        self._counter[0] += 1
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    def __init__(self, status, counter, **kwargs):
        self._status = status
        self._counter = counter

    def post(self, *args, **kwargs):
        return _FakeResponse(self._status, self._counter)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeConnector:
    def __init__(self, *args, **kwargs):
        pass

    async def close(self):
        return None


def _run_private(status, retries):
    """Call the private dispatcher against a server replying ``status``."""
    counter = [0]

    def _session(*args, **kwargs):
        return _FakeSession(status, counter, **kwargs)

    with (
        patch.object(dispatcher.aiohttp, "ClientSession", _session),
        patch.object(dispatcher.aiohttp, "TCPConnector", _FakeConnector),
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
