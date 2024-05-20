# shell: uvicorn motion_server:app --reload
""" A FastAPI service definition for a potentiostat device server, e.g. Gamry.

andor_server uses the Executor model with helao.drivers.spec.andor.driver which decouples
the hardware driver class from the action server base class.

"""

__all__ = ["makeApp"]


import asyncio
import time
from typing import Optional, List
from collections import defaultdict, deque

import numpy as np
import pandas as pd
from fastapi import Body

from helaocore.error import ErrorCodes
from helaocore.models.hlostatus import HloStatus

from helao.servers.base_api import BaseAPI
from helao.helpers.premodels import Action
from helao.helpers.config_loader import config_loader
from helao.helpers.executor import Executor
from helao.helpers import logging  # get LOGGER from BaseAPI instance
from helao.drivers.spec.andor.driver import AndorDriver

global LOGGER
if logging.LOGGER is None:
    LOGGER = logging.make_LOGGER(LOGGER_name="andor_server_standalone")
else:
    LOGGER = logging.LOGGER


class AndorCooling(Executor):
    """Handle cooling and warmup of Andor camera."""
    driver: AndorDriver


class AndorAdjustND(Executor):
    """Auto-select ND filter with maximum optimality."""
    driver: AndorDriver


class AndorExtTrig(Executor):
    """Acquire data with external start trigger."""
    driver: AndorDriver

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            self.poll_rate = 0.1  # pump events every 100 millisecond
            self.start_time = time.time()

            # link attrs for convenience
            self.action_params = self.active.action.action_params
            self.driver = self.active.base.fastapp.driver

            # no external timer, event sink signals end of measurement
            self.duration = -1
            
            self.frame_count = self.action_params["frame_count"]
            self.timeout = self.action_params["timeout"]
            self.buffer_count = self.action_params["buffer_count"]
            
            self.exp_time = self.action_params["exp_time"]
            self.framerate = self.action_params["framerate"]

            LOGGER.info("AndorExec initialized.")
        except Exception:
            LOGGER.error("AndorExec was not initialized.", exc_info=True)

    async def _pre_exec(self) -> dict:
        """Setup potentiostat device for given technique."""
        resp = self.driver.setup_acquisition(exp_time=self.exp_time, framerate=self.framerate)
        error = ErrorCodes.none if resp.response == "success" else ErrorCodes.setup
        return {"error": error}

    async def _exec(self) -> dict:
        """Set external trigger to wait for measurement start."""
        LOGGER.debug("setting external trigger")
        resp = self.driver.set_external_trigger()
        error = ErrorCodes.none if resp.response == "success" else ErrorCodes.critical
        return {"error": error}

    async def _poll(self) -> dict:
        """Return data and status from dtaq event sink."""
        resp = self.driver.get_data()
        # populate executor buffer for output calculation
        for k, v in resp.data.items():
            self.data_buffer[k].extend(v)
        error = ErrorCodes.none if resp.response == "success" else ErrorCodes.critical
        status = HloStatus.active if resp.message != "done" else HloStatus.finished
        return {"error": error, "status": status, "data": resp.data}

    async def _post_exec(self):
        resp = self.driver.cleanup()
        # may want to call disconnect if self.driver.connect() was used in setup or driver init
        self.driver.disconnect()


        # # _post_exec can send one last data message and/or make final calculations and store in action_params
        # # parse calculate outputs from data buffer:
        # for k in ["t_s", "Ewe_V", "I_A"]:
        #     if k in self.data_buffer:
        #         meanv = np.nanmean(np.array(self.data_buffer[k])[-5:])
        #         self.active.action.action_params[f"{k}__mean_final"] = meanv

        # if self.active.action.action_name == "run_OCV":
        #     data_df = pd.DataFrame(self.data_buffer)
        #     rsd_thresh = self.action_params.get("RSD_threshold", 1)
        #     simple_thresh = self.action_params.get("simple_threshold", 1)
        #     signal_change_thresh = self.action_params.get("signal_change_threshold", 1)
        #     amplitude_thresh = self.action_params.get("amplitude_threshold", 1)
        #     has_bubble = bubble_detection(
        #         data_df,
        #         rsd_thresh,
        #         simple_thresh,
        #         signal_change_thresh,
        #         amplitude_thresh,
        #     )
        #     self.active.action.action_params["has_bubble"] = has_bubble

        error = ErrorCodes.none if resp.response == "success" else ErrorCodes.critical
        return {"error": error, "data": {}}

    async def _manual_stop(self) -> dict:
        """Interrupt acquisition."""
        resp = self.driver.stop()
        error = ErrorCodes.none if resp.response == "success" else ErrorCodes.stop
        return {"error": error}


async def andor_dyn_endpoints(app=None):
    server_key = app.base.server.server_name

    # while not app.driver.ready:
    #     LOGGER.info("waiting for andor init")
    #     await asyncio.sleep(1)

    # app.driver.connect()
    # app.driver.disconnect()

    @app.post(f"/{server_key}/acquire_external_trig", tags=["action"])
    async def acquire_external_trig(
        action: Action = Body({}, embed=True),
        action_version: int = 2,
        some_example_param: float = 0.0,
    ):
        active = await app.base.setup_and_contain_action()

        # decide on abbreviated action name
        active.action.action_abbr = "ANDORSPEC"
        executor = AndorExtTrig(active=active, oneoff=False)
        active_action_dict = active.start_executor(executor)
        #
        
        return active_action_dict

    @app.post(f"/{server_key}/cancel_acquire_external_trig", tags=["action"])
    async def cancel_acquire_external_trig(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
    ):
        """Stop sleep action."""
        active = await app.base.setup_and_contain_action()
        for exec_id, executor in app.base.executors.items():
            if exec_id.split()[0] == "acquire_external_trig":
                executor.stop_action_task()
        finished_action = await active.finish()
        return finished_action.as_dict()

def makeApp(confPrefix, server_key, helao_root):

    config = config_loader(confPrefix, helao_root)

    app = BaseAPI(
        config=config,
        server_key=server_key,
        server_title=server_key,
        description="Andor camera/action server",
        version=0.1,
        driver_class=AndorDriver,
        dyn_endpoints=andor_dyn_endpoints,
    )

    @app.post("/stop_private", tags=["private"])
    def stop_private():
        """Calls driver stop method."""
        app.driver.stop()

    return app
