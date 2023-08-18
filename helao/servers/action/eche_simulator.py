""" CP simulation server

FastAPI server host for the websocket simulator driver.

"""

__all__ = ["makeApp"]

import time
import asyncio
from typing import Optional, List, Union
from fastapi import Body
import numpy as np

from helaocore.error import ErrorCodes
from helaocore.models.hlostatus import HloStatus
from helaocore.models.sample import SampleUnion

from helao.servers.base import Base, BaseAPI, Executor
from helao.helpers.premodels import Action
from helao.helpers.config_loader import config_loader


class EcheSim:
    def __init__(self, action_serv: Base):
        self.base = action_serv
        self.config_dict = action_serv.server_cfg["params"]
        self.world_config = action_serv.world_cfg
        self.loaded_plate = self.config_dict["plate_id"]

        self.event_loop = asyncio.get_event_loop()

    def shutdown(self):
        pass

class EcheSimExec(Executor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.active.base.print_message("WsExec initialized.")
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
        await asyncio.sleep(0.001)
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
        driver_class=EcheSim,
    )

    @app.post(f"/{server_key}/measure_cp", tags=["action"])
    async def acquire_data(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        duration: float = -1,
        acquisition_rate: float = 0.2,
        fast_samples_in: List[SampleUnion] = Body([], embed=True),
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
