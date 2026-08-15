"""Unit tests for the ``StatusIngester`` collaborator extracted from ``Orch``
(CARDS P5, Stage S4): status ingestion + WS broadcast cluster.

``update_status``/``update_nonblocking`` are already exercised (byte-for-byte,
via the fake-dispatcher status-ping mechanism) by
``test_orch_dispatch_golden_master.py --check``, so this module focuses on
the cluster-C surface that harness does *not* drive -- the background
broadcast/websocket paths:

  1. ``clear_nonblocking`` sends ``stop_executor`` to every tracked
     non-blocking executor (in order) and returns the collected
     ``(response, error_code)`` tuples.
  2. ``ws_globstat`` accepts the websocket, subscribes to ``globstat_q``,
     and forwards every published ``GlobalStatusModel`` as
     ``json.dumps(msg.as_dict())`` via ``websocket.send_text`` until the
     client disconnects (``send_text`` raising). Faithfully-preserved
     pre-existing quirk (not a harness bug, not fixed here -- spec sec 3.1
     rule 5 "no behavior fixes ride along"): the disconnect handler checks
     ``gs_sub in self.globstat_q.subscribers``, but ``gs_sub`` is the async
     *generator* returned by ``globstat_q.subscribe()``, never one of the
     registered ``asyncio.Queue`` objects in ``subscribers`` -- so that
     condition is always ``False`` and the subscriber queue is never
     actually removed on disconnect via this path. The test asserts this
     real (bug-for-bug identical) behavior.
  3. ``globstat_broadcast_task`` subscribes to ``globstat_q`` and drains it
     indefinitely (one message in, one iteration observed, sleeps between
     reads) without consuming/blocking messages meant for other subscribers.

Hermetic: uses the real ``MultisubscriberQueue`` (no network) with a fake
websocket/orch, mirroring ``unit_test_orch_monitor``'s fake-``Base`` pattern.
"""

__all__ = ["orch_status_sync_unit_test"]

import asyncio
import json
import traceback

from helao.core.error import ErrorCodes
from helao.hexagon.app import orch_status_sync as oss
from helao.core.tests._test_utils import TestReporter
from helao.helpers.multisubscriber_queue import MultisubscriberQueue


class _FakeGlobstatMsg:
    """Stand-in for a ``GlobalStatusModel`` with a deterministic ``as_dict``."""

    def __init__(self, payload: dict):
        self._payload = payload

    def as_dict(self) -> dict:
        return self._payload


class _FakeOrch:
    def __init__(self, nonblocking=None):
        self.nonblocking = nonblocking or []
        self.globstat_q = MultisubscriberQueue()


class _FakeWebSocket:
    """Records accept()/send_text() calls; can be told to fail on the Nth send."""

    def __init__(self, fail_after: int = None):
        self.accepted = False
        self.sent = []
        self.client = ("127.0.0.1", 12345)
        self._fail_after = fail_after

    async def accept(self):
        self.accepted = True

    async def send_text(self, text: str):
        self.sent.append(text)
        if self._fail_after is not None and len(self.sent) >= self._fail_after:
            raise ConnectionResetError("client disconnected")


async def _check_clear_nonblocking() -> bool:
    orch = _FakeOrch(
        nonblocking=[
            ("SRV1", "exec-1", "127.0.0.1", 8001),
            ("SRV2", "exec-2", "127.0.0.1", 8002),
        ]
    )
    calls = []

    async def _fake_dispatcher(**kwargs):
        calls.append(kwargs)
        if kwargs["server_key"] == "SRV2":
            return None, ErrorCodes.http
        return {"stopped": True}, ErrorCodes.none

    orig = oss.async_private_dispatcher
    oss.async_private_dispatcher = _fake_dispatcher
    try:
        ingester = oss.StatusIngester(orch)
        resp_tups = await ingester.clear_nonblocking()
    finally:
        oss.async_private_dispatcher = orig

    return (
        [c["server_key"] for c in calls] == ["SRV1", "SRV2"]
        and calls[0]["private_action"] == "stop_executor"
        and calls[0]["params_dict"] == {"executor_id": "exec-1"}
        and calls[1]["params_dict"] == {"executor_id": "exec-2"}
        and resp_tups == [({"stopped": True}, ErrorCodes.none), (None, ErrorCodes.http)]
    )


async def _check_ws_globstat_forwards_and_preserves_disconnect_quirk() -> bool:
    orch = _FakeOrch()
    ingester = oss.StatusIngester(orch)
    ws = _FakeWebSocket(fail_after=2)

    task = asyncio.ensure_future(ingester.ws_globstat(ws))
    # let ws_globstat subscribe before we publish
    for _ in range(50):
        if orch.globstat_q.subscribers:
            break
        await asyncio.sleep(0)
    subscribed_ok = len(orch.globstat_q.subscribers) == 1

    await orch.globstat_q.put(_FakeGlobstatMsg({"orch_state": "idle"}))
    # second put's send_text raises inside ws_globstat; the method catches
    # it, logs a warning, and returns -- driving the task to completion.
    await orch.globstat_q.put(_FakeGlobstatMsg({"orch_state": "busy"}))

    await asyncio.wait_for(task, timeout=2)

    return (
        subscribed_ok
        and ws.accepted is True
        and ws.sent
        == [json.dumps({"orch_state": "idle"}), json.dumps({"orch_state": "busy"})]
        # preserved quirk: the disconnect handler's `gs_sub in subscribers`
        # check compares the async generator to registered Queue objects
        # and is always False, so the subscriber queue is never removed
        # via this path -- it is still registered after "disconnect".
        and len(orch.globstat_q.subscribers) == 1
    )


async def _check_globstat_broadcast_task_drains_without_consuming_others() -> bool:
    orch = _FakeOrch()
    ingester = oss.StatusIngester(orch)

    # A second, independent subscriber (mirrors ws_globstat's own subscription)
    # must still see the message after the broadcast task's own drain pass.
    other_sub = orch.globstat_q.queue()

    task = asyncio.ensure_future(ingester.globstat_broadcast_task())
    try:
        # let the broadcast task subscribe (registering its own queue
        # alongside `other_sub`) before publishing.
        for _ in range(50):
            if len(orch.globstat_q.subscribers) == 2:
                break
            await asyncio.sleep(0)
        registered_ok = len(orch.globstat_q.subscribers) == 2

        await orch.globstat_q.put(_FakeGlobstatMsg({"orch_state": "idle"}))

        # give the broadcast task's own consumer a chance to read its copy
        # and loop back around to (correctly) block on the next one.
        await asyncio.sleep(0.05)
        other_saw_message = not other_sub.empty()
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # cancellation unwinds through `subscribe`'s `with queue_context():`,
    # which must deregister the broadcast task's own queue -- no dangling
    # subscriber should remain besides `other_sub`.
    no_dangling_subscriber = orch.globstat_q.subscribers == [other_sub]

    return registered_ok and other_saw_message and no_dangling_subscriber


async def _run_checks() -> dict:
    return {
        "clear_nonblocking": await _check_clear_nonblocking(),
        "ws_globstat": await _check_ws_globstat_forwards_and_preserves_disconnect_quirk(),
        "globstat_broadcast_task": await _check_globstat_broadcast_task_drains_without_consuming_others(),
    }


def orch_status_sync_unit_test() -> bool:
    reporter = TestReporter("orch_status_sync")
    try:
        res = asyncio.run(_run_checks())
    except Exception as exc:  # noqa: BLE001
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        print(repr(exc), tb)
        return False

    reporter.section("clear_nonblocking")
    reporter.check(
        "dispatches stop_executor per tracked executor, in order, and collects responses",
        lambda: res["clear_nonblocking"],
    )

    reporter.section("ws_globstat")
    reporter.check(
        "forwards globstat_q messages as json.dumps(msg.as_dict()); preserves the"
        " pre-existing disconnect-handler quirk (subscriber not removed via that path)",
        lambda: res["ws_globstat"],
    )

    reporter.section("globstat_broadcast_task")
    reporter.check(
        "drains its own subscription without consuming messages meant for other subscribers",
        lambda: res["globstat_broadcast_task"],
    )

    return reporter.success()


if __name__ == "__main__":
    import sys

    sys.exit(0 if orch_status_sync_unit_test() else 1)
