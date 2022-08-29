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

    @app.post(f"/{servKey}/calc_uvis_abs")
    async def calc_uvis_abs(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        ev_parts: list = [1.5, 2.0, 2.5, 3.0],
        bin_width: int = 3,
        window_length: int = 45,
        poly_order: int = 4,
        lower_wl: float = 370,
        upper_wl: float = 1020,
    ):
        active = await app.base.setup_and_contain_action(action_abbr="calcAbs")
        datadict = app.driver.calc_uvis_abs(active)
        await active.enqueue_data_dflt(datadict=datadict)
        finished_action = await active.finish()
        return finished_action.as_dict()

    return app
