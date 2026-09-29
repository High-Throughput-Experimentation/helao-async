"""CAOCV is a CA followed by an OCV, loaded as one experiment."""

import pytest

from helao.deploy.hte.drivers.pstat.biologic import data, vendor
from helao.deploy.hte.drivers.pstat.biologic.technique import (
    BIOTECHS,
    TechniqueError,
    caocv_sub_params,
    plan_for,
)

ARGS = dict(
    CA_Vval__V_list=[0.4, 0.6],
    CA_Tval__s_list=[1.0, 2.0],
    CA_AcqInterval__s=0.02,
    CA_AcqInterval__A=10.0,
    CA_IRange="m10",
    CA_ERange="v5",
    CA_Bandwidth="BW5",
    OCV_Tval__s=5.0,
    OCV_AcqInterval__s=0.25,
    OCV_AcqInterval__V=10.0,
)


def plan(**overrides):
    tech = BIOTECHS["CAOCV"]
    return plan_for(tech, {**tech.defaults, **ARGS, **overrides}, None)


def params_of(step):
    """ECC label -> value (or list of values, in index order) for one step.

    A plain `{label: v for label, v, _ in step.params}` -- the shape used
    elsewhere for LOOP/TTL steps, whose every param is scalar -- silently
    collapses a multi-index param (CA's `Voltage_step`/`Duration_step`) to
    its last index instead of reconstructing the list `entries()` expanded
    it from. `step.params` is already in index order per label, so grouping
    by first-seen label and only promoting to a list on the second value for
    that label reconstructs it exactly.
    """
    out: dict = {}
    for label, value, _ in step.params:
        if label in out:
            if not isinstance(out[label], list):
                out[label] = [out[label]]
            out[label].append(value)
        else:
            out[label] = value
    return out


def test_caocv_loads_ca_then_ocv():
    assert plan().tech_ids == [vendor.TECH_ID.CA, vendor.TECH_ID.OCV]


def test_the_ca_half_gets_the_ca_prefixed_parameters():
    ca = params_of(plan().steps[0])
    assert ca["Voltage_step"] == [0.4, 0.6]
    assert ca["Duration_step"] == [1.0, 2.0]
    assert ca["Step_number"] == 1
    assert ca["Record_every_dT"] == 0.02
    assert ca["Record_every_dI"] == 10.0


def test_the_ocv_half_gets_the_ocv_prefixed_parameters():
    ocv = params_of(plan().steps[1])
    assert ocv["Rest_time_T"] == 5.0
    assert ocv["Record_every_dT"] == 0.25
    assert ocv["Record_every_dE"] == 10.0


def test_ca_erange_reaches_the_hardware():
    """easy-biologic overwrote this from max(abs(voltages)); every other
    technique honours its ERange and CAOCV no longer differs."""
    assert params_of(plan().steps[0])["E_Range"] == vendor.E_RANGE.E_RANGE_5V


def test_ca_erange_auto_is_not_replaced_by_a_derived_range():
    ca = params_of(plan(CA_ERange="AUTO").steps[0])
    assert ca["E_Range"] == vendor.E_RANGE.E_RANGE_AUTO


def test_ca_irange_and_bandwidth_come_from_the_ca_prefixed_keys():
    ca = params_of(plan().steps[0])
    assert ca["I_Range"] == vendor.I_RANGE.I_RANGE_10mA
    assert ca["Bandwidth"] == vendor.BANDWIDTH.BW_5


def test_the_ocv_half_sends_no_hardware_ranges():
    ocv = params_of(plan().steps[1])
    assert not {"I_Range", "E_Range", "Bandwidth"} & set(ocv)


def test_sub_params_strips_the_prefixes():
    ca, ocv = caocv_sub_params({**BIOTECHS["CAOCV"].defaults, **ARGS})
    assert ca["Vval__V"] == [0.4, 0.6]
    assert ca["Tval__s"] == [1.0, 2.0]
    assert ca["IRange"] == "m10"
    assert ocv["Tval__s"] == 5.0
    assert "CA_Vval__V_list" not in ca


def test_mismatched_ca_lists_are_refused():
    with pytest.raises(TechniqueError, match="Duration_step"):
        plan(CA_Vval__V_list=[0.1, 0.2], CA_Tval__s_list=[1.0])


def test_the_column_plan_is_the_frozen_dc_set():
    assert set(BIOTECHS["CAOCV"].column_plan) == set(data.COLUMNS["CA"])


def test_a_ttl_trigger_still_goes_ahead_of_both_halves():
    tech = BIOTECHS["CAOCV"]
    p = plan_for(
        tech,
        {**tech.defaults, **ARGS},
        {"ttl": "out", "ttl_logic": 1, "ttl_duration": 1.0},
    )
    assert p.tech_ids == [vendor.TECH_ID.TO, vendor.TECH_ID.CA, vendor.TECH_ID.OCV]
