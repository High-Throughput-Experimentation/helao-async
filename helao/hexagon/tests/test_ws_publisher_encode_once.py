"""WsPublisher encodes each message once, however many clients are connected."""

import asyncio

import pytest

from harness.ws_frames import FakeWebSocket
from helao.helpers import ws_utils
from helao.helpers.multisubscriber_queue import MultisubscriberQueue
from helao.helpers.ws_utils import WsPublisher, wire_loads


async def _run(pub, queue, n_clients, msgs):
    sockets = [FakeWebSocket() for _ in range(n_clients)]
    tasks = [asyncio.ensure_future(pub.broadcast(ws)) for ws in sockets]
    for _ in range(200):
        if len(queue.subscribers) == n_clients:
            break
        await asyncio.sleep(0.01)
    assert len(queue.subscribers) == n_clients
    for m in msgs:
        await queue.put(m)
    for _ in range(200):
        if all(len(ws.frames) == len(msgs) for ws in sockets):
            break
        await asyncio.sleep(0.01)
    await queue.close()
    await asyncio.gather(*tasks)
    return sockets


@pytest.mark.asyncio
async def test_one_encode_for_three_clients(monkeypatch):
    calls = []
    real = ws_utils.wire_dumps
    monkeypatch.setattr(ws_utils, "wire_dumps", lambda o: calls.append(o) or real(o))
    q = MultisubscriberQueue()
    msg = {"a": (1.0, 2.0)}
    socks = await _run(WsPublisher(q), q, 3, [msg])
    assert len(calls) == 1
    frames = [ws.frames[0] for ws in socks]
    assert frames[0] == frames[1] == frames[2]
    assert wire_loads(frames[0]) == {"a": [1.0, 2.0]}


@pytest.mark.asyncio
async def test_distinct_messages_each_encoded_once(monkeypatch):
    calls = []
    real = ws_utils.wire_dumps
    monkeypatch.setattr(ws_utils, "wire_dumps", lambda o: calls.append(o) or real(o))
    q = MultisubscriberQueue()
    msgs = [{"n": i} for i in range(5)]
    socks = await _run(WsPublisher(q), q, 3, msgs)
    assert len(calls) == 5
    for ws in socks:
        assert [wire_loads(f)["n"] for f in ws.frames] == list(range(5))


@pytest.mark.asyncio
async def test_lagging_client_re_encodes_correctly(monkeypatch):
    monkeypatch.setattr(ws_utils, "_FRAME_CACHE_MAX", 2)
    pub = WsPublisher(MultisubscriberQueue())
    first = {"n": 0}
    f0 = pub._frame(first)
    assert f0 is not None
    for i in range(1, 4):  # evict `first`
        pub._frame({"n": i})
    assert id(first) not in pub._frames
    assert pub._frame(first) == f0  # lagging client misses, bytes still right
    assert wire_loads(f0) == {"n": 0}


@pytest.mark.asyncio
async def test_unencodable_message_is_skipped_stream_survives():
    q = MultisubscriberQueue()
    msgs = [{"n": 0}, {"bad": object()}, {"n": 2}]
    socks = await _run_n(WsPublisher(q), q, 2, msgs, expect=2)
    for ws in socks:
        assert [wire_loads(f) for f in ws.frames] == [{"n": 0}, {"n": 2}]


async def _run_n(pub, queue, n_clients, msgs, expect):
    sockets = [FakeWebSocket() for _ in range(n_clients)]
    tasks = [asyncio.ensure_future(pub.broadcast(ws)) for ws in sockets]
    for _ in range(200):
        if len(queue.subscribers) == n_clients:
            break
        await asyncio.sleep(0.01)
    for m in msgs:
        await queue.put(m)
    for _ in range(200):
        if all(len(ws.frames) == expect for ws in sockets):
            break
        await asyncio.sleep(0.01)
    await queue.close()
    await asyncio.gather(*tasks)
    return sockets


def test_cache_hit_requires_identity(monkeypatch):
    calls = []
    real = ws_utils.wire_dumps
    monkeypatch.setattr(ws_utils, "wire_dumps", lambda o: calls.append(o) or real(o))
    pub = WsPublisher(MultisubscriberQueue())
    a = {"n": 1}
    f = pub._frame(a)
    assert pub._frame(a) is f and len(calls) == 1  # same object: cache hit
    b = {"n": 1}  # equal content, different object: must be re-encoded
    assert pub._frame(b) == f and len(calls) == 2
