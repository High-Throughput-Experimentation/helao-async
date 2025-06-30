""" Kinesis motor server

"""

__all__ = ["makeApp"]

from helao.helpers import helao_logging as logging

if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER

import time
import asyncio
from typing import Optional
from fastapi import Body
from helao.helpers.premodels import Action
from helao.servers.base_api import BaseAPI
from helao.drivers.motion.kinesis_driver import (
    KinesisMotor,
    KinesisPoller,
    MoveModes,
    MOTION_STATES,
)
from helao.helpers.config_loader import CONFIG

from helao.core.error import ErrorCodes
from helao.helpers.executor import Executor
from helao.core.models.hlostatus import HloStatus


class KinesisMotorExec(Executor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # shortcut attribs
        self.base = self.active.base
        self.driver = self.base.app.driver
        self.live_dict = self.base.app.poller.live_dict

        # action params and axis config
        self.action_params = self.active.action.action_params
        self.axis_name = self.action_params["axis"]
        if not isinstance(self.axis_name, str):
            self.axis_name = self.axis_name.value
        self.axis_params = self.base.server_params["axes"][self.axis_name]
        LOGGER.info("KinesisMotorExec initialized.")

    async def _pre_exec(self):
        "Set velocity and acceleration."
        LOGGER.info("KinesisMotorExec running setup methods.")
        velocity = self.action_params.get("velocity_mm_s", None)
        acceleration = self.action_params.get("acceleration_mm_s2", None)
        LOGGER.info("KinesisMotorExec checking velocity and accel.")
        resp = self.driver.setup(
            axis=self.axis_name, velocity=velocity, acceleration=acceleration
        )
        error = ErrorCodes.none if resp.response == "success" else ErrorCodes.setup
        LOGGER.info("KinesisMotorExec setup complete.")
        return {"error": error}

    async def _exec(self):
        "Execute motion."
        LOGGER.info("KinesisMotorExec validating move mode & limit.")
        move_mode = self.action_params.get("move_mode", "relative")
        move_value = self.action_params.get("value_mm", 0.0)
        current_position = self.live_dict[self.axis_name].get("position_mm", 9999)
        target_position = move_value
        if move_mode == MoveModes.relative:
            target_position += current_position

        self.start_time = time.time()
        if target_position < self.axis_params.get("move_limit_mm", 3.0):
            LOGGER.info("KinesisMotorExec starting motion.")
            resp = self.driver.move(self.axis_name, move_mode, move_value)
            error = (
                ErrorCodes.none if resp.response == "success" else ErrorCodes.critical_error
            )
            return {"error": error}
        else:
            LOGGER.info(
                f"final position {target_position} is greater than motion limit, ignoring motion request."
            )
            return {"error": ErrorCodes.motor}

    async def _poll(self):
        """Read position and status from driver live_dict."""
        live_dict, epoch_s = self.base.get_lbuf(self.axis_name)
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
        return {"error": ErrorCodes.none}


async def kinesis_dyn_endpoints(app: BaseAPI):
    server_key = app.base.server.server_name
    motors = list(app.base.server_params["axes"].keys())

    if motors:

        @app.post(f"/{server_key}/kmove", tags=["action"])
        async def kmove(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            axis: app.driver.dev_kinesis = motors[0],
            move_mode: MoveModes = "relative",
            value_mm: float = 0.0,
            velocity_mm_s: Optional[float] = None,
            acceleration_mm_s2: Optional[float] = None,
            poll_rate_s: float = 0.1,
            exec_id: Optional[str] = None,
        ):
            """Set flow rate and record."""
            active = await app.base.setup_and_contain_action()
            active.action.action_abbr = "kmove"
            executor = KinesisMotorExec(
                active=active,
                oneoff=False,
                poll_rate=active.action.action_params["poll_rate_s"],
            )
            active_action_dict = active.start_executor(executor)
            return active_action_dict

        @app.post(f"/{server_key}/cancel_kmove", tags=["action"])
        async def cancel_kmove(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            axis: app.driver.dev_kinesis = motors[0],
            exec_id: Optional[str] = None,
        ):
            """Stop flowrate & acquisition for given device_name."""
            active = await app.base.setup_and_contain_action()
            if active.action.action_params["exec_id"] is not None:
                app.base.stop_executor(active.action.action_params["exec_id"])
            else:
                if active.action.action_params["axis"] is None:
                    dev_dict = {}
                else:
                    dev_dict = {"axis": active.action.action_params["axis"]}
                app.base.stop_all_executor_prefix("kmove", dev_dict)
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post(f"/{server_key}/set_velocity", tags=["action"])
        async def set_flowrate(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            axis: app.driver.dev_kinesis = motors[0],
            velocity_mm_s: Optional[float] = None,
            acceleration_mm_s2: Optional[float] = None,
        ):
            active = await app.base.setup_and_contain_action(action_abbr="set_velocity")
            app.driver.motors[
                active.action.action_params["axis"]
            ].set_velocity_parameters(
                acceleration=active.action.action_params["acceleration_mm_s2"],
                max_velocity=active.action.action_params["velocity_mm_s"],
            )
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post("/start_polling", tags=["private"])
        async def start_polling():
            await app.poller.start_polling()
            return "start_polling: ok"

        @app.post("/stop_polling", tags=["private"])
        async def stop_polling():
            await app.poller.stop_polling()
            return "stop_polling: ok"


def makeApp(server_key):
    config = CONFIG

    # current plan is 1 mfc per COM

    app = BaseAPI(
        config=config,
        server_key=server_key,
        server_title=server_key,
        description="Kinesis motor server",
        version=0.2,
        driver_classes=[KinesisMotor],
        poller_class=KinesisPoller,
        dyn_endpoints=kinesis_dyn_endpoints,
    )

    return app
