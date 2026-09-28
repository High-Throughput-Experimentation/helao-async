"""Synaccess Netbooter PDU driver.

Wraps the Netbooter HTTP cgi command interface (`cmd.cgi`) and exposes outlet
switching as blocking methods. The driver has no dependency on the action server
base object; async handling is the server's responsibility. All public methods
return a `DriverResponse`.
"""

import time

import httpx

# save a default log file system temp
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


from helao.core.drivers.helao_driver import (
    DriverResponse,
    DriverResponseType,
    DriverStatus,
    HelaoDriver,
)


class NetbooterDriver(HelaoDriver):
    """HelaoDriver wrapping the Synaccess Netbooter CGI HTTP interface.

    The driver reads `hostname`, `username`, and `password` from `config` and
    builds an `httpx.Client` that sends HTTP basic auth to
    `http://<hostname>/cmd.cgi?`. Public methods send `$A3`/`$A7` outlet commands
    and return a `DriverResponse`. A command succeeds only when the PDU answers
    HTTP 200 with a `$A0` body; `$AF` means the PDU rejected it.
    The `connect`/`get_status`/`stop`/`reset`/`disconnect` overrides are no-ops
    because every call is an independent HTTP request.
    """

    def __init__(self, config: dict = {}):
        """Initialize the HTTP client from `config`.

        Args:
            config: Driver configuration dict. Required keys: `hostname`,
                `username`, `password`. Optional: `timeout` (seconds per request,
                default 5) and `retry_delay` (seconds between attempts, default
                0.5). Missing required keys leave the client unconfigured, log an
                error, and make every command return a failed response.
        """
        super().__init__(config=config)
        # get params from config or use defaults
        hostname = self.config.get("hostname", None)
        username = self.config.get("username", None)
        password = self.config.get("password")
        self.retry_delay = self.config.get("retry_delay", 0.5)
        self.auth = None
        self.client = None
        self.host_url = None
        if hostname is None or username is None or password is None:
            LOGGER.error(
                "Missing parameters, check 'hostname', 'username', and 'password' in supplied config."
            )
        else:
            self.auth = httpx.BasicAuth(username=username, password=password)
            # The Netbooter's embedded web server drops idle sockets, so a pooled
            # keep-alive connection fails on the next request. Open a fresh
            # connection per command instead.
            self.client = httpx.Client(
                auth=self.auth,
                timeout=self.config.get("timeout", 5.0),
                limits=httpx.Limits(max_keepalive_connections=0),
            )
            self.host_url = f"http://{hostname}/cmd.cgi?"

    def _send(self, cmd: str, desc: str, repeat: int) -> DriverResponse:
        """Send one `cmd.cgi` command, retrying until the PDU answers `$A0`.

        Args:
            cmd: URL-encoded command string, e.g. `$A3%201%201`.
            desc: Human-readable action for the response message.
            repeat: Maximum number of HTTP attempts before reporting failure.

        Returns:
            A success `DriverResponse` on HTTP 200 with a `$A0` body; otherwise a
            failed one carrying the last status/body or exception.
        """
        if self.client is None:
            return DriverResponse(
                response=DriverResponseType.failed,
                message=f"could not {desc}: missing hostname/username/password",
                status=DriverStatus.error,
            )
        last = "no attempts made"
        for attempt in range(repeat):
            if attempt:
                time.sleep(self.retry_delay)
            try:
                resp = self.client.get(f"{self.host_url}{cmd}")
            except httpx.HTTPError as exc:
                last = f"{type(exc).__name__}: {exc}"
                LOGGER.warning(f"{desc} attempt {attempt + 1}/{repeat}: {last}")
                continue
            body = resp.text.strip()
            if resp.status_code == 200 and body.startswith("$A0"):
                return DriverResponse(
                    response=DriverResponseType.success,
                    message=desc,
                    status=DriverStatus.ok,
                )
            last = f"HTTP {resp.status_code} {body[:40]!r}"
            LOGGER.warning(f"{desc} attempt {attempt + 1}/{repeat}: {last}")
        return DriverResponse(
            response=DriverResponseType.failed,
            message=f"could not {desc} after {repeat} attempts, last: {last}",
            status=DriverStatus.error,
        )

    def switch_outlet(
        self, outlet_number: int, on: bool, repeat: int = 5
    ) -> DriverResponse:
        """Switch a single outlet on or off (`$A3`), retrying on failure.

        Args:
            outlet_number: 1-indexed outlet number on the Netbooter.
            on: True to power the outlet on, False to power it off.
            repeat: Maximum number of HTTP attempts before reporting failure.

        Returns:
            A `DriverResponse`; see `_send`.
        """
        return self._send(
            f"$A3%20{outlet_number:d}%20{on:d}",
            f"switch outlet {outlet_number:d} {'on' if on else 'off'}",
            repeat,
        )

    def switch_all(self, on: bool, repeat: int = 5) -> DriverResponse:
        """Switch every outlet on or off (`$A7`), retrying on failure.

        Args:
            on: True to power all outlets on, False to power them off.
            repeat: Maximum number of HTTP attempts before reporting failure.

        Returns:
            A `DriverResponse`; see `_send`.
        """
        return self._send(
            f"$A7%20{on:d}", f"switch all outlets {'on' if on else 'off'}", repeat
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
