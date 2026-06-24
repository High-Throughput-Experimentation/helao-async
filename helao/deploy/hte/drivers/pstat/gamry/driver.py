"""Gamry potentiostat driver built on the HelaoDriver abstract base class.

Wraps the GamryCOM Windows COM API behind the HelaoDriver contract. All
public driver methods are blocking and return a ``DriverResponse``; any async
behavior is expected to be implemented in the calling action server. The
driver chooses an appropriate ``GamryPstat`` model from ``GAMRY_DEVICES``
based on the device name returned by ``GamryDeviceList``, configures
sense/range/filter settings during setup, drives data acquisition via a
``GamryDtaqSink``, and exposes EIS measurements through a ``ReadZ`` helper.
"""

import sys

sys.coinit_flags = 0x0

# save a default log file system temp
from helao.framework.support import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
import comtypes
import comtypes.client as client
import psutil
import time
from enum import Enum
from copy import copy

import numpy as np

from helao.framework.ports.driver import (
    HelaoDriver,
    DriverResponse,
    DriverStatus,
    DriverResponseType,
    DriverPoller,
)

from .device import GamryPstat, GAMRY_DEVICES, TTL_OUTPUTS, TTL_OFF
from .sink import GamryDtaqSink, DummySink
from .technique import GamryTechnique
from .range import get_range, RANGES
from .signal import ControlMode
from .readz import ReadZ

DUMMY_SINK = DummySink()


class GamryDriver(HelaoDriver):
    """HelaoDriver implementation for a Gamry potentiostat via GamryCOM.

    Manages a single COM connection to one device in the GamryCOM device list,
    holds the currently configured technique/signal/dtaq state, and exposes
    blocking ``setup``/``measure``/``get_data``/``stop``/``cleanup`` methods
    plus EIS helpers (``setup_eis``/``close_eis``).

    Attributes:
        dtaqsink: Event sink that buffers data points from the active dtaq.
        device_name: Name reported by GamryCOM for the connected device.
        model: ``GamryPstat`` descriptor selected based on ``device_name``.
    """

    dtaqsink: GamryDtaqSink
    device_name: str
    model: GamryPstat

    def __init__(self, config: dict = {}):
        """Initialize the driver and open the GamryCOM connection.

        Args:
            config: Driver configuration. Recognized keys are ``dev_id``
                (index into ``GamryDeviceList.EnumSections``),
                ``filterfreq_hz`` (analog input filter, default 1000 Hz), and
                ``grounded`` (passed to ``SetGround``, default True).
        """
        super().__init__(config=config)
        #
        self.device_name = "unknown"
        self.dtaq = None
        self.dtaqsink = DUMMY_SINK
        self.events = None
        self.technique = None
        self.pstat = None
        self.signal = None
        self.readz = None
        self.ready = True
        self.counter = 0
        # get params from config or use defaults
        self.device_id = self.config.get("dev_id", None)
        self.filterfreq_hz = 1.0 * self.config.get("filterfreq_hz", 1000.0)
        self.grounded = int(self.config.get("grounded", True))
        self.connection_raised = False
        self.stopping = False
        self.connect()
        LOGGER.debug(f"connected to {self.device_name} on device_id {self.device_id}")

    def connect(self) -> DriverResponse:
        """Load the GamryCOM type library, open the device, and turn the cell off.

        Selects the ``GamryPstat`` model based on the device-name prefix and
        leaves the potentiostat in a safe ``CellOff`` state.

        Returns:
            ``DriverResponse`` reporting connection success or failure.
        """
        try:
            self.connection_raised = True
            LOGGER.info(f"using device_id {self.device_id} from config")
            self.GamryCOM = client.GetModule(
                ["{BD962F0D-A990-4823-9CF5-284D1CDD9C6D}", 1, 0]
            )
            devices = client.CreateObject("GamryCOM.GamryDeviceList")
            self.device_name = devices.EnumSections()[self.device_id]
            self.model = GAMRY_DEVICES.get(
                self.device_name.split("-")[0], GAMRY_DEVICES["DEFAULT"]
            )
            self.pstat = client.CreateObject(self.model.device)
            self.pstat.Init(self.device_name)
            self.pstat.Open()
            self.pstat.SetCell(self.GamryCOM.CellOff)
            self.state = self.pstat.State()
            response = DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            LOGGER.error("connect failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        return response

    def get_status(self, retries: int = 5) -> DriverResponse:
        """Return the parsed instrument state reported by ``pstat.State()``.

        Args:
            retries: Currently unused retry hint.

        Returns:
            ``DriverResponse`` whose ``data`` is the key/value dictionary
            parsed from the GamryCOM state string, or ``status=uninitialized``
            if the pstat object has not been created.
        """
        if self.pstat is not None:
            try:
                self.state = self.pstat.State()
                state = dict([x.split("\t") for x in self.state.split("\r\n") if x])
                response = DriverResponse(
                    response=DriverResponseType.success,
                    data=state,
                    status=DriverStatus.ok,
                )
            except Exception:
                LOGGER.error("get_status failed", exc_info=True)
                response = DriverResponse(
                    response=DriverResponseType.failed, status=DriverStatus.error
                )
        else:
            response = DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.uninitialized
            )
        return response

    def setup(
        self,
        technique: GamryTechnique,
        signal_params: dict = {},
        dtaq_params: dict = {},
        action_params: dict = {},  # for mapping action keys to signal keys
        ierange: Enum = "auto",
    ) -> DriverResponse:
        """Configure the potentiostat for a single measurement.

        Applies analog input ranges and filters, selects the I/E range, sets
        the control mode, constructs the technique-specific dtaq and signal
        COM objects, applies dtaq stop/threshold limits, and resolves any
        ``signal.map_keys`` against the supplied ``action_params``.

        Args:
            technique: Technique descriptor specifying the dtaq, signal, and
                range-handling flags.
            signal_params: Parameters consumed by the GamrySignal object
                (e.g. ``Vinit__V``, ``Vfinal__V``).
            dtaq_params: Optional dtaq limit/threshold parameters. Keys must
                appear in ``technique.dtaq.int_param_keys`` or
                ``bool_param_keys``.
            action_params: Action-server parameters used to fill in any
                signal map keys that name a string source.
            ierange: Requested current range identifier. Resolved against the
                model-specific range enum by ``get_range``.

        Returns:
            ``DriverResponse`` reporting setup status.

        Raises:
            TypeError: If another technique is still active (non-``DummySink``).
            KeyError: If the resolved signal parameters are missing keys
                required by the technique.
        """
        try:
            # check for ongoing measurement via dtaqsink
            if not isinstance(self.dtaqsink, DummySink):
                raise TypeError(
                    "dtaqsink is not of type DummySink. Another technique may be running."
                )

            # apply initial configuration
            # self.pstat.SetCell(self.GamryCOM.CellOff)
            self.pstat.SetPosFeedEnable(False)
            self.pstat.SetIEStability(self.GamryCOM.StabilityFast)
            self.pstat.SetSenseSpeedMode(self.model.set_sensemode)
            self.pstat.SetIConvention(self.GamryCOM.Anodic)
            self.pstat.SetGround(self.config.get("grounded", True))

            # maximum anticipated voltage (in Volts).
            ichrangeval = self.pstat.TestIchRange(3.0)
            self.pstat.SetIchRange(ichrangeval)
            self.pstat.SetIchRangeMode(True)  # auto-set
            self.pstat.SetIchOffsetEnable(False)

            # call TestIchFilter before setting SetIchFilter
            ichfilterval = self.pstat.TestIchFilter(
                self.config.get("filterfreq_hz", 1000.0)
            )
            self.pstat.SetIchFilter(ichfilterval)

            # voltage channel range.
            vchrangeval = self.pstat.TestVchRange(12.0)
            self.pstat.SetVchRange(vchrangeval)
            self.pstat.SetVchRangeMode(True)
            self.pstat.SetVchOffsetEnable(False)

            # call TestVchFilter before setting SetVchFilter
            vchfilterval = self.pstat.TestVchFilter(
                self.config.get("filterfreq_hz", 1000.0)
            )
            self.pstat.SetVchFilter(vchfilterval)

            # set the range of the Auxiliary A/D input.
            self.pstat.SetAchRange(3.0)

            # set the I/E Range of the potentiostat.
            self.pstat.SetAnalogOut(0.0)
            self.pstat.SetIruptMode(self.GamryCOM.IruptOff)

            # set device-specific ranges
            self.technique = technique
            self.pstat.SetIERange(0.03)  # default range
            range_enum = get_range(ierange, self.model.ierange)
            if range_enum == self.model.ierange.auto:
                self.pstat.SetIERangeMode(self.model.set_rangemode)
            else:
                self.pstat.SetIERange(RANGES[range_enum.name])

            # override device-specific ranges with technique ranges if given
            self.pstat.SetCtrlMode(getattr(self.GamryCOM, technique.signal.mode.value))
            if technique.set_vchrangemode is not None:
                self.pstat.SetVchRangeMode(technique.set_vchrangemode)
            if technique.vchrange_keys is not None:
                setpointv = np.max(
                    [np.abs(signal_params[x]) for x in technique.vchrange_keys]
                )
                vchrangeval = self.pstat.TestVchRange(setpointv * 1.1)
                self.pstat.SetVchRange(vchrangeval)
            if technique.set_ierangemode is not None:
                self.pstat.SetIERangeMode(technique.set_ierangemode)
            if technique.ierange_keys is not None:
                setpointie = np.max(
                    [np.abs(signal_params[x]) for x in technique.ierange_keys]
                )
                ierangeval = self.pstat.TestIERange(setpointie)
                self.pstat.SetIERange(ierangeval)

            # initialize dtaq
            self.dtaq = client.CreateObject(technique.dtaq.name)
            dtaq_init_args = (signal_params[x] for x in technique.signal.init_keys)
            if technique.dtaq.dtaq_type is not None:
                self.dtaq.Init(
                    self.pstat,
                    getattr(self.GamryCOM, technique.dtaq.dtaq_type.value),
                    *dtaq_init_args,
                )
            else:
                self.dtaq.Init(self.pstat, *dtaq_init_args)
            if technique.set_decimation is not None:
                self.dtaq.SetDecimation(technique.set_decimation)

            # apply dtaq limits
            for dtaq_key, val in dtaq_params.items():
                if val is None:
                    continue
                elif dtaq_key in technique.dtaq.int_param_keys:
                    getattr(self.dtaq, dtaq_key)(val)
                elif dtaq_key in technique.dtaq.bool_param_keys:
                    getattr(self.dtaq, dtaq_key)(True, val)

            # create event sink
            self.dtaqsink = GamryDtaqSink(self.dtaq)

            # map action params to signal params (e.g. OCV and CV cases)
            mapped_signal_params = copy(signal_params)
            for dest_key, val in technique.signal.map_keys.items():
                if dest_key in signal_params:
                    continue
                elif isinstance(val, str) and val in action_params:
                    mapped_signal_params[dest_key] = action_params[val]
                elif (
                    isinstance(val, float) or isinstance(val, int)
                ) and dest_key not in signal_params:
                    mapped_signal_params[dest_key] = val

            # check for missing parameter keys
            missing_keys = [
                key
                for key in technique.signal.param_keys + technique.signal.init_keys
                if key not in mapped_signal_params
            ]
            if missing_keys:
                raise KeyError(
                    f"missing parameter keys {missing_keys} required by {technique.name}"
                )
            signal_paramlist = (
                [self.pstat]
                + [mapped_signal_params[key] for key in technique.signal.param_keys]
                + [getattr(self.GamryCOM, self.technique.signal.mode.value)]
            )
            LOGGER.debug(signal_paramlist)
            self.signal = client.CreateObject(technique.signal.name)
            self.signal.Init(*signal_paramlist)
            self.pstat.SetSignal(self.signal)
            time.sleep(0.01)
            response = DriverResponse(
                response=DriverResponseType.success,
                message="setup complete",
                status=DriverStatus.ok,
            )
        except comtypes.COMError:
            LOGGER.error("setup failed on COMError", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
            self.reset()
            self.cleanup()
        except Exception:
            LOGGER.error("setup failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
            self.cleanup()
        return response

    def measure(self, ttl_params: dict = {}) -> DriverResponse:
        """Energize the cell and start dtaq data acquisition.

        Args:
            ttl_params: Optional ``{"TTLsend": <index>}`` selecting a digital
                output line to assert before the measurement begins.

        Returns:
            ``DriverResponse`` with ``status=busy`` and the wall-clock
            ``start_time`` in ``data`` on success.
        """
        try:
            # emit TTL output
            ttl_send = ttl_params.get("TTLsend", -1)
            if ttl_send > -1:
                self.pstat.SetDigitalOut(*TTL_OUTPUTS[ttl_send])
            # energize cell
            self.pstat.SetCell(getattr(self.GamryCOM, self.technique.on_method.value))
            # run data acquisition
            self.events = client.GetEvents(self.dtaq, self.dtaqsink)
            start_time = time.time()
            self.dtaq.Run(True)
            response = DriverResponse(
                response=DriverResponseType.success,
                message="measurement started",
                data={"start_time": start_time},
                status=DriverStatus.busy,
            )
        except comtypes.COMError:
            LOGGER.error("measure failed on COMError", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.error,
            )
            self.reset()
            self.cleanup()
        except Exception:
            LOGGER.error("measure failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.error,
            )
            self.cleanup()
        return response

    def get_data(self, pump_rate: float) -> DriverResponse:
        """Pump COM events and return any newly acquired data points.

        Args:
            pump_rate: Argument forwarded to ``comtypes.client.PumpEvents``,
                expressed in seconds.

        Returns:
            ``DriverResponse`` whose ``data`` maps each output key of the
            active dtaq to a list of new samples since the previous call, and
            whose ``status`` is ``busy`` while points are still arriving.
        """
        try:
            client.PumpEvents(pump_rate)
            total_points = len(self.dtaqsink.acquired_points)
            if self.counter < total_points:
                new_data = self.dtaqsink.acquired_points[self.counter : total_points]
                data_dict = {
                    k: v
                    for k, v in zip(
                        self.technique.dtaq.output_keys, np.matrix(new_data).T.tolist()
                    )
                }
            else:
                data_dict = {}

            sink_state = self.dtaqsink.status
            if sink_state == "measuring" or self.counter < total_points:
                status = DriverStatus.busy
            elif sink_state == "done":
                status = DriverStatus.ok
            else:
                status = DriverStatus.ok
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
        """General stop method to abort all active methods e.g. motion, I/O, compute.

        CV/CP/etc. use ``dtaqsink``; PEIS/GEIS use ``readz`` with ``dtaqsink`` still
        ``DummySink``, so we must stop ``readz`` here (same as GamryEisExec._manual_stop)
        or the visualizer ``stop_private`` path would not halt EIS.
        """
        try:
            if self.readz is not None:
                return await self.readz.stop()
            if not self.stopping:
                if self.dtaqsink.dtaq is not None:
                    self.stopping = True
                    self.dtaqsink.dtaq.Run(False)
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

    def cleanup(self, ttl_params: dict = {}) -> DriverResponse:
        """Turn the cell off, clear TTL output, and drop technique state.

        Does not close the COM connection.

        Args:
            ttl_params: Optional ``{"TTLsend": <index>}`` selecting a digital
                output line to de-assert.

        Returns:
            ``DriverResponse`` reporting cleanup status.
        """
        try:
            if self.pstat is not None:
                # disable TTL output
                ttl_send = ttl_params.get("TTLsend", -1)
                if ttl_send > -1:
                    self.pstat.SetDigitalOut(*TTL_OFF[ttl_send])
                self.pstat.SetCell(self.GamryCOM.CellOff)
            response = DriverResponse(
                response=DriverResponseType.success,
                message="measurement started",
                status=DriverStatus.ok,
            )
        except Exception:
            LOGGER.error("cleanup failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.error,
            )
        finally:
            self.events = None
            self.dtaq = None
            self.dtaqsink = DUMMY_SINK
            self.technique = None
            self.signal = None
            self.counter = 0
        return response

    def disconnect(self) -> DriverResponse:
        """Turn the cell off and close the GamryCOM pstat handle."""
        try:
            if self.pstat is not None:
                self.pstat.SetCell(self.GamryCOM.CellOff)
                self.pstat.Close()
            # self.ready = False
            response = DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            LOGGER.error("disconnect failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        finally:
            self.pstat = None
            self.connection_raised = False
        return response

    def reset(self) -> DriverResponse:
        """Force-kill the GamryCOM process and reconnect.

        Used to recover from a hung COM server: closes the existing pstat,
        terminates any running GamryCOM processes via ``kill_gamrycom``,
        then re-runs ``connect``.
        """
        try:
            self.pstat.SetCell(self.GamryCOM.CellOff)
            self.pstat.Close()
        except Exception:
            LOGGER.warn("Could not cleanly disconnect from pstat.", exc_info=True)
        try:
            kill_success = self.kill_gamrycom().response
            if kill_success == DriverResponseType.success:
                LOGGER.info("Successfully killed GamryCOM.")
            else:
                raise SystemError("Failed to kill GamryCOM.")
            self.connect()
            response = DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            LOGGER.error("reset error", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        return response

    def kill_gamrycom(self) -> DriverResponse:
        """Terminate any running GamryCOM Windows processes via psutil.

        Iterates ``psutil.process_iter`` looking for processes whose name
        starts with ``"gamrycom"`` and issues up to three ``terminate`` calls
        with short sleeps between them.

        Returns:
            ``DriverResponse`` with ``status=ok`` if all GamryCOM processes
            were terminated (or none were running).
        """
        try:
            process_ids = {
                p.pid: p
                for p in psutil.process_iter(["name"])
                if p.info["name"].lower().startswith("gamrycom")
            }

            for pid in process_ids:
                LOGGER.info(f"killing GamryCOM on PID: {pid}")
                p = psutil.Process(pid)
                for _ in range(3):
                    p.terminate()
                    time.sleep(0.5)
                    if not psutil.pid_exists(p.pid):
                        LOGGER.info("Successfully terminated GamryCom.")
                if psutil.pid_exists(p.pid):
                    LOGGER.warning(
                        "Failed to terminate server GamryCom after 3 retries."
                    )
                    raise SystemError(f"GamryCOM on PID: {pid} is still running.")
            response = DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except ProcessLookupError:
            LOGGER.warning("process not found, assume it's already dead.")
            response = DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            LOGGER.warning(
                "kill_gamrycom failed, likely already exited", exc_info=False
            )
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.ok
            )
        return response

    def shutdown(self) -> None:
        """Clean up technique state, disconnect, and kill GamryCOM.

        Invoked by ``BaseAPI`` when the action server is shutting down.
        """
        self.cleanup()
        self.disconnect()
        try:
            self.kill_gamrycom().response
        except Exception:
            LOGGER.error("shutdown error", exc_info=True)

    def setup_eis(
        self,
        control_mode: ControlMode,
        fast: bool,
        frequency: float,
        ac_amplitude: float,
        dc_amplitude: float,
        z_expected: float,
        set_ierange_ac: bool = False,
    ) -> DriverResponse:
        """Build a ``ReadZ`` helper for a single-frequency EIS measurement.

        Args:
            control_mode: Potentiostatic or galvanostatic control mode.
            fast: If True selects ``ReadZSpeedFast``; otherwise
                ``ReadZSpeedNorm``.
            frequency: Excitation frequency in Hz.
            ac_amplitude: AC amplitude (V for potentiostatic, A for
                galvanostatic).
            dc_amplitude: DC bias (V for potentiostatic, A for galvanostatic).
            z_expected: Expected impedance magnitude, used for range
                selection.
            set_ierange_ac: If True use ``TestIERangeAC`` instead of
                ``TestIERange`` when picking the current range.

        Returns:
            ``DriverResponse`` reporting EIS setup status.
        """
        try:
            # check for ongoing measurement via dtaqsink
            if not isinstance(self.dtaqsink, DummySink):
                raise TypeError(
                    "dtaqsink is not of type DummySink. Another technique may be running."
                )
            self.dtaq = client.CreateObject("GamryCOM.GamryReadZ")

            self.readz = ReadZ(
                control_mode,
                self.pstat,
                self.dtaq,
                self.GamryCOM,
                "ReadZSpeedFast" if fast else "ReadZSpeedNorm",
                ac_amplitude,
                dc_amplitude,
                z_expected,
                frequency,
                set_ierange_ac,
            )

            response = DriverResponse(
                response=DriverResponseType.success,
                message="EIS setup complete",
                status=DriverStatus.ok,
            )
        except Exception:
            LOGGER.error("EIS setup failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        return response

    def close_eis(self) -> DriverResponse:
        """Stop the EIS dtaq, turn the cell off, and clear EIS state."""
        try:
            if self.dtaq is not None:
                self.dtaq.Run(False)
                self.dtaq.stop()
            if self.pstat is not None:
                self.pstat.SetCell(self.GamryCOM.CellOff)
            self.readz.events = None
            self.readz = None
            response = DriverResponse(
                response=DriverResponseType.success,
                message="EIS closed",
                status=DriverStatus.ok,
            )
        except Exception:
            LOGGER.error("EIS close failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        finally:
            self.events = None
            self.dtaq = None
            self.dtaqsink = DUMMY_SINK
            self.technique = None
            self.signal = None
            self.counter = 0
        return response

    def get_gamry_state(self) -> dict:
        """Return the raw ``pstat.State()`` string parsed into a key/value dict."""
        state = self.pstat.State()
        state = dict([x.split("\t") for x in state.split("\r\n") if x])
        return state


class GamryPoller(DriverPoller):
    """Background poller that samples voltage/current/aux directly from the pstat.

    Note: this poller calls the same COM methods used by running techniques,
    so it conflicts with any active measurement and should only be used when
    the driver is idle.

    Attributes:
        driver: The ``GamryDriver`` instance whose pstat handle is polled.
    """

    driver: GamryDriver

    def get_data(self) -> DriverResponse:
        """Sample ``Ewe_V``, ``I_A``, and ``Aux_V`` and append driver status.

        Returns:
            ``DriverResponse`` whose ``data`` contains the three measured
            quantities plus the parsed pstat state, or ``status=uninitialized``
            if the pstat handle is not open.
        """
        try:
            if self.driver.pstat.TestIsOpen():
                poll_data = {
                    "Ewe_V": self.driver.pstat.MeasureV(),
                    "I_A": self.driver.pstat.MeasureI(),
                    "Aux_V": self.driver.pstat.MeasureA(),
                }
                poll_data.update(self.driver.get_status().data)
                resp = DriverResponse(
                    response=DriverResponseType.success,
                    status=DriverStatus.ok,
                    data=poll_data,
                )
            else:
                resp = DriverResponse(
                    response=DriverResponseType.success,
                    status=DriverStatus.uninitialized,
                    data={},
                )
        except Exception:
            LOGGER.error("polling error", exc_info=True)
            resp = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )

        return resp
