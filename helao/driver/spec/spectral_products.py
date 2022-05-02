__all__ = ["SM303"]

import os
import ctypes

from helaocore.server.base import Base
from helao.driver.io.enum import TriggerType


class SM303:
    """_summary_"""

    def __init__(self, action_serv: Base):
        self.base = action_serv
        self.config_dict = action_serv.server_cfg["params"]
        self.lib_path = self.config_dict["lib_path"]
        self.n_pixels = self.config_dict["n_pixels"]
        self.dev_num = ctypes.c_short(self.config_dict["dev_num"])
        self.data = (ctypes.c_long * 1056)()
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

    def measure_spec(self, int_time: float):
        # minimum int_time for SM303 is 7.0 msec
        self.int_time = ctypes.c_double(int_time)
        self.spec.spSetTrgEx(10, self.dev_num)
        self.spec.spSetDblIntEx(self.int_time, self.dev_num)
        self.spec.spReadDataEx(ctypes.byref(self.data), self.dev_num)
        data = [self.data[i] for i in range(1056)]
        data = data[10:1034]
        return data

    def measure_spec_adv(self, int_time: float, n_avg: int = 1, fft: int = 0):
        # minimum int_time for SM303 is 7.0 msec
        self.int_time = ctypes.c_double(int_time)
        self.spec.spSetTrgEx(10, self.dev_num)
        self.spec.spSetDblIntEx(self.int_time, self.dev_num)
        self.spec.spReadDataAdvEx(
            ctypes.byref(self.data),
            ctypes.c_short(n_avg),
            ctypes.c_short(fft),
            ctypes.c_short(0),
            ctypes.byref(self.bad_px),
            self.dev_num,
        )
        data = [self.data[i] for i in range(1056)]
        data = data[10:1034]
        return data

    def set_external_trigger(self, edge_mode: TriggerType = TriggerType.fallingedge):
        """Set external trigger mode.

        Notes:
            SM303 has max 'waiting time' of 7ms, ADC time of 4ms, min USB tx
            time of 2ms in addition to the min integration time of 7ms. 

            Trigger signal time must be at least 13ms.
            Galil IO appears to have 1ms toggle resolutionself.

            TODO: setup external trigger mode and integration time,
            SPEC server should switch over to usb context and listen for data,
            Galil IO or PSTAT should send SPEC server a finish signal

        """
        if edge_mode == TriggerType.fallingedge:
            trigger = ctypes.c_short(0)
        elif edge_mode == TriggerType.risingedge:
            trigger = ctypes.c_short(1)
        self.spec.spSetExtEdgeMode(trigger, self.dev_num)
        self.spec.spSetTrgEx(ctypes.c_short(12), self.dev_num)  # 12=SP_TRIGGER_EXTERNAL

    def unset_external_trigger(self):
        self.spec.spSetTrgEx(ctypes.c_short(10), self.dev_num)  # 10=SP_TRIGGER_OFF

    def shutdown(self):
        self.base.print_message("shutting down SM303")
        self.unset_external_trigger()
        self.spec.spSetTEC(ctypes.c_long(0), self.dev_num)
        self.spec.spCloseGivenChannel(self.dev_num)
        return {"shutdown"}
