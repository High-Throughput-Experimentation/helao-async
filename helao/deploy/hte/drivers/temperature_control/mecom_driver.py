"""Meerstetter MeCom TEC driver and HELAO executors.

Wraps the ``mecom`` library to talk to a Meerstetter TEC over serial,
periodically poll parameters such as object temperature and stability via
``MeerstetterTECPoller``, and expose monitor/wait executors usable by the
temperature-control action server.
"""

__all__ = ["MeerstetterTEC", "MeerstetterTECPoller", "TECMonExec", "TECWaitExec"]

import asyncio
import time

from mecom import MeCom, ResponseException, WrongChecksum
from mecom.exceptions import ResponseTimeout

from helao.core.drivers.helao_driver import (
    DriverPoller,
    DriverResponse,
    DriverResponseType,
    DriverStatus,
    HelaoDriver,
)
from helao.core.error import ErrorCodes
from helao.core.models.hlostatus import HloStatus
from helao.helpers import helao_logging as logging
from helao.helpers.executor import Executor

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

# default queries from command table below
DEFAULT_QUERIES = [
    "enabled_status",
    "object_temperature",
    "target_object_temperature",
    "output_current",
    "temperature_is_stable",
]

# syntax
# { display_name: [parameter_id, unit], }
COMMAND_TABLE = {
    "device_status": [104, ""],
    "enabled_status": [2010, ""],
    "temperature_is_stable": [1200, ""],
    "object_temperature": [1000, "degC"],
    "target_object_temperature": [1010, "degC"],
    "output_current": [1020, "A"],
    "output_voltage": [1021, "V"],
    "sink_temperature": [1001, "degC"],
    "ramp_temperature": [1011, "degC"],
}


class MeerstetterTEC(HelaoDriver):
    """``HelaoDriver`` wrapper for a Meerstetter TEC device controlled over serial.

    The ``MeCom`` serial session is opened by :meth:`connect`, not by
    construction; always-on telemetry polling is handled by the paired
    :class:`MeerstetterTECPoller`, wired in as the server's ``poller_class``.
    Exposes helpers to enable/disable the control loop and set the target
    object temperature.

    Server config parameters:
        ``channel``: TEC channel/parameter-instance index.
        ``port``: Serial port for the MeCom session.
        ``retries``: Handshake retry count on ``ResponseTimeout`` (default 15).
        ``queries``: Parameter names to poll (default ``DEFAULT_QUERIES``).
        ``start_margin``, ``allow_no_sample``: Carried for parity; unused by
            this driver.
    """

    def __init__(self, config: dict = {}):
        """Store config; the MeCom session is opened in :meth:`connect`.

        Args:
            config: Driver configuration (the server's ``params`` dict).
        """
        super().__init__(config=config)
        self.config_dict = self.config
        self.channel = self.config_dict["channel"]
        self.port = self.config_dict["port"]
        self.queries = self.config_dict.get("queries", DEFAULT_QUERIES)
        self._session = None
        self.address = None

        self.action = None
        self.active = None
        self.start_margin = self.config_dict.get("start_margin", 0)
        self.start_time = 0
        self.last_rec_time = 0
        self.recording_duration = 0
        self.recording_rate = 0.1  # seconds per acquisition
        self.allow_no_sample = self.config_dict.get("allow_no_sample", True)

    def _connect(self):
        """Open a ``MeCom`` session on ``self.port`` and identify the address."""
        # open session
        self._session = MeCom(serialport=self.port, timeout=1)
        # get device address
        self.address = self._session.identify()
        LOGGER.info("connected to {}".format(self.address))

    def connect(self) -> DriverResponse:
        """Open the MeCom session, retrying the handshake on timeouts.

        Returns:
            ``DriverResponse`` reporting connection success or failure.
        """
        connection_retries = self.config_dict.get("retries", 15)
        for i in range(connection_retries):
            try:
                self._connect()
                return DriverResponse(
                    response=DriverResponseType.success, status=DriverStatus.ok
                )
            except ResponseTimeout:
                LOGGER.info(f"connection timeout, retrying attempt {i+1}")
        LOGGER.error("connect failed: exhausted retries")
        return DriverResponse(
            response=DriverResponseType.failed, status=DriverStatus.error
        )

    def session(self):
        """Return the active session, lazily reconnecting if needed."""
        if self._session is None:
            self._connect()
        return self._session

    def get_status(self) -> DriverResponse:
        """Return whether the MeCom session has been opened.

        Returns:
            ``DriverResponse`` with ``status=ok`` if connected, else
            ``status=uninitialized``.
        """
        if self._session is not None:
            return DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        return DriverResponse(
            response=DriverResponseType.success, status=DriverStatus.uninitialized
        )

    def stop(self) -> DriverResponse:
        """No active operation to abort; reports current status."""
        return DriverResponse(
            response=DriverResponseType.success, status=DriverStatus.ok
        )

    def reset(self) -> DriverResponse:
        """Force-close and reopen the MeCom session."""
        self.disconnect()
        return self.connect()

    def disconnect(self) -> DriverResponse:
        """Close the underlying MeCom session."""
        try:
            if self._session is not None:
                self._session.stop()
            response = DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            LOGGER.error("disconnect failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        finally:
            self._session = None
        return response

    def shutdown(self):
        """No-op; `async_shutdown` handles safe-state-then-disconnect ordering."""
        return None

    async def async_shutdown(self):
        """Disable the TEC control loop (safe state), then close the session."""
        LOGGER.info("shutting down TEC controller")
        self.disable()
        self.disconnect()

    def get_data(self) -> dict:
        """Query each parameter in ``self.queries`` and return their values.

        Returns:
            ``{description: (value, unit)}`` for each successfully queried
            parameter.
        """
        data = {}
        for description in self.queries:
            cid, unit = COMMAND_TABLE[description]
            try:
                value = self.session().get_parameter(
                    parameter_id=cid,
                    address=self.address,
                    parameter_instance=self.channel,
                )
                data.update({description: (value, unit)})
            except (ResponseException, WrongChecksum) as ex:
                self.session().stop()
                self._session = None
        return data

    def set_temp(self, value):
        """Set the object temperature setpoint for this channel.

        Args:
            value: Target temperature in degrees Celsius. Must be ``float``.

        Returns:
            The result of the underlying ``set_parameter`` call.

        Raises:
            AssertionError: If ``value`` is not a ``float``.
        """
        # assertion to explicitly enter floats
        assert type(value) is float
        LOGGER.info(
            "set object temperature for channel {} to {} C".format(self.channel, value)
        )
        return self.session().set_parameter(
            parameter_id=3000,
            value=value,
            address=self.address,
            parameter_instance=self.channel,
        )

    def _set_enable(self, enable=True):
        """Enable or disable the TEC control loop for this channel.

        Args:
            enable: ``True`` to turn the loop on, ``False`` to turn it off.

        Returns:
            The result of the underlying ``set_parameter`` call.
        """
        value, description = (1, "on") if enable else (0, "off")
        LOGGER.info("set loop for channel {} to {}".format(self.channel, description))
        return self.session().set_parameter(
            value=value,
            parameter_name="Status",
            address=self.address,
            parameter_instance=self.channel,
        )

    def enable(self):
        """Enable the TEC control loop."""
        return self._set_enable(True)

    def disable(self):
        """Disable the TEC control loop."""
        return self._set_enable(False)


class MeerstetterTECPoller(DriverPoller):
    """Background poller that reads TEC telemetry (``tec_vals``) from the driver.

    Legacy ``poll_sensor_loop`` hardcoded ``frequency=1`` (i.e. 1 Hz / 1.0s
    sleep). ``BaseAPI`` constructs this poller with
    ``server_cfg.get("polling_time", 0.1)`` (10 Hz absent an explicit
    ``polling_time`` config key) -- construction-proof scope defers tuning
    that cadence back to 1.0s.
    """

    driver: MeerstetterTEC

    def get_data(self) -> DriverResponse:
        """Read one sample of every configured query parameter.

        Returns:
            ``DriverResponse`` with ``data={"tec_vals": {description: value,
            ...}}`` (unit dropped, matching the pre-migration
            ``poll_sensor_loop``'s ``v[0]`` scaling) when at least one
            parameter was read, or an empty ``DriverResponse`` otherwise.
        """
        tec_vals = {k: v[0] for k, v in self.driver.get_data().items()}
        if not tec_vals:
            return DriverResponse()
        return DriverResponse(
            response=DriverResponseType.success,
            status=DriverStatus.ok,
            data={"tec_vals": tec_vals},
        )


class TECMonExec(Executor):
    """HELAO :class:`Executor` that monitors TEC values for a fixed duration.

    Polls the live buffer for ``tec_vals`` and yields ``HloStatus.active``
    until ``duration`` seconds have elapsed (or indefinitely when
    ``duration < 0``).
    """

    def __init__(self, *args, **kwargs):
        """Capture the start time and configured monitor duration."""
        super().__init__(*args, **kwargs)
        LOGGER.info("TECMonExec initialized.")
        self.start_time = time.time()
        self.duration = self.active.action.action_params.get("duration", -1)

    async def _poll(self):
        """Read TEC values from the live buffer and signal duration completion.

        Returns:
            Standard executor dict with ``error``, ``status`` and ``data``.
        """
        live_dict = {}
        tec_vals, epoch_s = self.active.base.get_lbuf("tec_vals")
        live_dict["epoch_s"] = epoch_s
        for k, v in tec_vals.items():
            live_dict[k] = v
        iter_time = time.time()
        elapsed_time = iter_time - self.start_time
        if (self.duration < 0) or (elapsed_time < self.duration):
            status = HloStatus.active
        else:
            status = HloStatus.finished
        await asyncio.sleep(0.01)

        return {
            "error": ErrorCodes.none,
            "status": status,
            "data": live_dict,
        }


STABLE_ID_MAP = {
    0: "Temperature regulation not active.",
    1: "Temperature is not stable.",
    2: "Temperature is stable.",
}


class TECWaitExec(Executor):
    """HELAO :class:`Executor` that waits until the TEC reports stable.

    Polls ``tec_vals['temperature_is_stable']`` and finishes once it equals
    ``2`` (the "temperature is stable" code).
    """

    def __init__(self, *args, **kwargs):
        """Capture timing state and configure the initial pre-exec sleep."""
        super().__init__(*args, **kwargs)
        LOGGER.info("TECWaitExec initialized.")
        self.start_time = time.time()
        self.duration = -1
        self.last_check = 0
        self.initial_sleep = 2

    async def _pre_exec(self):
        """Sleep for ``self.initial_sleep`` to let the live buffer settle."""
        LOGGER.info(f"TECWait Executor sleeping for {self.initial_sleep} seconds.")
        await asyncio.sleep(self.initial_sleep)
        return {"error": ErrorCodes.none}

    async def _poll(self):
        """Read TEC values and finish once stability code reaches ``2``.

        Returns:
            Standard executor dict with ``error``, ``status`` and ``data``.
        """
        live_dict = {}
        tec_vals, epoch_s = self.active.base.get_lbuf("tec_vals")
        live_dict["epoch_s"] = epoch_s
        for k, v in tec_vals.items():
            live_dict[k] = v
        stable_id = live_dict["temperature_is_stable"]
        if stable_id != 2:
            status = HloStatus.active
            if epoch_s - self.last_check > 5:
                stab_msg = STABLE_ID_MAP.get(stable_id, "temperature state is unknown")
                LOGGER.info(stab_msg)
                self.last_check = epoch_s
        else:
            status = HloStatus.finished
        await asyncio.sleep(0.01)

        return {
            "error": ErrorCodes.none,
            "status": status,
            "data": live_dict,
        }
