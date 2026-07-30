"""Spectral Products SM303 spectrometer driver.

Wraps the vendor-supplied ``SMdbUSBm.dll`` to operate the SM303 spectrometer
in software- or externally-triggered acquisition modes. The :class:`SM303`
driver owns only the device I/O; the action lifecycle (sample validation,
``Active``/file-connection bookkeeping, and the externally-triggered
collect loop) lives in ``spec_server.py``'s ``SM303Exec``
(:class:`helao.helpers.executor.Executor`).
"""

__all__ = ["SM303"]

import asyncio
import ctypes
import os
import time
import traceback

import numpy as np

from helao.core.drivers.helao_driver import (
    DriverResponse,
    DriverResponseType,
    DriverStatus,
    HelaoDriver,
)
from helao.core.error import ErrorCodes
from helao.helpers import helao_logging as logging

from ...drivers.io.enum import TriggerType
from ...drivers.spec.enum import SpecTrigType

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class SM303(HelaoDriver):
    """Driver for the Spectral Products SM303 USB spectrometer.

    Loads the vendor ``SMdbUSBm.dll`` (path from ``config``) and configures
    the device (TEC, wavelength table) in :meth:`connect`. Provides
    synchronous single-shot acquisition (:meth:`acquire_spec_adv`) and the
    plain device-configuration primitives (:meth:`set_trigger_mode`,
    :meth:`set_extedge_mode`, :meth:`set_integration_time`,
    :meth:`read_data`) used by ``spec_server.py``'s ``SM303Exec`` to drive
    externally-triggered acquisition.
    """

    def __init__(self, config: dict = {}):
        """Store config; no device I/O here (see :meth:`connect`).

        Args:
            config: Driver configuration (the server's ``params`` dict).
        """
        super().__init__(config=config)
        self.config_dict = self.config
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

        # device connection state -- populated by connect()/setup_sm303(), not here
        self.spec = None
        self.ready = False
        self.model = None
        self.pxwl = []
        self.wl_saved = None

        self.trigmode: SpecTrigType = None
        self.edgemode: TriggerType = None
        self.n_avg = 1
        self.fft = 0
        self.int_time = 35
        self.trigger_duration = 0
        self.start_time: float = None
        self.spec_time: float = None

        self.allow_no_sample = self.config_dict.get("allow_no_sample", False)

        # for saving data localy
        self.FIFO_epoch = None
        self.FIFO_header = {}  # measuement specific, will be reset each measurement
        self.FIFO_column_headings = []
        self.FIFO_name = ""

    def connect(self) -> DriverResponse:
        """Load the vendor DLL and run the SM303 setup sequence.

        Returns:
            ``DriverResponse`` reporting connection success or failure.
        """
        if not os.path.exists(self.lib_path):
            LOGGER.error("SMdbUSBm.dll not found.")
            self.spec = None
            return DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.uninitialized
            )
        try:
            self.spec = ctypes.CDLL(self.lib_path)
            self.setup_sm303()
            self.spec.spCloseGivenChannel(self.dev_num)
            return DriverResponse(
                response=DriverResponseType.success,
                status=DriverStatus.ok if self.ready else DriverStatus.error,
            )
        except Exception:
            LOGGER.error("SM303 connect failed", exc_info=True)
            self.spec = None
            return DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )

    def get_status(self) -> DriverResponse:
        """Return whether :meth:`connect` has completed successfully.

        Returns:
            ``DriverResponse`` with ``status=ok`` if ready, else
            ``status=uninitialized``.
        """
        if self.ready and self.spec is not None:
            return DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        return DriverResponse(
            response=DriverResponseType.success, status=DriverStatus.uninitialized
        )

    def stop(self) -> DriverResponse:
        """Immediately disable the external trigger (ABC-required zero-arg stop).

        Distinct from the legacy delayed ``stop(delay=0)``, which is now
        :meth:`stop_acquisition`.
        """
        if self.spec is not None:
            self.unset_external_trigger()
        return DriverResponse(
            response=DriverResponseType.success, status=DriverStatus.ok
        )

    def reset(self) -> DriverResponse:
        """Force-close and reopen the spectrometer connection."""
        self.disconnect()
        return self.connect()

    def disconnect(self) -> DriverResponse:
        """Close the spectrometer channel.

        Returns:
            ``DriverResponse`` reporting close success or failure.
        """
        try:
            if self.spec is not None:
                self.spec.spCloseGivenChannel(self.dev_num)
            return DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            LOGGER.error("SM303 disconnect failed", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )

    async def async_shutdown(self) -> DriverResponse:
        """Close the spectrometer channel on server shutdown (sync ``shutdown`` is omitted)."""
        return self.disconnect()

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
            # LOGGER.info(
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

    def unset_external_trigger(self):
        """Disable the external trigger (sets ``SP_TRIGGER_OFF``)."""
        self.spec.spSetTrgEx(ctypes.c_short(10), self.dev_num)  # 10=SP_TRIGGER_OFF

    async def stop_acquisition(self, delay: int = 0) -> DriverResponse:
        """Wait ``delay`` seconds, then disable the external trigger.

        Renamed from the legacy ``stop(delay=0)`` (the ABC's zero-arg
        ``stop()`` is a distinct immediate abort). Does not itself terminate
        an in-progress ``SM303Exec`` poll loop -- callers (see
        ``spec_server.py``'s ``stop_extrig_after``) are responsible for that
        via the action-server framework's executor-stop primitive.

        Args:
            delay: Optional seconds to wait before disabling the trigger.

        Returns:
            ``DriverResponse`` reporting the trigger was disabled.
        """
        await asyncio.sleep(delay)
        if self.spec is not None:
            self.unset_external_trigger()
        return DriverResponse(
            response=DriverResponseType.success, status=DriverStatus.ok
        )

    async def estop(self, switch: bool, *args, **kwargs) -> bool:
        """Device-level e-stop hook: disable the external trigger when engaged.

        Server-side estop-flag bookkeeping (``actionservermodel.estop``) and
        terminating/finalizing in-flight actions are owned by the action-server
        framework (``base_api.py``'s ``/estop`` endpoint), not the driver.

        Args:
            switch: ``True`` to engage e-stop, ``False`` to clear it.

        Returns:
            The applied boolean state.
        """
        switch = bool(switch)
        if switch and self.spec is not None:
            self.unset_external_trigger()
        return switch
