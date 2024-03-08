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

from abc import ABC, abstractmethod
from enum import StrEnum
from datetime import datetime
from dataclasses import dataclass, field

from helao.helpers import logging

if logging.LOGGER is None:
    logger = logging.make_logger(logger_name="default_helao")
else:
    logger = logging.LOGGER


class DriverStatus(StrEnum):
    ok = "ok"
    busy = "busy"
    error = "error"
    uninitialized = "uninitialized"
    unknown = "unknown"

class DriverResponseType(StrEnum):
    success = "success"
    failed = "failed"
    not_implemented = "not_implemented"


@dataclass
class DriverMessage:
    timestamp: datetime = datetime.now()

    @property
    def timestamp_str(self):
        return self.timestamp.strftime('%F %T,%f')[:-3]


@dataclass
class DriverResponse(DriverMessage):
    response: DriverResponseType = DriverResponseType.not_implemented
    message: str = ""
    data: dict = field(default_factory=dict)
    status: DriverStatus = DriverStatus.unknown


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
        return self.timestamp.strftime('%F %T,%f')[:-3]
    
    @property
    def _uptime(self):
        """Driver uptime"""
        return (datetime.now() - self.timestamp).strftime('%F %T,%f')[:-3]

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

