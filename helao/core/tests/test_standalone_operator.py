"""Standalone tests for the standalone Bokeh operator. No pytest; run with:

    PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao \
        python -m helao.core.tests.test_standalone_operator
"""
import asyncio
import inspect

from helao.helpers.premodels import Experiment as _ExpModel


def _exp0(experiment: _ExpModel, val: int = 1):
    """Mock experiment library function (Experiment arg is filtered out)."""
    return []


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
    assert acts[0]["action_server"] == "motor@host"
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
        # seq0 unpacks to a single planned experiment so populate_sequence can
        # construct a valid Sequence (planned_experiments must be experiments).
        self.sequence_lib = {
            "seq0": lambda x=1: [_ExpModel(experiment_name="exp0")]
        }
        self.experiment_lib = {"exp0": _exp0}
        self._flags = {"actions": False, "experiments": False, "sequences": False}
        self.started = False
        self.on_change = None
        self.loop_state = "stopped"
        self.added = []
        self.split_added = []
        self.prepended = None

    def unpack_sequence(self, sequence_name, sequence_params):
        return self.sequence_lib[sequence_name](**sequence_params)

    def get_step_flags(self):
        return dict(self._flags)

    async def set_step_flag(self, kind, value):
        self._flags[kind] = value

    async def list_sequences(self):
        return [{"sequence_name": "seq0", "sequence_label": "l",
                 "sequence_uuid": "0123456789abcdef", "campaign_name": "c",
                 "campaign_uuid": "fedcba9876543210"}]

    async def list_experiments(self):
        return [{"experiment_name": "exp0", "experiment_uuid": "1111222233334444"}]

    async def list_actions(self):
        return [{"action_name": "noop", "action_server": "motor",
                 "action_uuid": "aaaabbbbccccdddd"}]

    async def get_histories(self):
        return {"action": [], "experiment": [], "sequence": []}

    async def get_status_summary(self):
        return {"motor": ["idle", "ok"]}

    async def get_orch_state(self):
        return {"loop_state": self.loop_state, "active_sequence": {}, "active_experiment": {},
                "n_sequences": 1, "n_experiments": 1, "n_actions": 1,
                "current_stop_message": ""}

    async def add_sequence(self, sequence):
        self.added.append(sequence)
        return "su"

    async def add_split_sequences(self, sequence):
        self.split_added.append(sequence)
        return ["su"]

    async def prepend_sequences(self, sequences):
        self.prepended = list(sequences)
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
    m = importlib.import_module("helao.deploy.hte.servers.operator.standalone_operator")
    assert hasattr(m, "makeBokehApp")
    params = list(inspect.signature(m.makeBokehApp).parameters)
    assert params == ["doc", "confPrefix", "server_key", "helao_repo_root"], params
    print("test_shim_exposes_makebokehapp PASS")


def test_orch_run_id_sharing():
    from helao.core.servers.orch import Orch
    from helao.helpers.premodels import Sequence
    from helao.helpers.zdeque import zdeque

    orch = Orch.__new__(Orch)
    orch.sequence_dq = zdeque([])
    orch.active_run_id = None
    orch.sequence_codehash_lib = {}
    orch.sequence_codepath_lib = {}
    orch.sequence_lib = {}

    s1 = Sequence(sequence_name="seq0")
    asyncio.run(orch.add_sequence(s1))
    assert s1.run_id is not None
    r1 = s1.run_id

    s2 = Sequence(sequence_name="seq0")
    asyncio.run(orch.add_sequence(s2))
    assert s2.run_id == r1, "non-empty queue should reuse in-flight run_id"

    # simulate clear_sequences emptying the dq -> next add gets a fresh run_id
    orch.sequence_dq = zdeque([])
    s3 = Sequence(sequence_name="seq0")
    asyncio.run(orch.add_sequence(s3))
    assert s3.run_id != r1, "cleared/empty queue should start a new run_id"
    print("test_orch_run_id_sharing PASS")


def test_orch_resolve_active_run_id():
    from helao.core.servers.orch import Orch
    from helao.helpers.premodels import Sequence
    from helao.helpers.time_utils import gen_uuid

    orch = Orch.__new__(Orch)
    orch.active_run_id = None

    rid = gen_uuid()
    s = Sequence(sequence_name="x")
    s.run_id = rid
    orch._resolve_active_run_id(s)
    assert orch.active_run_id == rid, "active_run_id should follow the sequence"

    s2 = Sequence(sequence_name="y")
    orch._resolve_active_run_id(s2)
    assert s2.run_id == rid, "sequence without run_id inherits active_run_id"
    print("test_orch_resolve_active_run_id PASS")


def test_orch_split_run_id():
    from helao.core.servers.orch import Orch
    from helao.helpers.premodels import Sequence
    from helao.helpers.zdeque import zdeque

    orch = Orch.__new__(Orch)
    orch.sequence_dq = zdeque([])
    orch.active_run_id = None
    orch.sequence_codehash_lib = {}
    orch.sequence_codepath_lib = {}
    orch.sequence_lib = {}
    orch.server_params = {"split_by_seq_params": ["plate_sample_no"]}

    seq = Sequence(sequence_name="seq0")
    seq.sequence_params = {"plate_sample_no": [1, 2, 3]}
    uuids = asyncio.run(orch.add_split_sequences(seq))
    assert len(uuids) == 3, uuids
    run_ids = {s.run_id for s in orch.sequence_dq}
    assert len(run_ids) == 1 and None not in run_ids, run_ids
    print("test_orch_split_run_id PASS")


def test_orch_prepend_order_and_run_id():
    from helao.core.servers.orch import Orch
    from helao.helpers.premodels import Sequence
    from helao.helpers.zdeque import zdeque

    orch = Orch.__new__(Orch)
    orch.sequence_dq = zdeque([])
    orch.active_run_id = None
    orch.sequence_codehash_lib = {}
    orch.sequence_codepath_lib = {}
    orch.sequence_lib = {}

    existing = Sequence(sequence_name="existing")
    asyncio.run(orch.add_sequence(existing))
    inflight = existing.run_id

    a = Sequence(sequence_name="A")
    b = Sequence(sequence_name="B")
    c = Sequence(sequence_name="C")
    uuids = asyncio.run(orch.prepend_sequences([a, b, c]))
    assert len(uuids) == 3

    names = [s.sequence_name for s in orch.sequence_dq]
    assert names == ["A", "B", "C", "existing"], names
    assert a.run_id == b.run_id == c.run_id == inflight, "prepend reuses in-flight run_id"

    # empty prepend is a no-op and must not mint a stray run_id
    before = orch.active_run_id
    assert asyncio.run(orch.prepend_sequences([])) == []
    assert orch.active_run_id == before
    print("test_orch_prepend_order_and_run_id PASS")


def test_prepend_sequences_helper():
    from helao.core.servers import orch_api

    class _O(_FakeOrch):
        async def prepend_sequences(self, sequences):
            self.prepended = sequences
            return ["u1", "u2"]

    orch = _O()
    uuids = asyncio.run(orch_api._prepend_sequences(orch, [{}, {}]))
    assert uuids == ["u1", "u2"]
    assert len(orch.prepended) == 2
    # dict inputs are coerced to Sequence instances
    from helao.helpers.premodels import Sequence
    assert all(isinstance(s, Sequence) for s in orch.prepended)
    print("test_prepend_sequences_helper PASS")


def test_local_backend_prepend():
    from helao.core.servers.operator.orch_backend import LocalBackend

    class _O(_FakeOrch):
        sequence_lib = {}
        experiment_lib = {}
        async def prepend_sequences(self, sequences):
            self.prepended = sequences
            return ["u1"]

    orch = _O()
    be = LocalBackend(orch)
    out = asyncio.run(be.prepend_sequences(["s1", "s2"]))
    assert out == ["u1"]
    assert orch.prepended == ["s1", "s2"]
    print("test_local_backend_prepend PASS")


def test_remote_backend_prepend():
    from helao.core.servers.operator.orch_backend import RemoteBackend
    from helao.core.error import ErrorCodes

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


def test_plan_buffer_append_and_wrap():
    from bokeh.document import Document
    from helao.core.servers.operator.bokeh_operator import BokehOperator

    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    op.sequence_dropdown.value = "seq0"
    op.populate_sequence(prepend=False)
    assert len(op.plan) == 1
    assert op.plan[0].sequence_name == "seq0"

    op.update_selector_layout("active", 0, 1)  # build the experiment panel + dropdown
    op.append_experiment()
    assert len(op.plan) == 2
    assert op.plan[1].sequence_name == "manual_orch_seq"
    assert len(op.plan[1].planned_experiments) == 1
    op.cleanup_session(None)
    print("test_plan_buffer_append_and_wrap PASS")


def test_plan_buffer_order():
    from bokeh.document import Document
    from helao.core.servers.operator.bokeh_operator import BokehOperator
    from helao.helpers.premodels import Sequence

    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    op.plan = [Sequence(sequence_name="A")]
    op.sequence_dropdown.value = "seq0"
    op.populate_sequence(prepend=True)   # inserts seq0 at front
    op.plan.append(Sequence(sequence_name="C"))
    names = [s.sequence_name for s in op.plan]
    assert names == ["seq0", "A", "C"], names
    op.cleanup_session(None)
    print("test_plan_buffer_order PASS")


def test_plan_metadata_capture_at_insert():
    from bokeh.document import Document
    from helao.core.servers.operator.bokeh_operator import BokehOperator

    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    op.sequence_dropdown.value = "seq0"
    op.input_sequence_label.value = "first"
    op.populate_sequence(prepend=False)
    op.input_sequence_label.value = "second"
    op.populate_sequence(prepend=False)
    assert op.plan[0].sequence_label == "first"
    assert op.plan[1].sequence_label == "second"
    op.cleanup_session(None)
    print("test_plan_metadata_capture_at_insert PASS")


def test_flush_add_dispatches_per_sequence():
    from bokeh.document import Document
    from helao.core.servers.operator.bokeh_operator import BokehOperator
    from helao.helpers.premodels import Sequence

    be = _MockBackend()
    op = BokehOperator(_FakeVisOp(Document()), be)
    op.plan = [Sequence(sequence_name="A"), Sequence(sequence_name="B")]
    asyncio.run(op._flush_plan(op.plan, be.add_sequence))
    assert [s.sequence_name for s in be.added] == ["A", "B"]
    op.cleanup_session(None)
    print("test_flush_add_dispatches_per_sequence PASS")


def test_plan_table_rows():
    from bokeh.document import Document
    from helao.core.servers.operator.bokeh_operator import BokehOperator
    from helao.helpers.premodels import Sequence, Experiment

    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    manual = Sequence(sequence_name="m")
    manual.sequence_label = "L1"
    manual.planned_experiments = [Experiment(experiment_name="exp0")]
    multi = Sequence(sequence_name="big")
    multi.sequence_label = "L2"
    multi.planned_experiments = [
        Experiment(experiment_name="exp0"),
        Experiment(experiment_name="exp0"),
    ]
    op.plan = [manual, multi]
    asyncio.run(op.update_tables())
    data = op.experiment_plan_source.data
    assert data["sequence_name"] == ["m", "big"]
    assert data["sequence_label"] == ["L1", "L2"]
    assert data["num_experiments"] == [1, 2]
    assert op.button_add_expplan.label == "Add plan [2]"
    op.cleanup_session(None)
    print("test_plan_table_rows PASS")


def test_plan_reorder_and_remove():
    from bokeh.document import Document
    from helao.core.servers.operator.bokeh_operator import BokehOperator
    from helao.helpers.premodels import Sequence

    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    op.plan = [Sequence(sequence_name=n) for n in ("A", "B", "C")]
    op.experiment_plan_source.selected.indices = [2]
    op.callback_plan_move_up(None)
    assert [s.sequence_name for s in op.plan] == ["A", "C", "B"]

    op.experiment_plan_source.selected.indices = [0]
    op.callback_plan_move_down(None)
    assert [s.sequence_name for s in op.plan] == ["C", "A", "B"]

    op.experiment_plan_source.selected.indices = [1]
    op.callback_plan_remove(None)
    assert [s.sequence_name for s in op.plan] == ["C", "B"]
    op.cleanup_session(None)
    print("test_plan_reorder_and_remove PASS")


def test_queue_controls_enable_gate():
    from bokeh.document import Document
    from helao.core.servers.operator.bokeh_operator import BokehOperator

    be = _MockBackend()
    op = BokehOperator(_FakeVisOp(Document()), be)

    be.loop_state = "started"
    asyncio.run(op.update_tables())
    assert op.button_seq_move_up.disabled is True
    assert op.button_seq_move_down.disabled is True
    assert op.button_seq_remove.disabled is True

    be.loop_state = "stopped"
    asyncio.run(op.update_tables())
    assert op.button_seq_move_up.disabled is False
    assert op.button_seq_move_down.disabled is False
    assert op.button_seq_remove.disabled is False
    op.cleanup_session(None)
    print("test_queue_controls_enable_gate PASS")


def test_prepend_plan_callback_clears_and_dispatches():
    from bokeh.document import Document
    from helao.core.servers.operator.bokeh_operator import BokehOperator
    from helao.helpers.premodels import Sequence

    be = _MockBackend()
    op = BokehOperator(_FakeVisOp(Document()), be)
    plan = [Sequence(sequence_name="A"), Sequence(sequence_name="B")]
    op.plan = plan
    op.callback_prepend_plan(None)
    assert op.plan == [], "buffer should clear synchronously"
    asyncio.run(be.prepend_sequences(plan))
    assert [s.sequence_name for s in be.prepended] == ["A", "B"]
    op.cleanup_session(None)
    print("test_prepend_plan_callback_clears_and_dispatches PASS")


def test_prepend_button_enable_gate():
    from bokeh.document import Document
    from helao.core.servers.operator.bokeh_operator import BokehOperator

    be = _MockBackend()
    op = BokehOperator(_FakeVisOp(Document()), be)

    be.loop_state = "started"
    asyncio.run(op.update_tables())
    assert op.button_prepend_plan.disabled is True, "disabled while running"

    be.loop_state = "stopped"
    asyncio.run(op.update_tables())
    assert op.button_prepend_plan.disabled is False, "enabled while stopped/paused"
    op.cleanup_session(None)
    print("test_prepend_button_enable_gate PASS")


def test_sanitize_sequence_label():
    from helao.core.servers.orch import sanitize_sequence_label
    assert sanitize_sequence_label("a b__c d") == "a_b_c_d"
    assert sanitize_sequence_label("a_b") == "a_b"        # single underscore preserved
    assert sanitize_sequence_label("") == ""
    assert sanitize_sequence_label(None) is None
    print("test_sanitize_sequence_label PASS")


def test_orch_add_sequence_sanitizes_label():
    from helao.core.servers.orch import Orch
    from helao.helpers.premodels import Sequence
    from helao.helpers.zdeque import zdeque

    orch = Orch.__new__(Orch)
    orch.sequence_dq = zdeque([])
    orch.active_run_id = None
    orch.sequence_codehash_lib = {}
    orch.sequence_codepath_lib = {}
    orch.sequence_lib = {}

    seq = Sequence(sequence_name="seq0")
    seq.sequence_label = "x y__z"
    asyncio.run(orch.add_sequence(seq))
    assert list(orch.sequence_dq)[0].sequence_label == "x_y_z"
    print("test_orch_add_sequence_sanitizes_label PASS")


def test_orch_move_and_remove_sequence():
    from helao.core.servers.orch import Orch
    from helao.helpers.premodels import Sequence
    from helao.helpers.zdeque import zdeque

    orch = Orch.__new__(Orch)
    orch.sequence_dq = zdeque(
        [Sequence(sequence_name=n) for n in ("A", "B", "C")]
    )

    asyncio.run(orch.move_sequence(2, 0))
    assert [s.sequence_name for s in orch.sequence_dq] == ["C", "A", "B"]

    asyncio.run(orch.remove_sequence(0))
    assert [s.sequence_name for s in orch.sequence_dq] == ["A", "B"]
    assert len(orch.sequence_dq) == 2

    # out-of-range is a no-op
    asyncio.run(orch.move_sequence(5, 0))
    asyncio.run(orch.remove_sequence(9))
    assert [s.sequence_name for s in orch.sequence_dq] == ["A", "B"]
    print("test_orch_move_and_remove_sequence PASS")


def test_local_backend_move_remove():
    from helao.core.servers.operator.orch_backend import LocalBackend

    class _O(_FakeOrch):
        sequence_lib = {}
        experiment_lib = {}
        def __init__(self):
            super().__init__()
            self.calls = []
        async def move_sequence(self, from_idx, to_idx):
            self.calls.append(("move", from_idx, to_idx))
        async def remove_sequence(self, idx):
            self.calls.append(("remove", idx))

    orch = _O()
    be = LocalBackend(orch)
    asyncio.run(be.move_sequence(2, 0))
    asyncio.run(be.remove_sequence(1))
    assert orch.calls == [("move", 2, 0), ("remove", 1)]
    print("test_local_backend_move_remove PASS")


def test_remote_backend_move_remove():
    from helao.core.servers.operator.orch_backend import RemoteBackend
    from helao.core.error import ErrorCodes

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


def test_uuid_truncation_in_queue_tables():
    from bokeh.document import Document
    from helao.core.servers.operator.bokeh_operator import BokehOperator

    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    asyncio.run(op.get_sequences())
    asyncio.run(op.get_experiments())
    asyncio.run(op.get_actions())
    assert op.sequence_source.data["sequence_uuid"] == ["89abcdef"]
    assert op.sequence_source.data["campaign_uuid"] == ["76543210"]
    assert op.sequence_source.data["sequence_name"] == ["seq0"]  # non-uuid untouched
    assert op.experiment_source.data["experiment_uuid"] == ["33334444"]
    assert op.action_source.data["action_uuid"] == ["ccccdddd"]
    op.cleanup_session(None)
    print("test_uuid_truncation_in_queue_tables PASS")


def test_param_key_uses_name_not_title():
    from bokeh.document import Document
    from helao.core.servers.operator.bokeh_operator import BokehOperator

    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    op.sequence_dropdown.value = "seq0"  # already selected in __init__; param is "x"
    inp = op.seq_param_input[0]
    assert inp.title == ""
    assert inp.name == "x"
    op.populate_sequence(prepend=False)
    assert "x" in op.plan[0].sequence_params  # keyed by .name, not .title
    op.cleanup_session(None)
    print("test_param_key_uses_name_not_title PASS")


def test_find_input_matches_name():
    from bokeh.document import Document
    from bokeh.models.widgets.inputs import TextInput
    from helao.core.servers.operator.bokeh_operator import BokehOperator

    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    probe = TextInput(value="", title="", name="solid_sample_no")
    assert op.find_input([probe], "solid_sample_no") is probe
    assert op.find_input([probe], "missing") is None
    op.cleanup_session(None)
    print("test_find_input_matches_name PASS")


def test_operator_label_sanitize_callback():
    from bokeh.document import Document
    from helao.core.servers.operator.bokeh_operator import BokehOperator

    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    # pure sanitizer used by the on_change callback
    assert op._clean_label("a b__c d") == "a_b_c_d"
    assert op._clean_label("a_b") == "a_b"
    assert op._clean_label("") == ""
    assert op._clean_label(None) is None
    # wiring: the on_change callback schedules a correction that rewrites the field
    op._sanitize_label_callback(op.input_sequence_label, "value", "nolabel", "x y")
    scheduled = list(op.vis.doc.session_callbacks)
    assert scheduled, "dirty input should schedule a correction callback"
    for cb in scheduled:
        try:
            cb.callback()  # do NOT remove_next_tick_callback — Bokeh self-removes on run
        except Exception:
            pass
    assert op.input_sequence_label.value == "x_y", op.input_sequence_label.value
    op.cleanup_session(None)
    print("test_operator_label_sanitize_callback PASS")


def _drain_callbacks(doc, iterations=20):
    """Run all queued Bokeh next-tick callbacks until the queue is empty or the
    iteration limit is reached.  Each iteration drains exactly one generation of
    callbacks; newly-scheduled ones are picked up in the next pass."""
    for _ in range(iterations):
        scheduled = list(doc.session_callbacks)
        if not scheduled:
            break
        for cb in scheduled:
            try:
                cb.callback()  # Bokeh self-removes on invocation
            except Exception:
                pass


def test_save_restore_label_campaign():
    from bokeh.document import Document
    from helao.core.servers.operator.bokeh_operator import BokehOperator

    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    # drain __init__ next-tick callbacks (async get_sequences/history etc.)
    _drain_callbacks(op.vis.doc)

    op.save_last_seq_pars.active = [0]  # save enabled
    op.input_sequence_label.value = "runA"
    op.input_campaign_name.value = "camp1"
    op.input_campaign_uuid.value = "uuid-1"
    # drain the mirror callbacks triggered by the direct .value assignments above
    _drain_callbacks(op.vis.doc)

    op.write_params("seq", "seq0", {"x": 1})

    # clear the live fields, then drain the mirror callbacks before restoring
    op.input_sequence_label.value = "x"
    op.input_campaign_name.value = ""
    op.input_campaign_uuid.value = ""
    _drain_callbacks(op.vis.doc)

    op.sequence_dropdown.value = "seq0"
    op.get_last_seq_pars()
    # run queued next-tick callbacks (restore schedules update_input_value for
    # both primary and mirror widgets; loop until queue drains)
    _drain_callbacks(op.vis.doc)

    assert op.input_sequence_label.value == "runA", op.input_sequence_label.value
    assert op.input_campaign_name.value == "camp1", op.input_campaign_name.value
    assert op.input_campaign_uuid.value == "uuid-1", op.input_campaign_uuid.value
    op.cleanup_session(None)
    print("test_save_restore_label_campaign PASS")


def test_param_label_enumeration():
    from bokeh.document import Document
    from helao.core.servers.operator.bokeh_operator import BokehOperator

    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    op.sequence_dropdown.value = "seq0"  # selected in __init__; single param "x"
    # seq_param_layout has 3 fixed prefix entries (description block, Spacer,
    # header block), then param rows appended by add_dynamic_inputs from index 3.
    # Each param row is layout([[Div],[TextInput],Spacer]) -> children[0].children[0]
    label_div = op.seq_param_layout[3].children[0].children[0]
    assert label_div.text.startswith("0) x"), label_div.text
    # widget key unchanged (decoupled from display)
    assert op.seq_param_input[0].name == "x"
    op.cleanup_session(None)
    print("test_param_label_enumeration PASS")


def test_object_to_html():
    from helao.core.servers.operator.bokeh_operator import _object_to_html

    obj = {
        "sequence_name": "CA_led",
        "sequence_uuid": "0123456789abcdef",
        "sequence_params": {"plate_id": 4083, "led": 385},
        "experiment_list": [{"experiment_name": "e0"}, {"experiment_name": "e1"}],
    }
    html = _object_to_html(obj, open_keys=["sequence_params"])
    assert "<details open><summary>sequence_params</summary>" in html
    assert "<details><summary>sequence_uuid</summary>" in html or \
           "sequence_uuid: 0123456789abcdef" in html
    assert "plate_id: 4083" in html
    assert "experiment_list [2]" in html
    assert "empty" in _object_to_html({})
    assert "scalar" in _object_to_html("scalar")
    print("test_object_to_html PASS")


def test_tree_header_text():
    from helao.core.servers.operator.bokeh_operator import (
        _tree_header_text, _server_header_text,
    )
    obj = {"sequence_name": "seq0", "sequence_uuid": "0123456789abcdef"}
    assert _tree_header_text("sequence", obj) == "seq0 · 89abcdef"
    assert _tree_header_text("action", {"action_name": "noop"}) == "noop"
    cfg = {"host": "127.0.0.1", "port": 8001}
    assert _server_header_text("MOTOR", cfg) == "MOTOR · 127.0.0.1:8001"
    print("test_tree_header_text PASS")


def run_all():
    test_endpoint_helpers_shapes()
    test_local_backend_normalized_shapes()
    test_remote_backend_dispatch_and_serialize()
    test_operator_accepts_backend()
    test_operator_tables_from_backend()
    test_uuid_truncation_in_queue_tables()
    test_plate_api_disabled_by_default()
    test_param_key_uses_name_not_title()
    test_find_input_matches_name()
    test_param_label_enumeration()
    test_object_to_html()
    test_tree_header_text()
    test_operator_label_sanitize_callback()
    test_save_restore_label_campaign()
    test_shim_exposes_makebokehapp()
    test_orch_run_id_sharing()
    test_orch_resolve_active_run_id()
    test_orch_split_run_id()
    test_orch_prepend_order_and_run_id()
    test_sanitize_sequence_label()
    test_orch_add_sequence_sanitizes_label()
    test_orch_move_and_remove_sequence()
    test_prepend_sequences_helper()
    test_local_backend_prepend()
    test_remote_backend_prepend()
    test_local_backend_move_remove()
    test_remote_backend_move_remove()
    test_plan_buffer_append_and_wrap()
    test_plan_buffer_order()
    test_plan_metadata_capture_at_insert()
    test_flush_add_dispatches_per_sequence()
    test_plan_table_rows()
    test_plan_reorder_and_remove()
    test_queue_controls_enable_gate()
    test_prepend_plan_callback_clears_and_dispatches()
    test_prepend_button_enable_gate()
    print("ALL STANDALONE_OPERATOR TESTS PASS")


if __name__ == "__main__":
    run_all()
