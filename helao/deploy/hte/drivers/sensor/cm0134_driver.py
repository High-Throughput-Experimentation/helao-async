"""CM-0134 oxygen sensor driver (RS-485 / Modbus).

Provides :class:`CM0134`, a Modbus driver that polls O2 ppm values into the
action server's live buffer, and :class:`O2MonExec`, an executor that records
those values for a configured duration.
"""

__all__ = ["CM0134", "O2MonExec"]

import time
import asyncio
import serial
import minimalmodbus

from helao.framework.support import helao_logging as logging
from helao.framework.models.errors import ErrorCodes
from helao.framework.models.hlostatus import HloStatus
from helao.framework.app.base_api import Base
from helao.framework.domain.executor import Executor

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class CM0134:
    """Modbus-RTU driver for the CM-0134 oxygen sensor.

    Opens a Modbus serial connection on construction and starts a background
    polling task that pushes O2 ppm readings into the action server's live
    buffer under the ``o2_ppm`` key.

    Server config parameters:
        ``device``: COM port or device path (e.g. ``"COM7"`` or
            ``"/dev/ttyUSB0"``).
        ``address``: Modbus device address.
        ``baudrate``: Serial baud rate (default 9600).
        ``start_margin``: Margin appended to recording windows.
        ``allow_no_sample``: Whether actions can run without samples.
    """

    def __init__(self, action_serv: Base):
        """Open the Modbus connection and spawn the polling task.

        Args:
            action_serv: Action server providing configuration and live buffer.
        """
        self.base = action_serv
        self.config_dict = action_serv.server_cfg.get("params", {})
        self.inst = minimalmodbus.Instrument(
            self.config_dict.get("device", "COM7"), self.config_dict.get("address", 254)
        )
        self.inst.serial.baudrate = self.config_dict.get("baudrate", 9600)
        self.action = None
        self.active = None
        self.start_margin = self.config_dict.get("start_margin", 0)
        self.start_time = 0
        self.last_rec_time = 0
        self.event_loop = asyncio.get_event_loop()
        self.recording_duration = 0
        self.recording_rate = 0.1  # seconds per acquisition
        self.allow_no_sample = self.config_dict.get("allow_no_sample", True)
        self.polling_task = self.event_loop.create_task(self.poll_sensor_loop())

    async def poll_sensor_loop(self, frequency: int = 2):
        """Continuously read O2 ppm from the sensor and publish to the live buffer.

        Args:
            frequency: Target polling rate in Hz.
        """
        waittime = 1.0 / frequency
        LOGGER.info("Starting polling loop")
        while True:
            try:
                o2_level = self.inst.read_register(1, functioncode=4) * 10
            except minimalmodbus.NoResponseError as err:
                LOGGER.info(f"NoResponseError: Driver polling rate is too fast. {err}")
                continue
            except serial.SerialException as err:
                LOGGER.info(f"Device {self.config_dict['device']} is in use. {err}")
                continue
            if o2_level:
                msg_dict = {"o2_ppm": int(o2_level)}
                await self.base.put_lbuf(msg_dict)
            await asyncio.sleep(waittime)

    def shutdown(self):
        """Cancel the polling task and close the underlying serial port."""
        try:
            self.polling_task.cancel()
        except asyncio.CancelledError:
            LOGGER.info("closed sensor polling loop task")
        self.inst.serial.close()


class O2MonExec(Executor):
    """Executor that records the live-buffer O2 ppm value for the action duration."""

    def __init__(self, *args, **kwargs):
        """Capture start time and the optional ``duration`` action parameter.

        Args:
            *args: Positional args forwarded to :class:`Executor`.
            **kwargs: Keyword args forwarded to :class:`Executor`.
        """
        super().__init__(*args, **kwargs)
        LOGGER.info("O2MonExec initialized.")
        self.start_time = time.time()
        self.duration = self.active.action.action_params.get("duration", -1)

    async def _poll(self) -> dict:
        """Read O2 ppm from the live buffer and report active/finished status.

        Returns:
            Dict with ``error``, ``status`` (``finished`` once ``duration``
            has elapsed, ``active`` otherwise), and ``data`` keys.
        """
        live_dict = {}
        o2_ppm, epoch_s = self.active.base.get_lbuf("o2_ppm")
        live_dict["o2_ppm"] = o2_ppm
        live_dict["epoch_s"] = epoch_s
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
            "data": live_dict,
        }
