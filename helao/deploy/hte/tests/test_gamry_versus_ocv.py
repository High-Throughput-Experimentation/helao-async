"""``versus_OCV`` on the dtaq techniques (CA, LSV, CV, RCA).

With ``versus_OCV`` set, ``GamryExec._pre_exec`` measures OCV the way
``run_PEIS`` does (``measure_init_ocv``, shared by both executors) and shifts
every potential the signal will be built from by the mean OCV, before
``driver.setup`` sizes the voltage range from them. Scan rates are not
potentials and stay put; RCA's ``SignalArray__V`` is shifted element-wise.
The recorded ``action_params`` keep the requested, vs-OCV values.
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from helao.deploy.hte.servers.action import gamry_server2 as gs
from helao.deploy.hte.drivers.pstat.gamry.technique import TECH_CV, TECH_RCA


def test_offset_shifts_potentials_not_scan_rates():
    params = {
        "Vinit__V": 0.0,
        "Vapex1__V": 0.5,
        "Vfinal__V": -0.1,
        "ScanRate__V_s": 0.1,
        "AcqInterval__s": 0.02,
        "Cycles": 2,
    }
    out = gs.offset_potentials(params, 0.25)
    assert out == {
        "Vinit__V": 0.25,
        "Vapex1__V": 0.75,
        "Vfinal__V": 0.15,
        "ScanRate__V_s": 0.1,
        "AcqInterval__s": 0.02,
        "Cycles": 2,
    }


def test_offset_shifts_signal_array_without_mutating_it():
    array = [0.1, 0.1, 0.4]
    out = gs.offset_potentials({"SignalArray__V": array, "Cycles": 1}, -0.5)
    assert out["SignalArray__V"] == pytest.approx([-0.4, -0.4, -0.1])
    assert array == [0.1, 0.1, 0.4]


class FakeDriver:
    def __init__(self):
        self.setup_args: tuple | None = None

    def get_gamry_state(self):
        return {"Cell": "0"}

    def setup(self, technique, signal_params, dtaq_params, action_params, ierange):
        self.setup_args = (technique, signal_params, action_params)
        return type("Resp", (), {"response": "success"})()


def _exec(technique, action_params, monkeypatch, ocv=0.25):
    calls = []

    async def fake_ocv(active, driver, params):
        calls.append(params)
        return ocv

    monkeypatch.setattr(gs, "measure_init_ocv", fake_ocv)
    ex = gs.GamryExec.__new__(gs.GamryExec)  # no ActiveAction needed for _pre_exec
    driver = FakeDriver()
    ex.active = None
    ex.driver = driver  # type: ignore  # duck-typed GamryDriver
    ex.technique = technique
    ex.action_params = action_params
    ex.signal_params = {
        k: v
        for k, v in action_params.items()
        if k in technique.signal.param_keys + technique.signal.init_keys
    }
    ex.dtaq_params = {}
    ex.ierange = "auto"
    result = asyncio.run(ex._pre_exec())
    assert driver.setup_args is not None
    return result, driver.setup_args, calls


CV_PARAMS = {
    "Vinit__V": 0.0,
    "Vapex1__V": 0.5,
    "Vapex2__V": -0.2,
    "Vfinal__V": 0.0,
    "ScanRate__V_s": 0.1,
    "AcqInterval__s": 0.02,
    "Cycles": 1,
}


def test_cv_versus_ocv_shifts_what_setup_receives(monkeypatch):
    params = {**CV_PARAMS, "versus_OCV": True}
    result, (_, signal_params, action_params), calls = _exec(
        TECH_CV, params, monkeypatch
    )
    assert result["error"] == gs.ErrorCodes.none
    assert len(calls) == 1
    assert signal_params["Vinit__V"] == 0.25
    assert signal_params["Vapex1__V"] == 0.75
    assert signal_params["Vapex2__V"] == pytest.approx(0.05)
    # the recorded request stays vs OCV
    assert action_params["Vapex1__V"] == 0.5


def test_cv_without_versus_ocv_measures_nothing(monkeypatch):
    result, (_, signal_params, _), calls = _exec(TECH_CV, dict(CV_PARAMS), monkeypatch)
    assert result["error"] == gs.ErrorCodes.none
    assert calls == []
    assert signal_params["Vapex1__V"] == 0.5


def test_rca_versus_ocv_shifts_signal_array(monkeypatch):
    params = {
        "Cycles": 1,
        "AcqInterval__s": 0.01,
        "AcqPointsPerCycle": 3,
        "SignalArray__V": [0.0, 0.0, 0.3],
        "versus_OCV": True,
    }
    _, (_, signal_params, action_params), _ = _exec(
        TECH_RCA, params, monkeypatch, ocv=0.1
    )
    assert signal_params["SignalArray__V"] == pytest.approx([0.1, 0.1, 0.4])
    assert action_params["SignalArray__V"] == [0.0, 0.0, 0.3]


def test_ocv_failure_is_a_setup_error_and_skips_setup(monkeypatch):
    async def boom(active, driver, params):
        raise RuntimeError("MeasureV failed")

    ex = gs.GamryExec.__new__(gs.GamryExec)
    driver = FakeDriver()
    ex.active, ex.technique = None, TECH_CV
    ex.driver = driver  # type: ignore  # duck-typed GamryDriver
    ex.action_params = {**CV_PARAMS, "versus_OCV": True}
    ex.signal_params, ex.dtaq_params, ex.ierange = dict(CV_PARAMS), {}, "auto"
    monkeypatch.setattr(gs, "measure_init_ocv", boom)
    assert asyncio.run(ex._pre_exec())["error"] == gs.ErrorCodes.setup
    assert driver.setup_args is None


class Active:
    """The parts of an ActionSession that ``measure_init_ocv`` reads and writes."""

    def __init__(self, written, latched=False, status=(), latch_on_write=False):
        self.written = written
        self.latch_on_write = latch_on_write
        self.base = SimpleNamespace(actionservermodel=SimpleNamespace(estop=latched))
        self.action = SimpleNamespace(action_status=list(status))

    async def write_file(self, **kw):
        self.written.update(kw)
        if self.latch_on_write:
            self.base.actionservermodel.estop = True


def test_measure_init_ocv_averages_last_five_and_writes_jsonl(monkeypatch):
    vs = [0.9, 0.9, 0.1, 0.2, 0.3, 0.4, 0.5]

    async def fake_measure_ocv(pstat, gamrycom, duration, period):
        assert (duration, period) == (3.0, 0.5)
        return list(range(len(vs))), vs

    written = {}
    monkeypatch.setattr(gs, "measure_ocv", fake_measure_ocv)
    driver = type("D", (), {"pstat": None, "GamryCOM": None})()
    params = {"OCV_duration__s": 3.0, "OCV_acquisition_period__s": 0.5}
    mean = asyncio.run(gs.measure_init_ocv(Active(written), driver, params))
    assert mean == pytest.approx(0.3)
    assert written["filename"] == "init_ocv.jsonl"
    assert json.loads(written["output_str"])["Ewe_V"] == vs
    assert abs(written["header"]["mean_ocv"] - 0.3) < 1e-9


@pytest.mark.parametrize(
    "latched,status,latch_on_write",
    [
        (True, (), False),
        (False, (gs.HloStatus.estopped,), False),
        (False, (), True),
    ],
    ids=["latch-held", "latched-then-released", "latched-during-file-write"],
)
def test_estop_during_ocv_raises_before_anything_is_energized(
    monkeypatch, latched, status, latch_on_write
):
    """The check runs after the last await (the file write), so an E-STOP any
    time before setup energizes the cell is caught."""

    async def fake_measure_ocv(pstat, gamrycom, duration, period):
        return [0.0], [0.4]

    monkeypatch.setattr(gs, "measure_ocv", fake_measure_ocv)
    driver = type("D", (), {"pstat": None, "GamryCOM": None})()
    active = Active({}, latched=latched, status=status, latch_on_write=latch_on_write)
    with pytest.raises(RuntimeError, match="E-STOP"):
        asyncio.run(gs.measure_init_ocv(active, driver, {}))
