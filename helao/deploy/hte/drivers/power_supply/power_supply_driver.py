
import time
from typing import Optional
import pyvisa as pv
from pyvisa.resources.serial import SerialInstrument
import time
import asyncio

# print(dir(pv.ResourceManager))
# print(dir(pv.resources.serial.SerialInstrument))


# save a default log file system temp
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
import numpy as np
import pandas as pd

from helao.core.drivers.helao_driver import (
    HelaoDriver,
    DriverResponse,
    DriverStatus,
    DriverResponseType,
)


class PowerSupplyDriver(HelaoDriver):
    def __init__(self, config: dict = {}):
        super().__init__(config=config)
        self.resource_name = self.config.get("resource_name")
        self.timeout_ms = int(self.config.get("timeout_ms", 10000))
        self.instrument: SerialInstrument | None = None # write and query methods
        self.rm: pv.ResourceManager | None = None # this gives access to the list resources method
        self.ready = False

    def connect(self) -> DriverResponse:
        try:
            self.rm = pv.ResourceManager()
            self.instrument = self.rm.open_resource(self.resource_name)
            self.instrument.timeout = self.timeout_ms
            idn = self.instrument.query("*IDN?").strip()
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
        if self.instrument is None:
            return DriverResponse(response=DriverResponseType.failed, status=DriverStatus.uninitialized, message="not connected")
        try:
            self.instrument.write(f"VSET1:0")
            self.instrument.write("OUT1" if output_on else "OUT0")
            LOGGER.info(f"Power supply voltage set to {voltage_v} V (output_on={output_on})")
            return DriverResponse(response=DriverResponseType.success, status=DriverStatus.ok)
        except Exception as e:
            return DriverResponse(response=DriverResponseType.failed, status=DriverStatus.error, message=f"setup failed: {e}")

    def get_status(self) -> DriverResponse:
        if self.instrument is None:
            return DriverResponse(response=DriverResponseType.failed, status=DriverStatus.uninitialized, message="not connected")
        try:
            status = self.instrument.write("STATUS?")
            return DriverResponse(response=DriverResponseType.success, status=DriverStatus.ok, data={"status": status})
        except Exception as e:
            return DriverResponse(response=DriverResponseType.failed, status=DriverStatus.error, message=f"get_status failed: {e}")

    def set_output(self, output_on: bool = True) -> DriverResponse:
        if self.instrument is None:
            return DriverResponse(response=DriverResponseType.failed, status=DriverStatus.uninitialized, message="not connected")
        try:
            self.instrument.write("OUT1" if output_on else "OUT0")
            return DriverResponse(response=DriverResponseType.success, status=DriverStatus.ok)
        except Exception:
            pv.logger.error("set_output_on failed:", exc_info=True)
            return DriverResponse(response=DriverResponseType.failed, status=DriverStatus.error, message=f"set_output_on failed: {e}")

    def set_voltage(self, voltage_v: float = 0.0) -> DriverResponse:
        if self.instrument is None:
            return DriverResponse(response=DriverResponseType.success, status=DriverStatus.uninitialized, data={})
        try:
            self.instrument.write(f"VSET1:{voltage_v}")
            return DriverResponse(response=DriverResponseType.success, status=DriverStatus.ok)
        except Exception:
            pv.logger.error("set_voltage failed:", exc_info=True)
            return DriverResponse(response=DriverResponseType.failed, status=DriverStatus.error, message=f"set_voltage failed: {e}")

    def get_voltage(self) -> DriverResponse:
        if self.instrument is None:
            return DriverResponse(response=DriverResponseType.failed, status=DriverStatus.uninitialized, message="not connected")
        try:
            voltage_v = float(self.instrument.query("VOUT1?"))
            return DriverResponse(response=DriverResponseType.success, status=DriverStatus.ok, data={"voltage_v": voltage_v})
        except Exception:
            pv.logger.error("get_voltage failed:", exc_info=True)
            return DriverResponse(response=DriverResponseType.failed, status=DriverStatus.error, message=f"get_voltage failed: {e}")
    
    async def get_voltage_async(self, sleep_time: float = 0.05) -> 'DriverResponse':
        """
        Asynchronously reads the output voltage of the power supply.
        """
        if self.instrument is None:
            return DriverResponse(response=DriverResponseType.failed, status=DriverStatus.uninitialized, message="not connected")
        try:
            voltage_v = float(self.instrument.query("VOUT1?"))
            await asyncio.sleep(sleep_time)
            return DriverResponse(response=DriverResponseType.success, status=DriverStatus.ok, data={"voltage_v": voltage_v})
        except Exception:
            pv.logger.error("get_voltage_async failed:", exc_info=True)
            return DriverResponse(response=DriverResponseType.failed, status=DriverStatus.error, message=f"get_voltage_async failed: {e}")

    async def get_current_async(self, sleep_time: float = 0.05) -> 'DriverResponse':
        """
        Asynchronously reads the output current of the power supply.
        """
        if self.instrument is None:
            return DriverResponse(response=DriverResponseType.failed, status=DriverStatus.uninitialized, message="not connected")
        try:
            current_a = float(self.instrument.query("IOUT1?"))
            await asyncio.sleep(sleep_time)
            return DriverResponse(response=DriverResponseType.success, status=DriverStatus.ok, data={"current_a": current_a})
        except Exception:
            pv.logger.error("get_current_async failed:", exc_info=True)
            return DriverResponse(response=DriverResponseType.failed, status=DriverStatus.error, message=f"get_current failed: {e}")


            
    async def apply_voltage_async(self, voltage: float, sleep_time: float = 0.05) -> 'DriverResponse':
        """
        Asynchronously sets the output voltage of the power supply to the specified value.

        Args:
            voltage (float): The voltage value to set.

        Returns:
            DriverResponse: Result of the operation.
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
            pv.logger.error("apply_voltage_async failed:", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.error,
                message=f"apply_voltage failed",
            )


    def stop(self) -> DriverResponse:
        """
        Stops the power supply. This is just a dummy method to satisfy the interface.
        """
        if self.instrument is None:
            return DriverResponse(response=DriverResponseType.failed, status=DriverStatus.uninitialized, message="not connected")
        try:
            return DriverResponse(response=DriverResponseType.success, status=DriverStatus.ok)
        except Exception:
            pv.logger.error("stop failed:", exc_info=True)
            return DriverResponse(response=DriverResponseType.failed, status=DriverStatus.error, message=f"stop failed: {e}")




    def disconnect(self) -> DriverResponse:
        try:
            if self.instrument is not None:
                self.instrument.close()
            if self.rm is not None:
                self.rm.close()
            self.instrument = None
            self.rm = None
            self.ready = False
            return DriverResponse(response=DriverResponseType.success, status=DriverStatus.uninitialized)
        except Exception:
            pv.logger.error("disconnect failed:", exc_info=True)
            return DriverResponse(response=DriverResponseType.failed, status=DriverStatus.error, message=f"disconnect failed: {e}")

    def reset(self) -> DriverResponse:
        self.disconnect()
        return self.connect()