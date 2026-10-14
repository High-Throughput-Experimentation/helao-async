"""``SamplingMode`` reaches ``Signal.SetAcquisitionControl`` before ``SetSignal``.

The Framework's ``sequencerCV.exp`` selects Fast / Noise Reject / Surface with
``Signal.SetAcquisitionControl(NIL, NIL, NIL, SamplingMode)`` right after the
signal is built and before ``SetSignal``. ``GamryDriver.setup`` mirrors that
when the action carries ``SamplingMode`` and makes no call when it is absent,
so existing CV/LSV actions keep the instrument default.

``comtypes`` is Windows-only, so ``comtypes``, ``comtypes.client`` and
``comtypes.automation`` are stubbed and every COM object is a recorder.
"""

import sys
import types

import pytest

from helao.deploy.hte.drivers.pstat.gamry.device import GAMRY_DEVICES
from helao.deploy.hte.drivers.pstat.gamry.driver import DUMMY_SINK, GamryDriver
from helao.deploy.hte.drivers.pstat.gamry.technique import TECH_CV

EMPTY = object()


class Recorder:
    def __init__(self, name, log):
        self._name = name
        self._log = log

    def __getattr__(self, attr):
        def call(*args):
            self._log.append((f"{self._name}.{attr}", args))
            return 1.0

        return call


class FakeGamryCOM:
    def __getattr__(self, name):
        return f"GamryCOM.{name}"


@pytest.fixture
def log(monkeypatch):
    log: list[tuple] = []
    client = types.SimpleNamespace(
        CreateObject=lambda progid: Recorder(progid.split(".")[-1], log)
    )
    automation = types.SimpleNamespace(VARIANT=types.SimpleNamespace(empty=EMPTY))
    comtypes = types.SimpleNamespace(
        COMError=type("COMError", (Exception,), {}),
        client=client,
        automation=automation,
    )
    monkeypatch.setitem(sys.modules, "comtypes", comtypes)
    monkeypatch.setitem(sys.modules, "comtypes.client", client)
    monkeypatch.setitem(sys.modules, "comtypes.automation", automation)
    return log


def _setup(log, **extra):
    d = GamryDriver.__new__(GamryDriver)  # no COM: connect() is Windows-only
    d.pstat = Recorder("pstat", log)
    d.GamryCOM = FakeGamryCOM()
    d.model = next(iter(GAMRY_DEVICES.values()))
    d.config = {}
    d.dtaqsink = DUMMY_SINK  # type: ignore  # driver annotates GamryDtaqSink only
    params = {
        "Vinit__V": 0.0,
        "Vapex1__V": 0.5,
        "Vapex2__V": 0.0,
        "Vfinal__V": 0.0,
        "ScanRate__V_s": 0.1,
        "AcqInterval__s": 0.02,
        "Cycles": 1,
        **extra,
    }
    signal_params = {k: v for k, v in params.items() if k in TECH_CV.signal.param_keys}
    resp = d.setup(TECH_CV, signal_params, {}, params)
    assert resp.response == "success"
    return [name for name, _ in log], log


@pytest.mark.parametrize(
    "mode", ["SamplingModeSurface", "SamplingModeFast", "SamplingModeNoiseReject"]
)
def test_mode_set_on_signal_before_set_signal(log, mode):
    names, log = _setup(log, SamplingMode=mode)
    acq = names.index("GamrySignalRupdn.SetAcquisitionControl")
    assert acq < names.index("pstat.SetSignal")
    assert acq > names.index("GamrySignalRupdn.Init")
    assert log[acq][1] == (EMPTY, EMPTY, EMPTY, f"GamryCOM.{mode}")


def test_absent_mode_makes_no_call(log):
    names, _ = _setup(log)
    assert "GamrySignalRupdn.SetAcquisitionControl" not in names
    assert "pstat.SetSignal" in names
