"""GalilMotionHardwareAdapter behavior tests (P3a galil-split slice-3).

Linux construct-test tier: proves the native adapter is constructible without
hardware or gclib, structurally satisfies HardwarePort, and delegates every
lifecycle/motion verb to the wrapped legacy driver with the legacy return
values intact. Real device I/O (connect + motion on the controller) is an
at-station gate and is not exercised here.
"""

import asyncio

import pytest

from helao.core.drivers.helao_driver import (
    DriverResponse,
    DriverResponseType,
    DriverStatus,
)
from helao.hexagon.adapters.native.galil_motion import GalilMotionHardwareAdapter
from helao.hexagon.ports.hardware import HardwarePort


# --------------------------------------------------------------------------
# Fakes: a stand-in legacy driver recording delegation, so the motion verbs
# can be exercised without gclib / a controller.
# --------------------------------------------------------------------------
class _FakeGalil:
    def __init__(self):
        self.galil_enabled = None
        self.axis_id = {"x": "A", "y": "B"}
        self.calls = []

    # sync ABC lifecycle
    def connect(self) -> DriverResponse:
        self.calls.append(("connect",))
        self.galil_enabled = True
        return DriverResponse(
            response=DriverResponseType.success, status=DriverStatus.ok
        )

    def get_status(self) -> DriverResponse:
        self.calls.append(("get_status",))
        return DriverResponse(
            response=DriverResponseType.success, status=DriverStatus.ok
        )

    def reset(self) -> DriverResponse:
        self.calls.append(("reset",))
        return DriverResponse(
            response=DriverResponseType.success, status=DriverStatus.ok
        )

    def disconnect(self) -> DriverResponse:
        self.calls.append(("disconnect",))
        return DriverResponse(
            response=DriverResponseType.success, status=DriverStatus.ok
        )

    def shutdown(self) -> set:
        self.calls.append(("shutdown",))
        return {"shutdown"}

    def get_all_axis(self) -> list:
        return [ax for ax in self.axis_id]

    # async device methods (dict / bool returns)
    async def stop(self) -> DriverResponse:
        self.calls.append(("stop",))
        return DriverResponse(
            response=DriverResponseType.success, status=DriverStatus.ok
        )

    async def estop(self, switch, *_args, **_kwargs) -> bool:
        self.calls.append(("estop", switch))
        return switch

    async def motor_move(self, active) -> dict:
        self.calls.append(("motor_move", active))
        return {"err_code": 0, "moved": active}

    async def motor_disconnect(self) -> dict:
        self.calls.append(("motor_disconnect",))
        return {"connection": False}

    async def query_axis_position(self, axis, *_args, **_kwargs) -> dict:
        self.calls.append(("query_axis_position", axis))
        return {"err_code": 0, "position": [1.0], "ax": axis}

    async def query_axis_moving(self, axis, *_args, **_kwargs) -> dict:
        self.calls.append(("query_axis_moving", axis))
        return {"err_code": 0, "motor_status": ["stopped"], "ax": axis}

    async def stop_axis(self, axis) -> dict:
        self.calls.append(("stop_axis", axis))
        return {"err_code": 0, "ax": axis}

    async def motor_off(self, axis, *_args, **_kwargs) -> dict:
        self.calls.append(("motor_off", axis))
        return {"err_code": 0, "ax": axis}

    async def motor_on(self, axis, *_args, **_kwargs) -> dict:
        self.calls.append(("motor_on", axis))
        return {"err_code": 0, "ax": axis}

    async def setaxisref(self):
        self.calls.append(("setaxisref",))
        return {"err_code": 0}

    async def reset_controller(self):
        self.calls.append(("reset_controller",))
        return ""


def _adapter() -> tuple[GalilMotionHardwareAdapter, _FakeGalil]:
    fake = _FakeGalil()
    # duck-typed stand-in for the legacy Galil; the adapter only delegates.
    return GalilMotionHardwareAdapter(fake), fake  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Construct / conformance (the real Galil, no hardware)
# --------------------------------------------------------------------------
def test_from_config_constructs_without_io():
    a = GalilMotionHardwareAdapter.from_config(
        {"axis_id": {"x": "A", "y": "B"}, "timeout": 42}
    )
    # slice 1/2 disconnected-construct: no gclib, no connection opened.
    assert a.galil_enabled is None
    assert a.driver.g is None
    assert a.driver.galilcmd is None
    assert a.get_all_axis() == ["x", "y"]


def test_from_config_defaults_and_base_hook():
    a = GalilMotionHardwareAdapter.from_config()
    assert a.driver._base_hook is None
    sentinel = object()
    b = GalilMotionHardwareAdapter.from_config({}, base_hook=sentinel)
    assert b.driver._base_hook is sentinel


def test_satisfies_hardware_port_protocol():
    a, _ = _adapter()
    assert isinstance(a, HardwarePort)


def test_galil_enabled_passthrough():
    a, fake = _adapter()
    assert a.galil_enabled is None
    fake.galil_enabled = True
    assert a.galil_enabled is True


def test_base_hook_proxy_reaches_wrapped_driver():
    # The server handshake assigns `app.driver._base_hook = app.base` AFTER
    # construction; when the adapter is `app.driver`, that must land on the
    # wrapped legacy driver so its connect() can read helaodirs/server_cfg.
    a = GalilMotionHardwareAdapter.from_config({"axis_id": {}})
    assert a._base_hook is None
    sentinel = object()
    a._base_hook = sentinel
    assert a._base_hook is sentinel
    assert a.driver._base_hook is sentinel


# --------------------------------------------------------------------------
# Lifecycle delegation
# --------------------------------------------------------------------------
def test_connect_delegates_and_passes_through_driver_response():
    a, fake = _adapter()
    resp = asyncio.run(a.connect())
    assert isinstance(resp, DriverResponse)
    assert resp.response == DriverResponseType.success
    assert fake.calls == [("connect",)]
    assert a.galil_enabled is True


def test_get_status_reset_disconnect_delegate():
    a, fake = _adapter()
    assert isinstance(asyncio.run(a.get_status()), DriverResponse)
    assert isinstance(asyncio.run(a.reset()), DriverResponse)
    assert isinstance(asyncio.run(a.disconnect()), DriverResponse)
    assert [c[0] for c in fake.calls] == ["get_status", "reset", "disconnect"]


def test_abort_maps_to_legacy_stop():
    a, fake = _adapter()
    resp = asyncio.run(a.abort())
    assert resp.response == DriverResponseType.success
    assert fake.calls == [("stop",)]


def test_estop_wraps_bool_into_driver_response_but_performs_device_action():
    a, fake = _adapter()
    resp = asyncio.run(a.estop(True))
    assert isinstance(resp, DriverResponse)
    assert resp.response == DriverResponseType.success
    assert resp.status == DriverStatus.ok
    # the device-side estop was actually invoked with the switch value
    assert fake.calls == [("estop", True)]


def test_shutdown_wraps_set_into_driver_response():
    a, fake = _adapter()
    resp = asyncio.run(a.shutdown())
    assert isinstance(resp, DriverResponse)
    assert resp.response == DriverResponseType.success
    assert fake.calls == [("shutdown",)]


# --------------------------------------------------------------------------
# Motion verbs: legacy dict returns intact
# --------------------------------------------------------------------------
def test_motion_verbs_return_legacy_dicts_verbatim():
    a, _ = _adapter()
    assert asyncio.run(a.motor_move("ACT")) == {"err_code": 0, "moved": "ACT"}
    assert asyncio.run(a.motor_disconnect()) == {"connection": False}
    assert asyncio.run(a.query_axis_position(["x"])) == {
        "err_code": 0,
        "position": [1.0],
        "ax": ["x"],
    }
    assert asyncio.run(a.query_axis_moving(["x"])) == {
        "err_code": 0,
        "motor_status": ["stopped"],
        "ax": ["x"],
    }
    assert asyncio.run(a.stop_axis(["x"])) == {"err_code": 0, "ax": ["x"]}
    assert asyncio.run(a.motor_off("x")) == {"err_code": 0, "ax": "x"}
    assert asyncio.run(a.motor_on("x")) == {"err_code": 0, "ax": "x"}
    assert asyncio.run(a.setaxisref()) == {"err_code": 0}
    assert asyncio.run(a.reset_controller()) == ""


# --------------------------------------------------------------------------
# Measurement phase is N/A and fails loud (never a silent no-op)
# --------------------------------------------------------------------------
@pytest.mark.parametrize("verb", ["arm", "start", "drain", "cleanup"])
def test_measurement_phase_raises_not_implemented(verb):
    a, _ = _adapter()
    with pytest.raises(NotImplementedError):
        asyncio.run(getattr(a, verb)())
