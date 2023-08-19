import os
import time
import asyncio
import functools

import pyzstd
import _pickle as cPickle

from helaocore.error import ErrorCodes
from helaocore.models.hlostatus import HloStatus

from helao.servers.base import Base, Executor


def decompress_pzstd(fpath):
    data = pyzstd.ZstdFile(fpath, "rb")
    data = cPickle.load(data)
    return data


class OerSim:
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

    def change_plate(self, plate_id):
        if plate_id in self.all_data:
            self.data = self.all_data[plate_id]
            self.base.print_message(f"loaded plate_id: {plate_id}")
            return True
        else:
            self.base.print_message(f"plate_id: {plate_id} does not exist in dataset")
            return False

    def list_plates(self):
        plate_els = [
            (
                pid,
                functools.reduce(
                    lambda x, y: set(x).union(y),
                    [compd["el_str"].split("-") for compd in plated.values()],
                ),
            )
            for pid, plated in self.all_data.items()
            if pid != "els"
        ]
        return {k: sorted(v) for k, v in plate_els}

    def list_addressable(self):
        plate_comps = list(self.data.keys())
        el_vecs = list(zip(*plate_comps))
        return {k: v for k, v in zip(self.all_data["els"], el_vecs)}

    def shutdown(self):
        pass


class OerSimExec(Executor):
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