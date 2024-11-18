__all__ = ["CM0134", "O2MonExec"]

import time
import asyncio
import serial
import minimalmodbus

from helao.helpers import logging
if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER
from helao.core.error import ErrorCodes
from helao.core.models.hlostatus import HloStatus
from helao.servers.base import Base
from helao.helpers.executor import Executor


class CM0134:
    """Device driver class for the CM0134 oxygen sensor using RS-485 communication.

    Server config parameters:
    "device": str -- port (e.g. "COM7") or device path (e.g. "/dev/ttyUSB0")
    "address": int -- modbus device address
    "baudrate": int -- serial communication baud rate (default 9600)

    """

    def __init__(self, action_serv: Base):
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
        """Continuous polling loop which populates live buffer with O2 ppm values."""
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
        """Stops polling task and closes serial device connection."""
        try:
            self.polling_task.cancel()
        except asyncio.CancelledError:
            LOGGER.info("closed sensor polling loop task")
        self.inst.serial.close()


class O2MonExec(Executor):
    """O2 recording action written as an executor."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        LOGGER.info("O2MonExec initialized.")
        self.start_time = time.time()
        self.duration = self.active.action.action_params.get("duration", -1)

    async def _poll(self):
        """Read O2 ppm from live buffer."""
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
