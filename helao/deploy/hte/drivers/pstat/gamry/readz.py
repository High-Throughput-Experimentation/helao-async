"""Gamry single-frequency impedance helper built on ``GamryReadZ``.

Wraps the COM ``GamryReadZ`` dtaq plus its event sink in a ``ReadZ`` helper
class that handles pstat initialization for EIS (range selection, sense/iE
configuration, cell equilibration) and exposes ``measure_frequency`` /
``get_data`` / ``stop`` entry points. Also provides an async ``measure_ocv``
helper for short OCV pre-measurements and a ``GamryReadZSink`` that buffers
points cooked from the dtaq and extracts the impedance result tuple on
completion.
"""

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


async def measure_ocv(pstat, gamrycom, duration: float = 2.0, acquisition_period: float = 0.1) -> tuple:
    """Measure open-circuit voltage by polling ``pstat.MeasureV`` while the cell is off.

    Args:
        pstat: GamryCOM pstat COM object.
        gamrycom: Loaded GamryCOM type library.
        duration: Total acquisition duration in seconds.
        acquisition_period: Delay between successive voltage samples.

    Returns:
        ``(times, voltages)`` tuple of lists, where each time is relative to
        the start of the call.
    """
    pstat.SetCell(gamrycom.CellOff)
    data = []

    ocv_start_time = time.time()
    while time.time() - ocv_start_time <= duration:
        data.append((time.time() - ocv_start_time, pstat.MeasureV()))
        await asyncio.sleep(acquisition_period)
    ts, vs = list(zip(*data))
    return list(ts), list(vs)

class ReadZ:
    """Helper around a GamryCOM ``ReadZ`` dtaq for single-frequency EIS.

    Holds the references to the pstat, dtaq, GamryCOM library, and event
    sink, and provides methods to configure the potentiostat for EIS,
    pick an appropriate I/E range, measure a single frequency, and stop the
    acquisition.
    """

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
        """Store EIS measurement parameters and create the event sink.

        Args:
            control_mode: ``ControlMode`` selecting potentiostatic or
                galvanostatic operation.
            pstat: GamryCOM pstat COM object.
            dtaq: Pre-created ``GamryCOM.GamryReadZ`` COM object.
            gamrycom: Loaded GamryCOM type library.
            readspeed: GamryCOM constant name for the read speed (e.g.
                ``"ReadZSpeedFast"``).
            ac_amplitude: AC amplitude (V or A).
            dc_amplitude: DC bias (V or A).
            z_expected: Expected impedance magnitude in ohms.
            frequency: Excitation frequency in Hz.
            set_ierange_ac: Use ``TestIERangeAC`` when picking the I/E range.
            init_cell_off: Whether the cell starts in the off state and
                should be equilibrated after enabling.
            leave_cell_on: Currently informational; if False the caller is
                expected to turn the cell off after the measurement.
        """
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
        self.stopping = False

    def init_pstat(self) -> DriverResponse:
        """Configure the pstat and dtaq for EIS at the stored conditions.

        Applies control mode, sense/range/ground settings, registers the
        event sink, picks an I/E range via ``set_ierange``, and enables the
        cell (with a brief equilibration delay when starting from cell-off).

        Returns:
            ``DriverResponse`` reporting initialization status.
        """
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
        """Choose an I/E range based on the expected current magnitude.

        Computes the worst-case AC+DC current from the configured amplitudes
        and expected impedance, then calls ``TestIERange`` (or
        ``TestIERangeAC`` when ``set_ierange_ac`` is True) and applies the
        result via ``SetIERange``. In galvanostatic mode also recomputes the
        internal source voltage from the IE resistor.

        Args:
            frequency: Excitation frequency in Hz, only used by the AC range
                selector.
            z_guess: Expected impedance magnitude in ohms.
            s_dc_max: DC slew-rate cap forwarded to ``TestIERangeAC``.
        """
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
        """Apply a frequency-dependent (min, max) cycle limit to the dtaq.

        Higher frequencies use larger cycle limits to average noise; lower
        frequencies use smaller limits to keep total acquisition time
        bounded.

        Args:
            frequency: Excitation frequency in Hz.
        """
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
        """Begin a single-frequency EIS measurement.

        Args:
            frequency: Excitation frequency in Hz.
        """
        LOGGER.debug(f"Measuring frequency: {frequency:.2f} Hz")
        self.set_cycle_limit(frequency)
        self.dtaq.Measure(frequency, self.ac_amplitude)

    def get_data(self, pump_rate: float) -> DriverResponse:
        """Pump COM events and return EIS results once the sink reports ``done``.

        Args:
            pump_rate: Argument forwarded to ``comtypes.client.PumpEvents``.

        Returns:
            ``DriverResponse`` whose ``status`` mirrors the sink state
            (``busy``/``retry``/``error``/``ok``) and whose ``data`` contains
            the impedance result dict only once the sink is done.
        """
        try:
            client.PumpEvents(pump_rate)
            time.sleep(0.1)
            total_points = len(self.dtaqsink.acquired_points)
            LOGGER.debug("acq_pts:", total_points)

            sink_state = self.dtaqsink.status
            LOGGER.info(f"Data sink state: {sink_state}")
            data_dict = {}
            if sink_state == "measuring":
                status = DriverStatus.busy
            elif sink_state == "retry":
                status = DriverStatus.retry
            elif sink_state == "error":
                status = DriverStatus.error
            else:
                status = DriverStatus.ok
            if sink_state == "done" or self.counter == total_points:
                data_dict = self.dtaqsink.z_values
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
        """Abort the currently running ReadZ dtaq and mark the sink as done."""
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
    """COM event sink that buffers samples from a ``GamryReadZ`` dtaq.

    Receives ``OnDataAvailable`` / ``OnDataDone`` callbacks from the COM
    layer, cooks them into Python tuples, and on completion captures the
    full impedance result tuple via ``read_z_values``.

    Attributes:
        dtaq: The ``GamryReadZ`` COM object whose events are being received.
        GamryCOM: Loaded GamryCOM type library, used to compare status codes.
        acquired_points: Accumulated raw data points from successive cooks.
        status: Current sink state -- ``idle``, ``measuring``, ``retry``,
            ``done``, or ``error``.
        buffer_size: Reserved for future use.
        z_values: Final impedance result dict populated once the dtaq
            reports ``ReadZStatusOk``.
    """

    def __init__(self, dtaq, gc):
        """Initialize the sink with empty buffers in the ``idle`` state.

        Args:
            dtaq: The ``GamryReadZ`` COM object.
            gc: Loaded GamryCOM type library.
        """
        self.dtaq = dtaq
        self.GamryCOM = gc
        self.acquired_points = []
        self.status = "idle"
        self.buffer_size = 0
        self.z_values = {}

    def read_z_values(self):
        """Capture the final impedance result tuple from the dtaq."""
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
        """Drain points from the dtaq via repeated ``Cook(1024)`` calls."""
        count = 1
        while count > 0:
            try:
                count, points = self.dtaq.Cook(1024)
                self.acquired_points.extend(zip(*points))
            except Exception:
                count = 0

    def _IGamryReadZEvents_OnDataAvailable(self, this):
        """COM callback invoked when new EIS data is ready to cook."""
        self.cook()
        self.status = "measuring"

    def _IGamryReadZEvents_OnDataDone(self, this, done_status):
        """COM callback invoked when the EIS measurement finishes.

        Performs a final cook, then captures the impedance result on
        ``ReadZStatusOk``, marks the sink as ``retry`` on
        ``ReadZStatusRetry``, or ``error`` otherwise.
        """
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
        """Clear accumulated points and return the sink to ``idle`` state."""
        self.acquired_points = []
        self.status = "idle"
        self.buffer_size = 0
        self.z_values = {}