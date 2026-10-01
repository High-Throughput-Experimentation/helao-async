"""Unit tests for ``ActionHost``'s live-buffer surface (``live_buffer_task``/
``_stamp_lbuf_dict``/``put_lbuf``/``put_lbuf_nowait``/``get_lbuf``/
``get_realtime``/``get_realtime_nowait``).

The action golden master drives ``get_realtime``/``get_realtime_nowait`` but
never ``put_lbuf``/``get_lbuf``/``live_buffer_task`` -- those are normally
executor-driven (a driver's poller pushes readings into the live buffer).
This module is the gate for that surface. Ported from the legacy ``Base``
fixture by B7b.

A bare ``ActionHost`` built with ``__new__`` (no FastAPI app, no disk I/O, no
NTP), populated only with the attributes these methods touch. The clock is
the production ``LegacyClockAdapter``: ``get_realtime_nowait`` reads its time
and offset through the clock port, not a cached ``ntp_offset``.

Hermetic: no network, no disk I/O; a real ``MultisubscriberQueue`` so the
``live_buffer_task`` drain is checked against genuine fan-out behavior, not a
stand-in.
"""

__all__ = ["base_live_buffer_unit_test"]

import asyncio
import traceback

from helao.core.models.machine import MachineModel
from helao.core.tests._test_utils import TestReporter
from helao.helpers.multisubscriber_queue import MultisubscriberQueue
from helao.hexagon.adapters.legacy.clock import LegacyClockAdapter
from helao.hexagon.app.action_host import ActionHost
from helao.hexagon.app.wiring import PortWiring

SERVER_NAME = "LBUFSRV"
MACHINE = "test-machine"


def _make_base(offset_s: float = 0.0) -> ActionHost:
    """Build a bare ``ActionHost`` with every attribute the live-buffer methods touch."""
    base = ActionHost.__new__(ActionHost)
    base.server = MachineModel(
        server_name=SERVER_NAME, machine_name=MACHINE, hostname="127.0.0.1", port=8000
    )
    base.hexagon_wiring = PortWiring(clock=LegacyClockAdapter(offset_s))
    base.live_q = MultisubscriberQueue()
    base.live_buffer = {}
    return base


async def _ticks(n: int = 5):
    for _ in range(n):
        await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# stamping + put/get
# ---------------------------------------------------------------------------


def _check_stamp_lbuf_dict() -> bool:
    base = _make_base()
    stamped = base._stamp_lbuf_dict({"a": 1, "b": "two"})
    return (
        set(stamped.keys()) == {"a", "b"}
        and stamped["a"][0] == 1
        and stamped["b"][0] == "two"
        and isinstance(stamped["a"][1], float)
        and isinstance(stamped["b"][1], float)
    )


async def _check_put_and_drain() -> bool:
    base = _make_base()
    task = asyncio.create_task(base.live_buffer_task())
    # let live_buffer_task's subscribe() register a subscriber before publishing
    await _ticks()

    await base.put_lbuf({"key1": "val1"})
    await _ticks()
    got_awaited = "key1" in base.live_buffer and base.live_buffer["key1"][0] == "val1"

    base.put_lbuf_nowait({"key2": "val2"})
    await _ticks()
    got_nowait = "key2" in base.live_buffer and base.live_buffer["key2"][0] == "val2"

    # get_lbuf returns the exact (value, timestamp) tuple stored in the dict
    lbuf_matches = base.get_lbuf("key1") == base.live_buffer["key1"]

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    return got_awaited and got_nowait and lbuf_matches


def _check_get_lbuf_keyerror() -> bool:
    base = _make_base()
    try:
        base.get_lbuf("missing")
    except KeyError:
        return True
    return False


# ---------------------------------------------------------------------------
# get_realtime / get_realtime_nowait
# ---------------------------------------------------------------------------


def _check_get_realtime_nowait() -> bool:
    base = _make_base()

    # epoch_ns given + offset=0 -> passthrough
    passthrough_ok = base.get_realtime_nowait(epoch_ns=1000, offset=0.0) == 1000

    # explicit offset (seconds) is added as nanoseconds
    offset_ok = base.get_realtime_nowait(epoch_ns=1000, offset=2.0) == 1000 + int(
        2.0 * 1e9
    )

    # offset=None defaults to the clock port's offset
    offset_base = _make_base(3.0)
    default_offset_ok = offset_base.get_realtime_nowait(epoch_ns=1000) == 1000 + int(
        3.0 * 1e9
    )

    # no epoch_ns -> the clock port's wall clock, a plausible epoch-ns value
    now_ns = base.get_realtime_nowait()
    now_ok = isinstance(now_ns, int) and now_ns > 10**18

    return passthrough_ok and offset_ok and default_offset_ok and now_ok


async def _check_get_realtime_async() -> bool:
    base = _make_base()
    result = await base.get_realtime(epoch_ns=500, offset=0.0)
    return result == 500


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------


async def _run_checks() -> dict:
    return {
        "stamp_lbuf_dict": _check_stamp_lbuf_dict(),
        "put_and_drain": await _check_put_and_drain(),
        "get_lbuf_keyerror": _check_get_lbuf_keyerror(),
        "get_realtime_nowait": _check_get_realtime_nowait(),
        "get_realtime_async": await _check_get_realtime_async(),
    }


def base_live_buffer_unit_test() -> bool:
    reporter = TestReporter("base_live_buffer")
    try:
        res = asyncio.run(_run_checks())
    except Exception as exc:  # noqa: BLE001
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        print(repr(exc), tb)
        return False

    reporter.section("_stamp_lbuf_dict")
    reporter.check(
        "wraps each value in a (value, now()) float-timestamped tuple",
        lambda: res["stamp_lbuf_dict"],
    )

    reporter.section("put_lbuf / put_lbuf_nowait / live_buffer_task / get_lbuf")
    reporter.check(
        "put_lbuf (awaited) and put_lbuf_nowait both stamp+enqueue onto live_q; "
        "live_buffer_task drains live_q into live_buffer; get_lbuf reads it back",
        lambda: res["put_and_drain"],
    )
    reporter.check(
        "get_lbuf raises KeyError for a key never published",
        lambda: res["get_lbuf_keyerror"],
    )

    reporter.section("get_realtime_nowait / get_realtime")
    reporter.check(
        "epoch_ns passthrough, explicit offset, default-to-clock-offset, and "
        "clock-port wall clock all compute the expected nanosecond value",
        lambda: res["get_realtime_nowait"],
    )
    reporter.check(
        "get_realtime is an async wrapper around get_realtime_nowait",
        lambda: res["get_realtime_async"],
    )

    return reporter.success()


if __name__ == "__main__":
    import sys

    sys.exit(0 if base_live_buffer_unit_test() else 1)
