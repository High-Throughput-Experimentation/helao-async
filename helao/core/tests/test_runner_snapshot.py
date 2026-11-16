"""build_runner_snapshot: a /ws_orch-shaped frame from MicroOrch state."""

from types import SimpleNamespace
from uuid import uuid4

from helao.core.models.group_snapshot import build_runner_snapshot
from helao.core.models.machine import MachineModel
from helao.helpers.premodels import Action, Experiment

ORCH_KEYS = {
    "seq_no",
    "t",
    "orch_state",
    "loop_state",
    "loop_intent",
    "closing_out",
    "n_sequences_queued",
    "seq",
    "orch_action",
    "servers",
    "experiments",
    "n_done",
    "n_queued",
    "act_exp",
    "actions",
    "events",
}


def _act(name, server="SIM"):
    a = Action(action_name=name, action_server=MachineModel(server_name=server))
    a.action_uuid = uuid4()
    return a


def micro(**kw):
    exp = Experiment(experiment_name="e_active")
    exp.experiment_uuid = uuid4()
    acts = [_act("wait", "ORCH"), _act("acquire_data")]
    base = dict(
        server_key="RUNNER",
        instance="i-1",
        world_cfg={
            "servers": {
                "SIM": {"host": "h", "port": 8002},
                "ORCH": {"host": "h", "port": 8001},
            }
        },
        active_sequence=None,
        last_sequence=None,
        active_experiment=exp,
        last_experiment=None,
        finished_experiments=[],
        queued_experiments=[],
        planned_actions=acts,
        server_estop={},
        finish_errors={},
        t_dispatch={acts[0].action_uuid: 10.0},
        t_finish={},
        active_actions=lambda: {acts[0].action_uuid: ("ORCH", "wait", False)},
        subscribed=lambda: {"ORCH", "SIM"},
        latest=lambda u: None,
        feed_config=lambda: {"server_key": "RUNNER"},
    )
    base.update(kw)
    return SimpleNamespace(**base), acts


def test_keys_match_orchestrator_frame_plus_runner_fields():
    m, _ = micro()
    snap = build_runner_snapshot(m, seq_no=1, now=11.0, events=[])
    assert ORCH_KEYS <= set(snap)
    assert snap["kind"] == "runner" and snap["instance"] == "i-1"
    assert snap["config"] == {"server_key": "RUNNER"}


def test_running_experiment_rows_and_server_status():
    m, acts = micro()
    snap = build_runner_snapshot(m, seq_no=1, now=11.0, events=[])
    assert snap["loop_state"] == "started" and snap["orch_state"] == "busy"
    assert snap["n_sequences_queued"] == 0 and snap["seq"] is None
    assert [r["state"] for r in snap["experiments"]] == ["active"]
    assert [r["state"] for r in snap["actions"]] == ["active", "queued"]
    assert snap["actions"][0]["t_start"] == 10.0
    rows = {r["key"]: r for r in snap["servers"]}
    assert rows["ORCH"]["status"] == "busy" and rows["ORCH"]["active_action"] == "wait"
    assert rows["SIM"]["status"] == "idle"
    assert (rows["SIM"]["host"], rows["SIM"]["port"]) == ("h", 8002)


def test_finished_action_done_and_error_server():
    m, acts = micro(
        active_actions=lambda: {},
        finish_errors={"SIM": "errored"},
        latest=lambda u: {"action_status": ["errored"]},
    )
    snap = build_runner_snapshot(m, seq_no=2, now=13.0, events=[])
    assert [r["state"] for r in snap["actions"]] == ["error", "error"]
    rows = {r["key"]: r for r in snap["servers"]}
    assert rows["SIM"]["status"] == "error"


def test_estop_and_idle():
    m, _ = micro(
        active_experiment=None, active_actions=lambda: {}, server_estop={"SIM": True}
    )
    snap = build_runner_snapshot(m, seq_no=3, now=14.0, events=[])
    assert snap["loop_state"] == "estopped" and snap["orch_state"] == "estopped"
    assert {r["key"]: r["status"] for r in snap["servers"]}["SIM"] == "estop"
    m2, _ = micro(active_experiment=None, active_actions=lambda: {})
    assert (
        build_runner_snapshot(m2, seq_no=4, now=15.0, events=[])["loop_state"]
        == "stopped"
    )


def test_queued_experiments_carry_qidx_and_no_uuid():
    plans = [SimpleNamespace(experiment_name=f"q{i}") for i in range(3)]
    m, _ = micro(queued_experiments=plans)
    rows = [
        r
        for r in build_runner_snapshot(m, seq_no=1, now=1.0, events=[])["experiments"]
        if r["state"] == "queued"
    ]
    assert [(r["name"], r["qidx"], r["uuid"]) for r in rows] == [
        ("q0", 0, None),
        ("q1", 1, None),
        ("q2", 2, None),
    ]
