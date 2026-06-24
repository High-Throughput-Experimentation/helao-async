"""Synaccess Netbooter PDU driver.

Wraps the Netbooter HTTP cgi command interface (`cmd.cgi`) and exposes outlet
switching as blocking methods. The driver has no dependency on the action server
base object; async handling is the server's responsibility. All public methods
return a `DriverResponse`.
"""

import httpx

# save a default log file system temp
from helao.framework.support import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


from helao.framework.ports.driver import (
    HelaoDriver,
    DriverResponse,
    DriverStatus,
    DriverResponseType,
)


class NetbooterDriver(HelaoDriver):
    """HelaoDriver wrapping the Synaccess Netbooter CGI HTTP interface.

    The driver reads `hostname`, `username`, and `password` from `config` and
    builds an authenticated `httpx.Client` pointed at `http://<hostname>/cmd.cgi?`.
    Public methods send `$A3`/`$A7` outlet commands and return a `DriverResponse`.
    The `connect`/`get_status`/`stop`/`reset`/`disconnect` overrides are no-ops
    because every call is an independent HTTP request.
    """

    def __init__(self, config: dict = {}):
        """Initialize the HTTP client from `config`.

        Args:
            config: Driver configuration dict. Required keys: `hostname`,
                `username`, `password`. Missing keys cause the client to be left
                unconfigured and an error to be logged.
        """
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
            self.client = httpx.Client(auth=self.auth, timeout=30.0)
            self.host_url = f"http://{hostname}/cmd.cgi?"

    def switch_outlet(self, outlet_number: int, on: bool, repeat: int = 5) -> DriverResponse:
        """Switch a single outlet on or off, retrying on non-200 responses.

        Args:
            outlet_number: 1-indexed outlet number on the Netbooter.
            on: True to power the outlet on, False to power it off.
            repeat: Maximum number of HTTP attempts before reporting failure.

        Returns:
            A `DriverResponse` reporting success on any HTTP 200, or failure
            after `repeat` unsuccessful attempts.
        """
        for _ in range(repeat):
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

    def switch_all(self, on: bool, repeat: int = 5) -> DriverResponse:
        """Switch every outlet on or off, retrying on non-200 responses.

        Args:
            on: True to power all outlets on, False to power them off.
            repeat: Maximum number of HTTP attempts before reporting failure.

        Returns:
            A `DriverResponse` reporting success on any HTTP 200, or failure
            after `repeat` unsuccessful attempts.
        """
        for _ in range(repeat):
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
        """No-op connect for the HTTP API pass-through; always reports success."""
        return DriverResponse(
            response=DriverResponseType.success,
            message="no connection method for HTTP API pass-thru",
            status=DriverStatus.ok,
        )

    def get_status(self) -> DriverResponse:
        """No-op status query for the HTTP API pass-through; always reports ok."""
        return DriverResponse(
            response=DriverResponseType.success,
            message="no status method for HTTP API pass-thru",
            status=DriverStatus.ok,
        )

    def stop(self) -> DriverResponse:
        """No-op stop for the HTTP API pass-through; always reports success."""
        return DriverResponse(
            response=DriverResponseType.success,
            message="no stop method for HTTP API pass-thru",
            status=DriverStatus.ok,
        )

    def reset(self) -> DriverResponse:
        """No-op reset for the HTTP API pass-through; always reports success."""
        return DriverResponse(
            response=DriverResponseType.success,
            message="no reset method for HTTP API pass-thru",
            status=DriverStatus.ok,
        )

    def disconnect(self) -> DriverResponse:
        """No-op disconnect for the HTTP API pass-through; always reports success."""
        return DriverResponse(
            response=DriverResponseType.success,
            message="no disconnection method for HTTP API pass-thru",
            status=DriverStatus.ok,
        )
