"""Gamry potentiostat driver using HelaoDriver abstract base class

This Gamry driver has zero dependencies on action server base object.
All public methods must return a DriverResponse.

"""

# save a default log file system temp
from helao.helpers import logging

if logging.LOGGER is None:
    logger = logging.make_logger(logger_name="gamry_driver_standalone")
else:
    logger = logging.LOGGER

import comtypes
import comtypes.client as client
import psutil
import time
from enum import Enum
from collections import defaultdict

# import asyncio
import numpy as np

from helao.drivers.helao_driver import (
    HelaoDriver,
    DriverResponse,
    DriverStatus,
    DriverResponseType,
)

from .device import GamryPstat, GAMRY_DEVICES, TTL_OUTPUTS
from .sink import GamryDtaqSink, DummySink
from .technique import GamryTechnique
from .range import get_range, RANGES

DUMMY_SINK = DummySink()


class GamryDriver(HelaoDriver):
    dtaqsink: GamryDtaqSink
    device_name: str
    model: GamryPstat

    def __init__(self, config: dict = {}):
        super().__init__()
        #
        self.device_name = "unknown"
        self.dtaq = None
        self.dtaqsink = DUMMY_SINK
        self.events = None
        self.technique = None
        self.pstat = None
        self.ready = False
        # get params from config or use defaults
        self.device_id = self.config.get("device_id", None)
        self.filterfreq_hz = 1.0 * self.config.get("filterfreq_hz", 1000.0)
        self.grounded = int(self.config.get("grounded", True))
        logger.info(f"using device_id {self.device_id} from config")

    def connect(self) -> DriverResponse:
        """Open connection to resource."""
        try:
            self.GamryCOM = client.GetModule(
                ["{BD962F0D-A990-4823-9CF5-284D1CDD9C6D}", 1, 0]
            )
            devices = client.CreateObject("GamryCOM.GamryDeviceList")
            self.device_name = devices.EnumSections()[self.device_id]
            self.model = GAMRY_DEVICES[self.device_name]
            self.pstat = client.CreateObject(self.model.device)
            self.pstat.Init(self.device_name)
            self.pstat.Open()
            logger.info(
                f"connected to {self.device_name} on device_id {self.device_id}"
            )

            # apply initial configuration
            self.pstat.SetCell(self.GamryCOM.CellOff)
            self.pstat.SetPosFeedEnable(False)
            self.pstat.SetIEStability(self.GamryCOM.StabilityFast)
            self.pstat.SetSenseSpeedMode(self.model.set_sensemode)
            self.pstat.SetIConvention(self.GamryCOM.Anodic)
            self.pstat.SetGround(self.config.get("grounded", True))
            # maximum anticipated voltage (in Volts).
            ichrangeval = self.pstat.TestIchRange(3.0)
            self.pstat.SetIchRange(ichrangeval)
            self.pstat.SetIchRangeMode(True)  # auto-set
            self.pstat.SetIchOffsetEnable(False)
            # call TestIchFilter before setting SetIchFilter
            ichfilterval = self.pstat.TestIchFilter(
                self.config.get("filterfreq_hz", 1000.0)
            )
            self.pstat.SetIchFilter(ichfilterval)
            # voltage channel range.
            vchrangeval = self.pstat.TestVchRange(12.0)
            self.pstat.SetVchRange(vchrangeval)
            self.pstat.SetVchRangeMode(True)
            self.pstat.SetVchOffsetEnable(False)
            # call TestVchFilter before setting SetVchFilter
            vchfilterval = self.pstat.TestVchFilter(
                self.config.get("filterfreq_hz", 1000.0)
            )
            self.pstat.SetVchFilter(vchfilterval)
            # set the range of the Auxiliary A/D input.
            self.pstat.SetAchRange(3.0)
            # set the I/E Range of the potentiostat.
            self.pstat.SetAnalogOut(0.0)
            self.pstat.SetIruptMode(self.GamryCOM.IruptOff)
            self.ready = True
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
            self.dtaq.Run(False)
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
        try:
            process_ids = {
                p.pid: p
                for p in psutil.process_iter(["name", "connections"])
                if p.info["name"].startswith("GamryCom")
            }

            for pid in process_ids:
                logger.info(f"killing GamryCOM on PID: {pid}")
                p = psutil.Process(pid)
                for _ in range(3):
                    p.terminate()
                    time.sleep(0.5)
                    if not psutil.pid_exists(p.pid):
                        logger.info("Successfully terminated GamryCom.")
                if psutil.pid_exists(p.pid):
                    logger.warning(
                        "Failed to terminate server GamryCom after 3 retries."
                    )
                    raise SystemError(f"GamryCOM on PID: {pid} is still running.")
            self.GamryCOM = client.GetModule(
                ["{BD962F0D-A990-4823-9CF5-284D1CDD9C6D}", 1, 0]
            )
            self.pstat = None
            self.ready = False
            self.connect()
            response = DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            logger.error("reset error", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        return response

    def disconnect(self) -> DriverResponse:
        """Release connection to resource."""
        try:
            self.pstat.SetCell(self.GamryCOM.CellOff)
            self.pstat.Close()
            self.pstat = None
            self.ready = False
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
        ierange: Enum = "auto",
    ) -> DriverResponse:
        """Set measurement conditions on potentiostat."""
        try:
            # set device-specific ranges
            self.technique = technique
            self.pstat.SetIERange(0.03)  # default range
            range_enum = get_range(ierange, self.model.ierange)
            if range_enum == self.model.ierange.auto:
                self.pstat.SetIERangeMode(self.model.set_rangemode)
            else:
                self.pstat.SetIERange(RANGES[range_enum.name])
            # override device-specific ranges with technique ranges if given
            self.pstat.SetCtrlMode(getattr(self.GamryCOM, technique.signal.mode.value))
            if technique.set_vchrangemode is not None:
                self.pstat.SetVchRangeMode(technique.set_vchrangemode)
            if technique.vchrange_keys is not None:
                setpointv = np.max(
                    [np.abs(signal_params[x]) for x in technique.vchrange_keys]
                )
                vchrangeval = self.pstat.TestVchRange(setpointv * 1.1)
                self.pstat.SetVchRange(vchrangeval)
            if technique.set_ierangemode is not None:
                self.pstat.SetIERangeMode(technique.set_ierangemode)
            if technique.ierange_keys is not None:
                setpointie = np.max(
                    [np.abs(signal_params[x]) for x in technique.ierange_keys]
                )
                ierangeval = self.pstat.TestIERange(setpointie)
                self.pstat.SetIERange(ierangeval)
            if technique.set_decimation is not None:
                self.pstat.SetDecimation(technique.set_decimation)
            # initialize dtaq
            self.dtaq = client.CreateObject(technique.dtaq.name)
            dtaq_init_args = (signal_params[x] for x in technique.signal.init_keys)
            if technique.dtaq.dtaq_type is not None:
                self.dtaq.Init(self.pstat, technique.dtaq.dtaq_type, *dtaq_init_args)
            else:
                self.dtaq.Init(self.pstat, *dtaq_init_args)
            # apply dtaq limits
            for dtaq_key in technique.dtaq.int_param_keys:
                val = dtaq_params.get(dtaq_key, 1)
                getattr(self.dtaq, dtaq_key)(val)
            for dtaq_key in technique.dtaq.bool_param_keys:
                val = dtaq_params.get(dtaq_key, 0.0)
                enable = dtaq_key in dtaq_params
                getattr(self.dtaq, dtaq_key)(enable, val)
            # create event sink
            self.dtaqsink = GamryDtaqSink(self.dtaq)
            # check for missing parameter keys
            missing_keys = [
                key
                for key in technique.signal.param_keys + technique.signal.init_keys
                if key not in signal_params
            ]
            if missing_keys:
                raise KeyError(
                    f"missing parameter keys {missing_keys} required by {technique.name}"
                )
            signal_paramlist = (
                [self.pstat]
                + [signal_params[key] for key in technique.signal.param_keys]
                + [getattr(self.GamryCOM, self.technique.signal.mode.value)]
            )
            signal = client.CreateObject(technique.signal.name)
            signal.Init(*signal_paramlist)
            self.pstat.SetSignal(signal)
            response = DriverResponse(
                response=DriverResponseType.success,
                message="setup complete",
                status=DriverStatus.ok,
            )
        except comtypes.COMError:
            logger.error("setup failed on COMError", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
            self.reset()
        except Exception:
            logger.error("setup failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        return response

    def measure(self, ttl_params: dict = {}) -> DriverResponse:
        """Apply signal and begin data acquisition."""
        try:
            # # wait for TTL input -- do this in Executor to decouple async
            # if ttl_params.get("TTLwait", -1) > 0:
            #     bits = self.pstat.DigitalIn()
            #     logger.info(f"Gamry DIbits: {bits}, waiting for trigger.")
            #     while not bits:
            #         await asyncio.sleep(0.01)
            #         bits = self.pstat.DigitalIn()

            # emit TTL output
            ttl_send = ttl_params.get("TTLsend", -1)
            if ttl_send > 0:
                self.pstat.SetDigitalOut(*TTL_OUTPUTS[ttl_send])
            # energize cell
            self.pstat.SetCell(getattr(self.GamryCOM, self.technique.on_method.value))
            # run data acquisition
            self.events = client.GetEvents(self.dtaq, self.dtaqsink)
            self.dtaq.Run(True)
            response = DriverResponse(
                response=DriverResponseType.success,
                message="measurement started",
                status=DriverStatus.busy,
            )
        except comtypes.COMError:
            logger.error("measure failed on COMError", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.error,
            )
            self.reset()
            self.cleanup()
        except Exception:
            logger.error("measure failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.error,
            )
            self.cleanup()
        return response

    def cleanup(self):
        """Release state objects."""
        try:
            self.pstat.SetCell(self.GamryCOM.CellOff)
            self.events = None
            self.dtaq = None
            self.dtaqsink = DUMMY_SINK
            self.technique = None
            self.counter = 0
            response = DriverResponse(
                response=DriverResponseType.success,
                message="measurement started",
                status=DriverStatus.ok,
            )
        except Exception:
            logger.error("cleanup failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.error,
            )
        return response

    def get_data(self, pump_rate: float) -> DriverResponse:
        """Retrieve data from device buffer."""
        try:
            client.PumpEvents(pump_rate) 
            total_points = len(self.dtaqsink.acquired_points)
            if self.counter < total_points:
                new_data = self.dtaqsink.acquired_points[self.counter:total_points]
                data_dict = {k: v for k, v in zip(self.technique.dtaq.output_keys, np.matrix(new_data).T.tolist())}
            else:
                data_dict = {}
            sink_state = self.dtaqsink.status
            if sink_state == "measuring":
                status = DriverStatus.busy
            elif sink_state == "done":
                logger.info("measurement complete, DtaqSink received DataDone")
                status = DriverStatus.ok
            else:
                logger.info("dtaq is idle")
                status = DriverStatus.ok
            response = DriverResponse(
                response=DriverResponseType.success,
                message=sink_state,
                data=data_dict,
                status=status,
            )
        except Exception:
            logger.error("get_data failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.error,
            )
        return response
