""" Andor Camera driver for Helao
"""

# save a default log file system temp
from helao.helpers import logging

if logging.LOGGER is None:
    LOGGER = logging.make_logger(logger_name="andor_driver_standalone")
else:
    LOGGER = logging.LOGGER


from helao.drivers.helao_driver import (
    HelaoDriver,
    DriverResponse,
    DriverStatus,
    DriverResponseType,
)


class AndorDriver(HelaoDriver):

    def __init__(self, config: dict = {}):
        super().__init__(config=config)
        # get params from config or use defaults
        self.device_id = self.config.get("dev_id", None)
        LOGGER.info(f"using device_id {self.device_id} from config")
        # if single context is used and held for the duration of the session, connect here, otherwise have executor call self.connect() in self.setup()
        # self.ready = False
        # self.connect()
        self.ready = True

    def connect(self) -> DriverResponse:
        """Open connection to resource."""
        try:
            LOGGER.debug(f"connected to {self.device_id}")

            response = DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception as exc:
            _, _, err_tup = exc.args
            if "In use by another script" in err_tup[0]:
                response = DriverResponse(
                    response=DriverResponseType.success, status=DriverStatus.busy
                )
            else:
                LOGGER.error("get_status connection", exc_info=True)
                response = DriverResponse(
                    response=DriverResponseType.failed, status=DriverStatus.error
                )

        return response

    def get_status(self, retries: int = 5) -> DriverResponse:
        """Return current driver status."""
        try:
            response = DriverResponse(
                response=DriverResponseType.success,
                data={},
                status=DriverStatus.ok,
            )
        except Exception:
            LOGGER.error("get_status failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        return response

    def setup(
        self,
        setup_params: dict = {},  # for mapping action keys to signal keys
    ) -> DriverResponse:
        """Set acquisition conditions on device."""
        try:
            response = DriverResponse(
                response=DriverResponseType.success,
                message="setup complete",
                status=DriverStatus.ok,
            )
        except Exception:
            LOGGER.error("setup failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
            self.cleanup()
        return response

    def set_external_trigger(self) -> DriverResponse:
        """Apply signal and begin data acquisition."""
        try:
            # call function to activate External Trigger mode
            response = DriverResponse(
                response=DriverResponseType.success,
                message="trigger set",
                status=DriverStatus.busy,
            )
        except Exception:
            LOGGER.error("set_external_trigger failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.error,
            )
            self.cleanup()
        return response

    def get_data(self) -> DriverResponse:
        """Retrieve data from device buffer."""
        try:
            data_dict = {}
            # status.busy will cause executor polling loop to continue
            status = DriverStatus.busy
            # status.ok will cause executor polling loop to exit
            status = DriverStatus.ok
            response = DriverResponse(
                response=DriverResponseType.success,
                message="",
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
            # call function to stop ongoing acquisition
            response = DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            LOGGER.error("stop failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        return response

    def cleanup(self):
        """Release state objects."""
        try:
            response = DriverResponse(
                response=DriverResponseType.success,
                message="cleanup complete",
                status=DriverStatus.ok,
            )
        except Exception:
            LOGGER.error("cleanup failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.error,
            )
        return response

    def disconnect(self) -> DriverResponse:
        """Release connection to resource."""
        try:
            response = DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            LOGGER.error("disconnect failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        return response

    def reset(self) -> DriverResponse:
        """Reinitialize driver, force-close old connection if necessary."""
        try:
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
