""" Motion simulation server

FastAPI server host for the websocket simulator driver.

"""

__all__ = ["makeApp"]

import time
import asyncio
from typing import Optional, List, Union
from fastapi import Body
import numpy as np

from helao.core.error import ErrorCodes
from helao.core.models.hlostatus import HloStatus
from helao.core.models.sample import AssemblySample, LiquidSample, GasSample,SolidSample, NoneSample

from helao.helpers import logging
if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER

from helao.servers.base import Base, Executor
from helao.servers.base_api import BaseAPI
from helao.helpers.premodels import Action
from helao.helpers.config_loader import config_loader


class WsSim:
    def __init__(self, action_serv: Base):
        self.base = action_serv
        self.config_dict = action_serv.server_cfg.get("params", {})
        self.world_config = action_serv.world_cfg
        self.scale_map = {
            f"series_{i}": v for i, v in enumerate([1, 2, 5, 10, 50, 100])
        }

        self.event_loop = asyncio.get_event_loop()
        self.polling_task = self.event_loop.create_task(self.poll_data_loop())

    async def poll_data_loop(self, frequency_hz: float = 10):
        waittime = 1.0 / frequency_hz
        LOGGER.info("Starting polling loop")
        while True:
            data_msg = {k: v * np.random.uniform() for k, v in self.scale_map.items()}
            await self.base.put_lbuf({"sim_dict": data_msg})
            await asyncio.sleep(waittime)

    def shutdown(self):
        pass

class WsExec(Executor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        LOGGER.info("WsExec initialized.")
        self.start_time = time.time()
        self.duration = self.active.action.action_params.get("duration", -1)

    async def _poll(self):
        """Read data from live buffer."""
        live_dict = {}
        sim_dict, epoch_s = self.active.base.get_lbuf("sim_dict")
        live_dict["epoch_s"] = epoch_s
        live_dict.update(sim_dict)
        iter_time = time.time()
        elapsed_time = iter_time - self.start_time
        if (self.duration < 0) or (elapsed_time < self.duration):
            status = HloStatus.active
        else:
            status = HloStatus.finished
        await asyncio.sleep(0.01)
        return {
            "error": ErrorCodes.none,
            "status": status,
            "data": live_dict,
        }

def makeApp(confPrefix, server_key, helao_root):
    config = config_loader(confPrefix, helao_root)

    app = BaseAPI(
        config=config,
        server_key=server_key,
        server_title=server_key,
        description="Websocket simulator",
        version=1.0,
        driver_class=WsSim,
    )

    @app.post(f"/{server_key}/acquire_data", tags=["action"])
    async def acquire_data(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        duration: float = -1,
        acquisition_rate: float = 0.2,
        fast_samples_in: List[Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
] = Body([], embed=True),
    ):
        """Record simulated data."""
        active = await app.base.setup_and_contain_action()
        active.action.action_abbr = "WsSim"
        executor = WsExec(
            active=active,
            oneoff=False,
            poll_rate=active.action.action_params["acquisition_rate"],
        )
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{server_key}/cancel_acquire_data", tags=["action"])
    async def cancel_acquire_data(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
    ):
        """Stop running acquire_data."""
        active = await app.base.setup_and_contain_action()
        for exec_id, executor in app.base.executors.items():
            if exec_id.split()[0] == "acquire_data":
                executor.stop_action_task()
        finished_action = await active.finish()
        return finished_action.as_dict()

    return app
