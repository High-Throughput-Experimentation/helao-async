"""Both BioLogic backends emit the same columns, and the OLE one delivers them.

This is the gate that makes the OLE backend a drop-in rather than merely a
similar thing. Both `biologic_vis` panels and five experiment libraries --
ANEC, ECHEUVIS, PSTAT, ECMS, HISPEC -- key off these names. A missing column
renders an empty trace with no error anywhere; a renamed one renders nothing
and logs nothing.

Two halves, and both are needed. The static half compares the registries'
declarations; on its own it would pass if the driver ignored its own plan. The
live half runs the OLE driver against its simulator. Either alone passes for
the wrong reason -- the static one if the driver ignores its own plan, the
live one if both registries are wrong in the same way.
"""

import asyncio
from pathlib import Path

import pytest

from helao.deploy.hte.drivers.pstat.biologic.technique import BIOTECHS
from helao.deploy.hte.drivers.pstat.biologic_ole import technique as ot
from helao.deploy.hte.drivers.pstat.biologic_ole.driver import BiologicOleDriver
from helao.deploy.hte.drivers.pstat.biologic_ole.sim import SimConfig, set_sim_config

TECHNIQUES = ["OCV", "CA", "CP", "CV", "PEIS", "GEIS", "CAOCV"]

#: Columns the eclib driver adds after field_remap, in code rather than in
#: the registry. `channel` is stamped by BiologicExec._poll on both backends;
#: X_ohm and R_ohm are derived in the eclib driver's get_data from modulus and
#: phase, and in the OLE cursor straight off MeasureEisValue.
ECLIB_DERIVED_IN_CODE = {"X_ohm", "R_ohm"}


def declared_eclib(name: str) -> set[str]:
    columns = set(BIOTECHS[name].field_map.values())
    if "modulus" in columns:
        columns |= ECLIB_DERIVED_IN_CODE
    return columns


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
