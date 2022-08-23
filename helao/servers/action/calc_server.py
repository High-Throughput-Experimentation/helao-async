""" General calculation server

Calc server is used for in-sequence data processing. 

"""

__all__ = ["makeApp"]

import time
from typing import Optional, List
from fastapi import Body

from helaocore.models.sequence import SequenceModel
from helaocore.models.experiment import ExperimentModel

from helao.helpers.premodels import Action
from helao.servers.base import makeActionServ
from helao.drivers.data.calc_driver import Calc
from helao.helpers.config_loader import config_loader


def makeApp(confPrefix, servKey, helao_root):
    config = config_loader(confPrefix, helao_root)
    app = makeActionServ(
        config=config,
        server_key=servKey,
        server_title=servKey,
        description="Calculation server",
        version=0.1,
        driver_class=Calc,
    )

    @app.post(f"/{servKey}/calc_uvis_basics")
    async def calc_uvis_basics(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        sequence_in: Optional[SequenceModel] = Body({}, embed=True),
    ):
        pass

    return app
