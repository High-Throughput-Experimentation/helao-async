""" A device class for the KD Scientific Legato pump, used by a FastAPI server instance.

"""

__all__ = []

import numpy as np
import time
import asyncio
from functools import partial
import json
import os
from socket import gethostname
from copy import deepcopy
import traceback

from bokeh.server.server import Server
from helao.servers.base import Base
from helaocore.error import ErrorCodes
from helao.helpers.premodels import Action
from helao.helpers.make_vis_serv import makeVisServ
from helao.helpers.sample_api import UnifiedSampleDataAPI
from helao.helpers.active_params import ActiveParams
from helaocore.models.file import FileConnParams
from helaocore.models.sample import SolidSample

import serial
import io


""" Notes:

Setup serial connection with pyserial module:
```
ser = serial.Serial(port='COM8', baudrate=115200, timeout=0.1)
sio = io.TextIOWrapper(io.BufferedRWPair(ser,ser))
sio.write("00@addr\r")
sio.flush()
resp = sio.readlines()
ser.close()
```
"""


class Legato:
    def __init__(self, action_serv: Base):

        self.base = action_serv
        self.config_dict = action_serv.server_cfg["params"]
        self.unified_db = UnifiedSampleDataAPI(self.base)

        self.motor_busy = False
        self.bokehapp = None
        
        # read pump addr and strings from config dict
        # hold serial connections in self.coms
        self.coms = None
    
    def set_direction(self, pump_addr: int, direction: int):
        "Set motion direction forward (1) or reverse (-1)"
        pass

    def set_force(self, pump_addr: int, force_val: int):
        "Set infusion force value in percentage"
        pass
    
    def set_rate(self, pump_addr: int, rate_val: int, direction: int):
        "Set infusion|withdraw rate in units TODO"
        pass

    def set_ramp(self, pump_addr: int, start_rate:int, end_rate: int, direction: int):
        "Set infusion|withdraw ramp rate in unites TODO"
        pass

    def shutdown(self):
        # this gets called when the server is shut down
        # or reloaded to ensure a clean
        # disconnect ... just restart or terminate the server
        self.base.print_message("shutting down syringe pump")