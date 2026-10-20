"""A fixed ``IErange`` switches Gamry auto-ranging off; IFC1010 skips both mode calls.

Station symptom: ``run_CV`` with a fixed ``IErange`` measured currents beyond
the range limit instead of saturating. ``GamryDriver.setup`` set the range but
never called ``SetIERangeMode(False)``, and auto-ranging persists on the open
pstat, so any earlier ``auto`` run (the endpoints' default) left it on. CV,
LSV, CA and RCA all take this path. The legacy driver (2022) also skipped
``SetIERangeMode``/``SetSenseSpeedMode`` entirely on the IFC1010 and enabled
sense-speed auto-set on every other model; ``GamryPstat`` now encodes that with
``None`` = make no call.

Every COM call is recorded by the stubs of ``test_gamry_sampling_mode``.
"""

import pytest

from helao.deploy.hte.drivers.pstat.gamry.device import (
    GAMRY_DEVICES,
    IFC1010,
    REF30K,
)
from helao.deploy.hte.drivers.pstat.gamry.driver import DUMMY_SINK, GamryDriver
from helao.deploy.hte.drivers.pstat.gamry.range import RANGES
from helao.deploy.hte.drivers.pstat.gamry.technique import TECH_CV
from helao.deploy.hte.tests.test_gamry_sampling_mode import (  # noqa: F401
    FakeGamryCOM,
    Recorder,
    log,
)

CV_PARAMS = {
    "Vinit__V": 0.0,
    "Vapex1__V": 0.5,
    "Vapex2__V": 0.0,
    "Vfinal__V": 0.0,
    "ScanRate__V_s": 0.1,
    "AcqInterval__s": 0.02,
    "Cycles": 1,
}


def _driver(model, log):
    d = GamryDriver.__new__(GamryDriver)  # no COM: connect() is Windows-only
    d.pstat = Recorder("pstat", log)
    d.GamryCOM = FakeGamryCOM()
    d.model = model
    d.config = {}
    return d


def _setup(d, ierange):
    d.dtaqsink = DUMMY_SINK  # type: ignore  # driver annotates GamryDtaqSink only
    signal_params = {
        k: v for k, v in CV_PARAMS.items() if k in TECH_CV.signal.param_keys
    }
    resp = d.setup(TECH_CV, signal_params, {}, CV_PARAMS, ierange)
    assert resp.response == "success"


def _calls(log, name):
    return [args for n, args in log if n == f"pstat.{name}"]


def _fixed(model):
    """Name of the model's first fixed range (``model.ierange`` is the enum class)."""
    return next(n for n in model.ierange.__members__ if n != "auto")


MODELS = sorted(GAMRY_DEVICES.items())


def test_model_flags_restore_the_legacy_calls():
    for name, model in GAMRY_DEVICES.items():
        if model is IFC1010:
            assert (model.set_sensemode, model.set_rangemode) == (None, True), name
        elif model is REF30K:
            assert (model.set_sensemode, model.set_rangemode) == (False, False)
        else:
            assert (model.set_sensemode, model.set_rangemode) == (True, True), name


@pytest.mark.parametrize("name,model", MODELS)
def test_fixed_range_switches_auto_ranging_off(log, name, model):
    fixed = _fixed(model)
    _setup(_driver(model, log), fixed)
    assert _calls(log, "SetIERange")[-1] == (RANGES[fixed],)
    modes = _calls(log, "SetIERangeMode")
    if model.set_rangemode is None:
        assert modes == []
    else:
        assert modes == [(False,)]


@pytest.mark.parametrize("name,model", MODELS)
def test_auto_range_uses_the_model_flag(log, name, model):
    _setup(_driver(model, log), "auto")
    modes = _calls(log, "SetIERangeMode")
    if model.set_rangemode is None:
        assert modes == []
    else:
        assert modes == [(model.set_rangemode,)]


@pytest.mark.parametrize("name,model", MODELS)
def test_sense_speed_mode_follows_the_model_flag(log, name, model):
    _setup(_driver(model, log), "auto")
    senses = _calls(log, "SetSenseSpeedMode")
    if model.set_sensemode is None:
        assert senses == []
    else:
        assert senses == [(model.set_sensemode,)]


def test_fixed_run_after_an_auto_run_leaves_auto_ranging_off(log):
    """The station sequence: the pstat stays open between actions."""
    model = GAMRY_DEVICES["REF600"]
    d = _driver(model, log)
    _setup(d, "auto")
    d.technique = None
    _setup(d, _fixed(model))
    assert _calls(log, "SetIERangeMode")[-1] == (False,)


def test_range_readback_is_logged_after_the_range_is_set(log):
    model = GAMRY_DEVICES["REF600"]
    _setup(_driver(model, log), _fixed(model))
    names = [n for n, _ in log]
    last_set = max(
        i
        for i, n in enumerate(names)
        if n in ("pstat.SetIERange", "pstat.SetIERangeMode")
    )
    assert names.index("pstat.IERangeMode", last_set) > last_set
    assert names.index("pstat.IERange", last_set) > last_set


def test_a_failing_readback_does_not_fail_setup(log):
    model = GAMRY_DEVICES["REF600"]
    d = _driver(model, log)

    def boom():
        raise RuntimeError("IERangeMode not supported")

    d.pstat.IERangeMode = boom  # type: ignore[attr-defined]
    _setup(d, _fixed(model))


def test_ifc1010_auto_run_after_a_cp_run_turns_auto_ranging_back_on(log):
    """CP/LSA leave SetIERangeMode(False) on the open pstat; auto must undo it."""
    from helao.deploy.hte.drivers.pstat.gamry.technique import TECH_CP

    d = _driver(IFC1010, log)
    d.dtaqsink = DUMMY_SINK  # type: ignore  # driver annotates GamryDtaqSink only
    cp = {"Ival__A": 1e-3, "Tval__s": 1.0, "AcqInterval__s": 0.1}
    sp = {
        k: v
        for k, v in cp.items()
        if k in TECH_CP.signal.param_keys + TECH_CP.signal.init_keys
    }
    assert d.setup(TECH_CP, sp, {}, cp)  # default IErange is auto.response == "success"
    assert _calls(log, "SetIERangeMode")[-1] == (False,)
    d.technique = None
    _setup(d, "auto")
    assert _calls(log, "SetIERangeMode")[-1] == (True,)
