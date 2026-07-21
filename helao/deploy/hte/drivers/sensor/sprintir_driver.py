"""SprintIR-6S CO2 sensor driver.

Provides :class:`SprintIR`, a ``HelaoDriver`` serial driver for the sensor,
the paired :class:`SprintIRPoller` that publishes CO2 ppm readings into the
action server's live buffer, and :class:`CO2MonExec` which exposes the
live-buffer value as a HELAO action over a fixed duration.
"""

__all__ = ["SprintIR", "SprintIRPoller", "CO2MonExec"]

import re
import time
import asyncio
from typing import Any

import serial

from helao.helpers import helao_logging as logging
from helao.core.error import ErrorCodes
from helao.core.models.hlostatus import HloStatus
from helao.helpers.executor import Executor
from helao.core.drivers.helao_driver import (
    HelaoDriver,
    DriverResponse,
    DriverStatus,
    DriverResponseType,
    DriverPoller,
)

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

""" Notes:

Setup polling task to populate the action server's live buffer; the
CO2MonExec executor reads from that buffer while an action is active.

TODO: send CO2 reading to bokeh visualizer w/o writing data

"""


class SprintIR(HelaoDriver):
    """Serial HelaoDriver for the SprintIR-6S NDIR CO2 sensor.

    The serial connection is opened by :meth:`connect`, not by construction;
    always-on CO2 ppm polling is handled by the paired :class:`SprintIRPoller`,
    wired in as the server's ``poller_class``.

    Server config parameters:
        ``port``: Serial port / device path for the sensor.
        ``start_margin``: Margin appended to recording windows (retained for
            downstream Executors).
    """

    def __init__(self, config: dict = {}):
        """Store config; the serial connection is opened in :meth:`connect`.

        Args:
            config: Driver configuration (the server's ``params`` dict).
        """
        super().__init__(config=config)
        self.config_dict = self.config
        self.com = None
        self.fw = {}
        self.start_margin = self.config_dict.get("start_margin", 0)
        self.start_time = 0
        self.last_rec_time = 0
        self.recording_duration = 0
        self.recording_rate = 0.1  # seconds per acquisition
        # Open the serial port at construction. BaseAPI builds the DriverPoller
        # (SprintIRPoller) immediately after the driver and the poller AUTO-STARTS
        # its poll loop in __init__ -- but BaseAPI never calls connect(), so
        # deferring the serial open left self.com=None and the poller spammed
        # "'NoneType' object has no attribute 'flush'" every cycle. Connecting
        # here (like the biologic/andor drivers) opens the port before the first
        # poll; a bad/absent port logs a clear "connect failed" instead.
        self.connect()

    def connect(self) -> DriverResponse:
        """Open the serial port, set polling mode, and read firmware scaling.

        Returns:
            ``DriverResponse`` reporting connection success or failure.
        """
        try:
            self.com = serial.Serial(
                port=self.config_dict["port"],
                baudrate=9600,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.5,
                xonxoff=False,
                rtscts=False,
            )

            # set POLL and flush present buffer until empty
            LOGGER.info("Setting sensor to polling mode.")
            self.com.write(b"K 2\r\n")
            self.send("! 0")
            self.send("Y")
            self.send("! 0")
            self.send("Y")
            self.send("! 0")
            self.send("Y")

            fw_map = [
                ("scaling_factor", "."),
                ("init_co2_filtered", "Z"),
                # ("zero-point_air", "G"),
                # ("undocumented_t", "t"),
                # ("undocumented_y", "y"),
                # ("pressure", "B"),
                # ("humidity", "H"),
                # ("zero-point_n2", "U"),
                # ("pc_compensation", "s"),
                # ("digital_filter_value", "a"),
            ]
            ifw_map = {v: k for k, v in fw_map}
            self.fw = {}
            LOGGER.info("Reading scaling factor and initial co2 ppm.")
            for k, v in fw_map:
                LOGGER.info(f"checking {k}")
                resp, aux = self.send(v)
                if resp:
                    fw_val = resp[0].split()[-1].replace(v, "").strip()
                    if fw_val not in ["?", ""]:
                        self.fw[k] = int(fw_val)
                for aresp in aux:
                    cmd = aresp[0]
                    if cmd in ifw_map.keys():
                        fw_val = aresp.split()[-1].replace(cmd, "").strip()
                        self.fw[ifw_map[cmd]] = int(fw_val)
                time.sleep(0.1)

            # set streaming mode before starting the poller
            LOGGER.info("Setting sensor to polling mode.")
            self.com.write(b"K 2\r\n")

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
        """Return whether the serial port has been opened.

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
        """Close the underlying serial port on server shutdown."""
        self.disconnect()

    def send(self, command_str: str) -> tuple:
        """Send a command to the sensor and split the response into echo and aux lines.

        Args:
            command_str: Raw command string; a trailing CRLF is added if missing.

        Returns:
            Tuple ``(cmd_resp, aux_resp)`` of lines beginning with the command
            character versus everything else.
        """
        if self.com is None:
            raise RuntimeError("SprintIR serial port is not connected")
        if not command_str.endswith("\r\n"):
            command_str = command_str + "\r\n"
        self.com.write(command_str.encode("utf8"))
        self.com.flush()
        lines = []
        buf = self.com.read_until(b"\r\n")
        lines += buf.decode("utf8").split("\n")
        while buf != b"":
            buf = self.com.read_until(b"\r\n")
            lines += buf.decode("utf8").split("\n")
        cmd_resp = []
        aux_resp = []
        for line in lines:
            strip = line.strip()
            if strip.startswith(command_str[0]):
                cmd_resp.append(strip)
            elif strip:
                aux_resp.append(strip)
        if aux_resp:
            LOGGER.info(f"Received auxiliary responses: {aux_resp}")
        return cmd_resp, aux_resp

    def read_stream(self) -> Any:
        """Read the most recent filtered CO2 value (``Z`` response).

        Returns:
            The latest filtered CO2 value as a string, or ``False`` if no
            valid reading was found.
        """
        if self.com is None:
            raise RuntimeError("SprintIR serial port is not connected")
        self.com.flush()
        lines, _ = self.send("Z")
        for line in lines[::-1]:
            stripped = line.strip()
            filts = re.findall(r"Z\s[0-9]+", stripped)
            filt = filts[-1].split()[-1] if filts else False
            if filt:
                return filt
        return False

    def reset_polling_mode(self) -> None:
        """Re-issue the polling-mode command (used after consecutive blank reads)."""
        if self.com is None:
            return
        self.com.write(b"K 2\r\n")


class SprintIRPoller(DriverPoller):
    """Background poller that reads CO2 ppm from the SprintIR sensor."""

    driver: SprintIR

    def get_data(self) -> DriverResponse:
        """Read one CO2 ppm sample from the driver.

        Resets the sensor into polling mode after 5 consecutive blank reads,
        mirroring the pre-migration ``poll_sensor_loop`` behavior.

        Returns:
            ``DriverResponse`` with ``data={"co2_ppm": <int>}`` when a
            reading was obtained and in range, or an empty ``DriverResponse``
            otherwise (blank read, parse error, or out-of-range value).
        """
        if not hasattr(self, "_blanks"):
            self._blanks = 0

        try:
            co2_level = self.driver.read_stream()
        except Exception as err:
            LOGGER.info(f"Could not parse streaming value, got {err}")
            return DriverResponse()

        if not co2_level:
            self._blanks += 1
            if self._blanks >= 5:
                LOGGER.warning(
                    "Did not receive a co2 message from sensor after 5 checks, "
                    "resetting polling mode."
                )
                self.driver.reset_polling_mode()
                self._blanks = 0
            return DriverResponse()

        self._blanks = 0
        co2_ppm = int(co2_level) * self.driver.fw["scaling_factor"]
        if 0 <= co2_ppm < 1e6:
            return DriverResponse(
                response=DriverResponseType.success,
                status=DriverStatus.ok,
                data={"co2_ppm": co2_ppm},
            )
        LOGGER.info(f"Got unreasonable co2_ppm value {co2_ppm}")
        return DriverResponse()


class CO2MonExec(Executor):
    """Executor that mirrors live-buffer CO2 readings for a fixed duration."""

    def __init__(self, *args, **kwargs):
        """Capture start time, action duration, and running accumulators.

        Args:
            *args: Positional args forwarded to :class:`Executor`.
            **kwargs: Keyword args forwarded to :class:`Executor`.
        """
        super().__init__(*args, **kwargs)
        LOGGER.info("CO2MonExec initialized.")
        self.start_time = time.time()
        self.duration = self.active.action.action_params.get("duration", -1)
        self.total = 0
        self.num_acqs = 0

    async def _poll(self) -> dict:
        """Read CO2 ppm from the live buffer and report active/finished status.

        Returns:
            Dict with ``error``, ``status`` and ``data`` keys; status is
            ``finished`` once ``duration`` has elapsed.
        """
        live_dict = {}
        co2_ppm, epoch_s = self.active.base.get_lbuf("co2_ppm")
        # LOGGER.info(f"got from live buffer: {co2_ppm}")
        self.total += co2_ppm
        self.num_acqs += 1
        live_dict["co2_ppm"] = co2_ppm
        live_dict["epoch_s"] = epoch_s
        iter_time = time.time()
        elapsed_time = iter_time - self.start_time
        if (self.duration < 0) or (elapsed_time < self.duration):
            status = HloStatus.active
        else:
            status = HloStatus.finished
        await asyncio.sleep(0.01)
        # LOGGER.info(f"sending status: {status}")
        # LOGGER.info(f"sending data: {live_dict}")
        return {
            "error": ErrorCodes.none,
            "status": status,
            "data": live_dict,
        }

    async def _post_exec(self) -> dict:
        """Write the mean CO2 ppm back to the action params at the end of the run."""
        if self.num_acqs > 0:
            self.active.action.action_params["mean_co2_ppm"] = (
                self.total / self.num_acqs
            )
        return {"data": {}, "error": ErrorCodes.none}
