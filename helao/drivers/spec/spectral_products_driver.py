__all__ = ["SM303"]

import os
import time
import ctypes
import asyncio
import traceback

import numpy as np

from helao.helpers import logging
if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER
from helao.core.error import ErrorCodes
from helao.core.models.data import DataModel
from helao.core.models.file import FileConnParams, HloHeaderModel
from helao.core.models.sample import SampleInheritance, SampleStatus
from helao.core.models.hlostatus import HloStatus
from helao.helpers.premodels import Action
from helao.helpers.active_params import ActiveParams
from helao.helpers.sample_api import UnifiedSampleDataAPI
from helao.servers.base import Base
from helao.drivers.io.enum import TriggerType
from helao.drivers.spec.enum import SpecTrigType


class SM303:
    """_summary_"""

    def __init__(self, action_serv: Base):
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
        self.action = None
        self.active = None
        self.trigmode = None
        self.edgemode = None
        self.n_avg = 1
        self.fft = 0
        self.int_time = 35
        self.trigger_duration = 0
        self.start_time = None
        self.spec_time = None
        self.IO_signalq = asyncio.Queue(1)
        self.IO_do_meas = False  # signal flag for intent (start/stop)
        self.IO_measuring = False  # status flag of measurement
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
        self.IO_continue = False
        self.IOloop_run = False

    def set_IO_signalq_nowait(self, val: bool) -> None:
        if self.IO_signalq.full():
            _ = self.IO_signalq.get_nowait()
        self.IO_signalq.put_nowait(val)

    async def set_IO_signalq(self, val: bool) -> None:
        if self.IO_signalq.full():
            _ = await self.IO_signalq.get()
        await self.IO_signalq.put(val)

    async def IOloop(self):
        """This is trigger-acquire-read loop which always runs."""
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
            LOGGER.info(f"Loaded wavelength range from EEPROM: {min(self.pxwl)}, {max(self.pxwl)} over {self.n_pixels} detector pixels.")
            self.ready = True
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            LOGGER.error(f"fatal error initializing SM303: {repr(e), tb,}")

    def set_trigger_mode(self, mode: SpecTrigType = SpecTrigType.off):
        resp = self.spec.spSetTrgEx(mode, self.dev_num)
        time.sleep(0.1)
        if resp == 1:
            LOGGER.info(f"Successfully set trigger mode to {str(mode)}")
            self.trigmode = mode
            return True
        LOGGER.error(f"Could not set trigger mode to {str(mode)}")
        return False

    def set_extedge_mode(self, mode: TriggerType = TriggerType.risingedge):
        cedge_mode = ctypes.c_short(mode)
        resp = self.spec.spSetExtEdgeMode(cedge_mode, self.dev_num)
        time.sleep(0.1)
        if resp == 1:
            LOGGER.info(f"Successfully set ext. trigger edge mode to {str(mode)}")
            self.edgemode = mode
            return True
        LOGGER.error(f"Could not set ext. trigger edge mode to {str(mode)}")
        return False

    def set_integration_time(self, int_time: float = 7.0):
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

    def acquire_spec_adv(self, int_time_ms: float, **kwargs):
        self.setup_sm303()
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
                retdict = {"epoch_s": time.time()}
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
                retdict["peak_intensity"] = float(arr_data[lower_lim:upper_lim].max())
                return retdict
            else:
                LOGGER.info("No data available.")
                return {"error_code": ErrorCodes.not_available}
        LOGGER.info("Trigger or integration time could not be set.")
        return {"error_code": ErrorCodes.not_available}

    async def acquire_spec_extrig(self, A: Action):
        """Perform async acquisition based on external trigger.

        Notes:
            SM303 has max 'waiting time' of 7ms, ADC time of 4ms, min USB tx
            time of 2ms in addition to the min integration time of 7ms.

            Trigger signal time must be at least 13ms.
            Galil IO appears to have 1ms toggle resolutionself.

            TODO: setup external trigger mode and integration time,
            SPEC server should switch over to usb context and listen for data,
            Galil IO or PSTAT should send SPEC server a finish signal

        Return active dict.
        """

        self.setup_sm303()
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
                self.base.print_message(
                    "Spec server got no valid sample, cannot start measurement!",
                    error=True,
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
            self.base.print_message(
                f"Could not trigger_mode ('SpecTrigType.external'), edge_mode ({params['edge_mode']}), int_time ({params['int_time']}), or trigger_duration ({params['duration']}).",
                error=True,
            )
            A.error_code = ErrorCodes.critical
            activeDict = A.as_dict()
        return activeDict

    def read_data(self):
        self._data = (ctypes.c_long * 1056)()
        if self.n_avg != 1 and self.fft != 0:
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

    async def continuous_read(self):
        """Async polling task.

        'start_margin' is the number of seconds to extend the trigger acquisition window
        to account for the time delay between SPEC and PSTAT actions
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
        if self.IO_measuring:
            self.IO_do_meas = False  # will stop meas loop
            self.IO_measuring = False
            self.unset_external_trigger()
            LOGGER.info("signaling IOloop to stop")
            self.set_IO_signalq_nowait(False)
        else:
            pass

    async def stop(self, delay: int = 0):
        """stops measurement, writes all data and returns from meas loop"""
        if self.IO_measuring:
            await asyncio.sleep(delay=delay)
            self.IO_do_meas = False  # will stop meas loop
            await self.set_IO_signalq(False)

    async def estop(self, switch: bool, *args, **kwargs):
        """same as stop, set or clear estop flag with switch parameter"""
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
        self.spec.spSetTrgEx(ctypes.c_short(10), self.dev_num)  # 10=SP_TRIGGER_OFF

    def shutdown(self):
        LOGGER.info("shutting down SM303")
        # self.unset_external_trigger()
        # self.spec.spSetTEC(ctypes.c_long(0), self.dev_num)
        self.spec.spCloseGivenChannel(self.dev_num)
        return {"shutdown"}
