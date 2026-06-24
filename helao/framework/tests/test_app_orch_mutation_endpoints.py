"""Root-path orchestrator mutation + control endpoints."""
from datetime import datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from helao.framework.app.factory import makeApp
from helao.framework.domain.run_models import RunSequence, RunExperiment


def _seq_dict(name="seq0"):
    return RunSequence(sequence_name=name, sequence_label="lbl",
                       sequence_uuid=uuid4(),
                       sequence_timestamp=datetime.now()).as_dict()


def _exp_dict(name="exp0"):
    return RunExperiment(experiment_name=name, experiment_uuid=uuid4(),
                         experiment_timestamp=datetime.now()).as_dict()


def _client(tmp_path):
    app = makeApp("ORCH", save_root=str(tmp_path), group="orchestrator")
    return TestClient(app), app.state.driver


def _names(dq):
    return [s.sequence_name for s in dq]


def test_append_sequence_enqueues(tmp_path):
    client, driver = _client(tmp_path)
    r = client.post("/append_sequence", json={"sequence": _seq_dict("a")})
    assert r.status_code == 200
    assert "sequence_uuid" in r.json()
    assert _names(driver.state.sequence_dq) == ["a"]


def test_prepend_sequences_order_and_uuids(tmp_path):
    client, driver = _client(tmp_path)
    client.post("/append_sequence", json={"sequence": _seq_dict("existing")})
    body = client.post("/prepend_sequences",
                       json={"sequences": [_seq_dict("a"), _seq_dict("b")]}).json()
    assert _names(driver.state.sequence_dq) == ["a", "b", "existing"]
    assert len(body) == 2


def test_move_and_remove_sequence(tmp_path):
    client, driver = _client(tmp_path)
    for n in ("a", "b", "c"):
        client.post("/append_sequence", json={"sequence": _seq_dict(n)})
    client.post("/move_sequence", params={"from_idx": 0, "to_idx": 2})
    assert _names(driver.state.sequence_dq) == ["b", "c", "a"]
    client.post("/remove_sequence", params={"idx": 1})
    assert _names(driver.state.sequence_dq) == ["b", "a"]


def test_insert_sequence(tmp_path):
    client, driver = _client(tmp_path)
    client.post("/append_sequence", json={"sequence": _seq_dict("a")})
    client.post("/insert_sequence", params={"idx": 0}, json={"sequence": _seq_dict("z")})
    assert _names(driver.state.sequence_dq) == ["z", "a"]


def test_append_and_insert_experiment(tmp_path):
    client, driver = _client(tmp_path)
    client.post("/append_experiment", json={"experiment": _exp_dict("a")})
    client.post("/insert_experiment", params={"idx": 0}, json={"experiment": _exp_dict("z")})
    assert [e.experiment_name for e in driver.state.experiment_dq] == ["z", "a"]


def test_add_split_sequences_fallback(tmp_path):
    client, driver = _client(tmp_path)
    body = client.post("/add_split_sequences", json={"sequence": _seq_dict("s")}).json()
    assert isinstance(body, list) and len(body) == 1
    assert _names(driver.state.sequence_dq) == ["s"]


def test_clear_ops(tmp_path):
    client, driver = _client(tmp_path)
    client.post("/append_sequence", json={"sequence": _seq_dict("a")})
    client.post("/append_experiment", json={"experiment": _exp_dict("b")})
    client.post("/clear_sequences")
    client.post("/clear_experiments")
    client.post("/clear_actions")
    assert driver.state.sequence_dq == []
    assert driver.state.experiment_dq == []
    assert driver.state.action_dq == []


def test_control_aliases_at_root(tmp_path):
    client, driver = _client(tmp_path)
    # no work queued: start returns immediately with a loop_state
    assert "loop_state" in client.post("/start").json()
    assert "loop_intent" in client.post("/stop").json()
    assert "loop_state" in client.post("/estop").json()
    assert "loop_state" in client.post("/clear_estop").json()
