"""Thorlabs Kinesis motor driver.

Wraps `pylablib.devices.Thorlabs.KinesisMotor` per configured axis and
exposes the HELAO `HelaoDriver` interface (`connect`, `get_status`, `stop`,
`reset`, `disconnect`) plus `setup` and `move`. Per-axis position/velocity/
acceleration scales are read from `config["axes"]`.

Reference scales for the MLJ150/M stage:
- position 0..61440000 counts -> 0..50 mm  (1228800.0 counts/mm)
- velocity 0..329853488        -> 0..5 mm/s (65970697.6)
- acceleration 0..135182       -> 0..10 mm/s^2 (13518.2)
"""

from helao.framework.support import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
from enum import Enum
from typing import Optional

from helao.framework.support.make_str_enum import make_str_enum

from pylablib.devices import Thorlabs

from helao.framework.ports.driver import (
    HelaoDriver,
    DriverPoller,
    DriverResponse,
    DriverStatus,
    DriverResponseType,
)


class MoveModes(str, Enum):
    """Move mode for the Kinesis driver.

    Attributes:
        relative: Move by an offset from the current position.
        absolute: Move to an absolute coordinate.
    """

    relative = "relative"
    absolute = "absolute"


MOTION_STATES = [
    "moving_fw",
    "moving_bk",
    "jogging_fw",
    "jogging_bk",
    "homing",
    "active",
]


class KinesisMotor(HelaoDriver):
    """`HelaoDriver` managing one Thorlabs Kinesis motor per configured axis.

    Each entry under `config["axes"]` must provide `serial_no`, `pos_scale`,
    `vel_scale`, and `acc_scale`. The driver also builds a `dev_kinesis`
    enum mapping axis name to itself for use in the action server's typed
    endpoints.
    """

    def __init__(self, config: dict = {}):
        """Initialize the driver state and immediately attempt to connect.

        Args:
            config: Driver configuration containing an `axes` dict.
        """
        super().__init__(config=config)
        self.motors = {}
        self.connect()

    def connect(self) -> DriverResponse:
        """Open a `KinesisMotor` instance for every configured axis."""
        try:
            for axis_name, dev_dict in self.config.get("axes", {}).items():
                scale_tup = (
                    dev_dict["pos_scale"],
                    dev_dict["vel_scale"],
                    dev_dict["acc_scale"],
                )
                self.motors[axis_name] = Thorlabs.KinesisMotor(
                    conn=dev_dict["serial_no"], scale=scale_tup
                )

            self.dev_kinesis = make_str_enum(
                "dev_kinesis", {key: key for key in self.motors}
            )

            LOGGER.info(f"Managing {len(self.motors)} devices:\n{self.motors.keys()}")

            response = DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            LOGGER.error("connection failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )

        return response

    def get_status(self) -> DriverResponse:
        """Return per-axis position (mm), velocity, acceleration, and status flags."""
        try:
            state = {}
            for axis, motor in self.motors.items():
                resp_dict = motor.get_full_status(
                    include=["velocity_parameters", "position", "status"]
                )
                if resp_dict is not None:
                    vel_params = resp_dict["velocity_parameters"]
                    state[axis] = {
                        "position_mm": round(resp_dict["position"], 3),
                        "velocity_mmpersec": round(vel_params.max_velocity, 3),
                        "acceleration_mmpersec2": round(vel_params.acceleration, 3),
                        "status": resp_dict["status"],
                    }
            response = DriverResponse(
                response=DriverResponseType.success, data=state, status=DriverStatus.ok
            )
        except Exception:
            LOGGER.error("get_status failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        return response

    def setup(
        self,
        axis: str,
        velocity: Optional[float] = None,
        acceleration: Optional[float] = None,
    ) -> DriverResponse:
        """Configure max velocity and/or acceleration on a single axis.

        Args:
            axis: Axis name (key in `self.motors`).
            velocity: New maximum velocity (physical units), or None to keep.
            acceleration: New acceleration (physical units), or None to keep.
        """
        try:
            if velocity is not None or acceleration is not None:
                self.motors[axis].setup_velocity(
                    acceleration=acceleration, max_velocity=velocity, scale=True
                )
                LOGGER.info(f"velocity and acceleration set for axis: {axis}")
            else:
                LOGGER.info("neither velocity nor acceleration were specified")
            response = DriverResponse(
                response=DriverResponseType.success,
                message="setup complete",
                status=DriverStatus.ok,
            )
        except Exception:
            LOGGER.error("setup failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        return response

    def move(self, axis: str, move_mode: MoveModes, value: float) -> DriverResponse:
        """Start a relative or absolute move on the named axis.

        Args:
            axis: Axis name (key in `self.motors`).
            move_mode: `MoveModes.relative` calls `move_by`,
                `MoveModes.absolute` calls `move_to`.
            value: Target distance or absolute position in physical units.
        """
        try:
            if move_mode == MoveModes.relative:
                move_func = self.motors[axis].move_by
            elif move_mode == MoveModes.absolute:
                move_func = self.motors[axis].move_to
                LOGGER.info("kinesis motor starting motion")
            move_func(value)
            response = DriverResponse(
                response=DriverResponseType.success,
                message="move started",
                status=DriverStatus.ok,
            )
        except Exception:
            LOGGER.error("move failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        return response

    def stop(self, axis: Optional[str] = None) -> DriverResponse:
        """Immediately stop one named axis or, when `axis` is None, every axis."""
        try:
            stop_axes = [axis] if axis is not None else self.motors.keys()
            for stop_axis in stop_axes:
                self.motors[stop_axis].stop(immediate=True, sync=True)
            response = DriverResponse(
                response=DriverResponseType.success,
                message="stop complete",
                status=DriverStatus.ok,
            )
        except Exception:
            LOGGER.error("stop failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        return response

    def reset(self) -> DriverResponse:
        """Disconnect every motor and reconnect; report failure if reconnect errors."""
        try:
            self.disconnect()
            reconnect_resp = self.connect()
            if reconnect_resp.status != DriverStatus.ok:
                raise ConnectionResetError
            response = DriverResponse(
                response=DriverResponseType.success,
                message="reset complete",
                status=DriverStatus.ok,
            )
        except Exception:
            LOGGER.error("reset failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        return response

    def disconnect(self) -> DriverResponse:
        """Close every Kinesis motor handle owned by this driver."""
        try:
            for axis_name, kmotor in self.motors.items():
                LOGGER.info(f"closing connection to {axis_name}")
                kmotor.close()
            response = DriverResponse(
                response=DriverResponseType.success,
                message="disconnect complete",
                status=DriverStatus.ok,
            )
        except Exception:
            LOGGER.error("disconnect failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        return response


class KinesisPoller(DriverPoller):
    """`DriverPoller` that publishes `KinesisMotor.get_status()` on every tick."""

    def get_data(self) -> DriverResponse:
        """Return the latest `get_status` `DriverResponse` from the underlying driver."""
        poll_data = self.driver.get_status()
        return poll_data
