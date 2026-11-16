"""RunnerGraphFeed: change/heartbeat framing and fail-safe POSTs."""

import httpx
import pytest

from helao.core.runners import runner_feed as rf
from helao.core.tests.test_runner_snapshot import micro


class Recorder:
    def __init__(self, status=200, raise_exc=None):
        self.calls = []
        self.status = status
        self.raise_exc = raise_exc

    def __call__(self, request: httpx.Request):
        self.calls.append((request.method, str(request.url)))
        if self.raise_exc:
            raise self.raise_exc
        return httpx.Response(self.status)


def feed_with(handler, urls=("http://ui:1",)):
    m, _ = micro()
    m.drain_events = lambda: []
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return rf.RunnerGraphFeed(m, list(urls), client=client), m


def test_step_frames_on_change_and_heartbeat_only():
    f, m = feed_with(Recorder())
    assert f.step(0.0) is not None  # first frame
    assert f.step(0.5) is None  # unchanged, no heartbeat yet
    assert f.step(2.1) is not None  # heartbeat
    m.active_actions = lambda: {}
    m.active_experiment = None
    assert f.step(2.2) is not None  # state changed


def test_events_force_a_frame():
    f, m = feed_with(Recorder())
    f.step(0.0)
    m.drain_events = lambda: [{"kind": "dispatch"}]
    snap = f.step(0.1)
    assert snap is not None and snap["events"] == [{"kind": "dispatch"}]


@pytest.mark.asyncio
async def test_post_failure_never_raises_and_logs_once(monkeypatch):
    warnings = []
    monkeypatch.setattr(rf.LOGGER, "warning", lambda msg, *a, **k: warnings.append(msg))
    rec = Recorder(raise_exc=httpx.ConnectError("down"))
    f, _ = feed_with(rec)
    frame = f.step(0.0)
    await f.post(frame)
    await f.post(frame)
    assert len(rec.calls) == 2
    assert len(warnings) == 1 and "frame POST" in warnings[0]


@pytest.mark.asyncio
async def test_409_stops_posting_to_that_target():
    rec = Recorder(status=409)
    f, _ = feed_with(rec)
    frame = f.step(0.0)
    await f.post(frame)
    await f.post(frame)
    assert len(rec.calls) == 1 and f.blocked == {"http://ui:1"}


@pytest.mark.asyncio
async def test_close_sends_delete_with_instance():
    rec = Recorder()
    f, _ = feed_with(rec)
    await f.close()
    assert rec.calls == [("DELETE", "http://ui:1/runners/RUNNER?instance=i-1")]
