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
from typing import Optional

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
        self.pump_tasks = {k: None for k in self.config_dict.get("pumps", {}).keys()}

        # read pump addr and strings from config dict
        self.com = serial.Serial(
            port=self.config_dict["port"],
            baudrate=115200,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.05,
            xonxoff=False,
            rtscts=False,
        )
        self.sio = io.TextIOWrapper(io.BufferedRWPair(self.com, self.com))
        self.safe_state()

        self.aloop = asyncio.get_running_loop()
        self.polling = True
        self.poll_signalq = asyncio.Queue(1)
        self.poll_signal_task = self.aloop.create_task(self.poll_signal_loop())
        self.polling_task = self.aloop.create_task(self.poll_sensor_loop())

    async def start_polling(self):
        await self.poll_signalq.put(True)

    async def stop_polling(self):
        await self.poll_signalq.put(False)

    async def poll_signal_loop(self):
        while True:
            self.polling = await self.poll_signalq.get()

    def send(self, pump_name: str, cmd: str):
        if not cmd.endswith("\r"):
            cmd = cmd + "\r"
        addr = self.config_dict["pumps"][pump_name]["address"]
        command_str = f"{addr:02}@{cmd}"
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

    async def poll_sensor_loop(self, frequency: int = 5):
        waittime = 1.0 / frequency
        lastupdate = 0
        while True:
            if self.polling:
                for plab, pdict in self.config_dict.get("pumps", {}).items():
                    checktime = time.time()
                    if checktime - lastupdate < waittime:
                        await asyncio.sleep(waittime - (checktime - lastupdate))
                    addr = pdict["address"]
                    status_resp = self.send(plab, "status")
                    lastupdate = time.time()
                    status = status_resp[0]
                    addrstate_rate, pumptime, pumpvol, flags = status.split()
                    raddr = int(addrstate_rate[:2])
                    if int(addr) == int(raddr):
                        state = [
                            v
                            for k, v in STATES.items()
                            if addrstate_rate[2:].startswith("k")
                        ][0]
                        rate = int(addrstate_rate.split(state)[-1])
                        pumptime = int(pumptime)
                        pumpvol = int(pumpvol)
                        (
                            motor_dir,
                            limit_status,
                            stall_status,
                            trig_input,
                            dir_port,
                            target_reached,
                        ) = flags.lower()
                        status_dict = {
                            "pump_address": addr,
                            "status": state,
                            "rate_fL": rate,
                            "pump_time_ms": pumptime,
                            "pump_volume_fL": pumpvol,
                            "motor_direction": motor_dir,
                            "limit_switch_state": limit_status,
                            "stall_status": stall_status,
                            "trigger_input_state": trig_input,
                            "direction_port": dir_port,
                            "target_reached": target_reached,
                        }
                        await self.base.put_lbuf(status_dict)
                        self.base.print_message(status_dict)
            else:
                await asyncio.sleep(0.05)

    def start_pump(self, pump_name: str, direction: int):
        "Start motion in direction forward/infuse (1) or reverse/withdraw (-1)"
        if direction == 1:
            cmd = "irun"
        elif direction == -1:
            cmd = "wrun"
        else:
            return False
        resp = self.send(pump_name, cmd)
        return resp

    def set_force(self, pump_name: str, force_val: int):
        "Set infusion force value in percentage"
        cmd = f"forc {force_val}"
        resp = self.send(pump_name, cmd)
        return resp

    def set_rate(self, pump_name: str, rate_val: float, direction: int):
        "Set infusion|withdraw rate in units TODO"
        if direction == 1:
            cmd = "irate"
        elif direction == -1:
            cmd = "wrate"
        else:
            return False
        resp = self.send(pump_name, cmd)
        return resp

    def set_ramp(self, pump_name: str, start_rate: int, end_rate: int, direction: int):
        "Set infusion|withdraw ramp rate in units TODO"
        pass

    def set_volume(self, pump_name: str, vol_val: float, direction: int):
        pass

    def clear_time(self, pump_name: Optional[str] = None, direction: Optional[int] = 0):
        if direction == 1:
            cmd = "citime"
        elif direction == -1:
            cmd = "cwtime"
        else:
            cmd = "ctime"
        if pump_name is None:
            for cpump_name in self.config_dict.get("pump_addrs", {}).keys():
                _ = self.send(cpump_name, cmd)
            return []
        else:
            resp = self.send(pump_name, cmd)
            return resp

    def clear_volume(
        self, pump_name: Optional[str] = None, direction: Optional[int] = 0
    ):
        if direction == 1:
            cmd = "civolume"
        elif direction == -1:
            cmd = "cwvolume"
        else:
            cmd = "cvolume"
        if pump_name is None:
            for cpump_name in self.config_dict.get("pump_addrs", {}).keys():
                _ = self.send(cpump_name, cmd)
            return []
        else:
            resp = self.send(pump_name, cmd)
            return resp

    def stop_pump(self, pump_name: Optional[str] = None):
        cmd = "stp"
        if pump_name is None:
            for cpump_name in self.config_dict.get("pump_addrs", {}).keys():
                _ = self.send(cpump_name, cmd)
            return []
        else:
            resp = self.send(pump_name, cmd)
            return resp

    def safe_state(self):
        for plab, addr in self.config_dict.get("pump_addrs", {}).items():
            idle_resp = f"{addr:02}:\x11"
            poll_resp = self.send(plab, "poll on")
            if poll_resp[-1] != idle_resp:
                self.base.print_message(f"Error setting pump '{plab}' to 'POLL on'.")
            nvram_resp = self.send(plab, "nvram off")
            if nvram_resp[-1] != idle_resp:
                self.base.print_message(f"Error setting pump '{plab}' to 'NVRAM off'.")
            stop_resp = self.stop_pump(plab)
            if stop_resp[-1] != idle_resp:
                self.base.print_message(f"Error stopping pump '{plab}'.")
            cleartime_resp = self.clear_time(plab)
            if cleartime_resp[-1] != idle_resp:
                self.base.print_message(
                    f"Error clearing time params for pump '{plab}'."
                )
            clearvol_resp = self.clear_volume(plab)
            if clearvol_resp[-1] != idle_resp:
                self.base.print_message(
                    f"Error clearing volume params for pump '{plab}'."
                )

    def shutdown(self):
        # this gets called when the server is shut down
        # or reloaded to ensure a clean
        # disconnect ... just restart or terminate the server
        self.base.print_message("shutting down syringe pump(s)")
        self.safe_state()
        self.com.close()
