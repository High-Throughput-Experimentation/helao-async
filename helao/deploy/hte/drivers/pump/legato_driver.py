"""KD Scientific Legato 100 series syringe pump driver.

Provides a ``HelaoDriver`` serial control wrapper (`KDS100`) that talks to one
or more daisy-chained syringe pumps over a single COM port, a `KDS100Poller`
that publishes per-pump status into the action server's live buffer, plus a
`PumpExec` executor that runs an infuse/withdraw action and reports status
via the action server's live buffer.
"""

__all__ = ["KDS100", "KDS100Poller", "PumpExec"]

import serial
import io
import time
import asyncio
from typing import Any, Optional

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
from helao.core.models.hlostatus import HloStatus
from helao.core.error import ErrorCodes
from helao.helpers.executor import Executor
from helao.core.drivers.helao_driver import (
    HelaoDriver,
    DriverResponse,
    DriverStatus,
    DriverResponseType,
    DriverPoller,
)


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

Pump status is published to the action server's live buffer by KDS100Poller.

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


class KDS100(HelaoDriver):
    """HELAO ``HelaoDriver`` wrapper for KD Scientific Legato 100 syringe pump(s) on an RS-232 chain.

    The serial port specified in ``config['port']`` is opened by :meth:`connect`,
    not by construction. Always-on per-pump status polling is handled by the
    paired :class:`KDS100Poller`, wired in as the server's ``poller_class``.

    Server config parameters:
        ``port``: Serial port for the daisy-chained pump(s).
        ``pumps``: dict of ``{pump_name: {"address": ..., "diameter": ...}}``.
    """

    def __init__(self, config: dict = {}):
        """Store config; the serial connection is opened in :meth:`connect`.

        Args:
            config: Driver configuration (the server's ``params`` dict).
        """
        super().__init__(config=config)
        self.config_dict = self.config

        self.com = None
        self.sio = None
        self.com_lock = False
        self.polling = True
        self.present_volume_ul = 0.0
        self.last_state = "unknown"

    def connect(self) -> DriverResponse:
        """Open the serial connection to the daisy-chained pump(s).

        Returns:
            ``DriverResponse`` reporting connection success or failure.
        """
        try:
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
        """Return whether the serial connection has been opened.

        Returns:
            ``DriverResponse`` with ``status=ok`` if connected, else
            ``status=uninitialized``.
        """
        if self.com is not None:
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
        """Force-close and reopen the serial connection."""
        self.disconnect()
        return self.connect()

    def disconnect(self) -> DriverResponse:
        """Close the underlying serial port."""
        try:
            if self.com is not None:
                self.com.close()
            response = DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            LOGGER.error("disconnect failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        finally:
            self.com = None
        return response

    def shutdown(self):
        """No-op; `async_shutdown` handles safe-state-then-disconnect ordering."""
        return None

    async def async_shutdown(self):
        """Return pumps to a safe state, then close the serial connection."""
        LOGGER.info("shutting down syringe pump(s)")
        await self.safe_state()
        self.disconnect()

    async def start_polling(self):
        """Resume background status polling (consulted by :class:`KDS100Poller`)."""
        LOGGER.info("got 'start_polling' request")
        self.polling = True

    async def stop_polling(self):
        """Pause background status polling so a raw command doesn't race the poller."""
        LOGGER.info("got 'stop_polling' request")
        self.polling = False

    async def send(self, pump_name: str, cmd: str) -> list:
        """Send a command to the addressed pump and return the parsed response lines.

        Args:
            pump_name: Key in the config ``pumps`` dict identifying the target pump.
            cmd: Pump command string; a trailing carriage return is added if missing.

        Returns:
            List of non-empty response lines stripped of whitespace.
        """
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

    def _send_sync(self, pump_name: str, cmd: str) -> list:
        """Synchronous status-query variant of :meth:`send`, used only by :class:`KDS100Poller`.

        ``DriverPoller.get_data`` is called synchronously (see
        ``helao_driver.py``), so the poller cannot ``await`` :meth:`send`.
        The wire protocol is identical; only the lock-wait sleep is blocking
        instead of cooperative.

        Args:
            pump_name: Key in the config ``pumps`` dict identifying the target pump.
            cmd: Pump command string; a trailing carriage return is added if missing.

        Returns:
            List of non-empty response lines stripped of whitespace.
        """
        if not cmd.endswith("\r"):
            cmd = cmd + "\r"
        addr = self.config_dict["pumps"][pump_name]["address"]
        command_str = f"{addr:02}@{cmd}"
        while self.com_lock:
            time.sleep(0.1)
        self.com_lock = True
        self.sio.write(command_str)
        self.sio.flush()
        resp = [x.strip() for x in self.sio.readlines() if x.strip()]
        if resp:
            while not resp[-1].endswith("\x11"):
                time.sleep(0.1)
                newlines = [x.strip() for x in self.sio.readlines() if x.strip()]
                resp += newlines
        self.com_lock = False
        return resp

    def update_status_from_response(self, response):
        """Parse the first response line and log the pump's post-command status.

        Args:
            response: List of response lines previously returned by ``send``.
        """
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
        LOGGER.info(f"command response returned status: {state}")

    async def start_pump(self, pump_name: str, direction: int) -> Any:
        """Start pump motion.

        Args:
            pump_name: Configured pump key.
            direction: ``1`` to infuse, ``-1`` to withdraw.

        Returns:
            Response list from the pump, or ``False`` if ``direction`` is invalid.
        """
        if direction == 1:
            cmd = "irun"
        elif direction == -1:
            cmd = "wrun"
        else:
            return False
        resp = await self.send(pump_name, cmd)
        self.update_status_from_response(resp)
        return resp

    async def set_force(self, pump_name: str, force_val: int) -> list:
        """Set the infusion force in percent.

        Args:
            pump_name: Configured pump key.
            force_val: Force value in percent.
        """
        cmd = f"forc {force_val}"
        resp = await self.send(pump_name, cmd)
        self.update_status_from_response(resp)
        return resp

    async def set_rate(self, pump_name: str, rate_val: int, direction: int) -> Any:
        """Set the infuse or withdraw rate in uL/sec.

        Args:
            pump_name: Configured pump key.
            rate_val: Flow rate in microliters per second.
            direction: ``1`` for infuse, ``-1`` for withdraw.

        Returns:
            Response list, or ``False`` for invalid ``direction``.
        """
        if direction == 1:
            cmd = "irate"
        elif direction == -1:
            cmd = "wrate"
        else:
            return False
        resp = await self.send(pump_name, f"{cmd} {rate_val} ul/sec")
        self.update_status_from_response(resp)
        return resp

    async def set_target_volume(self, pump_name: str, vol_val: float) -> list:
        """Set the target infuse/withdraw volume in microliters.

        Args:
            pump_name: Configured pump key.
            vol_val: Target volume in uL.
        """
        resp = await self.send(pump_name, f"tvolume {vol_val} ul")
        self.update_status_from_response(resp)
        return resp

    async def set_diameter(self, pump_name: str, diameter_mm: float) -> list:
        """Set syringe diameter in millimeters.

        Args:
            pump_name: Configured pump key.
            diameter_mm: Syringe diameter in mm.
        """
        resp = await self.send(pump_name, f"diameter {diameter_mm:.4f}")
        self.update_status_from_response(resp)
        return resp

    # def set_ramp(self, pump_name: str, start_rate: int, end_rate: int, direction: int):
    #     "Set infusion|withdraw ramp rate in units TODO"
    #     pass

    async def clear_time(
        self, pump_name: Optional[str] = None, direction: Optional[int] = 0
    ) -> list:
        """Clear the infused/withdrawn time counter on one or all pumps.

        Args:
            pump_name: Pump key, or ``None`` to clear all configured pumps.
            direction: ``1`` for infuse-time, ``-1`` for withdraw-time, ``0`` for both.
        """
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
    ) -> list:
        """Clear the infused/withdrawn volume counter on one or all pumps.

        Also updates ``self.present_volume_ul`` when a non-zero direction is
        supplied for a single pump by reading the accumulated volume first.

        Args:
            pump_name: Pump key, or ``None`` to clear all configured pumps.
            direction: ``1`` for infuse-volume, ``-1`` for withdraw-volume,
                ``0`` for both.
        """
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

    async def clear_target_volume(self, pump_name: Optional[str] = None) -> list:
        """Clear the target volume on one or all pumps.

        Args:
            pump_name: Pump key, or ``None`` for all configured pumps.
        """
        if pump_name is None:
            for cpump_name in self.config_dict.get("pump_addrs", {}).keys():
                resp = await self.send(cpump_name, "ctvolume")
                self.update_status_from_response(resp)
            return []
        else:
            resp = await self.send(pump_name, "ctvolume")
            self.update_status_from_response(resp)
            return resp

    async def stop_pump(self, pump_name: Optional[str] = None) -> list:
        """Issue a stop command to one or all pumps.

        Args:
            pump_name: Pump key, or ``None`` for all configured pumps.
        """
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
        """Bring every configured pump to a known idle configuration.

        Enables POLL mode, disables NVRAM writes, stops the pump, clears time
        and target volume counters, and applies the syringe diameter from
        configuration.
        """
        for plab, pdict in self.config_dict.get("pumps", {}).items():
            addr = pdict["address"]
            idle_resp = f"{addr:02}:\x11"
            poll_resp = await self.send(plab, "poll on")
            if poll_resp[-1] != idle_resp:
                LOGGER.info(f"Error setting pump '{plab}' to 'POLL on'.")
                LOGGER.info(f"Server returned: {poll_resp[0]}")
            nvram_resp = await self.send(plab, "nvram off")
            if nvram_resp[-1] != idle_resp:
                LOGGER.info(f"Error setting pump '{plab}' to 'NVRAM off'.")
                LOGGER.info(f"Server returned: {nvram_resp[0]}")
            stop_resp = await self.stop_pump(plab)
            if stop_resp[-1] != idle_resp:
                LOGGER.info(f"Error stopping pump '{plab}'.")
                LOGGER.info(f"Server returned: {stop_resp[0]}")
            cleartime_resp = await self.clear_time(plab)
            if cleartime_resp[-1] != idle_resp:
                LOGGER.info(f"Error clearing time params for pump '{plab}'.")
                LOGGER.info(f"Server returned: {cleartime_resp[0]}")
            clearvol_resp = await self.clear_target_volume(plab)
            if clearvol_resp[-1] != idle_resp:
                LOGGER.info(f"Error clearing volume params for pump '{plab}'.")
                LOGGER.info(f"Server returned: {clearvol_resp[0]}")
            diameter_resp = await self.set_diameter(plab, pdict["diameter"])
            if diameter_resp[-1] != idle_resp:
                LOGGER.info(f"Error setting syringe diameter on pump '{plab}'.")
                LOGGER.info(f"Server returned: {diameter_resp[0]}")
            self.update_status_from_response(diameter_resp)


class KDS100Poller(DriverPoller):
    """Background poller that reads status for every configured KDS100 pump."""

    driver: KDS100

    def get_data(self) -> DriverResponse:
        """Read one status sample from each configured pump.

        Skips the read entirely while `self.driver.polling` is `False`,
        mirroring the pre-migration `poll_sensor_loop`'s polling gate.

        Returns:
            `DriverResponse` with `data={pump_name: status_dict, ...}` merged
            across every pump that returned a matching-address reading this
            cycle (the pre-migration loop forwarded one `{pump_name:
            status_dict}` to `put_lbuf` per pump per cycle; folding them into
            a single call here is behaviorally equivalent since `DriverPoller`
            merges `resp.data` into `live_dict` as a whole), or an empty
            `DriverResponse` when polling is paused or no pump responded.
        """
        if not self.driver.polling:
            return DriverResponse()
        status_dict = {}
        for plab, pdict in self.driver.config_dict.get("pumps", {}).items():
            addr = pdict["address"]
            status_resp = self.driver._send_sync(plab, "status")
            if not status_resp:
                continue
            status_prompt = status_resp[-1]
            status = status_resp[0]
            addrstate_rate, pumptime, pumpvol, flags = status.split()
            raddr = int(addrstate_rate[:2])
            if addr != raddr:
                LOGGER.info("pump address does not match config")
                continue
            state = None
            state_split = None
            for k, v in STATES.items():
                if addrstate_rate[2:].startswith(k):
                    state_split = k
                if status_prompt[2:].startswith(k):
                    state = v
                else:
                    continue
            if state != self.driver.last_state:
                LOGGER.info(
                    f"pump state changed from '{self.driver.last_state}' to '{state}'"
                )
                self.driver.last_state = state
            rate = int(addrstate_rate.split(state_split)[-1])
            pumptime = int(pumptime)
            pumpvol = int(pumpvol)
            (
                motor_dir,
                limit_status,
                stall_status,
                trig_input,
                dir_port,
                target_reached,
            ) = flags.lower()
            status_dict[plab] = {
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
        if not status_dict:
            return DriverResponse()
        return DriverResponse(
            response=DriverResponseType.success,
            status=DriverStatus.ok,
            data=status_dict,
        )


class PumpExec(Executor):
    """Executor that drives a single pump through one infuse or withdraw action."""

    def __init__(self, direction: int, *args, **kwargs):
        """Initialize the executor for the first configured pump.

        Args:
            direction: ``1`` to infuse, ``-1`` to withdraw.
            *args: Positional args forwarded to :class:`Executor`.
            **kwargs: Keyword args forwarded to :class:`Executor`.
        """
        super().__init__(*args, **kwargs)
        self.direction = direction
        # current plan is 1 pump per COM
        self.pump_name = list(self.active.base.server_params["pumps"].keys())[0]
        LOGGER.info("PumpExec initialized.")

    async def _pre_exec(self) -> dict:
        """Send rate and target-volume setpoints to the pump before starting."""
        LOGGER.info("PumpExec running setup methods.")
        rate_resp = await self.active.driver.set_rate(
            pump_name=self.pump_name,
            rate_val=self.active.action.action_params["rate_uL_sec"],
            direction=self.direction,
        )
        LOGGER.info(f"set_rate returned: {rate_resp}")
        vol_resp = await self.active.driver.set_target_volume(
            pump_name=self.pump_name,
            vol_val=self.active.action.action_params["volume_uL"],
        )
        LOGGER.info(f"set_target_volume returned: {vol_resp}")
        return {"error": ErrorCodes.none}

    async def _exec(self) -> dict:
        """Start the pump in the configured direction."""
        start_resp = await self.active.driver.start_pump(
            pump_name=self.pump_name,
            direction=self.direction,
        )
        LOGGER.info(f"start_pump returned: {start_resp}")
        # Publish the start-transition synchronously in the same call path as
        # the start command: PumpExec._poll's first iteration runs with no
        # initial sleep and would otherwise read the stale pre-action status
        # from live_buffer before KDS100Poller's next cycle publishes it,
        # finishing the action immediately without dispensing.
        await self.active.base.put_lbuf(
            {
                self.pump_name: {
                    "status": "infusing" if self.direction == 1 else "withdrawing"
                }
            }
        )
        return {"error": ErrorCodes.none}

    async def _poll(self) -> dict:
        """Map the live-buffer pump status to an HLO status/error tuple."""
        live_buffer, _ = self.active.base.get_lbuf(self.pump_name)
        pump_status = live_buffer["status"]
        # LOGGER.info(f"poll iter status: {pump_status}")
        await asyncio.sleep(0.01)
        if pump_status in ["infusing", "withdrawing"]:
            return {"error": ErrorCodes.none, "status": HloStatus.active}
        elif pump_status == "stalled":
            return {"error": ErrorCodes.motor, "status": HloStatus.errored}
        else:
            return {"error": ErrorCodes.none, "status": HloStatus.finished}

    async def _manual_stop(self) -> dict:
        """Stop the pump in response to an external stop request."""
        stop_resp = await self.active.driver.stop_pump(self.pump_name)
        LOGGER.info(f"stop_pump returned: {stop_resp}")
        return {"error": ErrorCodes.none}

    async def _post_exec(self) -> dict:
        """Clear the volume and target-volume counters after the action ends."""
        LOGGER.info("PumpExec running cleanup methods.")
        clearvol_resp = await self.active.driver.clear_volume(
            pump_name=self.pump_name,
            direction=self.direction,
        )
        LOGGER.info(f"clear_volume returned: {clearvol_resp}")
        cleartar_resp = await self.active.driver.clear_target_volume(
            pump_name=self.pump_name,
        )
        LOGGER.info(f"clear_target_volume returned: {cleartar_resp}")
        return {"error": ErrorCodes.none}


# volume tracking notes
# 1. init volume at 0, need endpoint for user to tell initial volume
# 2. clear target vol is not necessary, but clear infused/withdrawn volume is needed before starting next syringe action
# 3. withdraw will add to volume tracker
# 4. infuse will remove from volume tracker
