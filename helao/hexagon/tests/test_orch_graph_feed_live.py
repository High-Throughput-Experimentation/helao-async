"""/ws_orch on a real in-process group: events, experiment states, Start/Stop."""

import asyncio
from collections import Counter

import pytest
import websockets

from helao.helpers.dispatcher import async_private_dispatcher
from helao.helpers.ws_utils import wire_loads
from helao.hexagon.tests.live_group import (
    ORCH_HOST,
    ORCH_PORT,
    build_ws_sequence,
    live_group,
    orch_call,
    wait_parked,
)


def _backend():
    from helao.ui.shared.operator.orch_backend import RemoteBackend

    # No cheap supported construction: RemoteBackend(vis) wants an operator vis
    # object and runs import_autolibs. Only the transport fields _call reads.
    b = RemoteBackend.__new__(RemoteBackend)
    b.orch_key, b.host, b.port, b._dispatch = (
        "ORCH",
        ORCH_HOST,
        ORCH_PORT,
        async_private_dispatcher,
    )
    return b


async def _until(frames, pred, timeout=60.0):
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if frames and pred(frames[-1]):
            return frames[-1]
        await asyncio.sleep(0.1)
    raise TimeoutError(f"no frame matched; last={frames[-1] if frames else None}")


@pytest.mark.asyncio
async def test_ws_orch_reports_each_action_once_and_experiments_in_order(tmp_path):
    frames = []
    async with live_group(str(tmp_path)) as g:

        async def collect():
            async with websockets.connect(
                f"ws://{ORCH_HOST}:{ORCH_PORT}/ws_orch"
            ) as ws:
                while True:
                    frames.append(wire_loads(await ws.recv()))

        task = asyncio.create_task(collect())
        try:
            await _until(frames, lambda f: True, timeout=5.0)  # cached frame on connect
            seq = build_ws_sequence(2, wait_time=0.5, data_duration=0.5)
            await orch_call("append_sequence", body={"sequence": seq.as_dict()})
            await orch_call("start")
            await wait_parked(g.orch)
            await asyncio.sleep(0.5)
            history = {str(u) for u in g.orch.action_history}

            events = [e for f in frames for e in f["events"]]
            dispatched = Counter(
                e["action_uuid"] for e in events if e["kind"] == "dispatch"
            )
            finished = Counter(
                e["action_uuid"] for e in events if e["kind"] == "finish"
            )
            assert history, "the run dispatched nothing"
            assert set(dispatched) == history and set(finished) == history
            assert set(dispatched.values()) == {1} and set(finished.values()) == {1}

            seqs = [f["seq_no"] for f in frames]
            assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)

            queued_counts = [
                sum(r["state"] == "queued" for r in f["experiments"]) for f in frames
            ]
            assert max(queued_counts) >= 1 and queued_counts[-1] == 0
            per_uuid = {}
            for f in frames:
                for r in f["experiments"]:
                    if r["uuid"] is None:
                        continue
                    states = per_uuid.setdefault(r["uuid"], [])
                    if not states or states[-1] != r["state"]:
                        states.append(r["state"])
            assert len(per_uuid) == 2
            # queued -> active -> done for every experiment, the last one
            # included: the feed frames the finished sequence (last_sequence).
            for states in per_uuid.values():
                assert states == ["queued", "active", "done"], per_uuid
            assert any(f["seq"] and f["seq"]["finished"] for f in frames)

            backend = _backend()
            more = build_ws_sequence(3, wait_time=1.0, data_duration=1.0)
            await orch_call("append_sequence", body={"sequence": more.as_dict()})
            await backend.start(strict=True)
            await _until(frames, lambda f: f["loop_state"] == "started", timeout=15.0)
            await backend.stop(strict=True)
            await _until(frames, lambda f: f["loop_state"] != "started", timeout=60.0)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
