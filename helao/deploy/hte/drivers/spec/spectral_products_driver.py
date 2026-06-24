"""Spectral Products SM303 spectrometer driver.

Wraps the vendor-supplied ``SMdbUSBm.dll`` to operate the SM303 spectrometer
in software- or externally-triggered acquisition modes. The :class:`SM303`
class is owned by the spec action server and pushes acquired spectra into
the active action's data stream.
"""

__all__ = ["SM303"]

import os
import time
import ctypes
import asyncio
import traceback

import numpy as np

from helao.framework.support import helao_logging as logging
from helao.framework.models.errors import ErrorCodes
from helao.framework.models.data import DataModel
from helao.framework.models.file import FileConnParams, HloHeaderModel
from helao.framework.models.sample import SampleInheritance, SampleStatus
from helao.framework.models.hlostatus import HloStatus
from helao.framework.domain.run_models import Action
from helao.framework.models.active_params import ActiveParams
from helao.framework.adapters.sample_api import UnifiedSampleDataAPI
from helao.framework.app.base_api import Base, Active
from ...drivers.io.enum import TriggerType
from ...drivers.spec.enum import SpecTrigType


LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class SM303:
    """Driver for the Spectral Products SM303 USB spectrometer.

    Loads the vendor ``SMdbUSBm.dll`` (path from the action-server config),
    sets up the device (TEC, integration time, trigger mode), and provides
    synchronous single-shot acquisition (:meth:`acquire_spec_adv`) and
    asynchronous external-trigger acquisition (:meth:`acquire_spec_extrig`)
    that streams spectra to the active HELAO :class:`Active` object via a
    background polling task.
    """

    def __init__(self, action_serv: Base):
        """Initialise the SM303 driver.

        Reads parameters from ``action_serv.server_cfg['params']``, loads the
        vendor DLL, configures the device, primes an async signal queue, and
        starts the :meth:`IOloop` background task.

        Args:
            action_serv: Parent HELAO action server (:class:`Base`) providing
                config, logger, sample-API and file-output integration.
        """
        self.base = action_serv
        self.config_dict = action_serv.server_cfg.get("params", {})
        self.lib_path = self.config_dict["lib_path"]
        self.n_pixels = self.config_dict["n_pixels"]
        self.start_margin = self.config_dict["start_margin"]
        self.dev_num = ctypes.c_short(self.config_dict["dev_num"])
        self._data = (ctypes.c_long * 1056)()  # placeholder
        self.data = []  # result
        self.bad_px = (ctypes.c_short * 1056)()
        # self.wl_cal = self.config_dict["wl_cal"]
        # self.px_cal = self.config_dict["px_cal"]
        # assert len(self.wl_cal) == len(self.px_cal)
        # self.n_cal = len(self.wl_cal)
        if os.path.exists(self.lib_path):
            self.spec = ctypes.CDLL(self.lib_path)
            self.setup_sm303()
            self.spec.spCloseGivenChannel(self.dev_num)
        else:
            LOGGER.error("SMdbUSBm.dll not found.")
            self.spec = None
        self.ready = False
        self.action: Action = None
        self.active: Active = None
        self.trigmode: SpecTrigType = None
        self.edgemode: TriggerType = None
        self.n_avg = 1
        self.fft = 0
        self.int_time = 35
        self.trigger_duration = 0
        self.start_time: float = None
        self.spec_time: float = None
        self.IO_signalq = asyncio.Queue(1)
        self.IO_do_meas: bool = False  # signal flag for intent (start/stop)
        self.IO_measuring: bool = False  # status flag of measurement
        self.event_loop = asyncio.get_event_loop()
        self.event_loop.create_task(self.IOloop())

        self.unified_db = UnifiedSampleDataAPI(self.base)
        asyncio.gather(self.unified_db.init_db())
        self.allow_no_sample = self.config_dict.get("allow_no_sample", False)

        # for saving data localy
        self.FIFO_epoch = None
        self.FIFO_header = {}  # measuement specific, will be reset each measurement
        self.FIFO_column_headings = []
        self.FIFO_name = ""

        # signals return to endpoint after active was created
        self.IO_continue: bool = False
        self.IOloop_run: bool = False

    def set_IO_signalq_nowait(self, val: bool) -> None:
        """Push ``val`` onto the IO signal queue, evicting any stale entry."""
        if self.IO_signalq.full():
            _ = self.IO_signalq.get_nowait()
        self.IO_signalq.put_nowait(val)

    async def set_IO_signalq(self, val: bool) -> None:
        """Async variant of :meth:`set_IO_signalq_nowait`."""
        if self.IO_signalq.full():
            _ = await self.IO_signalq.get()
        await self.IO_signalq.put(val)

    async def IOloop(self):
        """Long-running trigger/acquire/read loop driven by ``IO_signalq``.

        Waits for ``True`` on the signal queue to begin an external-trigger
        acquisition via :meth:`continuous_read`, then finishes the active
        action and resets state. Honours the action server's e-stop.
        """
        self.IOloop_run = True
        try:
            while self.IOloop_run:
                self.IO_do_meas = await self.IO_signalq.get()
                if self.IO_do_meas:
                    # are we in estop?
                    if not self.base.actionservermodel.estop:
                        LOGGER.info("Spec got measurement request")
                        try:
                            await asyncio.wait_for(
                                self.continuous_read(),
                                self.trigger_duration + self.start_margin,
                            )
                            self.spec.spCloseGivenChannel(self.dev_num)
                        except asyncio.exceptions.TimeoutError:
                            pass
                        if self.base.actionservermodel.estop:
                            self.IO_do_meas = False
                            LOGGER.error("Spec is in estop after measurement.")
                        else:
                            LOGGER.info("setting Spec to idle")
                            # await self.stat.set_idle()
                        LOGGER.info("Spec measurement is done")
                    else:
                        self.active.action.action_status.append(HloStatus.estopped)
                        self.IO_do_meas = False
                        LOGGER.error("Spec is in estop.")

                # endpoint can return even we got errors
                self.IO_continue = True

                if self.active is not None:
                    LOGGER.info("Spec finishes active action")
                    # active_not_finished = True
                    # while active_not_finished and self.active is not None:
                    #     try:
                    #         await asyncio.wait_for(self.active.finish(), 1)
                    #         active_not_finished = False
                    #     except asyncio.exceptions.TimeoutError:
                    #         pass
                    await self.active.finish()
                    self.active = None
                    self.action = None
                    self.samples_in = []

        except asyncio.CancelledError:
            # endpoint can return even we got errors
            self.IO_continue = True
            LOGGER.info("IOloop task was cancelled")

    def setup_sm303(self):
        """Run vendor initialisation sequence and load the wavelength table.

        Tests channels, identifies the model, sets up and inits the channel,
        enables the TEC, reads the wavelength table from EEPROM, and sets
        ``self.ready`` to ``True`` on success.
        """
        try:
            self.spec.spTestAllChannels()
            self.model = ctypes.c_short(self.spec.spGetModel(self.dev_num))
            self.spec.spSetupGivenChannel(self.dev_num)
            self.spec.spInitGivenChannel(self.model, self.dev_num)
            self.spec.spSetTEC(ctypes.c_long(1), self.dev_num)
            # self.c_wl_cal = (ctypes.c_double * self.n_cal)()
            # self.c_px_cal = (ctypes.c_double * self.n_cal)()
            # self.c_fitcoeffs = (ctypes.c_double * self.n_cal)()
            # for i, (wl, px) in enumerate(zip(self.wl_cal, self.px_cal)):
            #     self.c_wl_cal[i] = wl / 10
            #     self.c_px_cal[i] = px
            # self.spec.spPolyFit(
            #     ctypes.byref(self.c_px_cal),
            #     ctypes.byref(self.c_wl_cal),
            #     ctypes.c_short(self.n_cal),
            #     ctypes.byref(self.c_fitcoeffs),
            #     ctypes.c_short(3),  # polynomial order
            # )
            # self.c_wl = (ctypes.c_double * self.n_pixels)()
            # for i in range(self.n_pixels):
            #     self.spec.spPolyCalc(
            #         ctypes.byref(self.c_fitcoeffs),
            #         ctypes.c_short(3),  # polynomial order
            #         ctypes.c_double(i + 1),
            #         ctypes.byref(self.c_wl, ctypes.sizeof(ctypes.c_double) * i),
            #     )
            # self.pxwl = [self.c_wl[i] for i in range(self.n_pixels)]
            # self.base.print_message(
            #     f"Calibrated wavelength range: {min(self.pxwl)}, {max(self.pxwl)} over {self.n_pixels} detector pixels."
            # )
            self.wl_saved = (ctypes.c_double * 1024)()
            self.spec.spGetWLTable(ctypes.byref(self.wl_saved), self.dev_num)
            self.pxwl = list(self.wl_saved)
            LOGGER.info(
                f"Loaded wavelength range from EEPROM: {min(self.pxwl)}, {max(self.pxwl)} over {self.n_pixels} detector pixels."
            )
            self.ready = True
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            LOGGER.error(f"fatal error initializing SM303: {repr(e), tb,}")

    def set_trigger_mode(self, mode: SpecTrigType = SpecTrigType.off) -> bool:
        """Set the spectrometer trigger source.

        Args:
            mode: Target :class:`SpecTrigType` (off, internal or external).

        Returns:
            ``True`` if the DLL reported success, ``False`` otherwise.
        """
        resp = self.spec.spSetTrgEx(mode, self.dev_num)
        time.sleep(0.1)
        if resp == 1:
            LOGGER.info(f"Successfully set trigger mode to {str(mode)}")
            self.trigmode = mode
            return True
        LOGGER.error(f"Could not set trigger mode to {str(mode)}")
        return False

    def set_extedge_mode(self, mode: TriggerType = TriggerType.risingedge) -> bool:
        """Set the external-trigger edge polarity.

        Args:
            mode: :class:`TriggerType` indicating rising/falling edge.

        Returns:
            ``True`` if the DLL reported success, ``False`` otherwise.
        """
        cedge_mode = ctypes.c_short(mode)
        resp = self.spec.spSetExtEdgeMode(cedge_mode, self.dev_num)
        time.sleep(0.1)
        if resp == 1:
            LOGGER.info(f"Successfully set ext. trigger edge mode to {str(mode)}")
            self.edgemode = mode
            return True
        LOGGER.error(f"Could not set ext. trigger edge mode to {str(mode)}")
        return False

    def set_integration_time(self, int_time: float = 7.0) -> bool:
        """Set the integration time in milliseconds (minimum 7.0 ms).

        Args:
            int_time: Integration time in milliseconds.

        Returns:
            ``True`` if the DLL reported success, ``False`` otherwise.
        """
        # minimum int_time for SM303 is 7.0 msec
        self.int_time = float(int_time)
        cint_time = ctypes.c_double(int_time)
        resp = self.spec.spSetDblIntEx(cint_time, self.dev_num)
        time.sleep(0.1)
        if resp == 1:
            LOGGER.info(f"Successfully set integration time to {int_time:.1f} msec")
            self.int_time = cint_time
            return True
        LOGGER.error(f"Could not set integration time to {int_time:.1f}")
        return False

    def acquire_spec_adv(self, int_time_ms: float, **kwargs) -> dict:
        """Acquire a single spectrum using software triggering.

        Configures trigger off mode, advanced integration mode and the
        requested integration time, then reads a spectrum and returns a flat
        dict of per-channel intensities plus optional peak intensity within
        ``peak_lower_wl``/``peak_upper_wl`` bounds.

        Args:
            int_time_ms: Integration time in milliseconds.
            **kwargs: Optional ``n_avg``, ``fft``, ``peak_lower_wl`` and
                ``peak_upper_wl`` parameters.

        Returns:
            Dict with ``epoch_s``, ``ch_NNNN`` channel values, ``error_code``
            and ``peak_intensity`` on success; an error dict otherwise.
        """
        # self.setup_sm303()
        trigset = self.set_trigger_mode(SpecTrigType.off)
        intmset = self.spec.spSetIntMode(
            ctypes.c_short(2), ctypes.c_double(float(int_time_ms)), self.dev_num
        )
        inttset = self.set_integration_time(int_time_ms)
        if trigset and inttset and intmset:
            self.n_avg = kwargs.get("n_avg", 1)
            self.fft = kwargs.get("fft", 0)
            result = self.read_data()
            if result == 1:
                # self.data = [self._data[i] for i in range(1056)][10:1034]
                retdict: dict[str, float | ErrorCodes] = {"epoch_s": time.time()}
                retdict.update({f"ch_{i:04}": x for i, x in enumerate(self.data)})
                retdict["error_code"] = ErrorCodes.none
                arr_data = np.array(self.data)
                lower_lim = (
                    0
                    if kwargs.get("peak_lower_wl") is None
                    else min(
                        [
                            i
                            for i, v in enumerate(self.pxwl)
                            if v >= kwargs.get("peak_lower_wl")
                        ]
                    )
                )
                upper_lim = (
                    len(self.pxwl) - 1
                    if kwargs.get("peak_upper_wl") is None
                    else max(
                        [
                            i
                            for i, v in enumerate(self.pxwl)
                            if v <= kwargs.get("peak_upper_wl")
                        ]
                    )
                )
                retdict["peak_intensity"] = int(arr_data[lower_lim:upper_lim].max())
                return retdict
            else:
                LOGGER.info("No data available.")
                return {"error_code": ErrorCodes.not_available}
        LOGGER.info("Trigger or integration time could not be set.")
        return {"error_code": ErrorCodes.not_available}

    async def acquire_spec_extrig(self, A: Action) -> dict:
        """Start an externally triggered acquisition and return the active dict.

        Configures external trigger mode, edge mode and integration time from
        the action params, validates samples, opens a HELAO ``Active`` with a
        ``spec_helao__file`` connection (wavelength table in the header),
        then signals :meth:`IOloop` to begin collecting and waits until the
        active object has been activated.

        Args:
            A: The :class:`Action` request describing this acquisition.

        Returns:
            The active action's ``as_dict()`` payload.
        """

        # self.setup_sm303()
        params = A.action_params
        self.n_avg = params["n_avg"]
        self.fft = params["fft"]
        self.trigger_duration = params["duration"]
        trigset = self.set_trigger_mode(SpecTrigType.external)
        edgeset = self.set_extedge_mode(params["edge_mode"])
        inttset = self.set_integration_time(params["int_time"])
        # TODO: can perform more checks like gamry technique wrapper...
        if trigset and edgeset and inttset:
            A.error_code = ErrorCodes.none
            # validate samples_in
            samples_in = await self.unified_db.get_samples(A.samples_in)
            if not samples_in and not self.allow_no_sample:
                LOGGER.error(
                    "Spec server got no valid sample, cannot start measurement!",
                )
                A.samples_in = []
                A.error_code = ErrorCodes.no_sample
                activeDict = A.as_dict()
            else:
                self.samples_in = samples_in
                self.action = A
                # LOGGER.info("Writing initial spec_helao__file")
                spec_header = {"wl": self.pxwl}
                dflt_conn_key = self.base.dflt_file_conn_key()
                self.active = await self.base.contain_action(
                    ActiveParams(
                        action=self.action,
                        file_conn_params_dict={
                            dflt_conn_key: FileConnParams(
                                file_conn_key=dflt_conn_key,
                                sample_global_labels=[
                                    sample.get_global_label() for sample in samples_in
                                ],
                                file_type="spec_helao__file",
                                hloheader=HloHeaderModel(optional=spec_header),
                            )
                        },
                    )
                )
                for sample in samples_in:
                    sample.status = [SampleStatus.preserved]
                    sample.inheritance = SampleInheritance.allow_both

                self.active.action.samples_in = []
                # now add updated samples to sample_in again
                await self.active.append_sample(
                    samples=[sample_in for sample_in in self.samples_in], IO="in"
                )

                self.start_time = time.time()
                LOGGER.info(f"start_time: {self.start_time}")
                self.spec_time = time.time()
                LOGGER.info(f"spec_time: {self.spec_time}")
                self.active.finish_hlo_header(
                    realtime=self.base.get_realtime_nowait(),
                    file_conn_keys=self.active.action.file_conn_keys,
                )
                # signal the IOloop to start the measrurement
                await self.set_IO_signalq(True)

                # need to wait now for the activation of the meas routine
                # and that the active object is activated and sets action status
                while not self.IO_continue:
                    await asyncio.sleep(1)

                # reset continue flag
                self.IO_continue = False

                activeDict = self.active.action.as_dict()
        else:
            LOGGER.error(
                f"Could not trigger_mode ('SpecTrigType.external'), edge_mode ({params['edge_mode']}), int_time ({params['int_time']}), or trigger_duration ({params['duration']}).",
            )
            A.error_code = ErrorCodes.critical_error
            activeDict = A.as_dict()
        return activeDict

    def read_data(self) -> int:
        """Read a single spectrum from the device into ``self.data``.

        Uses ``spReadDataAdvEx`` when averaging or FFT is enabled, else the
        plain ``spReadDataEx``. Trims the raw 1056-element buffer to the
        1024 active pixels.

        Returns:
            The vendor result code (``1`` on success).
        """
        self._data = (ctypes.c_long * 1056)()
        if self.n_avg != 1 or self.fft != 0:
            result = self.spec.spReadDataAdvEx(
                ctypes.byref(self._data),
                ctypes.c_short(self.n_avg),
                ctypes.c_short(self.fft),
                ctypes.c_short(0),
                ctypes.byref(self.bad_px),
                self.dev_num,
            )
        else:
            result = self.spec.spReadDataEx(
                ctypes.byref(self._data),
                self.dev_num,
            )
        if result == 1:
            self.data = list(self._data)[10:1034]
        else:
            self.data = []
        return result

    async def continuous_read(self) -> dict:
        """Background polling coroutine for external-trigger acquisitions.

        Repeatedly calls :meth:`read_data` (via ``run_in_executor`` so that
        the DLL call's GIL release does not break async ordering), enqueues
        each spectrum onto the active action's data stream, and stops once
        ``trigger_duration + start_margin`` has elapsed.

        ``start_margin`` extends the trigger acquisition window to account
        for the time delay between the spec and pstat actions.

        Returns:
            ``{"measure": "done_extrig"}`` on normal completion or
            ``{"measure": "not initialized"}`` if the DLL was never loaded.
        """
        # first_print = True
        await asyncio.sleep(0.01)

        if self.spec is None:
            self.IO_measuring = False
            return {"measure": "not initialized"}

        else:
            # active object is set so we can set the continue flag
            self.IO_continue = True

        while self.IO_do_meas and (self.spec_time - self.start_time) < (
            self.trigger_duration + self.start_margin
        ):
            # if first_print:
            #     self.base.print_message(
            #         f"entering polling loop for {self.trigger_duration:.1f} seconds"
            #     )

            # VERY IMPORTANT! ctypes dll function calls release the GIL which interrupts
            # the synchronization of HELAO's async coroutines, so we wrap the dll call
            # with run_in_executor to force awaitable execution order in the while loop
            try:
                await self.event_loop.run_in_executor(None, self.read_data)
            except asyncio.exceptions.TimeoutError:
                self.data = []
            # if first_print:
            # LOGGER.info(f"spReadDataAdvEx was called")
            if self.data:
                self.data = [self._data[i] for i in range(1056)][10:1034]
                # enqueue data
                datadict = {"epoch_s": self.spec_time}
                datadict.update({f"ch_{i:04}": x for i, x in enumerate(self.data)})
                # if first_print:
                #     LOGGER.info("writing initial data")
                await self.active.enqueue_data(
                    datamodel=DataModel(
                        data={self.active.action.file_conn_keys[0]: datadict},
                        errors=[],
                        status=HloStatus.active,
                    )
                )
                self.data = []
            await asyncio.sleep(0.01)
            self.spec_time = time.time()
            # first_print = False

        LOGGER.info("polling loop duration complete, finishing")
        self.trigger_duration = 0
        self.close_spec_connection()
        return {"measure": "done_extrig"}

    def close_spec_connection(self):
        """Disable external trigger and signal the IO loop to stop."""
        if self.IO_measuring:
            self.IO_do_meas = False  # will stop meas loop
            self.IO_measuring = False
            self.unset_external_trigger()
            LOGGER.info("signaling IOloop to stop")
            self.set_IO_signalq_nowait(False)
        else:
            pass

    async def stop(self, delay: int = 0):
        """Stop the measurement, write all data and exit the meas loop.

        Args:
            delay: Optional seconds to wait before signalling stop.
        """
        if self.IO_measuring:
            await asyncio.sleep(delay=delay)
            self.IO_do_meas = False  # will stop meas loop
            await self.set_IO_signalq(False)

    async def estop(self, switch: bool, *args, **kwargs) -> bool:
        """Set or clear the e-stop flag, stopping the meas loop when set.

        Args:
            switch: ``True`` to engage e-stop, ``False`` to clear it.

        Returns:
            The applied boolean state.
        """
        # should be the same as stop()
        switch = bool(switch)
        self.base.actionservermodel.estop = switch
        if self.IO_measuring:
            if switch:
                self.IO_do_meas = False  # will stop meas loop
                await self.set_IO_signalq(False)
                if self.active:
                    # add estop status to active.status
                    self.active.set_estop()
        return switch

    def unset_external_trigger(self):
        """Disable the external trigger (sets ``SP_TRIGGER_OFF``)."""
        self.spec.spSetTrgEx(ctypes.c_short(10), self.dev_num)  # 10=SP_TRIGGER_OFF

    def shutdown(self) -> dict:
        """Close the spectrometer channel and return a shutdown marker."""
        LOGGER.info("shutting down SM303")
        # self.unset_external_trigger()
        # self.spec.spSetTEC(ctypes.c_long(0), self.dev_num)
        self.spec.spCloseGivenChannel(self.dev_num)
        return {"shutdown"}
