"""Section panels stretch without dragging their fixed-width widgets along.

``bokeh.layouts.layout(sizing_mode=...)`` does not merely size the container it
returns: ``_create_grid`` assigns that mode to every child it walks whose own
``sizing_mode`` is ``None`` and whose width/height policies are both ``"auto"``.
That is every plain ``TextInput(width=150)``, ``Button(width=70)`` and
``DataTable(width=400)`` in the visualizers, so passing the kwarg silently
overrode their widths — measured 785px inputs on a 1600px page, and a
``[plot, Spacer, table]`` row splitting three ways so the plot rendered at 526px
instead of filling what the table left.

:func:`stretch_section` walks the built tree instead and touches containers
only. These tests pin both halves: that it stretches what it should, and that
the kwarg it replaces really does have the side effect described above — if a
future Bokeh drops that behaviour, the second test fails and the helper can go.
"""

from bokeh.layouts import layout
from bokeh.models import Button, Column, Div, Row, Spacer, TextInput
from bokeh.plotting import figure

from helao.core.servers.bokeh_theme import SECTION_MARGIN, stretch_section


def _panel():
    """A layout shaped like a visualizer's: banner, controls row, plot + table."""
    return layout(
        [
            [Div(text="banner", sizing_mode="stretch_width", height=15)],
            [TextInput(value="1", width=150), Button(label="Stop", width=70)],
            Spacer(height=10),
            [figure(height=300, sizing_mode="stretch_width"), Spacer(width=20)],
        ],
        margin=SECTION_MARGIN,
    )


def _walk(model):
    yield model
    for child in getattr(model, "children", []):
        yield from _walk(child)


def test_stretch_section_stretches_containers_only():
    panel = stretch_section(_panel())

    assert panel.sizing_mode == "stretch_width"
    containers = [m for m in _walk(panel) if isinstance(m, (Row, Column))]
    assert len(containers) > 1, "expected nested rows to walk into"
    for container in containers:
        assert container.sizing_mode == "stretch_width", container

    # The widgets that asked for a width still have one, and no sizing mode
    # that would override it.
    for model in _walk(panel):
        if isinstance(model, (TextInput, Button)):
            assert model.sizing_mode is None, (model, model.sizing_mode)
            assert model.width in (150, 70), model.width

    # A figure that asked to stretch is left asking.
    figs = [m for m in _walk(panel) if isinstance(m, figure)]
    assert figs and all(f.sizing_mode == "stretch_width" for f in figs)
    print("test_stretch_section_stretches_containers_only PASS")


def test_the_layout_kwarg_really_does_overwrite_child_sizing():
    """Why :func:`stretch_section` exists at all.

    If this ever fails, Bokeh stopped propagating and the helper is redundant.
    """
    panel = layout(
        [[TextInput(value="1", width=150), Button(label="Stop", width=70)]],
        sizing_mode="stretch_width",
    )
    widgets = [m for m in _walk(panel) if isinstance(m, (TextInput, Button))]
    assert widgets, "no widgets to check"
    assert all(w.sizing_mode == "stretch_width" for w in widgets), [
        (type(w).__name__, w.sizing_mode) for w in widgets
    ]
    print("test_the_layout_kwarg_really_does_overwrite_child_sizing PASS")


def test_section_margin_is_the_shared_four_pixel_inset():
    # The operator and every visualizer read this one constant; a per-app copy
    # would let two pages on one station disagree about their edges.
    assert SECTION_MARGIN == (4, 4, 4, 4)
    assert _panel().margin == SECTION_MARGIN
    print("test_section_margin_is_the_shared_four_pixel_inset PASS")


if __name__ == "__main__":
    test_stretch_section_stretches_containers_only()
    test_the_layout_kwarg_really_does_overwrite_child_sizing()
    test_section_margin_is_the_shared_four_pixel_inset()
    print("ALL BOKEH_SECTION_SIZING TESTS PASS")
