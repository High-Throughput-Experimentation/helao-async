"""Unit tests for the ``ServerMonitor`` collaborator extracted from ``Orch``
(CARDS P5, Stage S3): network subscription + heartbeat/monitor cluster.

Cluster D is not exercised by ``test_orch_dispatch_golden_master.py`` (that
harness pins the dispatch state-machine, not the background monitor tasks),
so this module is the S3-specific behavior-preservation gate. It asserts the
extracted methods produce the same observable calls/effects as the original
inline ``Orch`` methods, against a lightweight fake orch (mirrors
``unit_test_estop_sync``'s fake-``Base`` pattern -- no full server, no
network):

  1. ``subscribe_all`` iterates only non-bokeh/non-demovis servers and sets
     ``init_success`` True only when every subscription succeeds.
  2. ``ping_action_servers`` skips ``DB``/``ANA``/``ignore_heartbeats``/bokeh
     servers and classifies busy/idle/unreachable identically to the
     pre-extraction inline method.
  3. ``active_action_monitor`` calls ``orch.stop()`` (and sets
     ``current_stop_message``) when an active endpoint is unreachable, and is
     a no-op when the loop isn't started / nothing is active.
  4. ``action_server_monitor`` refreshes ``orch.status_summary`` via
     ``ping_action_servers``.

Hermetic: the module-level ``async_private_dispatcher``/``endpoints_available``
names ``orch_monitor`` imports are monkeypatched for the duration of each
check; no network, no AWS/API configured.
"""

__all__ = ["orch_monitor_unit_test"]

import asyncio
import traceback

from helao.core.error import ErrorCodes
from helao.core.models.orchstatus import LoopStatus
from helao.hexagon.app import orch_monitor as om
from helao.core.tests._test_utils import TestReporter


class _StopLoop(Exception):
    """Sentinel raised by the patched ``asyncio.sleep`` to break a ``while True`` monitor loop."""


class _FakeGlobalStatusModel:
    def __init__(self, loop_state=LoopStatus.stopped, active_dict=None):
        self.loop_state = loop_state
        self.active_dict = active_dict or {}


class _FakeActionModel:
    def __init__(self, url):
        self.url = url


class _FakeServer:
    server_name = "ORCH"


class _FakeOrch:
    def __init__(self, servers):
        self.world_cfg = {"servers": servers}
        self.server = _FakeServer()
        self.server_cfg = {"host": "127.0.0.1", "port": 8000}
        self.init_success = False
        self.ignore_heartbeats = []
        self.heartbeat_interval = 0
        self.globalstatusmodel = _FakeGlobalStatusModel()
        self.current_stop_message = ""
        self.status_summary = {}
        self.stop_calls = 0

    async def stop(self):
        self.stop_calls += 1


async def _run_one_iteration(coro) -> None:
    """Await ``coro`` under a patched ``asyncio.sleep`` that aborts after one call.

    The extracted monitor loops are verbatim ``while True: ...; await
    asyncio.sleep(...)`` bodies -- this lets the test drive exactly one pass
    without changing the moved code.
    """
    orig_sleep = om.asyncio.sleep

    async def _fake_sleep(_):
        raise _StopLoop()

    om.asyncio.sleep = _fake_sleep
    try:
        await coro
    except _StopLoop:
        pass
    finally:
        om.asyncio.sleep = orig_sleep


async def _check_subscribe_all_all_succeed() -> bool:
    servers = {
        "SRV1": {"host": "127.0.0.1", "port": 8001},
        "SRV2": {"host": "127.0.0.1", "port": 8002},
        "VIS": {"host": "127.0.0.1", "port": 8003, "bokeh": True},
    }
    orch = _FakeOrch(servers)
    attempted = []

    async def _fake_dispatcher(**kwargs):
        attempted.append(kwargs["server_key"])
        return {"ok": True}, ErrorCodes.none

    orig = om.async_private_dispatcher
    om.async_private_dispatcher = _fake_dispatcher
    try:
        monitor = om.ServerMonitor(orch)
        await monitor.subscribe_all(retry_limit=1)
    finally:
        om.async_private_dispatcher = orig

    return attempted == ["SRV1", "SRV2"] and orch.init_success is True


async def _check_subscribe_all_partial_failure() -> bool:
    servers = {
        "SRV1": {"host": "127.0.0.1", "port": 8001},
        "SRV2": {"host": "127.0.0.1", "port": 8002},
    }
    orch = _FakeOrch(servers)

    async def _fake_dispatcher(**kwargs):
        if kwargs["server_key"] == "SRV2":
            return None, ErrorCodes.http
        return {"ok": True}, ErrorCodes.none

    orig = om.async_private_dispatcher
    om.async_private_dispatcher = _fake_dispatcher
    try:
        monitor = om.ServerMonitor(orch)
        await monitor.subscribe_all(retry_limit=1)
    finally:
        om.async_private_dispatcher = orig

    return orch.init_success is False


async def _check_ping_action_servers() -> bool:
    servers = {
        "SRV1": {"host": "127.0.0.1", "port": 8001},
        "SRV2": {"host": "127.0.0.1", "port": 8002},
        "SYNC": {"host": "127.0.0.1", "port": 8003},
        "SRV3": {
            "host": "127.0.0.1",
            "port": 8004,
            "params": {"ignore_heartbeats": True},
        },
        "VIS": {"host": "127.0.0.1", "port": 8005, "bokeh": True},
    }
    orch = _FakeOrch(servers)
    attempted = []

    async def _fake_dispatcher(**kwargs):
        attempted.append(kwargs["server_key"])
        if kwargs["server_key"] == "SRV1":
            return (
                {"_driver_status": "idle", "endpoints": {"ep1": {"active_dict": {}}}},
                ErrorCodes.none,
            )
        return None, ErrorCodes.http

    orig = om.async_private_dispatcher
    om.async_private_dispatcher = _fake_dispatcher
    try:
        monitor = om.ServerMonitor(orch)
        summary = await monitor.ping_action_servers()
    finally:
        om.async_private_dispatcher = orig

    return (
        attempted == ["SRV1", "SRV2"]
        and summary.get("SRV1") == ("idle", "idle")
        and summary.get("SRV2") == ("unreachable", "unknown")
        and "SYNC" not in summary
        and "SRV3" not in summary
        and "VIS" not in summary
    )


async def _check_active_action_monitor_stops_on_unreachable() -> bool:
    orch = _FakeOrch({})
    orch.globalstatusmodel = _FakeGlobalStatusModel(
        loop_state=LoopStatus.started,
        active_dict={"a1": _FakeActionModel("http://127.0.0.1:8001/SRV1/act")},
    )

    async def _fake_endpoints_available(urls):
        return [], [(u, "down") for u in urls]

    orig = om.endpoints_available
    om.endpoints_available = _fake_endpoints_available
    try:
        monitor = om.ServerMonitor(orch)
        await _run_one_iteration(monitor.active_action_monitor())
    finally:
        om.endpoints_available = orig

    return orch.stop_calls == 1 and "SRV1/act" in orch.current_stop_message


async def _check_active_action_monitor_idle_noop() -> bool:
    orch = _FakeOrch({})
    orch.globalstatusmodel = _FakeGlobalStatusModel(loop_state=LoopStatus.stopped)

    monitor = om.ServerMonitor(orch)
    await _run_one_iteration(monitor.active_action_monitor())

    return orch.stop_calls == 0


async def _check_action_server_monitor_refreshes_status() -> bool:
    orch = _FakeOrch({"SRV1": {"host": "127.0.0.1", "port": 8001}})

    async def _fake_dispatcher(**kwargs):
        return {"_driver_status": "idle", "endpoints": {}}, ErrorCodes.none

    orig = om.async_private_dispatcher
    om.async_private_dispatcher = _fake_dispatcher
    try:
        monitor = om.ServerMonitor(orch)
        await _run_one_iteration(monitor.action_server_monitor())
    finally:
        om.async_private_dispatcher = orig

    return orch.status_summary.get("SRV1") == ("idle", "idle")


async def _run_checks() -> dict:
    return {
        "subscribe_all_all_succeed": await _check_subscribe_all_all_succeed(),
        "subscribe_all_partial_failure": await _check_subscribe_all_partial_failure(),
        "ping_action_servers": await _check_ping_action_servers(),
        "active_action_monitor_stops": await _check_active_action_monitor_stops_on_unreachable(),
        "active_action_monitor_idle_noop": await _check_active_action_monitor_idle_noop(),
        "action_server_monitor_refreshes": await _check_action_server_monitor_refreshes_status(),
    }


def orch_monitor_unit_test() -> bool:
    reporter = TestReporter("orch_monitor")
    try:
        res = asyncio.run(_run_checks())
    except Exception as exc:  # noqa: BLE001
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        print(repr(exc), tb)
        return False

    reporter.section("subscribe_all")
    reporter.check(
        "attempts only non-bokeh servers and sets init_success True on full success",
        lambda: res["subscribe_all_all_succeed"],
    )
    reporter.check(
        "init_success stays False if any server fails to subscribe",
        lambda: res["subscribe_all_partial_failure"],
    )

    reporter.section("ping_action_servers")
    reporter.check(
        "skips DB/ANA/ignore_heartbeats/bokeh and classifies idle/unreachable",
        lambda: res["ping_action_servers"],
    )

    reporter.section("active_action_monitor")
    reporter.check(
        "stops orch and records message when active endpoint unreachable",
        lambda: res["active_action_monitor_stops"],
    )
    reporter.check(
        "no-op when loop not started / nothing active",
        lambda: res["active_action_monitor_idle_noop"],
    )

    reporter.section("action_server_monitor")
    reporter.check(
        "refreshes orch.status_summary via ping_action_servers",
        lambda: res["action_server_monitor_refreshes"],
    )

    return reporter.success()


if __name__ == "__main__":
    import sys

    sys.exit(0 if orch_monitor_unit_test() else 1)
