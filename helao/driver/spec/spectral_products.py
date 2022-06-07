__all__ = ["SM303"]

import os
import ctypes
import asyncio

from helaocore.schema import Action
from helaocore.error import ErrorCodes
from helaocore.model.data import DataModel
from helaocore.model.file import FileConnParams, HloHeaderModel
from helaocore.model.active import ActiveParams
from helaocore.model.hlostatus import HloStatus
from helaocore.data.sample import UnifiedSampleDataAPI
from helaocore.model.sample import SampleInheritance, SampleStatus
from helaocore.server.base import Base
from helao.driver.io.enum import TriggerType
from helao.driver.spec.enum import SpecTrigType


class SM303:
    """_summary_"""

    def __init__(self, action_serv: Base):
        self.base = action_serv
        self.config_dict = action_serv.server_cfg["params"]
        self.lib_path = self.config_dict["lib_path"]
        self.n_pixels = self.config_dict["n_pixels"]
        self.dev_num = ctypes.c_short(self.config_dict["dev_num"])
        self._data = (ctypes.c_long * 1056)()  # placeholder
        self.data = []  # result
        self.bad_px = (ctypes.c_short * 1056)()
        self.wl_cal = self.config_dict["wl_cal"]
        self.px_cal = self.config_dict["px_cal"]
        assert len(self.wl_cal) == len(self.px_cal)
        self.n_cal = len(self.wl_cal)
        if os.path.exists(self.lib_path):
            self.spec = ctypes.CDLL(self.lib_path)
            self.setup_sm303()
        else:
            self.base.print_message("SMdbUSBm.dll not found.", error=True)
            self.spec = None
        self.active = None
        self.trigmode = None
        self.edgemode = None
        self.polling_task = None
        self.polling = False

        self.unified_db = UnifiedSampleDataAPI(self.base)
        asyncio.gather(self.unified_db.init_db())
        self.allow_no_sample = self.config_dict.get("allow_no_sample", False)

    def setup_sm303(self):
        self.model = ctypes.c_short(self.spec.spGetModel())
        self.spec.spTestAllChannels()
        self.spec.spSetupGivenChannel(self.dev_num)
        self.spec.spInitGivenChannel(self.model, self.dev_num)
        self.spec.spSetTEC(ctypes.c_long(1), self.dev_num)
        self.c_wl_cal = (ctypes.c_double * self.n_cal)()
        self.c_px_cal = (ctypes.c_double * self.n_cal)()
        self.c_fitcoeffs = (ctypes.c_double * self.n_cal)()
        for i, (wl, px) in enumerate(zip(self.wl_cal, self.px_cal)):
            self.c_wl_cal[i] = wl / 10
            self.c_px_cal[i] = px
        self.spec.spPolyFit(
            ctypes.byref(self.c_px_cal),
            ctypes.byref(self.c_wl_cal),
            ctypes.c_short(self.n_cal),
            ctypes.byref(self.c_fitcoeffs),
            ctypes.c_short(3),  # polynomial order
        )
        self.c_wl = (ctypes.c_double * self.n_pixels)()
        for i in range(self.n_pixels):
            self.spec.spPolyCalc(
                ctypes.byref(self.c_fitcoeffs),
                ctypes.c_short(3),  # polynomial order
                ctypes.c_double(i + 1),
                ctypes.byref(self.c_wl, ctypes.sizeof(ctypes.c_double) * i),
            )
        self.pxwl = [self.c_wl[i] for i in range(self.n_pixels)]
        self.base.print_message(
            f"Calibrated wavelength range: {min(self.pxwl)}, {max(self.pxwl)} over {self.n_pixels} detector pixels."
        )
        self.wl_saved = (ctypes.c_double * 1024)()
        self.spec.spGetWLTable(ctypes.byref(self.wl_saved), self.dev_num)

    def set_trigger_mode(self, mode: SpecTrigType = SpecTrigType.off):
        resp = self.spec.spSetTrigEx(mode, self.dev_num)
        if resp == 1:
            self.base.print_message(f"Successfully set trigger mode to {str(mode)}")
            self.trigmode = mode
            return True
        self.base.print_message(
            f"Could not set trigger mode to {str(mode)}", error=True
        )
        return False

    def set_extedge_mode(self, mode: TriggerType = TriggerType.risingedge):
        cedge_mode = ctypes.short(mode)
        resp = self.spec.spExtEdgeMode(cedge_mode, self.dev_num)
        if resp == 1:
            self.base.print_message(
                f"Successfully set ext. trigger edge mode to {str(mode)}"
            )
            self.edgemode = mode
            return True
        self.base.print_message(
            f"Could not set ext. trigger edge mode to {str(mode)}", error=True
        )
        return False

    def set_integration_time(self, int_time: float = 7.0):
        # minimum int_time for SM303 is 7.0 msec
        cint_time = ctypes.c_double(int_time)
        resp = self.spec.spSetDblIntEx(cint_time, self.dev_num)
        if resp == 1:
            self.base.print_message(
                f"Successfully set integration time to {int_time:.1f} msec"
            )
            self.int_time = cint_time
            return True
        self.base.print_message(
            f"Could not set integration time to {int_time:.1f}", error=True
        )
        return False

    def acquire_spec_adv(self, int_time: float, **kwargs):
        trigset = self.set_trigger_mode(SpecTrigType.off)
        inttset = self.set_integration_time(int_time)
        if trigset and inttset:
            if "n_avg" in kwargs or "fft" in kwargs:
                _n_avg = kwargs.get("n_avg", 1)
                _fft = kwargs.get("fft", 0)
                result = self.spec.spReadDataAdvEx(
                    ctypes.byref(self._data),
                    ctypes.c_short(_n_avg),
                    ctypes.c_short(_fft),
                    ctypes.c_short(0),
                    ctypes.byref(self.bad_px),
                    self.dev_num,
                )
            else:
                result = self.spec.spReadDataEx(ctypes.byref(self._data), self.dev_num)
            if result == 1:
                self.data = [self._data[i] for i in range(1056)][10:1034]
                retdict = {"epoch_ns": self.base.get_realtime_nowait()}
                retdict.update({f'ch_{i:04}': x for i,x in enumerate(self.data)})
                retdict["error_code"] = ErrorCodes.none
                return retdict
            else:
                self.base.print_message(f"No data available.", info=True)
                return {"error_code": ErrorCodes.not_available}
        self.base.print_message(
            f"Trigger or integration time could not be set.", info=True
        )
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

        params = A.action_params

        trigset = self.set_trigger_mode(SpecTrigType.external)
        edgeset = self.set_extedge_mode(params["edge_mode"])
        inttset = self.set_integration_time(params["int_time"])

        if trigset and edgeset and inttset:
            myloop = asyncio.get_event_loop()
            A.error_code = ErrorCodes.none
            # validate samples_in
            samples_in = await self.unified_db.get_samples(A.samples_in)
            if not samples_in and not self.allow_no_sample:
                self.base.print_message(
                    "Gamry got no valid sample, cannot start measurement!", error=True
                )
                A.samples_in = []
                A.error_code = ErrorCodes.no_sample

            for sample in samples_in:
                sample.status = [SampleStatus.preserved]
                sample.inheritance = SampleInheritance.allow_both

            # TODO: can perform more checks like gamry technique wrapper...

            # setup active
            if A.error_code is ErrorCodes.none:
                spec_header = {"wl": self.pxwl}
                self.active = await self.base.contain_action(
                    ActiveParams(
                        action=A,
                        file_conn_params_dict={
                            self.base.dflt_file_conn_key(): FileConnParams(
                                file_conn_key=self.base.dflt_file_conn_key(),
                                sample_global_labels=[
                                    sample.get_global_label() for sample in samples_in
                                ],
                                file_type="spec_helao__file",
                                hloheader=HloHeaderModel(optional=spec_header),
                            )
                        },
                    )
                )
            if self.active is not None:
                # start polling task
                self.polling_task = myloop.create_task(
                    self.continuous_read(
                        params["n_avg"], params["fft"], params["duration"]
                    )
                )
                return self.active.action.as_dict()
            else:
                return A.as_dict()
        else:
            self.base.print_message(
                "Could not set trigger, edge mode, or integration time.", error=True
            )
            A.error_code = ErrorCodes.critical
            return A.as_dict()

    async def continuous_read(self, n_avg: int = 1, fft: int = 0, duration: float = -1):
        """Async polling task."""
        self.polling = True
        start_time = self.base.get_realtime_nowait()
        spec_time = self.base.get_realtime_nowait()
        while self.polling and (spec_time - start_time)/1e9 < duration:
            result = self.spec.spReadDataAdvEx(
                ctypes.byref(self._data),
                ctypes.c_short(n_avg),
                ctypes.c_short(fft),
                ctypes.c_short(0),
                ctypes.byref(self.bad_px),
                self.dev_num,
            )
            if result == 1:
                self.data = [self._data[i] for i in range(1056)][10:1034]
                # enqueue data
                spec_time = self.base.get_realtime_nowait()
                datadict = {'epoch_ns': spec_time}
                datadict.update({f'ch_{i:04}': x for i,x in enumerate(self.data)})
                await self.active.enqueue_data(datamodel=DataModel(data=datadict, errors=[], status=HloStatus.active))
            await asyncio.sleep(0.001)
        await self.active.finish()
        self.active = None
        self.polling_task = None
        self.polling = False
    
    async def stop_continuous_read(self):
        """Stop async polling task."""
        if self.polling_task is not None:
            await self.polling_task.cancel()
            await self.active.finish()
            self.active = None
            self.polling_task = None
            self.polling = False

    def unset_external_trigger(self):
        self.spec.spSetTrgEx(ctypes.c_short(10), self.dev_num)  # 10=SP_TRIGGER_OFF

    def shutdown(self):
        self.base.print_message("shutting down SM303")
        self.unset_external_trigger()
        self.spec.spSetTEC(ctypes.c_long(0), self.dev_num)
        self.spec.spCloseGivenChannel(self.dev_num)
        return {"shutdown"}
