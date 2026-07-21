"""Standalone regression test: KDS100 syringe pump with no serial connection.

Covers two station-observed regressions:

1. SHUTDOWN CRASH -- where a pump's COM port is absent, ``connect()`` leaves
   ``self.sio is None``; on shutdown ``async_shutdown -> safe_state -> send``
   did ``self.sio.write(...)`` and raised
   ``AttributeError: 'NoneType' object has no attribute 'write'``.
2. POLL-LOG SPAM -- the first guard for (1) logged a WARNING inside ``send`` /
   ``_send_sync``; the KDS100Poller calls ``_send_sync('status')`` every cycle,
   so an unconnected pump spammed a WARNING per poll. The poller must now
   short-circuit quietly, and the residual send-guard log is DEBUG, not WARNING.

The driver must tolerate an unconnected pump gracefully: ``send``/``_send_sync``
return ``[]`` (no WARNING), the poller's ``get_data`` skips quietly (no WARNING,
empty result), ``safe_state`` no-ops (one WARNING at shutdown is fine), and
``async_shutdown`` completes so the server shuts down cleanly.

Run:  conda run -n helao python helao/deploy/hte/tests/test_legato_shutdown_noneguard.py
"""

import asyncio
import logging as _logging
import sys

from helao.deploy.hte.drivers.pump.legato_driver import (
    KDS100,
    KDS100Poller,
    LOGGER,
)


class _WarnCapture(_logging.Handler):
    """Collects records at WARNING or above emitted on the driver LOGGER."""

    def __init__(self) -> None:
        super().__init__(level=_logging.WARNING)
        self.records: list = []

    def emit(self, record) -> None:
        if record.levelno >= _logging.WARNING:
            self.records.append(record)


def _make_unconnected() -> KDS100:
    """Build a KDS100 whose serial connection was never opened (sio is None).

    Bypasses ``__init__`` (which would open a real serial port) and sets only
    the attributes the exercised methods touch -- mirroring the post-failed
    ``connect()`` state (COM port absent at this station).
    """
    d = KDS100.__new__(KDS100)
    d.com = None
    d.sio = None
    d.com_lock = False
    d.polling = True
    # One configured pump so a non-short-circuited poll WOULD reach _send_sync
    # (proving the get_data short-circuit, not an empty pumps dict, is what
    # keeps it quiet).
    d.config_dict = {"pumps": {"one": {"address": 0, "diameter": 10.0}}}
    return d


def _make_poller(driver: KDS100) -> KDS100Poller:
    """Build a KDS100Poller bound to ``driver`` without starting its loop."""
    p = KDS100Poller.__new__(KDS100Poller)
    p.driver = driver
    return p


def main() -> int:
    failures = []

    def check(cond: bool, msg: str) -> None:
        if cond:
            print(f"PASS: {msg}")
        else:
            print(f"FAIL: {msg}")
            failures.append(msg)

    d = _make_unconnected()

    # --- send / _send_sync return [] and emit NO WARNING (guard is DEBUG) ---
    cap = _WarnCapture()
    LOGGER.addHandler(cap)
    try:
        try:
            resp = asyncio.run(d.send("one", "poll on"))
            check(resp == [], "send() returns [] when sio is None (no AttributeError)")
        except Exception as exc:  # noqa: BLE001
            check(False, f"send() must not raise when sio is None; raised {exc!r}")

        try:
            sync_resp = d._send_sync("one", "status")
            check(sync_resp == [], "_send_sync() returns [] when sio is None")
        except Exception as exc:  # noqa: BLE001
            check(
                False, f"_send_sync() must not raise when sio is None; raised {exc!r}"
            )

        check(
            not cap.records,
            "send()/_send_sync() emit NO WARNING when sio is None "
            f"(captured {len(cap.records)})",
        )
    finally:
        LOGGER.removeHandler(cap)

    # --- poller get_data skips quietly: empty result + NO WARNING over cycles ---
    poller = _make_poller(d)
    cap2 = _WarnCapture()
    LOGGER.addHandler(cap2)
    try:
        empties = True
        for _ in range(5):
            r = poller.get_data()
            if getattr(r, "data", None):
                empties = False
        check(
            empties, "poller.get_data() returns empty data every cycle when sio is None"
        )
        check(
            not cap2.records,
            "poller.get_data() emits NO WARNING across cycles when sio is None "
            f"(captured {len(cap2.records)}) -- the reported spam is gone",
        )
    except Exception as exc:  # noqa: BLE001
        check(
            False, f"poller.get_data() must not raise when sio is None; raised {exc!r}"
        )
    finally:
        LOGGER.removeHandler(cap2)

    # --- safe_state no-ops (one WARNING here is expected, not asserted) ---
    try:
        asyncio.run(d.safe_state())
        check(True, "safe_state() no-ops when sio is None (no crash)")
    except Exception as exc:  # noqa: BLE001
        check(False, f"safe_state() must not raise when sio is None; raised {exc!r}")

    # --- async_shutdown completes end-to-end (safe_state skip + disconnect) ---
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
