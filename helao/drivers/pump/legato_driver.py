""" A device class for the KD Scientific Legato 100 series syringe pump.

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

Supported operation modes:
1. volume input + rate/ramp input
2. time input + rate/ramp input

Supported volume units:
ml, ul, nl pl

Supported rate units:
ml, ul, nl, pl / Hr, Min, Sec

Prompt statuses:
: (idle)
> (infusing)
< (withdrawing)
* (stalled)
T* (target reached)


General workflow:
1. load inject | withdraw program (load qs i | load qs w)
2. clear time
3. clear volume
4. set syringe volume
5. set rate | ramp
6. set target time | volume
7. run inject | withdraw
8. poll status flags or promp
9. issue manual stop

Try polling task for updating base.live_buffer dictionary

TODO: if polling task works, send pump status (position?) to bokeh visualizer w/o write

"""

STATES = {
    ":": "idle",
    ">": "infusing",
    "<": "withdrawing",
    "*": "stalled",
    "T*": "target reached",
}


class KDS100:
    def __init__(self, action_serv: Base):

        self.base = action_serv
        self.config_dict = action_serv.server_cfg["params"]
        self.unified_db = UnifiedSampleDataAPI(self.base)

        self.bokehapp = None
        self.pump_tasks = {k: None for k in self.config_dict["pump_addrs"].values()}

        # read pump addr and strings from config dict
        self.com = serial.Serial(
            port=self.config_dict["port"],
            baudrate=115200,
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
        if not command_str.endswith("\r"):
            command_str = command_str + "\r"
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

    def start_pump(self, pump_name: str, direction: int):
        "Start motion in direction forward/infuse (1) or reverse/withdraw (-1)"
        if direction == 1:
            cmd = "irun"
        elif direction == -1:
            cmd = "wrun"
        else:
            return False
        addr = self.config_dict["pump_addrs"][pump_name]
        command_str = f"{addr:02}@{cmd}\r"
        resp = self.send(command_str)
        return resp

    def set_force(self, pump_name: str, force_val: int):
        "Set infusion force value in percentage"
        addr = self.config_dict["pump_addrs"][pump_name]
        command_str = f"{addr:02}@forc {force_val}\r"
        resp = self.send(command_str)
        return resp

    def set_rate(self, pump_name: str, rate_val: int, direction: int):
        "Set infusion|withdraw rate in units TODO"
        if direction == 1:
            cmd = "irate"
        elif direction == -1:
            cmd = "wrate"
        else:
            return False
        addr = self.config_dict["pump_addrs"][pump_name]
        command_str = f"{addr:02}@{cmd} {rate_val}\r"  # TODO: units
        resp = self.send(command_str)
        return resp

    def set_ramp(self, pump_name: str, start_rate: int, end_rate: int, direction: int):
        "Set infusion|withdraw ramp rate in units TODO"
        pass

    def shutdown(self):
        # this gets called when the server is shut down
        # or reloaded to ensure a clean
        # disconnect ... just restart or terminate the server
        self.base.print_message("shutting down syringe pump(s)")
        for addr in self.config_dict["pump_addrs"].values():
            _ = self.send(f"{addr:02}@stop\r")
        self.com.close()
