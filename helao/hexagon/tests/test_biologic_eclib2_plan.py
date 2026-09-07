"""Multi-technique plans: `build_plan_from_entries` and `/BIOLOGIC/run_plan`.

EC-Lib 2.0 runs a whole experiment of techniques on one channel in one load,
and has LOOP_START/LOOP_END control techniques for repeats. Neither sibling
backend can do that -- easy-biologic runs one program per action, and the OLE
backend's multi-technique unit is an `.mps` file -- so `run_plan` is registered
on eclib2 only, and there is no parity constraint on its shape.

The subtlety worth most of these tests: loop bounds are given over *plan
entries*, but an entry can expand to more than one EClib2 technique (PEIS
becomes CA+PEIS), so the bounds have to be mapped onto the flattened list. Get
that wrong and the instrument wraps the wrong techniques without complaint.
"""

import asyncio
import math

import pytest

from helao.deploy.hte.drivers.pstat.biologic_eclib2 import data as ec2data
from helao.deploy.hte.drivers.pstat.biologic_eclib2 import technique as ec2tech
from helao.deploy.hte.drivers.pstat.biologic_eclib2.driver import BiologicEclib2Driver
from helao.hexagon.tests.biologic_eclib2_sample_params import params as _raw_params

CHANNEL = 0


def entry(name, **overrides):
    return ec2tech.PlanEntry(name=name, params=_raw_params(name, **overrides))


def identifiers(plan):
    return [t.identifier for t in plan.techniques]


def loop_params(plan):
    """(identifier, loop_id, n_times) for each loop control technique."""
    out = []
    for technique in plan.techniques:
        if technique.identifier not in ec2tech.LOOP_IDENTIFIERS:
            continue
        values = {p.name: p.value for p in technique.params}
        out.append(
            (
                technique.identifier,
                values.get("EC_SDK_LOOP_ID"),
                values.get("EC_SDK_LOOP_N_TIMES"),
            )
        )
    return out


@pytest.fixture
def driver():
    d = BiologicEclib2Driver(
        {"address": "127.0.0.1", "num_channels": 1, "simulate": True}
    )
    try:
        d.connect()
        yield d
    finally:
        d.shutdown()


# --------------------------------------------------------------------------
# the column union
# --------------------------------------------------------------------------


def test_the_union_is_in_a_canonical_order_not_the_order_given():
    # Otherwise the same plan written two ways emits differently-ordered files.
    a = ec2data.union(ec2data.STEP_COLUMNS, ec2data.EIS_COLUMNS)
    b = ec2data.union(ec2data.EIS_COLUMNS, ec2data.STEP_COLUMNS)
    assert a == b
    assert a == tuple(c for c in ec2data.ALL_COLUMNS if c in set(a))


def test_the_union_of_one_set_is_that_set_reordered_canonically():
    assert set(ec2data.union(ec2data.OCV_COLUMNS)) == set(ec2data.OCV_COLUMNS)


def test_a_column_outside_the_contract_is_refused():
    # A silently dropped column would leave the emitted table missing data
    # with nothing reporting it.
    with pytest.raises(ValueError, match="outside the contract"):
        ec2data.union(("t_s", "not_a_column"))


def test_every_per_technique_column_set_is_inside_the_canonical_order():
    for columns in ec2tech.COLUMNS_BY_TECHNIQUE.values():
        assert set(columns) <= set(ec2data.ALL_COLUMNS)


# --------------------------------------------------------------------------
# building a plan
# --------------------------------------------------------------------------


def test_a_plan_needs_at_least_one_technique():
    with pytest.raises(ValueError, match="at least one technique"):
        ec2tech.build_plan_from_entries([])


def test_entries_run_in_the_order_given():
    plan = ec2tech.build_plan_from_entries([entry("OCV"), entry("CA"), entry("CP")])
    assert identifiers(plan) == [
        "EC_SDK_TECHNIQUE_OCV",
        "EC_SDK_TECHNIQUE_CA",
        "EC_SDK_TECHNIQUE_CP",
    ]


def test_an_entry_that_expands_contributes_all_its_techniques():
    # PEIS is sweep-only in EClib2; its bias leg is a CA before it.
    plan = ec2tech.build_plan_from_entries([entry("PEIS")])
    assert identifiers(plan) == ["EC_SDK_TECHNIQUE_CA", "EC_SDK_TECHNIQUE_PEIS"]


def test_the_columns_are_the_union_of_the_entries():
    plan = ec2tech.build_plan_from_entries([entry("CA"), entry("PEIS")])
    assert set(plan.columns) == set(ec2data.STEP_COLUMNS) | set(ec2data.EIS_COLUMNS)
    assert plan.technique_name == "PLAN"


def test_a_plan_of_one_technique_emits_exactly_that_techniques_columns():
    plan = ec2tech.build_plan_from_entries([entry("OCV")])
    assert set(plan.columns) == set(ec2data.OCV_COLUMNS)


def test_per_entry_ranges_are_independent():
    # The whole reason params are per entry rather than shared.
    plan = ec2tech.build_plan_from_entries(
        [entry("CA", IRange="m1"), entry("CP", IRange="u10")]
    )
    ca, cp = plan.techniques
    assert ca.irange == ("I_RANGE_MODE_FIXED", "EC_SDK_IRANGE_1mA")
    assert cp.irange == ("I_RANGE_MODE_FIXED", "EC_SDK_IRANGE_10uA")


def test_a_bad_entry_names_its_position_and_technique():
    # A plan is a list; "Tval__s is required" alone would not say which entry.
    bad = _raw_params("OCV")
    del bad["Tval__s"]
    with pytest.raises(ValueError, match=r"plan entry 1 \(OCV\)"):
        ec2tech.build_plan_from_entries(
            [entry("CA"), ec2tech.PlanEntry(name="OCV", params=bad)]
        )


def test_an_unknown_technique_in_a_plan_names_its_position():
    with pytest.raises(ValueError, match=r"plan entry 0 \(VSCAN\)"):
        ec2tech.build_plan_from_entries([ec2tech.PlanEntry(name="VSCAN", params={})])


# --------------------------------------------------------------------------
# loops
# --------------------------------------------------------------------------


def test_a_loop_wraps_the_entries_it_names():
    plan = ec2tech.build_plan_from_entries(
        [entry("OCV"), entry("CA"), entry("CP")], [ec2tech.PlanLoop(1, 2, 4)]
    )
    assert identifiers(plan) == [
        "EC_SDK_TECHNIQUE_OCV",
        ec2tech.LOOP_START_IDENTIFIER,
        "EC_SDK_TECHNIQUE_CA",
        "EC_SDK_TECHNIQUE_CP",
        ec2tech.LOOP_END_IDENTIFIER,
    ]
    assert loop_params(plan) == [
        (ec2tech.LOOP_START_IDENTIFIER, 0, None),
        (ec2tech.LOOP_END_IDENTIFIER, 0, 4),
    ]


def test_a_loop_over_an_expanding_entry_wraps_the_whole_expansion():
    # This is the mapping that matters: entry 0 is PEIS, which is two
    # techniques, so LOOP_END must come after the *second* one. Wrapping only
    # the CA would repeat the bias without the sweep.
    plan = ec2tech.build_plan_from_entries([entry("PEIS")], [ec2tech.PlanLoop(0, 0, 2)])
    assert identifiers(plan) == [
        ec2tech.LOOP_START_IDENTIFIER,
        "EC_SDK_TECHNIQUE_CA",
        "EC_SDK_TECHNIQUE_PEIS",
        ec2tech.LOOP_END_IDENTIFIER,
    ]


def test_a_loop_spanning_expanding_and_simple_entries_maps_correctly():
    plan = ec2tech.build_plan_from_entries(
        [entry("OCV"), entry("PEIS"), entry("CP")], [ec2tech.PlanLoop(1, 2, 3)]
    )
    assert identifiers(plan) == [
        "EC_SDK_TECHNIQUE_OCV",
        ec2tech.LOOP_START_IDENTIFIER,
        "EC_SDK_TECHNIQUE_CA",
        "EC_SDK_TECHNIQUE_PEIS",
        "EC_SDK_TECHNIQUE_CP",
        ec2tech.LOOP_END_IDENTIFIER,
    ]


def test_nested_loops_open_outermost_first_and_close_innermost_first():
    plan = ec2tech.build_plan_from_entries(
        [entry("OCV"), entry("CA"), entry("CP")],
        [ec2tech.PlanLoop(1, 1, 2), ec2tech.PlanLoop(0, 2, 5)],
    )
    assert identifiers(plan) == [
        ec2tech.LOOP_START_IDENTIFIER,
        "EC_SDK_TECHNIQUE_OCV",
        ec2tech.LOOP_START_IDENTIFIER,
        "EC_SDK_TECHNIQUE_CA",
        ec2tech.LOOP_END_IDENTIFIER,
        "EC_SDK_TECHNIQUE_CP",
        ec2tech.LOOP_END_IDENTIFIER,
    ]
    # Outer loop gets id 0, inner id 1, and each END matches its START.
    assert loop_params(plan) == [
        (ec2tech.LOOP_START_IDENTIFIER, 0, None),
        (ec2tech.LOOP_START_IDENTIFIER, 1, None),
        (ec2tech.LOOP_END_IDENTIFIER, 1, 2),
        (ec2tech.LOOP_END_IDENTIFIER, 0, 5),
    ]


def test_two_loops_closing_at_the_same_entry_close_innermost_first():
    plan = ec2tech.build_plan_from_entries(
        [entry("OCV"), entry("CA")],
        [ec2tech.PlanLoop(0, 1, 2), ec2tech.PlanLoop(1, 1, 3)],
    )
    ends = [p for p in loop_params(plan) if p[0] == ec2tech.LOOP_END_IDENTIFIER]
    # The inner loop (id 1, n=3) must close before the outer (id 0, n=2).
    assert ends == [
        (ec2tech.LOOP_END_IDENTIFIER, 1, 3),
        (ec2tech.LOOP_END_IDENTIFIER, 0, 2),
    ]


def test_loop_ids_are_unique_within_a_plan():
    plan = ec2tech.build_plan_from_entries(
        [entry("OCV"), entry("CA"), entry("CP")],
        [ec2tech.PlanLoop(0, 2, 2), ec2tech.PlanLoop(1, 1, 2)],
    )
    starts = [p[1] for p in loop_params(plan) if p[0] == ec2tech.LOOP_START_IDENTIFIER]
    assert len(starts) == len(set(starts))


@pytest.mark.parametrize(
    "loop,message",
    [
        (ec2tech.PlanLoop(0, 5, 2), "outside the plan"),
        (ec2tech.PlanLoop(-1, 1, 2), "outside the plan"),
        (ec2tech.PlanLoop(1, 0, 2), "precedes its start"),
        (ec2tech.PlanLoop(0, 1, 0), "at least once"),
    ],
)
def test_a_malformed_loop_is_refused(loop, message):
    with pytest.raises(ValueError, match=message):
        ec2tech.build_plan_from_entries([entry("OCV"), entry("CA")], [loop])


def test_straddling_loops_are_refused():
    # The firmware calls these "intricated" and rejects them with an event
    # rather than at load, so catching it here fails before the cell is
    # polarised.
    with pytest.raises(ValueError, match="overlap without nesting"):
        ec2tech.build_plan_from_entries(
            [entry("OCV"), entry("CA"), entry("CP")],
            [ec2tech.PlanLoop(0, 1, 2), ec2tech.PlanLoop(1, 2, 2)],
        )


def test_more_loops_than_the_firmware_supports_are_refused():
    entries = [entry("OCV") for _ in range(12)]
    loops = [ec2tech.PlanLoop(i, i, 2) for i in range(11)]
    with pytest.raises(ValueError, match="at most 10 loops"):
        ec2tech.build_plan_from_entries(entries, loops)


def test_exactly_ten_loops_are_allowed():
    entries = [entry("OCV") for _ in range(10)]
    loops = [ec2tech.PlanLoop(i, i, 2) for i in range(10)]
    plan = ec2tech.build_plan_from_entries(entries, loops)
    assert len([p for p in loop_params(plan) if p[2] is not None]) == 10


def test_a_loop_technique_has_no_data_reader():
    # It measures nothing; handing its buffer to a BL_ProcessRawTo* would
    # decode whatever is there as a measurement.
    plan = ec2tech.build_plan_from_entries([entry("OCV")], [ec2tech.PlanLoop(0, 0, 2)])
    for technique in plan.techniques:
        if technique.identifier in ec2tech.LOOP_IDENTIFIERS:
            assert technique.reader not in ec2tech.READERS
            assert technique.identifier not in ec2tech.READER_BY_IDENTIFIER


# --------------------------------------------------------------------------
# the technique object and the driver
# --------------------------------------------------------------------------


def test_plan_technique_validates_eagerly():
    # An unbuildable plan must fail the endpoint call, not the executor's
    # _pre_exec with the cell already claimed.
    with pytest.raises(ValueError):
        ec2tech.plan_technique([ec2tech.PlanEntry(name="VSCAN", params={})])


def test_plan_technique_carries_its_entries_and_columns():
    technique = ec2tech.plan_technique([entry("CA"), entry("PEIS")])
    assert technique.technique_name == "PLAN"
    assert technique.entries is not None and len(technique.entries) == 2
    assert set(technique.columns) == set(ec2data.STEP_COLUMNS) | set(
        ec2data.EIS_COLUMNS
    )


def test_a_resolved_single_technique_carries_no_entries():
    assert ec2tech.resolve("CA").entries is None


def test_the_driver_accepts_a_plan_technique_through_the_normal_setup(driver):
    technique = ec2tech.plan_technique([entry("OCV"), entry("CA")])
    response = driver.setup(technique=technique, action_params={"channel": CHANNEL})
    assert response.response == "success", response.message
    assert response.data["techniques"] == [
        "EC_SDK_TECHNIQUE_OCV",
        "EC_SDK_TECHNIQUE_CA",
    ]


def test_a_plan_runs_end_to_end_and_emits_the_union(driver):
    technique = ec2tech.plan_technique([entry("CA"), entry("PEIS")])
    driver.setup(technique=technique, action_params={"channel": CHANNEL})
    driver.start_channel(CHANNEL)

    async def drain():
        table = {c: [] for c in technique.columns}
        for _ in range(80):
            response = await driver.get_data(CHANNEL)
            assert response.response == "success", response.message
            for column, values in response.data.items():
                table[column].extend(values)
            if response.message == "done":
                return table
        raise AssertionError("plan never reported done")

    table = asyncio.run(drain())
    assert set(table) == set(technique.columns)
    lengths = {len(v) for v in table.values()}
    assert len(lengths) == 1 and lengths.pop() > 0
    # The CA entry's rows report no frequency; the sweep's do.
    assert set(table["process"]) == {0, 1}
    # P_W comes from the step legs, and is NaN on the sweep rows.
    assert any(not math.isnan(v) for v in table["P_W"])
    assert any(math.isnan(v) for v in table["P_W"])


def test_a_plan_with_a_loop_runs_end_to_end(driver):
    # The simulator does not replay a loop's span, so this asserts the loop
    # control techniques do not break the run -- not that the loop repeated.
    technique = ec2tech.plan_technique(
        [entry("OCV"), entry("CA")], [ec2tech.PlanLoop(0, 1, 3)]
    )
    driver.setup(technique=technique, action_params={"channel": CHANNEL})
    driver.start_channel(CHANNEL)

    async def drain():
        rows = 0
        for _ in range(80):
            response = await driver.get_data(CHANNEL)
            assert response.response == "success", response.message
            rows += len(response.data["t_s"])
            if response.message == "done":
                return rows
        raise AssertionError("plan never reported done")

    assert asyncio.run(drain()) > 0


def test_the_loop_controls_reach_the_instrument(driver):
    technique = ec2tech.plan_technique([entry("OCV")], [ec2tech.PlanLoop(0, 0, 7)])
    driver.setup(technique=technique, action_params={"channel": CHANNEL})
    added = [
        call[2].name
        for call in driver._client._api.calls
        if call[0] == "BL_AddTechnique"
    ]
    assert added == [
        "EC_SDK_TECHNIQUE_LOOP_START",
        "EC_SDK_TECHNIQUE_OCV",
        "EC_SDK_TECHNIQUE_LOOP_END",
    ]
    loop_end = [
        t
        for t in driver._client._api.techniques.values()
        if t.identifier.name == "EC_SDK_TECHNIQUE_LOOP_END"
    ][0]
    assert loop_end.params["EC_SDK_LOOP_N_TIMES"] == 7
    assert loop_end.params["EC_SDK_LOOP_ID"] == 0


# --------------------------------------------------------------------------
# the endpoint
# --------------------------------------------------------------------------


def _routes_for(backend, params):
    import tempfile

    from fastapi.testclient import TestClient

    from helao.helpers import config_loader

    config_loader.CONFIG = {
        "root": tempfile.mkdtemp(prefix="helao_run_plan_test_"),
        "servers": {
            "BIOLOGIC": {
                "group": "action",
                "host": "127.0.0.1",
                "port": 8000,
                "params": {**params, "pstat_backend": backend},
            }
        },
    }
    from helao.deploy.hte.servers.action import biologic_server

    app = biologic_server.makeApp("BIOLOGIC")
    try:
        with TestClient(app):
            pass
    except Exception:
        # The eclib backend cannot connect off-station; the route table is
        # still built by then.
        pass
    return {route.path for route in app.routes}


def test_run_plan_registers_on_the_eclib2_backend():
    routes = _routes_for(
        "eclib2", {"address": "127.0.0.1", "num_channels": 1, "simulate": True}
    )
    assert "/BIOLOGIC/run_plan" in routes


def test_run_plan_does_not_register_on_the_olecom_backend():
    # The OLE backend's multi-technique unit is an .mps file, which its own
    # run_protocol covers. Advertising run_plan there would offer a route that
    # could only fail.
    routes = _routes_for(
        "olecom", {"address": "127.0.0.1", "num_channels": 1, "simulate": True}
    )
    assert "/BIOLOGIC/run_plan" not in routes


def test_the_seven_technique_routes_are_unchanged_by_the_addition():
    routes = _routes_for(
        "eclib2", {"address": "127.0.0.1", "num_channels": 1, "simulate": True}
    )
    for name in ec2tech.TECHNIQUE_NAMES:
        assert f"/BIOLOGIC/run_{name}" in routes
