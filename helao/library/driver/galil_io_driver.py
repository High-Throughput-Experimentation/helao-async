""" A device class for the Galil motion controller, used by a FastAPI server instance.

The 'galil' device class exposes motion and I/O functions from the underlying 'gclib'
library. Class methods are specific to Galil devices. Device configuration is read from
config/config.py. 
"""


import os
import numpy as np
import time
import pathlib
import asyncio
from enum import Enum
from typing import List

from helaocore.server.base import Base
from helaocore.error import ErrorCodes
from helaocore.schema import Action
from helaocore.error import ErrorCodes


driver_path = os.path.dirname(__file__)

# install galil driver first
# (helao) c:\Program Files (x86)\Galil\gclib\source\wrappers\python>python setup.py install
import gclib

# pathlib.Path(os.path.join(helao_root, 'visualizer\styles.css')).read_text()


class cmd_exception(ValueError):
    def __init__(self, arg):
        self.args = arg


class Galil:
    def __init__(self, action_serv: Base):

        self.base = action_serv
        self.config_dict = action_serv.server_cfg["params"]

        if "Din_id" not in self.config_dict:
            self.config_dict["Din_id"] = dict()

        if "Dout_id" not in self.config_dict:
            self.config_dict["Dout_id"] = dict()

        if "Aout_id" not in self.config_dict:
            self.config_dict["Aout_id"] = dict()

        if "Ain_id" not in self.config_dict:
            self.config_dict["Ain_id"] = dict()


        # if this is the main instance let us make a galil connection
        self.g = gclib.py()
        self.base.print_message(f"gclib version: {self.g.GVersion()}")
        # TODO: error checking here: Galil can crash an dcarsh program
        try:
            self.g.GOpen("%s --direct -s ALL" % (self.config_dict["galil_ip_str"]))
            self.base.print_message(self.g.GInfo())
            self.c = self.g.GCommand  # alias the command callable
        except Exception:
            self.base.print_message(
                "severe Galil error ... please power cycle Galil and try again", error = True
            )

        self.cycle_lights = False


    async def reset(self):
        pass


    async def estop(self, switch:bool, *args, **kwargs):
        # this will estop the io
        # set estop: switch=true
        # release estop: switch=false
        self.base.print_message("IO Estop")
        if switch == True:
            await self.break_infinite_digital_cycles()
            await self.digital_out_off(await self.get_all_digital_out())
            await self.set_analog_out(await self.get_all_analoh_out(), 0)
            # set flag
            self.base.actionserver.estop = True
        else:
            # need only to set the flag
            self.base.actionserver.estop = False
        return switch


    async def get_analog_in(self, 
                            port:int,
                            ai_name:str="analog_in",
                            *args,**kwargs):
        err_code = ErrorCodes.none
        ret = None
        if port in self.config_dict["Ain_id"]:
            pID = self.config_dict["Ain_id"][port]
            ret = self.c(f"@AN[{int(pID)}]")
        else:
            err_code = ErrorCodes.not_available

        return {
                "error_code": err_code,
                "port": port,
                "name": ai_name,
                "type": "analog_in",
                "value": ret
               }


    async def get_digital_in(self, 
                             port:int, 
                             di_name:str="digital_in",
                             *args,**kwargs):
        err_code = ErrorCodes.none
        ret = None
        if port in self.config_dict["Din_id"]:
            pID = self.config_dict["Din_id"][port]
            ret = self.c(f"@IN[{int(pID)}]")
        else:
            err_code = ErrorCodes.not_available

        return {
                "error_code": err_code,
                "port": port,
                "name": di_name,
                "type": "digital_in",
                "value": ret
               }


    async def get_digital_out(self, 
                              port:int,
                              do_name:str="digital_out",
                              *args,**kwargs):
        err_code = ErrorCodes.none
        ret = None
        if port in self.config_dict["Dout_id"]:
            pID = self.config_dict["Dout_id"][port]
            ret = self.c(f"@OUT[{int(pID)}]")
        else:
            err_code = ErrorCodes.not_available

        return {
                "error_code": err_code,
                "port": port,
                "name": do_name,
                "type": "digital_out",
                "value": ret
               }


    # def set_analog_out(self, ports, handle: int, module: int, bitnum: int, multi_value):
    async def set_analog_out(self, 
                             port:int, 
                             value:float,
                             ao_name:str="analog_out",
                             *args,**kwargs):
        err_code = ErrorCodes.not_available
        # this is essentially a placeholder for now since the DMC-4143 does not support
        # analog out but I believe it is worthwhile to have this in here for the RIO
        # Handle num is A-H and must be on port 502 for the modbus commons
        # module is the position of the module from 1 to 16
        # bitnum is the IO point in the module from 1-4
        # the fist value n_0
        # n_0 = handle * 1000 + (module - 1) * 4 + bitnum
        # _ = self.c("AO {},{}".format(port, value))
        return {
                "error_code": err_code,
                "port": port,
                "name": ao_name,
                "type": "analog_out",
                "value": None
               }


    async def set_digital_out(self, 
                              port:int, 
                              on:bool, 
                              do_name:str="digital_out",
                              *args,**kwargs):
        err_code = ErrorCodes.none
        on = bool(on)
        ret = None
        if port in self.config_dict["Dout_id"]:
            pID = self.config_dict["Dout_id"][port]
            if on:
                _ = self.c(f"SB {int(pID)}")
            else:
                _ = self.c(f"CB {int(pID)}")
            ret = self.c(f"@OUT[{int(pID)}]")
        else:
            err_code = ErrorCodes.not_available

        return {
                "error_code": err_code,
                "port": port,
                "name": do_name,
                "type": "digital_out",
                "value": ret
               }


    async def upload_DMC(self, DMC_prog):
        self.c("UL;")  # begin upload
        # upload line by line from DMC_prog
        for DMC_prog_line in DMC_prog.split("\n"):
            self.c(DMC_prog_line)
        self.c("\x1a")  # terminator "<cntrl>Z"

    async def set_digital_cycle(self, trigger_port:int, out_port:int, t_cycle:float,*args,**kwargs):
        DMC_prog = pathlib.Path(
            os.path.join(driver_path, "galil_toogle.dmc")
        ).read_text()
        DMC_prog = DMC_prog.format(
            p_trigger=trigger_port, p_output=out_port, t_time=t_cycle
        )
        self.upload_DMC(DMC_prog)
        # self.c("XQ")
        self.c("XQ #main")  # excecute main routine


    async def infinite_digital_cycles(
        self, on_time:float=0.2, off_time:float=0.2, port:int=0, init_time:float=0,*args,**kwargs
    ):
        self.cycle_lights = True
        time.sleep(init_time)
        while self.cycle_lights:
            await self.set_digital_out(port, True)
            time.sleep(on_time)
            await self.set_digital_out(port, False)
            time.sleep(off_time)
        return {
            "ports": port,
            "value": "ran_infinite_light_cycles",
            "type": "digital_out",
        }


    async def break_infinite_digital_cycles(
        self, on_time=0.2, off_time=0.2, port=0, init_time=0
    ):
        self.cycle_lights = False


    def shutdown_event(self):
        # this gets called when the server is shut down or reloaded to ensure a clean
        # disconnect ... just restart or terminate the server
        self.base.print_message("shutting down galil io")
        self.g.GClose()
        return {"shutdown"}
