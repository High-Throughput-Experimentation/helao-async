"""Gamry potentiostat driver using HelaoDriver abstract base class

This Gamry driver has zero dependencies on action server base object.
All public methods must return a DriverResponse.

"""

# save a default log file system temp
from helao.helpers import logging

if logging.LOGGER is None:
    logger = logging.make_logger(logger_name="default_helao")
else:
    logger = logging.LOGGER

import comtypes
import comtypes.client as client
import psutil
from enum import Enum


from helao.drivers.helao_driver import (
    HelaoDriver,
    DriverResponse,
    DriverStatus,
    DriverResponseType,
)

from .gamry_device import GamryPstat, GAMRY_DEVICES
from .gamry_sink import GamryDtaqSink, DummySink
from .gamry_technique import GamryTechnique


class GamryDriver(HelaoDriver):
    dtaqsink: GamryDtaqSink
    device_name: str
    model: GamryPstat

    def __init__(self, config: dict = {}):
        super().__init__()
        #
        self.device_name = "unknown"
        self.dtaq = None  # from client.CreateObject
        self.dtaqsink = DummySink()
        self.com = client.GetModule(["{BD962F0D-A990-4823-9CF5-284D1CDD9C6D}", 1, 0])
        # get params from config or use defaults
        self.device_id = self.config.get("device_id", None)
        self.filterfreq_hz = 1.0 * self.config.get("filterfreq_hz", 1000.0)
        self.grounded = int(self.config.get("grounded", True))
        logger.info(f"using device_id {self.device_id} from config")

    def connect(self) -> DriverResponse:
        """Open connection to resource."""
        try:
            devices = client.CreateObject("GamryCOM.GamryDeviceList")
            self.device_name = devices.EnumSections()[self.device_id]
            self.model = GAMRY_DEVICES[self.device_name]
            self.pstat = client.CreateObject(self.model.device)
            self.pstat.Init(self.device_name)
            self.pstat.Open()
            logger.info(
                f"connected to {self.device_name} on device_id {self.device_id}"
            )
            response = DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            logger.error("connection failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )

        return response

    def get_status(self) -> DriverResponse:
        """Return current driver status."""
        try:
            state = self.pstat.State()
            state = dict([x.split("\t") for x in state.split("\r\n") if x])
            response = DriverResponse(
                response=DriverResponseType.success, data=state, status=DriverStatus.ok
            )
        except Exception:
            logger.error("get_status failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        return response

    def stop(self) -> DriverResponse:
        """General stop method to abort all active methods e.g. motion, I/O, compute."""
        try:
            self.dtaq.run(False)
            response = DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            logger.error("stop failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        return response

    def reset(self) -> DriverResponse:
        """Reinitialize driver, force-close old connection if necessary."""
        return DriverResponse()

    def disconnect(self) -> DriverResponse:
        """Release connection to resource."""
        try:
            self.pstat.SetCell(self.com.CellOff)
            self.pstat.Close()
            response = DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            logger.error("disconnect failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        return response

    def setup(
        self,
        technique: GamryTechnique,
        signal_params: dict = {},
        dtaq_params: dict = {},
        ttl_params: dict = {},
        ierange: Enum = "auto",
    ) -> DriverResponse:
        """Set measurement conditions on potentiostat."""
        #
        return DriverResponse()

    def measure(self) -> DriverResponse:
        """Apply signal and begin data acquisition."""
        return DriverResponse()

    def pump_events(self) -> DriverResponse:
        """Retrieve data from device buffer."""
        return DriverResponse()
