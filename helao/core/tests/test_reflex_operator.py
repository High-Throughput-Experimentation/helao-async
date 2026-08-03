"""Tests for the Reflex operator page.

Driven against a fake OrchBackend: the real one is an ABC, so a stub is small,
and no orchestrator runs here. The page's logic lives in module-level functions
for the same reason the browser's does -- rx.State cannot be instantiated
outside a running app.
"""

import asyncio
import os

import pytest
from pydantic import BaseModel

from helao.core.servers.operator import app_reflex as opx


class FakeBackend:
    """Only the OrchBackend methods the page calls."""

    def __init__(
        self,
        sequences=None,
        experiments=None,
        actions=None,
        state="idle",
        summary=None,
        fail=False,
    ):
        self._sequences = sequences or []
        self._experiments = experiments or []
        self._actions = actions or []
        self._state = state
        self._summary = summary or {}
        self._fail = fail
        self.calls = []

    def _boom(self):
        if self._fail:
            raise RuntimeError("orchestrator unreachable")

    async def get_orch_state(self):
        self._boom()
        return {"orch_state": self._state, "loop_state": "started"}

    async def list_sequences(self):
        self._boom()
        return self._sequences

    async def list_experiments(self):
        self._boom()
        return self._experiments

    async def list_actions(self):
        self._boom()
        return self._actions

    async def get_status_summary(self):
        self._boom()
        return self._summary

    async def start(self):
        self._boom()
        self.calls.append("start")

    async def stop(self, reset_run_id=False):
        self._boom()
        self.calls.append(("stop", reset_run_id))

    async def estop(self):
        self._boom()
        self.calls.append("estop")

    async def skip(self):
        self._boom()
        self.calls.append("skip")

    async def clear_sequences(self):
        self._boom()
        self.calls.append("clear_sequences")

    async def clear_experiments(self):
        self._boom()
        self.calls.append("clear_experiments")

    async def clear_actions(self):
        self._boom()
        self.calls.append("clear_actions")

    async def move_sequence(self, from_idx, to_idx):
        self._boom()
        self.calls.append(("move_sequence", from_idx, to_idx))

    async def move_experiment(self, from_idx, to_idx):
        self._boom()
        self.calls.append(("move_experiment", from_idx, to_idx))

    async def move_action(self, from_idx, to_idx):
        self._boom()
        self.calls.append(("move_action", from_idx, to_idx))

    async def remove_sequence(self, idx):
        self._boom()
        self.calls.append(("remove_sequence", idx))

    async def remove_experiment(self, idx):
        self._boom()
        self.calls.append(("remove_experiment", idx))

    async def remove_action(self, idx):
        self._boom()
        self.calls.append(("remove_action", idx))

    def close(self):
        self.calls.append("close")


def test_queue_rows_renders_requested_columns_as_strings():
    """Reflex serialises state to JSON; a UUID or None in a cell breaks the
    encoder or renders as garbage."""
    items = [{"a": 1, "b": None, "c": "x"}]
    assert opx.queue_rows(items, ["a", "b"]) == [["1", ""]]


def test_queue_rows_tolerates_a_missing_column():
    assert opx.queue_rows([{"a": 1}], ["a", "nope"]) == [["1", ""]]


def test_queue_rows_on_nothing_is_empty():
    assert opx.queue_rows([], ["a"]) == []


def test_queue_rows_stringifies_a_nested_value():
    rows = opx.queue_rows([{"a": {"k": 1}}], ["a"])
    assert rows == [["{'k': 1}"]]


def test_status_line_reports_the_orchestrator_state():
    assert "idle" in opx.status_line({"orch_state": "idle"}, reachable=True)


def test_status_line_includes_the_loop_state_when_present():
    line = opx.status_line({"orch_state": "busy", "loop_state": "started"}, True)
    assert "busy" in line and "started" in line


def test_status_line_distinguishes_unreachable_from_idle():
    """A station's orchestrator restarting mid-session is routine, and 'idle'
    would be a lie about it."""
    line = opx.status_line(None, reachable=False)
    assert "idle" not in line
    assert "reach" in line.lower()


def test_status_line_on_a_reachable_orchestrator_with_no_state():
    assert "unknown" in opx.status_line(None, reachable=True)


# -- backend registry --------------------------------------------------------


def test_backend_registry_is_per_session():
    reg = opx.BackendRegistry()
    a, b = FakeBackend(), FakeBackend()
    reg.put("tok-a", a)
    reg.put("tok-b", b)
    assert reg.get("tok-a") is a
    assert reg.get("tok-b") is b


def test_backend_registry_returns_none_for_an_unknown_session():
    assert opx.BackendRegistry().get("nobody") is None


def test_backend_registry_drop_closes_the_backend():
    """The backend holds sockets; dropping the reference without closing leaks
    an HTTP session per operator tab."""

    class Closable(FakeBackend):
        def __init__(self):
            super().__init__()
            self.closed = False

        def close(self):
            self.closed = True

    reg = opx.BackendRegistry()
    backend = Closable()
    reg.put("tok", backend)
    reg.drop("tok")
    assert backend.closed is True
    assert reg.get("tok") is None


def test_backend_registry_drop_survives_a_backend_that_cannot_close():
    """Teardown must not raise: it runs on page unmount, where an exception
    would leave the entry in the registry forever."""

    class Angry(FakeBackend):
        def close(self):
            raise RuntimeError("nope")

    reg = opx.BackendRegistry()
    reg.put("tok", Angry())
    reg.drop("tok")
    assert reg.get("tok") is None


# -- queue control gating ----------------------------------------------------


@pytest.mark.parametrize(
    "state,expected",
    [("idle", True), ("stopped", True), ("busy", False), ("estopped", False)],
)
def test_queue_edits_are_allowed_only_when_the_orchestrator_is_not_running(
    state, expected
):
    """Mirrors the Bokeh operator's enable gate: reordering a queue the
    orchestrator is actively dispatching from races it."""
    assert opx.may_edit_queue(state) is expected


def test_moved_index_refuses_to_move_the_first_item_up():
    assert opx.moved_index(0, "up", 5) is None


def test_moved_index_refuses_to_move_the_last_item_down():
    assert opx.moved_index(4, "down", 5) is None


def test_moved_index_returns_the_target_for_a_valid_move():
    assert opx.moved_index(2, "up", 5) == 1
    assert opx.moved_index(2, "down", 5) == 3


def test_moved_index_refuses_an_out_of_range_position():
    assert opx.moved_index(9, "up", 5) is None
    assert opx.moved_index(-1, "down", 5) is None


# -- column contract ---------------------------------------------------------


def test_queue_columns_are_keys_the_backend_actually_returns():
    """The column lists are a contract with ``RemoteBackend``'s normalizers.

    ``queue_rows`` renders a missing column as an empty cell, so a drifted
    column name does not raise -- it silently produces a blank column that
    looks like missing data from the orchestrator.
    """
    from helao.core.servers.operator import orch_backend as ob

    assert set(opx.SEQ_COLS) <= set(ob._SEQ_KEYS)
    assert set(opx.EXP_COLS) <= set(ob._EXP_KEYS)
    # list_actions builds its dicts inline rather than from a key constant.
    assert set(opx.ACT_COLS) <= {"action_name", "action_server", "action_uuid"}


# -- action-server status table ----------------------------------------------


def test_server_rows_sorts_by_server_name():
    """Fixed row order regardless of the unordered dict the backend returns."""
    rows = opx.server_rows({"b": ("idle", "ok"), "a": ("busy", "ok")})
    assert [r[0] for r in rows] == ["a", "b"]


def test_server_rows_stringifies_every_cell():
    rows = opx.server_rows({"a": ("idle", None)})
    assert rows == [["a", "idle", ""]]


def test_server_rows_tolerates_a_malformed_entry():
    """A server whose summary is not a (status, driver) pair still gets a row:
    dropping it would hide a server that is misbehaving."""
    rows = opx.server_rows({"a": "just a string"})
    assert rows[0][0] == "a"
    assert len(rows[0]) == 3


def test_server_rows_on_nothing_is_empty():
    assert opx.server_rows({}) == []
    assert opx.server_rows(None) == []


# -- poll interval -----------------------------------------------------------


def test_poll_interval_comes_from_the_server_params():
    cfg = {"servers": {"ui": {"params": {"poll_interval": 2.5}}}}
    assert opx.poll_interval_for(cfg, "ui") == 2.5


def test_poll_interval_defaults_when_absent():
    assert opx.poll_interval_for({"servers": {"ui": {}}}, "ui") == (
        opx.DEFAULT_POLL_INTERVAL
    )


def test_poll_interval_rejects_a_nonsense_value():
    """A typo'd YAML value must not turn into a zero-delay busy loop against
    the orchestrator."""
    cfg = {"servers": {"ui": {"params": {"poll_interval": "soon"}}}}
    assert opx.poll_interval_for(cfg, "ui") == opx.DEFAULT_POLL_INTERVAL
    cfg = {"servers": {"ui": {"params": {"poll_interval": 0}}}}
    assert opx.poll_interval_for(cfg, "ui") == opx.DEFAULT_POLL_INTERVAL


# -- refresh -----------------------------------------------------------------


def test_refresh_tables_reads_every_queue_and_the_state():
    backend = FakeBackend(
        sequences=[{"sequence_name": "s1"}],
        experiments=[{"experiment_name": "e1"}],
        actions=[{"action_name": "a1"}],
        summary={"srv": ("idle", "ok")},
    )
    out = asyncio.run(opx.refresh_tables(backend))
    assert out["reachable"] is True
    assert out["orch_state"] == "idle"
    assert out["seq_rows"][0][0] == "s1"
    assert out["exp_rows"][0][0] == "e1"
    assert out["act_rows"][0][0] == "a1"
    assert out["server_rows"] == [["srv", "idle", "ok"]]
    assert "idle" in out["status"]


def test_refresh_tables_keeps_the_last_rows_when_the_orchestrator_goes_away():
    """The returned dict carries no row keys on failure, so the caller's last
    known queues stay on screen while the status line says it cannot reach the
    orchestrator. Blanking the tables would read as 'the queue is empty'."""
    out = asyncio.run(opx.refresh_tables(FakeBackend(fail=True)))
    assert out["reachable"] is False
    assert "seq_rows" not in out
    assert "exp_rows" not in out
    assert "act_rows" not in out
    assert "server_rows" not in out
    assert "reach" in out["status"].lower()


def test_refresh_tables_reports_the_failure_in_error():
    out = asyncio.run(opx.refresh_tables(FakeBackend(fail=True)))
    assert "unreachable" in out["error"]


def test_refresh_tables_without_a_backend_is_unreachable():
    out = asyncio.run(opx.refresh_tables(None))
    assert out["reachable"] is False
    assert "seq_rows" not in out


def test_refresh_tables_clears_a_stale_error_on_success():
    out = asyncio.run(opx.refresh_tables(FakeBackend()))
    assert out["error"] == ""


# -- controls ----------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["start", "stop", "estop", "skip", "clear_sequences", "clear_experiments"],
)
def test_dispatch_control_calls_the_backend(name):
    backend = FakeBackend()
    assert asyncio.run(opx.dispatch_control(backend, name)) == ""
    assert len(backend.calls) == 1


def test_dispatch_control_refuses_a_method_that_is_not_a_control():
    """Event names arrive from the client. Without the allow-list, a crafted
    event would reach any coroutine on the backend, ``close`` included."""
    backend = FakeBackend()
    err = asyncio.run(opx.dispatch_control(backend, "close"))
    assert "unknown control" in err
    assert backend.calls == []


def test_dispatch_control_reports_a_backend_failure():
    err = asyncio.run(opx.dispatch_control(FakeBackend(fail=True), "start"))
    assert "start failed" in err


def test_dispatch_control_without_a_backend():
    err = asyncio.run(opx.dispatch_control(None, "start"))
    assert "no orchestrator" in err


# -- queue edits -------------------------------------------------------------


def test_dispatch_move_routes_to_the_right_backend_method():
    for kind, method in [
        ("sequence", "move_sequence"),
        ("experiment", "move_experiment"),
        ("action", "move_action"),
    ]:
        backend = FakeBackend()
        assert asyncio.run(opx.dispatch_move(backend, kind, 1, "up", 3)) == ""
        assert backend.calls == [(method, 1, 0)]


def test_dispatch_move_at_the_end_of_the_queue_does_not_call_the_backend():
    """An impossible move must not become a backend round trip that reorders
    nothing while the UI implies it worked."""
    backend = FakeBackend()
    assert asyncio.run(opx.dispatch_move(backend, "sequence", 0, "up", 3)) == ""
    assert backend.calls == []


def test_dispatch_move_refuses_an_unknown_kind():
    backend = FakeBackend()
    err = asyncio.run(opx.dispatch_move(backend, "nonsense", 0, "down", 3))
    assert "unknown queue" in err
    assert backend.calls == []


def test_dispatch_remove_routes_to_the_right_backend_method():
    for kind, method in [
        ("sequence", "remove_sequence"),
        ("experiment", "remove_experiment"),
        ("action", "remove_action"),
    ]:
        backend = FakeBackend()
        assert asyncio.run(opx.dispatch_remove(backend, kind, 2, 3)) == ""
        assert backend.calls == [(method, 2)]


def test_dispatch_remove_refuses_a_position_outside_the_queue():
    """Positions come from a rendered row index, which can outlive the row: a
    poll can shorten the queue between render and click."""
    backend = FakeBackend()
    err = asyncio.run(opx.dispatch_remove(backend, "sequence", 7, 3))
    assert "no longer" in err
    assert backend.calls == []


def test_dispatch_remove_reports_a_backend_failure():
    err = asyncio.run(opx.dispatch_remove(FakeBackend(fail=True), "sequence", 0, 3))
    assert "failed" in err


# -- backend construction ----------------------------------------------------


def test_vis_shim_exposes_what_the_backend_reads_off_a_bokeh_vis():
    """RemoteBackend was written against a Bokeh ``Vis``; it reads exactly two
    attributes off it, so the Reflex page supplies them rather than importing
    Bokeh."""
    shim = opx._VisShim({"servers": {}}, "ui")
    assert shim.world_cfg == {"servers": {}}
    assert hasattr(shim.helaodirs, "user_exp")
    assert hasattr(shim.helaodirs, "user_seq")


def test_session_backend_without_configuration_is_none():
    """Import-time safety: the state class exists before any config is loaded,
    and a poll that fires first must degrade to 'cannot reach', not raise."""
    opx.reset_settings()
    assert opx.session_backend("tok") is None


# -- parameter fields --------------------------------------------------------


class _ItemModel(BaseModel):
    """Minimal stand-in for the operator's return_sequence_lib model."""

    index: int
    experiment_name: str
    doc: str
    args: tuple
    defaults: tuple
    argtypes: tuple
    version: object = None
    codehash: object = None


def _item(args, defaults, argtypes, doc="", **extra):
    """A build_lib-shaped item without running introspection."""
    base = {
        "index": 0,
        "sequence_name": "seq_a",
        "doc": doc,
        "args": tuple(args),
        "defaults": tuple(defaults),
        "argtypes": tuple(argtypes),
        "version": None,
        "codehash": None,
    }
    base.update(extra)
    return base


def test_align_defaults_pads_positional_args_first():
    """Args without defaults are the leading ones. The Bokeh operator pads the
    front of the defaults list for exactly this reason; padding the end would
    hand every field the wrong neighbour's default."""
    assert opx.align_defaults(["a", "b", "c"], [1]) == ["", "", 1]


def test_align_defaults_leaves_a_matched_list_alone():
    assert opx.align_defaults(["a", "b"], [1, 2]) == [1, 2]


def test_fields_for_item_types_each_field_from_its_annotation():
    fields = opx.fields_for_item(
        _item(["n", "f", "b", "s"], [1, 1.5, True, "x"], [int, float, bool, str])
    )
    assert [f["kind"] for f in fields] == ["number", "number", "bool", "text"]


def test_fields_for_item_falls_back_to_text_without_an_annotation():
    fields = opx.fields_for_item(_item(["a"], ["x"], ["unspecified"]))
    assert fields[0]["kind"] == "text"


def test_fields_for_item_renders_a_container_default_as_text():
    """A list or dict default has no typed input; the Bokeh operator shows its
    repr in a text box and parses it back on enqueue."""
    fields = opx.fields_for_item(_item(["a"], [[1, 2]], [list]))
    assert fields[0]["kind"] == "text"
    assert fields[0]["default"] == "[1, 2]"


def test_fields_for_item_takes_help_text_from_the_docstring():
    doc = "Summary.\n\nArgs:\n    alpha: how many times\n"
    fields = opx.fields_for_item(_item(["alpha"], [1], [int], doc=doc))
    assert fields[0]["help"] == "how many times"


def test_fields_for_item_help_is_empty_when_undocumented():
    fields = opx.fields_for_item(_item(["alpha"], [1], [int]))
    assert fields[0]["help"] == ""


def test_fields_for_item_uses_an_options_map_to_make_a_select():
    """Custom-position params are a dropdown of the station's configured
    positions, matching the Bokeh operator's Select for those two args."""
    fields = opx.fields_for_item(
        _item(["solid_custom_position"], ["cell1"], [str]),
        options_map={"solid_custom_position": ["cell1", "cell2"]},
    )
    assert fields[0]["kind"] == "select"
    assert fields[0]["options"] == ["cell1", "cell2"]


def test_fields_for_item_select_default_falls_back_to_the_first_option():
    """Bokeh picks the first option when the default is not among them, rather
    than leaving a Select showing a value it cannot offer."""
    fields = opx.fields_for_item(
        _item(["solid_custom_position"], ["gone"], [str]),
        options_map={"solid_custom_position": ["cell1"]},
    )
    assert fields[0]["default"] == "cell1"


def test_fields_for_item_drops_the_framework_injected_argument():
    """Experiment functions take an Experiment the operator must not prompt
    for. build_lib filters it; this asserts the pair works end to end."""
    from helao.core.servers.operator import param_forms as pf

    class Marker:
        pass

    def exp_a(experiment: Marker, alpha: int = 1):
        """d"""

    pf.clear_lib_cache()
    items, _ = pf.build_lib(
        {"exp_a": exp_a},
        filter_type=Marker,
        config_key="experiment_params",
        world_cfg={},
        loaded_config_path="/cfg/fields.yml",
        model_class=_ItemModel,
        name_field="experiment_name",
    )
    names = [f["name"] for f in opx.fields_for_item(items[0])]
    assert names == ["alpha"]


def test_flatten_fields_is_all_strings_for_foreach():
    """rx.foreach needs a concrete element type, and Reflex cannot iterate a
    list of heterogeneous dicts."""
    fields = opx.fields_for_item(_item(["a", "b"], [1, True], [int, bool]))
    rows = opx.flatten_fields(fields)
    assert rows == [["a", "number", "1", ""], ["b", "bool", "True", ""]]


def test_field_options_is_parallel_to_the_rows():
    fields = opx.fields_for_item(
        _item(["a", "p"], [1, "cell1"], [int, str]),
        options_map={"p": ["cell1", "cell2"]},
    )
    assert opx.field_options(fields) == [[], ["cell1", "cell2"]]


# -- parameter coercion ------------------------------------------------------


def test_coerce_params_applies_the_annotated_builtin_type():
    fields = opx.fields_for_item(_item(["n"], [1], [int]))
    params, errors = opx.coerce_params(fields, {"n": "7"})
    assert params == {"n": 7}
    assert isinstance(params["n"], int)
    assert errors == []


def test_coerce_params_falls_back_to_the_default_for_an_untouched_field():
    fields = opx.fields_for_item(_item(["n"], [3], [int]))
    params, errors = opx.coerce_params(fields, {})
    assert params == {"n": 3}
    assert errors == []


def test_coerce_params_parses_a_container_from_text():
    fields = opx.fields_for_item(_item(["a"], [[1, 2]], [list]))
    params, _ = opx.coerce_params(fields, {"a": "[3, 4]"})
    assert params["a"] == [3, 4]


def test_coerce_params_accepts_single_quoted_json():
    """parse_bokeh_input rewrites single quotes, so a repr pasted back into
    the field round-trips."""
    fields = opx.fields_for_item(_item(["a"], [{}], [dict]))
    params, _ = opx.coerce_params(fields, {"a": "{'k': 1}"})
    assert params["a"] == {"k": 1}


def test_coerce_params_reports_a_value_that_will_not_convert():
    """Reported, not dropped: silently omitting the parameter would run the
    sequence with a default the operator never chose."""
    fields = opx.fields_for_item(_item(["n"], [1], [int]))
    params, errors = opx.coerce_params(fields, {"n": "twelve"})
    assert "n" not in params
    assert errors and "n" in errors[0]


def test_coerce_params_reads_false_as_false():
    """str(False) is 'False', and bool('False') is True. Routing checkbox text
    through the plain builtin cast would invert every unchecked box."""
    fields = opx.fields_for_item(_item(["b"], [True], [bool]))
    params, errors = opx.coerce_params(fields, {"b": "False"})
    assert params == {"b": False}
    assert errors == []


@pytest.mark.parametrize(
    "raw,expected",
    [("true", True), ("False", False), ("0", False), ("1", True), (True, True)],
)
def test_coerce_params_accepts_the_forms_a_checkbox_can_send(raw, expected):
    fields = opx.fields_for_item(_item(["b"], [False], [bool]))
    params, _ = opx.coerce_params(fields, {"b": raw})
    assert params["b"] is expected


def test_coerce_params_rejects_nonsense_in_a_bool_field():
    fields = opx.fields_for_item(_item(["b"], [False], [bool]))
    params, errors = opx.coerce_params(fields, {"b": "maybe"})
    assert "b" not in params
    assert errors


def test_coerce_params_leaves_an_unannotated_field_as_parsed():
    fields = opx.fields_for_item(_item(["a"], ["x"], ["unspecified"]))
    params, errors = opx.coerce_params(fields, {"a": "7"})
    assert params["a"] == 7
    assert errors == []


# -- version hint ------------------------------------------------------------


def test_version_text_joins_the_parts():
    assert opx.version_text({"version": 2, "codehash": "abc"}) == "v2 · abc"


def test_version_text_is_empty_without_either_part():
    assert opx.version_text({}) == ""


# -- library loading and enqueue ---------------------------------------------


class LibBackend(FakeBackend):
    """A backend carrying libraries, as RemoteBackend does."""

    def __init__(self, **kw):
        super().__init__(**kw)

        def seq_a(alpha: int = 1, beta: str = "x"):
            """A sequence.

            Args:
                alpha: how many
            """

        def exp_a(gamma: float = 2.5):
            """An experiment."""

        self.sequence_lib = {"seq_a": seq_a}
        self.experiment_lib = {"exp_a": exp_a}
        self.sequence_codehash = {"seq_a": "abcdef1234"}
        self.experiment_codehash = {}
        self.unpacked = None

    def unpack_sequence(self, sequence_name, sequence_params):
        self.unpacked = (sequence_name, sequence_params)
        return [{"experiment_name": "e1"}]

    async def add_sequence(self, sequence):
        self._boom()
        self.calls.append(("add_sequence", sequence))
        return {"ok": True}

    async def add_split_sequences(self, sequence):
        self._boom()
        self.calls.append(("add_split_sequences", sequence))
        return {"ok": True}

    async def prepend_sequences(self, sequences):
        self._boom()
        self.calls.append(("prepend_sequences", list(sequences)))
        return {"ok": True}


def _fresh_libs():
    from helao.core.servers.operator import param_forms as pf

    pf.clear_lib_cache()


def test_library_items_come_from_the_backend_libraries():
    _fresh_libs()
    items, names = opx.library_items(LibBackend(), "sequence", {})
    assert names == ["seq_a"]
    assert items[0]["sequence_name"] == "seq_a"


def test_library_items_carry_the_codehash_for_the_version_hint():
    _fresh_libs()
    items, _ = opx.library_items(LibBackend(), "sequence", {})
    assert items[0]["codehash"] == "abcdef12"


def test_library_items_for_experiments_drop_the_injected_experiment():
    _fresh_libs()
    items, names = opx.library_items(LibBackend(), "experiment", {})
    assert names == ["exp_a"]
    assert "experiment" not in items[0]["args"]


def test_library_items_without_a_backend_is_empty():
    assert opx.library_items(None, "sequence", {}) == ([], [])


def test_library_items_refuses_an_unknown_kind():
    _fresh_libs()
    assert opx.library_items(LibBackend(), "nonsense", {}) == ([], [])


def test_item_by_name_finds_the_selection():
    _fresh_libs()
    items, _ = opx.library_items(LibBackend(), "sequence", {})
    assert opx.item_by_name(items, "sequence", "seq_a")["sequence_name"] == "seq_a"


def test_item_by_name_returns_none_for_a_stale_selection():
    """The library can be reloaded under a selection that no longer exists."""
    assert opx.item_by_name([], "sequence", "gone") is None


def test_enqueue_sequence_unpacks_and_adds():
    _fresh_libs()
    backend = LibBackend()
    items, _ = opx.library_items(backend, "sequence", {})
    fields = opx.fields_for_item(items[0])
    message, error = asyncio.run(
        opx.enqueue_sequence(backend, items[0], fields, {"alpha": "9"}, label="run1")
    )
    assert error == ""
    assert backend.unpacked == ("seq_a", {"alpha": 9, "beta": "x"})
    assert backend.calls[0][0] == "add_sequence"
    assert "seq_a" in message


def test_enqueue_sequence_carries_the_label_and_planned_experiments():
    _fresh_libs()
    backend = LibBackend()
    items, _ = opx.library_items(backend, "sequence", {})
    fields = opx.fields_for_item(items[0])
    asyncio.run(opx.enqueue_sequence(backend, items[0], fields, {}, label="run1"))
    sequence = backend.calls[0][1]
    assert sequence.sequence_label == "run1"
    assert len(sequence.planned_experiments) == 1


def test_enqueue_sequence_refuses_when_a_parameter_will_not_convert():
    """Nothing reaches the orchestrator: running with a silently defaulted
    parameter is worse than not running."""
    _fresh_libs()
    backend = LibBackend()
    items, _ = opx.library_items(backend, "sequence", {})
    fields = opx.fields_for_item(items[0])
    _, error = asyncio.run(
        opx.enqueue_sequence(backend, items[0], fields, {"alpha": "nine"})
    )
    assert "alpha" in error
    assert backend.calls == []
    assert backend.unpacked is None


def test_enqueue_sequence_reports_an_unpack_failure():
    """A library sequence that raises while unpacking must name itself; the
    operator otherwise sees a button that does nothing."""
    _fresh_libs()
    backend = LibBackend()
    items, _ = opx.library_items(backend, "sequence", {})
    fields = opx.fields_for_item(items[0])

    def boom(sequence_name, sequence_params):
        raise ValueError("bad plate id")

    backend.unpack_sequence = boom
    _, error = asyncio.run(opx.enqueue_sequence(backend, items[0], fields, {}))
    assert "bad plate id" in error
    assert backend.calls == []


def test_enqueue_sequence_reports_a_backend_failure():
    _fresh_libs()
    backend = LibBackend(fail=True)
    backend._fail = False
    items, _ = opx.library_items(backend, "sequence", {})
    fields = opx.fields_for_item(items[0])
    backend._fail = True
    _, error = asyncio.run(opx.enqueue_sequence(backend, items[0], fields, {}))
    assert error


def test_enqueue_sequence_without_a_selection():
    _, error = asyncio.run(opx.enqueue_sequence(LibBackend(), None, [], {}))
    assert "no sequence" in error.lower()


# -- custom positions --------------------------------------------------------


def _pal_cfg(positions):
    return {
        "servers": {
            "MOTOR": {"fast": "galil_motion"},
            "PAL": {"fast": "pal_server", "params": {"positions": positions}},
        }
    }


def test_custom_positions_come_from_the_pal_server():
    cfg = _pal_cfg({"custom": {"cell1": {}, "cell2": {}}})
    assert opx.custom_positions(cfg) == ["cell1", "cell2"]


def test_custom_positions_is_empty_without_a_pal_server():
    """Most stations have no PAL. The params then render as plain text, which
    is what the Bokeh operator does with an empty custom-item list."""
    assert opx.custom_positions({"servers": {"MOTOR": {"fast": "galil_motion"}}}) == []


def test_custom_positions_tolerates_a_pal_without_positions():
    assert opx.custom_positions(_pal_cfg({})) == []
    assert opx.custom_positions({"servers": {"PAL": {"fast": "pal_server"}}}) == []


def test_custom_positions_on_an_empty_config():
    assert opx.custom_positions({}) == []


def test_options_map_names_both_custom_position_params():
    """Bokeh turns both solid_ and liquid_custom_position into dropdowns off
    the same list."""
    mapping = opx.options_map_for(_pal_cfg({"custom": {"cell1": {}}}))
    assert set(mapping) == {"solid_custom_position", "liquid_custom_position"}
    assert mapping["solid_custom_position"] == ["cell1"]


def test_options_map_is_empty_when_there_are_no_positions():
    """An empty map is what makes those params fall back to text inputs."""
    assert opx.options_map_for({"servers": {}}) == {}


# -- plan buffer -------------------------------------------------------------
#
# These mirror the Bokeh operator's six plan tests, which are the
# specification for this tab: test_plan_buffer_append_and_wrap,
# test_plan_buffer_order, test_plan_table_rows, test_plan_reorder_and_remove,
# test_flush_add_dispatches_per_sequence, and
# test_prepend_plan_callback_clears_and_dispatches.


def _seq(name, label="", experiments=0):
    from helao.helpers.premodels import Experiment, Sequence

    sequence = Sequence(sequence_name=name)
    if label:
        sequence.sequence_label = label
    sequence.planned_experiments = [
        Experiment(experiment_name="exp0") for _ in range(experiments)
    ]
    return sequence


def test_build_sequence_makes_a_sequence_from_the_selection():
    _fresh_libs()
    backend = LibBackend()
    items, _ = opx.library_items(backend, "sequence", {})
    fields = opx.fields_for_item(items[0])
    sequence, error = opx.build_sequence(backend, items[0], fields, {"alpha": "4"})
    assert error == ""
    assert sequence.sequence_name == "seq_a"
    assert sequence.sequence_params["alpha"] == 4


def test_build_manual_sequence_wraps_an_experiment():
    """Appending an experiment wraps it in a one-experiment 'manual_orch_seq',
    which is how the Bokeh operator gets a bare experiment into a queue that
    only accepts sequences."""
    _fresh_libs()
    items, _ = opx.library_items(LibBackend(), "experiment", {})
    fields = opx.fields_for_item(items[0])
    sequence, error = opx.build_manual_sequence(items[0], fields, {"gamma": "3.5"})
    assert error == ""
    assert sequence.sequence_name == "manual_orch_seq"
    assert sequence.manual_action is True
    assert len(sequence.planned_experiments) == 1
    assert sequence.planned_experiments[0].experiment_params["gamma"] == 3.5


def test_build_manual_sequence_refuses_a_bad_parameter():
    _fresh_libs()
    items, _ = opx.library_items(LibBackend(), "experiment", {})
    fields = opx.fields_for_item(items[0])
    sequence, error = opx.build_manual_sequence(items[0], fields, {"gamma": "soon"})
    assert sequence is None
    assert "gamma" in error


def test_plan_rows_shows_name_label_and_experiment_count():
    rows = opx.plan_rows([_seq("m", "L1", 1), _seq("big", "L2", 2)])
    assert [r[0] for r in rows] == ["m", "big"]
    assert [r[1] for r in rows] == ["L1", "L2"]
    assert [r[2] for r in rows] == ["1", "2"]


def test_plan_rows_on_an_empty_buffer():
    assert opx.plan_rows([]) == []


def test_plan_moved_swaps_the_selected_row():
    plan = [_seq(n) for n in ("A", "B", "C")]
    assert [s.sequence_name for s in opx.plan_moved(plan, 2, "up")] == ["A", "C", "B"]
    assert [s.sequence_name for s in opx.plan_moved(plan, 0, "down")] == ["B", "A", "C"]


def test_plan_moved_at_an_end_is_none():
    plan = [_seq(n) for n in ("A", "B")]
    assert opx.plan_moved(plan, 0, "up") is None
    assert opx.plan_moved(plan, 1, "down") is None


def test_plan_moved_with_nothing_selected():
    assert opx.plan_moved([_seq("A")], -1, "up") is None


def test_plan_removed_drops_the_selected_row():
    plan = [_seq(n) for n in ("C", "A", "B")]
    assert [s.sequence_name for s in opx.plan_removed(plan, 1)] == ["C", "B"]


def test_plan_removed_out_of_range_is_none():
    assert opx.plan_removed([_seq("A")], 4) is None
    assert opx.plan_removed([_seq("A")], -1) is None


def test_plan_edits_do_not_mutate_the_original_buffer():
    """The handler assigns the returned list, so returning a new one keeps the
    state var assignment explicit rather than mutating behind Reflex's back."""
    plan = [_seq(n) for n in ("A", "B")]
    opx.plan_moved(plan, 1, "up")
    opx.plan_removed(plan, 0)
    assert [s.sequence_name for s in plan] == ["A", "B"]


def test_dispatch_plan_appends_each_sequence_in_order():
    backend = LibBackend()
    plan = [_seq("A"), _seq("B")]
    assert asyncio.run(opx.dispatch_plan(backend, plan, "append")) == ""
    added = [c[1].sequence_name for c in backend.calls if c[0] == "add_sequence"]
    assert added == ["A", "B"]


def test_dispatch_plan_prepends_the_whole_buffer_at_once():
    """prepend_sequences takes the list: prepending one at a time would
    reverse the buffer's order at the head of the queue."""
    backend = LibBackend()
    plan = [_seq("A"), _seq("B")]
    assert asyncio.run(opx.dispatch_plan(backend, plan, "prepend")) == ""
    call = [c for c in backend.calls if c[0] == "prepend_sequences"][0]
    assert [s.sequence_name for s in call[1]] == ["A", "B"]


def test_dispatch_plan_routes_the_split_variant():
    backend = LibBackend()
    assert asyncio.run(opx.dispatch_plan(backend, [_seq("A")], "split")) == ""
    assert [c[0] for c in backend.calls] == ["add_split_sequences"]


def test_dispatch_plan_refuses_an_unknown_mode():
    backend = LibBackend()
    error = asyncio.run(opx.dispatch_plan(backend, [_seq("A")], "sideways"))
    assert "unknown" in error
    assert backend.calls == []


def test_dispatch_plan_on_an_empty_buffer_does_nothing():
    backend = LibBackend()
    assert asyncio.run(opx.dispatch_plan(backend, [], "append")) == ""
    assert backend.calls == []


def test_dispatch_plan_reports_which_sequence_failed():
    """A partial flush is the dangerous case: some sequences are queued and
    some are not, and the operator must know where it stopped."""
    backend = LibBackend()
    plan = [_seq("A"), _seq("B")]

    async def fail_on_b(sequence):
        if sequence.sequence_name == "B":
            raise RuntimeError("queue full")
        backend.calls.append(("add_sequence", sequence))

    backend.add_sequence = fail_on_b
    error = asyncio.run(opx.dispatch_plan(backend, plan, "append"))
    assert "B" in error
    assert [c[1].sequence_name for c in backend.calls] == ["A"]


def test_dispatch_plan_without_a_backend():
    assert "no orchestrator" in asyncio.run(
        opx.dispatch_plan(None, [_seq("A")], "append")
    )


# -- history -----------------------------------------------------------------


def _hist(kind, uuid, payload):
    return {"action": [], "experiment": [], "sequence": [], kind: [(uuid, payload)]}


def test_history_rows_builds_the_action_endpoint():
    rows = opx.history_rows(
        _hist("action", "u1", {"action_server": "MOTOR", "action_name": "move"}),
        "action",
    )
    assert rows[0][0] == "MOTOR/move"


def test_history_rows_shortens_the_uuid():
    """Full UUIDs make the table unreadable; Bokeh shows the last 8 characters."""
    rows = opx.history_rows(
        _hist("sequence", "0123456789abcdef", {"sequence_name": "s"}), "sequence"
    )
    assert "89abcdef" in rows[0]


def test_history_rows_takes_the_last_element_of_a_status_list():
    """Status arrives as a list of transitions; the current one is the last."""
    rows = opx.history_rows(
        _hist("action", "u1", {"action_status": ["active", "finished"]}), "action"
    )
    assert "finished" in rows[0]
    assert "active" not in rows[0]


def test_history_rows_renders_an_empty_status_list_as_blank():
    rows = opx.history_rows(_hist("action", "u1", {"action_status": []}), "action")
    assert rows[0][1] == ""


def test_history_rows_is_most_recent_first():
    hist = {
        "action": [("u1", {"action_name": "a"}), ("u2", {"action_name": "b"})],
        "experiment": [],
        "sequence": [],
    }
    rows = opx.history_rows(hist, "action")
    assert rows[0][0].endswith("b")


def test_history_rows_on_a_missing_kind_is_empty():
    assert opx.history_rows({}, "action") == []
    assert opx.history_rows(None, "sequence") == []


def test_history_rows_every_row_has_every_column():
    """Ragged rows are what broke the Bokeh table; the Reflex table would
    render a short row with missing cells instead."""
    rows = opx.history_rows(_hist("experiment", "u1", {}), "experiment")
    assert len(rows[0]) == len(opx.HIST_COLS["experiment"])


# -- plate map ---------------------------------------------------------------


def _pm(n=3):
    """A platemap the way HTEPlateAPI returns one."""
    return [
        {
            "x": float(i),
            "y": float(i * 2),
            "code": i,
            "A": 1.0 - i / 10,
            "B": i / 10,
        }
        for i in range(n)
    ]


def test_plate_api_is_off_without_the_config_key():
    """Opt-in, as in the Bokeh operator: most stations have no plate API, and
    the tab must say so rather than render a broken map."""
    assert opx.plate_api_for({}) is None
    assert opx.plate_api_for({"params": {}}) is None


def test_plate_api_ignores_an_unknown_name():
    """A typo'd plate_api value must not import something arbitrary."""
    assert opx.plate_api_for({"params": {"plate_api": "NotARealAPI"}}) is None


def test_platemap_points_splits_the_coordinates():
    xs, ys, samples = opx.platemap_points(_pm(3))
    assert xs == [0.0, 1.0, 2.0]
    assert ys == [0.0, 2.0, 4.0]
    assert samples == [1, 2, 3]


def test_platemap_points_numbers_samples_from_one():
    """A plate's sample numbers are 1-based; the map index is 0-based."""
    _, _, samples = opx.platemap_points(_pm(2))
    assert samples == [1, 2]


def test_platemap_points_skips_a_non_numeric_coordinate():
    """A coordinate that will not convert takes down the whole chart from
    inside the render, so it is dropped here with the rest of the row."""
    pmdata = _pm(2) + [{"x": "n/a", "y": 3.0}]
    xs, ys, samples = opx.platemap_points(pmdata)
    assert len(xs) == 2 and len(ys) == 2 and len(samples) == 2


def test_platemap_points_keeps_x_y_and_samples_the_same_length():
    """plots.scatter_map raises when x and y differ in length."""
    pmdata = [{"x": 1.0, "y": "bad"}, {"x": 2.0, "y": 2.0}]
    xs, ys, samples = opx.platemap_points(pmdata)
    assert len(xs) == len(ys) == len(samples) == 1


def test_platemap_points_on_an_empty_map():
    assert opx.platemap_points([]) == ([], [], [])
    assert opx.platemap_points(None) == ([], [], [])


def test_nearest_sample_snaps_to_the_closest_point():
    assert opx.nearest_sample(_pm(3), 0.9, 1.9) == 2


def test_nearest_sample_on_an_empty_map_is_none():
    assert opx.nearest_sample([], 0.0, 0.0) is None


def test_nearest_sample_ignores_unplottable_points():
    """The click lands on the rendered map, which does not include the rows
    that were dropped; matching against them would return a sample the
    operator cannot see."""
    pmdata = [{"x": "n/a", "y": "n/a"}, {"x": 5.0, "y": 5.0}]
    assert opx.nearest_sample(pmdata, 5.1, 5.1) == 2


def test_composition_text_lists_the_fractions():
    assert opx.composition_text({"A": 0.6, "B": 0.4}) == "A_0.6 B_0.4"


def test_composition_text_without_fractions():
    """A dash, not an empty string: an empty readout looks like a failure to
    load rather than a plate with no composition."""
    assert opx.composition_text({"x": 1.0}) == "-"


def test_sample_summary_reports_code_and_composition():
    summary = opx.sample_summary(_pm(3), 2)
    assert summary["code"] == "1"
    assert "A_0.9" in summary["composition"]


def test_sample_summary_for_a_sample_not_on_the_plate():
    summary = opx.sample_summary(_pm(3), 99)
    assert summary["error"]
    assert summary["composition"] == ""


def test_sample_summary_rejects_a_zero_sample_number():
    """Sample numbers are 1-based, so 0 is not merely absent -- taking it as
    an index would silently return the last sample on the plate."""
    assert opx.sample_summary(_pm(3), 0)["error"]


def test_poll_interval_survives_a_params_block_that_is_not_a_mapping():
    """build_app runs at import time, so a malformed config here takes down
    the whole module rather than one page."""
    assert opx.poll_interval_for({"servers": {"ui": {"params": []}}}, "ui") == (
        opx.DEFAULT_POLL_INTERVAL
    )
    assert opx.poll_interval_for({"servers": []}, "ui") == opx.DEFAULT_POLL_INTERVAL
    assert opx.poll_interval_for({"servers": {"ui": "nope"}}, "ui") == (
        opx.DEFAULT_POLL_INTERVAL
    )


def test_plate_api_survives_a_params_block_that_is_not_a_mapping():
    assert opx.plate_api_for({"params": []}) is None


# -- library paths from a foreign working directory ---------------------------


def test_repo_root_contains_the_helao_package():
    import os

    assert os.path.isdir(os.path.join(opx.repo_root(), "helao"))


def test_rooted_config_makes_the_library_paths_absolute():
    """The Reflex backend runs with its cwd inside the app directory, not the
    repo root, and import_autolibs resolves every library path relative to the
    cwd -- so the libraries silently come back empty."""
    import os

    cfg = {
        "experiment_libraries": ["simulatews_exp", "helao/deploy/test/x_exp.py"],
        "sequence_libraries": ["OERSIM_seq"],
        "loaded_config_path": "/repo/helao/deploy/test/configs/c.yml",
    }
    rooted = opx.rooted_config(cfg)
    assert os.path.isabs(rooted["experiment_path"])
    assert os.path.isabs(rooted["sequence_path"])
    assert os.path.isabs(rooted["experiment_libraries"][1])
    # A bare module name is not a path and must stay a name: it is resolved
    # against the library directory, which is now absolute.
    assert rooted["experiment_libraries"][0] == "simulatews_exp"
    assert rooted["sequence_libraries"] == ["OERSIM_seq"]


def test_rooted_config_derives_the_library_dir_from_the_deployment():
    cfg = {"loaded_config_path": "/repo/helao/deploy/test/configs/c.yml"}
    rooted = opx.rooted_config(cfg)
    assert rooted["experiment_path"].endswith(
        os.path.join("helao", "deploy", "test", "experiments")
    )
    assert rooted["sequence_path"].endswith(
        os.path.join("helao", "deploy", "test", "sequences")
    )


def test_rooted_config_keeps_an_explicit_path_but_makes_it_absolute():
    cfg = {
        "experiment_path": "helao/deploy/other/experiments",
        "loaded_config_path": "/repo/helao/deploy/test/configs/c.yml",
    }
    rooted = opx.rooted_config(cfg)
    assert os.path.isabs(rooted["experiment_path"])
    assert rooted["experiment_path"].endswith(
        os.path.join("helao", "deploy", "other", "experiments")
    )


def test_rooted_config_leaves_an_already_absolute_path_alone():
    cfg = {
        "experiment_path": "/somewhere/experiments",
        "loaded_config_path": "/repo/helao/deploy/test/configs/c.yml",
    }
    assert opx.rooted_config(cfg)["experiment_path"] == "/somewhere/experiments"


def test_rooted_config_does_not_mutate_the_caller_config():
    """The same world config is shared with every other server in the process."""
    cfg = {
        "experiment_libraries": ["helao/deploy/test/x_exp.py"],
        "loaded_config_path": "/repo/helao/deploy/test/configs/c.yml",
    }
    opx.rooted_config(cfg)
    assert cfg["experiment_libraries"] == ["helao/deploy/test/x_exp.py"]
    assert "experiment_path" not in cfg


def test_rooted_config_invents_no_library_dir_for_an_out_of_tree_config():
    """A config copied to USER_CONFIG names no deployment. Reading one out of
    the path anyway gave `DATA`, and every lookup then pointed into
    helao/deploy/DATA. With none, import_autolibs runs its own cascade."""
    cfg = {"loaded_config_path": "/INST_hlo/DATA/USER_CONFIG/eche10.yml"}
    rooted = opx.rooted_config(cfg)
    assert "experiment_path" not in rooted
    assert "sequence_path" not in rooted


def test_rooted_config_still_roots_library_entries_for_an_out_of_tree_config():
    """No deployment to derive, but a `.py` entry is still a path and still
    must not depend on the cwd."""
    cfg = {
        "experiment_libraries": ["helao/deploy/test/x_exp.py", "simulatews_exp"],
        "loaded_config_path": "/INST_hlo/DATA/USER_CONFIG/eche10.yml",
    }
    rooted = opx.rooted_config(cfg)
    assert os.path.isabs(rooted["experiment_libraries"][0])
    assert rooted["experiment_libraries"][1] == "simulatews_exp"


def test_rooted_config_without_a_loaded_config_path():
    """No deployment to derive: leave the paths alone rather than inventing one."""
    rooted = opx.rooted_config({})
    assert "experiment_path" not in rooted


# -- tick cadence ------------------------------------------------------------


def test_poll_ms_converts_the_configured_interval():
    assert opx.poll_ms_for(2.5) == 2500


def test_poll_ms_never_returns_zero():
    """A zero interval on a ticking component is a busy loop against the
    orchestrator, so it falls back to the default."""
    assert opx.poll_ms_for(0) == int(opx.DEFAULT_POLL_INTERVAL * 1000)
    assert opx.poll_ms_for(-1) == int(opx.DEFAULT_POLL_INTERVAL * 1000)


def test_the_page_ticks_from_a_component_not_a_server_loop():
    """A server-side `while True` outlives the browser tab: on_unmount fires on
    in-app navigation but never on a closed tab, so every abandoned tab left a
    loop polling the orchestrator forever."""
    import ast
    import inspect

    # The AST, not the text: the docstring that explains this fix says
    # "while True", and a substring check would match its own explanation.
    tree = ast.parse(inspect.getsource(opx.OperatorQueueState))
    assert not [n for n in ast.walk(tree) if isinstance(n, (ast.While, ast.AsyncFor))]
    assert hasattr(opx.OperatorQueueState, "poll_once")
    assert not hasattr(opx.OperatorQueueState, "poll_loop")


# -- saved parameters --------------------------------------------------------


def test_store_kind_maps_the_library_kind_to_the_file_key():
    """The store's keys are the Bokeh operator's 'seq'/'exp', and the file is
    shared between the two UIs, so the mapping cannot drift."""
    from helao.core.servers.operator import param_store as ps

    assert opx.store_kind("sequence") == "seq"
    assert opx.store_kind("experiment") == "exp"
    assert set(ps.PARAM_KINDS) == {"seq", "exp"}


def test_store_kind_refuses_an_unknown_library_kind():
    assert opx.store_kind("nonsense") == ""


def test_config_root_comes_from_the_configured_world_config():
    opx.reset_settings()
    opx.configure({"servers": {"UI": {}}, "root": "/inst"}, "UI")
    assert opx.config_root() == "/inst"
    opx.reset_settings()


def test_config_root_without_configuration_is_empty():
    """A read before configure() must return "" rather than raising: the state
    class exists before any config is loaded."""
    opx.reset_settings()
    assert opx.config_root() == ""


def test_saved_values_round_trip_through_the_shared_store(tmp_path):
    """What the Reflex form saves is what the Bokeh operator would read, and
    comes back as strings the form's inputs can hold."""
    from helao.core.servers.operator import param_store as ps

    root = str(tmp_path)
    ps.write_params(root, "seq", "seq_a", {"alpha": 4})
    assert opx.saved_values(root, "sequence", "seq_a") == {"alpha": "4"}


def test_saved_values_for_a_name_with_nothing_saved(tmp_path):
    assert opx.saved_values(str(tmp_path), "sequence", "seq_a") == {}


def test_saved_values_refuses_an_unknown_kind(tmp_path):
    assert opx.saved_values(str(tmp_path), "nonsense", "seq_a") == {}


# -- spec files --------------------------------------------------------------


def test_spec_config_keys_are_read_from_the_server_params():
    cfg = {
        "params": {
            "seqspec_parser_path": "/d/parser.py",
            "seqspec_folder_path": "/d/specs",
            "parser_kwargs": {"k": 1},
        }
    }
    assert opx.spec_parser_path(cfg) == "/d/parser.py"
    assert opx.spec_folder_path(cfg) == "/d/specs"
    assert opx.parser_kwargs(cfg) == {"k": 1}


def test_spec_config_is_empty_when_unconfigured():
    """Opt-in: without these keys the tab renders a note, not a selector."""
    assert opx.spec_parser_path({}) == ""
    assert opx.spec_folder_path({"params": {}}) == ""
    assert opx.parser_kwargs({"params": {}}) == {}


def test_spec_config_survives_a_params_block_that_is_not_a_mapping():
    """Same hazard as poll_interval_for: build_app runs at import time."""
    assert opx.spec_parser_path({"params": []}) == ""
    assert opx.spec_folder_path({"params": "no"}) == ""
    assert opx.parser_kwargs({"params": []}) == {}


def test_parser_kwargs_ignores_a_non_mapping_value():
    assert opx.parser_kwargs({"params": {"parser_kwargs": ["a"]}}) == {}


def test_spec_fields_coerce_through_the_same_path_as_library_params():
    """spec_fields returns the same field shape, so one coercion serves both."""
    from helao.core.servers.operator import spec_parser as sp

    class Parser:
        PARAM_TYPES = {"plate_id": int}

        def list_params(self, path, backend):
            return {"plate_id": None}

    fields = sp.spec_fields(Parser(), "a.txt", backend=None)
    params, errors = opx.coerce_params(fields, {"plate_id": "6284"})
    assert params == {"plate_id": 6284}
    assert errors == []


def test_a_spec_parameter_left_empty_is_reported():
    """Spec parameters are required and start empty, so an untouched one must
    fail loudly rather than reaching the parser as an empty string."""
    from helao.core.servers.operator import spec_parser as sp

    class Parser:
        PARAM_TYPES = {"plate_id": int}

        def list_params(self, path, backend):
            return {"plate_id": None}

    fields = sp.spec_fields(Parser(), "a.txt", backend=None)
    params, errors = opx.coerce_params(fields, {})
    assert "plate_id" not in params
    assert errors


def test_history_rows_on_a_payload_that_is_not_uuid_pairs():
    """get_histories is contracted to return (uuid, payload) pairs. A backend
    that returns bare dicts must not take the handler down."""
    import pytest as _pytest

    with _pytest.raises(Exception):
        # Documents the shape the handler now guards against, rather than
        # pretending history_rows tolerates it.
        opx.history_rows({"action": [{"action_name": "a"}]}, "action")


def test_a_campaign_gets_a_uuid_stamped_on_the_sequence():
    """The campaign-uuid field must reach the sequence. An input the enqueue
    ignores is worse than no input at all."""
    from uuid import UUID

    _fresh_libs()
    backend = LibBackend()
    items, _ = opx.library_items(backend, "sequence", {})
    fields = opx.fields_for_item(items[0])
    sequence, error = opx.build_sequence(
        backend, items[0], fields, {}, campaign="camp-1"
    )
    assert error == ""
    assert sequence.campaign_name == "camp-1"
    assert isinstance(sequence.campaign_uuid, UUID)


def test_an_entered_campaign_uuid_is_used_verbatim():
    from uuid import UUID

    _fresh_libs()
    backend = LibBackend()
    items, _ = opx.library_items(backend, "sequence", {})
    fields = opx.fields_for_item(items[0])
    entered = "12345678-1234-5678-1234-567812345678"
    sequence, _ = opx.build_sequence(
        backend, items[0], fields, {}, campaign="c", campaign_uuid=entered
    )
    assert sequence.campaign_uuid == UUID(entered)


def test_no_campaign_means_no_campaign_stamp():
    _fresh_libs()
    backend = LibBackend()
    items, _ = opx.library_items(backend, "sequence", {})
    fields = opx.fields_for_item(items[0])
    sequence, _ = opx.build_sequence(backend, items[0], fields, {})
    assert not sequence.campaign_name


def test_a_manual_sequence_also_carries_the_campaign():
    from uuid import UUID

    _fresh_libs()
    items, _ = opx.library_items(LibBackend(), "experiment", {})
    fields = opx.fields_for_item(items[0])
    sequence, _ = opx.build_manual_sequence(items[0], fields, {}, campaign="camp-2")
    assert sequence.campaign_name == "camp-2"
    assert isinstance(sequence.campaign_uuid, UUID)


# -- the attribute tree ------------------------------------------------------


def test_history_entries_keeps_each_row_beside_its_payload():
    """The alignment the tree depends on: row n must be object n.

    Rows and payloads are built in one pass precisely so a second sort cannot
    put a different object under the clicked row.
    """
    histories = {
        "sequence": [
            ("aaaa1111", {"sequence_name": "first", "sequence_status": ["done"]}),
            ("bbbb2222", {"sequence_name": "second", "sequence_status": ["done"]}),
        ]
    }
    entries = opx.history_entries(histories, "sequence")
    # Most recent first, so 'second' leads -- and its payload comes with it.
    assert [obj["sequence_name"] for _, obj in entries] == ["second", "first"]
    assert opx.history_rows(histories, "sequence") == [row for row, _ in entries]


def test_history_entries_carries_the_full_payload_not_the_display_copy():
    """The tree shows what the orchestrator holds, uuid unabbreviated."""
    histories = {"sequence": [("abcdef1234567890", {"sequence_name": "cv"})]}
    ((_row, obj),) = opx.history_entries(histories, "sequence")
    assert obj == {"sequence_name": "cv"}, "the derived display fields leaked in"


def test_tree_for_reports_the_empty_state():
    assert opx.tree_for("sequence", None) == (opx.TREE_EMPTY_HEADER, "")
    assert opx.tree_for("sequence", {}) == (opx.TREE_EMPTY_HEADER, "")


def test_tree_for_titles_the_object_and_opens_its_params():
    header, html = opx.tree_for(
        "sequence",
        {
            "sequence_name": "CV",
            "sequence_uuid": "abcdef1234567890",
            "sequence_params": {"rate": 0.1},
            "other": 1,
        },
    )
    assert "CV" in header and "34567890" in header
    # Params expanded, everything else collapsed.
    assert "<details open><summary>sequence_params" in html
    assert "<details><summary>other" not in html  # a scalar is not a disclosure
    assert "rate" in html


def test_tree_for_falls_back_to_a_dash_when_there_is_no_name():
    header, html = opx.tree_for("sequence", {"unrelated": 1})
    assert header == "—"
    assert "unrelated" in html


def test_tree_for_escapes_object_values():
    _header, html = opx.tree_for("sequence", {"sequence_name": "<b>x</b>"})
    assert "&lt;b&gt;" in html
