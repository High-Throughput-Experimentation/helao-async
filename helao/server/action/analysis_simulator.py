""" Archive simulation server

FastAPI server host for the analysis simulator driver. Loads historical data.
TODO: Returns FOM.
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


class AnalysisSim:
    def __init__(self, action_serv: Base):
        self.base = action_serv
        self.config_dict = action_serv.server_cfg["params"]
        self.world_config = action_serv.world_cfg
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
            
    def calc_cpfom(self, plate_id:int, sample_no:int, ph:int, jmacm2:int, *args, **kwargs):
        match = self.df.query(f"plate_id=={plate_id} & Sample=={sample_no} & solution_ph=={ph}")
        eta = float(match[f"EtaV_CP{jmacm2}"].iloc[0])
        return eta
    
    def shutdown(self):
        pass


def makeApp(confPrefix, servKey, helao_root):

    config = config_loader(confPrefix, helao_root)

    app = makeActionServ(
        config=config,
        server_key=servKey,
        server_title=servKey,
        description="Analysis simulator",
        version=2.0,
        driver_class=AnalysisSim
    )

    @app.post(f"/{servKey}/calc_cpfom", tags=["public"])
    async def calc_cpfom(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        plate_id: int = 0,
        sample_no: int = 0,
        ph: int = 0,
        jmacm2: int = 3
    ):
        """Calculate Eta vs O2/H2O potential."""
        active = await app.base.setup_and_contain_action()
        eta = app.driver.calc_cpfom(**active.action.action_params)
        active.action.action_params.update({f"_eta": eta})
        finished_action = await active.finish()
        return finished_action.as_dict()

    return app
