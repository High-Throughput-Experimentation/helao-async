"""CALIMIT/CPLIMIT limits, and the staircase EIS pair.

The bit positions in `test_encode_test_packs_the_documented_bitfield` are
transcribed from the rendered PDF page, not from its text layer.
"""

import pytest

from helao.deploy.hte.drivers.pstat.biologic import data, vendor
from helao.deploy.hte.drivers.pstat.biologic.technique import (
    BIOTECHS,
    ExitCond,
    LimitTest,
    TechniqueError,
    encode_test,
)

LIMIT_ARGS = dict(
    Vval__V=[0.5],
    Tval__s=[10.0],
    AcqInterval__s=0.01,
    AcqInterval__A=10.0,
    IRange="m10",
    ERange="AUTO",
    Bandwidth="BW4",
    Cycles=0,
    ExitCondition=int(ExitCond.NEXT_TECHNIQUE),
    Test1={
        "variable": "I",
        "above": True,
        "value": 1e-3,
        "logic": "AND",
        "active": True,
    },
)

SPEIS_ARGS = dict(
    Vinit__V=0.0,
    Vfinal__V=0.5,
    StepNumber=10,
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

SGEIS_ARGS = dict(
    Iinit__A=0.0,
    Ifinal__A=1e-3,
    StepNumber=10,
    Iamp__A=1e-4,
    Finit__Hz=1000.0,
    Ffinal__Hz=1e6,
    FrequencyNumber=60,
    Duration__s=0.0,
    AcqInterval__s=0.1,
    SweepMode="log",
    Repeats=10,
    DelayFraction=0.1,
    IRange="m10",
    ERange="AUTO",
    Bandwidth="BW4",
)


def built(name, args, **overrides):
    tech = BIOTECHS[name]
    return tech.build({**tech.defaults, **args, **overrides})


# --- the bitfield -----------------------------------------------------------


def test_encode_test_packs_the_documented_bitfield():
    """Bit positions read off PDF section 7.37.2's rendered table. Replace the
    literals below with what that page shows before implementing."""
    VARIABLE_SHIFT = 5
    SIGN_BIT = 2
    LOGIC_BIT = 1
    ACTIVE_BIT = 0

    packed = encode_test(LimitTest(variable="I", above=True, logic="AND", active=True))
    assert packed >> VARIABLE_SHIFT == 3  # I (Current) = 3
    assert (packed >> SIGN_BIT) & 1 == 1  # ">" = 1
    assert (packed >> LOGIC_BIT) & 1 == 1  # AND = 1
    assert (packed >> ACTIVE_BIT) & 1 == 1  # active = 1


def test_the_four_variables_have_the_documented_codes():
    codes = {
        v: encode_test(LimitTest(v, above=False, logic="OR", active=True)) >> 5
        for v in ("E", "AUX1", "AUX2", "I")
    }
    assert codes == {"E": 0, "AUX1": 1, "AUX2": 2, "I": 3}


def test_an_inactive_test_still_encodes_its_variable():
    packed = encode_test(LimitTest("E", above=False, logic="OR", active=False))
    assert packed & 1 == 0


def test_below_and_or_are_the_zero_encodings():
    assert encode_test(LimitTest("E", above=False, logic="OR", active=False)) == 0


def test_an_unknown_variable_is_refused():
    with pytest.raises(TechniqueError, match="AUX3"):
        encode_test(LimitTest("AUX3", above=True, logic="AND", active=True))


def test_an_unknown_logic_is_refused():
    with pytest.raises(TechniqueError, match="XOR"):
        encode_test(LimitTest("E", above=True, logic="XOR", active=True))


# --- the dependency rules PDF section 7.37.2 states -------------------------


def test_test2_without_test1_is_refused():
    """The PDF says Test2 is ignored if Test1 is inactive -- ignored, not
    refused, which is worse: the limit the caller asked for does not exist."""
    with pytest.raises(TechniqueError, match="Test1"):
        built(
            "CALIMIT",
            LIMIT_ARGS,
            Test1=None,
            Test2={
                "variable": "E",
                "above": True,
                "value": 1.0,
                "logic": "AND",
                "active": True,
            },
        )


def test_test3_without_test2_is_refused():
    with pytest.raises(TechniqueError, match="Test2"):
        built(
            "CALIMIT",
            LIMIT_ARGS,
            Test3={
                "variable": "E",
                "above": True,
                "value": 1.0,
                "logic": "AND",
                "active": True,
            },
        )


def test_a_malformed_limit_dict_is_refused_not_a_bare_keyerror():
    """A TestN dict missing a required key used to surface to the operator as
    `setup failed: 'logic'` -- everything else in this layer raises
    TechniqueError with a sentence."""
    with pytest.raises(TechniqueError, match="logic"):
        built(
            "CALIMIT", LIMIT_ARGS, Test1={"variable": "E", "above": True, "value": 1.0}
        )


def test_no_tests_at_all_is_allowed():
    got = built("CALIMIT", LIMIT_ARGS, Test1=None)
    assert got["Test1_Config"] == [0]
    assert got["Test1_Value"] == [0.0]


# --- CALIMIT / CPLIMIT ------------------------------------------------------


def test_calimit_reuses_cps_column_plan():
    assert set(BIOTECHS["CALIMIT"].column_plan) == set(data.COLUMNS["CP"])
    assert set(BIOTECHS["CPLIMIT"].column_plan) == set(data.COLUMNS["CP"])


def test_calimit_step_number_is_len_minus_one():
    """PDF section 7.37.2: "Number of steps minus 1"."""
    got = built("CALIMIT", LIMIT_ARGS, Vval__V=[0.1, 0.2, 0.3], Tval__s=[1.0, 2.0, 3.0])
    assert got["Step_number"] == 2


def test_calimit_sends_voltage_steps_and_cplimit_sends_current_steps():
    ca = built("CALIMIT", LIMIT_ARGS)
    assert "Voltage_step" in ca and "Current_step" not in ca
    cp = built(
        "CPLIMIT",
        {**LIMIT_ARGS, "Ival__A": [1e-3], "AcqInterval__V": 0.001},
    )
    assert "Current_step" in cp and "Voltage_step" not in cp


def test_the_limit_arrays_are_per_step_and_twenty_wide():
    tech = BIOTECHS["CALIMIT"]
    for label in (
        "Test1_Config",
        "Test1_Value",
        "Test2_Config",
        "Test2_Value",
        "Test3_Config",
        "Test3_Value",
        "Exit_Cond",
    ):
        assert tech.param_table[label].arity == 20


def test_the_limit_value_carries_the_unit_of_its_variable():
    got = built("CALIMIT", LIMIT_ARGS)
    assert got["Test1_Value"] == [pytest.approx(1e-3)]


def test_exit_condition_is_broadcast_to_every_step():
    got = built(
        "CALIMIT",
        LIMIT_ARGS,
        Vval__V=[0.1, 0.2],
        Tval__s=[1.0, 2.0],
        ExitCondition=int(ExitCond.STOP),
    )
    assert got["Exit_Cond"] == [int(ExitCond.STOP)] * 2


def test_an_unknown_exit_condition_is_refused():
    with pytest.raises(TechniqueError, match="7"):
        built("CALIMIT", LIMIT_ARGS, ExitCondition=7)


def test_calimit_stems_and_ids():
    assert (BIOTECHS["CALIMIT"].ecc_stem, BIOTECHS["CALIMIT"].tech_id) == (
        "calimit",
        vendor.TECH_ID.CALIMIT,
    )
    assert (BIOTECHS["CPLIMIT"].ecc_stem, BIOTECHS["CPLIMIT"].tech_id) == (
        "cplimit",
        vendor.TECH_ID.CPLIMIT,
    )


def test_cplimit_refuses_i_auto_range():
    """PDF page 158 (I_Range row, §7.36.2): "Warning: I Auto-range is not
    allowed" -- under galvanostatic control the instrument is driving the
    current, so it cannot auto-range the quantity it is setting."""
    with pytest.raises(TechniqueError, match="CPLIMIT"):
        built(
            "CPLIMIT",
            {
                **LIMIT_ARGS,
                "Ival__A": [1e-3],
                "AcqInterval__V": 0.001,
                "IRange": "AUTO",
            },
        )


def test_cplimit_builds_fine_with_an_explicit_i_range():
    got = built(
        "CPLIMIT",
        {**LIMIT_ARGS, "Ival__A": [1e-3], "AcqInterval__V": 0.001},
    )
    assert got["I_Range"] != int(vendor.I_RANGE.I_RANGE_AUTO)


# --- SPEIS / SGEIS ----------------------------------------------------------


def test_speis_sweeps_between_two_distinct_biases():
    """The difference from PEIS: Initial_ and Final_ are not the same value,
    and Step_number is the number of steps between them."""
    got = built("SPEIS", SPEIS_ARGS)
    assert got["Initial_Voltage_step"] == 0.0
    assert got["Final_Voltage_step"] == 0.5
    assert got["Step_number"] == 10


def test_sgeis_sweeps_between_two_currents():
    got = built("SGEIS", SGEIS_ARGS)
    assert got["Initial_Current_step"] == 0.0
    assert got["Final_Current_step"] == 1e-3
    assert got["Step_number"] == 10


def test_staircase_step_number_is_bounded_by_the_pdf_range():
    """PDF section 7.12.2: [0..98]."""
    with pytest.raises(TechniqueError, match="98"):
        built("SPEIS", SPEIS_ARGS, StepNumber=99)


def test_the_staircase_pair_uses_the_fixed_sweep_coercion():
    assert built("SPEIS", SPEIS_ARGS)["sweep"] is False
    assert built("SGEIS", SGEIS_ARGS, SweepMode="lin")["sweep"] is True


def test_the_staircase_column_plans_add_step_to_the_eis_set():
    for name in ("SPEIS", "SGEIS"):
        assert set(BIOTECHS[name].column_plan) == set(data.COLUMNS["PEIS"]) | {"step"}


def test_staircase_stems_and_ids():
    assert (BIOTECHS["SPEIS"].ecc_stem, BIOTECHS["SPEIS"].tech_id) == (
        "seisp",
        vendor.TECH_ID.SPEIS,
    )
    assert (BIOTECHS["SGEIS"].ecc_stem, BIOTECHS["SGEIS"].tech_id) == (
        "seisg",
        vendor.TECH_ID.SGEIS,
    )


def test_sgeis_refuses_i_auto_range():
    """PDF §7.14.2's I_Range row carries the same warning as CPLIMIT's;
    SGEIS is current-controlled the same way. GEIS itself is deliberately
    left unchanged -- it is a production technique on four stations today."""
    with pytest.raises(TechniqueError, match="SGEIS"):
        built("SGEIS", {**SGEIS_ARGS, "IRange": "AUTO"})


def test_sgeis_builds_fine_with_an_explicit_i_range():
    got = built("SGEIS", SGEIS_ARGS)
    assert got["I_Range"] != int(vendor.I_RANGE.I_RANGE_AUTO)


def test_every_new_technique_only_emits_declared_labels():
    for name, args in (
        ("CALIMIT", LIMIT_ARGS),
        ("CPLIMIT", {**LIMIT_ARGS, "Ival__A": [1e-3], "AcqInterval__V": 0.001}),
        ("SPEIS", SPEIS_ARGS),
        ("SGEIS", SGEIS_ARGS),
    ):
        assert set(built(name, args)) <= set(BIOTECHS[name].param_table)
