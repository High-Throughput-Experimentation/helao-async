"""adjust_ND applies the 1-based filter whose 0-based optimality index won."""

import numpy as np

from helao.deploy.hte.drivers.spec.andor import spectrograph as sg


class _FakeSpc:
    ATSPECTROGRAPH_SUCCESS = 20202
    filters = []

    def __init__(self):
        self.__class__.filters = []

    def __getattr__(self, name):
        if name == "SetFilter":
            return lambda dev, n: self.filters.append(n)
        if name == "IsFilterPresent":
            return lambda dev: (20202, 1)
        if name == "Initialize":
            return lambda *a: 20202
        if name in ("GetGrating", "GetWavelength"):
            return lambda *a: (20202, 1)
        if name == "GetWavelengthLimits":
            return lambda *a: (20202, 1, 2)
        if name == "GetPixelCalibrationCoefficients":
            return lambda *a: (20202, 0, 0, 0, 0)
        if name == "GetFunctionReturnDescription":
            return lambda *a: (0, "ok")
        return lambda *a: (20202, 1)


def test_adjust_nd_sets_one_based_filter(monkeypatch):
    monkeypatch.setattr(sg, "_load_spectrograph", lambda: None)
    monkeypatch.setattr(sg, "ATSpectrograph", _FakeSpc, raising=False)
    drv = object.__new__(sg.AndorSpectrographDriver)
    opt = iter([5.0, 4.0, 1.0, 3.0, 6.0, 7.0])  # best is 0-based index 2
    drv.image_and_check_dynamic_range = lambda: (None, 100.0, None, next(opt))
    resp = drv.adjust_ND()
    assert resp.data["ND_filter_num"] == 2
    assert _FakeSpc.filters[-1] == 3


def test_setup_spectroscope_sets_the_given_one_based_filter(monkeypatch):
    monkeypatch.setattr(sg, "_load_spectrograph", lambda: None)
    monkeypatch.setattr(sg, "ATSpectrograph", _FakeSpc, raising=False)
    drv = object.__new__(sg.AndorSpectrographDriver)
    try:
        drv.setup_spectroscope(PixelWidth=6.5, ND_filter_num=1)
    except Exception:
        pass  # the fake need not satisfy the wavelength read after SetFilter
    assert _FakeSpc.filters[-1] == 1
