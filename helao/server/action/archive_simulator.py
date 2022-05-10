""" Archive simulation server

FastAPI server host for the archive simulator driver. Loads historical data.
TODO: Return addressable space, measured, and unmeasured positions.
"""

__all__ = ["makeApp"]


from typing import Optional, List, Union
from fastapi import Body
import numpy as np
import pandas as pd

from helaocore.server.base import Base
from helaocore.server.base import makeActionServ
from helaocore.helper.make_str_enum import make_str_enum
from helaocore.schema import Action
from helaocore.error import ErrorCodes
from helaocore.helper.config_loader import config_loader


class ArchiveSim:
    def __init__(self, action_serv: Base):
        self.base = action_serv
        self.config_dict = action_serv.server_cfg["params"]
        self.world_config = action_serv.world_cfg
        self.loaded_plate_id = None
        self.loaded_ph = None
        self.loaded_els = []
        self.loaded_space = []
        self.measured_space = []
        self.df = pd.read_csv(self.config_dict["data_path"])
        self.loaded_df = None
        non_els = [
            "plate_id",
            "Sample",
            "solution_ph",
            "EtaV_CP3",
            "EtaV_CP10",
        ]
        plateparams = (
            self.df[non_els]
            .groupby(["plate_id", "solution_ph"])
            .count()
            .reset_index()[["plate_id", "solution_ph"]]
        )
        self.platespaces = []
        for plate_id in set(self.df.plate_id):
            self.platespaces.append(
                {
                    "plate_id": plate_id,
                    "solution_ph": plateparams.query(
                        f"plate_id=={plate_id}"
                    ).solution_ph.to_list()[0],
                    "elements": [
                        k
                        for k, v in (
                            self.df.query(f"plate_id=={plate_id}")
                            .drop(non_els, axis=1)
                            .sum(axis=0)
                            > 0
                        ).items()
                        if v > 0
                    ],
                }
            )

    def reset(self):
        self.measured_space = []

    def load_plate_id(self, plate_id: int, *args, **kwargs):
        if plate_id == self.loaded_plate_id:
            self.base.print_message(f"plate {plate_id} is already loaded")
            return False
        if plate_id in self.list_plates():
            plated = [d for d in self.platespaces if d["plate_id"] == plate_id][0]
            self.loaded_plate_id = plate_id
            self.loaded_ph = plated["solution_ph"]
            self.loaded_els = plated["elements"]
            self.loaded_df = self.df.query(f"plate_id=={plate_id}")
            self.loaded_space = self.loaded_df[self.loaded_els].to_numpy().tolist()
            self.reset()
            return {
                "plate_id": self.loaded_plate_id,
                "ph": self.loaded_ph,
                "elements": self.loaded_els,
                "space": self.loaded_space,
            }
        else:
            return False

    def list_spaces(self):
        return self.platespaces

    def list_plates(self):
        return [d["plate_id"] for d in self.platespaces]

    def get_acquired(self):
        return self.measured_space

    def reset_acquired(self):
        self.reset()
        return {"detail": "driver.measured_space was reset to []"}

    def get_loaded_elements(self):
        return self.loaded_els

    def get_loaded_space(self):
        return self.loaded_space

    def get_loaded_ph(self):
        return self.loaded_ph

    def get_loaded_plate_id(self):
        return self.loaded_plate_id

    def acquire(self, element_fracs: list, *args, **kwargs):
        if element_fracs in self.loaded_space:
            match = self.loaded_df.iloc[self.loaded_space.index(element_fracs)]
            sample_no = int(match.Sample)
            eta3 = float(match.EtaV_CP3)
            eta10 = float(match.EtaV_CP10)
            acq_dict = {k: v for k,v in zip(self.loaded_els, element_fracs)}
            acq_dict.update({"solution_ph": self.loaded_ph, "eta3": eta3, "eta10": eta10})
            self.measured_space.append(acq_dict)
            return sample_no
        else:
            return False

    def shutdown(self):
        pass


def makeApp(confPrefix, servKey, helao_root):

    config = config_loader(confPrefix, helao_root)

    app = makeActionServ(
        config=config,
        server_key=servKey,
        server_title=servKey,
        description="Archive simulator",
        version=2.0,
        driver_class=ArchiveSim,
    )

    
    # PRIVATE ENDPOINTS (not managed by Orch)

    @app.post(f"/list_plates", tags=["private"])
    def list_plates():
        platelist = app.driver.list_plates()
        return platelist

    @app.post(f"/list_all_spaces", tags=["private"])
    def list_all_spaces():
        platespaces = app.driver.list_spaces()
        return platespaces

    @app.post(f"/get_measured", tags=["private"])
    def get_measured():
        measured = app.driver.get_acquired()
        return measured

    @app.post(f"/clear_measured", tags=["private"])
    def get_measured():
        result = app.driver.reset_acquired()
        return result

    @app.post(f"/get_loaded_space", tags=["private"])
    async def get_loaded_space():
        fullspace = app.driver.get_loaded_space()
        return fullspace

    @app.post(f"/get_loaded_plate_id", tags=["private"])
    async def get_loaded_plate_id():
        plate_id = app.driver.get_loaded_plate_id()
        return plate_id

    @app.post(f"/get_loaded_ph", tags=["private"])
    async def get_loaded_ph():
        ph = app.driver.get_loaded_ph()
        return ph

    @app.post(f"/get_loaded_elements", tags=["private"])
    async def get_loaded_elements():
        elements = app.driver.get_loaded_elements()
        return elements


    # BEGIN PUBLIC ENDPOINTS (Actions dispatched by Orch)

    @app.post(f"/{servKey}/load_space", tags=["public"])
    async def load_space(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        plate_id: int = 0,
    ):
        active = await app.base.setup_and_contain_action()
        platedict = app.driver.load_plate_id(plate_id=plate_id)
        for k, v in platedict.items():
            active.action.action_params.update({f"_{k}": v})
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{servKey}/query_plate", tags=["public"])
    async def query_plate(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        elements: Optional[List[str]] = [],
        ph: Optional[int] = 13,
    ):
        active = await app.base.setup_and_contain_action()
        platespaces = app.driver.list_spaces()
        if ph is not None:
            platespaces = [
                x
                for x in platespaces
                if x["solution_ph"] == ph and sorted(x["elements"]) == sorted(elements)
            ][0]
        active.action.action_params.update(
            {
                "_elements": platespaces["elements"],
                "_plate_id": platespaces["plate_id"],
            }
        )
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{servKey}/acquire", tags=["public"])
    async def acquire(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        element_fracs: Optional[List[int]] = [],
    ):
        active = await app.base.setup_and_contain_action()
        sample_no = app.driver.acquire(**active.action.action_params)
        active.action.action_params.update({f"_sampleno": sample_no})
        finished_action = await active.finish()
        return finished_action.as_dict()

    return app
