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

    @app.post(f"/{servKey}/stop")
    async def stop(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
    ):
        """Stops measurement in a controlled way."""
        active = await app.base.setup_and_contain_action(action_abbr="stop")
        await active.enqueue_data_dflt(datadict={"stop": await app.driver.stop()})
        finished_action = await active.finish()
        return finished_action.as_dict()

    return app
