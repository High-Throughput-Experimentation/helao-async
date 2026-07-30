"""Alicat mass flow controller driver and HELAO executors.

Builds on a forked copy of the numat `alicat` serial driver (`FlowMeter`,
`FlowController` at the bottom of this module) and wraps it in `AliCatMFC`,
a `HelaoDriver` that owns one `FlowController` per configured device. The
paired `AliCatMFCPoller` publishes per-device status to the action server's
live buffer. Three `Executor` subclasses (`MfcExec`, `PfcExec`,
`MfcConstPresExec`, `MfcConstConcExec`) drive constant-flow, constant-pressure,
and concentration-feedback sequences.

NOTE: the factory default control setpoint on Alicat MFCs is analog and must
be changed to serial (Menu-Control-Setpoint_setup-Setpoint_source) for this
driver to operate. The default gas list shipped with `alicat` differs from
HELAO's units at G16 (i-C4H10), G25 (He-25), and G26 (He-75); update the gas
registers if those gases are used.
"""

__all__ = ["AliCatMFC", "AliCatMFCPoller", "MfcExec", "PfcExec", "MfcConstPresExec"]

import asyncio
import json
import time
from collections import defaultdict
from typing import Optional, Union

import numpy as np
import serial

from helao.core.drivers.helao_driver import (
    DriverPoller,
    DriverResponse,
    DriverResponseType,
    DriverStatus,
    HelaoDriver,
)
from helao.core.error import ErrorCodes
from helao.core.models.hlostatus import HloStatus
from helao.helpers import helao_logging as logging
from helao.helpers.executor import Executor
from helao.helpers.make_str_enum import make_str_enum
from helao.helpers.ws_utils import WsSyncClient as WSC

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class AliCatMFC(HelaoDriver):
    """HELAO ``HelaoDriver`` wrapper around one or more Alicat `FlowController` instances.

    Reads a `devices` dict from `config["devices"]`; each `FlowController` is
    opened by :meth:`connect`, not by construction. Always-on per-device status
    polling is handled by the paired :class:`AliCatMFCPoller`, wired in as the
    server's ``poller_class``. Exposes async helpers for setting flow/pressure,
    swapping gases, locking/unlocking the front panel, holding valves, and
    taring.

    Server config parameters:
        ``devices``: dict of ``{device_name: {"port": ..., "unit_id": ...}}``.
    """

    def __init__(self, config: dict = {}):
        """Store config; each `FlowController` is opened in :meth:`connect`.

        Args:
            config: Driver configuration (the server's ``params`` dict).
        """
        super().__init__(config=config)
        self.config_dict = self.config

        self.fcs = {}
        self.fcs_last_mode = {}
        self.fcinfo = {}

        # built from config alone (no device I/O) so endpoint typing is
        # available before connect() has opened any serial ports
        self.dev_mfcs = make_str_enum(
            "dev_mfcs", {key: key for key in self.config_dict.get("devices", {})}
        )

        self.polling = True
        self.last_state = "unknown"
        # Open the Alicat serial connections at construction. BaseAPI builds the
        # AliCatMFCPoller immediately after the driver and the poller AUTO-STARTS
        # its poll loop in __init__ -- but BaseAPI never calls connect(), so
        # deferring the serial open left self.fcs empty: the poller produced no
        # data, the live buffer key never appeared, and acquire_flowrate's
        # MfcExec._poll (get_lbuf) never advanced -> the capture hung. Connect
        # here (like the biologic/andor/SprintIR drivers) so the controllers are
        # open before the first poll; a bad/absent port logs a clear
        # "connect failed" instead. get_data() already no-ops on empty fcs.
        self.connect()

    def connect(self) -> DriverResponse:
        """Open every configured Alicat and query its gas/identity registers.

        Returns:
            ``DriverResponse`` reporting connection success or failure.
        """
        try:
            for dev_name, dev_dict in self.config_dict.get("devices", {}).items():
                self.make_fc_instance(dev_name, dev_dict)
            LOGGER.info(f"Managing {len(self.fcs)} devices:\n{self.fcs.keys()}")
            # query status with self.mfc.get()
            # query pid settings with self.mfc.get_pid()
            response = DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            LOGGER.error("connect failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        return response

    def get_status(self) -> DriverResponse:
        """Return whether any Alicat connections have been opened.

        Returns:
            ``DriverResponse`` with ``status=ok`` if at least one device is
            connected, else ``status=uninitialized``.
        """
        if self.fcs:
            return DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        return DriverResponse(
            response=DriverResponseType.success, status=DriverStatus.uninitialized
        )

    def stop(self) -> DriverResponse:
        """No active operation to abort; reports current status."""
        return DriverResponse(
            response=DriverResponseType.success, status=DriverStatus.ok
        )

    def reset(self) -> DriverResponse:
        """Force-close and reopen every Alicat connection."""
        self.disconnect()
        return self.connect()

    def disconnect(self) -> DriverResponse:
        """Close every Alicat serial connection."""
        try:
            for fc in self.fcs.values():
                fc.close()
            response = DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            LOGGER.error("disconnect failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        return response

    def make_fc_instance(self, device_name: str, device_config: dict):
        """Open a `FlowController` and cache its gas list and identity info.

        Sends `lsss` to force serial setpoint control, then queries `??g*` and
        `??m*` to populate `self.fcinfo[device_name]` with `gases` and `info`
        dicts.

        Args:
            device_name: Key used to look up this controller in `self.fcs`.
            device_config: Per-device config containing `port` and `unit_id`.
        """
        self.fcs[device_name] = FlowController(
            port=device_config["port"], address=device_config["unit_id"]
        )
        # setpoint control mode: serial
        self._send(device_name, "lsss")
        # close valves and hold
        # self._send(device_name, "hc")
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

    def _send(self, device_name: str, command: str) -> list:
        """Send a raw serial command to a controller and collect the multi-line reply.

        Args:
            device_name: Key in `self.fcs`.
            command: Command body; a trailing carriage return is added if
                missing. The unit_id prefix is prepended automatically.

        Returns:
            List of response lines (without the trailing blank line).
        """
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
        return lines

    async def start_polling(self):
        """Resume device polling (consulted by :class:`AliCatMFCPoller`)."""
        LOGGER.info("got 'start_polling' request")
        self.polling = True

    async def stop_polling(self):
        """Pause device polling so a raw write command doesn't race the poller."""
        LOGGER.info("got 'stop_polling' request")
        self.polling = False

    def get_device_status(self, device_name: str) -> Optional[dict]:
        """Read one status dict from a single flow controller, reconnecting on error.

        Mirrors the pre-migration `poll_sensor_loop` per-device branch: on a
        `get_status` exception the controller is rebuilt via `make_fc_instance`
        and its last known control point restored.

        Args:
            device_name: Key in `self.fcs`.

        Returns:
            The device's status dict, or `None` if the read failed or the
            returned dict was missing an expected key.
        """
        fc = self.fcs[device_name]
        try:
            resp_dict = fc.get_status()
        except Exception as e:
            LOGGER.info(f"Exception occured on get_status() {e}. Resetting MFC.")
            self.make_fc_instance(device_name, self.config_dict["devices"][device_name])
            self.fcs[device_name]._set_control_point(self.fcs_last_mode[device_name], 5)
            LOGGER.info("MFC connection restored")
            return None
        if all(
            x in resp_dict
            for x in ("mass_flow", "pressure", "setpoint", "control_point")
        ):
            self.fcs_last_mode[device_name] = resp_dict["control_point"]
            return resp_dict
        LOGGER.info(f"!!Received unexpected dict: {resp_dict}")
        return None

    def list_gases(self, device_name: str) -> dict:
        """Return the cached gas-register dict for the named device."""
        return self.fcinfo.get(device_name, {}).get("gases", {})

    async def set_pressure(
        self,
        device_name: str,
        pressure_psia: float,
        ramp_psi_sec: Optional[float] = 0,
        *args,
        **kwargs,
    ) -> list:
        """Switch the device into pressure control and set the setpoint.

        Args:
            device_name: Key in `self.fcs`.
            pressure_psia: Setpoint in psia.
            ramp_psi_sec: Ramp rate in psi/s; zero disables ramping.

        Returns:
            List with the ramp-command response and the `set_pressure` reply.
        """
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
    ) -> list:
        """Switch the device into mass-flow control and set the setpoint.

        Args:
            device_name: Key in `self.fcs`.
            flowrate_sccm: Setpoint in sccm.
            ramp_sccm_sec: Ramp rate in sccm/s; zero disables ramping.

        Returns:
            List with the ramp-command response and the `set_flow_rate` reply.
        """
        resp = []
        await self.stop_polling()
        resp.append(self._send(device_name, f"SR {ramp_sccm_sec} 4"))
        resp.append(self.fcs[device_name].set_flow_rate(flowrate_sccm))
        await self.start_polling()
        return resp

    async def set_gas(self, device_name: str, gas: Union[int, str]):
        """Set the device to a pure gas (by Alicat gas index or short name)."""
        await self.stop_polling()
        resp = self.fcs[device_name].set_gas(gas)
        await self.start_polling()
        return resp

    async def set_gas_mixture(self, device_name: str, gas_dict: dict):
        """Define and select a custom mix (slot 236) given `{gas_name: pct}`.

        Returns an empty dict (without sending commands) if the percentages
        do not sum to 100.
        """
        if sum(gas_dict.values()) != 100:
            LOGGER.info("Gas mixture percentages do not add to 100.")
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
        """Lock the front-panel display on one device, or on all when `device_name` is None."""
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
        """Unlock the front-panel display on one device, or on all when `device_name` is None."""
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
        """Hold the valve at its current position on one device, or all when `device_name` is None."""
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
        """Drive flow to zero, then issue a `hc` hold-closed on one device or all."""
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
        """Cancel an active valve hold on one device, or on all when `device_name` is None."""
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
        """Tare volumetric flow on one device or all. Caller must isolate the MFC first."""
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
        """Tare absolute pressure on one device, or on all when `device_name` is None."""
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

    async def async_shutdown(self):
        """Stop polling, close all valves, then close every serial connection."""
        await self.stop_polling()
        await asyncio.sleep(0.5)
        LOGGER.info("stopping MFC flows")
        await self.hold_valve_closed()
        self.disconnect()

    async def estop(self, *args, **kwargs) -> bool:
        """Close every valve and return True to indicate the estop was handled."""
        LOGGER.info("stopping MFC flows")
        await self.hold_valve_closed()
        return True

    def shutdown(self):
        """No-op; `async_shutdown` handles safe-state-then-disconnect ordering."""
        return None


class AliCatMFCPoller(DriverPoller):
    """Background poller that reads status for every configured Alicat MFC/PFC."""

    driver: AliCatMFC

    def get_data(self) -> DriverResponse:
        """Read one status sample from each configured flow controller.

        Skips the read entirely while `self.driver.polling` is `False` (a
        raw write is in progress), mirroring the pre-migration
        `poll_sensor_loop`'s per-device `polling` gate.

        Returns:
            `DriverResponse` with `data={dev_name: status_dict, ...}` merged
            across every device that returned a valid reading this cycle
            (the pre-migration loop forwarded one `{dev_name: resp_dict}` to
            `put_lbuf` per device per cycle; folding them into a single call
            here is behaviorally equivalent since `DriverPoller` merges
            `resp.data` into `live_dict` as a whole), or an empty
            `DriverResponse` when polling is paused or no device responded.
        """
        if not self.driver.polling:
            return DriverResponse()
        status_dict = {}
        for dev_name in list(self.driver.fcs.keys()):
            resp_dict = self.driver.get_device_status(dev_name)
            if resp_dict is not None:
                status_dict[dev_name] = resp_dict
        if not status_dict:
            return DriverResponse()
        return DriverResponse(
            response=DriverResponseType.success,
            status=DriverStatus.ok,
            data=status_dict,
        )


class MfcExec(Executor):
    """Executor for a fixed-flow MFC action.

    Reads `device_name`, `duration`, `flowrate_sccm`, `ramp_sccm_sec`, and
    `stay_open` from the action params. Sets the flow rate in `_pre_exec`,
    cancels the valve hold in `_exec`, integrates total flow in `_poll`, and
    optionally reasserts the valve hold in `_post_exec`.
    """

    def __init__(self, *args, **kwargs):
        """Initialize the executor and capture device name, duration, and start time."""
        super().__init__(*args, **kwargs)
        self.start_time = time.time()
        self.device_name = self.active.action.action_params["device_name"]
        # current plan is 1 flow controller per COM
        LOGGER.info("MfcExec initialized.")
        self.duration = self.active.action.action_params.get("duration", -1)

    def _device_not_connected_error(self) -> Optional[dict]:
        """Fail-fast terminal error when this exec's MFC device isn't connected.

        A failed ``AliCatMFC.connect()`` (e.g. a wrong/absent COM port) leaves
        the driver's ``fcs`` empty, so the poller never populates the live
        buffer and ``_poll``'s ``get_lbuf(device_name)`` would ``KeyError``
        mid-loop -- and because that escaped before the action was finalized,
        the ``-act.yml`` never reached a terminal status and a golden capture /
        caller hung waiting out its timeout. Returning a non-``none`` error from
        ``_pre_exec`` makes ``action_loop_task`` ``finish()`` the action
        ``errored`` immediately, with a clear reason, instead. Returns ``None``
        when the device is connected.
        """
        fcs = getattr(self.active.driver, "fcs", {}) or {}
        if self.device_name not in fcs:
            LOGGER.error(
                f"MFC device {self.device_name!r} is not connected "
                f"(driver.fcs={list(fcs)}); check the device COM port and power. "
                "Aborting action (fail-fast)."
            )
            return {"error": ErrorCodes.critical_error}
        return None

    async def _pre_exec(self) -> dict:
        """Set the flow rate (and ramp) for the configured device."""
        guard = self._device_not_connected_error()
        if guard is not None:
            return guard
        LOGGER.info("MfcExec running setup methods.")
        self.flowrate_sccm = self.active.action.action_params.get("flowrate_sccm", None)
        self.ramp_sccm_sec = self.active.action.action_params.get("ramp_sccm_sec", 0)
        if self.flowrate_sccm is not None:
            rate_resp = await self.active.driver.set_flowrate(
                device_name=self.device_name,
                flowrate_sccm=self.flowrate_sccm,
                ramp_sccm_sec=self.ramp_sccm_sec,
            )
            LOGGER.info(f"set_flowrate returned: {rate_resp}")
        return {"error": ErrorCodes.none}

    async def _exec(self) -> dict:
        """Reset accumulators and cancel the valve hold to start flowing."""
        self.start_time = time.time()
        self.last_acq_time = self.start_time
        self.last_acq_flow = 0
        self.total_scc = 0
        if self.flowrate_sccm is not None:
            openvlv_resp = await self.active.driver.hold_cancel(
                device_name=self.device_name,
            )
            LOGGER.info(f"hold_cancel returned: {openvlv_resp}")
        return {"error": ErrorCodes.none}

    async def _poll(self) -> dict:
        """Read flow from the live buffer and integrate total volume.

        Returns a dict with `error`, `status` (active until `duration`
        elapses), and `data` containing the latest live-buffer record.
        """
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

    async def _post_exec(self) -> dict:
        """Record `total_scc` on the action and close the valve unless `stay_open`."""
        LOGGER.info("MfcExec running cleanup methods.")
        self.active.action.action_params["total_scc"] = self.total_scc
        if not self.active.action.action_params.get("stay_open", False):
            closevlv_resp = await self.active.driver.hold_valve_closed(
                device_name=self.device_name,
            )
            LOGGER.info(f"hold_valve_closed returned: {closevlv_resp}")
        else:
            LOGGER.info("'stay_open' is True, skipping valve hold")
        return {"error": ErrorCodes.none}


class PfcExec(MfcExec):
    """Executor for a fixed-pressure MFC action.

    Reads `pressure_psia` and `ramp_psi_sec` instead of flow params and uses
    `set_pressure` to drive the MFC in pressure mode.
    """

    async def _pre_exec(self) -> dict:
        """Set the target pressure (and ramp) on the configured device."""
        guard = self._device_not_connected_error()
        if guard is not None:
            return guard
        LOGGER.info("PfcExec running setup methods.")
        self.pressure_psia = self.active.action.action_params.get("pressure_psia", None)
        self.ramp_psi_sec = self.active.action.action_params.get("ramp_psi_sec", 0)
        if self.pressure_psia is not None:
            rate_resp = await self.active.driver.set_pressure(
                device_name=self.device_name,
                pressure_psia=self.pressure_psia,
                ramp_psi_sec=self.ramp_psi_sec,
            )
            LOGGER.info(f"set_pressure returned: {rate_resp}")
        return {"error": ErrorCodes.none}

    async def _exec(self) -> dict:
        """Reset accumulators and cancel the valve hold to apply the pressure setpoint."""
        self.start_time = time.time()
        self.last_acq_time = self.start_time
        self.last_acq_flow = 0
        self.total_scc = 0
        if self.pressure_psia is not None:
            openvlv_resp = await self.active.driver.hold_cancel(
                device_name=self.device_name,
            )
            LOGGER.info(f"hold_cancel returned: {openvlv_resp}")
        return {"error": ErrorCodes.none}


class MfcConstPresExec(MfcExec):
    """Executor that pulses the MFC to maintain a target pressure in a fixed volume.

    Reads `target_pressure`, `total_gas_scc`, `flowrate_sccm`, `ramp_sccm_sec`,
    and `refill_freq_sec`. Each poll cycle, if the measured pressure is below
    `target_pressure` and the refill cooldown has elapsed, opens the valve
    for a computed time before closing it again.
    """

    def __init__(self, *args, **kwargs):
        """Initialize the executor and read its target-pressure parameters."""
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

    def eval_pressure(self, pressure) -> tuple:
        """Compute the refill time and volume needed to reach `target_pressure`.

        Args:
            pressure: Measured pressure in the same units as `target_pressure`.

        Returns:
            `(False, False)` if already above target, otherwise
            `(fill_time_seconds, fill_volume_scc)`.
        """
        if pressure > self.target_pressure:
            return False, False
        else:
            fill_scc = self.total_gas_scc * (1 - pressure / self.target_pressure)
            fill_time = 60.0 * fill_scc / self.flowrate_sccm
            return fill_time, fill_scc

    async def _pre_exec(self) -> dict:
        """Set the refill flow rate on the device before the loop starts."""
        guard = self._device_not_connected_error()
        if guard is not None:
            return guard
        LOGGER.info("MfcConstPresExec running setup methods.")
        rate_resp = await self.active.driver.set_flowrate(
            device_name=self.device_name,
            flowrate_sccm=self.flowrate_sccm,
            ramp_sccm_sec=self.ramp_sccm_sec,
        )
        LOGGER.info(f"set_flowrate returned: {rate_resp}")
        return {"error": ErrorCodes.none}

    async def _exec(self) -> dict:
        """Reset accumulators; the loop opens the valve only on demand."""
        self.start_time = time.time()
        self.last_acq_time = self.start_time
        self.last_acq_flow = 0
        self.total_scc = 0
        return {"error": ErrorCodes.none}

    async def _poll(self) -> dict:
        """Decide whether to open or close the valve based on measured pressure."""
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
            LOGGER.info(
                f"pressure below {self.target_pressure}, filling {fill_scc} scc over {fill_time} seconds"
            )
            self.filling = True
            openvlv_resp = await self.active.driver.hold_cancel(
                device_name=self.device_name,
            )
            LOGGER.info(f"hold_cancel returned: {openvlv_resp}")
            self.fill_end = iter_time + fill_time
        elif self.filling and iter_time >= self.fill_end:
            LOGGER.info("target volume filled, closing mfc valve")
            closevlv_resp = await self.active.driver.hold_valve_closed(
                device_name=self.device_name,
            )
            LOGGER.info(f"hold_valve_closed returned: {closevlv_resp}")
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

    async def _post_exec(self) -> dict:
        """Record `total_scc` and close the valve unless `stay_open` is set."""
        LOGGER.info("MfcConstPresExec running cleanup methods.")
        self.active.action.action_params["total_scc"] = self.total_scc
        if not self.active.action.action_params.get("stay_open", False):
            closevlv_resp = await self.active.driver.hold_valve_closed(
                device_name=self.device_name,
            )
            LOGGER.info(f"hold_valve_closed returned: {closevlv_resp}")
        else:
            LOGGER.info("'stay_open' is True, skipping valve hold")
        return {"error": ErrorCodes.none}


class MfcConstConcExec(MfcExec):
    """Executor that maintains a target CO2 concentration in a fixed headspace.

    Subscribes to a configured CO2 sensor server's `ws_live` WebSocket and
    pulses the MFC valve to inject CO2 until the headspace concentration
    reaches `target_co2_ppm`. Reads `target_co2_ppm`, `headspace_scc`,
    `flowrate_sccm`, `ramp_sccm_sec`, and `refill_freq_sec` from action params.
    """

    def __init__(self, *args, **kwargs):
        """Initialize the executor and connect to the CO2 sensor server WebSocket."""
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
        LOGGER.info(f"checking config for co2 server named: {self.co2serv_key}")
        co2serv_config = self.active.base.world_cfg["servers"].get(
            self.co2serv_key, None
        )
        if co2serv_config is None:
            return
        co2serv_host = co2serv_config.get("host", None)
        co2serv_port = co2serv_config.get("port", None)
        LOGGER.info(
            f"subscribing to {self.co2serv_key} at {co2serv_host}:{co2serv_port}"
        )

        self.wsc = WSC(co2serv_host, co2serv_port, "ws_live")

    def eval_conc(self) -> tuple:
        """Read recent CO2 readings and compute the refill time and volume.

        Blocks (with 1 s sleeps) until at least one CO2 packet arrives on the
        WebSocket, then averages up to the last 10 `co2_ppm` samples and
        returns `(fill_time_seconds, fill_volume_scc)` needed to reach
        `target_co2_ppm` in `headspace_scc`.
        """
        data_package = self.wsc.read_messages()
        while not data_package:
            data_package = self.wsc.read_messages()
            LOGGER.info("No co2_ppm readings have been received, sleeping for 1 second")
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

        # LOGGER.info(f"got co2 data: {data_dict}")
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

    async def _pre_exec(self) -> dict:
        """Set the refill flow rate on the device before the loop starts."""
        guard = self._device_not_connected_error()
        if guard is not None:
            return guard
        LOGGER.info("MfcConstConcExec running setup methods.")
        rate_resp = await self.active.driver.set_flowrate(
            device_name=self.device_name,
            flowrate_sccm=self.flowrate_sccm,
            ramp_sccm_sec=self.ramp_sccm_sec,
        )
        LOGGER.info(f"set_flowrate returned: {rate_resp}")
        return {"error": ErrorCodes.none}

    async def _exec(self) -> dict:
        """Reset accumulators; the poll loop drives valve pulses."""
        self.start_time = time.time()
        self.last_acq_time = self.start_time
        self.last_acq_flow = 0
        self.total_scc = 0
        return {"error": ErrorCodes.none}

    async def _poll(self) -> dict:
        """Decide whether to open or close the valve based on measured CO2 ppm."""
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
        # LOGGER.info(f"eval_conc() returned {fill_time}, {fill_scc}")
        if (
            fill_time > 0
            and not self.filling
            and iter_time - self.last_fill >= self.refill_freq
        ):
            LOGGER.info(f"filling {fill_scc} scc over {fill_time} seconds")
            self.filling = True
            openvlv_resp = await self.active.driver.hold_cancel(
                device_name=self.device_name,
            )
            LOGGER.info(f"hold_cancel returned: {openvlv_resp}")
            self.fill_end = iter_time + fill_time
        elif self.filling and iter_time >= self.fill_end:
            LOGGER.info("target volume filled, closing mfc valve")
            closevlv_resp = await self.active.driver.hold_valve_closed(
                device_name=self.device_name,
            )
            LOGGER.info(f"hold_valve_closed returned: {closevlv_resp}")
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

    async def _post_exec(self) -> dict:
        """Record `total_scc` and close the valve unless `stay_open` is set."""
        LOGGER.info("MfcConstConcExec running cleanup methods.")
        self.active.action.action_params["total_scc"] = self.total_scc
        if not self.active.action.action_params.get("stay_open", False):
            closevlv_resp = await self.active.driver.hold_valve_closed(
                device_name=self.device_name,
            )
            LOGGER.info(f"hold_valve_closed returned: {closevlv_resp}")
        else:
            LOGGER.info("'stay_open' is True, skipping valve hold")
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
    """Serial driver for Alicat flow meters.

    Communicates with the device over USB or RS-232/RS-485 using `pyserial`.
    Multiple `FlowMeter` instances sharing the same serial port share a
    single `serial.Serial` via `FlowMeter.open_ports` refcounting.
    """

    # A dictionary that maps port names to a tuple of connection
    # objects and the refcounts
    open_ports = {}

    def __init__(self, port="/dev/ttyUSB0", address="A"):
        """Open (or share) a 19200-baud serial connection to the flow meter.

        Args:
            port: Serial port name. Default '/dev/ttyUSB0'.
            address: Alicat unit ID character, A-Z. Default 'A'.
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
        self.flush()

    @classmethod
    def is_connected(cls, port, address="A") -> bool:
        """Probe a port/address and return True if the device matches `cls`.

        Useful for auto-discovery. The check distinguishes `FlowMeter` and
        `FlowController` by whether `setpoint` appears in the status keys.
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
        """Raise IOError if the underlying serial connection has been closed.

        Raises:
            IOError: When `self.open` is False.
        """
        if not self.open:
            raise IOError("The FlowController with address {} and \
                          port {} is not open".format(self.address, self.port))

    def get_status(self, retries=5) -> dict:
        """Read the current device state.

        Per the Alicat documentation, the returned dict contains: pressure
        (psia), temperature (C), volumetric flow, mass flow, optional total
        flow, and the currently selected gas. `HLD` and `LCK` status flags
        are surfaced as `hold_valve` and `lock_display` bools. An
        `acquire_time` epoch timestamp is appended.

        Args:
            retries: Maximum number of serial retries on no-response.

        Returns:
            Dict mapping status keys to floats (or strings for the gas field).
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
        """Set the selected gas by name or by Alicat gas index.

        Args:
            gas: Gas name (one of `self.gases`) or integer gas index.
                Gas mixtures must be referenced by index.
            retries: Maximum number of serial retries.
        """
        self._test_controller_open()

        if isinstance(gas, int):
            return self._set_gas_number(gas, retries)
        else:
            return self._set_gas_name(gas, retries)

    def _set_gas_number(self, number, retries):
        """Set the gas by Alicat gas index and verify via register 46.

        Raises:
            IOError: If the readback does not match the requested index.
        """
        self._test_controller_open()
        command = "{addr}$${index}\r".format(addr=self.address, index=number)
        self._write_and_read(command, retries)

        reg46 = self._write_and_read("{addr}$$R46\r".format(addr=self.address), retries)
        reg46_gasbit = int(reg46.split()[-1]) & 0b0000000111111111

        if number != reg46_gasbit:
            raise IOError("Cannot set gas.")

    def _set_gas_name(self, name, retries):
        """Set the gas by name and verify via register 46.

        Raises:
            ValueError: If `name` is not in `self.gases`.
            IOError: If the readback does not match the requested gas.
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
        """Create a COMPOSER gas mix in slots 236-255.

        Requires firmware 5v or greater. Display names longer than six
        characters are truncated by the device.

        Args:
            mix_no: Mix slot, in [236, 255].
            name: Display name for the mix.
            gases: Dict mapping gas name to its integer percentage; values
                must sum to 100.
            retries: Maximum number of serial retries.

        Raises:
            IOError: On unsupported firmware or device-reported failure.
            ValueError: For bad slot, bad percentages, or unsupported gas.
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
        """Delete the gas mix in slot `mix_no`.

        Raises:
            IOError: If the device returns "?".
        """
        self._test_controller_open()
        command = "{addr}GD{mixNumber}\r".format(addr=self.address, mixNumber=mix_no)
        line = self._write_and_read(command, retries)

        if line == "?":
            raise IOError("Unable to delete mix.")

    def lock(self, retries=2):
        """Lock the front-panel display."""
        self._test_controller_open()
        command = "{addr}$$L\r".format(addr=self.address)
        self._write_and_read(command, retries)

    def unlock(self, retries=2):
        """Unlock the front-panel display."""
        self._test_controller_open()
        command = "{addr}$$U\r".format(addr=self.address)
        self._write_and_read(command, retries)

    def tare_pressure(self, retries=2):
        """Tare absolute pressure.

        Raises:
            IOError: If the device returns "?".
        """
        self._test_controller_open()

        command = "{addr}$$PC\r".format(addr=self.address)
        line = self._write_and_read(command, retries)

        if line == "?":
            raise IOError("Unable to tare pressure.")

    def tare_volumetric(self, retries=2):
        """Tare volumetric flow.

        Raises:
            IOError: If the device returns "?".
        """
        self._test_controller_open()
        command = "{addr}$$V\r".format(addr=self.address)
        line = self._write_and_read(command, retries)

        if line == "?":
            raise IOError("Unable to tare flow.")

    def reset_totalizer(self, retries=2):
        """Reset the totalizer (only meaningful on totalizer-equipped units)."""
        self._test_controller_open()
        command = "{addr}T\r".format(addr=self.address)
        self._write_and_read(command, retries)

    def flush(self):
        """Flush the underlying serial input and output buffers."""
        self._test_controller_open()

        self.connection.flush()
        self.connection.flushInput()
        self.connection.flushOutput()

    def close(self):
        """Release this instance's reference to the shared serial port.

        The underlying `serial.Serial` is only closed when no other
        `FlowMeter` shares the same port.
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
        """Send `command` and return the first non-empty response.

        Raises:
            IOError: If no response is received after `retries + 1` attempts.
        """
        self._test_controller_open()

        for _ in range(retries + 1):
            self.flush()
            self.connection.write(command.encode("ascii"))
            line = self._readline()
            if line:
                return line
        else:
            raise IOError("Could not read from flow controller.")

    def _readline(self):
        """Read bytes until a CR terminator and return the decoded string."""
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
    """Serial driver for Alicat flow controllers (extends `FlowMeter`).

    Adds setpoint, control-point, hold, and PID-tuning commands on top of
    `FlowMeter`. The controller must be configured with serial setpoint input
    (Menu-Control-Setpoint_setup-Setpoint_source = Serial).

    Attributes:
        registers: Mapping of control-point names to the register value
            written to register 122 to select that control mode.
    """

    registers = {
        "mass flow": 0b00100101,
        "vol flow": 0b00100100,
        "abs pressure": 0b00100010,
        "gauge pressure": 0b00100110,
        "diff pressure": 0b00100111,
    }

    def __init__(self, port="/dev/ttyUSB0", address="A"):
        """Open the serial link and cache the current control point.

        Args:
            port: Serial port name. Default '/dev/ttyUSB0'.
            address: Alicat unit ID character, A-Z. Default 'A'.
        """
        FlowMeter.__init__(self, port, address)
        try:
            self.control_point = self._get_control_point()
        except Exception:
            self.control_point = None

    def get_status(self, retries=5) -> dict:
        """Read current state and append the cached control point.

        Extends `FlowMeter.get_status` with a `control_point` field that
        identifies whether the device is currently controlling flow or
        pressure.

        Args:
            retries: Maximum number of serial retries.

        Returns:
            Dict of status values, or None if the underlying read returned None.
        """
        state = FlowMeter.get_status(self, retries)
        if state is None:
            return None
        state["control_point"] = self.control_point
        return state

    def set_flow_rate(self, flow, retries=2):
        """Set the target mass-flow setpoint, switching control point if needed.

        Args:
            flow: Target flow rate in the device's configured flow units.
            retries: Maximum number of serial retries.
        """
        if self.control_point in ["abs pressure", "gauge pressure", "diff pressure"]:
            self._set_setpoint(0, retries)
            self._set_control_point("mass flow", retries)
        self._set_setpoint(flow, retries)

    def set_pressure(self, pressure, retries=2):
        """Set the target pressure setpoint, switching control point if needed.

        Args:
            pressure: Target pressure in the device's configured pressure units
                (typically psia).
            retries: Maximum number of serial retries.
        """
        if self.control_point in ["mass flow", "vol flow"]:
            self._set_setpoint(0, retries)
            self._set_control_point("abs pressure", retries)
        self._set_setpoint(pressure, retries)

    def hold(self, retries=2):
        """Hold the valve(s) at their current position via `$$H`.

        For dual-valve pressure controllers this closes both valves.
        """
        self._test_controller_open()
        command = "{addr}$$H\r".format(addr=self.address)
        self._write_and_read(command, retries)

    def cancel_hold(self, retries=2):
        """Cancel an active valve hold via `$$C`."""
        self._test_controller_open()
        command = "{addr}$$C\r".format(addr=self.address)
        self._write_and_read(command, retries)

    def get_pid(self, retries=2) -> dict:
        """Read the current PID configuration (loop type plus P/D/I gains).

        Returns:
            Dict with keys `loop_type`, `P`, `D`, and `I`.
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
        """Write any subset of P/I/D/loop_type by writing the corresponding registers.

        Args:
            p: Proportional gain (register 21).
            i: Integral gain (register 23). Only meaningful for PD2I.
            d: Derivative gain (register 22).
            loop_type: Either 'PD/PDF' or 'PD2I'.
            retries: Maximum number of serial retries.

        Raises:
            ValueError: If `loop_type` is not one of the allowed strings.
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
        """Issue the `S<setpoint>` command and log a warning if readback diverges.

        Called by `set_flow_rate` and `set_pressure` once the appropriate
        control register has been selected.
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
        """Read register 122 and return the matching `registers` key.

        Raises:
            ValueError: If the device returns an unmapped register value.
        """
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
        """Switch the active control register to `point`.

        Args:
            point: A key of `self.registers` (e.g. "mass flow", "abs pressure").

        Raises:
            ValueError: If `point` is not one of the supported registers.
            IOError: If the device readback differs from the requested value.
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
    """CLI entry point used when the forked `alicat` driver is run directly.

    Applies the requested gas/flow/pressure/lock/hold operations and either
    streams readings or prints a single JSON status snapshot.
    """

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
