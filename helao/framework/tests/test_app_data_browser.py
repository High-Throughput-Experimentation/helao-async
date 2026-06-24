"""Unit tests for the framework data_browser Bokeh app."""
import json
import os
import tempfile
from pathlib import Path

import yaml

from bokeh.document import Document

from helao.framework.adapters.data_browser import sources


def _write_hlo(path):
    with open(path, "w") as f:
        f.write("hlo_version: 1.0\naction_name: cv\ncolumn_headings: [t_s, Ewe_V]\n%%\n")
        f.write(json.dumps({"t_s": 0.0, "Ewe_V": 0.1}) + "\n")
        f.write(json.dumps({"t_s": 1.0, "Ewe_V": 0.2}) + "\n")


def _make_finished_tree(root):
    act_dir = os.path.join(
        root, "RUNS_FINISHED", "26.25", "0618",
        "141523__SDC_seq__lab1", "260618.141524__SDC_exp_CV", "1__0__sim__cv")
    os.makedirs(act_dir)
    _write_hlo(os.path.join(act_dir, "cv_data.hlo"))
    with open(os.path.join(act_dir, "260618.141525-act.yml"), "w") as f:
        yaml.safe_dump({"technique_name": "CV", "run_type": "data",
                        "samples_out": [{"global_label": "solid__lab1_1"}]}, f)


class _FakeDirs:
    def __init__(self, root):
        self.root = Path(root)
        self.log_root = None


class _FakeVis:
    def __init__(self, root, doc):
        self.world_cfg = {}
        self.helaodirs = _FakeDirs(root)
        self.doc = doc
        self.server_cfg = {"params": {"max_points": 50000}}

    def print_message(self, *a, **k):
        pass


def test_build_document_smoke():
    from helao.framework.app.data_browser import build_document
    with tempfile.TemporaryDirectory() as d:
        _make_finished_tree(d)
        doc = Document()
        build_document(_FakeVis(d, doc))
        assert len(doc.roots) >= 1


def test_plot_tab_builds_traces():
    from helao.framework.app.data_browser import _UI
    with tempfile.TemporaryDirectory() as d:
        _make_finished_tree(d)
        doc = Document()
        ui = _UI(_FakeVis(d, doc), d, 50000)
        ui.index_df = sources.get_index(d, "RUNS_FINISHED", None, None)
        ui._refresh_index_table()
        ui.index_source.selected.indices = [0]
        ui._on_add()
        assert len(ui.selected) == 1
        assert set(ui.x_sel.options) == {"t_s", "Ewe_V"}
        ui.x_sel.value, ui.y_sel.value = "t_s", "Ewe_V"
        ui._rebuild_plot()
        assert len(ui.plot.renderers) == 1


def test_table_tab_summary_and_rows():
    from helao.framework.app.data_browser import _UI
    with tempfile.TemporaryDirectory() as d:
        _make_finished_tree(d)
        doc = Document()
        ui = _UI(_FakeVis(d, doc), d, 50000)
        ui.index_df = sources.get_index(d, "RUNS_FINISHED", None, None)
        ui._refresh_index_table()
        ui.index_source.selected.indices = [0]
        ui._on_add()
        ui.x_sel.value, ui.y_sel.value = "t_s", "Ewe_V"
        ui._rebuild_tables()
        assert ui.summary_source.data["n_points"] == [2]
        ui.summary_source.selected.indices = [0]
        ui._on_summary_select("indices", [], [0])
        assert ui.rows_source.data["t_s"] == [0.0, 1.0]
        assert ui.rows_source.data["Ewe_V"] == [0.1, 0.2]


def test_plot_replot_and_clear_safe():
    from helao.framework.app.data_browser import _UI
    with tempfile.TemporaryDirectory() as d:
        _make_finished_tree(d)
        doc = Document()
        ui = _UI(_FakeVis(d, doc), d, 50000)
        ui.index_df = sources.get_index(d, "RUNS_FINISHED", None, None)
        ui._refresh_index_table()
        ui.index_source.selected.indices = [0]
        ui._on_add()
        ui.x_sel.value, ui.y_sel.value = "t_s", "Ewe_V"
        ui._rebuild_plot()
        ui._rebuild_plot()  # replot: exercises legend-clear path twice
        assert len(ui.plot.renderers) == 1
        ui.summary_source.selected.indices = [0]
        ui._on_clear()
        ui._on_summary_select("indices", [], [0])  # stale index must not raise
        assert ui.selected == []
