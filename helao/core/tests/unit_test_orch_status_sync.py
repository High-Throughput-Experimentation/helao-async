"""Unit tests for the ``StatusIngester`` collaborator extracted from ``Orch``
(CARDS P5, Stage S4): the status-ingestion cluster.

``update_status``/``update_nonblocking`` are already exercised (byte-for-byte,
via the fake-dispatcher status-ping mechanism) by
``test_orch_dispatch_golden_master.py --check``, so this module covers the
cluster-C member that harness does *not* drive:

  1. ``clear_nonblocking`` sends ``stop_executor`` to every tracked
     non-blocking executor (in order) and returns the collected
     ``(response, error_code)`` tuples.

B7b deleted ``ws_globstat`` and ``globstat_broadcast_task`` with the
``globstat_q`` they served (a ``/ws_globstat`` sender that never had a route),
and with them this module's two checks of those methods.

Hermetic: a fake orch and a patched ``async_private_dispatcher`` (no network),
mirroring ``unit_test_orch_monitor``'s fake-``Base`` pattern.
"""

__all__ = ["orch_status_sync_unit_test"]

import asyncio
import traceback

from helao.core.error import ErrorCodes
from helao.hexagon.app import orch_status_sync as oss
from helao.core.tests._test_utils import TestReporter


class _FakeOrch:
    def __init__(self, nonblocking=None):
        self.nonblocking = nonblocking or []


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


async def _run_checks() -> dict:
    return {
        "clear_nonblocking": await _check_clear_nonblocking(),
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

    return reporter.success()


if __name__ == "__main__":
    import sys

    sys.exit(0 if orch_status_sync_unit_test() else 1)
