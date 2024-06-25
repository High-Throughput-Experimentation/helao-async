""" HelaoDriver wrapper around easy-biologic package for Biologic potentiostats

https://github.com/bicarlsen/easy-biologic

Notes:
- import easy_biologic as ebl
- import easy_biologic.base_programs as blp
- establish connection using `ebl.BiologicDevice('ip_address')`
- create technique using blp.OCV, blp.CP, etc. with set channels
- run technique using retrieve_data=False
- manually call _retrieve_data_segment to get single channel data

"""

from typing import Optional

# save a default log file system temp
from helao.helpers import logging

if logging.LOGGER is None:
    LOGGER = logging.make_logger(logger_name="biologic_driver_standalone")
else:
    LOGGER = logging.LOGGER

import easy_biologic as ebl

from helao.drivers.helao_driver import (
    HelaoDriver,
    DriverResponse,
    DriverStatus,
    DriverResponseType,
)

from .technique import BiologicTechnique


class BiologicDriver(HelaoDriver):
    device_name: str
    connection_raised: bool

    def __init__(self, config: dict = {}):
        super().__init__(config=config)
        #
        self.address = config.get(key="address", default="192.168.200.240")
        self.num_channels = config.get(key="num_channels", default=12)
        self.device_name = "unknown"
        self.connection_raised = False
        self.pstat = ebl.BiologicDevice(self.address)
        self.connect()

    def connect(self) -> DriverResponse:
        """Open connection to resource."""
        try:
            if self.connection_raised:
                raise ConnectionError(
                    "Connection already raised. In use by another script."
                )
            self.pstat.connect()
            self.connection_raised = True
            LOGGER.debug(f"connected to {self.device_name} on device_id {self.address}")
            response = DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception as exc:
            if "In use by another script" in exc.__str__():
                response = DriverResponse(
                    response=DriverResponseType.failed, status=DriverStatus.busy
                )
            else:
                LOGGER.error("get_status connection", exc_info=True)
                response = DriverResponse(
                    response=DriverResponseType.failed, status=DriverStatus.error
                )
        return response

    def get_status(self, channel: Optional[int] = None) -> DriverResponse:
        """Return current driver status."""
        try:
            if channel is None:
                infos = [self.pstat.channel_info(i) for i in range(self.num_channels)]
                states = [x.State for x in infos]
                status = (
                    DriverStatus.busy
                    if any([x > 0 for x in states])
                    else DriverStatus.ok
                )
            else:
                info = self.pstat.channel_info(channel)
                status = DriverStatus.busy if info.State > 0 else DriverStatus.ok
            response = DriverResponse(
                response=DriverResponseType.success, status=status
            )
        except Exception:
            LOGGER.error("get_status failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        return response

    def setup(
        self,
        technique: BiologicTechnique,
        action_params: dict = {},  # for mapping action keys to signal keys
        channel: int = 0,
    ) -> DriverResponse:
        """Set measurement conditions on potentiostat."""
        try:
            # TODO: validate channel in use
            parmap = technique.parameter_map
            mapped_params = {
                parmap[k]: v for k, v in action_params.items() if k in action_params
            }
            program = technique.easy_class(self.pstat, params=mapped_params)
            response = DriverResponse(
                response=DriverResponseType.success,
                message="setup complete",
                status=DriverStatus.ok,
            )
            response.program = program
        except Exception:
            LOGGER.error("setup failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
            self.cleanup()
        return response

    def measure(self, ttl_params: dict = {}) -> DriverResponse:
        """Apply signal and begin data acquisition."""
        try:
            # emit TTL output
            ttl_send = ttl_params.get("TTLsend", -1)
            if ttl_send > -1:
                self.pstat.SetDigitalOut(*TTL_OUTPUTS[ttl_send])
            # energize cell
            self.pstat.SetCell(getattr(self.GamryCOM, self.technique.on_method.value))
            # run data acquisition
            self.events = client.GetEvents(self.dtaq, self.dtaqsink)
            start_time = time.time()
            self.dtaq.Run(True)
            response = DriverResponse(
                response=DriverResponseType.success,
                message="measurement started",
                data={"start_time": start_time},
                status=DriverStatus.busy,
            )
        except comtypes.COMError:
            LOGGER.error("measure failed on COMError", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.error,
            )
            self.reset()
            self.cleanup()
        except Exception:
            LOGGER.error("measure failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.error,
            )
            self.cleanup()
        return response

    def get_data(self, pump_rate: float) -> DriverResponse:
        """Retrieve data from device buffer."""
        try:
            client.PumpEvents(pump_rate)
            total_points = len(self.dtaqsink.acquired_points)
            if self.counter < total_points:
                new_data = self.dtaqsink.acquired_points[self.counter : total_points]
                data_dict = {
                    k: v
                    for k, v in zip(
                        self.technique.dtaq.output_keys, np.matrix(new_data).T.tolist()
                    )
                }
            else:
                data_dict = {}

            sink_state = self.dtaqsink.status
            if sink_state == "measuring" or self.counter < total_points:
                status = DriverStatus.busy
            elif sink_state == "done":
                status = DriverStatus.ok
            else:
                status = DriverStatus.ok
            self.counter = total_points
            response = DriverResponse(
                response=DriverResponseType.success,
                message=sink_state,
                data=data_dict,
                status=status,
            )
        except Exception:
            LOGGER.error("get_data failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.error,
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
            LOGGER.error("stop failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        return response

    def cleanup(self, ttl_params: dict = {}):
        """Release state objects but don't close pstat."""
        try:
            if self.pstat is not None:
                # disable TTL output
                ttl_send = ttl_params.get("TTLsend", -1)
                if ttl_send > -1:
                    self.pstat.SetDigitalOut(*TTL_OFF[ttl_send])
                self.pstat.SetCell(self.GamryCOM.CellOff)
            response = DriverResponse(
                response=DriverResponseType.success,
                message="measurement started",
                status=DriverStatus.ok,
            )
        except Exception:
            LOGGER.error("cleanup failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.error,
            )
        finally:
            self.events = None
            self.dtaq = None
            self.dtaqsink = DUMMY_SINK
            self.technique = None
            self.signal = None
            self.counter = 0
        return response

    def disconnect(self) -> DriverResponse:
        """Release connection to resource."""
        try:
            if self.pstat is not None:
                self.pstat.SetCell(self.GamryCOM.CellOff)
                self.pstat.Close()
            # self.ready = False
            response = DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            LOGGER.error("disconnect failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        finally:
            self.pstat = None
            comtypes.CoUninitialize()
            self.connection_raised = False
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
                LOGGER.info(f"killing GamryCOM on PID: {pid}")
                p = psutil.Process(pid)
                for _ in range(3):
                    p.terminate()
                    time.sleep(0.5)
                    if not psutil.pid_exists(p.pid):
                        LOGGER.info("Successfully terminated GamryCom.")
                if psutil.pid_exists(p.pid):
                    LOGGER.warning(
                        "Failed to terminate server GamryCom after 3 retries."
                    )
                    raise SystemError(f"GamryCOM on PID: {pid} is still running.")
            self.GamryCOM = client.GetModule(
                ["{BD962F0D-A990-4823-9CF5-284D1CDD9C6D}", 1, 0]
            )
            self.pstat = None
            # self.ready = False
            # self.connect()
            response = DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            LOGGER.error("reset error", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        return response

    def shutdown(self) -> None:
        """Pass-through shutdown events for BaseAPI."""
        self.cleanup()
        self.disconnect()
