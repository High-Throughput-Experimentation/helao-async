"""Generic VISA-controlled power supply driver.

Wraps a `pyvisa` serial resource that speaks the common `VSET1:`/`ISET1:`/
`VOUT1?`/`IOUT1?`/`OUT1`/`OUT0` command set used by bench supplies (e.g.
Korad/RND). Implements the HELAO `HelaoDriver` interface (`connect`,
`get_status`, `stop`, `reset`, `disconnect`) plus synchronous and async
helpers for setting/reading voltage and current.
"""

import asyncio

import pyvisa as pv
from pyvisa.resources.serial import SerialInstrument

# print(dir(pv.ResourceManager))
# print(dir(pv.resources.serial.SerialInstrument))
# save a default log file system temp
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
import numpy as np

from helao.core.drivers.helao_driver import (
    DriverResponse,
    DriverResponseType,
    DriverStatus,
    HelaoDriver,
)


class PowerSupplyDriver(HelaoDriver):
    """HelaoDriver wrapping a VISA serial-controlled bench power supply.

    Reads `resource_name` and `timeout_ms` from `config`. Holds a single
    `pyvisa` `SerialInstrument` and provides both synchronous and async
    voltage/current set/get helpers. Async methods sleep `sleep_time` after
    issuing the command to give the supply time to settle.
    """

    def __init__(self, config: dict = {}):
        """Capture the VISA resource name and timeout from `config`.

        Args:
            config: Driver configuration; must include `resource_name`.
                `timeout_ms` defaults to 10000.
        """
        super().__init__(config=config)
        self.resource_name = self.config.get("resource_name")
        self.timeout_ms = int(self.config.get("timeout_ms", 10000))
        self.instrument: SerialInstrument | None = None  # write and query methods
        self.rm: pv.ResourceManager | None = (
            None  # this gives access to the list resources method
        )
        self.ready = False

    def connect(self) -> DriverResponse:
        """Open the VISA resource, query `*IDN?`, and mark the driver ready."""
        try:
            self.rm = pv.ResourceManager()
            self.instrument = self.rm.open_resource(self.resource_name)
            self.instrument.timeout = self.timeout_ms
            idn = self.instrument.query("*IDN?").strip()
            LOGGER.info(f"connected to {idn} on {self.resource_name}")
            self.ready = True
            return DriverResponse(
                response=DriverResponseType.success,
                status=DriverStatus.ok,
                data={"idn": idn, "resource": self.resource_name},
            )
        except Exception as e:
            self.ready = False
            return DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.error,
                message=f"connect failed: {e}",
            )

    def setup(self, voltage_v: float = 0.0, output_on: bool = True) -> DriverResponse:
        """Zero `VSET1` and enable or disable the output.

        Note: `voltage_v` is currently logged but not used in the `VSET1:`
        command (which writes the literal `0`).
        """
        if self.instrument is None:
            return DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.uninitialized,
                message="not connected",
            )
        try:
            self.instrument.write(f"VSET1:0")
            self.instrument.write("OUT1" if output_on else "OUT0")
            LOGGER.info(
                f"Power supply voltage set to {voltage_v} V (output_on={output_on})"
            )
            return DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception as e:
            return DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.error,
                message=f"setup failed: {e}",
            )

    def get_status(self) -> DriverResponse:
        """Issue `STATUS?` and return the write-call result as `data["status"]`."""
        if self.instrument is None:
            return DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.uninitialized,
                message="not connected",
            )
        try:
            status = self.instrument.write("STATUS?")
            return DriverResponse(
                response=DriverResponseType.success,
                status=DriverStatus.ok,
                data={"status": status},
            )
        except Exception as e:
            return DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.error,
                message=f"get_status failed: {e}",
            )

    def set_output(self, output_on: bool = True) -> DriverResponse:
        """Send `OUT1` or `OUT0` to enable or disable the supply output."""
        if self.instrument is None:
            return DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.uninitialized,
                message="not connected",
            )
        try:
            self.instrument.write("OUT1" if output_on else "OUT0")
            return DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            LOGGER.error("set_output_on failed:", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.error,
                message=f"set_output_on failed:",
            )

    def set_voltage(self, voltage_v: float = 0.0) -> DriverResponse:
        """Send `VSET1:<voltage_v>` to update the voltage setpoint."""
        if self.instrument is None:
            return DriverResponse(
                response=DriverResponseType.success,
                status=DriverStatus.uninitialized,
                data={},
            )
        try:
            self.instrument.write(f"VSET1:{voltage_v}")
            return DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            LOGGER.error("set_voltage failed:", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.error,
                message=f"set_voltage failed:",
            )

    def set_current(self, current_a: float = 0.0) -> DriverResponse:
        """Send `ISET1:<current_a>` to update the current limit."""
        if self.instrument is None:
            return DriverResponse(
                response=DriverResponseType.success,
                status=DriverStatus.uninitialized,
                data={},
            )
        try:
            self.instrument.write(f"ISET1:{current_a}")
            return DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            LOGGER.error("set_current failed:", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.error,
                message=f"set_current failed:",
            )

    def get_voltage(self) -> DriverResponse:
        """Query `VOUT1?` and return the parsed float in `data["voltage_v"]`."""
        if self.instrument is None:
            return DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.uninitialized,
                message="not connected",
            )
        try:
            voltage_v = float(self.instrument.query("VOUT1?"))
            return DriverResponse(
                response=DriverResponseType.success,
                status=DriverStatus.ok,
                data={"voltage_v": voltage_v},
            )
        except Exception:
            LOGGER.error("get_voltage failed:", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.success,
                status=DriverStatus.ok,
                message=f"get_voltage failed:",
            )

    async def get_voltage_async(self, sleep_time: float = 0.05) -> "DriverResponse":
        """Asynchronously read `VOUT1?` after sleeping `sleep_time` seconds.

        Args:
            sleep_time: Delay applied before the query to throttle requests.

        Returns:
            `DriverResponse` whose `data["voltage_v"]` is the parsed float
            (or NaN if the query raised).
        """
        if self.instrument is None:
            return DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.uninitialized,
                message="not connected",
            )
        try:
            await asyncio.sleep(sleep_time)
            voltage_v = float(self.instrument.query("VOUT1?"))

            return DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.ok,
                data={"voltage_v": voltage_v},
            )
        except Exception:

            # self.reset()
            # for i in range (3):
            #     LOGGER.error('In the duplicate try loop')
            #     try:
            #         voltage_v = float(self.instrument.query("VOUT1?"))
            #         await asyncio.sleep(sleep_time)
            #         return DriverResponse(response=DriverResponseType.success, status=DriverStatus.ok, data={"voltage_v": voltage_v})

            #     except:
            #         LOGGER.error('iterating call for voltage failed :( )')

            LOGGER.error("get_voltage_async failed:", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.success,
                status=DriverStatus.ok,
                data={"voltage_v": np.nan},
                message=f"get_voltage_async failed:",
            )

    async def get_current_async(self, sleep_time: float = 0.05) -> "DriverResponse":
        """Asynchronously read `IOUT1?` and return the parsed current in amps.

        Args:
            sleep_time: Delay applied after a successful query to throttle requests.

        Returns:
            `DriverResponse` whose `data["current_a"]` is the parsed float,
            NaN if the response was non-numeric, or the response is success
            with no `data` if the query itself raised.
        """
        if self.instrument is None:
            return DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.uninitialized,
                message="not connected",
            )
        try:
            # await asyncio.sleep(1)
            current_a = self.instrument.query("IOUT1?")
            LOGGER.info(f"Read current is: {current_a}")
            try:
                current_a = float(current_a)
            except ValueError:
                LOGGER.warning(
                    f"The power supply returned a non float current. It's value is {current_a}. Returning np.nan to the caller."
                )
                return DriverResponse(
                    response=DriverResponseType.success,
                    status=DriverStatus.ok,
                    data={"current_a": np.nan},
                )
            await asyncio.sleep(sleep_time)
            return DriverResponse(
                response=DriverResponseType.success,
                status=DriverStatus.ok,
                data={"current_a": current_a},
            )
        except Exception:
            LOGGER.warning("get_current_async failed:", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.success,
                status=DriverStatus.ok,
                message=f"The call the the power supply failed at get_current_async",
            )

    async def apply_voltage_async(
        self, voltage: float, sleep_time: float = 0.05
    ) -> "DriverResponse":
        """Asynchronously write `VSET1:<voltage>` and sleep `sleep_time` seconds.

        Args:
            voltage: Voltage setpoint to apply.
            sleep_time: Delay applied after the write to give the supply time to settle.

        Returns:
            `DriverResponse` carrying the applied setpoint in `data["set_voltage"]`.
        """
        if self.instrument is None:
            return DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.uninitialized,
                message="not connected",
            )
        try:
            self.instrument.write(f"VSET1:{voltage}")
            await asyncio.sleep(sleep_time)

            return DriverResponse(
                response=DriverResponseType.success,
                status=DriverStatus.ok,
                data={"set_voltage": voltage},
                message="Voltage applied successfully.",
            )
        except Exception:
            # for _ in range (3):
            #     try:
            #         voltage_v = float(self.instrument.query("VSET1?"))
            #         await asyncio.sleep(sleep_time)
            #         break
            #     except:
            #         LOGGER.critical('all calls for voltage failed :( )')

            return DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.error,
                message=f"apply_voltage failed",
            )

    async def apply_current_async(
        self, current: float, sleep_time: float = 0.05
    ) -> "DriverResponse":
        """Asynchronously write `ISET1:<current>` and sleep `sleep_time` seconds.

        Args:
            current: Current limit to apply.
            sleep_time: Delay applied after the write to give the supply time to settle.

        Returns:
            `DriverResponse` carrying the applied setpoint in `data["set_current"]`.
        """
        if self.instrument is None:
            return DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.uninitialized,
                message="not connected",
            )
        try:
            self.instrument.write(f"ISET1:{current}")
            await asyncio.sleep(sleep_time)
            return DriverResponse(
                response=DriverResponseType.success,
                status=DriverStatus.ok,
                data={"set_current": current},
                message="Current applied successfully.",
            )
        except Exception:
            LOGGER.error("apply_current_async failed:", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.error,
                message=f"apply_Current failed",
            )

    def stop(self) -> DriverResponse:
        """Stub stop method satisfying the `HelaoDriver` interface; performs no action."""
        if self.instrument is None:
            return DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.uninitialized,
                message="not connected",
            )
        try:
            return DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            LOGGER.error("stop failed:", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.error,
                message=f"stop failed:",
            )

    def disconnect(self) -> DriverResponse:
        """Close the VISA instrument and resource manager, clearing `self.instrument`."""
        try:
            if self.instrument is not None:
                self.instrument.close()
            if self.rm is not None:
                self.rm.close()
            self.instrument = None
            self.rm = None
            self.ready = False
            return DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.uninitialized
            )
        except Exception:
            LOGGER.error("disconnect failed:", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.error,
                message=f"disconnect failed:",
            )

    def reset(self) -> DriverResponse:
        """Disconnect and immediately reconnect to the VISA resource."""
        self.disconnect()
        return self.connect()
