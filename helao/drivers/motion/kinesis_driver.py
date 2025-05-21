""" Thorlabs Kinesis motor driver class

Notes:
# list devices
devices = Thorlabs.list_kinesis_devices()

# connect to MLJ150/M
stage = Thorlabs.KinesisMotor("49370234", scale=(pos_scale, vel_scle, acc_scale))

# get current status (position, status list, motion parameters)
stage.get_full_status()

# move_by
# move_to
# home

# MLJ150/M -- read ranges from kinesis application, switch between device and phys units
# position 0 - 61440000 :: 0 - 50 mm :: physical-to-internal = 1228800.0
# velocity 0 - 329853488 :: 0 - 5 mm/s :: physical-to-internal = 65970697.6
# accel 0 - 135182 :: 0 - 10 mm/s2 :: physical-to-internal = 13518.2

"""

from helao.helpers import helao_logging as logging

if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER

from enum import Enum
from typing import Optional

from helao.helpers.make_str_enum import make_str_enum

from pylablib.devices import Thorlabs

from helao.drivers.helao_driver import (
    HelaoDriver,
    DriverPoller,
    DriverResponse,
    DriverStatus,
    DriverResponseType,
)


class MoveModes(str, Enum):
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
    def __init__(self, config: dict = {}):
        super().__init__(config=config)
        self.motors = {}
        self.connect()

    def connect(self) -> DriverResponse:
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
    def get_data(self):
        poll_data = self.driver.get_status()
        return poll_data
