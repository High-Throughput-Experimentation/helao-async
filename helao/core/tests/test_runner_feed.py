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
async def test_409_backs_off_then_retries_and_warns_once(monkeypatch):
    warnings = []
    monkeypatch.setattr(rf.LOGGER, "warning", lambda msg, *a, **k: warnings.append(msg))
    rec = Recorder(status=409)
    f, _ = feed_with(rec)
    now = [100.0]
    f.clock = lambda: now[0]
    frame = f.step(0.0)
    await f.post(frame)
    assert len(rec.calls) == 1 and set(f.retry_at) == {"http://ui:1"}
    now[0] = 100.0 + rf.RETRY_409_S - 0.1
    await f.post(frame)
    assert len(rec.calls) == 1  # still backing off
    now[0] = 100.0 + rf.RETRY_409_S
    await f.post(frame)
    assert len(rec.calls) == 2  # retried after the back-off
    assert len(warnings) == 1 and "'RUNNER'" in warnings[0]


@pytest.mark.asyncio
async def test_2xx_after_409_clears_back_off_and_rewarns(monkeypatch):
    warnings = []
    monkeypatch.setattr(rf.LOGGER, "warning", lambda msg, *a, **k: warnings.append(msg))
    rec = Recorder(status=409)
    f, _ = feed_with(rec)
    now = [0.0]
    f.clock = lambda: now[0]
    frame = f.step(0.0)
    await f.post(frame)
    rec.status = 200
    now[0] = rf.RETRY_409_S
    await f.post(frame)
    assert f.retry_at == {}
    rec.status = 409
    await f.post(frame)
    assert len(warnings) == 2


@pytest.mark.asyncio
async def test_close_sends_delete_with_instance():
    rec = Recorder()
    f, _ = feed_with(rec)
    await f.close()
    assert rec.calls == [("DELETE", "http://ui:1/runners/RUNNER?instance=i-1")]


def _orch(tmp_path, group_urls):
    from helao.core.runners.micro_orch import MicroOrch
    from helao.core.tests.unit_test_micro_orch import _free_port

    port = _free_port()
    return MicroOrch(
        server_key="micro",
        host="127.0.0.1",
        port=port,
        world_cfg={"root": str(tmp_path), "servers": {}},
        group_urls=group_urls,
    )


@pytest.mark.asyncio
async def test_no_targets_means_no_feed_task(tmp_path):
    orch = _orch(tmp_path, [])
    await orch.start()
    try:
        assert orch._feed_task is None and orch._feed is None
    finally:
        await orch.stop()


@pytest.mark.asyncio
async def test_stop_cancels_feed_and_deregisters(tmp_path):
    rec = Recorder()
    orch = _orch(tmp_path, ["http://ui:1"])
    await orch.start()
    try:
        assert orch._feed_task is not None and not orch._feed_task.done()
        await orch._feed.client.aclose()
        orch._feed.client = httpx.AsyncClient(transport=httpx.MockTransport(rec))
    finally:
        await orch.stop()
    assert orch._feed_task is None and orch._feed is None
    assert (
        "DELETE",
        f"http://ui:1/runners/micro?instance={orch.instance}",
    ) in rec.calls
