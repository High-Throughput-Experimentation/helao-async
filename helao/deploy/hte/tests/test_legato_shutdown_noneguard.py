"""Standalone regression test: KDS100 syringe-pump shutdown with no connection.

Reproduces and locks the fix for the shutdown crash observed at a station
where a syringe pump's COM port was absent, so ``connect()`` left
``self.sio is None``. On shutdown ``async_shutdown -> safe_state -> send``
then did ``self.sio.write(...)`` and raised
``AttributeError: 'NoneType' object has no attribute 'write'``.

The driver must tolerate an unconnected pump gracefully: ``send``/``_send_sync``
return ``[]`` (so the background poller and any action fail benignly rather
than crashing), ``safe_state`` no-ops, and ``async_shutdown`` completes so the
server can shut down cleanly.

Run:  conda run -n helao python helao/deploy/hte/tests/test_legato_shutdown_noneguard.py
"""

import asyncio
import sys

from helao.deploy.hte.drivers.pump.legato_driver import KDS100


def _make_unconnected() -> KDS100:
    """Build a KDS100 whose serial connection was never opened (sio is None).

    Bypasses ``__init__`` (which would need a real HelaoDriver/config setup)
    and sets only the attributes the exercised methods touch -- mirroring the
    post-``__init__``, pre/failed-``connect()`` state.
    """
    d = KDS100.__new__(KDS100)
    d.com = None
    d.sio = None
    d.com_lock = False
    d.polling = True
    d.config_dict = {"pumps": {}}
    return d


def main() -> int:
    failures = []

    def check(cond: bool, msg: str) -> None:
        if cond:
            print(f"PASS: {msg}")
        else:
            print(f"FAIL: {msg}")
            failures.append(msg)

    d = _make_unconnected()

    # send() on an unconnected pump returns [] instead of raising.
    try:
        resp = asyncio.run(d.send("cleansyringe", "poll on"))
        check(resp == [], "send() returns [] when sio is None (no AttributeError)")
    except Exception as exc:  # noqa: BLE001
        check(False, f"send() must not raise when sio is None; raised {exc!r}")

    # _send_sync() (the poller path) likewise returns [].
    try:
        sync_resp = d._send_sync("cleansyringe", "poll on")
        check(sync_resp == [], "_send_sync() returns [] when sio is None")
    except Exception as exc:  # noqa: BLE001
        check(False, f"_send_sync() must not raise when sio is None; raised {exc!r}")

    # safe_state() is a clean no-op (was where the shutdown crash originated).
    try:
        asyncio.run(d.safe_state())
        check(True, "safe_state() no-ops when sio is None (no crash)")
    except Exception as exc:  # noqa: BLE001
        check(False, f"safe_state() must not raise when sio is None; raised {exc!r}")

    # async_shutdown() completes end-to-end (safe_state skip + disconnect).
    try:
        asyncio.run(d.async_shutdown())
        check(True, "async_shutdown() completes when sio is None")
    except Exception as exc:  # noqa: BLE001
        check(
            False, f"async_shutdown() must not raise when sio is None; raised {exc!r}"
        )

    print("=" * 44)
    if failures:
        print(f"RESULT: FAIL ({len(failures)} check(s) failed)")
        return 1
    print("RESULT: PASS (all checks passed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
