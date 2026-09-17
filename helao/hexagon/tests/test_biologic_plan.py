"""Plan expansion, and the entry-index to loaded-index mapping."""

import pytest

from helao.deploy.hte.drivers.pstat.biologic import vendor
from helao.deploy.hte.drivers.pstat.biologic.technique import (
    PlanEntry,
    PlanLoop,
    TechniqueError,
    plan_technique,
)

OCV = dict(Tval__s=1.0, AcqInterval__s=0.1)
CA = dict(
    Vval__V=0.5,
    Tval__s=1.0,
    AcqInterval__s=0.01,
    AcqInterval__A=10.0,
    IRange="AUTO",
    ERange="AUTO",
    Bandwidth="BW4",
)
TTL_IN = {"ttl": "in", "ttl_logic": 1, "ttl_duration": 1.0}


def expand(entries, loops=(), ttl=None):
    return plan_technique(list(entries), list(loops)).expand({}, ttl)


def loop_params(step):
    return {label: value for label, value, _ in step.params}


def test_a_two_entry_plan_loads_two_techniques_in_order():
    plan = expand([PlanEntry("OCV", OCV), PlanEntry("CA", CA)])
    assert plan.tech_ids == [vendor.TECH_ID.OCV, vendor.TECH_ID.CA]


def test_each_entry_carries_its_own_ranges():
    """One plan may run two techniques at different current ranges."""
    plan = expand(
        [
            PlanEntry("CA", {**CA, "IRange": "u10"}),
            PlanEntry("CA", {**CA, "IRange": "m10"}),
        ]
    )
    first = {label: v for label, v, _ in plan.steps[0].params}
    second = {label: v for label, v, _ in plan.steps[1].params}
    assert first["I_Range"] == vendor.I_RANGE.I_RANGE_10uA
    assert second["I_Range"] == vendor.I_RANGE.I_RANGE_10mA


def test_a_loop_appends_a_loop_technique_after_the_span():
    plan = expand(
        [PlanEntry("OCV", OCV), PlanEntry("CA", CA)], [PlanLoop(start=0, end=1, n=3)]
    )
    assert plan.tech_ids == [
        vendor.TECH_ID.OCV,
        vendor.TECH_ID.CA,
        vendor.TECH_ID.LOOP,
    ]
    assert loop_params(plan.steps[2]) == {"loop_N_times": 3, "protocol_number": 0}


def test_protocol_number_is_the_loaded_index_not_the_plan_index():
    """A prepended TTL shifts every loaded index by one."""
    plan = expand(
        [PlanEntry("OCV", OCV), PlanEntry("CA", CA)],
        [PlanLoop(start=0, end=1, n=2)],
        ttl=TTL_IN,
    )
    assert plan.tech_ids[0] == vendor.TECH_ID.TI
    assert loop_params(plan.steps[-1])["protocol_number"] == 1


@pytest.mark.xfail(reason="CAOCV lands in Task 11")
def test_a_loop_over_a_multi_technique_entry_wraps_all_of_it():
    """CAOCV occupies two slots. A loop over that one entry must return to the
    CA, not to the OCV half."""
    plan = expand(
        [PlanEntry("OCV", OCV), PlanEntry("CAOCV", _CAOCV)],
        [PlanLoop(start=1, end=1, n=2)],
    )
    assert plan.tech_ids[:3] == [
        vendor.TECH_ID.OCV,
        vendor.TECH_ID.CA,
        vendor.TECH_ID.OCV,
    ]
    assert loop_params(plan.steps[-1])["protocol_number"] == 1


@pytest.mark.xfail(reason="CAOCV lands in Task 11")
def test_a_loop_lands_after_the_last_technique_of_its_end_entry():
    plan = expand(
        [PlanEntry("CAOCV", _CAOCV), PlanEntry("CA", CA)],
        [PlanLoop(start=0, end=0, n=2)],
    )
    # CA, OCV (the CAOCV pair), LOOP, then the trailing CA.
    assert plan.tech_ids == [
        vendor.TECH_ID.CA,
        vendor.TECH_ID.OCV,
        vendor.TECH_ID.LOOP,
        vendor.TECH_ID.CA,
    ]


def test_two_nested_loops_both_resolve():
    plan = expand(
        [PlanEntry("OCV", OCV), PlanEntry("CA", CA), PlanEntry("OCV", OCV)],
        [PlanLoop(start=1, end=1, n=2), PlanLoop(start=0, end=2, n=3)],
    )
    assert plan.tech_ids.count(vendor.TECH_ID.LOOP) == 2
    inner, outer = plan.steps[2], plan.steps[-1]
    assert loop_params(inner)["protocol_number"] == 1
    assert loop_params(outer)["protocol_number"] == 0


def test_unlimited_goto_is_refused():
    with pytest.raises(TechniqueError, match="-1"):
        expand([PlanEntry("CA", CA)], [PlanLoop(start=0, end=0, n=-1)])


def test_a_zero_repeat_loop_is_refused():
    with pytest.raises(TechniqueError, match="loop_N_times"):
        expand([PlanEntry("CA", CA)], [PlanLoop(start=0, end=0, n=0)])


def test_straddling_spans_are_refused():
    with pytest.raises(TechniqueError, match="nest"):
        expand(
            [PlanEntry("OCV", OCV), PlanEntry("CA", CA), PlanEntry("OCV", OCV)],
            [PlanLoop(start=0, end=1, n=2), PlanLoop(start=1, end=2, n=2)],
        )


def test_an_out_of_range_span_is_refused():
    with pytest.raises(TechniqueError, match="range"):
        expand([PlanEntry("CA", CA)], [PlanLoop(start=0, end=5, n=2)])


def test_a_reversed_span_is_refused():
    with pytest.raises(TechniqueError, match="range"):
        expand(
            [PlanEntry("OCV", OCV), PlanEntry("CA", CA)],
            [PlanLoop(start=1, end=0, n=2)],
        )


def test_an_unknown_technique_name_is_refused_at_build_time():
    """The endpoint builds the plan before ctx.begin(), so an unbuildable plan
    fails the call rather than starting an action that aborts with the cell
    already claimed."""
    with pytest.raises(TechniqueError, match="ZRA"):
        expand([PlanEntry("ZRA", {})])


def test_an_empty_plan_is_refused():
    with pytest.raises(TechniqueError, match="empty"):
        expand([])


def test_the_plan_column_plan_is_the_union_of_its_entries():
    tech = plan_technique([PlanEntry("CA", CA), PlanEntry("PEIS", _PEIS)], [])
    assert set(tech.column_plan) == set(_COLUMNS["CA"]) | set(_COLUMNS["PEIS"])


def test_a_single_entry_plan_emits_exactly_that_technique_columns():
    tech = plan_technique([PlanEntry("CA", CA)], [])
    assert set(tech.column_plan) == set(_COLUMNS["CA"])


_CAOCV = dict(
    CA_Vval__V_list=[0.5],
    CA_Tval__s_list=[1.0],
    CA_AcqInterval__s=0.01,
    CA_AcqInterval__A=10.0,
    CA_IRange="AUTO",
    CA_ERange="AUTO",
    CA_Bandwidth="BW4",
    OCV_Tval__s=1.0,
    OCV_AcqInterval__s=0.1,
    OCV_AcqInterval__V=10.0,
)

_PEIS = dict(
    Vinit__V=0.0,
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

from helao.deploy.hte.drivers.pstat.biologic.data import (
    COLUMNS as _COLUMNS,
)  # noqa: E402
