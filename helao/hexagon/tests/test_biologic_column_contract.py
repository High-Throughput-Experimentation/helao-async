"""Both BioLogic backends emit the same columns, and the OLE one delivers them.

This is the gate that makes the OLE backend a drop-in rather than merely a
similar thing. Both `biologic_vis` panels and five experiment libraries --
ANEC, ECHEUVIS, PSTAT, ECMS, HISPEC -- key off these names. A missing column
renders an empty trace with no error anywhere; a renamed one renders nothing
and logs nothing.

Two halves, and both are needed. The static half compares the registries'
declarations; on its own it would pass if a driver ignored its own plan. The
live half runs a real driver against its simulator. Either alone passes for
the wrong reason -- the static one if a driver ignores its own plan, the live
one if both registries are wrong in the same way. The static half is now
proven by two drivers rather than declared by one: both the OLE and eclib
live halves below run against the same frozen sets.
"""

import asyncio
from pathlib import Path

import pytest

from helao.core.drivers.helao_driver import DriverResponseType
from helao.deploy.hte.drivers.pstat.biologic import sim as eclib_sim
from helao.deploy.hte.drivers.pstat.biologic.driver import BiologicDriver
from helao.deploy.hte.drivers.pstat.biologic.technique import BIOTECHS
from helao.deploy.hte.drivers.pstat.biologic_ole import technique as ot
from helao.deploy.hte.drivers.pstat.biologic_ole.driver import BiologicOleDriver
from helao.deploy.hte.drivers.pstat.biologic_ole.sim import SimConfig, set_sim_config

TECHNIQUES = ["OCV", "CA", "CP", "CV", "PEIS", "GEIS", "CAOCV"]

#: The four EClib1-only techniques (PDF-only limit-test and staircase EIS
#: variants). The OLE backend has never had them and is not expected to grow
#: them, so they are declared here but deliberately excluded from
#: TECHNIQUES/the cross-backend comparisons above.
ECLIB_ONLY_TECHNIQUES = ["CALIMIT", "CPLIMIT", "SPEIS", "SGEIS"]


def declared_eclib(name: str) -> set[str]:
    return set(BIOTECHS[name].column_plan)


def declared_ole(name: str) -> set[str]:
    return set(ot.columns(ot.resolve(name).column_plan))


@pytest.mark.parametrize("name", TECHNIQUES)
def test_the_two_registries_declare_the_same_columns(name):
    assert declared_ole(name) == declared_eclib(name), {
        "only_eclib": sorted(declared_eclib(name) - declared_ole(name)),
        "only_ole": sorted(declared_ole(name) - declared_eclib(name)),
    }


def test_the_dc_column_set_is_the_frozen_one():
    """Spelled out, so a change to both registries at once still fails."""
    assert declared_ole("CA") == {"t_s", "Ewe_V", "I_A", "P_W", "cycle"}


def test_the_eis_column_set_is_the_frozen_one():
    assert declared_ole("PEIS") == {
        "process",
        "t_s",
        "Ewe_V",
        "I_A",
        "AbsEwe_V",
        "AbsI_A",
        "phase",
        "modulus",
        "Ece_V",
        "AbsEce_V",
        "AbsIce_A",
        "phase_ce",
        "modulus_ce",
        "f_Hz",
        "X_ohm",
        "R_ohm",
    }


def test_ocv_emits_only_time_and_potential():
    assert declared_ole("OCV") == {"t_s", "Ewe_V"}


#: Real, GUI-authored EC-Lab templates for all seven techniques -- the same
#: ground truth `test_ole_technique.py` drives, and already committed under
#: `biologic_ole/templates/`. The plan's original fixture here synthesized
#: one template holding every caption any technique's parameter_map names,
#: to stand in for real templates that did not exist yet when the plan was
#: written. All seven are now real and committed (`CAOCV.mps` included), and
#: `run_once` below calls `driver.setup(technique, {"channel": 0})` --
#: `_patch` skips every parameter_map entry whose key is absent from
#: `action_params`, so with no keys but `channel` present, nothing here
#: actually substitutes a caption. Real templates cost nothing over a
#: synthetic one for this test and exercise the real per-technique files
#: instead of a stand-in, so they are used directly rather than falling back
#: to a synthetic fixture.
REAL_TEMPLATES = Path("helao/deploy/hte/drivers/pstat/biologic_ole/templates")


def run_once(name: str, templates, tmp_path) -> dict:
    """Drive one technique through the OLE driver against the simulator."""
    kind = "eis" if name in ("PEIS", "GEIS") else "dc"
    set_sim_config(SimConfig(run_seconds=0.0, kind=kind, n_eis_points=4))
    try:
        driver = BiologicOleDriver(
            config={
                "address": "1.2.3.4",
                "num_channels": 1,
                "simulate": True,
                "templates_dir": str(templates),
                "scratch_dir": str(tmp_path / name),
            }
        )
        assert driver.connect().response == "success"
        assert driver.setup(ot.resolve(name), {"channel": 0}).response == "success"
        assert driver.start_channel(0).response == "success"
        collected: dict[str, list] = {}
        for _ in range(10):
            response = asyncio.run(driver.get_data(0))
            for column, values in response.data.items():
                collected.setdefault(column, []).extend(values)
            if response.message == "done":
                break
        driver.cleanup(0)
        driver.disconnect()
        return collected
    finally:
        set_sim_config(SimConfig())


@pytest.mark.parametrize("name", TECHNIQUES)
def test_the_driver_delivers_every_column_it_declares(name, tmp_path):
    collected = run_once(name, REAL_TEMPLATES, tmp_path)
    assert set(collected) >= declared_ole(name), sorted(
        declared_ole(name) - set(collected)
    )


@pytest.mark.parametrize("name", TECHNIQUES)
def test_every_delivered_column_has_the_same_number_of_rows(name, tmp_path):
    """A short column misaligns every row after it, in every consumer."""
    collected = run_once(name, REAL_TEMPLATES, tmp_path)
    lengths = {column: len(values) for column, values in collected.items()}
    assert len(set(lengths.values())) == 1, lengths


@pytest.mark.parametrize("name", TECHNIQUES)
def test_the_driver_delivers_no_column_it_did_not_declare(name, tmp_path):
    """An undeclared column is a contract the other backend does not honour."""
    collected = run_once(name, REAL_TEMPLATES, tmp_path)
    assert set(collected) <= declared_ole(name), sorted(
        set(collected) - declared_ole(name)
    )


@pytest.mark.parametrize("name", TECHNIQUES)
def test_at_least_one_row_is_delivered(name, tmp_path):
    """A run that emits nothing would satisfy every set comparison above."""
    collected = run_once(name, REAL_TEMPLATES, tmp_path)
    assert collected["t_s"], name


# --------------------------------------------------------------------------
# the eclib live half -- mirrors run_once above, against the EClib1 sim
# --------------------------------------------------------------------------

#: Minimal action params for each shared technique, against the eclib1 sim.
#: Every value a technique's build reads but its own `defaults` does not
#: supply must be present here or `setup()` raises a KeyError.
ECLIB_LIVE_PARAMS: dict[str, dict] = {
    "OCV": {"channel": 0, "Tval__s": 1.0, "AcqInterval__s": 0.1},
    "CA": {
        "channel": 0,
        "Vval__V": 0.5,
        "Tval__s": 1.0,
        "AcqInterval__s": 0.01,
        "AcqInterval__A": 10.0,
        "IRange": "AUTO",
        "ERange": "AUTO",
        "Bandwidth": "BW4",
    },
    "CP": {"channel": 0, "Ival__A": 1e-3, "Tval__s": 1.0},
    "CV": {
        "channel": 0,
        "Vinit__V": 0.0,
        "Vapex1__V": 0.5,
        "Vapex2__V": -0.5,
        "Vfinal__V": 0.0,
        "ScanRate__V_s": 0.1,
        "Cycles": 1,
    },
    "PEIS": {
        "channel": 0,
        "Vinit__V": 0.0,
        "Vamp__V": 0.01,
        "Finit__Hz": 1000.0,
        "Ffinal__Hz": 1e6,
        "FrequencyNumber": 60,
        "Duration__s": 0.0,
        "AcqInterval__s": 0.1,
        "SweepMode": "log",
        "Repeats": 10,
        "DelayFraction": 0.1,
    },
    "GEIS": {
        "channel": 0,
        "Iinit__A": 1e-3,
        "Iamp__A": 1e-4,
        "Finit__Hz": 1000.0,
        "Ffinal__Hz": 1e6,
        "FrequencyNumber": 60,
        "Duration__s": 0.0,
        "AcqInterval__s": 0.1,
        "SweepMode": "log",
        "Repeats": 10,
        "DelayFraction": 0.1,
    },
    "CAOCV": {
        "channel": 0,
        "CA_Vval__V_list": [0.4, 0.6],
        "CA_Tval__s_list": [1.0, 2.0],
        "CA_AcqInterval__s": 0.02,
        "CA_AcqInterval__A": 10.0,
        "CA_IRange": "m10",
        "CA_ERange": "v5",
        "CA_Bandwidth": "BW5",
        "OCV_Tval__s": 5.0,
        "OCV_AcqInterval__s": 0.25,
        "OCV_AcqInterval__V": 10.0,
    },
}


def run_once_eclib(name: str) -> dict:
    """Drive one technique through the eclib1 driver against its simulator."""
    eclib_sim.set_sim_config(eclib_sim.SimConfig())
    try:
        driver = BiologicDriver(
            {
                "address": "192.168.200.100",
                "num_channels": 1,
                "simulate": True,
                "sdk_path": "/unused",
            }
        )
        assert driver.connect().response == DriverResponseType.success
        technique = BIOTECHS[name]
        setup_resp = driver.setup(
            technique=technique, action_params=ECLIB_LIVE_PARAMS[name]
        )
        assert setup_resp.response == DriverResponseType.success, setup_resp.message
        assert driver.start_channel(0).response == DriverResponseType.success
        collected: dict[str, list] = {}
        for _ in range(50):
            response = asyncio.run(driver.get_data(0))
            for column, values in (response.data or {}).items():
                collected.setdefault(column, []).extend(values)
            if response.message == "done":
                break
        driver.shutdown()
        return collected
    finally:
        eclib_sim.set_sim_config(eclib_sim.SimConfig())


@pytest.mark.parametrize("name", TECHNIQUES)
def test_the_eclib_driver_also_delivers_exactly_the_declared_columns(name):
    """The eclib driver additionally stamps `_`-prefixed CurrentValues
    fields (`_State`, `_TimeBase`, ...) onto every row -- diagnostics, not
    part of the declared plan -- so those are excluded before comparing."""
    collected = run_once_eclib(name)
    emitted = {column for column in collected if not column.startswith("_")}
    assert emitted == declared_eclib(name), {
        "missing": sorted(declared_eclib(name) - emitted),
        "extra": sorted(emitted - declared_eclib(name)),
    }


# --------------------------------------------------------------------------
# eclib-only techniques -- declared, but out of the cross-backend contract
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", ECLIB_ONLY_TECHNIQUES)
def test_the_new_techniques_declare_a_real_column_plan(name):
    assert declared_eclib(name)


@pytest.mark.parametrize("name", ECLIB_ONLY_TECHNIQUES)
def test_the_new_techniques_are_not_part_of_the_ole_registry(name):
    """The OLE backend has no CALIMIT/CPLIMIT/SPEIS/SGEIS and is not expected
    to grow them -- these four are eclib-only, not a gap in the OLE side."""
    with pytest.raises(ValueError, match=name):
        ot.resolve(name)
