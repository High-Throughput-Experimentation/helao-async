""" Potentiostat simulation server

FastAPI server host for the potentiostat simulator driver. Currently just sleeps.
TODO: Load and stream old measurements.
"""

__all__ = ["makeApp"]


import asyncio
from typing import Optional, List
from fastapi import Body, Query
from glob import glob
import pandas as pd

from helaocore.server.base import Base
from helaocore.server.base import makeActionServ
from helaocore.model.sample import LiquidSample, SampleUnion
from helaocore.schema import Action
from helaocore.helper.config_loader import config_loader


class PstatSim:
    def __init__(self, action_serv: Base):
        self.base = action_serv
        self.config_dict = action_serv.server_cfg["params"]
        self.world_config = action_serv.world_cfg
        self.measure_status = None
        self.df = pd.read_csv(self.config_dict['data_path'])
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
    
    def shutdown(self):
        pass


def makeApp(confPrefix, servKey, helao_root):

    config = config_loader(confPrefix, helao_root)

    app = makeActionServ(
        config=config,
        server_key=servKey,
        server_title=servKey,
        description="PSTAT simulator",
        version=2.0,
        driver_class=PstatSim
    )

    @app.post(f"/{servKey}/run_CP", tags=["public"])
    async def run_CP(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        Ival: Optional[float] = 0.0,
        Tval__s: Optional[float] = 10.0,
        AcqInterval__s: Optional[float] = 1.0,  # Time between data acquisition samples in seconds.
    ):
        """Chronopotentiometry (Potential response on controlled current)
        use 4bit bitmask for triggers
        IErange depends on gamry model used (test actual limit before using)"""
        active = await app.base.setup_and_contain_action()
        active.action.action_abbr = "CP"
        await asyncio.sleep(active.action.action_params["Tval__s"])
        finished_action = await active.finish()
        return finished_action.as_dict()

    return app
