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
import pathlib
import traceback
from typing import Union, Optional, List

from helaocore.server.base import Base
from helaocore.error import ErrorCodes
from helaocore.helper.make_str_enum import make_str_enum

from helao.driver.io.enum import TriggerType

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

        self.dev_ai = self.config_dict.get("dev_ai", dict())
        self.dev_aiitems = make_str_enum("dev_ai", {key: key for key in self.dev_ai})

        self.dev_ao = self.config_dict.get("dev_ao", dict())
        self.dev_aoitems = make_str_enum("dev_ao", {key: key for key in self.dev_ao})

        self.dev_di = self.config_dict.get("dev_di", dict())
        self.dev_diitems = make_str_enum("dev_di", {key: key for key in self.dev_di})

        self.dev_do = self.config_dict.get("dev_do", dict())
        self.dev_doitems = make_str_enum("dev_do", {key: key for key in self.dev_do})

        self.digital_cycle_out = None
        self.digital_cycle_out_gamry = None
        self.digital_cycle_mainthread = None
        self.digital_cycle_subthread = None
        self.digital_cycle_subthread2 = None

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
                self.base.print_message("no Galil IP configured", error=True)
                self.galil_enabled = False
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            self.base.print_message(
                f"severe Galil error ... please power cycle Galil "
                f"and try again {repr(e), tb,}",
                error=True,
            )
            self.galil_enabled = False

        self.cycle_lights = False

    async def reset(self):
        pass

    async def estop(self, switch: bool, *args, **kwargs):
        # this will estop the io
        # set estop: switch=true
        # release estop: switch=false
        self.base.print_message("IO Estop")
        if switch == True:
            for ao_name, ao_port in self.dev_ao.items():
                await self.set_digital_out(
                    ao_port=ao_port,
                    value=0.0,
                    ao_name=ao_name,
                )
            for do_name, do_port in self.dev_do.items():
                await self.set_digital_out(
                    do_port=do_port,
                    on=False,
                    do_name=do_name,
                )
            # set flag
            self.base.actionserver.estop = True
        else:
            # need only to set the flag
            self.base.actionserver.estop = False
        return switch

    async def get_analog_in(
        self, ai_port: str, ai_name: str = "analog_in", *args, **kwargs
    ):
        err_code = ErrorCodes.none
        ret = None
        if ai_name in self.dev_ai and self.dev_ai[ai_name] == ai_port:
            cmd = f"MG @AN[{int(ai_port)}]"
            self.base.print_message(f"cmd: '{cmd}'", info=True)
            ret = self.galilcmd(cmd)
        else:
            err_code = ErrorCodes.not_available

        return {
            "error_code": err_code,
            "port": ai_port,
            "name": ai_name,
            "type": "analog_in",
            "value": ret,
        }

    async def get_digital_in(
        self, di_port: str, di_name: str = "digital_in", *args, **kwargs
    ):
        err_code = ErrorCodes.none
        ret = None
        if di_name in self.dev_di and self.dev_di[di_name] == di_port:
            cmd = f"MG @IN[{int(di_port)}]"
            self.base.print_message(f"cmd: '{cmd}'", info=True)
            ret = self.galilcmd(cmd)
        else:
            err_code = ErrorCodes.not_available

        return {
            "error_code": err_code,
            "port": di_port,
            "name": di_name,
            "type": "digital_in",
            "value": ret,
        }

    async def get_digital_out(
        self, do_port: str, do_name: str = "digital_out", *args, **kwargs
    ):
        err_code = ErrorCodes.none
        ret = None
        if do_name in self.dev_do and self.dev_do[do_name] == do_port:
            cmd = f"MG @OUT[{int(do_port)}]"
            self.base.print_message(f"cmd: '{cmd}'", info=True)
            ret = self.galilcmd(cmd)
        else:
            err_code = ErrorCodes.not_available

        return {
            "error_code": err_code,
            "port": do_port,
            "name": do_name,
            "type": "digital_out",
            "value": ret,
        }

    # def set_analog_out(self, ports, handle: int, module: int, bitnum: int, multi_value):
    async def set_analog_out(
        self, ao_port: int, value: float, ao_name: str = "analog_out", *args, **kwargs
    ):
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
            "value": None,
        }

    async def set_digital_out(
        self, do_port: str, on: bool, do_name: str = "", *args, **kwargs
    ):
        err_code = ErrorCodes.none
        on = bool(on)
        ret = None
        if do_name in self.dev_do and self.dev_do[do_name] == do_port:
            if on:
                cmd = f"SB {int(do_port)}"
            else:
                cmd = f"CB {int(do_port)}"
            self.base.print_message(f"cmd: '{cmd}'", info=True)
            _ = self.galilcmd(cmd)
            cmd = f"MG @OUT[{int(do_port)}]"
            self.base.print_message(f"cmd: '{cmd}'", info=True)
            ret = self.galilcmd(cmd)
        else:
            err_code = ErrorCodes.not_available

        return {
            "error_code": err_code,
            "port": do_port,
            "name": do_name,
            "type": "digital_out",
            "value": ret,
        }

    async def upload_DMC(self, DMC_prog):
        # self.galilcmd("UL;")  # begin upload
        # upload line by line from DMC_prog
        self.galilprgdownload("DL;")
        self.base.print_message(f"DMC prg:\n{DMC_prog}", info=True)
        self.galilprgdownload(DMC_prog + "\x00")

    async def set_digital_cycles(
        self,
        trigger_name: str,
        triggertype: TriggerType,
        out_name: Union[str, List[str]],
        t_on: Union[int, List[int]],
        t_off: Union[int, List[int]],
        t_offset: Union[int, List[int]],
        t_duration: Union[int, List[int]],
        out_name_gamry: Optional[str] = None,
        *args,
        **kwargs,
    ):
        err_code = ErrorCodes.none
        valid_trig = False
        if trigger_name in self.dev_di:
            valid_trig = True
            trigger_port = self.dev_di[trigger_name]
            if triggertype == TriggerType.risingedge:
                trigger_port = f"{abs(int(trigger_port))}"
            elif triggertype == TriggerType.fallingedge:
                trigger_port = f"-{abs(int(trigger_port))}"

        if (
            valid_trig
            and out_name_gamry is not None
            and isinstance(out_name, str)
            and isinstance(t_on, int)
            and isinstance(t_off, int)
            and isinstance(t_offset, int)
            and isinstance(t_duration, int)
            and out_name in self.dev_do
            and out_name_gamry in self.dev_do
        ):
            out_port = self.dev_do[out_name]
            out_port_gamry = self.dev_do[out_name_gamry]
            out_ports = [out_port, out_port_gamry]
            t_on = [t_on] * 2
            t_off = [t_off] * 2
            t_offset = [t_offset] * 2
            t_duration = [t_duration] * 2
            self.digital_cycle_out = out_port
            self.digital_cycle_out_gamry = out_port_gamry
            self.digital_cycle_mainthread = 0
            self.digital_cycle_subthread = 1

            # di (AI n):
            # if n is positive, galil waits for input to go high (rising edge)
            # if n is negative, galil waits for input to go low (falling edge)

        elif (
            valid_trig
            and out_name_gamry is None
            and isinstance(out_name, list)
            and isinstance(t_on, list)
            and isinstance(t_off, list)
            and isinstance(t_offset, list)
            and isinstance(t_duration, list)
            and trigger_name in self.dev_di
            and all([x in self.dev_do for x in out_name])
            and len(out_name)
            == len(t_on)
            == len(t_off)
            == len(t_offset)
            == len(t_duration)
        ):
            out_ports = [self.dev_do[x] for x in out_name]
            self.digital_cycle_out = out_ports
            self.digital_cycle_out_gamry = None
            self.digital_cycle_mainthread = 0
            self.digital_cycle_subthread = [i + 1 for i in range(len(out_ports))]

        else:
            self.base.print_message(
                "set_digital_cycle parameters are not valid", error=True
            )
            return {"error_code": ErrorCodes.not_available}

        mainprog = pathlib.path(
            os.path.join(driver_path, "galil_toggle_main.dmc")
        ).read_text()
        subprog = pathlib.path(
            os.path.join(driver_path, "galil_toggle_sub.dmc")
        ).read_text()
        mainlines = mainprog.split("\n")
        subindex = [i for i, x in enumerate(mainlines) if x.strip().startswith("XQ")][0]
        subline = mainlines.pop(subindex)
        for i in range(len(trigger_port)):
            mainlines.insert(subindex + i + 1, subline.format(subthread=i + 1))
        clearbits = [i for i, x in enumerate(mainlines) if x.strip().startswith("CB")]
        for i in clearbits:
            mainlines[i] = "    " + "".join([f"CB {oc};" for oc in out_ports])
        haltindex = [i for i, x in enumerate(mainlines) if x.strip().startswith("HX")][
            0
        ]
        mainlines.pop(haltindex)
        haltline = "    " + "".join([f"HX{i+1};" for i in range(len(out_ports))])
        mainlines.insert(haltindex + 1, haltline)
        prog_parts = ["\n".join(mainlines).format(p_trigger=trigger_port)] + [
            subprog.format(
                subthread=i + 1,
                p_output=out_ports[i],
                t_duration=t_duration[i],
                t_offset=t_offset[i],
                t_time_on=t_on[i],
                t_time_off=t_off[i],
            )
            for i in range(len(out_ports))
        ]
        dmc_prog = "\n".join(prog_parts)
        await self.upload_dmc(dmc_prog)
        self.galilcmd(f"XQ #main,0")  # excecute main routine

        return {"error_code": err_code}

    async def stop_digital_cycles(self):
        if self.digital_cycle_out is not None:
            self.galilcmd(f"HX{self.digital_cycle_mainthread}")  # stops main routine
            self.digital_cycle_mainthread = None
            if isinstance(self.digital_cycle_out, int):
                self.digital_cycle_out = [self.digital_cycle_out]
            for i, dout in enumerate(self.digital_cycle_out):
                self.galilcmd(f"HX{i+1}")  # stops main routine
                cmd = f"CB {int(dout)}"
                _ = self.galilcmd(cmd)
            self.digital_cycle_out = None
            self.digital_cycle_subthread = None
        if self.digital_cycle_out_gamry is not None:
            cmd = f"CB {int(self.digital_cycle_out_gamry)}"
            _ = self.galilcmd(cmd)
            self.digital_cycle_out_gamry = None

        return {}

    async def set_digital_cycle(
        self,
        trigger_port: str,
        trigger_name: str,
        triggertype: TriggerType,
        out_port: str,
        out_name: str,
        out_port_gamry: str,
        out_name_gamry: str,
        t_on: int,
        t_off: int,
        t_offset: int,
        t_duration: int,
        *args,
        **kwargs,
    ):
        err_code = ErrorCodes.none
        if (
            trigger_name in self.dev_di
            and self.dev_di[trigger_name] == trigger_port
            and out_name in self.dev_do
            and self.dev_do[out_name] == out_port
            and out_name_gamry in self.dev_do
            and self.dev_do[out_name_gamry] == out_port_gamry
        ):

            self.digital_cycle_out = out_port
            self.digital_cycle_out_gamry = out_port_gamry
            self.digital_cycle_mainthread = 0
            self.digital_cycle_subthread = 1

            # di (AI n):
            # if n is positive, galil waits for input to go high (rising edge)
            # if n is negative, galil waits for input to go low (falling edge)
            if triggertype == TriggerType.risingedge:
                trigger_port = f"{abs(int(trigger_port))}"
            elif triggertype == TriggerType.fallingedge:
                trigger_port = f"-{abs(int(trigger_port))}"

            print(t_duration)
            print((t_on + t_off))
            print(t_duration / (t_on + t_off))
            f_maxcount = round(t_duration / (t_on + t_off))
            self.base.print_message(f"toggle count: {f_maxcount}", info=True)

            DMC_prog = pathlib.Path(
                os.path.join(driver_path, "galil_toggle.dmc")
            ).read_text()
            DMC_prog = DMC_prog.format(
                p_trigger=trigger_port,
                p_output=out_port,
                p_output_gamry=out_port_gamry,
                t_time_on=t_on,
                t_time_off=t_off,
                t_offset=t_offset,
                f_maxcount=f_maxcount,
                subthread=self.digital_cycle_subthread,
                mainthread=self.digital_cycle_subthread,
            )
            await self.upload_DMC(DMC_prog)
            self.galilcmd(
                f"XQ #main{self.digital_cycle_subthread},{self.digital_cycle_subthread}"
            )  # excecute main routine
        else:
            self.base.print_message(
                "set_digital_cycle parameters are not valid", error=True
            )
            err_code = ErrorCodes.not_available

        return {"error_code": err_code}

    async def stop_digital_cycle(self):
        if self.digital_cycle_out:
            self.galilcmd(f"HX{self.digital_cycle_mainthread}")  # stops main routine
            self.galilcmd(f"HX{self.digital_cycle_subthread}")  # stops main routine
            cmd = f"CB {int(self.digital_cycle_out)}"
            _ = self.galilcmd(cmd)
            cmd = f"CB {int(self.digital_cycle_out_gamry)}"
            _ = self.galilcmd(cmd)
            self.digital_cycle_out = None
            self.digital_cycle_out_gamry = None
            self.digital_cycle_mainthread = None
            self.digital_cycle_subthread = None

        return {}

    async def set_digital_cycle2(
        self,
        trigger_port: str,
        trigger_name: str,
        triggertype: TriggerType,
        out_port: str,
        out_name: str,
        out_port2: str,
        out_name2: str,
        t_on: int,
        t_off: int,
        t_offset: int,
        t_duration: int,
        t_on2: int,
        t_off2: int,
        t_offset2: int,
        t_duration2: int,
        *args,
        **kwargs,
    ):
        err_code = ErrorCodes.none
        if (
            trigger_name in self.dev_di
            and self.dev_di[trigger_name] == trigger_port
            and out_name in self.dev_do
            and self.dev_do[out_name] == out_port
            and out_name2 in self.dev_do
            and self.dev_do[out_name2] == out_port2
        ):

            self.digital_cycle_out = out_port
            self.digital_cycle_out2 = out_port2
            self.digital_cycle_mainthread = 0
            self.digital_cycle_subthread = [1, 2]

            # di (AI n):
            # if n is positive, galil waits for input to go high (rising edge)
            # if n is negative, galil waits for input to go low (falling edge)
            if triggertype == TriggerType.risingedge:
                trigger_port = f"{abs(int(trigger_port))}"
            elif triggertype == TriggerType.fallingedge:
                trigger_port = f"-{abs(int(trigger_port))}"

            print(t_duration)
            print((t_on + t_off))
            print(t_duration / (t_on + t_off))
            f_maxcount = round(t_duration / (t_on + t_off))
            f_maxcount2 = round(t_duration2 / (t_on2 + t_off2))
            self.base.print_message(f"toggle count: {f_maxcount}", info=True)

            DMC_prog = pathlib.Path(
                os.path.join(driver_path, "galil_two_toggle.dmc")
            ).read_text()
            DMC_prog = DMC_prog.format(
                p_trigger=trigger_port,
                p_output=out_port,
                p_output2=out_port2,
                t_time_on=t_on,
                t_time_off=t_off,
                t_offset=t_offset,
                t_duration=t_duration,
                f_maxcount=f_maxcount,
                t_time_on2=t_on2,
                t_time_off2=t_off2,
                t_offset2=t_offset2,
                t_duration2=t_duration2,
                f_maxcount2=f_maxcount2,
                subthread=self.digital_cycle_subthread[0],
                subthread2=self.digital_cycle_subthread[1],
                mainthread=self.digital_cycle_mainthread,
            )
            await self.upload_DMC(DMC_prog)
            self.galilcmd(
                f"XQ #main{self.digital_cycle_mainthread},{self.digital_cycle_mainthread}"
            )  # excecute main routine
        else:
            self.base.print_message(
                "set_digital_cycle parameters are not valid", error=True
            )
            err_code = ErrorCodes.not_available

        return {"error_code": err_code}

    async def stop_digital_cycle2(self):
        if self.digital_cycle_out:
            self.galilcmd(f"HX{self.digital_cycle_mainthread}")  # stops main routine
            self.galilcmd(f"HX{self.digital_cycle_subthread[0]}")  # stops main routine
            self.galilcmd(f"HX{self.digital_cycle_subthread[1]}")  # stops main routine
            cmd = f"CB {int(self.digital_cycle_out)}"
            _ = self.galilcmd(cmd)
            self.digital_cycle_out = None
            if self.digital_cycle_out2:
                cmd = f"CB {int(self.digital_cycle_out2)}"
                _ = self.galilcmd(cmd)
                self.digital_cycle_out2 = None
            self.digital_cycle_mainthread = None
            self.digital_cycle_subthread = None
            self.digital_cycle_subthread2 = None

        return {}

    def shutdown(self):
        # this gets called when the server is shut down or reloaded to ensure a clean
        # disconnect ... just restart or terminate the server
        self.base.print_message("shutting down galil io")
        self.galil_enabled = False
        try:
            self.g.GClose()
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            self.base.print_message(
                f"could not close galil connection: {repr(e), tb,}", error=True
            )
        return {"shutdown"}
