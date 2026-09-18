"""TTL is two techniques, loaded first. There is no trigger call in EClib1."""

import pytest

from helao.deploy.hte.drivers.pstat.biologic import vendor
from helao.deploy.hte.drivers.pstat.biologic.technique import (
    BIOTECHS,
    TechniqueError,
    plan_for,
)

CA = dict(
    Vval__V=0.5,
    Tval__s=1.0,
    AcqInterval__s=0.01,
    AcqInterval__A=10.0,
    IRange="AUTO",
    ERange="AUTO",
    Bandwidth="BW4",
)
NO_TTL = {"ttl": "none", "ttl_logic": 1, "ttl_duration": 1.0}
TTL_IN = {"ttl": "in", "ttl_logic": 1, "ttl_duration": 1.0}
TTL_OUT = {"ttl": "out", "ttl_logic": 1, "ttl_duration": 2.5}


def plan(ttl, **overrides):
    tech = BIOTECHS["CA"]
    return plan_for(tech, {**tech.defaults, **CA, **overrides}, ttl)


def labels(step):
    return {label for label, _, _ in step.params}


def value(step, label):
    return next(v for lab, v, _ in step.params if lab == label)


def test_no_ttl_loads_one_technique():
    p = plan(NO_TTL)
    assert len(p.steps) == 1
    assert p.steps[0].ecc_stem == "ca"
    assert p.tech_ids == [vendor.TECH_ID.CA]


def test_ttl_in_prepends_trigger_in():
    p = plan(TTL_IN)
    assert [s.ecc_stem for s in p.steps] == ["TI", "ca"]
    assert p.tech_ids == [vendor.TECH_ID.TI, vendor.TECH_ID.CA]


def test_ttl_out_prepends_trigger_out():
    p = plan(TTL_OUT)
    assert [s.ecc_stem for s in p.steps] == ["TO", "ca"]
    assert p.tech_ids == [vendor.TECH_ID.TO, vendor.TECH_ID.CA]


def test_trigger_in_sends_only_the_logic_parameter():
    p = plan(TTL_IN)
    assert labels(p.steps[0]) == {"Trigger_Logic"}
    assert value(p.steps[0], "Trigger_Logic") == 1


def test_trigger_out_also_sends_a_duration():
    p = plan(TTL_OUT)
    assert labels(p.steps[0]) == {"Trigger_Logic", "Trigger_Duration"}
    assert value(p.steps[0], "Trigger_Duration") == pytest.approx(2.5)


def test_trigger_duration_is_a_single_and_logic_an_int():
    p = plan(TTL_OUT)
    assert isinstance(value(p.steps[0], "Trigger_Duration"), float)
    assert isinstance(value(p.steps[0], "Trigger_Logic"), int)


def test_an_unrecognised_ttl_mode_is_refused():
    """A typo must not silently run without the trigger the caller asked for."""
    with pytest.raises(TechniqueError, match="sideways"):
        plan({"ttl": "sideways", "ttl_logic": 1, "ttl_duration": 1.0})


def test_a_missing_ttl_dict_means_no_trigger():
    tech = BIOTECHS["CA"]
    p = plan_for(tech, {**tech.defaults, **CA}, None)
    assert len(p.steps) == 1


def test_the_measurement_keeps_its_own_parameters_when_a_trigger_is_added():
    p = plan(TTL_OUT)
    assert "Voltage_step" in labels(p.steps[1])
    assert "Trigger_Logic" not in labels(p.steps[1])


def test_the_trigger_is_always_at_index_zero():
    """The driver reads the technique list back and asserts exactly this."""
    for ttl in (TTL_IN, TTL_OUT):
        assert plan(ttl).tech_ids[0] in (vendor.TECH_ID.TI, vendor.TECH_ID.TO)


def test_ttl_works_for_every_technique_whose_endpoint_offers_it():
    """Every run_* endpoint except run_PEIS/run_GEIS' siblings takes TTLwait
    and TTLsend, so no technique may reject a trigger."""
    for name in ("OCV", "CA", "CP", "CV", "PEIS", "GEIS"):
        tech = BIOTECHS[name]
        args = {**tech.defaults, **_MINIMAL[name]}
        assert plan_for(tech, args, TTL_IN).tech_ids[0] == vendor.TECH_ID.TI


_MINIMAL = {
    "OCV": dict(Tval__s=1.0, AcqInterval__s=0.1),
    "CA": CA,
    "CP": dict(
        Ival__A=1e-3,
        Tval__s=1.0,
        AcqInterval__s=0.01,
        AcqInterval__V=0.001,
        IRange="AUTO",
        ERange="AUTO",
        Bandwidth="BW4",
    ),
    "CV": dict(
        Vinit__V=0.0,
        Vapex1__V=1.0,
        Vapex2__V=-1.0,
        Vfinal__V=0.0,
        ScanRate__V_s=1.0,
        AcqInterval__s=0.1,
        Cycles=1,
        IRange="AUTO",
        ERange="AUTO",
        Bandwidth="BW4",
    ),
    "PEIS": dict(
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
    ),
    "GEIS": dict(
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
    ),
}
