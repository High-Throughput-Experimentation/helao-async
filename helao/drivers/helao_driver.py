
"""
This module defines the core classes and methods for the Helao driver framework.

Classes:
    DriverStatus (StrEnum): Enumerated driver status strings for DriverResponse objects.
    DriverResponseType (StrEnum): Success or failure flag for a public driver method's response.
    DriverResponse (dataclass): Standardized response for all public driver methods.
    HelaoDriver (ABC): Generic class for Helao drivers without base.py dependency.
    DriverPoller: Generic class for Helao driver polling with optional base dependency.

Functions:
    HelaoDriver.connect(self) -> DriverResponse: Open connection to resource.
    HelaoDriver.get_status(self) -> DriverResponse: Return current driver status.
    HelaoDriver.stop(self) -> DriverResponse: General stop method, abort all active methods e.g. motion, I/O, compute.
    HelaoDriver.reset(self) -> DriverResponse: Reinitialize driver, force-close old connection if necessary.
    HelaoDriver.disconnect(self) -> DriverResponse: Release connection to resource.
    DriverPoller.get_data(self) -> DriverResponse: Method to be implemented by subclasses to return a dictionary of polled values.
"""
import asyncio
from abc import ABC, abstractmethod
from enum import StrEnum
from datetime import datetime
from dataclasses import dataclass, field

from helao.helpers import logging

if logging.LOGGER is None:
    LOGGER = logging.make_logger(logger_name="default_helaodriver")
else:
    LOGGER = logging.LOGGER


class DriverStatus(StrEnum):
    """
    DriverStatus is an enumeration representing the various states a driver can be in.

    Attributes:
        ok (str): Indicates the driver is working as expected.
        busy (str): Indicates the driver is operating or using a resource.
        error (str): Indicates the driver returned a low-level error.
        uninitialized (str): Indicates the driver connection to the device has not been established.
        unknown (str): Indicates the driver is in an unknown state.
    """

    ok = "ok"  # driver is working as expected
    busy = "busy"  # driver is operating or using a resource
    error = "error"  # driver returned a low-level error
    uninitialized = (
        "uninitialized"  # driver connection to device has not been established
    )
    unknown = "unknown"  # driver is in an unknown state


class DriverResponseType(StrEnum):
    """
    DriverResponseType is an enumeration that represents the possible outcomes of a method execution in the driver.

    Attributes:
        success (str): Indicates that the method executed successfully.
        failed (str): Indicates that the method did not execute successfully.
        not_implemented (str): Indicates that the method is not implemented.
    """

    success = "success"  # method executed successfully
    failed = "failed"  # method did not execute successfully
    not_implemented = "not_implemented"  # method is not implemented


@dataclass
class DriverResponse:
    """
    DriverResponse class encapsulates the response from a driver operation.

    Attributes:
        response (DriverResponseType): The type of response from the driver.
        message (str): A message associated with the response.
        data (dict): Additional data related to the response.
        status (DriverStatus): The status of the driver response.
        timestamp (datetime): The timestamp when the response was created.

    Methods:
        __post_init__(): Initializes the timestamp attribute after the object is created.
        timestamp_str(): Returns the timestamp as a formatted string.
    """

    response: DriverResponseType = DriverResponseType.not_implemented
    message: str = ""
    data: dict = field(default_factory=dict)
    status: DriverStatus = DriverStatus.unknown
    timestamp: datetime = field(init=False)

    def __post_init__(self):
        self.timestamp = datetime.now()

    @property
    def timestamp_str(self):
        return self.timestamp.strftime("%F %T,%f")[:-3]


class HelaoDriver(ABC):
    """
    HelaoDriver is an abstract base class that defines the interface for a driver in the Helao system.

    Attributes:
        timestamp (datetime): The timestamp when the driver instance was created.
        config (dict): Configuration dictionary for the driver.

    Methods:
        connect() -> DriverResponse:
            Open connection to resource.
        get_status() -> DriverResponse:
            Return current driver status.
        stop() -> DriverResponse:
            General stop method, abort all active methods e.g. motion, I/O, compute.
        reset() -> DriverResponse:
            Reinitialize driver, force-close old connection if necessary.
        disconnect() -> DriverResponse:
            Release connection to resource.

    Properties:
        _created_at (str):
            Instantiation timestamp formatted as "YYYY-MM-DD HH:MM:SS,mmm".
        _uptime (str):
            Driver uptime formatted as "YYYY-MM-DD HH:MM:SS,mmm".
    """

    timestamp: datetime
    config: dict

    def __init__(self, config: dict = {}):
        """
        Initializes the HelaoDriver instance.

        Args:
            config (dict, optional): Configuration dictionary for the driver. Defaults to an empty dictionary.

        Attributes:
            timestamp (datetime): The timestamp when the instance is created.
            config (dict): The configuration dictionary for the driver.
        """
        self.timestamp = datetime.now()
        self.config = config

    @property
    def _created_at(self):
        """
        Returns the creation timestamp formatted as a string.

        The timestamp is formatted as "YYYY-MM-DD HH:MM:SS,mmm" where "mmm" 
        represents milliseconds.

        Returns:
            str: The formatted timestamp string.
        """
        return self.timestamp.strftime("%F %T,%f")[:-3]

    @property
    def _uptime(self):
        """
        Calculate the uptime of the driver.

        Returns:
            str: The uptime formatted as "YYYY-MM-DD HH:MM:SS,mmm".
        """
        return (datetime.now() - self.timestamp).strftime("%F %T,%f")[:-3]

    @abstractmethod
    def connect(self) -> DriverResponse:
        """Open connection to resource."""

    @abstractmethod
    def get_status(self) -> DriverResponse:
        """Return current driver status."""

    @abstractmethod
    def stop(self) -> DriverResponse:
        """General stop method, abort all active methods e.g. motion, I/O, compute."""

    @abstractmethod
    def reset(self) -> DriverResponse:
        """Reinitialize driver, force-close old connection if necessary."""

    @abstractmethod
    def disconnect(self) -> DriverResponse:
        """Release connection to resource."""


class DriverPoller:
    """
    A class to handle polling of a HelaoDriver at regular intervals.

    Attributes:
    -----------
    driver : HelaoDriver
        The driver instance to be polled.
    wait_time : float
        The time interval (in seconds) between each poll.
    last_update : datetime
        The timestamp of the last successful poll.
    live_dict : dict
        A dictionary to store the live data from the driver.
    polling : bool
        A flag indicating whether polling is currently active.

    Methods:
    --------
    __init__(driver: HelaoDriver, wait_time: float = 0.05) -> None
        Initializes the DriverPoller with the given driver and wait time.
    
    async _start_polling()
        Starts the polling process by raising a signal.
    
    async _stop_polling()
        Stops the polling process by raising a signal.
    
    async _poll_signal_loop()
        An internal loop that waits for polling signals to start or stop polling.
    
    async _poll_sensor_loop()
        An internal loop that performs the actual polling of the driver at regular intervals.
    
    get_data() -> DriverResponse
        A placeholder method to retrieve data from the driver. Should be implemented by subclasses.
    """

    driver: HelaoDriver
    wait_time: float
    last_update: datetime
    live_dict: dict
    polling: bool

    def __init__(self, driver: HelaoDriver, wait_time: float = 0.05) -> None:
        """
        Initializes the HelaoDriver instance.

        Args:
            driver (HelaoDriver): The driver instance to be used.
            wait_time (float, optional): The wait time between polling operations. Defaults to 0.05 seconds.

        Attributes:
            driver (HelaoDriver): The driver instance to be used.
            wait_time (float): The wait time between polling operations.
            aloop (asyncio.AbstractEventLoop): The running event loop.
            live_dict (dict): A dictionary to store live data.
            last_update (datetime.datetime): The timestamp of the last update.
            polling (bool): A flag indicating whether polling is active.
            poll_signalq (asyncio.Queue): A queue for polling signals.
            poll_signal_task (asyncio.Task): The task for the polling signal loop.
            polling_task (asyncio.Task): The task for the polling sensor loop.
            _base_hook (Optional[Callable]): A base hook for additional functionality.
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
        """
        Asynchronously starts the polling process by raising a signal and waiting for the polling loop to begin.

        This method performs the following steps:
        1. Logs the receipt of a 'start_polling' request.
        2. Puts a True value into the poll_signalq queue to signal the start of polling.
        3. Enters a loop that waits for the polling process to start, logging the status and sleeping for 0.1 seconds between checks.

        Returns:
            None
        """
        LOGGER.info("got 'start_polling' request, raising signal")
        await self.poll_signalq.put(True)
        while not self.polling:
            LOGGER.info("waiting for polling loop to start")
            await asyncio.sleep(0.1)

    async def _stop_polling(self):
        """
        Asynchronously stops the polling process.

        This method logs a 'stop_polling' request, signals the polling loop to stop,
        and waits until the polling loop has completely stopped.

        Raises:
            asyncio.QueueFull: If the queue is full when attempting to put the stop signal.
        """
        LOGGER.info("got 'stop_polling' request, raising signal")
        await self.poll_signalq.put(False)
        while self.polling:
            LOGGER.info("waiting for polling loop to stop")
            await asyncio.sleep(0.1)

    async def _poll_signal_loop(self):
        """
        Asynchronous loop that continuously polls for signals.

        This method runs an infinite loop that waits for a signal from the 
        `poll_signalq` queue. When a signal is received, it sets the `polling` 
        attribute and logs the event.

        Returns:
            None
        """
        while True:
            self.polling = await self.poll_signalq.get()
            LOGGER.info("polling signal received")

    async def _poll_sensor_loop(self):
        """
        Asynchronous loop that continuously polls a sensor for data.

        This method runs indefinitely, checking if polling is enabled and, if so,
        retrieves data from the sensor. If data is received, it updates the 
        `live_dict` with the new data and the timestamp of the last update. If a 
        base hook is defined, it also sends the data to the base hook.

        The loop sleeps for a duration specified by `self.wait_time` between each 
        polling attempt.

        Attributes:
            polling (bool): Flag indicating whether polling is enabled.
            wait_time (float): Time to wait between polling attempts.
            last_update (datetime): Timestamp of the last data update.
            live_dict (dict): Dictionary to store live data and the last update timestamp.
            _base_hook (object): Optional hook to send data to an external buffer.

        Logs:
            Logs an info message when the polling task starts.
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
        """
        Retrieves data from the driver.

        This method is intended to be overridden by subclasses to provide
        specific data retrieval functionality. By default, it logs a message
        indicating that the method has not been implemented and returns an
        empty `DriverResponse` object.

        Returns:
            DriverResponse: An empty response object indicating no data.
        """
        LOGGER.info("DriverPoller.get_data() has not been implemented")
        return DriverResponse()
