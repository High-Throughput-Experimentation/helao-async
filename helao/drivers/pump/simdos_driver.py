""" A device class for the KNF SIMDOS RC-P series diaphragm pump.

"""

__all__ = []

import serial
import io
import time
import asyncio
from typing import Optional
from enum import IntEnum, Enum

# import traceback

from helaocore.models.hlostatus import HloStatus
from helaocore.error import ErrorCodes
from helao.servers.base import Base
from helao.helpers.executor import Executor


""" Notes:

Setup serial connection with pyserial module:
```
In [136]: ser = serial.Serial(port='COM12', baudrate=9600, timeout=0.1, parity='N', stopbits=1)
     ...: ser.write(b'\x0200?SI\x03U')
     ...: ser.flush()
     ...: resp = ser.read(100)
     ...: ser.close()
     ...: print(resp)
b'\x06\x0200\x03\x01'

hex bytes conversion
b = b'\x06'
bHex = b.hex()
bInt = int(bHex, 16)
bBin = f"{bInt:08b}"
print(bBin)
```

polling loop will check 5 states: operation, system, run mode, dispense mode, fault

"""

OPSTAT = [
    ("motor doesn't turn", "motor turns"),
    ("no pump fault", "pump fault"),
    ("display ON", "display OFF"),
]

SYSTAT = [
    ("motor not adjusted", "motor adjusted"),
    ("I/O 1 input low", "I/O 1 input high"),
    ("I/O 2 input low", "I/O 2 input high"),
    ("motor not on UT", "motor on UT"),
]

RUSTAT = [("run-mode stopped", "run-mode started")]

DISTAT = [
    ("dispense-mode stopped", "dispense-mode started"),
    ("", ""),
    ("", ""),
    ("user stop active", "user stop NOT active"),
]

FADIAG = [
    "overpressure",
    "reserved",
    "reserved",
    "analog signal under 4 mA",
    "power supply failure",
    "motor error",
    "temperature exceeded",
    "no encoder sensor signal",
]

class PumpMode(IntEnum):
    continuous = 0
    volume = 1
    rate = 2

class PumpParam(Enum):
    rate = "RV"
    time = "DT"
    volume = "DV"

PUMPLIMS = {
    PumpParam.rate: (30, 20000),
    PumpParam.time: (100, 99595999),
    PumpParam.volume: (30, 9999999)
    
}

def str2bin(val: str):
    try:
        bInt = int(val)
        bBin = f"{bInt:08b}"
        return [int(x) for x in bBin[::-1]]
    except Exception:
        print(f"could not parse string: {val}")
        return []


class SIMDOS:
    def __init__(self, action_serv: Base):
        self.base = action_serv
        self.config_dict = action_serv.server_cfg.get("params", {})
        # self.unified_db = UnifiedSampleDataAPI(self.base)
        # self.bokehapp = None

        # read pump addr and strings from config dict
        self.com = serial.Serial(
            port=self.config_dict["port"],
            baudrate=9600,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.5,
        )

        self.aloop = asyncio.get_running_loop()
        self.polling = True
        self.poll_signalq = asyncio.Queue(1)
        self.poll_signal_task = self.aloop.create_task(self.poll_signal_loop())
        self.polling_task = self.aloop.create_task(self.poll_sensor_loop())
        self.last_state = "unknown"

    async def start_polling(self):
        self.base.print_message("got 'start_polling' request, raising signal", info=True)
        try:
            async with asyncio.timeout(2):
                await self.poll_signalq.put(True)
            while not self.polling:
                self.base.print_message("waiting for polling loop to start", warn=True)
                await asyncio.sleep(0.1)
        except TimeoutError:
            if self.poll_signalq.full():
                self.poll_signalq.get_nowait()  # unsure if we should set polling directly, do normal put, or put_nowait
            self.polling = True
            self.base.print_message("could not raise start signal, forcing polling loop to start", warn=True)

    async def stop_polling(self):
        self.base.print_message("got 'stop_polling' request, raising signal", info=True)
        try:
            async with asyncio.timeout(2):
                await self.poll_signalq.put(False)
            while self.polling:
                self.base.print_message("waiting for polling loop to stop", warn=True)
                await asyncio.sleep(0.1)
        except TimeoutError:
            if self.poll_signalq.full():
                self.poll_signalq.get_nowait()
            self.polling = False
            self.base.print_message("could not raise start signal, forcing polling loop to stop", warn=True)


    async def poll_signal_loop(self):
        while True:
            self.polling = await self.poll_signalq.get()
            self.base.print_message("polling signal received")

    def send(self, cmd: str):
        addr = self.config_dict["address"]
        command_str = f"{addr:02}{cmd}"
        self.com.write(b"\x02" + command_str.encode() + b"\x03U")
        self.com.flush()
        full_resp = self.com.readlines()
        # keep only ack responses
        resp = [
            x
            for x in full_resp
            if x.decode("ascii").startswith("\x06")
        ]
        # strip frame
        resp = [x.decode("ascii").split("\x06\x02")[-1].split("\x03")[0] for x in resp]
        if not resp:
            self.base.print_message("command did not return a valid response")
            print(full_resp)
            return None
        if len(resp) > 1:
            self.base.print_message("command returned multiple responses, using first")
        return resp[0]

    def get_opstat(self):
        resp = self.send("?SS1")
        if resp is None:
            return {}
        state_dict = {}
        bits = str2bin(resp)
        for i, casetup in enumerate(OPSTAT):
            state_dict[i] = (casetup[bits[i]], bits[i])
        return state_dict

    def get_sysstat(self):
        resp = self.send("?SS2")
        if resp is None:
            return {}
        state_dict = {}
        bits = str2bin(resp)
        for i, casetup in enumerate(SYSTAT):
            state_dict[i] = (casetup[bits[i]], bits[i])
        return state_dict

    def get_runstat(self):
        resp = self.send("?SS3")
        if resp is None:
            return {}
        state_dict = {}
        bits = str2bin(resp)
        for i, casetup in enumerate(RUSTAT):
            state_dict[i] = (casetup[bits[i]], bits[i])
        return state_dict

    def get_dispstat(self):
        resp = self.send("?SS4")
        if resp is None:
            return {}
        state_dict = {}
        bits = str2bin(resp)
        for i, casetup in enumerate(DISTAT):
            state_dict[i] = (casetup[bits[i]], bits[i])
        return state_dict

    def get_faults(self):
        resp = self.send("?SS6")
        if resp is None:
            return {}
        state_dict = {}
        bits = str2bin(resp)
        for i, fault in enumerate(FADIAG):
            state_dict[i] = (fault if bits[i] else "OK", bits[i])
        return state_dict

    async def poll_sensor_loop(self, frequency: int = 10):
        self.base.print_message("polling background task has started")
        waittime = 1.0 / frequency
        lastupdate = 0
        while True:
            if self.polling:
                status_dict = {}
                for group, func in [
                    ("operation", self.get_opstat),
                    ("system", self.get_sysstat),
                    ("run", self.get_runstat),
                    ("dispense", self.get_dispstat),
                    ("fault", self.get_faults),
                ]:
                    checktime = time.time()
                    if checktime - lastupdate < waittime:
                        # self.base.print_message("waiting for minimum update interval.")
                        await asyncio.sleep(waittime - (checktime - lastupdate))

                    resp_dict = func()
                    # self.base.print_message(f"received status: {resp_dict}")
                    for k, v in resp_dict.items():
                        status_dict[f"{group}_{k}"] = v

                    lastupdate = time.time()

                await self.base.put_lbuf(status_dict)
                # await asyncio.sleep(0.01)

                faults = [
                    fk
                    for k, (fk, fv) in status_dict.items()
                    if k.startswith("fault_") and fv != 0
                ]
                if faults:
                    self.base.print_message(f"fault detected, stopping simdos executors")
                    for executor in self.base.executors.values():
                        executor.stop_action_task()

            else:
                await asyncio.sleep(0.05)

    def get_mode(self, retries: int = 5):
        retry_num = 5
        resp = self.send("?MS")
        while resp is None and retry_num < retries:
            resp = self.send("?MS")
            retry_num += 1
        if resp is None:
            return False
        return PumpMode(int(resp))

    def set_mode(self, mode: PumpMode):
        success = False
        modecmd = f"MS{int(mode)}"
        _ = self.send(modecmd)
        if self.get_mode() == mode:
            success = True
        else:
            self.base.print_message(f"could not set pump mode to {mode.name}")
        return success

    def get_run_param(self, param: PumpParam):
        parcmd = param.value
        resp = self.send(f"?{parcmd}")
        if resp is not None:
            return int(resp)
        else:
            self.base.print_message(f"could not validate {param.name}")
            return -1

    def set_run_param(self, param: PumpParam, val: int):
        success = False
        lo_lim, hi_lim = PUMPLIMS[param]
        parcmd = param.value
        if val < lo_lim or val > hi_lim:
            self.base.print_message(f"{param.name} setpoint is out of range [{lo_lim}, {hi_lim}]")
        else:
            resp = self.send(f"{parcmd}{val:08}")
            print(resp)
            check = None
            if resp is not None:
                check = self.send(f"?{parcmd}")
            if check is not None and int(check) == val:
                success = True
                self.base.print_message(f"successfully set {param.name} to {val}")
            else:
                self.base.print_message(f"could not validate {param.name} setpoint")
        return success

    async def stop(self):
        await self.stop_polling()
        success = False
        resp = self.send("KY0")
        await self.start_polling()
        if resp is not None:
            success = True
        return success

    async def start(self):
        await self.stop_polling()
        success = False
        resp = self.send("KY1")
        await self.start_polling()
        if resp is not None:
            success = True
        return success

    async def prime(self):
        await self.stop_polling()
        success = False
        resp = self.send("KY2")
        await self.start_polling()
        if resp is not None:
            success = True
        return success

    async def pause(self):
        await self.stop_polling()
        success = False
        resp = self.send("KY3")
        await self.start_polling()
        if resp is not None:
            success = True
        return success

    def shutdown(self):
        self.com.close()


class RunExec(Executor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # current plan is 1 pump per COM
        self.driver = self.active.base.fastapp.driver
        self.active.base.print_message("RunExec initialized.")
        self.start_time = time.time()
        self.duration = self.active.action.action_params["duration_sec"]

    async def _pre_exec(self):
        "Set rate and volume params, then run."
        self.active.base.print_message("RunExec running setup methods.")
        await self.driver.stop_polling()
        error = ErrorCodes.none
        mode = PumpMode.continuous
        setmode_resp = self.driver.set_mode(mode)
        if not setmode_resp:
            self.active.base.print_message(f"could not set pump mode to {mode.name}")
            error = ErrorCodes.cmd_error
        param = PumpParam.rate
        val = self.active.action.action_params["rate_uL_min"]
        setrate_resp = self.driver.set_run_param(param, val)
        if not setrate_resp:
            self.active.base.print_message(f"could not set pump {param.name} to {val}")
            error = ErrorCodes.cmd_error
        return {"error": error}

    async def _exec(self):
        error = ErrorCodes.none
        self.start_time = time.time()
        start_resp = await self.driver.start()
        if not start_resp:
            self.active.base.print_message("could not start pump")
            error = ErrorCodes.cmd_error
        await self.driver.start_polling()
        return {"error": error}

    async def _poll(self):
        iter_time = time.time()
        elapsed_time = iter_time - self.start_time
        status = HloStatus.active
        if (elapsed_time > self.duration) and (self.duration > 0):
            await self.driver.stop()
            status = HloStatus.finished
        return {"error": ErrorCodes.none, "status": status}

    async def _manual_stop(self):
        error = ErrorCodes.none
        stop_resp = await self.driver.stop()
        if not stop_resp:
            self.active.base.print_message("could not stop pump")
            error = ErrorCodes.cmd_error
        return {"error": error}

#     async def _post_exec(self):
#         self.active.base.print_message("PumpExec running cleanup methods.")
#         clearvol_resp = self.active.base.fastapp.driver.clear_volume(
#             pump_name=self.pump_name,
#             direction=self.direction,
#         )
#         self.active.base.print_message(f"clear_volume returned: {clearvol_resp}")
#         cleartar_resp = self.active.base.fastapp.driver.clear_target_volume(
#             pump_name=self.pump_name,
#         )
#         self.active.base.print_message(f"clear_target_volume returned: {cleartar_resp}")
#         return {"error": ErrorCodes.none}
