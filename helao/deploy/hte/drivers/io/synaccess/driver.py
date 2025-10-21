"""Synaccess Netbooter driver using HelaoDriver abstract base class

Synaccess driver has zero dependencies on action server base object, and all
exposed methods are intended to be blocking. Async should be handled in the server.
All public methods must return a DriverResponse.

"""

import httpx

# save a default log file system temp
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


from helao.core.drivers.helao_driver import (
    HelaoDriver,
    DriverResponse,
    DriverStatus,
    DriverResponseType,
)


class NetbooterDriver(HelaoDriver):

    def __init__(self, config: dict = {}):
        super().__init__(config=config)
        # get params from config or use defaults
        hostname = self.config.get("hostname", None)
        username = self.config.get("username", None)
        password = self.config.get("password")
        self.auth = None
        self.client = None
        self.host_url = None
        if any([par is None for par in (hostname, username, password)]):
            LOGGER.error(
                "Missing parameters, check 'hostname', 'username', and 'password' in supplied config."
            )
        else:
            self.auth = httpx.BasicAuth(username=username, password=password)
            self.client = httpx.Client(auth=self.auth)
            self.host_url = f"http://{hostname}/cmd.cgi?"

    def switch_outlet(self, outlet_number: int, on: bool):
        resp = self.client.get(f"{self.host_url}$A3%20{outlet_number:d}%20{on:d}")
        if resp.status_code == 200:
            return DriverResponse(
                response=DriverResponseType.success,
                message=f"switched outlet {outlet_number:d} {'on' if on else 'off'}",
                status=DriverStatus.ok,
            )
        return DriverResponse(
            response=DriverResponseType.failed,
            message=f"could not switch outlet {outlet_number:d} {'on' if on else 'off'}",
            status=DriverStatus.error,
        )

    def switch_all(self, on: bool):
        resp = self.client.get(f"{self.host_url}$A7%20{on:d}")
        if resp.status_code == 200:
            return DriverResponse(
                response=DriverResponseType.success,
                message=f"switched all outlets {'on' if on else 'off'}",
                status=DriverStatus.ok,
            )
        return DriverResponse(
            response=DriverResponseType.failed,
            message=f"could not switch all outlets {'on' if on else 'off'}",
            status=DriverStatus.error,
        )

    def connect(self) -> DriverResponse:
        """Open connection to resource."""
        return DriverResponse(
            response=DriverResponseType.success,
            message="no connection method for HTTP API pass-thru",
            status=DriverStatus.ok,
        )

    def get_status(self) -> DriverResponse:
        """Return current driver status."""
        return DriverResponse(
            response=DriverResponseType.success,
            message="no status method for HTTP API pass-thru",
            status=DriverStatus.ok,
        )

    def stop(self) -> DriverResponse:
        """General stop method, abort all active methods e.g. motion, I/O, compute."""
        return DriverResponse(
            response=DriverResponseType.success,
            message="no stop method for HTTP API pass-thru",
            status=DriverStatus.ok,
        )

    def reset(self) -> DriverResponse:
        """Reinitialize driver, force-close old connection if necessary."""
        return DriverResponse(
            response=DriverResponseType.success,
            message="no reset method for HTTP API pass-thru",
            status=DriverStatus.ok,
        )

    def disconnect(self) -> DriverResponse:
        """Release connection to resource."""
        return DriverResponse(
            response=DriverResponseType.success,
            message="no disconnection method for HTTP API pass-thru",
            status=DriverStatus.ok,
        )
