""" A device class for the AliCat mass flow controller.

This device class uses the python implementation from https://github.com/numat/alicat
and additional methods from https://documents.alicat.com/Alicat-Serial-Primer.pdf. The 
default gas list included in the module code differs from our MFC at G16 (i-C4H10),
G25 (He-25), and G26 (He-75). Update the gas list registers in case any of the 3 gases 
are used.

NOTE: Factory default control setpoint is analog and must be changed for driver operation.
Setpoint setup (Menu-Control-Setpoint_setup-Setpoint_source) has to be set to serial. 

"""

__all__ = ["AliCatMFC", "MfcExec", "PfcExec", "MfcConstPresExec"]

import time
import json
import asyncio
import serial
from collections import defaultdict
from typing import Union, Optional

import numpy as np

from helaocore.error import ErrorCodes
from helao.servers.base import Base
from helao.helpers.executor import Executor
from helaocore.models.hlostatus import HloStatus
from helao.helpers.make_str_enum import make_str_enum
from helao.helpers.sample_api import UnifiedSampleDataAPI
from helao.helpers.ws_subscriber import WsSyncClient as WSC

# setup pressure control and ramping


class AliCatMFC:
    def __init__(self, action_serv: Base):
        self.base = action_serv
        self.config_dict = action_serv.server_cfg.get("params", {})

        self.unified_db = UnifiedSampleDataAPI(self.base)

        self.fcs = {}
        self.fcinfo = {}

        for dev_name, dev_dict in self.config_dict.get("devices", {}).items():
            self.make_fc_instance(dev_name, dev_dict)

        self.dev_mfcs = make_str_enum("dev_mfcs", {key: key for key in self.fcs})

        self.base.print_message(f"Managing {len(self.fcs)} devices:\n{self.fcs.keys()}")
        # query status with self.mfc.get()
        # query pid settings with self.mfc.get_pid()

        self.aloop = asyncio.get_running_loop()
        self.polling = True
        self.poll_signalq = asyncio.Queue(1)
        self.poll_signal_task = self.aloop.create_task(self.poll_signal_loop())
        self.polling_task = self.aloop.create_task(self.poll_sensor_loop())
        self.last_state = "unknown"

    def make_fc_instance(self, device_name: str, device_config: dict):
        self.fcs[device_name] = FlowController(
            port=device_config["port"], address=device_config["unit_id"]
        )
        # setpoint control mode: serial
        self._send(device_name, "lsss")
        # close valves and hold
        self._send(device_name, "hc")
        # retrieve gas list
        gas_resp = self._send(device_name, "??g*")
        # device information (model, serial, calib date...)
        mfg_resp = self._send(device_name, "??m*")

        gas_list = [
            x.replace(f"{device_config['unit_id']} G", "").strip() for x in gas_resp
        ]
        gas_dict = {int(gas.split()[0]): gas.split()[-1] for gas in gas_list}

        mfg_list = [
            x.replace(f"{device_config['unit_id']} M", "").strip() for x in mfg_resp
        ]
        mfg_dict = {" ".join(line.split()[:-1]): line.split()[-1] for line in mfg_list}
        self.fcinfo[device_name] = {"gases": gas_dict, "info": mfg_dict}

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
        # async with self.base.aiolock:
        await self.poll_signalq.put(True)
        while not self.polling:
            self.base.print_message("waiting for polling loop to start")
            await asyncio.sleep(0.1)

    async def stop_polling(self):
        self.base.print_message("'stop_polling' has been disabled")
        # self.base.print_message("got 'stop_polling' request, raising signal")
        # async with self.base.aiolock:
        # await self.poll_signalq.put(False)
        # while self.polling:
        #     self.base.print_message("waiting for polling loop to stop")
        #     await asyncio.sleep(0.1)

    async def poll_signal_loop(self):
        while True:
            self.polling = await self.poll_signalq.get()
            self.base.print_message("polling signal received")

    async def poll_sensor_loop(self, waittime: float = 0.1):
        self.base.print_message("MFC background task has started")
        self.last_acquire = {dev_name: 0 for dev_name in self.fcs.keys()}
        lastupdate = 0
        while True:
            for dev_name, fc in self.fcs.items():
                try:
                # self.base.print_message(f"Refreshing {dev_name} MFC")
                # if self.polling:
                    fc.flush()
                    checktime = time.time()
                    if checktime - lastupdate < waittime:
                        await asyncio.sleep(waittime - (checktime - lastupdate))
                        resp_dict = fc.get_status()
                        self.base.print_message(
                            f"Received {dev_name} MFC status:\n{resp_dict}"
                        )
                        if all(
                            [
                                x in resp_dict
                                for x in (
                                    "mass_flow",
                                    "pressure",
                                    "setpoint",
                                    "control_point",
                                )
                            ]
                        ):
                            status_dict = {dev_name: resp_dict}
                            lastupdate = time.time()
                            self.base.print_message(f"Live buffer updated at {checktime}")
                            # async with self.base.aiolock:
                            await self.base.put_lbuf(status_dict)
                            # self.base.print_message("status sent to live buffer")
                        else:
                            self.base.print_message(
                                f"!!Received unexpected dict: {resp_dict}"
                            )
                            raise ValueError("unexpected response")
                except Exception as e:
                    del self.fcs[dev_name]
                    self.base.print_message(
                        f"Exception occured on get_status() {e}. Resetting MFC."
                    )
                    self.make_fc_instance(
                        dev_name, self.config_dict["device"][dev_name]
                    )
                await asyncio.sleep(0.01)

    def list_gases(self, device_name: str):
        return self.fcinfo.get(device_name, {}).get("gases", {})

    async def set_pressure(
        self,
        device_name: str,
        pressure_psia: float,
        ramp_psi_sec: Optional[float] = 0,
        *args,
        **kwargs,
    ):
        """Set control mode to pressure, set point = pressure_psi, ramping psi/sec or zero to disable."""
        resp = []
        await self.stop_polling()
        resp.append(self._send(device_name, f"SR {ramp_psi_sec} 4"))
        resp.append(self.fcs[device_name].set_pressure(pressure_psia))
        await self.start_polling()
        return resp

    async def set_flowrate(
        self,
        device_name: str,
        flowrate_sccm: float,
        ramp_sccm_sec: Optional[float] = 0,
        *args,
        **kwargs,
    ):
        """Set control mode to mass flow, set point = flowrate_scc, ramping flowrate_sccm or zero to disable."""
        resp = []
        await self.stop_polling()
        resp.append(self._send(device_name, f"SR {ramp_sccm_sec} 4"))
        resp.append(self.fcs[device_name].set_flow_rate(flowrate_sccm))
        await self.start_polling()
        return resp

    async def set_gas(self, device_name: str, gas: Union[int, str]):
        "Set MFC to pure gas"
        await self.stop_polling()
        resp = self.fcs[device_name].set_gas(gas)
        await self.start_polling()
        return resp

    async def set_gas_mixture(self, device_name: str, gas_dict: dict):
        "Set MFC to gas mixture defined in gas_dict {gasname: integer_pct}"
        if sum(gas_dict.values()) != 100:
            self.base.print_message("Gas mixture percentages do not add to 100.")
            return {}
        else:
            await self.stop_polling()
            self.fcs[device_name].delete_mix(236)
            self.fcs[device_name].create_mix(
                mix_no=236, name="HELAO_mix", gases=gas_dict
            )
            resp = self.fcs[device_name].set_gas(236)
            await self.start_polling()
            return resp

    async def lock_display(self, device_name: Optional[str] = None):
        """Lock the front display."""
        await self.stop_polling()
        if device_name is None:
            resp = []
            for dev_name, fc in self.fcs.items():
                lock_resp = fc.lock()
                resp.append({dev_name: lock_resp})
        else:
            resp = self.fcs[device_name].lock()
        await self.start_polling()
        return resp

    async def unlock_display(self, device_name: Optional[str] = None):
        """Unlock the front display."""
        await self.stop_polling()
        if device_name is None:
            resp = []
            for dev_name, fc in self.fcs.items():
                unlock_resp = fc.unlock()
                resp.append({dev_name: unlock_resp})
        else:
            resp = self.fcs[device_name].unlock()
        await self.start_polling()
        return resp

    async def hold_valve(self, device_name: Optional[str] = None):
        """Hold the valve in its current position."""
        await self.stop_polling()
        if device_name is None:
            resp = []
            for dev_name, fc in self.fcs.items():
                hold_resp = fc.hold()
                resp.append({dev_name: hold_resp})
        else:
            resp = self.fcs[device_name].hold()
        await self.start_polling()
        return resp

    async def hold_valve_closed(self, device_name: Optional[str] = None):
        """Close valve and hold."""
        await self.stop_polling()
        if device_name is None:
            resp = []
            for dev_name, _ in self.fcs.items():
                await self.set_flowrate(dev_name, 0)
                chold_resp = self._send(dev_name, "hc")
                resp.append({dev_name: chold_resp})
        else:
            resp = self._send(device_name, "hc")
        await self.start_polling()
        return resp

    async def hold_cancel(self, device_name: Optional[str] = None):
        """Cancel the valve hold."""
        await self.stop_polling()
        if device_name is None:
            resp = []
            for dev_name, fc in self.fcs.items():
                cancel_resp = fc.cancel_hold()
                resp.append({dev_name: cancel_resp})
        else:
            resp = self.fcs[device_name].cancel_hold()
        await self.start_polling()
        return resp

    async def tare_volume(self, device_name: Optional[str] = None):
        """Tare volumetric flow. Ensure mfc is isolated."""
        await self.stop_polling()
        if device_name is None:
            resp = []
            for dev_name, fc in self.fcs.items():
                tarev_resp = fc.tare_volumetric()
                resp.append({dev_name: tarev_resp})
        else:
            resp = self.fcs[device_name].tare_volumetric()
        await self.start_polling()
        return resp

    async def tare_pressure(self, device_name: Optional[str] = None):
        """Tare absolute pressure."""
        await self.stop_polling()
        if device_name is None:
            resp = []
            for dev_name, fc in self.fcs.items():
                tarep_resp = fc.tare_pressure()
                resp.append({dev_name: tarep_resp})
        else:
            resp = self.fcs[device_name].tare_pressure()
        await self.start_polling()
        return resp

    # def reset_totalizer(self, device_name: Optional[str] = None):
    #     """Reset totalizer, if totalizer functionality included."""
    #     if device_name is None:
    #         resp = []
    #         for dev_name, fc in self.fcs.items():
    #             reset_resp = fc.reset_totalizer()
    #             resp.append({dev_name: reset_resp})
    #     else:
    #         resp = self.fcs[device_name].reset_totalizer()
    #     return resp

    def manual_query_status(self, device_name: str):
        return self.base.get_lbuf(device_name)

    async def async_shutdown(self):
        """Await tasks prior to driver shutdown."""
        await self.stop_polling()
        await asyncio.sleep(0.5)
        self.base.print_message("stopping MFC flows")
        await self.hold_valve_closed()

    async def estop(self, *args, **kwargs):
        self.base.print_message("stopping MFC flows")
        await self.hold_valve_closed()
        return True

    def shutdown(self):
        # this gets called when the server is shut down or reloaded to ensure a clean
        # disconnect ... just restart or terminate the server
        # self.poll_signalq.put_nowait(False)
        self.base.print_message("closing MFC connections")
        for fc in self.fcs.values():
            fc.close()


class MfcExec(Executor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.start_time = time.time()
        self.device_name = self.active.action.action_params["device_name"]
        # current plan is 1 flow controller per COM
        self.active.base.print_message("MfcExec initialized.")
        self.duration = self.active.action.action_params.get("duration", -1)

    async def _pre_exec(self):
        "Set flow rate."
        self.active.base.print_message("MfcExec running setup methods.")
        self.flowrate_sccm = self.active.action.action_params.get("flowrate_sccm", None)
        self.ramp_sccm_sec = self.active.action.action_params.get("ramp_sccm_sec", 0)
        if self.flowrate_sccm is not None:
            rate_resp = await self.active.base.fastapp.driver.set_flowrate(
                device_name=self.device_name,
                flowrate_sccm=self.flowrate_sccm,
                ramp_sccm_sec=self.ramp_sccm_sec,
            )
            self.active.base.print_message(f"set_flowrate returned: {rate_resp}")
        return {"error": ErrorCodes.none}

    async def _exec(self):
        "Cancel valve hold."
        self.start_time = time.time()
        self.last_acq_time = self.start_time
        self.last_acq_flow = 0
        self.total_scc = 0
        if self.flowrate_sccm is not None:
            openvlv_resp = await self.active.base.fastapp.driver.hold_cancel(
                device_name=self.device_name,
            )
            self.active.base.print_message(f"hold_cancel returned: {openvlv_resp}")
        return {"error": ErrorCodes.none}

    async def _poll(self):
        """Read flow from live buffer."""
        live_dict, epoch_s = self.active.base.get_lbuf(self.device_name)
        live_dict["epoch_s"] = epoch_s
        live_flow = max(live_dict["mass_flow"], 0)
        iter_time = time.time()
        elapsed_time = iter_time - self.start_time
        self.total_scc += (
            (iter_time - self.last_acq_time) / 60 * (live_flow + self.last_acq_flow) / 2
        )
        self.last_acq_time = iter_time
        self.last_acq_flow = live_flow
        if (self.duration < 0) or (elapsed_time < self.duration):
            status = HloStatus.active
        else:
            status = HloStatus.finished
        await asyncio.sleep(0.01)
        return {
            "error": ErrorCodes.none,
            "status": status,
            "data": live_dict,
        }

    async def _post_exec(self):
        "Restore valve hold."
        self.active.base.print_message("MfcExec running cleanup methods.")
        self.active.action.action_params["total_scc"] = self.total_scc
        if not self.active.action.action_params.get("stay_open", False):
            closevlv_resp = await self.active.base.fastapp.driver.hold_valve_closed(
                device_name=self.device_name,
            )
            self.active.base.print_message(
                f"hold_valve_closed returned: {closevlv_resp}"
            )
        else:
            self.active.base.print_message("'stay_open' is True, skipping valve hold")
        return {"error": ErrorCodes.none}


class PfcExec(MfcExec):
    async def _pre_exec(self):
        "Set pressure."
        self.active.base.print_message("PfcExec running setup methods.")
        self.pressure_psia = self.active.action.action_params.get("pressure_psia", None)
        self.ramp_psi_sec = self.active.action.action_params.get("ramp_psi_sec", 0)
        if self.pressure_psia is not None:
            rate_resp = await self.active.base.fastapp.driver.set_pressure(
                device_name=self.device_name,
                pressure_psia=self.pressure_psia,
                ramp_psi_sec=self.ramp_psi_sec,
            )
            self.active.base.print_message(f"set_pressure returned: {rate_resp}")
        return {"error": ErrorCodes.none}

    async def _exec(self):
        "Cancel valve hold."
        self.start_time = time.time()
        self.last_acq_time = self.start_time
        self.last_acq_flow = 0
        self.total_scc = 0
        if self.pressure_psia is not None:
            openvlv_resp = await self.active.base.fastapp.driver.hold_cancel(
                device_name=self.device_name,
            )
            self.active.base.print_message(f"hold_cancel returned: {openvlv_resp}")
        return {"error": ErrorCodes.none}


class MfcConstPresExec(MfcExec):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_fill = self.start_time
        action_params = self.active.action.action_params
        self.target_pressure = action_params.get("target_pressure", 14.7)
        self.total_gas_scc = action_params.get("total_gas_scc", 7.0)
        self.flowrate_sccm = action_params.get("flowrate_sccm", 0.5)
        self.ramp_sccm_sec = action_params.get("ramp_sccm_sec", 0)
        self.refill_freq = action_params.get("refill_freq_sec", 10.0)
        self.filling = False
        self.fill_end = self.start_time

    def eval_pressure(self, pressure):
        if pressure > self.target_pressure:
            return False, False
        else:
            fill_scc = self.total_gas_scc * (1 - pressure / self.target_pressure)
            fill_time = 60.0 * fill_scc / self.flowrate_sccm
            return fill_time, fill_scc

    async def _pre_exec(self):
        "Set flow rate."
        self.active.base.print_message("MfcConstPresExec running setup methods.")
        rate_resp = await self.active.base.fastapp.driver.set_flowrate(
            device_name=self.device_name,
            flowrate_sccm=self.flowrate_sccm,
            ramp_sccm_sec=self.ramp_sccm_sec,
        )
        self.active.base.print_message(f"set_flowrate returned: {rate_resp}")
        return {"error": ErrorCodes.none}

    async def _exec(self):
        "Cancel valve hold."
        self.start_time = time.time()
        self.last_acq_time = self.start_time
        self.last_acq_flow = 0
        self.total_scc = 0
        return {"error": ErrorCodes.none}

    async def _poll(self):
        """Read flow from live buffer."""
        iter_time = time.time()
        live_dict, _ = self.active.base.get_lbuf(self.device_name)
        live_flow = max(live_dict["mass_flow"], 0)
        iter_time = time.time()
        elapsed_time = iter_time - self.start_time
        self.total_scc += (
            (iter_time - self.last_acq_time) / 60 * (live_flow + self.last_acq_flow) / 2
        )
        self.last_acq_time = iter_time
        self.last_acq_flow = live_flow
        fill_time, fill_scc = self.eval_pressure(live_dict["pressure"])
        if (
            fill_time
            and not self.filling
            and iter_time - self.last_fill >= self.refill_freq
        ):
            self.active.base.print_message(
                f"pressure below {self.target_pressure}, filling {fill_scc} scc over {fill_time} seconds"
            )
            self.filling = True
            openvlv_resp = await self.active.base.fastapp.driver.hold_cancel(
                device_name=self.device_name,
            )
            self.active.base.print_message(f"hold_cancel returned: {openvlv_resp}")
            self.fill_end = iter_time + fill_time
        elif self.filling and iter_time >= self.fill_end:
            self.active.base.print_message("target volume filled, closing mfc valve")
            closevlv_resp = await self.active.base.fastapp.driver.hold_valve_closed(
                device_name=self.device_name,
            )
            self.active.base.print_message(
                f"hold_valve_closed returned: {closevlv_resp}"
            )
            self.filling = False
            self.last_fill = iter_time
        elapsed_time = iter_time - self.start_time
        if (self.duration < 0) or (elapsed_time < self.duration):
            status = HloStatus.active
        else:
            status = HloStatus.finished
        await asyncio.sleep(0.01)
        return {
            "error": ErrorCodes.none,
            "status": status,
        }

    async def _post_exec(self):
        "Restore valve hold."
        self.active.base.print_message("MfcConstPresExec running cleanup methods.")
        self.active.action.action_params["total_scc"] = self.total_scc
        if not self.active.action.action_params.get("stay_open", False):
            closevlv_resp = await self.active.base.fastapp.driver.hold_valve_closed(
                device_name=self.device_name,
            )
            self.active.base.print_message(
                f"hold_valve_closed returned: {closevlv_resp}"
            )
        else:
            self.active.base.print_message("'stay_open' is True, skipping valve hold")
        return {"error": ErrorCodes.none}


class MfcConstConcExec(MfcExec):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_fill = self.start_time
        action_params = self.active.action.action_params
        self.target_co2_ppm = action_params.get("target_co2_ppm", 1e5)
        self.headspace_scc = action_params.get("headspace_scc", 7.5)
        self.flowrate_sccm = action_params.get("flowrate_sccm", 0.5)
        self.ramp_sccm_sec = action_params.get("ramp_sccm_sec", 0)
        self.refill_freq = action_params.get("refill_freq_sec", 10.0)
        self.filling = False
        self.fill_end = self.start_time

        self.co2serv_key = self.active.base.server_params.get("co2_server_name", None)
        self.active.base.print_message(
            f"checking config for co2 server named: {self.co2serv_key}"
        )
        co2serv_config = self.active.base.world_cfg["servers"].get(
            self.co2serv_key, None
        )
        if co2serv_config is None:
            return
        co2serv_host = co2serv_config.get("host", None)
        co2serv_port = co2serv_config.get("port", None)
        self.active.base.print_message(
            f"subscribing to {self.co2serv_key} at {co2serv_host}:{co2serv_port}"
        )

        self.wsc = WSC(co2serv_host, co2serv_port, "ws_live")

    def eval_conc(self):
        data_package = self.wsc.read_messages()
        while not data_package:
            data_package = self.wsc.read_messages()
            self.active.base.print_message(
                "No co2_ppm readings have been received, sleeping for 1 second"
            )
            time.sleep(1)
        data_dict = defaultdict(list)
        for datalab, (dataval, epochsec) in data_package.items():
            if datalab == "sim_dict":
                for k, v in dataval.items():
                    data_dict[k].append(v)
            elif isinstance(dataval, list):
                data_dict[datalab] += dataval
            else:
                data_dict[datalab].append(dataval)

        # self.active.base.print_message(f"got co2 data: {data_dict}")
        co2_vec = data_dict.get("co2_ppm", [])
        # self.active.base.print_message(
        #     f"got co2_ppm from {self.co2serv_key}: {co2_vec}"
        # )
        if len(co2_vec) > 10:  # default rate is 0.05, so 20 points per second
            co2_mean_ppm = np.mean(co2_vec[-10:])
        else:
            co2_mean_ppm = np.mean(co2_vec)

        fill_scc = self.headspace_scc * (self.target_co2_ppm - co2_mean_ppm) / 1e6
        fill_time = fill_scc / self.flowrate_sccm * 60.0
        return fill_time, fill_scc

    async def _pre_exec(self):
        "Set flow rate."
        self.active.base.print_message("MfcConstConcExec running setup methods.")
        rate_resp = await self.active.base.fastapp.driver.set_flowrate(
            device_name=self.device_name,
            flowrate_sccm=self.flowrate_sccm,
            ramp_sccm_sec=self.ramp_sccm_sec,
        )
        self.active.base.print_message(f"set_flowrate returned: {rate_resp}")
        return {"error": ErrorCodes.none}

    async def _exec(self):
        "Begin loop."
        self.start_time = time.time()
        self.last_acq_time = self.start_time
        self.last_acq_flow = 0
        self.total_scc = 0
        return {"error": ErrorCodes.none}

    async def _poll(self):
        """Read flow from live buffer."""
        iter_time = time.time()
        live_dict, _ = self.active.base.get_lbuf(self.device_name)
        live_flow = max(live_dict["mass_flow"], 0)
        iter_time = time.time()
        elapsed_time = iter_time - self.start_time
        self.total_scc += (
            (iter_time - self.last_acq_time) / 60 * (live_flow + self.last_acq_flow) / 2
        )
        self.last_acq_time = iter_time
        self.last_acq_flow = live_flow
        fill_time, fill_scc = self.eval_conc()
        # self.active.base.print_message(f"eval_conc() returned {fill_time}, {fill_scc}")
        if (
            fill_time > 0
            and not self.filling
            and iter_time - self.last_fill >= self.refill_freq
        ):
            self.active.base.print_message(
                f"filling {fill_scc} scc over {fill_time} seconds"
            )
            self.filling = True
            openvlv_resp = await self.active.base.fastapp.driver.hold_cancel(
                device_name=self.device_name,
            )
            self.active.base.print_message(f"hold_cancel returned: {openvlv_resp}")
            self.fill_end = iter_time + fill_time
        elif self.filling and iter_time >= self.fill_end:
            self.active.base.print_message("target volume filled, closing mfc valve")
            closevlv_resp = await self.active.base.fastapp.driver.hold_valve_closed(
                device_name=self.device_name,
            )
            self.active.base.print_message(
                f"hold_valve_closed returned: {closevlv_resp}"
            )
            self.filling = False
            self.last_fill = iter_time
        elapsed_time = iter_time - self.start_time
        if (self.duration < 0) or (elapsed_time < self.duration):
            status = HloStatus.active
        else:
            status = HloStatus.finished
        await asyncio.sleep(0.01)
        return {
            "error": ErrorCodes.none,
            "status": status,
        }

    async def _post_exec(self):
        "Restore valve hold."
        self.active.base.print_message("MfcConstConcExec running cleanup methods.")
        self.active.action.action_params["total_scc"] = self.total_scc
        if not self.active.action.action_params.get("stay_open", False):
            closevlv_resp = await self.active.base.fastapp.driver.hold_valve_closed(
                device_name=self.device_name,
            )
            self.active.base.print_message(
                f"hold_valve_closed returned: {closevlv_resp}"
            )
        else:
            self.active.base.print_message("'stay_open' is True, skipping valve hold")
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

"""Python driver for Alicat mass flow controllers, using serial communication.

Source code forked from https://github.com/numat/alicat/blob/master/alicat/serial.py
and modified to rename .get() method which conflicts with dictionary usage

Distributed under the GNU General Public License v2
Copyright (C) 2019 NuMat Technologies
"""


class FlowMeter(object):
    """Python driver for Alicat Flow Meters.

    [Reference](http://www.alicat.com/
    products/mass-flow-meters-and-controllers/mass-flow-meters/).

    This communicates with the flow meter over a USB or RS-232/RS-485
    connection using pyserial.
    """

    # A dictionary that maps port names to a tuple of connection
    # objects and the refcounts
    open_ports = {}

    def __init__(self, port="/dev/ttyUSB0", address="A"):
        """Connect this driver with the appropriate USB / serial port.

        Args:
            port: The serial port. Default '/dev/ttyUSB0'.
            address: The Alicat-specified address, A-Z. Default 'A'.
        """
        self.address = address
        self.port = port

        if port in FlowMeter.open_ports:
            self.connection, refcount = FlowMeter.open_ports[port]
            FlowMeter.open_ports[port] = (self.connection, refcount + 1)
        else:
            self.connection = serial.Serial(port, 19200, timeout=1.0)
            FlowMeter.open_ports[port] = (self.connection, 1)

        self.status_keys = [
            "pressure",
            "temperature",
            "volumetric_flow",
            "mass_flow",
            "setpoint",
            "gas",
        ]
        self.gases = [
            "Air",
            "Ar",
            "CH4",
            "CO",
            "CO2",
            "C2H6",
            "H2",
            "He",
            "N2",
            "N2O",
            "Ne",
            "O2",
            "C3H8",
            "n-C4H10",
            "C2H2",
            "C2H4",
            "i-C2H10",
            "Kr",
            "Xe",
            "SF6",
            "C-25",
            "C-10",
            "C-8",
            "C-2",
            "C-75",
            "A-75",
            "A-25",
            "A1025",
            "Star29",
            "P-5",
        ]

        self.open = True

    @classmethod
    def is_connected(cls, port, address="A"):
        """Return True if the specified port is connected to this device.

        This class can be used to automatically identify ports with connected
        Alicats. Iterate through all connected interfaces, and use this to
        test. Ports that come back True should be valid addresses.

        Note that this distinguishes between `FlowController` and `FlowMeter`.
        """
        is_device = False
        try:
            device = cls(port, address)
            try:
                c = device.get_status()
                if cls.__name__ == "FlowMeter":
                    assert c and "setpoint" not in device.status_keys
                elif cls.__name__ == "FlowController":
                    assert c and "setpoint" in device.status_keys
                else:
                    raise NotImplementedError("Must be meter or controller.")
                is_device = True
            finally:
                device.close()
        except Exception:
            pass
        return is_device

    def _test_controller_open(self):
        """Raise an IOError if the FlowMeter has been closed.

        Does nothing if the meter is open and good for read/write
        otherwise raises an IOError. This only checks if the meter
        has been closed by the FlowMeter.close method.
        """
        if not self.open:
            raise IOError(
                "The FlowController with address {} and \
                          port {} is not open".format(
                    self.address, self.port
                )
            )

    def get_status(self, retries=5):
        """Get the current state of the flow controller.

        From the Alicat mass flow controller documentation, this data is:
         * Pressure (normally in psia)
         * Temperature (normally in C)
         * Volumetric flow (in units specified at time of order)
         * Mass flow (in units specified at time of order)
         * Total flow (only on models with the optional totalizer function)
         * Currently selected gas

        Args:
            retries: Number of times to re-attempt reading. Default 2.
        Returns:
            The state of the flow controller, as a dictionary.

        """
        self._test_controller_open()

        command = "{addr}\r".format(addr=self.address)
        line = self._write_and_read(command, retries)
        spl = line.split()
        address, values = spl[0], spl[1:]

        # Mass/volume over range error.
        # Explicitly silenced because I find it redundant.
        while values[-1].upper() in ["MOV", "VOV", "POV"]:
            del values[-1]

        holdlockd = {}
        for stat, key in [("HLD", "hold_valve"), ("LCK", "lock_display")]:
            has_stat = stat in values
            holdlockd[key] = has_stat
            if has_stat:
                values.pop(values.index(stat))

        if address != self.address:
            raise ValueError("Flow controller address mismatch.")
        if len(values) == 5 and len(self.status_keys) == 6:
            del self.status_keys[-2]
        elif len(values) == 7 and len(self.status_keys) == 6:
            self.status_keys.insert(5, "total flow")
        elif len(values) == 2 and len(self.status_keys) == 6:
            self.status_keys.insert(1, "setpoint")
        return_dict = {
            k: (v if k == self.status_keys[-1] else float(v))
            for k, v in zip(self.status_keys, values)
        }
        return_dict.update(holdlockd)
        return_dict["acquire_time"] = time.time()

        return return_dict

    def set_gas(self, gas, retries=2):
        """Set the gas type.

        Args:
            gas: The gas type, as a string or integer. Supported strings are:
                'Air', 'Ar', 'CH4', 'CO', 'CO2', 'C2H6', 'H2', 'He', 'N2',
                'N2O', 'Ne', 'O2', 'C3H8', 'n-C4H10', 'C2H2', 'C2H4',
                'i-C2H10', 'Kr', 'Xe', 'SF6', 'C-25', 'C-10', 'C-8', 'C-2',
                'C-75', 'A-75', 'A-25', 'A1025', 'Star29', 'P-5'

                Gas mixes may only be called by their mix number.
        """
        self._test_controller_open()

        if isinstance(gas, int):
            return self._set_gas_number(gas, retries)
        else:
            return self._set_gas_name(gas, retries)

    def _set_gas_number(self, number, retries):
        """Set flow controller gas type by number.

        See supported gases in 'FlowController.gases'.
        """
        self._test_controller_open()
        command = "{addr}$${index}\r".format(addr=self.address, index=number)
        self._write_and_read(command, retries)

        reg46 = self._write_and_read("{addr}$$R46\r".format(addr=self.address), retries)
        reg46_gasbit = int(reg46.split()[-1]) & 0b0000000111111111

        if number != reg46_gasbit:
            raise IOError("Cannot set gas.")

    def _set_gas_name(self, name, retries):
        """Set flow controller gas type by name.

        See the Alicat manual for usage.
        """
        self._test_controller_open()
        if name not in self.gases:
            raise ValueError(f"{name} not supported!")
        command = "{addr}$${gas}\r".format(
            addr=self.address, gas=self.gases.index(name)
        )
        self._write_and_read(command, retries)

        reg46 = self._write_and_read("{addr}$$R46\r".format(addr=self.address), retries)
        reg46_gasbit = int(reg46.split()[-1]) & 0b0000000111111111

        if self.gases.index(name) != reg46_gasbit:
            raise IOError("Cannot set gas.")

    def create_mix(self, mix_no, name, gases, retries=2):
        """Create a gas mix.

        Gas mixes are made using COMPOSER software.
        COMPOSER mixes are only allowed for firmware 5v or greater.

        Args:
        mix_no: The mix number. Gas mixes are stored in slots 236-255.
        name: A name for the gas that will appear on the front panel.
        Names greater than six letters will be cut off.
        gases: A dictionary of the gas by name along with the associated
        percentage in the mix.
        """
        self._test_controller_open()

        read = "{addr}VE\r".format(addr=self.address)
        firmware = self._write_and_read(read, retries)
        if any(v in firmware for v in ["2v", "3v", "4v", "GP"]):
            raise IOError("This unit does not support COMPOSER gas mixes.")

        if mix_no < 236 or mix_no > 255:
            raise ValueError("Mix number must be between 236-255!")

        total_percent = sum(gases.values())
        if total_percent != 100:
            raise ValueError("Percentages of gas mix must add to 100%!")

        if any(gas not in self.gases for gas in gases):
            raise ValueError("Gas not supported!")

        gas_list = " ".join(
            [
                " ".join([str(percent), str(self.gases.index(gas))])
                for gas, percent in gases.items()
            ]
        )
        command = " ".join([self.address, "GM", name, str(mix_no), gas_list]) + "\r"

        line = self._write_and_read(command, retries)

        # If a gas mix is not successfully created, ? is returned.
        if line == "?":
            raise IOError("Unable to create mix.")

    def delete_mix(self, mix_no, retries=2):
        """Delete a gas mix."""
        self._test_controller_open()
        command = "{addr}GD{mixNumber}\r".format(addr=self.address, mixNumber=mix_no)
        line = self._write_and_read(command, retries)

        if line == "?":
            raise IOError("Unable to delete mix.")

    def lock(self, retries=2):
        """Lock the display."""
        self._test_controller_open()
        command = "{addr}$$L\r".format(addr=self.address)
        self._write_and_read(command, retries)

    def unlock(self, retries=2):
        """Unlock the display."""
        self._test_controller_open()
        command = "{addr}$$U\r".format(addr=self.address)
        self._write_and_read(command, retries)

    def tare_pressure(self, retries=2):
        """Tare the pressure."""
        self._test_controller_open()

        command = "{addr}$$PC\r".format(addr=self.address)
        line = self._write_and_read(command, retries)

        if line == "?":
            raise IOError("Unable to tare pressure.")

    def tare_volumetric(self, retries=2):
        """Tare volumetric flow."""
        self._test_controller_open()
        command = "{addr}$$V\r".format(addr=self.address)
        line = self._write_and_read(command, retries)

        if line == "?":
            raise IOError("Unable to tare flow.")

    def reset_totalizer(self, retries=2):
        """Reset the totalizer."""
        self._test_controller_open()
        command = "{addr}T\r".format(addr=self.address)
        self._write_and_read(command, retries)

    def flush(self):
        """Read all available information. Use to clear queue."""
        self._test_controller_open()

        self.connection.flush()
        self.connection.flushInput()
        self.connection.flushOutput()

    def close(self):
        """Close the flow meter. Call this on program termination.

        Also closes the serial port if no other FlowMeter object has
        a reference to the port.
        """
        if not self.open:
            return

        self.flush()

        if FlowMeter.open_ports[self.port][1] <= 1:
            self.connection.close()
            del FlowMeter.open_ports[self.port]
        else:
            connection, refcount = FlowMeter.open_ports[self.port]
            FlowMeter.open_ports[self.port] = (connection, refcount - 1)

        self.open = False

    def _write_and_read(self, command, retries=2):
        """Write a command and reads a response from the flow controller."""
        self._test_controller_open()

        for _ in range(retries + 1):
            self.connection.write(command.encode("ascii"))
            line = self._readline()
            if line:
                return line
        else:
            raise IOError("Could not read from flow controller.")

    def _readline(self):
        """Read a line using a custom newline character (CR in this case).

        Function from http://stackoverflow.com/questions/16470903/
        pyserial-2-6-specify-end-of-line-in-readline
        """
        self._test_controller_open()

        line = bytearray()
        while True:
            c = self.connection.read(1)
            if c:
                line += c
                if line[-1] == ord("\r"):
                    break
            else:
                break
        return line.decode("ascii").strip()


class FlowController(FlowMeter):
    """Python driver for Alicat Flow Controllers.

    [Reference](http://www.alicat.com/products/mass-flow-meters-and-
    controllers/mass-flow-controllers/).

    This communicates with the flow controller over a USB or RS-232/RS-485
    connection using pyserial.

    To set up your Alicat flow controller, power on the device and make sure
    that the "Input" option is set to "Serial".
    """

    registers = {
        "mass flow": 0b00100101,
        "vol flow": 0b00100100,
        "abs pressure": 0b00100010,
        "gauge pressure": 0b00100110,
        "diff pressure": 0b00100111,
    }

    def __init__(self, port="/dev/ttyUSB0", address="A"):
        """Connect this driver with the appropriate USB / serial port.

        Args:
            port: The serial port. Default '/dev/ttyUSB0'.
            address: The Alicat-specified address, A-Z. Default 'A'.
        """
        FlowMeter.__init__(self, port, address)
        try:
            self.control_point = self._get_control_point()
        except Exception:
            self.control_point = None

    def get_status(self, retries=5):
        """Get the current state of the flow controller.

        From the Alicat mass flow controller documentation, this data is:
         * Pressure (normally in psia)
         * Temperature (normally in C)
         * Volumetric flow (in units specified at time of order)
         * Mass flow (in units specified at time of order)
         * Flow setpoint (in units of control point)
         * Flow control point (either 'flow' or 'pressure')
         * Total flow (only on models with the optional totalizer function)
         * Currently selected gas

        Args:
            retries: Number of times to re-attempt reading. Default 2.
        Returns:
            The state of the flow controller, as a dictionary.

        """
        state = FlowMeter.get_status(self, retries)
        if state is None:
            return None
        state["control_point"] = self.control_point
        return state

    def set_flow_rate(self, flow, retries=2):
        """Set the target flow rate.

        Args:
            flow: The target flow rate, in units specified at time of purchase
        """
        if self.control_point in ["abs pressure", "gauge pressure", "diff pressure"]:
            self._set_setpoint(0, retries)
            self._set_control_point("mass flow", retries)
        self._set_setpoint(flow, retries)

    def set_pressure(self, pressure, retries=2):
        """Set the target pressure.

        Args:
            pressure: The target pressure, in units specified at time of
                purchase. Likely in psia.
        """
        if self.control_point in ["mass flow", "vol flow"]:
            self._set_setpoint(0, retries)
            self._set_control_point("abs pressure", retries)
        self._set_setpoint(pressure, retries)

    def hold(self, retries=2):
        """Override command to issue a valve hold.

        For a single valve controller, hold the valve at the present value.
        For a dual valve flow controller, hold the valve at the present value.
        For a dual valve pressure controller, close both valves.
        """
        self._test_controller_open()
        command = "{addr}$$H\r".format(addr=self.address)
        self._write_and_read(command, retries)

    def cancel_hold(self, retries=2):
        """Cancel valve hold."""
        self._test_controller_open()
        command = "{addr}$$C\r".format(addr=self.address)
        self._write_and_read(command, retries)

    def get_pid(self, retries=2):
        """Read the current PID values on the controller.

        Values include the loop type, P value, D value, and I value.
        Values returned as a dictionary.
        """
        self._test_controller_open()

        self.pid_keys = ["loop_type", "P", "D", "I"]

        command = "{addr}$$r85\r".format(addr=self.address)
        read_loop_type = self._write_and_read(command, retries)
        spl = read_loop_type.split()

        loopnum = int(spl[3])
        loop_type = ["PD/PDF", "PD/PDF", "PD2I"][loopnum]
        pid_values = [loop_type]
        for register in range(21, 24):
            value = self._write_and_read("{}$$r{}\r".format(self.address, register))
            value_spl = value.split()
            pid_values.append(value_spl[3])

        return {
            k: (v if k == self.pid_keys[-1] else str(v))
            for k, v in zip(self.pid_keys, pid_values)
        }

    def set_pid(self, p=None, i=None, d=None, loop_type=None, retries=2):
        """Set specified PID parameters.

        Args:
            p: Proportional gain
            i: Integral gain. Only used in PD2I loop type.
            d: Derivative gain
            loop_type: Algorithm option, either 'PD/PDF' or 'PD2I'

        This communication works by writing Alicat registers directly.
        """
        self._test_controller_open()
        if loop_type is not None:
            options = ["PD/PDF", "PD2I"]
            if loop_type not in options:
                raise ValueError(f"Loop type must be {options[0]} or {options[1]}.")
            command = "{addr}$$w85={loop_num}\r".format(
                addr=self.address, loop_num=options.index(loop_type) + 1
            )
            self._write_and_read(command, retries)
        if p is not None:
            command = "{addr}$$w21={v}\r".format(addr=self.address, v=p)
            self._write_and_read(command, retries)
        if i is not None:
            command = "{addr}$$w23={v}\r".format(addr=self.address, v=i)
            self._write_and_read(command, retries)
        if d is not None:
            command = "{addr}$$w22={v}\r".format(addr=self.address, v=d)
            self._write_and_read(command, retries)

    def _set_setpoint(self, setpoint, retries=2):
        """Set the target setpoint.

        Called by `set_flow_rate` and `set_pressure`, which both use the same
        command once the appropriate register is set.
        """
        self._test_controller_open()

        command = "{addr}S{setpoint:.2f}\r".format(addr=self.address, setpoint=setpoint)
        line = self._write_and_read(command, retries)
        try:
            current = float(line.split()[5])
        except IndexError:
            current = None
        if current is not None and abs(current - setpoint) > 0.01:
            # raise IOError("Could not set setpoint.")
            print("Could not set setpoint. Possibly ramping.")

    def _get_control_point(self, retries=2):
        """Get the control point, and save to internal variable."""
        command = "{addr}R122\r".format(addr=self.address)
        line = self._write_and_read(command, retries)
        if not line:
            return None
        value = int(line.split("=")[-1])
        try:
            return next(p for p, r in self.registers.items() if value == r)
        except StopIteration:
            raise ValueError("Unexpected register value: {:d}".format(value))

    def _set_control_point(self, point, retries=2):
        """Set whether to control on mass flow or pressure.

        Args:
            point: Either "flow" or "pressure".
        """
        if point not in self.registers:
            raise ValueError("Control point must be 'flow' or 'pressure'.")
        reg = self.registers[point]
        command = "{addr}W122={reg:d}\r".format(addr=self.address, reg=reg)
        line = self._write_and_read(command, retries)

        value = int(line.split("=")[-1])
        if value != reg:
            raise IOError("Could not set control point.")
        self.control_point = point


def command_line(args):
    """CLI interface, accessible when installed through pip."""

    flow_controller = FlowController(port=args.port, address=args.address)

    if args.set_gas:
        flow_controller.set_gas(args.set_gas)
    if args.set_flow_rate is not None and args.set_pressure is not None:
        raise ValueError("Cannot set both flow rate and pressure.")
    if args.set_flow_rate is not None:
        flow_controller.set_flow_rate(args.set_flow_rate)
    if args.set_pressure is not None:
        flow_controller.set_pressure(args.set_pressure)
    if args.lock:
        flow_controller.lock()
    if args.unlock:
        flow_controller.unlock()
    if args.hold:
        flow_controller.hold()
    if args.cancel_hold:
        flow_controller.cancel_hold()
    if args.reset_totalizer:
        flow_controller.reset_totalizer()
    state = flow_controller.get_status()
    if args.stream:
        try:
            print("time\t" + "\t".join(flow_controller.status_keys))
            t0 = time.time()
            while True:
                state = flow_controller.get_status()
                print(
                    "{:.2f}\t".format(time.time() - t0)
                    + "\t\t".join(
                        "{:.2f}".format(state[key])
                        for key in flow_controller.status_keys[:-1]
                    )
                    + "\t\t"
                    + state["gas"]
                )
        except KeyboardInterrupt:
            pass
    else:
        print(json.dumps(state, indent=2, sort_keys=True))
    flow_controller.close()
