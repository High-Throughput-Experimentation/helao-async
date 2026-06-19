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


class _FakeDirsOp:
    def __init__(self):
        import tempfile
        from pathlib import Path
        self.root = Path(tempfile.mkdtemp())
        self.log_root = None
        self.user_exp = None
        self.user_seq = None


class _FakeVisOp:
    """Vis stand-in with the minimum surface BokehOperator reads."""
    def __init__(self, doc):
        self.doc = doc
        self.helaodirs = _FakeDirsOp()
        self.world_cfg = {
            "servers": {"ORCH": {"group": "orchestrator", "host": "h", "port": 1}},
            "root": str(self.helaodirs.root),
            "loaded_config_path": "test.yml",
        }
        self.server_cfg = {"params": {}}

    def print_message(self, *a, **k):
        pass


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


def test_local_backend_normalized_shapes():
    from helao.core.servers.operator.orch_backend import LocalBackend

    class _Seq:
        def as_dict(self):
            return {
                "sequence_name": "seq0", "sequence_label": "lbl",
                "sequence_uuid": "su", "campaign_name": "camp",
                "campaign_uuid": "cu", "extra": "ignored",
            }

    class _Srv:
        def disp_name(self):
            return "motor@host"

    class _Act:
        action_server = _Srv()
        def as_dict(self):
            return {"action_name": "noop", "action_uuid": "au"}

    class _Orch2(_FakeOrch):
        def list_sequences(self, limit=10):
            return [_Seq()]
        def list_experiments(self, limit=10):
            return [type("E", (), {"as_dict": lambda s: {"experiment_name": "exp0", "experiment_uuid": "eu"}})()]
        def list_actions(self, limit=10):
            return [_Act()]
        sequence_lib = {"seq0": lambda x=1: [x]}
        experiment_lib = {}
        def unpack_sequence(self, sequence_name, sequence_params):
            return self.sequence_lib[sequence_name](**sequence_params)

    orch = _Orch2()
    be = LocalBackend(orch)
    seqs = asyncio.run(be.list_sequences())
    assert seqs == [{
        "sequence_name": "seq0", "sequence_label": "lbl", "sequence_uuid": "su",
        "campaign_name": "camp", "campaign_uuid": "cu",
    }]
    acts = asyncio.run(be.list_actions())
    assert acts == [{"action_name": "noop", "action_server": "motor@host", "action_uuid": "au"}]
    assert be.get_step_flags() == {"actions": False, "experiments": False, "sequences": False}
    assert be.unpack_sequence("seq0", {"x": 5}) == [5]
    asyncio.run(be.clear_sequences())
    assert "sequences" in orch.cleared
    print("test_local_backend_normalized_shapes PASS")


def test_remote_backend_dispatch_and_serialize():
    from helao.core.servers.operator.orch_backend import RemoteBackend
    from helao.core.error import ErrorCodes

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
    assert acts[0]["action_server"] == "motor"
    asyncio.run(be.add_sequence(_Seq()))
    ep, _, body = [c for c in calls if c[0] == "append_sequence"][0]
    assert body == {"sequence": {"sequence_name": "seq0"}}
    asyncio.run(be.set_step_flag("actions", True))
    assert be.get_step_flags()["actions"] is True
    print("test_remote_backend_dispatch_and_serialize PASS")


def test_operator_accepts_backend():
    import inspect
    from helao.core.servers.operator.bokeh_operator import BokehOperator
    params = list(inspect.signature(BokehOperator.__init__).parameters)
    assert params == ["self", "vis_serv", "backend"], params
    print("test_operator_accepts_backend PASS")


class _MockBackend:
    def __init__(self):
        self.sequence_lib = {"seq0": lambda x=1: [x]}
        self.experiment_lib = {}
        self._flags = {"actions": False, "experiments": False, "sequences": False}
        self.started = False
        self.on_change = None

    def unpack_sequence(self, sequence_name, sequence_params):
        return self.sequence_lib[sequence_name](**sequence_params)

    def get_step_flags(self):
        return dict(self._flags)

    async def set_step_flag(self, kind, value):
        self._flags[kind] = value

    async def list_sequences(self):
        return [{"sequence_name": "seq0", "sequence_label": "l",
                 "sequence_uuid": "su", "campaign_name": "c", "campaign_uuid": "cu"}]

    async def list_experiments(self):
        return [{"experiment_name": "exp0", "experiment_uuid": "eu"}]

    async def list_actions(self):
        return [{"action_name": "noop", "action_server": "motor", "action_uuid": "au"}]

    async def get_histories(self):
        return {"action": [], "experiment": [], "sequence": []}

    async def get_status_summary(self):
        return {"motor": ["idle", "ok"]}

    async def get_orch_state(self):
        return {"loop_state": "stopped", "active_sequence": {}, "active_experiment": {},
                "n_sequences": 1, "n_experiments": 1, "n_actions": 1,
                "current_stop_message": ""}

    async def add_sequence(self, sequence):
        return "su"

    async def add_split_sequences(self, sequence):
        return ["su"]

    async def start(self):
        self.started = True

    async def stop(self): ...
    async def skip(self): ...
    async def estop(self): ...
    async def clear_sequences(self): ...
    async def clear_experiments(self): ...
    async def clear_actions(self): ...

    def subscribe(self, on_change):
        self.on_change = on_change

    def close(self):
        self.on_change = None


def test_operator_tables_from_backend():
    from bokeh.document import Document
    from helao.core.servers.operator.bokeh_operator import BokehOperator

    doc = Document()
    vis = _FakeVisOp(doc)
    be = _MockBackend()
    op = BokehOperator(vis, be)
    assert be.on_change is not None
    asyncio.run(op.update_tables())
    assert op.sequence_source.data["sequence_name"] == ["seq0"]
    assert op.action_source.data["action_server"] == ["motor"]
    assert op.action_server_source.data["server_status"] == ["idle"]
    assert "stop" in op.orch_status_button.label.lower()
    op.cleanup_session(None)
    print("test_operator_tables_from_backend PASS")


def test_plate_api_disabled_by_default():
    from bokeh.document import Document
    from helao.core.servers.operator.bokeh_operator import BokehOperator
    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    assert op.dataAPI is None  # no plate_api param -> disabled
    op.cleanup_session(None)
    print("test_plate_api_disabled_by_default PASS")


def test_shim_exposes_makebokehapp():
    import importlib, inspect
    for mod in ("helao.deploy.test.servers.operator.standalone_operator",
                "helao.deploy.hte.servers.operator.standalone_operator"):
        m = importlib.import_module(mod)
        assert hasattr(m, "makeBokehApp"), mod
        params = list(inspect.signature(m.makeBokehApp).parameters)
        assert params == ["doc", "confPrefix", "server_key", "helao_repo_root"], (mod, params)
    print("test_shim_exposes_makebokehapp PASS")


def run_all():
    test_endpoint_helpers_shapes()
    test_local_backend_normalized_shapes()
    test_remote_backend_dispatch_and_serialize()
    test_operator_accepts_backend()
    test_operator_tables_from_backend()
    test_plate_api_disabled_by_default()
    test_shim_exposes_makebokehapp()
    print("ALL STANDALONE_OPERATOR TESTS PASS")


if __name__ == "__main__":
    run_all()
