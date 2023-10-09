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
                            f"{axis}_pos_mm": round(resp_dict["position"], 6),
                            f"{axis}_vel_mmpersec": round(vel_params.max_velocity, 6),
                            f"{axis}_acc_mmpersec2": round(vel_params.acceleration, 6),
                            f"{axis}_status": resp_dict["status"]
                        }
                        lastupdate = time.time()
                        # self.base.print_message(f"Live buffer updated at {checktime}")
                        async with self.base.aiolock:
                            await self.base.put_lbuf(status_dict)
                        # self.base.print_message("status sent to live buffer")
                await asyncio.sleep(waittime)
