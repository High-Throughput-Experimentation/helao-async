"""Synaccess Netbooter driver using HelaoDriver abstract base class

Synaccess driver has zero dependencies on action server base object, and all
exposed methods are intended to be blocking. Async should be handled in the server.
All public methods must return a DriverResponse.

"""

# save a default log file system temp
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
import time
from enum import Enum
from copy import copy

import numpy as np

from helao.core.drivers.helao_driver import (
    HelaoDriver,
    DriverResponse,
    DriverStatus,
    DriverResponseType,
)

DUMMY_SINK = DummySink()


class NetbooterDriver(HelaoDriver):

    def __init__(self, config: dict = {}):
        super().__init__(config=config)
        # get params from config or use defaults
        self.connection_raised = False
        self.stopping = False
        self.connect()
        LOGGER.debug(f"connected to {self.device_name} on device_id {self.device_id}")

    def connect(self) -> DriverResponse:
        """Open connection to resource."""
        pass

    def get_status(self) -> DriverResponse:
        """Return current driver status."""
        pass

    def stop(self) -> DriverResponse:
        """General stop method, abort all active methods e.g. motion, I/O, compute."""
        pass

    def reset(self) -> DriverResponse:
        """Reinitialize driver, force-close old connection if necessary."""
        pass

    def disconnect(self) -> DriverResponse:
        """Release connection to resource."""
        pass
