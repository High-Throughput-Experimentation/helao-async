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
        self.loaded_plateid = None
        self.loaded_ph = None
        self.loaded_els = []
        self.loaded_space = []
        self.measured_space = []
        self.df = pd.read_csv(self.config_dict["data_path"])
        self.loaded_df = None
        non_els = [
            "plate_id",
            "Sample",
            "ana",
            "idx",
            "Eta.V_ave",
            "solution_ph",
            "J_mAcm2",
        ]
        plateparams = (
            self.df[non_els]
            .groupby(["plate_id", "solution_ph"])
            .count()
            .reset_index()[["plate_id", "solution_ph"]]
        )
        self.platespaces = []
        for plateid in set(self.df.plate_id):
            self.platespaces.append(
                {
                    "plate_id": plateid,
                    "solution_ph": plateparams.query(
                        f"plate_id=={plateid}"
                    ).solution_ph.to_list()[0],
                    "elements": [
                        k
                        for k, v in (
                            self.df.query(f"plate_id=={plateid}")
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

    def load_plateid(self, plateid: int, *args, **kwargs):
        if plateid == self.loaded_plateid:
            self.base.print_message(f"plate {plateid} is already loaded")
            return False
        if plateid in self.list_plates():
            plated = [d for d in self.platespaces if d["plate_id"] == plateid][0]
            self.loaded_plateid = plateid
            self.loaded_ph = plated["solution_ph"]
            self.loaded_els = plated["elements"]
            self.loaded_df = self.df.query(f"plate_id=={plateid}")
            self.loaded_space = self.loaded_df[self.loaded_els].to_numpy().tolist()
            self.reset()
            return {
                "plateid": self.loaded_plateid,
                "ph": self.loaded_ph,
                "elements": self.loaded_els,
                # "space": self.loaded_space,
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

    def get_loaded_plateid(self):
        return self.loaded_plateid

    def acquire(self, element_fracs: list, *args, **kwargs):
        if element_fracs in self.loaded_space:
            self.measured_space.append(element_fracs)
            sample_no = self.loaded_df.iloc[
                self.loaded_space.index(element_fracs)
            ].Sample
            return sample_no
        else:
            return False


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

    @app.post(f"/{servKey}/load_plateid")
    async def load_plateid(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        plateid: Optional[int] = None,
    ):
        active = await app.base.setup_and_contain_action()
        platedict = app.driver.load_plateid(**active.action.action_params)
        for k, v in platedict.items():
            active.action.action_params.update({f"_{k}": v})
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{servKey}/list_plates")
    async def list_plates(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
    ):
        active = await app.base.setup_and_contain_action()
        platelist = app.driver.list_plates()
        active.action.action_params.update({f"_platelist": platelist})
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{servKey}/list_spaces")
    async def list_spaces(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
    ):
        active = await app.base.setup_and_contain_action()
        platespaces = app.driver.list_spaces()
        active.action.action_params.update({f"_platespaces": platespaces})
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{servKey}/acquire")
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

    @app.post(f"/{servKey}/get_loaded_space")
    async def get_loaded_space(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
    ):
        active = await app.base.setup_and_contain_action()
        fullspace = app.driver.get_loaded_space()
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{servKey}/get_loaded_plateid")
    async def get_loaded_plateid(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
    ):
        active = await app.base.setup_and_contain_action()
        plateid = app.driver.get_loaded_plateid()
        active.action.action_params.update({f"_plateid": plateid})
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{servKey}/get_loaded_ph")
    async def get_loaded_ph(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
    ):
        active = await app.base.setup_and_contain_action()
        ph = app.driver.get_loaded_ph()
        active.action.action_params.update({f"_ph": ph})
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{servKey}/get_loaded_elements")
    async def get_loaded_elements(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
    ):
        active = await app.base.setup_and_contain_action()
        elements = app.driver.get_loaded_elements()
        active.action.action_params.update({f"_elements": elements})
        finished_action = await active.finish()
        return finished_action.as_dict()

    return app
