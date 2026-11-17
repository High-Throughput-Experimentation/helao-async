"""Runner requirement inference and check (spec: Requirement check)."""

from helao.core.runners.requirements import check, inferred

SRC = """
from helao.core.models.machine import MachineModel
from helao.helpers.premodels import Action
SERVER = "PSTAT"

def _act(server, name, params=None): ...

async def run(orch, plate_id: int = 1):
    await orch.run_action(_act("ORCH", "wait", {"waittime": 1}))
    await orch.run_action(_act("SIM", "acquire_data"))
    await orch.run_action(_act(SERVER, "run_CA"))          # variable: skipped
    await orch.run_action(_act("ORCH", "wait"))            # repeat: deduped
    await orch.run_action(x.make_action("M", "go"))
    a = Action(action_name="measure", action_server=MachineModel(server_name="XRF"))
"""


def test_inferred_collects_literals_only():
    assert inferred(SRC) == {
        "ORCH": ["wait"],
        "SIM": ["acquire_data"],
        "M": ["go"],
        "XRF": ["measure"],
    }


def test_inferred_on_bad_source_is_empty():
    assert inferred("def broken(:\n") == {}


WORLD = {"servers": {"SIM": {"host": "h", "port": 1}, "ORCH": {"host": "h", "port": 2}}}


def _rows(**kw):
    base = dict(
        requires={"SIM": ["acquire_data"], "ORCH": ["wait"], "GONE": ["x"]},
        world_cfg=WORLD,
        endpoints={"SIM": ["acquire_data"], "ORCH": [], "GONE": None},
        status={"SIM": {"estop": False, "endpoints": {}}, "ORCH": {"estop": False}},
    )
    base.update(kw)
    return {(r["server"], r["action"]): r for r in check(**base)}


def test_check_verdicts():
    rows = _rows()
    assert rows[("SIM", "acquire_data")]["verdict"] == "ok"
    assert rows[("ORCH", "wait")]["verdict"] == "fail"  # missing endpoint
    assert rows[("GONE", "x")]["verdict"] == "fail"  # not in config
    assert rows[("GONE", "x")]["in_config"] is False


def test_check_estop_fails_and_busy_warns():
    rows = _rows(
        endpoints={"SIM": ["acquire_data"], "ORCH": ["wait"], "GONE": None},
        status={
            "SIM": {"estop": True, "endpoints": {}},
            "ORCH": {"estop": False, "endpoints": {"wait": {"active_dict": {"u": {}}}}},
        },
    )
    assert rows[("SIM", "acquire_data")]["verdict"] == "fail"
    assert rows[("ORCH", "wait")]["verdict"] == "warn"
    assert rows[("ORCH", "wait")]["busy"] is True


def test_probe_unreachable_server_fails_rows():
    rows = _rows(endpoints={"SIM": None, "ORCH": ["wait"], "GONE": None})
    assert rows[("SIM", "acquire_data")]["reachable"] is False
    assert rows[("SIM", "acquire_data")]["verdict"] == "fail"


def test_inferred_only_downgrades_fail_to_warn():
    rows = _rows(inferred_only=True)
    assert rows[("ORCH", "wait")]["verdict"] == "warn"


def test_busy_is_server_level():
    rows = _rows(
        endpoints={"SIM": ["acquire_data"], "ORCH": ["wait"], "GONE": None},
        status={
            "SIM": {
                "estop": False,
                "endpoints": {"stop_data": {"active_dict": {"u": {}}}},
            },
            "ORCH": {"estop": False},
        },
    )
    assert rows[("SIM", "acquire_data")]["busy"] is True
    assert rows[("SIM", "acquire_data")]["verdict"] == "warn"


def test_str_requires_is_one_action():
    rows = check({"SIM": "acquire_data"}, WORLD, {"SIM": ["acquire_data"]}, {})
    assert [(r["action"], r["verdict"]) for r in rows] == [("acquire_data", "ok")]
