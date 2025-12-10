import time
import asyncio
import numpy as np
import comtypes.client as client

from .signal import ControlMode
from helao.core.drivers.helao_driver import (
    DriverResponse,
    DriverResponseType,
    DriverStatus,
)
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


async def measure_ocv(pstat, gamrycom, duration: float = 2.0, acquisition_period: float = 0.1):
    # pstat.Open()
    pstat.SetCell(gamrycom.CellOff)
    data = []

    ocv_start_time = time.time()
    while time.time() - ocv_start_time <= duration:
        data.append((time.time() - ocv_start_time, pstat.MeasureV()))
        await asyncio.sleep(acquisition_period)
    ts, vs = list(zip(*data))
    return list(ts), list(vs)

class ReadZ:

    def __init__(
        self,
        control_mode,
        pstat,
        dtaq,
        gamrycom,
        readspeed,
        ac_amplitude,
        dc_amplitude,
        z_expected,
        frequency,
        set_ierange_ac=False,
        init_cell_off=True,
        leave_cell_on=False,
    ):
        self.control_mode = control_mode
        self.pstat = pstat
        self.dtaq = dtaq
        self.GamryCOM = gamrycom
        self.readspeed = readspeed
        self.ac_amplitude = ac_amplitude
        self.dc_amplitude = dc_amplitude
        self.frequency = frequency
        self.set_ierange_ac = set_ierange_ac
        self.dtaqsink = GamryReadZSink(self.dtaq, gc=self.GamryCOM)
        self.init_cell_off = init_cell_off
        self.leave_cell_on = leave_cell_on
        self.z_expected = z_expected
        self.events = None
        self.counter = 0

    def init_pstat(self):
        try:
            self.events = client.GetEvents(self.dtaq, self.dtaqsink)
            self.pstat.SetAchSelect(self.GamryCOM.GND)
            self.pstat.SetCtrlMode(getattr(self.GamryCOM, self.control_mode.value))
            self.pstat.SetIEStability(self.GamryCOM.StabilityFast)
            self.pstat.SetSenseSpeedMode(True)
            self.pstat.SetIConvention(self.GamryCOM.Anodic)
            self.pstat.SetGround(self.GamryCOM.Float)
            self.pstat.SetIchOffsetEnable(False)
            self.pstat.SetVchOffsetEnable(True)
            self.pstat.SetIERangeMode(False)
            self.pstat.SetAnalogOut(0.0)
            self.pstat.SetPosFeedEnable(False)
            self.pstat.SetIruptMode(self.GamryCOM.IruptOff)

            self.dtaq.Init(self.pstat)
            self.dtaq.SetSpeed(getattr(self.GamryCOM, self.readspeed))
            self.dtaq.SetGain(1.0)
            self.dtaq.SetINoise(0.0)
            self.dtaq.SetVNoise(0.0)
            self.dtaq.SetIENoise(0.0)
            self.dtaq.SetZmod(self.z_expected)

            if self.control_mode == ControlMode.GstatMode:
                self.pstat.SetCASpeed(3)
                self.dtaq.SetIdc(self.dc_amplitude)
                LOGGER.info(f"Setting DC current to {self.dc_amplitude:.2e} A")
                LOGGER.info(f"Setting AC current to {self.ac_amplitude:.2e} A")
                self.set_ierange(self.frequency, self.z_expected)
                if self.init_cell_off:
                    self.pstat.SetCell(self.GamryCOM.CellOn)  # turn the cell on
                    LOGGER.debug("Waiting 3s for sample equilibration...")
                    time.sleep(3)  # Let sample equilibrate
                self.pstat.FindVchRange()

            elif self.control_mode == ControlMode.PstatMode:
                LOGGER.info(f"Setting DC voltage to {self.dc_amplitude:.2e} V")
                LOGGER.info(f"Setting AC voltage to {self.ac_amplitude:.2e} V")
                v_max = abs(self.dc_amplitude) + np.sqrt(2) * abs(self.ac_amplitude)
                self.pstat.SetVchRange(self.pstat.TestVchRange(v_max))

                self.pstat.SetCASpeed(3)
                self.pstat.SetVoltage(self.dc_amplitude)

                self.set_ierange(self.frequency, self.z_expected)
                if self.init_cell_off:
                    self.pstat.SetCell(self.GamryCOM.CellOn)
                    time.sleep(1)
                    self.dtaq.SetIdc(self.pstat.MeasureI())

            LOGGER.info(f"VchRange: {self.pstat.VchRange()}")
            self.pstat.SetCell(self.GamryCOM.CellOn)

            response = DriverResponse(
                response=DriverResponseType.success,
                message="Potentiostat initialized successfully for EIS.",
                status=DriverStatus.ok,
            )
        except Exception:
            LOGGER.error("Error during potentiostat initialization.", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed,
                message="Error during potentiostat initialization.",
                status=DriverStatus.error,
            )
        return response

    def set_ierange(self, frequency: float, z_guess: float, s_dc_max: float = 1.0):
        if self.set_ierange_ac:
            if self.control_mode == ControlMode.GstatMode:
                v_ac_max = self.ac_amplitude * z_guess * 2
                IERange = self.pstat.TestIERangeAC(
                    self.ac_amplitude, v_ac_max, self.dc_amplitude, s_dc_max, frequency
                )
            else:
                i_ac_max = 2 * self.ac_amplitude / z_guess
                IERange = self.pstat.TestIERangeAC(
                    i_ac_max, self.ac_amplitude, s_dc_max, self.dc_amplitude, frequency
                )
        else:
            if self.control_mode == ControlMode.GstatMode:
                # 5% buffer
                i_max = 1.05 * (
                    abs(self.dc_amplitude) + (2**0.5) * abs(self.ac_amplitude)
                )
            else:
                i_max = (
                    2
                    * (abs(self.dc_amplitude) + (2**0.5) * self.ac_amplitude)
                    / self.z_expected
                )

            IERange = self.pstat.TestIERange(i_max)

        LOGGER.info(f"IERange: {IERange}")
        self.pstat.SetIERange(IERange)

        if self.control_mode == ControlMode.GstatMode:
            Rm = self.pstat.IEResistor(IERange)
            v_internal = Rm * self.dc_amplitude
            self.pstat.SetVoltage(v_internal)

    def set_cycle_limit(self, frequency):
        if frequency > 3e4:
            cycle_lim = (10, 20)
        elif frequency > 1e3:
            cycle_lim = (8, 12)
        elif frequency > 30:
            cycle_lim = (4, 8)
        elif frequency > 1:
            cycle_lim = (3, 6)
        else:
            cycle_lim = (2, 4)
        self.dtaq.SetCycleLim(*cycle_lim)

    def measure_frequency(self, frequency):
        LOGGER.debug(f"Measuring frequency: {frequency:.2f} Hz")
        self.set_cycle_limit(frequency)
        self.dtaq.Measure(frequency, self.ac_amplitude)

    def get_data(self, pump_rate: float) -> DriverResponse:
        """Retrieve data from device buffer."""
        try:
            client.PumpEvents(pump_rate)
            time.sleep(0.1)
            total_points = len(self.dtaqsink.acquired_points)
            LOGGER.debug("acq_pts:", total_points)

            sink_state = self.dtaqsink.status
            LOGGER.info(f"Data sink state: {sink_state}")
            data_dict = {}
            if sink_state == "measuring" or self.counter < total_points:
                status = DriverStatus.busy
            elif sink_state == "retry":
                status = DriverStatus.retry
            elif sink_state == "error":
                status = DriverStatus.error
            elif sink_state == "done":
                status = DriverStatus.ok
            else:
                status = DriverStatus.ok
            if self.dtaqsink.z_values:
                data_dict.update(self.dtaqsink.z_values)
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

    async def stop(self) -> DriverResponse:
        """General stop method to abort all active methods e.g. motion, I/O, compute."""
        try:
            if not self.stopping:
                if self.dtaqsink.dtaq is not None:
                    self.stopping = True
                    self.dtaqsink.dtaq.Stop()
                    self.dtaqsink.status = "done"
                    self.stopping = False
            response = DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            LOGGER.error("stop failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        return response


class GamryReadZSink:
    """Event sink for reading data from Gamry device."""

    def __init__(self, dtaq, gc):
        self.dtaq = dtaq
        self.GamryCOM = gc
        self.acquired_points = []
        self.status = "idle"
        self.buffer_size = 0
        self.z_values = {}

    def read_z_values(self):
        keys = [
            "Zfreq",
            "Zreal",
            "Zimag",
            "Zsig",
            "Zmod",
            "Zphz",
            "Ireal",
            "Iimag",
            "Isig",
            "Imod",
            "Iphz",
            "Idc",
            "Vreal",
            "Vimag",
            "Vsig",
            "Vmod",
            "Vphz",
            "Vdc",
            "Gain",
            "INoise",
            "VNoise",
            "IENoise",
            "IERange",
        ]
        self.z_values = {k: getattr(self.dtaq, k)() for k in keys}

    def cook(self):
        count = 1
        while count > 0:
            try:
                count, points = self.dtaq.Cook(1024)
                self.acquired_points.extend(zip(*points))
            except Exception:
                count = 0

    def _IGamryReadZEvents_OnDataAvailable(self, this):
        self.cook()
        self.status = "measuring"

    def _IGamryReadZEvents_OnDataDone(self, this, done_status):
        com_status = done_status
        self.cook()  # a final cook
        if com_status == self.GamryCOM.ReadZStatusRetry:
            self.status = "retry"
        elif com_status == self.GamryCOM.ReadZStatusOk:
            self.read_z_values()
            self.status = "done"
        else:
            self.status = "error"

    def reset(self):
        self.acquired_points = []
        self.status = "idle"
        self.buffer_size = 0
        self.z_values = {}