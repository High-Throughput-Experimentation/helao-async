""" A device class for the Galil motion controller, used by a FastAPI server instance.

The 'galil' device class exposes motion and I/O functions from the underlying 'gclib'
library. Class methods are specific to Galil devices. Device configuration is read from
config/config.py. 
"""

__all__ = [
            "Galil",
            "TriggerType",
          ]


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
from helaocore.helper.make_str_enum import make_str_enum


driver_path = os.path.dirname(__file__)

# install galil driver first
# (helao) c:\Program Files (x86)\Galil\gclib\source\wrappers\python>python setup.py install
import gclib

# pathlib.Path(os.path.join(helao_root, 'visualizer\styles.css')).read_text()


class cmd_exception(ValueError):
    def __init__(self, arg):
        self.args = arg


class TriggerType(str, Enum):
    risingedge = "risingedge"
    fallingedge = "fallingedge"


class Galil:
    def __init__(self, action_serv: Base):

        self.base = action_serv
        self.config_dict = action_serv.server_cfg["params"]

        self.dev_ai = self.config_dict.get("dev_ai",dict())
        self.dev_aiitems = make_str_enum("dev_ai",{key:key for key in self.dev_ai})
        
        self.dev_ao = self.config_dict.get("dev_ao",dict())
        self.dev_aoitems = make_str_enum("dev_ao",{key:key for key in self.dev_ao})

        self.dev_di = self.config_dict.get("dev_di",dict())
        self.dev_diitems = make_str_enum("dev_di",{key:key for key in self.dev_di})

        self.dev_do = self.config_dict.get("dev_do",dict())
        self.dev_doitems = make_str_enum("dev_do",{key:key for key in self.dev_do})

        self.digital_cycle_out = None
        self.digital_cycle_out_gamry = None
        self.digital_cycle_mainthread = None
        self.digital_cycle_subthread = None


        # if this is the main instance let us make a galil connection
        self.g = gclib.py()
        self.base.print_message(f"gclib version: {self.g.GVersion()}")
        # TODO: error checking here: Galil can crash an dcarsh program
        galil_ip = self.config_dict.get("galil_ip_str", None)
        self.galil_enabled = None
        try:
            if galil_ip:
                self.g.GOpen("%s --direct -s ALL" % (galil_ip))
                self.base.print_message(self.g.GInfo())
                self.galilcmd = self.g.GCommand  # alias the command callable
                # downloads a DMC program to galil
                self.galilprgdownload = self.g.GProgramDownload
                self.galil_enabled = True
            else:
                self.base.print_message(
                    "no Galil IP configured",
                    error = True
                )
                self.galil_enabled = False
        except Exception:
            self.base.print_message(
                "severe Galil error ... please power cycle Galil and try again", error = True
            )
            self.galil_enabled = False

        self.cycle_lights = False


    async def reset(self):
        pass


    async def estop(self, switch:bool, *args, **kwargs):
        # this will estop the io
        # set estop: switch=true
        # release estop: switch=false
        self.base.print_message("IO Estop")
        if switch == True:
            await self.digital_out_off(await self.get_all_digital_out())
            await self.set_analog_out(await self.get_all_analoh_out(), 0)
            # set flag
            self.base.actionserver.estop = True
        else:
            # need only to set the flag
            self.base.actionserver.estop = False
        return switch


    async def get_analog_in(self, 
                            ai_port:str,
                            ai_name:str="analog_in",
                            *args,**kwargs):
        err_code = ErrorCodes.none
        ret = None
        if ai_name in self.dev_ai \
        and self.dev_ai[ai_name] == ai_port:
            cmd = f"MG @AN[{int(ai_port)}]"
            self.base.print_message(f"cmd: '{cmd}'", info = True)
            ret = self.galilcmd(cmd)
        else:
            err_code = ErrorCodes.not_available

        return {
                "error_code": err_code,
                "port": ai_port,
                "name": ai_name,
                "type": "analog_in",
                "value": ret
               }


    async def get_digital_in(self, 
                             di_port:str,
                             di_name:str="digital_in",
                             *args,**kwargs):
        err_code = ErrorCodes.none
        ret = None
        if di_name in self.dev_di \
        and self.dev_di[di_name] == di_port:
            cmd = f"MG @IN[{int(di_port)}]"
            self.base.print_message(f"cmd: '{cmd}'", info = True)
            ret = self.galilcmd(cmd)
        else:
            err_code = ErrorCodes.not_available

        return {
                "error_code": err_code,
                "port": di_port,
                "name": di_name,
                "type": "digital_in",
                "value": ret
               }


    async def get_digital_out(self, 
                              do_port:str,
                              do_name:str="digital_out",
                              *args,**kwargs):
        err_code = ErrorCodes.none
        ret = None
        if do_name in self.dev_do \
        and self.dev_do[do_name] == do_port:
            cmd = f"MG @OUT[{int(do_port)}]"
            self.base.print_message(f"cmd: '{cmd}'", info = True)
            ret = self.galilcmd(cmd)
        else:
            err_code = ErrorCodes.not_available

        return {
                "error_code": err_code,
                "port": do_port,
                "name": do_name,
                "type": "digital_out",
                "value": ret
               }


    # def set_analog_out(self, ports, handle: int, module: int, bitnum: int, multi_value):
    async def set_analog_out(self, 
                             ao_port:int, 
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
        # _ = self.galilcmd("AO {},{}".format(port, value))
        return {
                "error_code": err_code,
                "port": ao_port,
                "name": ao_name,
                "type": "analog_out",
                "value": None
               }


    async def set_digital_out(self, 
                              do_port:str,
                              on:bool, 
                              do_name:str="",
                              *args,**kwargs):
        err_code = ErrorCodes.none
        on = bool(on)
        ret = None
        if do_name in self.dev_do \
        and self.dev_do[do_name] == do_port:
            if on:
                cmd = f"SB {int(do_port)}"
            else:
                cmd = f"CB {int(do_port)}"
            self.base.print_message(f"cmd: '{cmd}'", info = True)
            _ = self.galilcmd(cmd)
            cmd = f"MG @OUT[{int(do_port)}]"
            self.base.print_message(f"cmd: '{cmd}'", info = True)
            ret = self.galilcmd(cmd)
        else:
            err_code = ErrorCodes.not_available

        return {
                "error_code": err_code,
                "port": do_port,
                "name": do_name,
                "type": "digital_out",
                "value": ret
               }


    async def upload_DMC(self, DMC_prog):
        # self.galilcmd("UL;")  # begin upload
        # upload line by line from DMC_prog
        self.galilprgdownload("DL;")
        self.base.print_message(f"DMC prg:\n{DMC_prog}", info = True)
        self.galilprgdownload(DMC_prog+"\x00")


    async def set_digital_cycle(
                                self, 
                                trigger_port:str, 
                                trigger_name:str, 
                                triggertype:TriggerType,
                                out_port:str,
                                out_name:str,
                                out_port_gamry:str,
                                out_name_gamry:str,
                                t_on:float,
                                t_off:float,
                                mainthread:int,
                                subthread:int,
                                *args,
                                **kwargs
                               ):
        err_code = ErrorCodes.none
        if trigger_name in self.dev_di \
        and self.dev_di[trigger_name] == trigger_port\
        and out_name in self.dev_do \
        and self.dev_do[out_name] == out_port \
        and out_name_gamry in self.dev_do \
        and self.dev_do[out_name_gamry] == out_port_gamry \
        and mainthread != subthread:
    
            self.digital_cycle_out = out_port
            self.digital_cycle_out_gamry = out_port_gamry
            self.digital_cycle_mainthread = mainthread
            self.digital_cycle_subthread = subthread
            
            # di (AI n): 
            # if n is positive, galil waits for input to go high (rising edge)
            # if n is negative, galil waits for input to go low (falling edge)
            if triggertype == TriggerType.risingedge:
                trigger_port = f"{abs(int(trigger_port))}"
            elif triggertype == TriggerType.fallingedge:
                trigger_port = f"-{abs(int(trigger_port))}"

    
            DMC_prog = pathlib.Path(
                os.path.join(driver_path, "galil_toogle.dmc")
            ).read_text()
            DMC_prog = DMC_prog.format(
                p_trigger=trigger_port, 
                p_output=out_port, 
                p_output_gamry=out_port_gamry, 
                t_time_on=t_on,
                t_time_off=t_off,
                subthread = subthread,
               mainthread = mainthread
            )
            await self.upload_DMC(DMC_prog)
            self.galilcmd(f"XQ #main{mainthread},{mainthread}")  # excecute main routine
            # self.galilcmd("XQ #toogle, 1")  # excecute main routine
        else:
            err_code = ErrorCodes.not_available

        return {
                "error_code": err_code
               }


    async def stop_digital_cycle(self):
            if self.digital_cycle_out:
                self.galilcmd(f"HX{self.digital_cycle_mainthread}")  # stops main routine
                self.galilcmd("HX{self.digital_cycle_subthread}")  # stops main routine
                cmd = f"CB {int(self.digital_cycle_out)}"
                _ = self.galilcmd(cmd)
                cmd = f"CB {int(self.digital_cycle_out_gamry)}"
                _ = self.galilcmd(cmd)
                self.digital_cycle_out = None
                self.digital_cycle_out_gamry = None
                self.digital_cycle_mainthread = None
                self.digital_cycle_subthread = None


            return dict()


    def shutdown_event(self):
        # this gets called when the server is shut down or reloaded to ensure a clean
        # disconnect ... just restart or terminate the server
        try:
            self.base.print_message("shutting down galil io")
            self.g.GClose()
        except Exception as e:
            self.base.print_message(f"could not close galil connection: {e}",
                                    info = True)
        return {"shutdown"}
