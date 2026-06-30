# helao/framework/tests/test_adapters_operator_backend.py
"""Unit tests for the RemoteBackend orchestrator adapter (ported)."""
import asyncio


def test_remote_backend_dispatch_and_serialize():
    from helao.framework.adapters.operator_backend import RemoteBackend
    from helao.framework.models.errors import ErrorCodes

    calls = []

    async def fake_dispatch(server_key, host, port, endpoint, params_dict=None, json_dict=None, **kw):
        calls.append((endpoint, params_dict, json_dict))
        canned = {
            "list_sequences": [{
                "sequence_name": "seq0", "sequence_label": "lbl", "sequence_uuid": "su",
                "campaign_name": "camp", "campaign_uuid": "cu", "junk": 1,
            }],
            "list_actions": [{
                "action_name": "noop", "action_uuid": "au",
                "action_server": {"server_name": "motor", "machine_name": "host"},
            }],
            "get_orch_state": {"loop_state": "stopped", "n_sequences": 2,
                               "n_experiments": 0, "n_actions": 0,
                               "current_stop_message": ""},
            "get_step_flags": {"actions": True, "experiments": False, "sequences": False},
            "append_sequence": {"sequence_uuid": "newseq"},
        }
        return canned.get(endpoint, {}), ErrorCodes.none

    class _Seq:
        def __init__(self):
            self.sequence_name = "seq0"
        def model_dump(self):
            return {"sequence_name": self.sequence_name}

    be = RemoteBackend.__new__(RemoteBackend)  # bypass lib loading for unit test
    be.orch_key = "ORCH"
    be.host = "127.0.0.1"
    be.port = 8001
    be._dispatch = fake_dispatch
    be._step_flags = {"actions": False, "experiments": False, "sequences": False}

    seqs = asyncio.run(be.list_sequences())
    assert seqs == [{
        "sequence_name": "seq0", "sequence_label": "lbl", "sequence_uuid": "su",
        "campaign_name": "camp", "campaign_uuid": "cu",
    }]
    acts = asyncio.run(be.list_actions())
    assert acts[0]["action_server"] == "motor@host"
    asyncio.run(be.add_sequence(_Seq()))
    ep, _, body = [c for c in calls if c[0] == "append_sequence"][0]
    assert body == {"sequence": {"sequence_name": "seq0"}}
    asyncio.run(be.set_step_flag("actions", True))
    assert be.get_step_flags()["actions"] is True
    print("test_remote_backend_dispatch_and_serialize PASS")


def test_remote_backend_prepend():
    from helao.framework.adapters.operator_backend import RemoteBackend
    from helao.framework.models.errors import ErrorCodes

    calls = []

    async def fake_dispatch(server_key, host, port, endpoint, params_dict=None, json_dict=None, **kw):
        calls.append((endpoint, params_dict, json_dict))
        return {"sequence_uuids": ["u1", "u2"]}, ErrorCodes.none

    class _Seq:
        def __init__(self, name):
            self.name = name
        def model_dump(self):
            return {"sequence_name": self.name}

    be = RemoteBackend.__new__(RemoteBackend)
    be.orch_key = "ORCH"
    be.host = "127.0.0.1"
    be.port = 8001
    be._dispatch = fake_dispatch

    out = asyncio.run(be.prepend_sequences([_Seq("A"), _Seq("B")]))
    assert out == {"sequence_uuids": ["u1", "u2"]}
    ep, _, body = calls[0]
    assert ep == "prepend_sequences"
    assert body == {"sequences": [{"sequence_name": "A"}, {"sequence_name": "B"}]}
    print("test_remote_backend_prepend PASS")


def test_remote_backend_move_remove():
    from helao.framework.adapters.operator_backend import RemoteBackend
    from helao.framework.models.errors import ErrorCodes

    calls = []

    async def fake_dispatch(server_key, host, port, endpoint, params_dict=None, json_dict=None, **kw):
        calls.append((endpoint, params_dict))
        return {"n_sequences": 0}, ErrorCodes.none

    be = RemoteBackend.__new__(RemoteBackend)
    be.orch_key = "ORCH"
    be.host = "127.0.0.1"
    be.port = 8001
    be._dispatch = fake_dispatch

    asyncio.run(be.move_sequence(2, 0))
    asyncio.run(be.remove_sequence(1))
    assert calls[0] == ("move_sequence", {"from_idx": 2, "to_idx": 0})
    assert calls[1] == ("remove_sequence", {"idx": 1})
    print("test_remote_backend_move_remove PASS")


def test_remote_backend_get_queue_object():
    from helao.framework.adapters.operator_backend import RemoteBackend
    from helao.framework.models.errors import ErrorCodes

    calls = []

    async def fake_dispatch(server_key, host, port, endpoint, params_dict=None, json_dict=None, **kw):
        calls.append((endpoint, params_dict))
        return {"sequence_name": "B", "sequence_params": {"x": 1}}, ErrorCodes.none

    be = RemoteBackend.__new__(RemoteBackend)
    be.orch_key = "ORCH"
    be.host = "127.0.0.1"
    be.port = 8001
    be._dispatch = fake_dispatch

    out = asyncio.run(be.get_queue_object("sequence", 1))
    assert out == {"sequence_name": "B", "sequence_params": {"x": 1}}
    assert calls[0] == ("get_queue_object", {"kind": "sequence", "idx": 1})
    print("test_remote_backend_get_queue_object PASS")


def test_stop_forwards_reset_run_id_flag():
    from helao.framework.adapters.operator_backend import RemoteBackend
    from helao.framework.models.errors import ErrorCodes

    calls = []

    async def fake_dispatch(server_key, host, port, endpoint, params_dict=None, json_dict=None, **kw):
        calls.append((endpoint, params_dict))
        return {}, ErrorCodes.none

    be = RemoteBackend.__new__(RemoteBackend)
    be.orch_key = "ORCH"
    be.host = "127.0.0.1"
    be.port = 8001
    be._dispatch = fake_dispatch

    asyncio.run(be.stop())
    asyncio.run(be.stop(reset_run_id=True))
    assert calls[0] == ("stop", {"reset_run_id": False})
    assert calls[1] == ("stop", {"reset_run_id": True})
    print("test_stop_forwards_reset_run_id_flag PASS")


def test_experiment_and_action_queue_calls():
    from helao.framework.adapters.operator_backend import RemoteBackend
    from helao.framework.models.errors import ErrorCodes

    calls = []

    async def fake_dispatch(server_key, host, port, endpoint, params_dict=None, json_dict=None, **kw):
        calls.append((endpoint, params_dict))
        return {}, ErrorCodes.none

    be = RemoteBackend.__new__(RemoteBackend)
    be.orch_key = "ORCH"
    be.host = "127.0.0.1"
    be.port = 8001
    be._dispatch = fake_dispatch

    asyncio.run(be.move_experiment(2, 0))
    asyncio.run(be.remove_experiment(1))
    asyncio.run(be.move_action(0, 3))
    asyncio.run(be.remove_action(2))
    assert calls[0] == ("move_experiment", {"from_idx": 2, "to_idx": 0})
    assert calls[1] == ("remove_experiment", {"idx": 1})
    assert calls[2] == ("move_action", {"from_idx": 0, "to_idx": 3})
    assert calls[3] == ("remove_action", {"idx": 2})
    print("test_experiment_and_action_queue_calls PASS")
