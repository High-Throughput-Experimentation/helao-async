"""Standalone tests for the standalone Bokeh operator. No pytest; run with:

    PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao \
        python -m helao.deploy.test.tests.test_standalone_operator
"""
import asyncio
import inspect


class _FakeGlobalStatus:
    def __init__(self):
        self.loop_state = "stopped"
        self.orch_state = "stopped"
        self.loop_intent = "none"

    def as_json(self):
        return {"loop_state": self.loop_state}


class _FakeOrch:
    """Minimal stand-in for Orch exposing only what the new endpoints/backends touch."""

    def __init__(self):
        self.globalstatusmodel = _FakeGlobalStatus()
        self.step_thru_actions = False
        self.step_thru_experiments = False
        self.step_thru_sequences = False
        self.status_summary = {"motor": ("idle", "ok")}
        self.action_history = {"a1": {"action_name": "noop", "action_server": "motor"}}
        self.experiment_history = {"e1": {"experiment_name": "exp0"}}
        self.sequence_history = {"s1": {"sequence_name": "seq0"}}
        self.sequence_dq = [1, 2, 3]
        self.experiment_dq = [1]
        self.action_dq = []
        self.cleared = []

    def list_sequences(self, limit=10):
        return []

    async def clear_sequences(self):
        self.cleared.append("sequences")

    async def add_split_sequences(self, sequence):
        return ["uuid-1", "uuid-2"]


def test_endpoint_helpers_shapes():
    # Endpoint handler bodies are extracted as module-level helpers for testability.
    from helao.core.servers import orch_api

    orch = _FakeOrch()
    assert orch_api._histories_payload(orch) == {
        "action": [("a1", {"action_name": "noop", "action_server": "motor"})],
        "experiment": [("e1", {"experiment_name": "exp0"})],
        "sequence": [("s1", {"sequence_name": "seq0"})],
    }
    assert orch_api._status_summary_payload(orch) == {"motor": ["idle", "ok"]}
    assert orch_api._step_flags_payload(orch) == {
        "actions": False,
        "experiments": False,
        "sequences": False,
    }
    orch_api._set_step_flag(orch, "actions", True)
    assert orch.step_thru_actions is True
    assert orch_api._queue_counts(orch) == {
        "n_sequences": 3,
        "n_experiments": 1,
        "n_actions": 0,
    }
    print("test_endpoint_helpers_shapes PASS")


if __name__ == "__main__":
    test_endpoint_helpers_shapes()
    print("ok")
