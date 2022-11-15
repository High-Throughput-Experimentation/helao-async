""" A device class for the SprintIR-6S CO2 sensor.

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


class Legato:
    def __init__(self, action_serv: Base):

        self.base = action_serv
        self.config_dict = action_serv.server_cfg["params"]
        self.unified_db = UnifiedSampleDataAPI(self.base)

        self.bokehapp = None
        self.pump_tasks = {k: None for k in self.config_dict["pump_addrs"].values()}

        # read pump addr and strings from config dict
        self.com = serial.Serial(
            port=self.config_dict["port"],
            baudrate=9600,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.1,
            xonxoff=False,
            rtscts=False,
        )
        self.sio = io.TextIOWrapper(io.BufferedRWPair(self.com, self.com))

        # set POLL to on for all pumps
        # clear time and volume, issue stop for all pumps
        # disable writes to NVRAM? faster response but no recovery

    def send(self, command_str: str):
        if not command_str.endswith("\r\n"):
            command_str = command_str + "\r\n"
        self.sio.write(command_str)
        self.sio.flush()
        resp = [x.strip() for x in self.sio.readlines() if x.strip()]
        # look for "\x11" end of response character when POLL is on
        if resp:
            while not resp[-1].endswith("\x11"):
                time.sleep(0.1)  # wait 100 msec and re-read, response
                newlines = [x.strip() for x in self.sio.readlines() if x.strip()]
                resp += newlines
        return resp