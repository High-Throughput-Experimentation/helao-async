"""The Gamry/Biologic visualizers' axis selectors are dropdowns keyed by name.

Both visualizers used to hold the axis choice as an *index* into
``data_dict_keys`` because the widget was a ``RadioButtonGroup`` whose state is
an index. They are ``Select`` widgets now, whose state is the option string, and
the cached ``xselect``/``yselect`` are the data-key names themselves.

That migration is the kind that fails silently: an index left in place where a
name is expected still plots — just the wrong column, with no error on either
side. These tests build both visualizers for real and assert on the column names
the plot renderers actually received.

Run directly (``python -m pytest`` on this file) — the hte suite is not part of
``run_unit_tests.py``.
"""

import asyncio

import pytest
from bokeh.document import Document
from bokeh.models import Select

SERV_KEY = "PSTAT"
SERVERS = {SERV_KEY: {"host": "127.0.0.1", "port": 8004}}


class _FakeVis:
    """The two attributes ``VisSubscriber.__init__`` reads, plus a document."""

    def __init__(self, doc, params=None):
        self.doc = doc
        self.server_cfg = {"params": params or {}}
        self.world_cfg = {"servers": SERVERS}


def _build(module, params=None):
    """Construct a visualizer and stop its ingest task before it does any work.

    ``_mount`` starts ``IOloop_data`` with ``asyncio.create_task``, so this has
    to run inside a loop; the task is cancelled immediately, before it can open
    a socket to a server that is not there.
    """

    async def _make():
        vis = module.C_vis(_FakeVis(Document(), params), SERV_KEY)
        vis.IOloop_data_run = False
        vis.IOtask.cancel()
        return vis

    return asyncio.run(_make())


def _field(spec):
    """Column name from a glyph property, which Bokeh may hold either way.

    ``line(x="t_s")`` stores the bare string; a spec built with ``field()``
    stores a ``Field``. Both mean the same column.
    """
    return spec if isinstance(spec, str) else spec.field


def _plotted_axes(plot):
    """Return the ``(x, y)`` column names the plot's line renderers are bound to."""
    return [
        (_field(r.glyph.x), _field(r.glyph.y))
        for r in plot.renderers
        if hasattr(getattr(r, "glyph", None), "x")
    ]


@pytest.mark.parametrize("modname", ["gamry_vis", "biologic_vis"])
def test_axis_selectors_are_dropdowns(modname):
    import importlib

    module = importlib.import_module(f"helao.deploy.hte.servers.visualizer.{modname}")
    vis = _build(module, params={"num_channels": 1})

    for selector, title in (
        (vis.xaxis_selector_group, "x-axis:"),
        (vis.yaxis_selector_group, "y-axis:"),
    ):
        assert isinstance(selector, Select), type(selector)
        # The Select carries the label, so the layout has no separate Div for
        # it; a lost title would leave two unlabelled dropdowns side by side.
        assert selector.title == title, selector.title
        assert selector.options == vis.data_dict_keys, selector.options

    # The cached selection is the data key itself, not an index.
    assert vis.xselect == vis.data_dict_keys[0], vis.xselect
    assert vis.yselect == vis.data_dict_keys[3], vis.yselect
    print(f"test_axis_selectors_are_dropdowns[{modname}] PASS")


@pytest.mark.parametrize("modname", ["gamry_vis", "biologic_vis"])
def test_changing_an_axis_replots_that_column(modname):
    import importlib

    module = importlib.import_module(f"helao.deploy.hte.servers.visualizer.{modname}")
    vis = _build(module, params={"num_channels": 1})
    plot = vis.plot if modname == "gamry_vis" else vis.channel_plots[0]

    # Nothing is plotted until a selection changes or data arrives — the
    # construction-time reset_plot only rebuilds when it is handed a package.
    assert _plotted_axes(plot) == []

    # Pick a pair that is neither default and confirm the plot follows it. This
    # is the assertion an index left in place would fail: data_dict_keys[1] and
    # [2] are valid indices too, so the wrong reading still plots something.
    new_x, new_y = vis.data_dict_keys[1], vis.data_dict_keys[2]
    vis.xaxis_selector_group.value = new_x
    vis.yaxis_selector_group.value = new_y
    # The widget callbacks are Bokeh property callbacks; drive the same entry
    # point they do rather than relying on a document to dispatch them.
    vis.callback_selector_change("value", None, new_y)

    axes = _plotted_axes(plot)
    assert axes, "no line renderer after the axis change"
    for x, y in axes:
        assert (x, y) == (new_x, new_y), (x, y)
    # And the cache caught up, so the next change is detected rather than
    # compared against a stale index.
    assert (vis.xselect, vis.yselect) == (new_x, new_y), (vis.xselect, vis.yselect)
    print(f"test_changing_an_axis_replots_that_column[{modname}] PASS")


if __name__ == "__main__":
    for name in ("gamry_vis", "biologic_vis"):
        test_axis_selectors_are_dropdowns(name)
        test_changing_an_axis_replots_that_column(name)
    print("ALL PSTAT_VIS_AXIS_SELECTOR TESTS PASS")
