""" A device class for the KD Scientific Legato 100 series syringe pump.

"""

__all__ = []

import serial
import io
import time
import asyncio
from typing import Optional

# import traceback

from helaocore.models.hlostatus import HloStatus
from helaocore.error import ErrorCodes
from helao.servers.base import Base
from helao.helpers.executor import Executor

# from helao.helpers.sample_api import UnifiedSampleDataAPI


# from functools import partial
# from bokeh.server.server import Server
# from helao.helpers.active_params import ActiveParams

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

ulmap = {
    "pl": 0.000001,
    "nl": 0.001,
    "ul": 1.0,
    "ml": 1000.0,
}


class KDS100:
    def __init__(self, action_serv: Base):
        self.base = action_serv
        self.config_dict = action_serv.server_cfg.get("params", {})
        # self.unified_db = UnifiedSampleDataAPI(self.base)
        # self.bokehapp = None

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

        self.aloop = asyncio.get_running_loop()
        self.com_lock = False
        self.polling = True
        self.poll_signalq = asyncio.Queue(1)
        self.poll_signal_task = self.aloop.create_task(self.poll_signal_loop())
        self.polling_task = self.aloop.create_task(self.poll_sensor_loop())
        self.present_volume_ul = 0.0
        self.last_state = "unknown"

    async def start_polling(self):
        self.base.print_message("got 'start_polling' request, raising signal")
        async with self.base.aiolock:
            await self.poll_signalq.put(True)
        while not self.polling:
            self.base.print_message("waiting for polling loop to start")
            await asyncio.sleep(0.1)

    async def stop_polling(self):
        self.base.print_message("got 'stop_polling' request, raising signal")
        async with self.base.aiolock:
            await self.poll_signalq.put(False)
        while self.polling:
            self.base.print_message("waiting for polling loop to stop")
            await asyncio.sleep(0.1)

    async def poll_signal_loop(self):
        await self.safe_state()
        while True:
            self.polling = await self.poll_signalq.get()
            self.base.print_message("polling signal received")

    async def send(self, pump_name: str, cmd: str):
        if not cmd.endswith("\r"):
            cmd = cmd + "\r"
        addr = self.config_dict["pumps"][pump_name]["address"]
        command_str = f"{addr:02}@{cmd}"
        while self.com_lock:
            await asyncio.sleep(0.1)
        self.com_lock = True
        self.sio.write(command_str)
        self.sio.flush()
        resp = [x.strip() for x in self.sio.readlines() if x.strip()]
        # look for "\x11" end of response character when POLL is on
        if resp:
            while not resp[-1].endswith("\x11"):
                time.sleep(0.1)  # wait 100 msec and re-read, response
                newlines = [x.strip() for x in self.sio.readlines() if x.strip()]
                resp += newlines
        self.com_lock = False
        return resp

    async def poll_sensor_loop(self, frequency: int = 10):
        self.base.print_message("polling background task has started")
        waittime = 1.0 / frequency
        lastupdate = 0
        while True:
            if self.polling:
                for plab, pdict in self.config_dict.get("pumps", {}).items():
                    checktime = time.time()
                    if checktime - lastupdate < waittime:
                        # self.base.print_message("waiting for minimum update interval.")
                        await asyncio.sleep(waittime - (checktime - lastupdate))
                    addr = pdict["address"]
                    status_resp = await self.send(plab, "status")
                    # self.base.print_message(f"received status: {status_resp}")
                    lastupdate = time.time()
                    status_prompt = status_resp[-1]
                    status = status_resp[0]
                    # self.base.print_message(f"current status: {status}")
                    addrstate_rate, pumptime, pumpvol, flags = status.split()
                    raddr = int(addrstate_rate[:2])
                    # self.base.print_message(
                    #     f"received address: {raddr}, config address: {addr}"
                    # )
                    if addr == raddr:
                        state = None
                        state_split = None
                        for k, v in STATES.items():
                            if addrstate_rate[2:].startswith(k):
                                state_split = k
                            if status_prompt[2:].startswith(k):
                                state = v
                            else:
                                continue
                        if state != self.last_state:
                            self.base.print_message(
                                f"pump state changed from '{self.last_state}' to '{state}'"
                            )
                            self.last_state = state
                        rate = int(addrstate_rate.split(state_split)[-1])
                        pumptime = int(pumptime)
                        pumpvol = int(pumpvol)
                        # self.base.print_message(f"flags: {flags.lower()}")
                        (
                            motor_dir,
                            limit_status,
                            stall_status,
                            trig_input,
                            dir_port,
                            target_reached,
                        ) = flags.lower()
                        status_dict = {
                            plab: {
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
                        }
                        # self.base.print_message(status_dict[plab]["status"])
                        await self.base.put_lbuf(status_dict)
                        # self.base.print_message("status sent to live buffer")
                    else:
                        self.base.print_message("pump address does not match config")
                # await asyncio.sleep(0.01)
            else:
                await asyncio.sleep(0.05)

    def update_status_from_response(self, response):
        status = response[0]
        addr_status = status.split()[0]
        addr = int(addr_status[:2])
        pump_name = [
            k for k, d in self.config_dict["pumps"].items() if int(d["address"]) == addr
        ][0]
        state = "unknown"
        for k, v in STATES.items():
            if addr_status[2:].startswith(k):
                state = v
                break
            else:
                continue
        self.base.print_message(f"command response returned status: {state}")
        status_dict = {"status": state}
        self.base.live_buffer[pump_name][0].update(status_dict)

    async def start_pump(self, pump_name: str, direction: int):
        "Start motion in direction forward/infuse (1) or reverse/withdraw (-1)"
        if direction == 1:
            cmd = "irun"
        elif direction == -1:
            cmd = "wrun"
        else:
            return False
        resp = await self.send(pump_name, cmd)
        self.update_status_from_response(resp)
        return resp

    async def set_force(self, pump_name: str, force_val: int):
        "Set infusion force value in percentage"
        cmd = f"forc {force_val}"
        resp = await self.send(pump_name, cmd)
        self.update_status_from_response(resp)
        return resp

    async def set_rate(self, pump_name: str, rate_val: int, direction: int):
        "Set infusion|withdraw rate in uL/sec"
        if direction == 1:
            cmd = "irate"
        elif direction == -1:
            cmd = "wrate"
        else:
            return False
        resp = await self.send(pump_name, f"{cmd} {rate_val} ul/sec")
        self.update_status_from_response(resp)
        return resp

    async def set_target_volume(self, pump_name: str, vol_val: float):
        "Set infusion|withdraw volume in uL"
        resp = await self.send(pump_name, f"tvolume {vol_val} ul")
        self.update_status_from_response(resp)
        return resp

    async def set_diameter(self, pump_name: str, diameter_mm: float):
        "Set syringe diameter in mm"
        resp = await self.send(pump_name, f"diameter {diameter_mm:.4f}")
        self.update_status_from_response(resp)
        return resp

    # def set_ramp(self, pump_name: str, start_rate: int, end_rate: int, direction: int):
    #     "Set infusion|withdraw ramp rate in units TODO"
    #     pass

    async def clear_time(self, pump_name: Optional[str] = None, direction: Optional[int] = 0):
        if direction == 1:
            cmd = "citime"
        elif direction == -1:
            cmd = "cwtime"
        else:
            cmd = "ctime"
        if pump_name is None:
            for cpump_name in self.config_dict.get("pump_addrs", {}).keys():
                resp = await self.send(cpump_name, cmd)
                self.update_status_from_response(resp)
            return []
        else:
            resp = await self.send(pump_name, cmd)
            self.update_status_from_response(resp)
            return resp

    async def clear_volume(
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
                resp = await self.send(cpump_name, cmd)
                self.update_status_from_response(resp)
            return []
        else:
            if direction != 0 and direction is not None:
                resp = await self.send(pump_name, cmd[1:])
                vol_resp = resp[0].split(":")[-1]
                vol_val, vol_units = vol_resp.lower().split()
                vol_val = float(vol_val)
                direct_vol_ul = vol_val * ulmap[vol_units] * direction * -1
                self.present_volume_ul += direct_vol_ul
            resp = await self.send(pump_name, cmd)
            self.update_status_from_response(resp)
            return resp

    async def clear_target_volume(self, pump_name: Optional[str] = None):
        if pump_name is None:
            for cpump_name in self.config_dict.get("pump_addrs", {}).keys():
                resp = await self.send(cpump_name, "ctvolume")
                self.update_status_from_response(resp)
            return []
        else:
            resp = await self.send(pump_name, "ctvolume")
            self.update_status_from_response(resp)
            return resp

    async def stop_pump(self, pump_name: Optional[str] = None):
        cmd = "stp"
        if pump_name is None:
            for cpump_name in self.config_dict.get("pump_addrs", {}).keys():
                resp = await self.send(cpump_name, cmd)
                self.update_status_from_response(resp)
            return []
        else:
            resp = await self.send(pump_name, cmd)
            self.update_status_from_response(resp)
            return resp

    async def safe_state(self):
        for plab, pdict in self.config_dict.get("pumps", {}).items():
            addr = pdict["address"]
            idle_resp = f"{addr:02}:\x11"
            poll_resp = await self.send(plab, "poll on")
            if poll_resp[-1] != idle_resp:
                self.base.print_message(f"Error setting pump '{plab}' to 'POLL on'.")
                self.base.print_message(f"Server returned: {poll_resp[0]}")
            nvram_resp = await self.send(plab, "nvram off")
            if nvram_resp[-1] != idle_resp:
                self.base.print_message(f"Error setting pump '{plab}' to 'NVRAM off'.")
                self.base.print_message(f"Server returned: {nvram_resp[0]}")
            stop_resp = await self.stop_pump(plab)
            if stop_resp[-1] != idle_resp:
                self.base.print_message(f"Error stopping pump '{plab}'.")
                self.base.print_message(f"Server returned: {stop_resp[0]}")
            cleartime_resp = await self.clear_time(plab)
            if cleartime_resp[-1] != idle_resp:
                self.base.print_message(
                    f"Error clearing time params for pump '{plab}'."
                )
                self.base.print_message(f"Server returned: {cleartime_resp[0]}")
            clearvol_resp = await self.clear_target_volume(plab)
            if clearvol_resp[-1] != idle_resp:
                self.base.print_message(
                    f"Error clearing volume params for pump '{plab}'."
                )
                self.base.print_message(f"Server returned: {clearvol_resp[0]}")
            diameter_resp = await self.set_diameter(plab, pdict["diameter"])
            if diameter_resp[-1] != idle_resp:
                self.base.print_message(
                    f"Error setting syringe diameter on pump '{plab}'."
                )
                self.base.print_message(f"Server returned: {diameter_resp[0]}")
            self.update_status_from_response(diameter_resp)

    async def shutdown(self):
        # this gets called when the server is shut down
        # or reloaded to ensure a clean
        # disconnect ... just restart or terminate the server
        self.base.print_message("shutting down syringe pump(s)")
        await self.safe_state()
        self.com.close()


class PumpExec(Executor):
    def __init__(self, direction: int, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.direction = direction
        # current plan is 1 pump per COM
        self.pump_name = list(self.active.base.server_params["pumps"].keys())[0]
        self.active.base.print_message("PumpExec initialized.")

    async def _pre_exec(self):
        "Set rate and volume params, then run."
        self.active.base.print_message("PumpExec running setup methods.")
        rate_resp = await self.active.base.fastapp.driver.set_rate(
            pump_name=self.pump_name,
            rate_val=self.active.action.action_params["rate_uL_sec"],
            direction=self.direction,
        )
        self.active.base.print_message(f"set_rate returned: {rate_resp}")
        vol_resp = await self.active.base.fastapp.driver.set_target_volume(
            pump_name=self.pump_name,
            vol_val=self.active.action.action_params["volume_uL"],
        )
        self.active.base.print_message(f"set_target_volume returned: {vol_resp}")
        return {"error": ErrorCodes.none}

    async def _exec(self):
        start_resp = await self.active.base.fastapp.driver.start_pump(
            pump_name=self.pump_name,
            direction=self.direction,
        )
        self.active.base.print_message(f"start_pump returned: {start_resp}")
        return {"error": ErrorCodes.none}

    async def _poll(self):
        live_buffer, _ = self.active.base.get_lbuf(self.pump_name)
        pump_status = live_buffer["status"]
        # self.active.base.print_message(f"poll iter status: {pump_status}")
        await asyncio.sleep(0.01)
        if pump_status in ["infusing", "withdrawing"]:
            return {"error": ErrorCodes.none, "status": HloStatus.active}
        elif pump_status == "stalled":
            return {"error": ErrorCodes.motor, "status": HloStatus.errored}
        else:
            return {"error": ErrorCodes.none, "status": HloStatus.finished}

    async def _manual_stop(self):
        stop_resp = await self.active.base.fastapp.driver.stop_pump(self.pump_name)
        self.active.base.print_message(f"stop_pump returned: {stop_resp}")
        return {"error": ErrorCodes.none}

    async def _post_exec(self):
        self.active.base.print_message("PumpExec running cleanup methods.")
        clearvol_resp = await self.active.base.fastapp.driver.clear_volume(
            pump_name=self.pump_name,
            direction=self.direction,
        )
        self.active.base.print_message(f"clear_volume returned: {clearvol_resp}")
        cleartar_resp = await self.active.base.fastapp.driver.clear_target_volume(
            pump_name=self.pump_name,
        )
        self.active.base.print_message(f"clear_target_volume returned: {cleartar_resp}")
        return {"error": ErrorCodes.none}


# volume tracking notes
# 1. init volume at 0, need endpoint for user to tell initial volume
# 2. clear target vol is not necessary, but clear infused/withdrawn volume is needed before starting next syringe action
# 3. withdraw will add to volume tracker
# 4. infuse will remove from volume tracker
