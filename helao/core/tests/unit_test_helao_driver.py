"""Unit tests for :mod:`helao.core.drivers.helao_driver`.

Covers the driver contract surface that does not need a real device or
event loop:

* :class:`DriverStatus` and :class:`DriverResponseType` — enum
  membership and string-value round-tripping.
* :class:`DriverResponse` — defaults, ``timestamp`` auto-stamping,
  ``timestamp_str`` format, and explicit-field round-trip.
* :class:`HelaoDriver` — instantiation through a fully concrete
  subclass, the recorded creation ``timestamp``, the ``config`` echo,
  and that the ABC refuses to instantiate when any of the five
  required methods is missing.

The :class:`DriverPoller` exercises asyncio tasks at construction time
that depend on a running loop; rather than spin up a fake loop we
instead drive its ``get_data`` default-implementation contract.
"""

__all__ = ["helao_driver_unit_test"]

import asyncio
import traceback
from datetime import datetime

from helao.core.drivers.helao_driver import (
    DriverPoller,
    DriverResponse,
    DriverResponseType,
    DriverStatus,
    HelaoDriver,
)
from helao.core.tests._test_utils import TestReporter


class _StubDriver(HelaoDriver):
    """Minimal concrete :class:`HelaoDriver` that records call counts."""

    def __init__(self, config: dict = None):
        super().__init__(config or {})
        self.calls = {
            "connect": 0,
            "get_status": 0,
            "stop": 0,
            "reset": 0,
            "disconnect": 0,
        }

    def connect(self) -> DriverResponse:
        self.calls["connect"] += 1
        return DriverResponse(
            response=DriverResponseType.success, status=DriverStatus.ok
        )

    def get_status(self) -> DriverResponse:
        self.calls["get_status"] += 1
        return DriverResponse(
            response=DriverResponseType.success, status=DriverStatus.ok
        )

    def stop(self) -> DriverResponse:
        self.calls["stop"] += 1
        return DriverResponse(
            response=DriverResponseType.success, status=DriverStatus.ok
        )

    def reset(self) -> DriverResponse:
        self.calls["reset"] += 1
        return DriverResponse(
            response=DriverResponseType.success, status=DriverStatus.ok
        )

    def disconnect(self) -> DriverResponse:
        self.calls["disconnect"] += 1
        return DriverResponse(
            response=DriverResponseType.success, status=DriverStatus.ok
        )


class _IncompleteDriver(HelaoDriver):
    """Driver missing every abstract method - instantiation must fail."""

    pass


def helao_driver_unit_test() -> bool:
    """Run all helao_driver assertions and report pass/fail."""
    reporter = TestReporter("helao_driver")

    try:
        reporter.section("DriverStatus enum")
        expected_status = {
            "ok",
            "busy",
            "error",
            "uninitialized",
            "unknown",
            "retry",
        }
        reporter.check(
            "DriverStatus has all six documented members",
            lambda: {m.name for m in DriverStatus} == expected_status,
        )
        reporter.check(
            "DriverStatus.ok round-trips through its value",
            lambda: DriverStatus(DriverStatus.ok.value) is DriverStatus.ok,
        )
        reporter.check(
            "DriverStatus values equal their names",
            lambda: all(m.value == m.name for m in DriverStatus),
        )

        reporter.section("DriverResponseType enum")
        reporter.check(
            "DriverResponseType has the three documented members",
            lambda: {m.name for m in DriverResponseType}
            == {"success", "failed", "not_implemented"},
        )

        reporter.section("DriverResponse defaults and timestamp stamping")
        resp = DriverResponse()
        reporter.check(
            "default response is not_implemented",
            lambda: resp.response is DriverResponseType.not_implemented,
        )
        reporter.check(
            "default status is unknown",
            lambda: resp.status is DriverStatus.unknown,
        )
        reporter.check(
            "default data is an empty dict",
            lambda: resp.data == {},
        )
        reporter.check(
            "default message is empty",
            lambda: resp.message == "",
        )
        reporter.check(
            "timestamp is stamped at construction",
            lambda: isinstance(resp.timestamp, datetime),
        )
        reporter.check(
            "timestamp_str is a non-empty formatted string",
            lambda: isinstance(resp.timestamp_str, str) and len(resp.timestamp_str) > 0,
        )

        reporter.section("DriverResponse honours explicit fields")
        rich = DriverResponse(
            response=DriverResponseType.success,
            message="ok",
            data={"value": 1},
            status=DriverStatus.ok,
        )
        reporter.check(
            "DriverResponse preserves response/status/data/message",
            lambda: (
                rich.response is DriverResponseType.success
                and rich.status is DriverStatus.ok
                and rich.data == {"value": 1}
                and rich.message == "ok"
            ),
        )

        reporter.section("HelaoDriver concrete subclass works")
        drv = _StubDriver(config={"option": True})
        reporter.check(
            "HelaoDriver records the provided config",
            lambda: drv.config == {"option": True},
        )
        reporter.check(
            "HelaoDriver records a creation timestamp",
            lambda: isinstance(drv.timestamp, datetime),
        )
        reporter.check(
            "HelaoDriver._created_at exposes a formatted timestamp",
            lambda: isinstance(drv._created_at, str) and len(drv._created_at) > 0,
        )

        # Confirm each abstract method dispatches to its concrete impl.
        for method in ("connect", "get_status", "stop", "reset", "disconnect"):
            response = getattr(drv, method)()
            reporter.check(
                f"_StubDriver.{method}() returns a successful DriverResponse",
                (
                    lambda response=response: response.response
                    is DriverResponseType.success
                    and response.status is DriverStatus.ok
                ),
            )
        reporter.check(
            "every abstract method on the stub driver was invoked exactly once",
            lambda: all(c == 1 for c in drv.calls.values()),
        )

        reporter.section(
            "HelaoDriver refuses to instantiate without the abstract methods"
        )

        def _try_instantiate_incomplete():
            _IncompleteDriver()  # type: ignore[abstract]

        reporter.check(
            "missing-abstract subclass raises TypeError",
            lambda: _expect_raises(_try_instantiate_incomplete, TypeError),
        )

        reporter.section("DriverPoller.get_data default contract")

        async def _drive_poller_default():
            # The poller spawns asyncio tasks at construction time, which
            # immediately enter the polling loop. Cancel them right away so
            # the loop doesn't keep firing get_data() during the test.
            poller = DriverPoller(drv, wait_time=999.0)
            try:
                poller.poll_signal_task.cancel()
                poller.polling_task.cancel()
                # await cancellation
                for t in (poller.poll_signal_task, poller.polling_task):
                    try:
                        await t
                    except asyncio.CancelledError:
                        pass
                # The unoverridden get_data must return a default DriverResponse
                resp = poller.get_data()
                return resp

            finally:
                pass

        default_resp = asyncio.run(_drive_poller_default())
        reporter.check(
            "DriverPoller.get_data default returns a DriverResponse instance",
            lambda: isinstance(default_resp, DriverResponse),
        )
        reporter.check(
            "DriverPoller.get_data default has empty data dict",
            lambda: default_resp.data == {},
        )

        return reporter.success()

    except Exception as exc:  # noqa: BLE001
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        print(repr(exc), tb)
        return False


def _expect_raises(fn, exc_type) -> bool:
    """Return True iff calling ``fn()`` raises an instance of ``exc_type``."""
    try:
        fn()
    except exc_type:
        return True
    except Exception:  # noqa: BLE001
        return False
    return False
