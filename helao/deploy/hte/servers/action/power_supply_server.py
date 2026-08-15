"""FastAPI action server for a generic programmable power supply.

Defines three executors that share a :class:`PowerSupplyDriver`:

* :class:`ApplyVoltageExecutor` writes a constant voltage and polls current.
* :class:`SquareWaveExecutor` produces a single voltage square pulse and
  polls current.
* :class:`ConstantCurrentSquareWaveExecutor` produces a constant-current
  square pulse using ``sleep_time``/``sleep_time1``/``sleep_time2`` to
  define the OFF / ON / OFF phase boundaries.

The ``power_supply_dyn_endpoints`` hook registers ``apply_voltage``,
``square_wave``, and ``constant_current_square_wave`` action endpoints.
"""

__all__ = ["makeApp"]


import time

from helao.core.error import ErrorCodes
from helao.core.models.file import HloHeaderModel
from helao.core.models.hlostatus import HloStatus
from helao.hexagon.app.action_context import ActionContext
from helao.hexagon.app.action_host import ActionHost
from helao.helpers import helao_logging as logging  # get LOGGER from the host instance
from helao.helpers.executor import Executor

from ...drivers.power_supply.power_supply_driver import (
    DriverResponseType,
    PowerSupplyDriver,
)

global LOGGER
LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

from enum import Enum


class ConstantCurrentSquareWaveExecutor(Executor):
    """Executor that emits a constant-current square pulse with timed phases.

    The executor tracks four states through a local ``PollFlag`` enum and
    uses ``sleep_time``, ``sleep_time1``, and ``sleep_time2`` action params
    as the elapsed-time boundaries between the OFF, ON, and final OFF
    phases. Voltage is sampled at every poll and reported with the elapsed
    time.

    Attributes:
        driver: The bound :class:`PowerSupplyDriver` instance.
        poll_rate: Polling period in seconds.
        start_time: Wall-clock start time of the active phase.
        poll_flag: Current phase, one of the inner ``PollFlag`` values.
        duration: Sentinel value (``-1``) indicating no external timer.
    """

    driver: PowerSupplyDriver

    def __init__(self, *args, **kwargs):
        """Initialise executor state, phase flag enum, and driver shortcut.

        Args:
            *args: Forwarded to :class:`Executor`.
            **kwargs: Forwarded to :class:`Executor`.
        """
        super().__init__(*args, **kwargs)
        try:
            self.poll_rate = 0.2  # pump events every 100 millisecond
            self.start_time = time.time()

            class PollFlag(Enum):
                PRE = "pre"
                OFF_0 = "off_0"
                ON = "on"
                OFF_1 = "off1"

            self.PollFlag = PollFlag
            self.poll_flag = PollFlag.PRE
            # link attrs for convenience
            self.action_params = self.active.action.action_params
            self.driver = self.active.driver

            # no external timer, event sink signals end of measurement
            self.duration = -1
        except Exception:
            LOGGER.error(f"Failed to initialize apply_voltage executor:", exc_info=True)
        # init should never return for any python class!

    async def _pre_exec(self) -> dict:
        """Open the power-supply connection and enable the output.

        Returns:
            Dict with ``error`` set to :attr:`ErrorCodes.none` on success or
            :attr:`ErrorCodes.critical_error` if any driver call fails.
        """
        resp = self.driver.connect()

        if resp.response != DriverResponseType.success:
            LOGGER.error(
                f"ConstantCurrentSquareWaveExecutor connect failed:", exc_info=True
            )
            return {"error": ErrorCodes.critical_error}
        resp = self.driver.set_output(True)
        if resp.response != DriverResponseType.success:
            LOGGER.error(
                f"ConstantCurrentSquareWaveExecutor set_output(True) failed:",
                exc_info=True,
            )
            return {"error": ErrorCodes.critical_error}
        else:
            LOGGER.info(f"power supply is connected")
        return {"error": ErrorCodes.none}

    async def _exec(self) -> dict:
        """Reset the supply to zero current and enter the first OFF phase.

        Marks ``start_time`` and transitions the phase flag to ``OFF_0``.

        Returns:
            Dict with ``error`` set to :attr:`ErrorCodes.none`.
        """
        self.start_time = time.time()

        resp = await self.driver.apply_current_async(current=0, sleep_time=0.1)
        resp = self.driver.set_output(output_on=False)
        if resp.response != DriverResponseType.success:
            LOGGER.warning("failed to set current to 0")

        self.poll_flag = self.PollFlag.OFF_0
        return {
            "error": ErrorCodes.none,
        }

    async def _poll(self) -> dict:
        """Advance the phase state machine and emit a voltage sample.

        On each poll the elapsed time is compared against ``sleep_time``
        (OFF_0 -> ON), ``sleep_time1`` (ON -> OFF_1), and ``sleep_time2``
        (final stop). Voltage is read asynchronously and appended with the
        elapsed time before returning.

        Returns:
            Dict containing the sampled ``data`` and an :class:`HloStatus`
            of ``active`` until ``sleep_time2`` is exceeded, ``finished``
            thereafter.
        """
        current_a = self.action_params["current"]
        # to do  - speed up the polling and add an exit condition. make errored reads ok
        sleep_time = self.action_params["sleep_time"]
        sleep_time1 = self.action_params["sleep_time1"]
        sleep_time2 = self.action_params["sleep_time2"]

        time_now = time.time() - self.start_time

        if time_now > sleep_time2:

            resp = await self.driver.apply_current_async(current=0, sleep_time=0.1)
            resp = self.driver.set_output(output_on=False)
            LOGGER.warning("poll completed")
            return {"status": HloStatus.finished}

        elif time_now > sleep_time1:
            if self.poll_flag == self.PollFlag.ON:
                LOGGER.warning("changing poll flag from ON to OFF_1")
                resp = await self.driver.apply_current_async(current=0, sleep_time=0.1)
                time.sleep(0.1)
                resp = self.driver.set_output(output_on=False)
                if resp.response != DriverResponseType.success:
                    LOGGER.warning("failed to set current to 0")

                self.poll_flag = self.PollFlag.OFF_1
                time.sleep(0.1)
                if resp.response != DriverResponseType.success:
                    LOGGER.error(f"set output failed in poll:", exc_info=True)
                LOGGER.info(
                    f"poll, at time {time_now}, which is after the second time of {sleep_time1}"
                )

        elif time_now > sleep_time:
            if self.poll_flag == self.PollFlag.OFF_0:
                resp = self.driver.set_output(output_on=True)
                LOGGER.warning(f"output set for ON time, response is {resp.response}")
                time.sleep(0.1)
                if resp.response != DriverResponseType.success:
                    LOGGER.error(f"set output failed in poll:", exc_info=True)
                resp = await self.driver.apply_current_async(
                    current=current_a, sleep_time=0.1
                )
                LOGGER.warning(f"Current for ON applied, response is {resp.response}")

                self.poll_flag = self.PollFlag.ON
            LOGGER.info(f"poll, at time {time_now}, which is after {sleep_time}")

        else:

            LOGGER.info(f"poll, at time {time_now}, which is before {sleep_time}")

        resp = await self.driver.get_voltage_async(sleep_time=0.05)
        LOGGER.info(f"polled voltage is {resp.data['voltage_v']}")
        resp.data["t_s"] = time_now
        return {"data": resp.data, "status": HloStatus.active}

    async def _post_exec(self) -> dict:
        """Disconnect from the supply on completion.

        Returns:
            Dict with ``error`` set to :attr:`ErrorCodes.none` on success or
            :attr:`ErrorCodes.critical_error` on disconnect failure.
        """
        resp = self.driver.disconnect()
        if resp.response != DriverResponseType.success:
            return {"error": ErrorCodes.critical_error}
        return {"error": ErrorCodes.none}


class ApplyVoltageExecutor(Executor):
    """Executor that applies a constant voltage and polls current.

    Attributes:
        driver: The bound :class:`PowerSupplyDriver` instance.
        poll_rate: Polling period in seconds.
        start_time: Wall-clock start time of the active phase.
        duration: Sentinel value (``-1``) indicating no external timer.
    """

    driver: PowerSupplyDriver

    def __init__(self, *args, **kwargs):
        """Initialise executor state and cache action params and driver.

        Args:
            *args: Forwarded to :class:`Executor`.
            **kwargs: Forwarded to :class:`Executor`.
        """
        super().__init__(*args, **kwargs)
        try:
            self.poll_rate = 5  # pump events every 100 millisecond
            self.start_time = time.time()

            # link attrs for convenience
            self.action_params = self.active.action.action_params
            self.driver = self.active.driver

            # no external timer, event sink signals end of measurement
            self.duration = -1
        except Exception:
            LOGGER.error(f"Failed to initialize apply_voltage executor:", exc_info=True)
        # init should never return for any python class!

    async def _pre_exec(self) -> dict:
        """Open the power-supply connection and enable the output.

        Returns:
            Dict with ``error`` set to :attr:`ErrorCodes.none` on success or
            :attr:`ErrorCodes.critical_error` on any driver failure.
        """
        resp = self.driver.connect()
        if resp.response != DriverResponseType.success:
            return {"error": ErrorCodes.critical_error}
        resp = self.driver.set_output(True)
        if resp.response != DriverResponseType.success:
            return {"error": ErrorCodes.critical_error}
        return {"error": ErrorCodes.none}

    async def _exec(self) -> dict:
        """Apply the configured voltage and re-enable the output.

        Returns:
            Dict with ``error`` set to :attr:`ErrorCodes.none` on success or
            :attr:`ErrorCodes.critical_error` on failure.
        """
        voltage = self.action_params["voltage"]
        sleep_time = self.action_params["sleep_time"]
        resp = await self.driver.apply_voltage_async(
            voltage=voltage, sleep_time=sleep_time
        )
        resp = self.driver.set_output(output_on=True)
        if resp.response != DriverResponseType.success:
            return {"error": ErrorCodes.critical_error}
        return {"error": ErrorCodes.none}

    async def _poll(self) -> dict:
        """Sample the supply current.

        Returns:
            Dict with the sampled ``data``, an :class:`HloStatus.active` on
            a successful read, or :attr:`ErrorCodes.critical_error` and
            :class:`HloStatus.errored` on a failed read.
        """
        resp = await self.driver.get_current_async(sleep_time=self.poll_rate)
        LOGGER.info(f"_poll response is {resp}")
        status = HloStatus.active
        if resp.response != DriverResponseType.success:
            status = HloStatus.errored
            return {"error": ErrorCodes.critical_error, "status": status}
        return {"error": ErrorCodes.none, "data": resp.data, "status": status}

    async def _post_exec(self) -> dict:
        """Disconnect from the supply on completion.

        Returns:
            Dict with ``error`` set to :attr:`ErrorCodes.none` on success or
            :attr:`ErrorCodes.critical_error` on disconnect failure.
        """
        resp = self.driver.disconnect()
        if resp.response != DriverResponseType.success:
            return {"error": ErrorCodes.critical_error}
        return {"error": ErrorCodes.none}


class SquareWaveExecutor(Executor):
    """Executor that emits a single voltage square pulse.

    Pulses the output off then on around an ``apply_voltage_async`` call
    spaced by ``sleep_time``, and polls current between cycles.

    Attributes:
        driver: The bound :class:`PowerSupplyDriver` instance.
        poll_rate: Polling period in seconds.
        start_time: Wall-clock start time of the active phase.
        duration: Sentinel value (``-1``) indicating no external timer.
    """

    driver: PowerSupplyDriver

    def __init__(self, *args, **kwargs):
        """Initialise executor state and cache action params and driver.

        Args:
            *args: Forwarded to :class:`Executor`.
            **kwargs: Forwarded to :class:`Executor`.
        """
        super().__init__(*args, **kwargs)
        try:
            self.poll_rate = 5  # pump events every 100 millisecond
            self.start_time = time.time()

            # link attrs for convenience
            self.action_params = self.active.action.action_params
            self.driver = self.active.driver

            # no external timer, event sink signals end of measurement
            self.duration = -1
        except Exception:
            LOGGER.error(f"Failed to initialize apply_voltage executor:", exc_info=True)
        # init should never return for any python class!

    async def _pre_exec(self) -> dict:
        """Open the power-supply connection and enable the output.

        Returns:
            Dict with ``error`` set to :attr:`ErrorCodes.none` on success or
            :attr:`ErrorCodes.critical_error` on any driver failure.
        """
        resp = self.driver.connect()
        if resp.response != DriverResponseType.success:
            return {"error": ErrorCodes.critical_error}
        resp = self.driver.set_output(True)
        if resp.response != DriverResponseType.success:
            return {"error": ErrorCodes.critical_error}
        return {"error": ErrorCodes.none}

    async def _exec(self) -> dict:
        """Emit the off-on-off voltage square pulse.

        Sequence: disable output, sleep, re-enable, apply voltage, sleep,
        disable. Any driver-call failure is logged and returns
        :attr:`ErrorCodes.critical_error`.

        Returns:
            Dict with ``error`` set to :attr:`ErrorCodes.none` on success or
            :attr:`ErrorCodes.critical_error` on failure.
        """
        voltage = self.action_params["voltage"]
        sleep_time = self.action_params["sleep_time"]
        try:
            resp = self.driver.set_output(output_on=False)
            time.sleep(sleep_time)
            if resp.response != DriverResponseType.success:
                LOGGER.error(
                    f"SquareWaveExecutor set_output(output_on=False) failed:",
                    exc_info=True,
                )
                return {"error": ErrorCodes.critical_error}
            resp = self.driver.set_output(output_on=True)
            if resp.response != DriverResponseType.success:
                LOGGER.error(
                    f"SquareWaveExecutor set_output(output_on=True) failed:",
                    exc_info=True,
                )
                return {"error": ErrorCodes.critical_error}
            resp = await self.driver.apply_voltage_async(
                voltage=voltage, sleep_time=sleep_time
            )
            if resp.response != DriverResponseType.success:
                LOGGER.error(
                    f"SquareWaveExecutor apply_voltage_async failed:", exc_info=True
                )
                return {"error": ErrorCodes.critical_error}
            resp = self.driver.set_output(output_on=False)
            time.sleep(sleep_time)
            if resp.response != DriverResponseType.success:
                LOGGER.error(
                    f"SquareWaveExecutor set_output(output_on=False) failed:",
                    exc_info=True,
                )
                return {"error": ErrorCodes.critical_error}

            return {"error": ErrorCodes.none}
        except Exception:
            LOGGER.error(f"SquareWaveExecutor failed:", exc_info=True)
            return {"error": ErrorCodes.critical_error}

    async def _poll(self) -> dict:
        """Sample the supply current.

        Returns:
            Dict with the sampled ``data`` on success, or
            :attr:`ErrorCodes.critical_error` on failure.
        """
        try:
            resp = await self.driver.get_current_async(sleep_time=0.1)
            LOGGER.info(f"SquareWaveExecutor poll response: {resp}")
            if resp.response != DriverResponseType.success:
                LOGGER.error(
                    f"SquareWaveExecutor poll response not success:", exc_info=True
                )
                return {"error": ErrorCodes.critical_error}

            return {"error": ErrorCodes.none, "data": resp.data}
        except Exception:
            LOGGER.error(f"SquareWaveExecutor poll failed:", exc_info=True)
            return {"error": ErrorCodes.critical_error}

    async def _post_exec(self) -> dict:
        """Disconnect from the supply on completion.

        Returns:
            Dict with ``error`` set to :attr:`ErrorCodes.none` on success or
            :attr:`ErrorCodes.critical_error` on disconnect failure.
        """
        resp = self.driver.disconnect()
        if resp.response != DriverResponseType.success:
            return {"error": ErrorCodes.critical_error}
        return {"error": ErrorCodes.none}


async def power_supply_dyn_endpoints(app: ActionHost):
    """Register the power-supply action endpoints.

    Disables concurrent actions on this server and attaches ``apply_voltage``,
    ``square_wave``, and ``constant_current_square_wave`` endpoints.

    Args:
        app: The :class:`ActionHost` instance being configured.
    """
    server_key = app.server.server_name
    app.server_params["allow_concurrent_actions"] = False

    @app.action()
    async def apply_voltage(
        ctx: ActionContext,
        voltage: float = 1.0,
        sleep_time: float = 0.05,
    ):
        """Start an :class:`ApplyVoltageExecutor` to drive a constant voltage.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            voltage: Voltage setpoint in volts.
            sleep_time: Delay forwarded to the driver between operations.

        Returns:
            The active action dictionary from ``start_executor``.
        """

        # Prepare json_data_keys for logging/serialization (for example: ["elapsed_time_s", "voltage_v", "current_a"])
        data_keys = ["elapsed_time_s", "voltage_v", "current_a"]  # Adjust as needed

        active = await ctx.begin(
            json_data_keys=data_keys,
            file_type="power_supply_helao__file",
            hloheader=HloHeaderModel(
                column_headings=data_keys,
                optional={},
            ),
        )

        # Abbreviate action for clarity
        active.action.action_abbr = "APPLYVOLT"
        # Save parameters to action_params
        active.action.action_params["voltage"] = voltage
        active.action.action_params["sleep_time"] = sleep_time

        # Start executor
        executor = ApplyVoltageExecutor(active=active, oneoff=False)
        active_action_dict = active.start_executor(executor)

        return active_action_dict

    @app.action()
    async def square_wave(
        ctx: ActionContext,
        voltage: float = 1.0,
        sleep_time: float = 0.05,
    ):
        """Start a :class:`SquareWaveExecutor` to emit a voltage square pulse.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            voltage: Pulse amplitude in volts.
            sleep_time: Phase duration between output toggles in seconds.

        Returns:
            The active action dictionary from ``start_executor``.
        """

        # Prepare json_data_keys for logging/serialization (for example: ["elapsed_time_s", "voltage_v", "current_a"])
        data_keys = ["elapsed_time_s", "voltage_v", "current_a"]  # Adjust as needed

        active = await ctx.begin(
            json_data_keys=data_keys,
            file_type="power_supply_helao__file",
            hloheader=HloHeaderModel(
                column_headings=data_keys,
                optional={},
            ),
        )

        # Abbreviate action for clarity
        active.action.action_abbr = "SQUAREWAVE"
        # Save parameters to action_params
        active.action.action_params["voltage"] = voltage
        active.action.action_params["sleep_time"] = sleep_time

        # Start executor
        executor = SquareWaveExecutor(active=active, oneoff=False)
        active_action_dict = active.start_executor(executor)

        return active_action_dict

    @app.action()
    async def constant_current_square_wave(
        ctx: ActionContext,
        current: float = 0.01,
        sleep_time: float = 0.05,
        sleep_time1: float = 1,
        sleep_time2: float = 1,
    ):
        """Start a :class:`ConstantCurrentSquareWaveExecutor` to emit a current pulse.

        ``sleep_time``, ``sleep_time1``, and ``sleep_time2`` are elapsed-time
        thresholds that define the OFF/ON/OFF phase transitions inside the
        executor's poll loop.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            current: Constant current setpoint in amperes during the ON phase.
            sleep_time: Elapsed time at which OFF_0 transitions to ON.
            sleep_time1: Elapsed time at which ON transitions to OFF_1.
            sleep_time2: Elapsed time at which polling finishes.

        Returns:
            The active action dictionary from ``start_executor``.
        """

        # Prepare json_data_keys for logging/serialization (for example: ["elapsed_time_s", "voltage_v", "current_a"])
        data_keys = ["elapsed_time_s", "voltage_v", "current_a"]  # Adjust as needed

        active = await ctx.begin(
            json_data_keys=data_keys,
            file_type="power_supply_helao__file",
            hloheader=HloHeaderModel(
                column_headings=data_keys,
                optional={},
            ),
        )

        # Abbreviate action for clarity
        active.action.action_abbr = "SQUAREWAVE"
        # Save parameters to action_params
        active.action.action_params["current"] = current
        active.action.action_params["sleep_time"] = sleep_time
        active.action.action_params["sleep_time1"] = sleep_time1
        active.action.action_params["sleep_time2"] = sleep_time2

        # Start executor
        executor = ConstantCurrentSquareWaveExecutor(active=active, oneoff=False)
        active_action_dict = active.start_executor(executor)

        return active_action_dict


def makeApp(server_key) -> ActionHost:
    """Build the ActionHost app for a generic programmable power supply.

    Args:
        server_key: Unique key identifying this server in the orchestration
            group.

    Returns:
        The configured ActionHost instance with power-supply action endpoints
        attached via :func:`power_supply_dyn_endpoints` and a private
        ``stop_private`` endpoint that disconnects the driver.
    """

    app = ActionHost(
        server_key=server_key,
        server_title=server_key,
        description="Power supply action server",
        version=0.1,
        driver_classes=[PowerSupplyDriver],
        dyn_endpoints=power_supply_dyn_endpoints,
    )

    @app.post("/stop_private", tags=["private"])
    def stop_private():
        """Disconnect from the power supply via the driver."""
        app.driver.disconnect()

    return app
