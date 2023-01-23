""" A device class for the AliCat mass flow controller.

This device class uses the python implementation from https://github.com/numat/alicat
which has been added to the 'helao' conda environment. The default gas list included in
the module code differs from our MFC at G16 (i-C4H10), G25 (He-25), and G26 (He-75).
Update the gas list registers in case any of the 3 gases are used.

"""

__all__ = ["AliCatMFC", "MfcExec"]

import time
import asyncio
from typing import Union, Optional

from helaocore.error import ErrorCodes
from helao.servers.base import Base, Executor
from helaocore.models.hlostatus import HloStatus
from helao.helpers.sample_api import UnifiedSampleDataAPI

from alicat import FlowController, FlowMeter


# setup pressure control and ramping


class HelaoFlowMeter(FlowMeter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def get_status(self):
        self._test_controller_open()
        command = "{addr}\r".format(addr=self.address)
        line = self._write_and_read(command, retries)
        spl = line.split()
        address, values = spl[0], spl[1:]
        while values[-1].upper() in ["MOV", "VOV", "POV"]:
            del values[-1]
        if address != self.address:
            raise ValueError("Flow controller address mismatch.")
        if len(values) == 5 and len(self.keys) == 6:
            del self.keys[-2]
        elif len(values) == 7 and len(self.keys) == 6:
            self.keys.insert(5, "total flow")
        elif len(values) == 2 and len(self.keys) == 6:
            self.keys.insert(1, "setpoint")
        return {
            k: (v if k == self.keys[-1] else float(v))
            for k, v in zip(self.keys, values)
        }


class HelaoFlowController(FlowController, HelaoFlowMeter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class AliCatMFC:
    def __init__(self, action_serv: Base):

        self.base = action_serv
        self.config_dict = action_serv.server_cfg["params"]

        self.unified_db = UnifiedSampleDataAPI(self.base)

        self.fcs = {}
        self.fcinfo = {}

        for dev_name, dev_dict in self.config_dict.get("devices", {}).items():

            self.fcs[dev_name] = HelaoFlowController(
                port=dev_dict["port"], address=dev_dict["unit_id"]
            )
            # setpoint control mode: serial
            self._send(dev_name, "lsss")
            # close valves and hold
            self._send(dev_name, "hc")
            # retrieve gas list
            gas_resp = self._send(dev_name, "??g*")
            # device information (model, serial, calib date...)
            mfg_resp = self._send(dev_name, "??m*")

            gas_list = [
                x.replace(f"{dev_dict['unit_id']} G", "").strip() for x in gas_resp
            ]
            gas_dict = {int(gas.split()[0]): gas.split()[-1] for gas in gas_list}

            mfg_list = [
                x.replace(f"{dev_dict['unit_id']} M", "").strip() for x in mfg_resp
            ]
            mfg_dict = {
                " ".join(line.split()[:-1]): line.split()[-1] for line in mfg_list
            }

            self.fcinfo[dev_name] = {"gases": gas_dict, "info": mfg_dict}

        self.base.print_message(f"Managing {len(self.fcs)} devices:\n{self.fcs.keys()}")
        # query status with self.mfc.get()
        # query pid settings with self.mfc.get_pid()

        self.aloop = asyncio.get_running_loop()
        self.polling = False
        self.poll_signalq = asyncio.Queue(1)
        self.poll_signal_task = self.aloop.create_task(self.poll_signal_loop())
        self.polling_task = self.aloop.create_task(self.poll_sensor_loop())
        self.last_state = "unknown"

    def _send(self, device_name: str, command: str):
        unit_id = self.config_dict["devices"][device_name]["unit_id"]
        if not command.endswith("\r"):
            command += "\r"
        lines = []
        lines.append(
            self.fcs[device_name]._write_and_read(f"{unit_id.upper()}{command}")
        )
        next_line = self.fcs[device_name]._readline()
        while next_line.strip() != "":
            lines.append(next_line)
            next_line = self.fcs[device_name]._readline()
        self.fcs[device_name].flush()
        return lines

    async def start_polling(self):
        self.base.print_message("got 'start_polling' request, raising signal")
        await self.poll_signalq.put(True)

    async def stop_polling(self):
        self.base.print_message("got 'stop_polling' request, raising signal")
        await self.poll_signalq.put(False)

    async def poll_signal_loop(self):
        while True:
            self.polling = await self.poll_signalq.get()
            self.base.print_message("polling signal received")

    async def poll_sensor_loop(self, waittime: float = 0.05):
        self.polling = True
        self.base.print_message("MFC background task has started")
        lastupdate = 0
        while True:
            for dev_name, fc in self.fcs.items():
                self.base.print_message(f"Refreshing {dev_name} MFC")
                fc.flush()
                if self.polling:
                    checktime = time.time()
                    self.base.print_message(f"{dev_name} MFC checked at {checktime}")
                    if checktime - lastupdate < waittime:
                        self.base.print_message("waiting for minimum update interval.")
                        await asyncio.sleep(waittime - (checktime - lastupdate))
                    self.base.print_message(f"Retrieving {dev_name} MFC status")
                    resp_dict = fc.get_status()
                    self.base.print_message(
                        f"Received {dev_name} MFC status:\n{resp_dict}"
                    )
                    status_dict = {dev_name: resp_dict}
                    lastupdate = time.time()
                    self.base.print_message(f"Live buffer updated at {checktime}")
                    await self.base.put_lbuf(status_dict)
                    self.base.print_message("status sent to live buffer")
                await asyncio.sleep(waittime)

    def list_gases(self, device_name: str):
        return self.fcinfo.get(device_name, {}).get("gases", {})

    def set_pressure(self, device_name: str, pressure_psia: float):
        resp = self.fcs[device_name].set_pressure(pressure_psia)
        return resp

    def set_flowrate(self, device_name: str, flowrate_sccm: float):
        resp = self.fcs[device_name].set_flow_rate(flowrate_sccm)
        return resp

    def set_gas(self, device_name: str, gas: Union[int, str]):
        "Set MFC to pure gas"
        resp = self.fcs[device_name].set_gas(gas)
        return resp

    def set_gas_mixture(self, device_name: str, gas_dict: dict):
        "Set MFC to gas mixture defined in gas_dict {gasname: integer_pct}"
        if sum(gas_dict.values()) != 100:
            self.base.print_message("Gas mixture percentages do not add to 100.")
            return {}
        else:
            self.fcs[device_name].delete_mix(236)
            self.fcs[device_name].create_mix(
                mix_no=236, name="HELAO_mix", gases=gas_dict
            )
            resp = self.fcs[device_name].set_gas(236)
            return resp

    def lock_display(self, device_name: Optional[str] = None):
        """Lock the front display."""
        if device_name is None:
            resp = []
            for dev_name, fc in self.fcs.items():
                lock_resp = fc.lock()
                resp.append({dev_name: lock_resp})
        else:
            resp = self.fcs[device_name].lock()
        return resp

    def unlock_display(self, device_name: Optional[str] = None):
        """Unlock the front display."""
        if device_name is None:
            resp = []
            for dev_name, fc in self.fcs.items():
                unlock_resp = fc.unlock()
                resp.append({dev_name: unlock_resp})
        else:
            resp = self.fcs[device_name].unlock()
        return resp

    def hold_valve(self, device_name: Optional[str] = None):
        """Hold the valve in its current position."""
        if device_name is None:
            resp = []
            for dev_name, fc in self.fcs.items():
                hold_resp = fc.hold()
                resp.append({dev_name: hold_resp})
        else:
            resp = self.fcs[device_name].hold()
        return resp

    def hold_valve_closed(self, device_name: Optional[str] = None):
        """Close valve and hold."""
        if device_name is None:
            resp = []
            for dev_name, _ in self.fcs.items():
                chold_resp = self._send(dev_name, "c")
                resp.append({dev_name: chold_resp})
        else:
            resp = self._send(device_name, "c")
        return resp

    def hold_cancel(self, device_name: Optional[str] = None):
        """Cancel the valve hold."""
        if device_name is None:
            resp = []
            for dev_name, fc in self.fcs.items():
                cancel_resp = fc.cancel_hold()
                resp.append({dev_name: cancel_resp})
        else:
            resp = self.fcs[device_name].cancel_hold()
        return resp

    def tare_volume(self, device_name: Optional[str] = None):
        """Tare volumetric flow. Ensure mfc is isolated."""
        if device_name is None:
            resp = []
            for dev_name, fc in self.fcs.items():
                tarev_resp = fc.tare_pressure()
                resp.append({dev_name: tarev_resp})
        else:
            resp = self.fcs[device_name].tare_volumetric()
        return resp

    def tare_pressure(self, device_name: Optional[str] = None):
        """Tare absolute pressure."""
        if device_name is None:
            resp = []
            for dev_name, fc in self.fcs.items():
                tarep_resp = fc.tare_pressure()
                resp.append({dev_name: tarep_resp})
        else:
            resp = self.fcs[device_name].tare_pressure()
        return resp

    def reset_totalizer(self, device_name: Optional[str] = None):
        """Reset totalizer, if totalizer functionality included."""
        if device_name is None:
            resp = []
            for dev_name, fc in self.fcs.items():
                reset_resp = fc.reset_totalizer()
                resp.append({dev_name: reset_resp})
        else:
            resp = self.fcs[device_name].reset_totalizer()
        return resp

    def manual_query_status(self, device_name: str):
        return self.fcs[device_name].get_status()

    def shutdown(self):
        # this gets called when the server is shut down or reloaded to ensure a clean
        # disconnect ... just restart or terminate the server
        self.base.print_message("closing MFC connections")
        for fc in self.fcs.values():
            fc.close()


class MfcExec(Executor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # current plan is 1 flow controller per COM
        self.device_name = list(self.active.base.server_params["devices"].keys())[0]
        self.active.base.print_message("MFCExec initialized.")
        self.start_time = time.time()
        self.duration = kwargs.get("duration", -1)
        self.exid = self.device_name

    async def _pre_exec(self):
        "Set flow rate."
        self.active.base.print_message("MFCExec running setup methods.")
        flowrate_sccm = self.active.action.action_params.get("flowrate_sccm", None)
        if flowrate_sccm is not None:
            rate_resp = self.active.base.fastapp.driver.set_flowrate(
                device_name=self.device_name,
                flowrate_sccm=flowrate_sccm,
            )
            self.active.base.print_message(f"set_flowrate returned: {rate_resp}")
        return {"error": ErrorCodes.none}

    async def _exec(self):
        "Cancel valve hold."
        self.start_time = time.time()
        openvlv_resp = self.active.base.fastapp.driver.hold_cancel(
            device_name=self.device_name,
        )
        self.active.base.print_message(f"hold_cancel returned: {openvlv_resp}")
        return {"error": ErrorCodes.none}

    async def _poll(self):
        """Read flow from live buffer."""
        live_dict, epoch_s = self.active.base.get_lbuf(self.device_name)
        live_dict["epoch_s"] = epoch_s
        iter_time = time.time()
        if self.duration < 0 or iter_time - self.start_time < self.duration:
            status = HloStatus.active
        else:
            status = HloStatus.finished
        return {
            "error": ErrorCodes.none,
            "status": status,
            "data": live_dict,
        }

    async def _manual_stop(self):
        stop_resp = self.active.base.fastapp.driver.stop_pump(self.device_name)
        self.active.base.print_message(f"stop_pump returned: {stop_resp}")
        return {"error": ErrorCodes.none}

    async def _post_exec(self):
        "Restore valve hold."
        self.active.base.print_message("MFCExec running cleanup methods.")
        closevlv_resp = self.active.base.fastapp.driver.hold_valve_closed(
            device_name=self.device_name,
        )
        self.active.base.print_message(f"hold_valve_closed returned: {closevlv_resp}")
        return {"error": ErrorCodes.none}


"""Notes:

Register diffs at G16,25,26
(returned by b"A??g*\r"):       (coded into alicat/serial.py):
A G00      Air                  Air
A G01       Ar                  Ar
A G02      CH4                  CH4
A G03       CO                  CO
A G04      CO2                  CO2
A G05     C2H6                  C2H6
A G06       H2                  H2
A G07       He                  He
A G08       N2                  N2
A G09      N2O                  N2O
A G10       Ne                  Ne
A G11       O2                  O2
A G12     C3H8                  C3H8
A G13   nC4H10                  n-C4H10
A G14     C2H2                  C2H2
A G15     C2H4                  C2H4
A G16   iC4H10                  i-C2H10
A G17       Kr                  K
A G18       Xe                  Xe
A G19      SF6                  SF6
A G20     C-25                  C-25
A G21     C-10                  C-10
A G22      C-8                  C-8
A G23      C-2                  C-2
A G24     C-75                  C-75
A G25    He-25                  A-75
A G26    He-75                  A-25
A G27    A1025                  A1025
A G28   Star29                  Star29
A G29      P-5                  P-5
A G140     C-15
A G141     C-20
A G142     C-50
A G143    He-50
A G144    He-90
A G145    Bio5M
A G146   Bio10M
A G147   Bio15M
A G148   Bio20M
A G149   Bio25M
A G150   Bio30M
A G151   Bio35M
A G152   Bio40M
A G153   Bio45M
A G154   Bio50M
A G155   Bio55M
A G156   Bio60M
A G157   Bio65M
A G158   Bio70M
A G159   Bio75M
A G160   Bio80M
A G161   Bio85M
A G162   Bio90M
A G163   Bio95M
A G164   EAN-32
A G165   EAN-36
A G166   EAN-40
A G167   HeOx20
A G168   HeOx21
A G169   HeOx30
A G170   HeOx40
A G171   HeOx50
A G172   HeOx60
A G173   HeOx80
A G174   HeOx99
A G175    EA-40
A G176    EA-60
A G177    EA-80
A G178    Metab
A G179   LG-4.5
A G180     LG-6
A G181     LG-7
A G182     LG-9
A G183   HeNe-9
A G184   LG-9.4
A G185   SynG-1
A G186   SynG-2
A G187   SynG-3
A G188   SynG-4
A G189   NatG-1
A G190   NatG-2
A G191   NatG-3
A G192    CoalG
A G193     Endo
A G194      HHO
A G195     HD-5
A G196    HD-10
A G197   OCG-89
A G198   OCG-93
A G199   OCG-95
A G200     FG-1
A G201     FG-2
A G202     FG-3
A G203     FG-4
A G204     FG-5
A G205     FG-6
A G206     P-10
A G210       D2
"""
