"""Tests for :mod:`helao.framework.ports.driver`.

Ports the meaningful assertions from the legacy
``helao.core.tests.unit_test_helao_driver`` suite onto the framework
copy of the driver contract. Uses a dummy :class:`HelaoDriver` subclass
so nothing here touches real hardware.
"""

import asyncio
from datetime import datetime

import pytest

from helao.framework.ports.driver import (
    DriverPoller,
    DriverResponse,
    DriverResponseType,
    DriverStatus,
    HelaoDriver,
)


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


# --- DriverStatus enum -----------------------------------------------------


def test_driver_status_has_all_six_members():
    assert {m.name for m in DriverStatus} == {
        "ok",
        "busy",
        "error",
        "uninitialized",
        "unknown",
        "retry",
    }


def test_driver_status_round_trips_through_value():
    assert DriverStatus(DriverStatus.ok.value) is DriverStatus.ok


def test_driver_status_values_equal_names():
    assert all(m.value == m.name for m in DriverStatus)


def test_driver_status_compares_equal_to_string():
    assert DriverStatus.ok == "ok"


# --- DriverResponseType enum ----------------------------------------------


def test_driver_response_type_has_three_members():
    assert {m.name for m in DriverResponseType} == {
        "success",
        "failed",
        "not_implemented",
    }


def test_driver_response_type_compares_equal_to_string():
    assert DriverResponseType.success == "success"


# --- DriverResponse --------------------------------------------------------


def test_driver_response_defaults():
    resp = DriverResponse()
    assert resp.response is DriverResponseType.not_implemented
    assert resp.status is DriverStatus.unknown
    assert resp.data == {}
    assert resp.message == ""


def test_driver_response_stamps_timestamp_at_construction():
    resp = DriverResponse()
    assert isinstance(resp.timestamp, datetime)


def test_driver_response_timestamp_str_is_formatted_string():
    resp = DriverResponse()
    assert isinstance(resp.timestamp_str, str)
    assert len(resp.timestamp_str) > 0
    # YYYY-MM-DD HH:MM:SS,mmm
    assert resp.timestamp_str == resp.timestamp.strftime("%F %T,%f")[:-3]


def test_driver_response_round_trips_explicit_fields():
    rich = DriverResponse(
        response=DriverResponseType.success,
        message="ok",
        data={"value": 1},
        status=DriverStatus.ok,
    )
    assert rich.response is DriverResponseType.success
    assert rich.status is DriverStatus.ok
    assert rich.data == {"value": 1}
    assert rich.message == "ok"


# --- HelaoDriver ABC -------------------------------------------------------


def test_concrete_subclass_records_config():
    drv = _StubDriver(config={"option": True})
    assert drv.config == {"option": True}


def test_concrete_subclass_records_creation_timestamp():
    drv = _StubDriver()
    assert isinstance(drv.timestamp, datetime)


def test_created_at_returns_formatted_string():
    drv = _StubDriver()
    assert isinstance(drv._created_at, str)
    assert len(drv._created_at) > 0


def test_uptime_inherits_source_timedelta_bug():
    # Ported near-verbatim from helao.core: ``_uptime`` calls ``.strftime``
    # on a ``timedelta`` (the result of ``datetime.now() - self.timestamp``),
    # which raises. We assert the inherited behavior rather than alter the
    # faithfully-ported source.
    drv = _StubDriver()
    with pytest.raises(AttributeError):
        _ = drv._uptime


def test_abstract_methods_dispatch_to_concrete_impl():
    drv = _StubDriver()
    for method in ("connect", "get_status", "stop", "reset", "disconnect"):
        response = getattr(drv, method)()
        assert response.response is DriverResponseType.success
        assert response.status is DriverStatus.ok
    assert all(c == 1 for c in drv.calls.values())


def test_incomplete_subclass_cannot_instantiate():
    with pytest.raises(TypeError):
        _IncompleteDriver()  # type: ignore[abstract]


# --- DriverPoller ----------------------------------------------------------


def test_driver_poller_constructs_and_get_data_default_contract():
    async def _drive_poller_default():
        drv = _StubDriver()
        poller = DriverPoller(drv, wait_time=999.0)
        assert poller.driver is drv
        assert poller.wait_time == 999.0
        assert poller.polling is True
        # Cancel the background tasks so the loop stops firing get_data().
        poller.poll_signal_task.cancel()
        poller.polling_task.cancel()
        for t in (poller.poll_signal_task, poller.polling_task):
            try:
                await t
            except asyncio.CancelledError:
                pass
        # The unoverridden get_data must return a default DriverResponse.
        return poller.get_data()

    resp = asyncio.run(_drive_poller_default())
    assert isinstance(resp, DriverResponse)
    assert resp.data == {}


def test_driver_poller_toggles_polling_flag():
    async def _toggle():
        drv = _StubDriver()
        poller = DriverPoller(drv, wait_time=999.0)
        try:
            await poller._stop_polling()
            assert poller.polling is False
            await poller._start_polling()
            assert poller.polling is True
        finally:
            poller.poll_signal_task.cancel()
            poller.polling_task.cancel()
            for t in (poller.poll_signal_task, poller.polling_task):
                try:
                    await t
                except asyncio.CancelledError:
                    pass

    asyncio.run(_toggle())
