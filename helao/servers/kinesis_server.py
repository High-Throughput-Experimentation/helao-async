""" Kinesis motor server

"""

__all__ = ["makeApp"]

from typing import Optional, List, Union
from fastapi import Body
from helao.helpers.premodels import Action
from helao.servers.base_api import BaseAPI
from helaocore.models.sample import SampleUnion
from helao.drivers.motion.kinesis_driver import KinesisMotor
from helao.helpers.config_loader import config_loader


async def mfc_dyn_endpoints(app=None):
    server_key = app.base.server.server_name
    motors = list(app.base.server_params["axes"].keys())

    if motors:

        # @app.post(f"/{server_key}/acquire_flowrate", tags=["action"])
        # async def acquire_flowrate(
        #     action: Action = Body({}, embed=True),
        #     action_version: int = 2,
        #     device_name: app.driver.dev_mfcs = motors[0],
        #     flowrate_sccm: float = None,
        #     ramp_sccm_sec: float = 0,
        #     stay_open: bool = False,
        #     duration: float = -1,
        #     acquisition_rate: float = 0.2,
        #     fast_samples_in: List[SampleUnion] = Body([], embed=True),
        #     exec_id: Optional[str] = None,
        # ):
        #     """Set flow rate and record."""
        #     active = await app.base.setup_and_contain_action()
        #     active.action.action_abbr = "acq_flow"
        #     executor = MfcExec(
        #         active=active,
        #         oneoff=False,
        #         poll_rate=active.action.action_params["acquisition_rate"],
        #     )
        #     active_action_dict = active.start_executor(executor)
        #     return active_action_dict

        # @app.post(f"/{server_key}/cancel_acquire_flowrate", tags=["action"])
        # async def cancel_acquire_flowrate(
        #     action: Action = Body({}, embed=True),
        #     action_version: int = 1,
        #     device_name: Optional[str] = None,
        #     exec_id: Optional[str] = None,
        # ):
        #     """Stop flowrate & acquisition for given device_name."""
        #     active = await app.base.setup_and_contain_action()
        #     if active.action.action_params["exec_id"] is not None:
        #         app.base.stop_executor(active.action.action_params["exec_id"])
        #     else:
        #         if active.action.action_params["device_name"] is None:
        #             dev_dict = {}
        #         else:
        #             dev_dict = {"device_name": active.action.action_params["device_name"]}
        #         app.base.stop_all_executor_prefix("acquire_flowrate", dev_dict)
        #     finished_action = await active.finish()
        #     return finished_action.as_dict()

        # @app.post(f"/{server_key}/set_flowrate", tags=["action"])
        # async def set_flowrate(
        #     action: Action = Body({}, embed=True),
        #     action_version: int = 1,
        #     device_name: app.driver.dev_mfcs = devices[0],
        #     flowrate_sccm: float = None,
        #     ramp_sccm_sec: float = 0,
        # ):
        #     active = await app.base.setup_and_contain_action(action_abbr="set_flow")
        #     app.driver.set_flowrate(**active.action.action_params)
        #     finished_action = await active.finish()
        #     return finished_action.as_dict()

        # @app.post(f"/{server_key}/set_pressure", tags=["action"])
        # async def set_pressure(
        #     action: Action = Body({}, embed=True),
        #     action_version: int = 1,
        #     device_name: app.driver.dev_mfcs = devices[0],
        #     pressure_psia: float = None,
        #     ramp_psi_sec: float = 0,
        # ):
        #     active = await app.base.setup_and_contain_action(action_abbr="set_pressure")
        #     app.driver.set_pressure(**active.action.action_params)
        #     finished_action = await active.finish()
        #     return finished_action.as_dict()

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
