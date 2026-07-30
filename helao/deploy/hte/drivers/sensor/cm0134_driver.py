"""CM-0134 oxygen sensor driver (RS-485 / Modbus).

Provides :class:`CM0134`, a ``HelaoDriver`` Modbus driver for the sensor, the
paired :class:`CM0134Poller` that publishes O2 ppm readings into the action
server's live buffer, and :class:`O2MonExec`, an executor that records those
values for a configured duration.
"""

__all__ = ["CM0134", "CM0134Poller", "O2MonExec"]

import asyncio
import time

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

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class CM0134(HelaoDriver):
    """Modbus-RTU HelaoDriver for the CM-0134 oxygen sensor.

    The Modbus serial connection is opened by :meth:`connect`, not by
    construction; always-on O2 ppm polling is handled by the paired
    :class:`CM0134Poller`, wired in as the server's ``poller_class``.

    Server config parameters:
        ``device``: COM port or device path (e.g. ``"COM7"`` or
            ``"/dev/ttyUSB0"``).
        ``address``: Modbus device address.
        ``baudrate``: Serial baud rate (default 9600).
        ``start_margin``: Margin appended to recording windows.
        ``allow_no_sample``: Whether actions can run without samples.
    """

    def __init__(self, config: dict = {}):
        """Store config; the Modbus connection is opened in :meth:`connect`.

        Args:
            config: Driver configuration (the server's ``params`` dict).
        """
        super().__init__(config=config)
        self.config_dict = self.config
        self.inst = None
        self.start_margin = self.config_dict.get("start_margin", 0)
        self.start_time = 0
        self.last_rec_time = 0
        self.recording_duration = 0
        self.recording_rate = 0.1  # seconds per acquisition
        self.allow_no_sample = self.config_dict.get("allow_no_sample", True)

    def connect(self) -> DriverResponse:
        """Open the Modbus serial connection to the sensor.

        Returns:
            ``DriverResponse`` reporting connection success or failure.
        """
        import minimalmodbus

        try:
            self.inst = minimalmodbus.Instrument(
                self.config_dict.get("device", "COM7"),
                self.config_dict.get("address", 254),
            )
            self.inst.serial.baudrate = self.config_dict.get("baudrate", 9600)
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
        """Return whether the Modbus instrument has been opened.

        Returns:
            ``DriverResponse`` with ``status=ok`` if connected, else
            ``status=uninitialized``.
        """
        if self.inst is not None:
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
        """Force-close and reopen the Modbus connection."""
        self.disconnect()
        return self.connect()

    def disconnect(self) -> DriverResponse:
        """Close the underlying serial port."""
        try:
            if self.inst is not None:
                self.inst.serial.close()
            response = DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            LOGGER.error("disconnect failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        finally:
            self.inst = None
        return response

    def shutdown(self):
        """Close the underlying serial port on server shutdown."""
        self.disconnect()

    def read_o2_ppm(self):
        """Read one O2 ppm value from the sensor, or ``None`` on a transient error."""
        import minimalmodbus

        try:
            o2_level = self.inst.read_register(1, functioncode=4) * 10
        except minimalmodbus.NoResponseError as err:
            LOGGER.info(f"NoResponseError: Driver polling rate is too fast. {err}")
            return None
        except serial.SerialException as err:
            LOGGER.info(f"Device {self.config_dict.get('device')} is in use. {err}")
            return None
        return o2_level


class CM0134Poller(DriverPoller):
    """Background poller that reads O2 ppm from the CM0134 sensor."""

    driver: CM0134

    def get_data(self) -> DriverResponse:
        """Read one O2 ppm sample from the driver.

        Returns:
            ``DriverResponse`` with ``data={"o2_ppm": <int>}`` when a reading
            was obtained, or an empty ``DriverResponse`` when the read was
            transiently skipped (matches the pre-migration ``continue``/
            falsy-reading behavior of ``poll_sensor_loop``).
        """
        o2_level = self.driver.read_o2_ppm()
        if not o2_level:
            return DriverResponse()
        return DriverResponse(
            response=DriverResponseType.success,
            status=DriverStatus.ok,
            data={"o2_ppm": int(o2_level)},
        )


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
