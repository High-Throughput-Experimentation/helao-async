"""Bokeh operator guards: empty tab lists, seqspec plate-map lookup, sample bounds,
and a quote-safe modified-colour callback. Widgets only; no server, no document."""

from types import SimpleNamespace

from bokeh.models import CustomJS, TextInput
from bokeh.plotting import figure

from helao.ui.bokeh.operator import BokehOperator


def _op(**attrs):
    op = BokehOperator.__new__(BokehOperator)
    for k, v in attrs.items():
        setattr(op, k, v)
    return op


def test_update_selector_layout_tolerates_empty_lists():
    op = _op(seqspec_select_list=[], experiment_select_list=[], sequence_select_list=[])
    for tab in (0, 1, 2):
        op.update_selector_layout("active", 0, tab)


def test_seqspec_inputs_are_found_for_plate_map_callbacks():
    sender = TextInput(name="solid_plate_id")
    priv = [figure(title="PlateMap")]
    op = _op(
        exp_param_input=[],
        exp_private_input=[],
        seq_param_input=[],
        seq_private_input=[],
        seqspec_param_input=[sender],
        seqspec_private_input=priv,
    )
    assert op.find_param_private_input(sender) == (priv, [sender])


def _sample_op(plate_value, pmdata):
    sender = TextInput(name="solid_plate_id", value=plate_value)
    sample = TextInput(name="solid_sample_no", value="")
    ticks = []
    op = _op(
        dataAPI=SimpleNamespace(get_platemap_plateid=lambda _p: pmdata),
        exp_param_input=[sender, sample],
        exp_private_input=[figure(title="PlateMap")],
        seq_param_input=[],
        seq_private_input=[],
        seqspec_param_input=[],
        seqspec_private_input=[],
        vis=SimpleNamespace(doc=SimpleNamespace(add_next_tick_callback=ticks.append)),
    )
    return op, sender, ticks


def test_sample_one_past_the_end_is_rejected_not_indexed():
    op, sender, _ = _sample_op("1", [{"x": 0, "y": 0}])
    assert op.get_sample_infos([1], sender) is False  # would IndexError at [1]


def test_empty_plate_id_does_not_raise():
    op, sender, _ = _sample_op("", [])
    assert op.get_sample_infos([0], sender) is False


def test_default_with_quote_is_passed_as_data_not_spliced_into_js():
    op = _op(
        skip_default_highlights=[],
        dataAPI=None,
        dev_customitems=[],
        max_width=300,
    )
    op.__dict__.setdefault("color_sq_param_inputs", "#fff")
    param_input, layout = [], []
    try:
        op.add_dynamic_inputs(
            param_input, [], layout, ["p"], ["it's `x`"], ["str"], [], None
        )
    except AttributeError as e:  # a widget attr this bare instance lacks
        raise AssertionError(f"harness lacks {e}") from e
    cbs = [
        cb
        for cb in param_input[0].js_property_callbacks["change:value"]
        if isinstance(cb, CustomJS)
    ]
    assert cbs and cbs[0].args["def_val"] == "it's `x`"
    assert "it's" not in cbs[0].code
