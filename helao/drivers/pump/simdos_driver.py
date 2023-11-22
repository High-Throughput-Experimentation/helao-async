""" A device class for the KNF SIMDOS RC-P series diaphragm pump.

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
            timeout=0.1,
        )

        self.aloop = asyncio.get_running_loop()
        self.polling = True
        self.poll_signalq = asyncio.Queue(1)
        self.poll_signal_task = self.aloop.create_task(self.poll_signal_loop())
        self.polling_task = self.aloop.create_task(self.poll_sensor_loop())
        self.present_volume_ul = 0.0
        self.last_state = "unknown"

    async def start_polling(self):
        self.base.print_message("got 'start_polling' request, raising signal")
        await self.poll_signalq.put(True)

    async def stop_polling(self):
        self.base.print_message("got 'stop_polling' request, raising signal")
        await self.poll_signalq.put(False)

    async def poll_signal_loop(self):
        self.safe_state()
        while True:
            self.polling = await self.poll_signalq.get()
            self.base.print_message("polling signal received")

    def send(self, cmd: str):
        addr = self.config_dict["address"]
        command_str = f"{addr:02}{cmd}"
        self.com.write(command_str)
        self.com.flush()
        resp = self.com.readlines()
        # keep only ack responses
        resp = [
            x
            for x in resp
            if x.decode("ascii").startswith("\x06\x02") and "\x03" in x.decode("ascii")
        ]
        # strip frame
        resp = [x.decode("ascii").strip("\x06\x02").split("\x03")[0] for x in resp]
        resp = [x for x in resp if x != ""]
        if not resp:
            self.base.print_message("command did not return a valid response")
            return None
        if len(resp)>1:
            self.base.print_message("command returned multiple responses, using first")
        return resp[0]

    def get_opstat(self):
        resp = self.send("?SS1")
        if resp is None:
            return {}
        state_dict = {}
        bits = str2bin(resp)
        for i, casetup in enumerate(OPSTAT):
            state_dict[i] = casetup[bits[i]]
        return state_dict

    def get_sysstat(self):
        resp = self.send("?SS2")
        if resp is None:
            return {}
        state_dict = {}
        bits = str2bin(resp)
        for i, casetup in enumerate(SYSTAT):
            state_dict[i] = casetup[bits[i]]
        return state_dict

    def get_runstat(self):
        resp = self.send("?SS3")
        if resp is None:
            return {}
        state_dict = {}
        bits = str2bin(resp)
        for i, casetup in enumerate(RUSTAT):
            state_dict[i] = casetup[bits[i]]
        return state_dict

    def get_dispstat(self):
        resp = self.send("?SS4")
        if resp is None:
            return {}
        state_dict = {}
        bits = str2bin(resp)
        for i, casetup in enumerate(DISTAT):
            state_dict[i] = casetup[bits[i]]
        return state_dict

    def get_faults(self):
        resp = self.send("?SS6")
        if resp is None:
            return {}
        state_dict = {}
        bits = str2bin(resp)
        for i, fault in enumerate(FADIAG):
            state_dict[i] = fault if bits[i] else "OK"
        return state_dict

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
                    status_resp = self.send(plab, "status")
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

    def shutdown(self):
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
        rate_resp = self.active.base.fastapp.driver.set_rate(
            pump_name=self.pump_name,
            rate_val=self.active.action.action_params["rate_uL_sec"],
            direction=self.direction,
        )
        self.active.base.print_message(f"set_rate returned: {rate_resp}")
        vol_resp = self.active.base.fastapp.driver.set_target_volume(
            pump_name=self.pump_name,
            vol_val=self.active.action.action_params["volume_uL"],
        )
        self.active.base.print_message(f"set_target_volume returned: {vol_resp}")
        return {"error": ErrorCodes.none}

    async def _exec(self):
        start_resp = self.active.base.fastapp.driver.start_pump(
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
        stop_resp = self.active.base.fastapp.driver.stop_pump(self.pump_name)
        self.active.base.print_message(f"stop_pump returned: {stop_resp}")
        return {"error": ErrorCodes.none}

    async def _post_exec(self):
        self.active.base.print_message("PumpExec running cleanup methods.")
        clearvol_resp = self.active.base.fastapp.driver.clear_volume(
            pump_name=self.pump_name,
            direction=self.direction,
        )
        self.active.base.print_message(f"clear_volume returned: {clearvol_resp}")
        cleartar_resp = self.active.base.fastapp.driver.clear_target_volume(
            pump_name=self.pump_name,
        )
        self.active.base.print_message(f"clear_target_volume returned: {cleartar_resp}")
        return {"error": ErrorCodes.none}


# volume tracking notes
# 1. init volume at 0, need endpoint for user to tell initial volume
# 2. clear target vol is not necessary, but clear infused/withdrawn volume is needed before starting next syringe action
# 3. withdraw will add to volume tracker
# 4. infuse will remove from volume tracker
