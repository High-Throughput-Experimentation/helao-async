"""Standalone tests for the standalone Bokeh operator. No pytest; run with:

    PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao \
        python -m helao.core.tests.test_standalone_operator
"""

import asyncio

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


def _bare_orch():
    """A real ``Orch`` with ``__init__`` bypassed but its collaborators wired.

    ``Orch.__init__`` does far more than these tests need (config, network,
    queue files), so they build the object with ``__new__`` and set only the
    attributes under test.

    The CARDS P5 decomposition moved the queue-CRUD and run-id bodies out of
    ``Orch`` into the ``RunQueues`` collaborator, which ``__init__`` assigns at
    orch.py:209 -- the one line ``__new__`` skips. Every ``Orch.__new__`` test
    therefore started failing with ``'Orch' object has no attribute
    'run_queues'`` even though production is fine. Wiring it here (rather than
    at each of the eight call sites) is deliberate: the duplicated
    hand-construction is exactly why all of them rotted together.

    Sufficient because RunQueues holds only the back-reference and resolves
    orch state at call time -- never caching a deque or attribute -- so the
    per-test attribute assignments that follow still take effect.
    """
    from helao.core.servers.orch import Orch
    from helao.core.servers.orch_queues import RunQueues

    orch = Orch.__new__(Orch)
    orch.run_queues = RunQueues(orch)
    return orch


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


def test_remote_backend_dispatch_and_serialize():
    from helao.core.error import ErrorCodes
    from helao.core.servers.operator.orch_backend import RemoteBackend

    calls = []

    async def fake_dispatch(
        server_key, host, port, endpoint, params_dict=None, json_dict=None, **kw
    ):
        calls.append((endpoint, params_dict, json_dict))
        canned = {
            "list_sequences": [
                {
                    "sequence_name": "seq0",
                    "sequence_label": "lbl",
                    "sequence_uuid": "su",
                    "campaign_name": "camp",
                    "campaign_uuid": "cu",
                    "junk": 1,
                }
            ],
            "list_actions": [
                {
                    "action_name": "noop",
                    "action_uuid": "au",
                    "action_server": {"server_name": "motor", "machine_name": "host"},
                }
            ],
            "get_orch_state": {
                "loop_state": "stopped",
                "n_sequences": 2,
                "n_experiments": 0,
                "n_actions": 0,
                "current_stop_message": "",
            },
            "get_step_flags": {
                "actions": True,
                "experiments": False,
                "sequences": False,
            },
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
    assert seqs == [
        {
            "sequence_name": "seq0",
            "sequence_label": "lbl",
            "sequence_uuid": "su",
            "campaign_name": "camp",
            "campaign_uuid": "cu",
        }
    ]
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
        self.sequence_lib = {"seq0": lambda x=1: [_ExpModel(experiment_name="exp0")]}
        self.experiment_lib = {"exp0": _exp0}
        self._flags = {"actions": False, "experiments": False, "sequences": False}
        self.started = False
        self.on_change = None
        self.loop_state = "stopped"
        self.added = []
        self.split_added = []
        self.prepended = None
        # (endpoint_name, *args) log for queue-mutation calls
        self.queue_calls = []
        self.stop_reset = None
        # override in a test to exercise the manual-sequence gating path
        self.active_sequence = {}

    def unpack_sequence(self, sequence_name, sequence_params):
        return self.sequence_lib[sequence_name](**sequence_params)

    def get_step_flags(self):
        return dict(self._flags)

    async def set_step_flag(self, kind, value):
        self._flags[kind] = value

    async def list_sequences(self):
        return [
            {
                "sequence_name": "seq0",
                "sequence_label": "l",
                "sequence_uuid": "0123456789abcdef",
                "campaign_name": "c",
                "campaign_uuid": "fedcba9876543210",
            }
        ]

    async def list_experiments(self):
        return [{"experiment_name": "exp0", "experiment_uuid": "1111222233334444"}]

    async def list_actions(self):
        return [
            {
                "action_name": "noop",
                "action_server": "motor",
                "action_uuid": "aaaabbbbccccdddd",
            }
        ]

    async def get_histories(self):
        return {"action": [], "experiment": [], "sequence": []}

    async def get_status_summary(self):
        return {"motor": ["idle", "ok"]}

    async def get_orch_state(self):
        return {
            "loop_state": self.loop_state,
            "active_sequence": self.active_sequence,
            "active_experiment": {},
            "n_sequences": 1,
            "n_experiments": 1,
            "n_actions": 1,
            "current_stop_message": "",
        }

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

    async def stop(self, reset_run_id: bool = False):
        self.stop_reset = reset_run_id

    async def skip(self): ...
    async def estop(self): ...
    async def clear_sequences(self): ...
    async def clear_experiments(self): ...
    async def clear_actions(self): ...

    async def move_sequence(self, from_idx, to_idx):
        self.queue_calls.append(("move_sequence", from_idx, to_idx))

    async def remove_sequence(self, idx):
        self.queue_calls.append(("remove_sequence", idx))

    async def move_experiment(self, from_idx, to_idx):
        self.queue_calls.append(("move_experiment", from_idx, to_idx))

    async def remove_experiment(self, idx):
        self.queue_calls.append(("remove_experiment", idx))

    async def move_action(self, from_idx, to_idx):
        self.queue_calls.append(("move_action", from_idx, to_idx))

    async def remove_action(self, idx):
        self.queue_calls.append(("remove_action", idx))

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


def test_plate_callbacks_noop_when_plate_api_disabled():
    """Regression: refresh_inputs must not fire the plate callbacks when dataAPI is None.

    The plateid/sampleno callbacks are only registered behind a
    ``self.dataAPI is not None`` guard, but refresh_inputs re-fired them
    unconditionally, so selecting a sequence with a ``solid_plate_id`` param
    crashed with ``'NoneType' object has no attribute 'get_platemap_plateid'``.
    """
    from bokeh.document import Document
    from bokeh.models import TextInput

    from helao.core.servers.operator.bokeh_operator import BokehOperator

    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    assert op.dataAPI is None

    scheduled = []
    op.vis.doc.add_next_tick_callback = lambda cb: scheduled.append(cb)

    plate_input = TextInput(value="6284", name="solid_plate_id")
    sample_input = TextInput(value="1", name="solid_sample_no")
    op.refresh_inputs([plate_input, sample_input], [])
    assert not scheduled  # no plate callbacks scheduled

    # and the plate-data helpers bail out instead of dereferencing None
    assert op.get_pm(6284, plate_input) is False
    assert op.get_samples([0.0], [0.0], plate_input) == [None]
    assert op.get_elements_plateid(6284, plate_input) is False
    assert op.get_sample_infos([0], plate_input) is False
    op.callback_changed_plateid("value", "", "6284", plate_input)
    op.callback_changed_sampleno("value", "", "1", sample_input)

    op.cleanup_session(None)
    print("test_plate_callbacks_noop_when_plate_api_disabled PASS")


def test_shim_exposes_makebokehapp():
    import importlib
    import inspect

    m = importlib.import_module("helao.deploy.hte.servers.operator.standalone_operator")
    assert hasattr(m, "makeBokehApp")
    params = list(inspect.signature(m.makeBokehApp).parameters)
    assert params == ["doc", "confPrefix", "server_key", "helao_repo_root"], params
    print("test_shim_exposes_makebokehapp PASS")


def test_orch_run_id_sharing():
    from helao.helpers.premodels import Sequence
    from helao.helpers.zdeque import zdeque

    orch = _bare_orch()
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
    from helao.helpers.premodels import Sequence
    from helao.helpers.time_utils import gen_uuid

    orch = _bare_orch()
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
    from helao.helpers.premodels import Sequence
    from helao.helpers.zdeque import zdeque

    orch = _bare_orch()
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
    from helao.helpers.premodels import Sequence
    from helao.helpers.zdeque import zdeque

    orch = _bare_orch()
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
    assert (
        a.run_id == b.run_id == c.run_id == inflight
    ), "prepend reuses in-flight run_id"

    # empty prepend is a no-op and must not mint a stray run_id
    before = orch.active_run_id
    assert asyncio.run(orch.prepend_sequences([])) == []
    assert orch.active_run_id == before
    print("test_orch_prepend_order_and_run_id PASS")


def test_queue_object_payload():
    from helao.core.servers import orch_api

    class _Item:
        def __init__(self, name):
            self._name = name

        def as_dict(self):
            return {"sequence_name": self._name, "sequence_params": {"x": 1}}

    class _O(_FakeOrch):
        def __init__(self):
            super().__init__()
            self.sequence_dq = [_Item("A"), _Item("B")]
            self.experiment_dq = []
            self.action_dq = []

    orch = _O()
    assert orch_api._queue_object_payload(orch, "sequence", 1) == {
        "sequence_name": "B",
        "sequence_params": {"x": 1},
    }
    assert orch_api._queue_object_payload(orch, "sequence", 9) == {}
    assert orch_api._queue_object_payload(orch, "bogus", 0) == {}
    print("test_queue_object_payload PASS")


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


def test_remote_backend_prepend():
    from helao.core.error import ErrorCodes
    from helao.core.servers.operator.orch_backend import RemoteBackend

    calls = []

    async def fake_dispatch(
        server_key, host, port, endpoint, params_dict=None, json_dict=None, **kw
    ):
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
    op.populate_sequence(prepend=True)  # inserts seq0 at front
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
    from helao.helpers.premodels import Experiment, Sequence

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

    def _disabled():
        return (
            op.button_queue_move_up.disabled,
            op.button_queue_move_down.disabled,
            op.button_queue_remove.disabled,
        )

    # Running -> the single unified button set is disabled on every tab.
    be.loop_state = "started"
    op.queue_tabs.active = 0
    asyncio.run(op.update_tables())
    assert _disabled() == (True, True, True)

    # Stopped + Sequence tab (0) -> enabled regardless of manual flag.
    be.loop_state = "stopped"
    be.active_sequence = {}
    op.queue_tabs.active = 0
    asyncio.run(op.update_tables())
    assert _disabled() == (False, False, False)

    # Stopped + Experiment tab (1), non-manual sequence -> still disabled.
    op.queue_tabs.active = 1
    op._refresh_queue_button_state()
    assert _disabled() == (True, True, True)

    # Stopped + Experiment tab (1), manual sequence -> enabled.
    be.active_sequence = {"manual_action": True}
    asyncio.run(op.update_tables())
    assert _disabled() == (False, False, False)

    # Action Servers tab (3) is read-only -> always disabled.
    op.queue_tabs.active = 3
    op._refresh_queue_button_state()
    assert _disabled() == (True, True, True)
    op.cleanup_session(None)
    print("test_queue_controls_enable_gate PASS")


def test_queue_button_dispatch_routing():
    """The single unified button set targets the backend matching the active tab."""
    from bokeh.document import Document

    from helao.core.servers.operator.bokeh_operator import BokehOperator

    be = _MockBackend()
    op = BokehOperator(_FakeVisOp(Document()), be)
    _drain_callbacks(op.vis.doc)

    # _active_queue_target resolves the right (source, move_fn, remove_fn) per tab.
    for idx, source, move_fn, remove_fn, col in (
        (0, op.sequence_source, be.move_sequence, be.remove_sequence, "sequence_name"),
        (
            1,
            op.experiment_source,
            be.move_experiment,
            be.remove_experiment,
            "experiment_name",
        ),
        (2, op.action_source, be.move_action, be.remove_action, "action_name"),
    ):
        op.queue_tabs.active = idx
        tgt = op._active_queue_target()
        assert tgt == (source, move_fn, remove_fn, col)
    # Action Servers tab (3) has no reorderable queue.
    op.queue_tabs.active = 3
    assert op._active_queue_target() is None

    # callback_queue_remove dispatches to the active tab's remove endpoint.
    op.queue_tabs.active = 1
    op.experiment_source.selected.indices = [0]
    op.callback_queue_remove(None)
    _drain_callbacks(op.vis.doc)
    assert ("remove_experiment", 0) in be.queue_calls

    op.queue_tabs.active = 2
    op.action_source.selected.indices = [0]
    op.callback_queue_remove(None)
    _drain_callbacks(op.vis.doc)
    assert ("remove_action", 0) in be.queue_calls
    op.cleanup_session(None)
    print("test_queue_button_dispatch_routing PASS")


def test_stop_callback_forwards_reset_run_id():
    """The reset-run_id checkbox forwards its state to backend.stop()."""
    from bokeh.document import Document

    from helao.core.servers.operator.bokeh_operator import BokehOperator

    be = _MockBackend()
    op = BokehOperator(_FakeVisOp(Document()), be)
    _drain_callbacks(op.vis.doc)

    op.reset_run_id_on_stop.active = []
    op.callback_stop_orch(None)
    _drain_callbacks(op.vis.doc)
    assert be.stop_reset is False

    op.reset_run_id_on_stop.active = [0]
    op.callback_stop_orch(None)
    _drain_callbacks(op.vis.doc)
    assert be.stop_reset is True
    op.cleanup_session(None)
    print("test_stop_callback_forwards_reset_run_id PASS")


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
    assert sanitize_sequence_label("a_b") == "a_b"  # single underscore preserved
    assert sanitize_sequence_label("") == ""
    assert sanitize_sequence_label(None) is None
    print("test_sanitize_sequence_label PASS")


def test_orch_add_sequence_sanitizes_label():
    from helao.helpers.premodels import Sequence
    from helao.helpers.zdeque import zdeque

    orch = _bare_orch()
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
    from helao.helpers.premodels import Sequence
    from helao.helpers.zdeque import zdeque

    orch = _bare_orch()
    orch.sequence_dq = zdeque([Sequence(sequence_name=n) for n in ("A", "B", "C")])

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


def test_orch_move_and_remove_experiment_action():
    from helao.helpers.premodels import Action, Experiment
    from helao.helpers.zdeque import zdeque

    orch = _bare_orch()
    orch.experiment_dq = zdeque(
        [Experiment(experiment_name=n) for n in ("A", "B", "C")]
    )
    orch.action_dq = zdeque([Action(action_name=n) for n in ("X", "Y", "Z")])

    asyncio.run(orch.move_experiment(2, 0))
    assert [e.experiment_name for e in orch.experiment_dq] == ["C", "A", "B"]
    asyncio.run(orch.remove_experiment(0))
    assert [e.experiment_name for e in orch.experiment_dq] == ["A", "B"]

    asyncio.run(orch.move_action(0, 2))
    assert [a.action_name for a in orch.action_dq] == ["Y", "Z", "X"]
    asyncio.run(orch.remove_action(1))
    assert [a.action_name for a in orch.action_dq] == ["Y", "X"]

    # out-of-range is a no-op for both queues
    asyncio.run(orch.move_experiment(5, 0))
    asyncio.run(orch.remove_action(9))
    assert [e.experiment_name for e in orch.experiment_dq] == ["A", "B"]
    assert [a.action_name for a in orch.action_dq] == ["Y", "X"]
    print("test_orch_move_and_remove_experiment_action PASS")


def test_orch_stop_reset_run_id():
    from uuid import uuid4

    from helao.core.models.orchstatus import LoopStatus

    orch = _bare_orch()
    orch.active_run_id = uuid4()

    class _GSM:
        loop_state = LoopStatus.stopped

    orch.globalstatusmodel = _GSM()

    # stop without reset leaves the run_id intact
    asyncio.run(orch.stop())
    assert orch.active_run_id is not None

    # stop with reset drops the run_id
    asyncio.run(orch.stop(reset_run_id=True))
    assert orch.active_run_id is None
    print("test_orch_stop_reset_run_id PASS")


def test_remote_backend_move_remove():
    from helao.core.error import ErrorCodes
    from helao.core.servers.operator.orch_backend import RemoteBackend

    calls = []

    async def fake_dispatch(
        server_key, host, port, endpoint, params_dict=None, json_dict=None, **kw
    ):
        calls.append((endpoint, params_dict))
        return {"n_sequences": 0}, ErrorCodes.none

    be = RemoteBackend.__new__(RemoteBackend)
    be.orch_key = "ORCH"
    be.host = "127.0.0.1"
    be.port = 8001
    be._dispatch = fake_dispatch

    asyncio.run(be.move_sequence(2, 0))
    asyncio.run(be.remove_sequence(1))
    asyncio.run(be.move_experiment(3, 1))
    asyncio.run(be.remove_experiment(2))
    asyncio.run(be.move_action(4, 0))
    asyncio.run(be.remove_action(5))
    assert calls[0] == ("move_sequence", {"from_idx": 2, "to_idx": 0})
    assert calls[1] == ("remove_sequence", {"idx": 1})
    assert calls[2] == ("move_experiment", {"from_idx": 3, "to_idx": 1})
    assert calls[3] == ("remove_experiment", {"idx": 2})
    assert calls[4] == ("move_action", {"from_idx": 4, "to_idx": 0})
    assert calls[5] == ("remove_action", {"idx": 5})
    print("test_remote_backend_move_remove PASS")


def test_remote_backend_stop_reset_run_id():
    from helao.core.error import ErrorCodes
    from helao.core.servers.operator.orch_backend import RemoteBackend

    calls = []

    async def fake_dispatch(
        server_key, host, port, endpoint, params_dict=None, json_dict=None, **kw
    ):
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
    print("test_remote_backend_stop_reset_run_id PASS")


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
    callbacks; newly-scheduled ones are picked up in the next pass.

    Async callbacks (coroutine functions) are run via asyncio.run so that their
    awaitable body actually executes rather than just creating a coroutine object.
    """
    import inspect

    for _ in range(iterations):
        scheduled = list(doc.session_callbacks)
        if not scheduled:
            break
        for cb in scheduled:
            try:
                result = cb.callback()  # Bokeh self-removes on invocation
                if inspect.iscoroutine(result):
                    asyncio.run(result)
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
    # seq_param_layout has 4 fixed prefix entries (load/save header block,
    # description block, Spacer, params header block), then the parameter grid
    # from index 4. Each grid row is row(cell, cell-or-Spacer); a single
    # parameter therefore pairs with a Spacer.
    # Each cell is layout([input_col, Spacer]) where input_col ==
    # column(row(Spacer, name_div, desc_div, type_div), row(index_div, input)).
    grid_row = op.seq_param_layout[4]
    cell = grid_row.children[0]
    input_col = cell.children[0]
    label_row = input_col.children[0]
    name_div = label_row.children[1]
    desc_div = label_row.children[2]
    type_div = label_row.children[3]
    index_div = input_col.children[1].children[0]
    assert index_div.text == "[0]", index_div.text
    assert name_div.text == "x", name_div.text
    # The description sits between the name and the right-aligned type hint.
    assert desc_div.styles.get("text-align") is None, desc_div.styles
    assert type_div.text.startswith("<i>["), type_div.text
    assert type_div.styles["text-align"] == "right", type_div.styles
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
    assert "sequence_uuid: 0123456789abcdef" in html
    assert "plate_id: 4083" in html
    assert "experiment_list [2]" in html
    assert "empty" in _object_to_html({})
    assert "scalar" in _object_to_html("scalar")
    # values with HTML special chars are escaped (no raw injection)
    assert "&lt;b&gt;" in _object_to_html({"k": "<b>x</b>"})
    print("test_object_to_html PASS")


def test_parse_arg_docs():
    from helao.core.servers.operator.bokeh_operator import BokehOperator

    doc = (
        "Plan a thing.\n\n"
        "Args:\n"
        "    wait_time: Base wait used inside each sub-experiment.\n"
        "    cycles (int): Number of cycles\n"
        "        per sample.\n"
        "    *args: Ignored positional arguments.\n"
        "\n"
        "Returns:\n"
        "    Planned experiments.\n"
    )
    descs = BokehOperator._parse_arg_docs(doc)
    assert descs["wait_time"] == "Base wait used inside each sub-experiment.", descs
    # type annotation stripped + continuation line folded in
    assert descs["cycles"] == "Number of cycles per sample.", descs
    # *args skipped, Returns section not bled in
    assert "args" not in descs, descs
    assert "Returns" not in " ".join(descs.values()), descs
    assert BokehOperator._parse_arg_docs("") == {}
    assert BokehOperator._parse_arg_docs("No args section here.") == {}
    print("test_parse_arg_docs PASS")


def test_tree_header_text():
    from helao.core.servers.operator.bokeh_operator import (
        _server_header_text,
        _tree_header_text,
    )

    obj = {"sequence_name": "seq0", "sequence_uuid": "0123456789abcdef"}
    assert _tree_header_text("sequence", obj) == "seq0 · 89abcdef"
    assert _tree_header_text("action", {"action_name": "noop"}) == "noop"
    cfg = {"host": "127.0.0.1", "port": 8001}
    assert _server_header_text("MOTOR", cfg) == "MOTOR · 127.0.0.1:8001"
    # data fields are HTML-escaped (no raw injection)
    assert "&lt;" in _tree_header_text(
        "sequence", {"sequence_name": "<x>", "sequence_uuid": "abcd1234"}
    )
    print("test_tree_header_text PASS")


def test_remote_backend_get_queue_object():
    from helao.core.error import ErrorCodes
    from helao.core.servers.operator.orch_backend import RemoteBackend

    calls = []

    async def fake_dispatch(
        server_key, host, port, endpoint, params_dict=None, json_dict=None, **kw
    ):
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


def test_history_objects_retained():
    from bokeh.document import Document

    from helao.core.servers.operator.bokeh_operator import BokehOperator

    class _BE(_MockBackend):
        async def get_histories(self):
            return {
                "action": [
                    (
                        "au1",
                        {
                            "action_name": "noop",
                            "action_uuid": "au1",
                            "action_server": "test_server",
                        },
                    )
                ],
                "experiment": [],
                "sequence": [],
            }

    op = BokehOperator(_FakeVisOp(Document()), _BE())
    asyncio.run(op.get_history())
    assert op._hist_objs["action"][0]["action_name"] == "noop"
    assert op.planhistory_tree_div is not None
    assert op.queue_tree_div is not None
    assert op.planhistory_tree_header is not None
    assert op.queue_tree_header is not None
    op.cleanup_session(None)
    print("test_history_objects_retained PASS")


def test_planhistory_tree_render_plan():
    from bokeh.document import Document

    from helao.core.servers.operator.bokeh_operator import BokehOperator
    from helao.helpers.premodels import Sequence

    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    s = Sequence(sequence_name="seqX")
    s.sequence_params = {"plate_id": 7}
    op.plan = [s]
    op.planhistory_tabs.active = 0  # Plan tab
    op.experiment_plan_source.selected.indices = [0]
    op._render_planhistory_tree()
    assert "seqX" in op.planhistory_tree_header.text
    assert (
        "<details open><summary>sequence_params</summary>"
        in op.planhistory_tree_div.text
    )
    assert "plate_id: 7" in op.planhistory_tree_div.text
    op.cleanup_session(None)
    print("test_planhistory_tree_render_plan PASS")


def test_queue_tree_render_action_server():
    from bokeh.document import Document

    from helao.core.servers.operator.bokeh_operator import BokehOperator

    vis = _FakeVisOp(Document())
    vis.world_cfg["servers"]["MOTOR"] = {
        "group": "action",
        "host": "10.0.0.1",
        "port": 8005,
        "params": {"axis": "x"},
    }
    op = BokehOperator(vis, _MockBackend())
    asyncio.run(op.get_orch_status_summary())
    op.action_server_source.data = {
        "action_server": ["MOTOR"],
        "server_status": ["idle"],
        "driver_status": ["ok"],
    }
    op.queue_tabs.active = 3  # Action Servers tab
    op.action_server_source.selected.indices = [0]
    op._render_queue_tree()
    assert "MOTOR · 10.0.0.1:8005" in op.queue_tree_header.text
    assert "<details open><summary>params</summary>" in op.queue_tree_div.text
    assert "axis: x" in op.queue_tree_div.text
    op.cleanup_session(None)
    print("test_queue_tree_render_action_server PASS")


def test_queue_tree_render_lazy_sequence():
    from bokeh.document import Document

    from helao.core.servers.operator.bokeh_operator import BokehOperator

    fetched = {}

    class _BE(_MockBackend):
        async def get_queue_object(self, kind, idx):
            fetched["args"] = (kind, idx)
            return {
                "sequence_name": "Q",
                "sequence_uuid": "ffff0000ffff1111",
                "sequence_params": {"k": 9},
            }

    op = BokehOperator(_FakeVisOp(Document()), _BE())
    op.queue_tabs.active = 0  # Sequences tab
    op.sequence_source.selected.indices = [2]
    op._render_queue_tree()
    _drain_callbacks(op.vis.doc)
    assert fetched["args"] == ("sequence", 2)
    assert "Q · ffff1111" in op.queue_tree_header.text
    assert "<details open><summary>sequence_params</summary>" in op.queue_tree_div.text
    op.cleanup_session(None)
    print("test_queue_tree_render_lazy_sequence PASS")


def test_queue_tree_lazy_empty_clears():
    from bokeh.document import Document

    from helao.core.servers.operator.bokeh_operator import BokehOperator

    class _BE(_MockBackend):
        async def get_queue_object(self, kind, idx):
            return {}  # snapshot miss: queue mutated since poll

    op = BokehOperator(_FakeVisOp(Document()), _BE())
    # seed a non-placeholder tree so we can observe it being cleared
    op.queue_tree_header.text = "<b>stale</b>"
    op.queue_tree_div.text = "<div>stale</div>"
    op.queue_tabs.active = 2  # Actions tab
    op.action_source.selected.indices = [0]
    op._render_queue_tree()
    _drain_callbacks(op.vis.doc)
    assert op.queue_tree_header.text == "<b>select a row</b>"
    assert op.queue_tree_div.text == ""
    op.cleanup_session(None)
    print("test_queue_tree_lazy_empty_clears PASS")


def test_layout_is_stretch_width():
    from bokeh.document import Document

    from helao.core.servers.operator.bokeh_operator import BokehOperator

    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    assert op.dynamic_col.sizing_mode == "stretch_width"
    assert op.sequence_table.sizing_mode == "stretch_width"
    op.cleanup_session(None)
    print("test_layout_is_stretch_width PASS")


def _param_grid(op, args, defaults, argtypes):
    """Rebuild the spec-file parameter form from an explicit signature.

    The seqspec mode is the only one that takes ``args``/``defaults``/
    ``argtypes`` directly, which is what lets these tests exercise parameter
    kinds the mock library does not happen to contain. Returns the dynamic
    section of the layout — everything after the four fixed prefix blocks.
    """
    op._update_param_layout(
        "seqspec", 0, args=args, defaults=defaults, argtypes=argtypes
    )
    # Prefix is description + Spacer + params header (seqspec has no
    # load/save header row), then the grid, then the two footer blocks.
    return op.seqspec_param_layout[3:-2]


def test_bool_param_renders_a_radio_group():
    from bokeh.document import Document
    from bokeh.models import RadioButtonGroup

    from helao.core.servers.operator.bokeh_operator import (
        BOOL_LABELS,
        BokehOperator,
        param_widget_value,
    )
    from helao.helpers.to_json import parse_bokeh_input

    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    _param_grid(op, ["flag", "n"], [True, 3], [bool, int])

    widget = op.seqspec_param_input[0]
    assert isinstance(widget, RadioButtonGroup), type(widget)
    assert widget.labels == BOOL_LABELS, widget.labels
    assert widget.active == 0, widget.active
    assert widget.name == "flag"
    # The non-bool parameter beside it is untouched.
    assert not isinstance(op.seqspec_param_input[1], RadioButtonGroup)

    # The label IS the value, and survives the coercion the enqueue paths use.
    assert param_widget_value(widget) == "True"
    assert parse_bokeh_input(param_widget_value(widget)) is True
    widget.active = 1
    assert parse_bokeh_input(param_widget_value(widget)) is False
    op.cleanup_session(None)
    print("test_bool_param_renders_a_radio_group PASS")


def test_bool_param_without_a_bool_default_keeps_its_text_field():
    from bokeh.document import Document
    from bokeh.models import RadioButtonGroup

    from helao.core.servers.operator.bokeh_operator import BokehOperator

    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    # A radio group has no third position for None, and defaulting it to False
    # would change what the operator enqueues.
    _param_grid(op, ["flag"], [None], [bool])
    assert not isinstance(op.seqspec_param_input[0], RadioButtonGroup)
    assert op.seqspec_param_input[0].value == "None"
    op.cleanup_session(None)
    print("test_bool_param_without_a_bool_default_keeps_its_text_field PASS")


def test_radio_group_round_trips_through_the_restore_setter():
    from bokeh.document import Document

    from helao.core.servers.operator.bokeh_operator import (
        BokehOperator,
        param_widget_value,
    )

    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    _param_grid(op, ["flag"], [True], [bool])
    widget = op.seqspec_param_input[0]

    # update_input_value is the setter every restore path goes through.
    op.update_input_value(widget, "False")
    assert param_widget_value(widget) == "False"
    op.update_input_value(widget, "True")
    assert param_widget_value(widget) == "True"
    # A value that is not a label clears the selection rather than guessing.
    op.update_input_value(widget, "banana")
    assert widget.active is None
    assert param_widget_value(widget) == ""
    op.cleanup_session(None)
    print("test_radio_group_round_trips_through_the_restore_setter PASS")


def test_param_cells_render_two_to_a_row():
    from bokeh.document import Document
    from bokeh.layouts import Spacer

    from helao.core.servers.operator.bokeh_operator import (
        PARAM_CELL_NAME,
        BokehOperator,
    )

    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    grid = _param_grid(op, ["a", "b", "c"], [1, 2, 3], [int, int, int])

    assert len(grid) == 2, len(grid)
    assert [child.name for child in grid[0].children] == [
        PARAM_CELL_NAME,
        PARAM_CELL_NAME,
    ]
    # The odd cell pairs with a spacer rather than widening, so every input in
    # the form has the same width.
    assert grid[1].children[0].name == PARAM_CELL_NAME
    assert isinstance(grid[1].children[1], Spacer)

    # An even count leaves no spacer at all.
    grid = _param_grid(op, ["a", "b"], [1, 2], [int, int])
    assert len(grid) == 1, len(grid)
    assert all(child.name == PARAM_CELL_NAME for child in grid[0].children)
    op.cleanup_session(None)
    print("test_param_cells_render_two_to_a_row PASS")


def test_sections_stretch_and_carry_a_margin():
    from bokeh.document import Document

    from helao.core.servers.operator.bokeh_operator import (
        SECTION_MARGIN,
        BokehOperator,
    )

    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    sections = [
        op.layout0.children[0],
        op.layout1.children[0],
        op.layout2.children[0],
        op.layout4.children[1],
    ]
    for section in sections:
        assert section.sizing_mode == "stretch_width", section.sizing_mode
        assert section.margin == SECTION_MARGIN, section.margin
        # A fixed width would defeat the stretch whatever the sizing mode says.
        assert section.width is None, section.width
    op.cleanup_session(None)
    print("test_sections_stretch_and_carry_a_margin PASS")


def test_tree_views_are_bordered():
    from bokeh.document import Document

    from helao.core.servers.operator.bokeh_operator import BokehOperator
    from helao.core.servers.palette import PANEL_BORDER

    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    for tree in (op.planhistory_tree_div, op.queue_tree_div):
        assert PANEL_BORDER in tree.styles["border"], tree.styles
        assert tree.styles["padding"] == "4px", tree.styles
    # Separate dicts, so restyling one tree cannot silently restyle the other.
    assert op.planhistory_tree_div.styles is not op.queue_tree_div.styles
    op.cleanup_session(None)
    print("test_tree_views_are_bordered PASS")


def run_all():
    test_endpoint_helpers_shapes()
    test_remote_backend_dispatch_and_serialize()
    test_operator_accepts_backend()
    test_operator_tables_from_backend()
    test_uuid_truncation_in_queue_tables()
    test_plate_api_disabled_by_default()
    test_param_key_uses_name_not_title()
    test_find_input_matches_name()
    test_param_label_enumeration()
    test_parse_arg_docs()
    test_object_to_html()
    test_tree_header_text()
    test_operator_label_sanitize_callback()
    test_save_restore_label_campaign()
    test_plate_callbacks_noop_when_plate_api_disabled()
    test_shim_exposes_makebokehapp()
    test_orch_run_id_sharing()
    test_orch_resolve_active_run_id()
    test_orch_split_run_id()
    test_orch_prepend_order_and_run_id()
    test_sanitize_sequence_label()
    test_orch_add_sequence_sanitizes_label()
    test_orch_move_and_remove_sequence()
    test_orch_move_and_remove_experiment_action()
    test_orch_stop_reset_run_id()
    test_prepend_sequences_helper()
    test_queue_object_payload()
    test_remote_backend_prepend()
    test_remote_backend_move_remove()
    test_remote_backend_stop_reset_run_id()
    test_remote_backend_get_queue_object()
    test_plan_buffer_append_and_wrap()
    test_plan_buffer_order()
    test_plan_metadata_capture_at_insert()
    test_flush_add_dispatches_per_sequence()
    test_plan_table_rows()
    test_plan_reorder_and_remove()
    test_queue_controls_enable_gate()
    test_queue_button_dispatch_routing()
    test_stop_callback_forwards_reset_run_id()
    test_prepend_plan_callback_clears_and_dispatches()
    test_prepend_button_enable_gate()
    test_history_objects_retained()
    test_planhistory_tree_render_plan()
    test_queue_tree_render_action_server()
    test_queue_tree_render_lazy_sequence()
    test_queue_tree_lazy_empty_clears()
    test_layout_is_stretch_width()
    test_bool_param_renders_a_radio_group()
    test_bool_param_without_a_bool_default_keeps_its_text_field()
    test_radio_group_round_trips_through_the_restore_setter()
    test_param_cells_render_two_to_a_row()
    test_sections_stretch_and_carry_a_margin()
    test_tree_views_are_bordered()
    print("ALL STANDALONE_OPERATOR TESTS PASS")


if __name__ == "__main__":
    run_all()
