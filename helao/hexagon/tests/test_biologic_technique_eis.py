"""PEIS/GEIS parameters, and the sweep flag that never worked."""

import pytest

from helao.deploy.hte.drivers.pstat.biologic import vendor
from helao.deploy.hte.drivers.pstat.biologic.technique import (
    BIOTECHS,
    SweepMode,
    ec_sweep,
)

PEIS_ARGS = dict(
    Vinit__V=0.05,
    Vamp__V=0.01,
    Finit__Hz=1000.0,
    Ffinal__Hz=1e6,
    FrequencyNumber=60,
    Duration__s=0.0,
    AcqInterval__s=0.1,
    SweepMode="log",
    Repeats=10,
    DelayFraction=0.1,
    IRange="AUTO",
    ERange="AUTO",
    Bandwidth="BW4",
)

GEIS_ARGS = dict(
    Iinit__A=1e-3,
    Iamp__A=1e-4,
    Finit__Hz=1000.0,
    Ffinal__Hz=1e6,
    FrequencyNumber=60,
    Duration__s=0.0,
    AcqInterval__s=0.1,
    SweepMode="log",
    Repeats=10,
    DelayFraction=0.1,
    IRange="AUTO",
    ERange="AUTO",
    Bandwidth="BW4",
)


def built(name, **overrides):
    tech = BIOTECHS[name]
    args = {
        **tech.defaults,
        **(PEIS_ARGS if name == "PEIS" else GEIS_ARGS),
        **overrides,
    }
    return tech.build(args)


# --- the fix ----------------------------------------------------------------


def test_lin_is_true_because_the_pdf_says_true_means_linear():
    assert ec_sweep("lin") is True
    assert ec_sweep(SweepMode.LINEAR) is True


def test_log_is_false():
    """bool("log") is True, which is why every station swept linearly."""
    assert ec_sweep("log") is False
    assert ec_sweep(SweepMode.LOG) is False


def test_an_unrecognised_sweep_mode_raises_rather_than_defaulting():
    with pytest.raises(ValueError):
        ec_sweep("logarithmic")


def test_a_bare_bool_is_refused_so_the_old_shape_cannot_slip_through():
    with pytest.raises(ValueError):
        ec_sweep(True)


def test_peis_sends_sweep_false_for_the_endpoint_default():
    assert built("PEIS")["sweep"] is False


def test_peis_sends_sweep_true_for_lin():
    assert built("PEIS", SweepMode="lin")["sweep"] is True


def test_geis_uses_the_same_coercion():
    assert built("GEIS")["sweep"] is False
    assert built("GEIS", SweepMode="lin")["sweep"] is True


# --- PEIS -------------------------------------------------------------------


def test_peis_duplicates_the_bias_into_initial_and_final():
    """PDF section 7.11.2 takes a start and an end step; HELAO exposes one
    bias, so both carry it and Step_number is 0."""
    got = built("PEIS", Vinit__V=0.25)
    assert got["Initial_Voltage_step"] == 0.25
    assert got["Final_Voltage_step"] == 0.25
    assert got["Step_number"] == 0


def test_peis_maps_every_endpoint_parameter():
    got = built("PEIS")
    assert got["Amplitude_Voltage"] == 0.01
    assert got["Initial_frequency"] == 1000.0
    assert got["Final_frequency"] == 1e6
    assert got["Frequency_number"] == 60
    assert got["Duration_step"] == 0.0
    assert got["Record_every_dT"] == 0.1
    assert got["Average_N_times"] == 10
    assert got["Wait_for_steady"] == 0.1


def test_peis_defaults_match_what_easy_biologic_supplied():
    got = built("PEIS")
    assert got["vs_initial"] is False
    assert got["vs_final"] is False
    assert got["Correction"] is False
    assert got["Record_every_dI"] == 0.001


def test_peis_carries_the_three_hardware_ranges():
    got = built("PEIS", IRange="m1", ERange="v10", Bandwidth="BW5")
    assert got["I_Range"] == vendor.I_RANGE.I_RANGE_1mA
    assert got["E_Range"] == vendor.E_RANGE.E_RANGE_10V
    assert got["Bandwidth"] == vendor.BANDWIDTH.BW_5


def test_peis_stem_and_id():
    assert BIOTECHS["PEIS"].ecc_stem == "peis"
    assert BIOTECHS["PEIS"].tech_id == vendor.TECH_ID.PEIS


# --- GEIS -------------------------------------------------------------------


def test_geis_duplicates_the_current_bias_and_records_on_potential():
    got = built("GEIS", Iinit__A=2e-3)
    assert got["Initial_Current_step"] == 2e-3
    assert got["Final_Current_step"] == 2e-3
    assert got["Amplitude_Current"] == 1e-4
    assert got["Record_every_dE"] == 0.001
    assert "Record_every_dI" not in got


def test_geis_stem_and_id():
    assert BIOTECHS["GEIS"].ecc_stem == "geis"
    assert BIOTECHS["GEIS"].tech_id == vendor.TECH_ID.GEIS


def test_geis_does_not_derive_a_current_range_from_the_amplitude():
    """easy-biologic called set_current_range(2 * amplitude), which only warns
    when a range is supplied -- and the endpoint always supplies one."""
    got = built("GEIS", Iamp__A=1.0, IRange="u1")
    assert got["I_Range"] == vendor.I_RANGE.I_RANGE_1uA


# --- both -------------------------------------------------------------------


@pytest.mark.parametrize("name", ["PEIS", "GEIS"])
def test_the_eis_column_plans_are_the_frozen_sixteen(name):
    assert len(BIOTECHS[name].column_plan) == 16


@pytest.mark.parametrize("name", ["PEIS", "GEIS"])
def test_every_built_label_is_declared_in_the_param_table(name):
    tech = BIOTECHS[name]
    assert set(built(name)) <= set(tech.param_table)
