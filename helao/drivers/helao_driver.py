"""Generic driver class for inheriting common methods and attributes.

The following methods are used by various drivers which require access to action server
base object. 

    print_message
    helaodirs.save_root
    helao_dirs.process_root
    orch_key
    orch_host
    orch_port
    put_lbuf
    aiolock
    fastapp.helao_cfg
    actionservermodel.estop
    dflt_file_conn_key
    server_cfg
    server_params
    server.server_name
    contain_action
    get_realtime_nowait
    
    

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
    """Enumerated driver status strings for DriverResponse objects."""

    ok = "ok"  # driver is working as expected
    busy = "busy"  # driver is operating or using a resource
    error = "error"  # driver returned a low-level error
    uninitialized = (
        "uninitialized"  # driver connection to device has not been established
    )
    unknown = "unknown"  # driver is in an unknown state


class DriverResponseType(StrEnum):
    """Success or failure flag for a public driver method's response."""

    success = "success"  # method executed successfully
    failed = "failed"  # method did not execute successfully
    not_implemented = "not_implemented"  # method is not implemented


@dataclass
class DriverResponse:
    """Standardized response for all public driver methods."""

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
    """Generic class for helao drivers w/o base.py dependency.

    Note:
        All public methods must return a DriverResponse object.

    """

    timestamp: datetime
    config: dict

    def __init__(self, config: dict = {}):
        self.timestamp = datetime.now()
        self.config = config

    @property
    def _created_at(self):
        """Instantiation timestamp"""
        return self.timestamp.strftime("%F %T,%f")[:-3]

    @property
    def _uptime(self):
        """Driver uptime"""
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
    """Generic class for helao driver polling w/optional base dependency.

    Subclasses must implement get_data() which returns a dictionary of polled values.

    """

    driver: HelaoDriver
    wait_time: float
    last_update: datetime
    live_dict: dict
    polling: bool

    def __init__(self, driver: HelaoDriver, wait_time: float = 0.05) -> None:
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
        LOGGER.info("got 'start_polling' request, raising signal")
        await self.poll_signalq.put(True)
        while not self.polling:
            LOGGER.info("waiting for polling loop to start")
            await asyncio.sleep(0.1)

    async def _stop_polling(self):
        LOGGER.info("got 'stop_polling' request, raising signal")
        await self.poll_signalq.put(False)
        while self.polling:
            LOGGER.info("waiting for polling loop to stop")
            await asyncio.sleep(0.1)

    async def _poll_signal_loop(self):
        while True:
            self.polling = await self.poll_signalq.get()
            LOGGER.info("polling signal received")

    async def _poll_sensor_loop(self):
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
        LOGGER.info("DriverPoller.get_data() has not been implemented")
        return DriverResponse()
