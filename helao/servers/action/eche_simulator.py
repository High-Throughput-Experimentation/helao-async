""" CP simulation server

FastAPI server host for the OER screening simulator.

Loads a subset of 3 mA/cm2 CP measurement data from https://doi.org/10.1039/C8MH01641K

"""

__all__ = ["makeApp"]

import os
import time
import asyncio
from typing import List
from fastapi import Body

import pyzstd
import _pickle as cPickle

from helaocore.error import ErrorCodes
from helaocore.models.hlostatus import HloStatus

from helao.servers.base import Base, Executor
from helao.servers.base_api import BaseAPI
from helao.helpers.premodels import Action
from helao.helpers.config_loader import config_loader


def decompress_pzstd(fpath):
    data = pyzstd.ZstdFile(fpath, "rb")
    data = cPickle.load(data)
    return data


class EcheSim:
    def __init__(self, action_serv: Base):
        self.base = action_serv
        self.config_dict = action_serv.server_cfg["params"]
        self.world_config = action_serv.world_cfg
        self.loaded_plate = self.config_dict["plate_id"]
        self.data_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "demos",
            "data",
            "oer13_cps.pzstd",
        )
        self.all_data = decompress_pzstd(self.data_file)
        self.data = self.all_data[self.loaded_plate]

        self.event_loop = asyncio.get_event_loop()

    def shutdown(self):
        pass


class EcheSimExec(Executor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.active.base.print_message("EcheSimExec initialized.")
        self.last_idx = 0
        self.start_time = time.time()  # instantiation time
        self.duration = self.active.action.action_params.get("duration", -1)
        self.sample_data = self.active.base.driver.data[
            tuple(self.active.action_params["comp_vec"])
        ]
        self.cp = self.sample_data["CP3"]
        self.els = self.sample_data["el_str"].split("-")
        self.fracs = [self.sample_data[el] for el in self.els]

    async def _exec(self):
        self.start_time = time.time()  # pre-polling iteration time
        data = {"elements": self.els, "atfracs": self.fracs}
        return {"data": data, "error": ErrorCodes.none}

    async def _poll(self):
        """Read data from live buffer."""
        elapsed_time = time.time() - self.start_time
        new_idx = max([i for i, v in enumerate(self.cp["t_s"]) if v < elapsed_time])
        live_dict = {k: v[self.last_idx : new_idx] for k, v in self.cp.items()}
        self.last_idx = new_idx
        if self.last_idx == new_idx:
            status = HloStatus.finished
        else:
            status = HloStatus.active
        await asyncio.sleep(0.001)
        return {
            "error": ErrorCodes.none,
            "status": status,
            "data": live_dict,
        }

    async def _post_exec(self):
        # calculate final 4-second eta mean and pass to params
        thresh_ts = max(self.cp["t_s"]) - 4
        thresh_idx = min([i for i, v in enumerate(self.cp["t_s"]) if v > thresh_ts])
        erhes = self.cp["erhe_v"][thresh_idx:]
        eta_mean = sum(erhes) / len(erhes) - 1.23
        self.active.action.action_params["mean_eta_vrhe"] = eta_mean
        return {"error": ErrorCodes.none}


def makeApp(confPrefix, server_key, helao_root):
    config = config_loader(confPrefix, helao_root)

    app = BaseAPI(
        config=config,
        server_key=server_key,
        server_title=server_key,
        description="OER CP simulator",
        version=1.0,
        driver_class=EcheSim,
    )

    @app.post(f"/{server_key}/measure_cp", tags=["action"])
    async def measure_cp(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        comp_vec: List[float] = [],
        acquisition_rate: float = 0.2,
    ):
        """Record simulated data."""
        active = await app.base.setup_and_contain_action()
        active.action.action_abbr = "EcheCPSim"
        executor = EcheSimExec(
            active=active,
            oneoff=False,
            poll_rate=active.action.action_params["acquisition_rate"],
        )
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{server_key}/cancel_measure_cp", tags=["action"])
    async def cancel_measure_cp(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
    ):
        """Stop running measure_cp."""
        active = await app.base.setup_and_contain_action()
        for exec_id, executor in app.base.executors.items():
            if exec_id.split()[0] == "measure_cp":
                executor.stop_action_task()
        finished_action = await active.finish()
        return finished_action.as_dict()

    return app
