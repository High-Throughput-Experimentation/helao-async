"""Plan expansion, and the entry-index to loaded-index mapping."""

import asyncio

import pytest

from helao.deploy.hte.drivers.pstat.biologic import data as biodata
from helao.deploy.hte.drivers.pstat.biologic import sim, vendor
from helao.deploy.hte.drivers.pstat.biologic.driver import BiologicDriver
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


def resolved_technique(plan, loop_step):
    """The tech_id a LOOP step's protocol_number actually points at."""
    return plan.tech_ids[loop_params(loop_step)["protocol_number"]]


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


def test_two_disjoint_sibling_loops_each_resolve_to_their_own_entry():
    """Neither span nests the other. The first LOOP's insertion must not
    stale-out the second span's protocol_number."""
    plan = expand(
        [
            PlanEntry("OCV", OCV),
            PlanEntry("CA", CA),
            PlanEntry("OCV", OCV),
            PlanEntry("CA", CA),
        ],
        [PlanLoop(start=0, end=1, n=2), PlanLoop(start=3, end=3, n=5)],
    )
    assert plan.tech_ids == [
        vendor.TECH_ID.OCV,
        vendor.TECH_ID.CA,
        vendor.TECH_ID.LOOP,
        vendor.TECH_ID.OCV,
        vendor.TECH_ID.CA,
        vendor.TECH_ID.LOOP,
    ]
    first_loop, second_loop = plan.steps[2], plan.steps[5]
    assert resolved_technique(plan, first_loop) == vendor.TECH_ID.OCV
    assert resolved_technique(plan, second_loop) == vendor.TECH_ID.CA


def test_disjoint_sibling_loops_with_a_prepended_trigger():
    """The trigger shift and the first LOOP's insertion both precede the
    second span's target -- two levels of shift the fix must survive."""
    plan = expand(
        [
            PlanEntry("OCV", OCV),
            PlanEntry("CA", CA),
            PlanEntry("OCV", OCV),
            PlanEntry("CA", CA),
        ],
        [PlanLoop(start=0, end=1, n=2), PlanLoop(start=3, end=3, n=5)],
        ttl=TTL_IN,
    )
    assert plan.tech_ids == [
        vendor.TECH_ID.TI,
        vendor.TECH_ID.OCV,
        vendor.TECH_ID.CA,
        vendor.TECH_ID.LOOP,
        vendor.TECH_ID.OCV,
        vendor.TECH_ID.CA,
        vendor.TECH_ID.LOOP,
    ]
    first_loop, second_loop = plan.steps[3], plan.steps[6]
    assert resolved_technique(plan, first_loop) == vendor.TECH_ID.OCV
    assert resolved_technique(plan, second_loop) == vendor.TECH_ID.CA


def test_three_deep_nesting_all_resolve():
    plan = expand(
        [
            PlanEntry("OCV", OCV),
            PlanEntry("CA", CA),
            PlanEntry("OCV", OCV),
            PlanEntry("CA", CA),
            PlanEntry("OCV", OCV),
        ],
        [
            PlanLoop(start=1, end=1, n=2),
            PlanLoop(start=0, end=2, n=3),
            PlanLoop(start=0, end=4, n=4),
        ],
    )
    loop_indices = [i for i, t in enumerate(plan.tech_ids) if t == vendor.TECH_ID.LOOP]
    assert len(loop_indices) == 3
    inner, mid, outer = (plan.steps[i] for i in loop_indices)
    # inner wraps just the CA at plan index 1
    assert resolved_technique(plan, inner) == vendor.TECH_ID.CA
    # mid and outer both start at plan index 0, an OCV
    assert resolved_technique(plan, mid) == vendor.TECH_ID.OCV
    assert resolved_technique(plan, outer) == vendor.TECH_ID.OCV


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

# --- driving a plan through the driver (the C1 regression) ------------------
#
# C1: `data.decode` raised `KeyError` on the terminal poll of every `run_plan`
# run, because `_segment_name`'s fallback name ("PLAN"/"NONE" for a technique
# id this build does not recognize, or a zero-row poll) is not a `COLUMNS`
# key. Nothing above this line ever drives a plan through the driver's
# `get_data` -- these tests exercise `expand()` only -- and
# `test_biologic_caocv.py` does not cover it either, because `"CAOCV"` *is* a
# `COLUMNS` key; only a plain multi-entry `PlanTechnique` (whose
# `technique_name` really is `"PLAN"`) ever takes the fallback path. Before
# this, the Critical was proofed only by a scratch reproduction script, with
# no committed regression.


def test_a_two_technique_plan_completes_with_every_poll_successful(monkeypatch):
    """The full C1 regression: two techniques, polled to completion, with
    every response asserted successful (not just the last) and more than one
    distinct decoded segment name actually seen.

    The second assertion is what makes the M8 fix (the simulator advancing
    through loaded techniques instead of always reporting the first one)
    load-bearing here rather than decorative -- without it, this test would
    have passed against the pre-fix driver too, the same way nineteen other
    green tests in this file missed C1: the bug only fires when `get_data`
    decodes a *later* segment's id, and a simulator that always reports the
    first technique never reaches that code path.
    """
    seen_names: list[str] = []
    orig_decode = biodata.decode

    def spy_decode(name, *args, **kwargs):
        seen_names.append(name)
        return orig_decode(name, *args, **kwargs)

    monkeypatch.setattr(biodata, "decode", spy_decode)

    sim.set_sim_config(sim.SimConfig())
    driver = BiologicDriver(
        {"address": "1.2.3.4", "num_channels": 1, "simulate": True, "sdk_path": "/x"}
    )
    try:
        assert driver.connect().response == "success"
        tech = plan_technique([PlanEntry("OCV", OCV), PlanEntry("CA", CA)], [])
        assert driver.setup(tech, {"channel": 0}).response == "success"
        assert driver.start_channel(0).response == "success"

        for _ in range(50):
            resp = asyncio.run(driver.get_data(0))
            assert resp.response == "success", resp.message
            if resp.message == "done":
                break
        else:
            raise AssertionError("plan never finished")
    finally:
        driver.shutdown()
        sim.set_sim_config(sim.SimConfig())

    assert {"OCV", "CA"} <= set(seen_names), seen_names


def test_current_technique_advances_across_the_run():
    """M8 at the unit level: `sim._current_technique` must not always report
    the first loaded technique -- that is what hid C1 from every test above
    this section."""
    channel = sim._Channel(techniques=[vendor.TECH_ID.OCV, vendor.TECH_ID.CA])
    cfg = sim.SimConfig(polls_until_stop=3)
    seen = {sim._current_technique(channel, cfg) for channel.polls in range(4)}
    assert seen == {vendor.TECH_ID.OCV, vendor.TECH_ID.CA}
