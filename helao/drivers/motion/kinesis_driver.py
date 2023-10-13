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

from enum import Enum
import time
import asyncio

import numpy as np

from helaocore.error import ErrorCodes
from helao.servers.base import Base
from helao.helpers.executor import Executor
from helaocore.models.hlostatus import HloStatus
from helao.helpers.make_str_enum import make_str_enum
from helao.helpers.sample_api import UnifiedSampleDataAPI
from helao.helpers.ws_subscriber import WsSyncClient as WSC

from pylablib.devices import Thorlabs


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


class KinesisMotor:
    def __init__(self, action_serv: Base):
        self.base = action_serv
        self.config_dict = action_serv.server_cfg.get("params", {})

        self.unified_db = UnifiedSampleDataAPI(self.base)

        self.motors = {}

        for axis_name, dev_dict in self.config_dict.get("axes", {}).items():
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

        self.base.print_message(
            f"Managing {len(self.motors)} devices:\n{self.motors.keys()}"
        )

        self.aloop = asyncio.get_running_loop()
        self.polling = True
        self.poll_signalq = asyncio.Queue(1)
        self.poll_signal_task = self.aloop.create_task(self.poll_signal_loop())
        self.polling_task = self.aloop.create_task(self.poll_sensor_loop())
        self.last_state = "unknown"

    async def start_polling(self):
        self.base.print_message("got 'start_polling' request, raising signal")
        async with self.base.aiolock:
            await self.poll_signalq.put(True)

    async def stop_polling(self):
        self.base.print_message("got 'stop_polling' request, raising signal")
        async with self.base.aiolock:
            await self.poll_signalq.put(False)

    async def poll_signal_loop(self):
        while True:
            self.polling = await self.poll_signalq.get()
            self.base.print_message("polling signal received")

    async def poll_sensor_loop(self, waittime: float = 0.05):
        self.base.print_message("Kinesis background task has started")
        lastupdate = 0
        while True:
            for axis, motor in self.motors.items():
                if self.polling:
                    checktime = time.time()
                    if checktime - lastupdate < waittime:
                        await asyncio.sleep(waittime - (checktime - lastupdate))
                    resp_dict = motor.get_full_status(
                        include=["velocity_parameters", "position", "status"]
                    )
                    if resp_dict is not None:
                        vel_params = resp_dict["velocity_parameters"]
                        status_dict = {
                            axis: {
                                "position_mm": round(resp_dict["position"], 3),
                                "velocity_mmpersec": round(vel_params.max_velocity, 3),
                                "acceleration_mmpersec2": round(
                                    vel_params.acceleration, 3
                                ),
                                "status": resp_dict["status"],
                            }
                        }
                        lastupdate = time.time()
                        # self.base.print_message(f"Live buffer updated at {checktime}")
                        async with self.base.aiolock:
                            await self.base.put_lbuf(status_dict)
                        # self.base.print_message("status sent to live buffer")
                await asyncio.sleep(waittime)


class KinesisMotorExec(Executor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.axis_name = self.active.action.action_params["axis"]
        self.current_position = self.active.base.get_lbuf(self.axis_name)[0].get(
            "position_mm", 9999
        )
        self.axis = self.active.base.fastapp.driver.motors[self.axis_name]
        self.axis_params = self.active.base.server_params["axes"][self.axis_name]
        self.active.base.print_message("KinesisMotorExec initialized.")
        self.start_time = time.time()
        self.duration = self.active.action.action_params.get("duration", -1)

    async def _pre_exec(self):
        "Set velocity and acceleration."
        self.active.base.print_message("KinesisMotorExec running setup methods.")
        self.velocity = self.active.action.action_params.get("velocity_mm_s", None)
        self.acceleration = self.active.action.action_params.get(
            "acceleration_mm_s2", None
        )
        self.move_mode = self.active.action.action_params.get("move_mode", "relative")
        self.move_value = self.active.action.action_params.get("value_mm", 0.0)
        self.active.base.print_message("KinesisMotorExec checking velocity and accel.")
        if self.velocity is not None or self.acceleration is not None:
            self.axis.setup_velocity(
                acceleration=self.acceleration, max_velocity=self.velocity, scale=True
            )
        self.active.base.print_message("KinesisMotorExec setup complete.")
        return {"error": ErrorCodes.none}

    async def _exec(self):
        "Execute motion."
        self.active.base.print_message("KinesisMotorExec validating move mode & limit.")
        self.start_time = time.time()
        if self.move_mode == MoveModes.relative:
            move_func = self.axis.move_by
            final_pos = self.current_position + self.move_value
        else:
            move_func = self.axis.move_to
            final_pos = self.move_value

        if final_pos < self.axis_params.get("move_limit_mm", 3.0):
            self.active.base.print_message("KinesisMotorExec starting motion.")
            move_func(self.move_value)
            return {"error": ErrorCodes.none}
        else:
            self.active.base.print_message(
                f"final position {final_pos} is greater than motion limit, ignoring motion request."
            )
            return {"error": ErrorCodes.motor}

    async def _poll(self):
        """Read flow from live buffer."""
        live_dict, epoch_s = self.active.base.get_lbuf(self.axis_name)
        live_dict["epoch_s"] = epoch_s
        if any([x in MOTION_STATES for x in live_dict["status"]]):
            status = HloStatus.active
        else:
            status = HloStatus.finished
        await asyncio.sleep(0.01)
        return {
            "error": ErrorCodes.none,
            "status": status,
            "data": {"position_mm": live_dict["position_mm"]},
        }

    async def _manual_stop(self):
        "Perform device manual stop, return error state."
        self.axis.stop(immediate=True, sync=True)
        self.stop_err = ErrorCodes.none
        return {"error": self.stop_err}