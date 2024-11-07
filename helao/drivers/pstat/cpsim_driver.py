import os
import time
import asyncio
import functools

from helao.core.error import ErrorCodes
from helao.core.models.hlostatus import HloStatus
from helao.helpers.zstd_io import unzpickle
from helao.servers.base import Base
from helao.helpers.executor import Executor
from helao.drivers.data.gpsim_driver import calc_eta


class CPSim:
    def __init__(self, action_serv: Base):
        self.base = action_serv
        self.config_dict = action_serv.server_cfg.get("params", {})
        self.world_config = action_serv.world_cfg
        self.loaded_plate = self.config_dict["plate_id"]
        self.data_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))),
            "demos",
            "data",
            "oer13_cps.pzstd",
        )
        self.all_data = unzpickle(self.data_file)
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

    def list_addressable(self, limit: int = 10, by_el: bool = False):
        plate_comps = list(self.data.keys())[:limit]
        if by_el:
            el_vecs = list(zip(*plate_comps))
            return {k: v for k, v in zip(self.all_data["els"], el_vecs)}
        else:
            return [self.all_data["els"]] + plate_comps

    def shutdown(self):
        pass


class CPSimExec(Executor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.active.base.print_message("EcheSimExec initialized.")
        self.last_idx = 0
        self.start_time = time.time()  # instantiation time
        self.duration = self.active.action.action_params.get("duration", -1)
        self.sample_data = self.active.base.fastapp.driver.data[
            tuple(self.active.action.action_params["comp_vec"])
        ]
        self.cp = self.sample_data["CP3"]
        self.els = self.sample_data["el_str"].split("-")
        self.fracs = [self.sample_data[el] for el in self.els]

    async def _exec(self):
        self.start_time = time.time()  # pre-polling iteration time
        data = {"elements": self.els, "atfracs": self.fracs}
        data.update({k: [] for k in self.cp})
        return {"data": data, "error": ErrorCodes.none}

    async def _poll(self):
        """Read data from live buffer."""
        elapsed_time = time.time() - self.start_time
        new_idxs = [i for i, v in enumerate(self.cp["t_s"]) if v < elapsed_time]
        status = HloStatus.active
        live_dict = {}
        if new_idxs:
            newest_idx = max(new_idxs)
            live_dict = {k: v[self.last_idx : newest_idx] for k, v in self.cp.items()}
            self.last_idx = newest_idx
            if newest_idx == len(self.cp["t_s"]) - 1:
                status = HloStatus.finished
        await asyncio.sleep(0.001)
        return {
            "error": ErrorCodes.none,
            "status": status,
            "data": live_dict,
        }

    async def _post_exec(self):
        # calculate final 4-second eta mean and pass to params
        self.active.action.action_params["mean_eta_vrhe"] = calc_eta(self.cp)
        return {"error": ErrorCodes.none}
