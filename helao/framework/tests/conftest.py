"""Shared pytest fixtures: a fresh fake per port for every test."""
import asyncio
from contextlib import asynccontextmanager

import pytest

from helao.framework.adapters.fakes.clock import FakeClock
from helao.framework.adapters.fakes.eventsink import FakeEventSink
from helao.framework.adapters.fakes.storage import FakeStorage
from helao.framework.adapters.fakes.transport import FakeTransport


@asynccontextmanager
async def asgi_lifespan(app):
    """Drive a Starlette/FastAPI app's ASGI ``lifespan`` protocol.

    ``httpx.ASGITransport`` does NOT run ``startup``/``shutdown`` events, and
    ``asgi_lifespan`` is not a project dependency. This minimal manager speaks
    the lifespan ASGI protocol directly: it sends ``lifespan.startup`` on enter
    (awaiting ``startup.complete``) and ``lifespan.shutdown`` on exit, running
    the app's lifespan coroutine as a background task for the body's duration.

    Usage::

        async with asgi_lifespan(app):
            async with httpx.AsyncClient(transport=..., ...) as client:
                ...
    """
    receive_q: asyncio.Queue = asyncio.Queue()
    send_q: asyncio.Queue = asyncio.Queue()

    async def receive():
        return await receive_q.get()

    async def send(message):
        await send_q.put(message)

    scope = {"type": "lifespan", "asgi": {"version": "3.0"}}
    task = asyncio.ensure_future(app(scope, receive, send))

    await receive_q.put({"type": "lifespan.startup"})
    msg = await send_q.get()
    if msg["type"] == "lifespan.startup.failed":
        await task
        raise RuntimeError(f"lifespan startup failed: {msg.get('message')}")
    assert msg["type"] == "lifespan.startup.complete"
    try:
        yield
    finally:
        await receive_q.put({"type": "lifespan.shutdown"})
        msg = await send_q.get()
        assert msg["type"] in (
            "lifespan.shutdown.complete",
            "lifespan.shutdown.failed",
        )
        await task


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def fake_eventsink() -> FakeEventSink:
    return FakeEventSink()


@pytest.fixture
def fake_storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
def fake_transport() -> FakeTransport:
    return FakeTransport()
