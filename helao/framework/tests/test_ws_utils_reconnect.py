"""WsSubscriber reconnect robustness (helao.helpers.ws_utils).

The visualizer's WsSubscriber connects to an action server's ws stream. The old
loop retried a fixed 5 times then died forever, and slept with a blocking
time.sleep inside the async loop (freezing the Bokeh document). These tests pin
the fixed behavior: reconnect indefinitely, non-blocking sleep, reset backoff on
a successful connect.
"""
import asyncio
import collections

import pytest

from helao.helpers import ws_utils


def _bare_subscriber():
    """A WsSubscriber without running __init__ (which would spawn the task)."""
    sub = ws_utils.WsSubscriber.__new__(ws_utils.WsSubscriber)
    sub.data_url = "ws://test/ws_data"
    sub.recv_queue = collections.deque(maxlen=10)
    return sub


@pytest.mark.asyncio
async def test_reconnects_past_five_and_never_blocks(monkeypatch):
    calls = {"connect": 0, "time_sleep": 0, "asyncio_sleep": 0}

    class _FailingCtx:
        async def __aenter__(self):
            raise ConnectionError("refused")

        async def __aexit__(self, *a):
            return False

    def fake_connect(url):
        calls["connect"] += 1
        return _FailingCtx()

    real_sleep = asyncio.sleep

    async def fast_asleep(_seconds):
        calls["asyncio_sleep"] += 1
        await real_sleep(0)  # yield without waiting

    monkeypatch.setattr(ws_utils.websockets, "connect", fake_connect)
    monkeypatch.setattr(ws_utils.asyncio, "sleep", fast_asleep)
    monkeypatch.setattr(ws_utils.time, "sleep", lambda _s: calls.__setitem__("time_sleep", calls["time_sleep"] + 1))

    sub = _bare_subscriber()
    task = asyncio.create_task(sub.subscriber_loop())
    for _ in range(200):
        await real_sleep(0)
        if calls["connect"] > 8:
            break
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert calls["connect"] > 5, "must reconnect past the old 5-attempt limit"
    assert calls["time_sleep"] == 0, "must not use blocking time.sleep in the async loop"
    assert calls["asyncio_sleep"] > 0, "must back off via awaitable asyncio.sleep"


@pytest.mark.asyncio
async def test_decode_hook_parses_json_frames(monkeypatch):
    import json

    real_sleep = asyncio.sleep
    frames = ['{"a": 1, "b": "x"}']

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def recv(self):
            if frames:
                return frames.pop(0)
            raise asyncio.CancelledError  # stop the loop after the one frame

    monkeypatch.setattr(ws_utils.websockets, "connect", lambda url: _Session())

    sub = ws_utils.WsSubscriber.__new__(ws_utils.WsSubscriber)
    sub.data_url = "ws://test/ws_data"
    sub.recv_queue = collections.deque(maxlen=10)
    sub._decode = json.loads  # framework send_json relay

    task = asyncio.create_task(sub.subscriber_loop())
    with pytest.raises(asyncio.CancelledError):
        await task

    assert list(sub.recv_queue) == [{"a": 1, "b": "x"}]


@pytest.mark.asyncio
async def test_backoff_resets_after_successful_connect(monkeypatch):
    backoffs = []
    real_sleep = asyncio.sleep

    async def record_asleep(seconds):
        backoffs.append(seconds)
        await real_sleep(0)

    # connect: fail, fail (backoff 2 then 4), then a session that yields one msg
    # and drops (should reset backoff back to the initial 2 on the next failure).
    state = {"n": 0}

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def recv(self):
            raise ConnectionError("dropped")

    class _FailCtx:
        async def __aenter__(self):
            raise ConnectionError("refused")

        async def __aexit__(self, *a):
            return False

    def fake_connect(url):
        state["n"] += 1
        # attempts 1,2 fail; attempt 3 "succeeds" then drops; 4,5 fail
        return _Session() if state["n"] == 3 else _FailCtx()

    monkeypatch.setattr(ws_utils.websockets, "connect", fake_connect)
    monkeypatch.setattr(ws_utils.asyncio, "sleep", record_asleep)
    monkeypatch.setattr(ws_utils.time, "sleep", lambda _s: None)

    sub = _bare_subscriber()
    task = asyncio.create_task(sub.subscriber_loop())
    for _ in range(200):
        await real_sleep(0)
        if state["n"] >= 5:
            break
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # first two failures escalate 2 -> 4; the drop after the successful connect
    # (attempt 3) resets, so the failure after it backs off from 2 again.
    assert backoffs[0] == ws_utils.INITIAL_RECONNECT_BACKOFF_S
    assert backoffs[1] == ws_utils.INITIAL_RECONNECT_BACKOFF_S * 2
    assert ws_utils.INITIAL_RECONNECT_BACKOFF_S in backoffs[2:], "backoff did not reset after a successful connect"
