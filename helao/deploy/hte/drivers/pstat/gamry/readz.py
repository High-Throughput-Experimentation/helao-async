import time
import numpy as np

from .signal import ControlMode
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


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
        expected_z,
        frequencies=[],
        use_ac_ierange=False,
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
        self.freq_list = frequencies
        self.use_ac_ierange = use_ac_ierange
        self.dtaqsink = GamryReadZSink(self.dtaq)
        self.init_cell_off = init_cell_off
        self.leave_cell_on = leave_cell_on
        self.expected_z = expected_z

    def init_pstat(self):
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
        self.dtaq.SetZmod(self.expected_z)

        if self.control_mode == ControlMode.GstatMode:
            self.pstat.SetCASpeed(3)
            self.dtaq.SetIdc(self.dc_amplitude)
            LOGGER.info(f"Setting DC current to {self.dc_amplitude:.2e} A")
            LOGGER.info(f"Setting AC current to {self.ac_amplitude:.2e} A")
            self.set_ie_range(self.freq_list[0], self.expected_z)
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

            self.set_ie_range(self.freq_list[0], self.expected_z)
            if self.init_cell_off:
                self.pstat.SetCell(self.GamryCOM.CellOn)
                time.sleep(1)
                self.dtaq.SetIdc(self.pstat.MeasureI())

        LOGGER.info(f"VchRange: {self.pstat.VchRange()}")
        self.pstat.SetCell(self.GamryCOM.CellOn)

    def set_ie_range(self, frequency: float, z_guess: float, s_dc_max: float = 1.0):
        if self.use_ac_ierange:
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
                    / self.expected_z
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


class GamryReadZSink:
    """Event sink for reading data from Gamry device."""

    def __init__(self, dtaq):
        self.dtaq = dtaq
        self.acquired_points = []
        self.status = "idle"
        self.buffer_size = 0

    def cook(self):
        count = 1
        while count > 0:
            try:
                count, points = self.dtaq.Cook(1024)
                self.acquired_points.extend(zip(*points))
            except Exception:
                count = 0

    def _IGamryReadZEvents_OnDataAvailable(self):
        self.cook()
        self.status = "measuring"

    def _IGamryReadZEvents_OnDataDone(self):
        self.cook()  # a final cook
        self.status = "done"
