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

""" Notes:

Setup polling task to populate base.live_buffer dictionary, record CO2 action will read
from dictionary.

TODO: send CO2 reading to bokeh visualizer w/o writing data

"""


class SprintIR:
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

        # set POLL and flush present buffer until empty
        self.com.write(b"K 2\r\n")
        self.com.flush()
        buf = self.com.read_all()
        while not buf == b"":
            buf = self.com.read_all()
            
        myloop = asyncio.get_event_loop()
        self.polling_task = myloop.create_task(self.poll_sensor_loop())

    def send(self, command_str: str):
        if not command_str.endswith("\r\n"):
            command_str = command_str + "\r\n"
        self.sio.write(command_str)
        self.sio.flush()
        lines = self.sio.readlines()
        cmd_resp = []
        aux_resp = []
        for line in lines:
            strip = line.strip()
            if strip.startswith(command_str[0]):
                cmd_resp.append(strip)
            else:
                aux_resp.append(strip)
        if aux_resp:
            self.base.print_message(f"Received auxiliary responses: {aux_resp}", warning=True)
        while not cmd_resp:
            cmd_resp += self.send(command_str)
        return cmd_resp
    
    async def poll_sensor_loop(self, frequency: int = 20):
        waittime = 1.0 / frequency
        while True:
            co2_level = self.send("Z")[0]
            await self.base.put_lbuf({'co2_sensor': co2_level[0]})
            await asyncio.sleep(waittime)

