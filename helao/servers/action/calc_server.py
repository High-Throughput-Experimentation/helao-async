""" General calculation server

Calc server is used for in-sequence data processing. 

"""

__all__ = ["makeApp"]

import time
from typing import Optional, List
from fastapi import Body

from helaocore.models.sample import SampleUnion
from helaocore.models.file import HloHeaderModel

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
    return app
