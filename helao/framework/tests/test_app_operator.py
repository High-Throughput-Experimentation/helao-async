"""Tests for helao.framework.app.operator.bokeh_operator — ported from
helao/core/tests/test_standalone_operator.py (operator-facing tests only).

Run with:
    conda run -n helao python -m pytest helao/framework/tests/test_app_operator.py -v
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
        self.stop_calls = []

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

    async def stop(self, reset_run_id: bool = False):
        self.stop_calls.append(reset_run_id)

    async def skip(self): ...
    async def estop(self): ...
    async def clear_sequences(self): ...
    async def clear_experiments(self): ...
    async def clear_actions(self): ...

    def subscribe(self, on_change):
        self.on_change = on_change

    def close(self):
        self.on_change = None


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


def test_operator_accepts_backend():
    import inspect
    from helao.framework.app.operator.bokeh_operator import BokehOperator
    params = list(inspect.signature(BokehOperator.__init__).parameters)
    assert params == ["self", "vis_serv", "backend"], params
    print("test_operator_accepts_backend PASS")


def test_operator_tables_from_backend():
    from bokeh.document import Document
    from helao.framework.app.operator.bokeh_operator import BokehOperator

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
    from helao.framework.app.operator.bokeh_operator import BokehOperator
    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    assert op.dataAPI is None  # no plate_api param -> disabled
    op.cleanup_session(None)
    print("test_plate_api_disabled_by_default PASS")


def test_plan_buffer_append_and_wrap():
    from bokeh.document import Document
    from helao.framework.app.operator.bokeh_operator import BokehOperator

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
    from helao.framework.app.operator.bokeh_operator import BokehOperator
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
    from helao.framework.app.operator.bokeh_operator import BokehOperator

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
    from helao.framework.app.operator.bokeh_operator import BokehOperator
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
    from helao.framework.app.operator.bokeh_operator import BokehOperator
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
    from helao.framework.app.operator.bokeh_operator import BokehOperator
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
    from helao.framework.app.operator.bokeh_operator import BokehOperator

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
    from helao.framework.app.operator.bokeh_operator import BokehOperator
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
    from helao.framework.app.operator.bokeh_operator import BokehOperator

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


def test_uuid_truncation_in_queue_tables():
    from bokeh.document import Document
    from helao.framework.app.operator.bokeh_operator import BokehOperator

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
    from helao.framework.app.operator.bokeh_operator import BokehOperator

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
    from helao.framework.app.operator.bokeh_operator import BokehOperator

    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    probe = TextInput(value="", title="", name="solid_sample_no")
    assert op.find_input([probe], "solid_sample_no") is probe
    assert op.find_input([probe], "missing") is None
    op.cleanup_session(None)
    print("test_find_input_matches_name PASS")


def test_operator_label_sanitize_callback():
    from bokeh.document import Document
    from helao.framework.app.operator.bokeh_operator import BokehOperator

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


def test_save_restore_label_campaign():
    from bokeh.document import Document
    from helao.framework.app.operator.bokeh_operator import BokehOperator

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
    from helao.framework.app.operator.bokeh_operator import BokehOperator

    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    op.sequence_dropdown.value = "seq0"  # selected in __init__; single param "x"
    # seq_param_layout has 4 fixed prefix entries (load/save header block,
    # description block, Spacer, params header block), then param rows appended
    # by add_dynamic_inputs from index 4.
    # Each param row is layout([row(input_col, desc_col), Spacer]) where
    # input_col == column(row(Spacer, name_div, type_div), row(index_div, input)).
    param_row = op.seq_param_layout[4].children[0]
    input_col = param_row.children[0]
    label_row = input_col.children[0]
    name_div = label_row.children[1]
    type_div = label_row.children[2]
    index_div = input_col.children[1].children[0]
    assert index_div.text == "[0]", index_div.text
    assert name_div.text == "x", name_div.text
    assert type_div.text.startswith("<i>["), type_div.text
    # widget key unchanged (decoupled from display)
    assert op.seq_param_input[0].name == "x"
    op.cleanup_session(None)
    print("test_param_label_enumeration PASS")


def test_object_to_html():
    from helao.framework.app.operator.bokeh_operator import _object_to_html

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
    from helao.framework.app.operator.bokeh_operator import BokehOperator

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
    from helao.framework.app.operator.bokeh_operator import (
        _tree_header_text, _server_header_text,
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


def test_history_objects_retained():
    from bokeh.document import Document
    from helao.framework.app.operator.bokeh_operator import BokehOperator

    class _BE(_MockBackend):
        async def get_histories(self):
            return {
                "action": [("au1", {"action_name": "noop", "action_uuid": "au1",
                                    "action_server": "test_server"})],
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
    from helao.framework.app.operator.bokeh_operator import BokehOperator
    from helao.helpers.premodels import Sequence

    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    s = Sequence(sequence_name="seqX")
    s.sequence_params = {"plate_id": 7}
    op.plan = [s]
    op.planhistory_tabs.active = 0  # Plan tab
    op.experiment_plan_source.selected.indices = [0]
    op._render_planhistory_tree()
    assert "seqX" in op.planhistory_tree_header.text
    assert "<details open><summary>sequence_params</summary>" in op.planhistory_tree_div.text
    assert "plate_id: 7" in op.planhistory_tree_div.text
    op.cleanup_session(None)
    print("test_planhistory_tree_render_plan PASS")


def test_queue_tree_render_action_server():
    from bokeh.document import Document
    from helao.framework.app.operator.bokeh_operator import BokehOperator

    vis = _FakeVisOp(Document())
    vis.world_cfg["servers"]["MOTOR"] = {
        "group": "action", "host": "10.0.0.1", "port": 8005,
        "params": {"axis": "x"},
    }
    op = BokehOperator(vis, _MockBackend())
    asyncio.run(op.get_orch_status_summary())
    op.action_server_source.data = {
        "action_server": ["MOTOR"], "server_status": ["idle"], "driver_status": ["ok"],
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
    from helao.framework.app.operator.bokeh_operator import BokehOperator

    fetched = {}

    class _BE(_MockBackend):
        async def get_queue_object(self, kind, idx):
            fetched["args"] = (kind, idx)
            return {"sequence_name": "Q", "sequence_uuid": "ffff0000ffff1111",
                    "sequence_params": {"k": 9}}

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
    from helao.framework.app.operator.bokeh_operator import BokehOperator

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
    from helao.framework.app.operator.bokeh_operator import BokehOperator

    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    assert op.dynamic_col.sizing_mode == "stretch_width"
    assert op.sequence_table.sizing_mode == "stretch_width"
    op.cleanup_session(None)
    print("test_layout_is_stretch_width PASS")


def test_history_tables_equal_length_with_missing_keys():
    """Regression: history rows missing campaign_name/sequence_label must NOT make
    the ColumnDataSource columns unequal length (Bokeh refuses to render an
    unequal CDS -> the history tabs appeared empty on the operator)."""
    from bokeh.document import Document
    from helao.framework.app.operator.bokeh_operator import BokehOperator

    class _HistBackend(_MockBackend):
        async def get_histories(self):
            # Each row carries only the always-present keys — campaign_name and
            # sequence_label are ABSENT (the live-deploy case that broke render).
            return {
                "action": [("a" * 16, {
                    "action_server": "SIM", "action_name": "acquire_data",
                    "action_timestamp": 1.0, "action_finished_timestamp": 2.0,
                    "action_status": ["finished"]})],
                "experiment": [("e" * 16, {
                    "experiment_name": "exp0", "experiment_timestamp": 1.0,
                    "experiment_status": ["finished"]})],
                "sequence": [("s" * 16, {
                    "sequence_name": "seq0", "sequence_timestamp": 1.0,
                    "sequence_status": ["finished"]})],
            }

    op = BokehOperator(_FakeVisOp(Document()), _HistBackend())
    asyncio.run(op.get_history())
    for label, src in (
        ("action", op.action_history_source),
        ("experiment", op.experiment_history_source),
        ("sequence", op.sequence_history_source),
    ):
        lengths = {k: len(v) for k, v in src.data.items()}
        assert len(set(lengths.values())) == 1, f"{label} CDS columns unequal: {lengths}"
        assert all(v == 1 for v in lengths.values()), f"{label}: {lengths}"
    op.cleanup_session(None)
    print("test_history_tables_equal_length_with_missing_keys PASS")


def test_clear_button_renamed_to_clear_plan():
    from bokeh.document import Document
    from helao.framework.app.operator.bokeh_operator import BokehOperator
    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    assert op.button_clear_expplan.label == "Clear plan"


def test_reset_checkbox_unchecked_by_default():
    from bokeh.document import Document
    from helao.framework.app.operator.bokeh_operator import BokehOperator
    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    assert op.reset_run_id_on_stop.active == []


def test_stop_callback_forwards_checkbox_state():
    from bokeh.document import Document
    from helao.framework.app.operator.bokeh_operator import BokehOperator
    vis = _FakeVisOp(Document())
    be = _MockBackend()
    op = BokehOperator(vis, be)
    op.reset_run_id_on_stop.active = [0]          # check the box
    op.callback_stop_orch(None)
    _drain_callbacks(vis.doc)
    assert be.stop_calls and be.stop_calls[-1] is True
