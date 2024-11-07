""" Motion simulation server

FastAPI server host for the motion simulator driver. Currently just sleeps.
TODO: Calculate sleep time using displacement and speed.
"""

__all__ = ["makeApp"]

import asyncio
from typing import Optional, List, Union
from fastapi import Body
import numpy as np
import pandas as pd

from helao.servers.base import Base
from helao.servers.base_api import BaseAPI
from helao.helpers.make_str_enum import make_str_enum
from helao.helpers.premodels import Action
from helao.core.error import ErrorCodes
from helao.helpers.config_loader import config_loader


class MotionSim:
    def __init__(self, action_serv: Base):
        self.base = action_serv
        self.config_dict = action_serv.server_cfg.get("params", {})
        self.world_config = action_serv.world_cfg
        self.present_x = 0
        self.present_y = 0
        pm_cols = ['Sample', 'x', 'y', 'dx', 'dy', 'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'code']
        self.pmdf = pd.read_csv(self.config_dict['platemap_path'], skiprows=2, header=None, names=pm_cols)

    def solid_get_samples_xy(self, plate_id: int, sample_no: int, *args, **kwargs):
        rowmatch = self.pmdf.query(f"Sample=={sample_no}")
        if len(rowmatch)==0:
            self.base.print_message(f"Could not locate sample_no: {sample_no} on plate_id: {plate_id}")
            retxy = [None, None]
        else:
            if len(rowmatch)>1:
                self.base.print_message(f"Found multiple locations matching plate_id: {plate_id}, sample_no: {sample_no}, returning first match.")
            else:
                self.base.print_message(f"Found x,y")
            firstmatch = rowmatch.iloc[0]
            retxy = [float(firstmatch.x), float(firstmatch.y)]
        return {"platexy": retxy}

    def move(self, d_mm: List[float], axis: List[str], speed: int = None):
        pass
    
    def shutdown(self):
        pass


def makeApp(confPrefix, server_key, helao_root):

    config = config_loader(confPrefix, helao_root)

    app = BaseAPI(
        config=config,
        server_key=server_key,
        server_title=server_key,
        description="Motion simulator",
        version=2.0,
        driver_class=MotionSim
    )

    @app.post(f"/{server_key}/solid_get_samples_xy", tags=["action"])
    async def solid_get_samples_xy(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        plate_id: int = None,
        sample_no: int = None,
    ):
        active = await app.base.setup_and_contain_action()
        platexy = app.driver.solid_get_samples_xy(
            **active.action.action_params
        )
        active.action.action_params.update({"_platexy": platexy})
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/move", tags=["action"])
    async def move(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        d_mm: List[float] = [0, 0],
        axis: List[str] = ["x", "y"],
        speed: int = None,
    ):
        """Move a apecified {axis} by {d_mm} distance at {speed} using {mode} i.e. relative.
        Use Rx, Ry, Rz and not in combination with x,y,z only in motorxy.
        No z, Rx, Ry, Rz when platexy selected."""
        active = await app.base.setup_and_contain_action(action_abbr="move")
        await asyncio.sleep(3)
        finished_action = await active.finish()
        return finished_action.as_dict()

    return app
