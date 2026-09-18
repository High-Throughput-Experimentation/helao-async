"""A WebSocket stream must end quietly when the server shuts down.

Every server printed an ASGI traceback at CTRL-x:

    ERROR:    Cancel 1 running task(s), timeout graceful shutdown exceeded
    ERROR:    Exception in ASGI application
    ...
    asyncio.exceptions.CancelledError: Task cancelled, timeout graceful
    shutdown exceeded

Two separate things produce those two lines. The visualizers hold /ws_status,
/ws_data and /ws_live open; nothing tells them to stop, so uvicorn waits the
whole timeout_graceful_shutdown and then cancels the tasks -- that is the
first line. The cancel then escapes ``WsPublisher.broadcast``, which is the
last frame of a WebSocket endpoint, so uvicorn reports it as an unhandled
application exception -- that is the traceback.

``ActionHost.shutdown`` closing the fan-out queues fixes the first (on the
POST /shutdown path, which is the one CTRL-x takes); ``broadcast`` handling
its own cancellation fixes the second, including on the signal path where the
lifespan shutdown event runs only *after* uvicorn has already cancelled.
"""

import asyncio

import pytest

from helao.helpers.multisubscriber_queue import MultisubscriberQueue
from helao.helpers.ws_utils import WsPublisher


class _FakeSocket:
    """Enough WebSocket for the publisher: accept, send, and a sent-log."""

    def __init__(self):
        self.sent = []

    async def accept(self):
        return None

    async def send_bytes(self, payload: bytes):
        self.sent.append(payload)


@pytest.mark.asyncio
async def test_closing_the_source_queue_ends_the_broadcast():
    queue = MultisubscriberQueue()
    pub = WsPublisher(queue)
    sock = _FakeSocket()
    await pub.connect(sock)  # type: ignore[arg-type]

    task = asyncio.create_task(pub.broadcast(sock))  # type: ignore[arg-type]
    while not queue.subscribers:  # wait for the iterator to register
        await asyncio.sleep(0)
    await queue.put({"a": 1})
    await queue.close()

    # No cancel needed: this is what lets the POST /shutdown path finish
    # inside uvicorn's graceful window instead of being killed after it.
    await asyncio.wait_for(task, 1.0)
    assert len(sock.sent) == 1
    assert sock not in pub.active_connections


@pytest.mark.asyncio
async def test_a_cancelled_broadcast_does_not_raise_into_the_asgi_layer():
    queue = MultisubscriberQueue()
    pub = WsPublisher(queue)
    sock = _FakeSocket()
    await pub.connect(sock)  # type: ignore[arg-type]

    task = asyncio.create_task(pub.broadcast(sock))  # type: ignore[arg-type]
    while not queue.subscribers:
        await asyncio.sleep(0)
    task.cancel()

    # Returning rather than re-raising is the whole point: uvicorn logs
    # anything that escapes the endpoint coroutine as "Exception in ASGI
    # application".
    try:
        await asyncio.wait_for(task, 1.0)
    except asyncio.CancelledError:
        pytest.fail("CancelledError escaped broadcast and would reach uvicorn")
    assert sock not in pub.active_connections


@pytest.mark.asyncio
async def test_the_subscriber_queue_is_not_left_registered():
    # broadcast used to call subscribe() twice -- once into a generator that
    # was never iterated, so it registered nothing and the cleanup branch
    # guarding on it could never fire.
    queue = MultisubscriberQueue()
    pub = WsPublisher(queue)
    sock = _FakeSocket()
    await pub.connect(sock)  # type: ignore[arg-type]

    task = asyncio.create_task(pub.broadcast(sock))  # type: ignore[arg-type]
    while not queue.subscribers:
        await asyncio.sleep(0)
    assert len(queue.subscribers) == 1, "one stream must register exactly one queue"

    await queue.close()
    await asyncio.wait_for(task, 1.0)
    assert queue.subscribers == []


@pytest.mark.asyncio
async def test_disconnect_after_broadcast_already_cleaned_up_does_not_raise():
    # Every endpoint calls publisher.disconnect() from its except arm, and
    # broadcast's finally has already removed the socket by then.
    queue = MultisubscriberQueue()
    pub = WsPublisher(queue)
    sock = _FakeSocket()
    await pub.connect(sock)  # type: ignore[arg-type]

    task = asyncio.create_task(pub.broadcast(sock))  # type: ignore[arg-type]
    while not queue.subscribers:
        await asyncio.sleep(0)
    await queue.close()
    await asyncio.wait_for(task, 1.0)

    pub.disconnect(sock)  # type: ignore[arg-type]  # must not raise ValueError
    assert pub.active_connections == []
