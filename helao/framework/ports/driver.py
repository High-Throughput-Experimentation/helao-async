"""Abstract driver contract used by every HELAO device backend.

Defines the response envelope (``DriverResponse``), status/result enums
(``DriverStatus``, ``DriverResponseType``), the ``HelaoDriver`` ABC that all
drivers implement (``connect``/``get_status``/``stop``/``reset``/``disconnect``),
and ``DriverPoller`` which runs a periodic ``get_data`` loop on a driver and
mirrors the result into a live dictionary.
"""

import asyncio
from abc import ABC, abstractmethod
from enum import StrEnum
from datetime import datetime
from dataclasses import dataclass, field

from helao.framework.support import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class DriverStatus(StrEnum):
    """Operational state of a driver, reported on every ``DriverResponse``.

    Attributes:
        ok: Driver is working as expected.
        busy: Driver is operating or holding a resource.
        error: Driver returned a low-level error.
        uninitialized: Connection to the device has not been established.
        unknown: Driver is in an unknown state.
        retry: Last operation failed and the driver suggests retrying.
    """

    ok = "ok"  # driver is working as expected
    busy = "busy"  # driver is operating or using a resource
    error = "error"  # driver returned a low-level error
    uninitialized = (
        "uninitialized"  # driver connection to device has not been established
    )
    unknown = "unknown"  # driver is in an unknown state
    retry = "retry" # driver is operation failed and suggests retry


class DriverResponseType(StrEnum):
    """Success/failure flag attached to a driver method's response.

    Attributes:
        success: Method executed successfully.
        failed: Method did not execute successfully.
        not_implemented: Method is not implemented for this driver.
    """

    success = "success"  # method executed successfully
    failed = "failed"  # method did not execute successfully
    not_implemented = "not_implemented"  # method is not implemented


@dataclass
class DriverResponse:
    """Standardized return value of every public driver method.

    Attributes:
        response: Success/failure/not-implemented flag for the call.
        message: Optional human-readable message.
        data: Method-specific payload.
        status: Operational state of the driver at the time of the response.
        timestamp: When the response object was constructed (set automatically).
    """

    response: DriverResponseType = DriverResponseType.not_implemented
    message: str = ""
    data: dict = field(default_factory=dict)
    status: DriverStatus = DriverStatus.unknown
    timestamp: datetime = field(init=False)

    def __post_init__(self):
        """Stamp the response with the current wall-clock time."""
        self.timestamp = datetime.now()

    @property
    def timestamp_str(self) -> str:
        """Timestamp formatted as ``YYYY-MM-DD HH:MM:SS,mmm``."""
        return self.timestamp.strftime("%F %T,%f")[:-3]


class HelaoDriver(ABC):
    """Abstract base class every HELAO device driver implements.

    Subclasses must implement five public methods that each return a
    ``DriverResponse``: ``connect``, ``get_status``, ``stop``, ``reset``, and
    ``disconnect``. Construction records a creation timestamp and stores the
    caller-supplied config dict.

    Attributes:
        timestamp: When the driver instance was created.
        config: Configuration dictionary supplied at construction.
    """

    timestamp: datetime
    config: dict

    def __init__(self, config: dict = {}):
        """Record the creation timestamp and store the driver config.

        Args:
            config: Driver-specific configuration. Defaults to an empty dict.
        """
        self.timestamp = datetime.now()
        self.config = config

    @property
    def _created_at(self) -> str:
        """Instantiation timestamp formatted as ``YYYY-MM-DD HH:MM:SS,mmm``."""
        return self.timestamp.strftime("%F %T,%f")[:-3]

    @property
    def _uptime(self) -> str:
        """Time since instantiation formatted as ``YYYY-MM-DD HH:MM:SS,mmm``."""
        return (datetime.now() - self.timestamp).strftime("%F %T,%f")[:-3]

    @abstractmethod
    def connect(self) -> DriverResponse:
        """Open the connection to the underlying resource."""

    @abstractmethod
    def get_status(self) -> DriverResponse:
        """Return the current operational state of the driver."""

    @abstractmethod
    def stop(self) -> DriverResponse:
        """Abort all active activity (motion, I/O, computation)."""

    @abstractmethod
    def reset(self) -> DriverResponse:
        """Reinitialize the driver, force-closing any existing connection."""

    @abstractmethod
    def disconnect(self) -> DriverResponse:
        """Release the connection to the underlying resource."""


class DriverPoller:
    """Runs a periodic ``get_data`` loop against a ``HelaoDriver``.

    On construction the poller schedules two background asyncio tasks on the
    running loop: one waits on a signal queue to toggle the ``polling`` flag,
    the other repeatedly calls :meth:`get_data` (which subclasses override)
    and merges the returned data into ``live_dict``. When a ``_base_hook`` is
    attached the data is also forwarded to ``base_hook.put_lbuf``.

    Attributes:
        driver: The driver being polled.
        wait_time: Sleep interval between polls, in seconds.
        last_update: Timestamp of the most recent non-empty data response.
        live_dict: Latest polled values, plus a ``last_updated`` entry.
        polling: Whether the polling loop is currently active.
    """

    driver: HelaoDriver
    wait_time: float
    last_update: datetime
    live_dict: dict
    polling: bool

    def __init__(self, driver: HelaoDriver, wait_time: float = 0.05) -> None:
        """Bind to ``driver`` and start the signal and polling background tasks.

        Args:
            driver: Driver instance to poll.
            wait_time: Seconds to sleep between polls. Defaults to ``0.05``.
        """
        self.driver = driver
        self.wait_time = wait_time
        self.aloop = asyncio.get_running_loop()
        self.live_dict = {}
        self.last_update = datetime.now()
        self.polling = True
        self.poll_signalq = asyncio.Queue(1)
        self.poll_signal_task = self.aloop.create_task(self._poll_signal_loop())
        self.polling_task = self.aloop.create_task(self._poll_sensor_loop())
        self._base_hook = None

    async def _start_polling(self):
        """Signal the polling loop to start and wait until it does."""
        LOGGER.info("got 'start_polling' request, raising signal")
        await self.poll_signalq.put(True)
        while not self.polling:
            LOGGER.info("waiting for polling loop to start")
            await asyncio.sleep(0.1)

    async def _stop_polling(self):
        """Signal the polling loop to stop and wait until it does."""
        LOGGER.info("got 'stop_polling' request, raising signal")
        await self.poll_signalq.put(False)
        while self.polling:
            LOGGER.info("waiting for polling loop to stop")
            await asyncio.sleep(0.1)

    async def _poll_signal_loop(self):
        """Background loop that updates ``self.polling`` from the signal queue."""
        while True:
            self.polling = await self.poll_signalq.get()
            LOGGER.info("polling signal received")

    async def _poll_sensor_loop(self):
        """Background loop that calls :meth:`get_data` and updates ``live_dict``.

        While ``polling`` is true, the driver is polled every ``wait_time``
        seconds; non-empty responses update ``live_dict`` (with ``last_updated``)
        and are forwarded to ``_base_hook.put_lbuf`` when a hook is attached.
        """
        LOGGER.info("polling task has started")
        while True:
            if self.polling:
                resp = self.get_data()
                if resp.data:
                    self.last_update = resp.timestamp
                    self.live_dict.update(resp.data)
                    self.live_dict["last_updated"] = self.last_update
                    if self._base_hook is not None:
                        await self._base_hook.put_lbuf(resp.data)
            await asyncio.sleep(self.wait_time)

    def get_data(self) -> DriverResponse:
        """Return one polled sample from the driver.

        Subclasses must override this to populate ``DriverResponse.data`` with
        the values to merge into ``live_dict``. The default implementation logs
        a notice and returns an empty response.
        """
        LOGGER.info("DriverPoller.get_data() has not been implemented")
        return DriverResponse()
