""" Kinesis motor server

"""

__all__ = ["makeApp"]

from typing import Optional
from fastapi import Body
from helao.helpers.premodels import Action
from helao.servers.base_api import BaseAPI
from helao.drivers.motion.kinesis_driver import (
    KinesisMotor,
    MoveModes,
    KinesisMotorExec,
)
from helao.helpers.config_loader import config_loader


async def mfc_dyn_endpoints(app=None):
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
            await app.driver.start_polling()
            return "start_polling: ok"

        @app.post("/stop_polling", tags=["private"])
        async def stop_polling():
            await app.driver.stop_polling()
            return "stop_polling: ok"


def makeApp(confPrefix, server_key, helao_root):
    config = config_loader(confPrefix, helao_root)

    # current plan is 1 mfc per COM

    app = BaseAPI(
        config=config,
        server_key=server_key,
        server_title=server_key,
        description="Kinesis motor server",
        version=0.1,
        driver_class=KinesisMotor,
        dyn_endpoints=mfc_dyn_endpoints,
    )

    return app
