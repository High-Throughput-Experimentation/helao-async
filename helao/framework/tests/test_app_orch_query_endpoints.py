"""Root-path orchestrator query endpoints (over SP-ORCH-1 domain ops)."""
from datetime import datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from helao.framework.app.factory import makeApp
from helao.framework.domain.run_models import RunSequence, RunExperiment, RunAction


def _seq(name="seq0"):
    return RunSequence(sequence_name=name, sequence_label="lbl",
                       sequence_uuid=uuid4(), sequence_timestamp=datetime.now())


def _exp(name="exp0"):
    return RunExperiment(experiment_name=name, experiment_uuid=uuid4(),
                         experiment_timestamp=datetime.now())


def _act(name="noop"):
    return RunAction(action_name=name, action_uuid=uuid4(),
                     action_timestamp=datetime.now())


def _client(tmp_path):
    app = makeApp("ORCH", save_root=str(tmp_path), group="orchestrator")
    return TestClient(app), app.state.driver


def test_get_histories_root_path(tmp_path):
    client, driver = _client(tmp_path)
    driver.state.action_history = {"a1": {"action_name": "noop"}}
    r = client.post("/get_histories")
    assert r.status_code == 200
    assert r.json()["action"] == [["a1", {"action_name": "noop"}]]


def test_get_step_flags_and_set(tmp_path):
    client, driver = _client(tmp_path)
    assert client.post("/get_step_flags").json() == {
        "actions": False, "experiments": False, "sequences": False}
    r = client.post("/set_step_flag", params={"kind": "actions", "value": True})
    assert r.json() == {"actions": True}
    assert driver.state.step_thru_actions is True


def test_get_orch_state_includes_active(tmp_path):
    client, driver = _client(tmp_path)
    driver.state.sequence_dq = [_seq(), _seq()]
    driver.state.active_sequence = _seq("running_seq")
    body = client.post("/get_orch_state").json()
    assert body["n_sequences"] == 2
    assert "loop_state" in body and "current_stop_message" in body
    assert body["active_sequence"].get("sequence_name") == "running_seq"


def test_list_sequences_limit_and_keys(tmp_path):
    client, driver = _client(tmp_path)
    driver.state.sequence_dq = [_seq("a"), _seq("b"), _seq("c")]
    rows = client.post("/list_sequences", params={"limit": 2}).json()
    assert len(rows) == 2
    assert rows[0]["sequence_name"] == "a"
    # carries the keys RemoteBackend trims to
    assert {"sequence_name", "sequence_label", "sequence_uuid"} <= set(rows[0])


def test_list_experiments_and_actions(tmp_path):
    client, driver = _client(tmp_path)
    driver.state.experiment_dq = [_exp()]
    driver.state.action_dq = [_act()]
    assert len(client.post("/list_experiments").json()) == 1
    assert len(client.post("/list_actions").json()) == 1


def test_get_queue_object_bounds(tmp_path):
    client, driver = _client(tmp_path)
    driver.state.sequence_dq = [_seq("seqX")]
    assert client.post("/get_queue_object",
                       params={"kind": "sequence", "idx": 0}).json()["sequence_name"] == "seqX"
    assert client.post("/get_queue_object",
                       params={"kind": "sequence", "idx": 9}).json() == {}


def test_latest_uuids_and_status_summary(tmp_path):
    client, driver = _client(tmp_path)
    driver.state.sequence_history = {"s1": {}, "s2": {}}
    driver.state.status_summary = {"motor": ("idle", "ok")}
    assert set(client.post("/latest_sequence_uuids").json()) == {"s1", "s2"}
    assert client.post("/get_status_summary").json() == {"motor": ["idle", "ok"]}
