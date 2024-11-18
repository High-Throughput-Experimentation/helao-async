""" A device class for the Galil motion controller, used by a FastAPI server instance.

The 'galil' device class exposes motion and I/O functions from the underlying 'gclib'
library. Class methods are specific to Galil devices. Device configuration is read from
config/config.py. 

This driver requires gclib to be installed. After installation, activate the helao
environment and run:

`python "c:\Program Files (x86)\Galil\gclib\source\wrappers\python\setup.py" install`

to install the python module.

"""

__all__ = [
    "Galil",
    "TriggerType",
]


import time
import os
import pathlib
import traceback
import asyncio
from typing import Union, Optional, List


from helao.helpers import logging
if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER

from helao.servers.base import Base
from helao.helpers.executor import Executor
from helao.core.error import ErrorCodes
from helao.helpers.make_str_enum import make_str_enum
from helao.core.models.hlostatus import HloStatus

from helao.drivers.io.enum import TriggerType

driver_path = os.path.dirname(os.path.realpath(__file__))

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
        self.config_dict = action_serv.server_cfg.get("params", {})

        self.dev_ai = self.config_dict.get("dev_ai", {})
        self.dev_aiitems = make_str_enum("dev_ai", {key: key for key in self.dev_ai})

        self.monitor_ai = {
            ai_name: scaling
            for ai_name, scaling in self.config_dict.get("monitor_ai", {}).items()
            if ai_name in self.dev_ai.keys()
        }

        self.dev_ao = self.config_dict.get("dev_ao", {})
        self.dev_aoitems = make_str_enum("dev_ao", {key: key for key in self.dev_ao})

        self.dev_di = self.config_dict.get("dev_di", {})
        self.dev_diitems = make_str_enum("dev_di", {key: key for key in self.dev_di})

        self.dev_do = self.config_dict.get("dev_do", {})
        self.dev_doitems = make_str_enum("dev_do", {key: key for key in self.dev_do})

        self.digital_cycle_out = None
        self.digital_cycle_out_gamry = None
        self.digital_cycle_mainthread = None
        self.digital_cycle_subthread = None
        self.digital_cycle_subthread2 = None

        # if this is the main instance let us make a galil connection
        self.g = gclib.py()
        LOGGER.info(f"gclib version: {self.g.GVersion()}")
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
                LOGGER.error("no Galil IP configured")
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

        self.aloop = asyncio.get_running_loop()
        self.polling = True
        self.poll_signalq = asyncio.Queue(1)
        self.poll_signal_task = self.aloop.create_task(self.poll_signal_loop())
        self.polling_task = self.aloop.create_task(self.poll_sensor_loop())

    async def poll_sensor_loop(self, frequency: int = 4):
        LOGGER.info("polling background task has started")
        waittime = 1.0 / frequency
        lastupdate = 0
        while True:
            if self.polling:
                for ai_name, scaling in self.monitor_ai.items():
                    status_dict = {}
                    checktime = time.time()
                    if checktime - lastupdate < waittime:
                        # LOGGER.info("waiting for minimum update interval.")
                        await asyncio.sleep(waittime - (checktime - lastupdate))
                    ai_resp = await self.get_analog_in(ai_name)
                    if (
                        ai_resp.get("error_code", ErrorCodes.not_available)
                        == ErrorCodes.none
                    ):
                        status_dict = {ai_name: float(ai_resp["value"]) * scaling}
                        await self.base.put_lbuf(status_dict)
                    lastupdate = time.time()
                    # self.base.print_message(ai_resp)
            await asyncio.sleep(0.01)

    async def reset(self):
        pass

    async def start_polling(self):
        LOGGER.info("got 'start_polling' request, raising signal")
        async with self.base.aiolock:
            await self.poll_signalq.put(True)
        while not self.polling:
            LOGGER.info("waiting for polling loop to start")
            await asyncio.sleep(0.1)

    async def stop_polling(self):
        LOGGER.info("got 'stop_polling' request, raising signal")
        async with self.base.aiolock:
            await self.poll_signalq.put(False)
        while self.polling:
            LOGGER.info("waiting for polling loop to stop")
            await asyncio.sleep(0.1)

    async def poll_signal_loop(self):
        while True:
            self.polling = await self.poll_signalq.get()
            LOGGER.info("polling signal received")

    async def estop(self, switch: bool, *args, **kwargs):
        # this will estop the io
        # set estop: switch=true
        # release estop: switch=false
        LOGGER.info("IO Estop")
        if switch:
            for ao_name in self.dev_ao.keys():
                await self.set_digital_out(
                    on=False,
                    value=0.0,
                    ao_name=ao_name,
                )
            for do_name in self.dev_do.keys():
                await self.set_digital_out(
                    on=False,
                    do_name=do_name,
                )
            # set flag
            self.base.actionservermodel.estop = True
        else:
            # need only to set the flag
            self.base.actionservermodel.estop = False
        return switch

    async def get_analog_in(self, ai_name: str = "analog_in", *args, **kwargs):
        err_code = ErrorCodes.none
        ret = None
        ai_port = -1
        if ai_name in self.dev_ai:
            ai_port = self.dev_ai[ai_name]
            cmd = f"MG @AN[{int(ai_port)}]"
            # LOGGER.info(f"cmd: '{cmd}'")
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

    async def get_digital_in(self, di_name: str = "digital_in", *args, **kwargs):
        err_code = ErrorCodes.none
        ret = None
        di_port = -1
        if di_name in self.dev_di:
            di_port = self.dev_di[di_name]
            cmd = f"MG @IN[{int(di_port)}]"
            # LOGGER.info(f"cmd: '{cmd}'")
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

    async def get_digital_out(self, do_name: str = "digital_out", *args, **kwargs):
        err_code = ErrorCodes.none
        ret = None
        do_port = -1
        if do_name in self.dev_do:
            do_port = self.dev_do[do_name]
            cmd = f"MG @OUT[{int(do_port)}]"
            # LOGGER.info(f"cmd: '{cmd}'")
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
        self, value: float, ao_name: str = "analog_out", *args, **kwargs
    ):
        err_code = ErrorCodes.not_available
        ao_port = -1
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

    async def set_digital_out(self, on: bool, do_name: str = "", *args, **kwargs):
        err_code = ErrorCodes.none
        on = bool(on)
        ret = None
        do_port = -1
        if do_name in self.dev_do:
            do_port = self.dev_do[do_name]
            if on:
                cmd = f"SB {int(do_port)}"
            else:
                cmd = f"CB {int(do_port)}"
            # LOGGER.info(f"cmd: '{cmd}'")
            _ = self.galilcmd(cmd)
            cmd = f"MG @OUT[{int(do_port)}]"
            # LOGGER.info(f"cmd: '{cmd}'")
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
        LOGGER.info(f"DMC prg:\n{DMC_prog}")
        self.galilprgdownload(DMC_prog + "\x00")

    async def set_digital_cycle(
        self,
        trigger_name: str,
        triggertype: TriggerType,
        out_name: Union[str, List[str]],
        toggle_init_delay: Union[float, List[float]],  # seconds
        toggle_duty: Union[float, List[float]],  # fraction
        toggle_period: Union[float, List[float]],  # seconds
        toggle_duration: Union[float, List[float]],  # seconds
        out_name_gamry: Optional[str] = None,
        req_out_name: Optional[str] = None,
        stop_via_ttl: Optional[bool] = True,
        *args,
        **kwargs,
    ):
        # rewrite params for consistency w/jcap eche runs
        t_duration = (
            [int(round(x * 1e3)) for x in toggle_duration]
            if isinstance(toggle_duration, list)
            else int(round(toggle_duration * 1e3))
        )
        t_on = (
            [int(round(x * y * 1e3)) for x, y in zip(toggle_period, toggle_duty)]
            if isinstance(toggle_period, list)
            else int(round(toggle_period * toggle_duty * 1e3))
        )
        t_off = (
            [int(round(x * (1 - y) * 1e3)) for x, y in zip(toggle_period, toggle_duty)]
            if isinstance(toggle_period, list)
            else int(round(toggle_period * (1 - toggle_duty) * 1e3))
        )
        t_offset = (
            [int((x * 1e3)) for x in toggle_init_delay]
            if isinstance(toggle_init_delay, list)
            else int(round(toggle_init_delay * 1e3))
        )

        err_code = ErrorCodes.none
        valid_trig = False
        if trigger_name in self.dev_di:
            valid_trig = True
            trigger_port = self.dev_di[trigger_name]
            if triggertype == TriggerType.risingedge:
                trigger_port_on = trigger_port
                trigger_port_off = -trigger_port
            elif triggertype == TriggerType.fallingedge:
                trigger_port_on = -trigger_port
                trigger_port_off = trigger_port
            elif triggertype == TriggerType.blip:
                trigger_port_on = trigger_port
                trigger_port_off = trigger_port

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
            LOGGER.error("set_digital_cycle parameters are not valid")
            return {"error_code": ErrorCodes.not_available}

        if stop_via_ttl:
            main_dmc = "galil_toggle_main.dmc"
        else:
            main_dmc = "galil_toggle_main_nostop.dmc"
        mainprog = pathlib.Path(os.path.join(driver_path, main_dmc)).read_text()
        if req_out_name is not None:
            req_port = self.dev_do[req_out_name]
            subprog_dmc = "galil_toggle_sub_req.dmc"
        else:
            req_port = ""
            subprog_dmc = "galil_toggle_sub.dmc"
        subprog = pathlib.Path(os.path.join(driver_path, subprog_dmc)).read_text()
        mainlines = mainprog.split("\n")
        subindex = [i for i, x in enumerate(mainlines) if x.strip().startswith("XQ")][0]
        subline = mainlines.pop(subindex)
        for i in range(len(out_ports)):
            mainlines.insert(subindex + i, subline.format(subthread=i + 1))
        clearbits = [i for i, x in enumerate(mainlines) if x.strip().startswith("CB")]
        for i in clearbits:
            mainlines[i] = "    " + "".join([f"CB {oc};" for oc in out_ports])
        haltindex = [i for i, x in enumerate(mainlines) if x.strip().startswith("HX")][
            0
        ]
        mainlines.pop(haltindex)
        haltline = "    " + "".join([f"HX{i+1};" for i in range(len(out_ports))])
        mainlines.insert(haltindex, haltline)
        prog_parts = [
            "\n".join(mainlines).format(
                p_trigger_on=trigger_port_on, p_trigger_off=trigger_port_off
            )
        ] + [
            subprog.format(
                subthread=i + 1,
                p_output=out_ports[i],
                t_duration=t_duration[i],
                t_offset=t_offset[i],
                t_time_on=t_on[i],
                t_time_off=t_off[i],
                r_output=req_port,
            )
            for i in range(len(out_ports))
        ]
        dmc_prog = "\n".join(prog_parts)
        await self.upload_DMC(dmc_prog)
        self.galilcmd("XQ #main,0")  # excecute main routine

        return {"error_code": err_code}

    async def stop_digital_cycle(self):
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

        return {"error_code": ErrorCodes.none}

    def shutdown(self):
        # this gets called when the server is shut down or reloaded to ensure a clean
        # disconnect ... just restart or terminate the server
        LOGGER.info("shutting down galil io")
        self.galil_enabled = False
        try:
            self.g.GClose()
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            LOGGER.error(f"could not close galil connection: {repr(e), tb,}")
        return {"shutdown"}


class AiMonExec(Executor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        LOGGER.info("AiMonExec initialized.")
        self.start_time = time.time()
        self.duration = self.active.action.action_params.get("duration", -1)
        LOGGER.info("AiMonExec init complete.")

    async def _poll(self):
        """Read analog inputs from live buffer."""
        data_dict = {}
        times = []
        for ai_name in self.active.base.fastapp.driver.monitor_ai.keys():
            val, epoch_s = self.active.base.get_lbuf(ai_name)
            data_dict[ai_name] = val
            times.append(epoch_s)
        data_dict["epoch_s"] = max(times)
        iter_time = time.time()
        elapsed_time = iter_time - self.start_time
        if (self.duration < 0) or (elapsed_time < self.duration):
            status = HloStatus.active
        else:
            status = HloStatus.finished
        await asyncio.sleep(0.01)
        return {
            "error": ErrorCodes.none,
            "status": status,
            "data": data_dict,
        }
