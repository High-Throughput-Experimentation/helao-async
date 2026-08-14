"""Standalone tests for the data_browser package. No pytest; run with:

    PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao \
        python -m helao.deploy.test.tests.test_data_browser
"""

import json
import os
import tempfile
import zipfile

import pyarrow as pa
import pyarrow.parquet as pq
import yaml
from bokeh.document import Document

from helao.core.models.run_dir import RunDir
from helao.ui.shared.data_browser import readers, sources
from helao.ui.shared.data_browser import state as dbstate


class _FakeDirs:
    def __init__(self, root):
        from pathlib import Path

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


class _RecordingVis(_FakeVis):
    """A vis that keeps what the UI reported, so a silent skip is visible."""

    def __init__(self, root, doc):
        super().__init__(root, doc)
        self.messages = []

    def print_message(self, *a, **k):
        self.messages.append(" ".join(str(x) for x in a))


def _write_hlo(path):
    """Write a minimal HLO file (YAML header, %% marker, JSONL body)."""
    with open(path, "w") as f:
        f.write("hlo_version: 1.0\n")
        f.write("action_name: cv\n")
        f.write("column_headings: [t_s, Ewe_V]\n")
        f.write("%%\n")
        f.write(json.dumps({"t_s": 0.0, "Ewe_V": 0.1}) + "\n")
        f.write(json.dumps({"t_s": 1.0, "Ewe_V": 0.2}) + "\n")


def test_read_hlo_file():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "cv_data.hlo")
        _write_hlo(p)
        meta, data = readers.read_dataset(p)
        assert data["t_s"] == [0.0, 1.0], data
        assert data["Ewe_V"] == [0.1, 0.2], data
    print("test_read_hlo_file PASS")


def test_read_json_columnar():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "out.json")
        with open(p, "w") as f:
            json.dump({"wl_nm": [400, 500], "abs": [0.1, 0.2], "note": "x"}, f)
        meta, data = readers.read_dataset(p, fmt="json")
        assert data == {"wl_nm": [400, 500], "abs": [0.1, 0.2]}, data
        assert meta == {"note": "x"}, meta
    print("test_read_json_columnar PASS")


def test_read_json_records():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "recs.json")
        with open(p, "w") as f:
            json.dump([{"a": 1, "b": 2}, {"a": 3, "b": 4}], f)
        _, data = readers.read_dataset(p, fmt="json")
        assert data == {"a": [1, 3], "b": [2, 4]}, data
    print("test_read_json_records PASS")


def test_read_parquet():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "pat.parquet")
        table = pa.table({"q": [1.0, 2.0], "I": [10.0, 20.0]})
        pq.write_table(table, p)
        _, data = readers.read_dataset(p)
        assert data == {"q": [1.0, 2.0], "I": [10.0, 20.0]}, data
    print("test_read_parquet PASS")


def test_read_hlo_from_zip():
    with tempfile.TemporaryDirectory() as d:
        hlo = os.path.join(d, "cv_data.hlo")
        _write_hlo(hlo)
        zip_path = os.path.join(d, "seq.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.write(hlo, "exp/act/cv_data.hlo")
        loc = readers.make_zip_locator(zip_path, "exp/act/cv_data.hlo")
        _, data = readers.read_dataset(loc, fmt="hlo")
        assert data["t_s"] == [0.0, 1.0], data
    print("test_read_hlo_from_zip PASS")


def test_dir_walk_and_range():
    with tempfile.TemporaryDirectory() as d:
        base = os.path.join(d, RunDir.FINISHED.value)
        for ww, mmdd in [("26.20", "0515"), ("26.25", "0618")]:
            os.makedirs(os.path.join(base, ww, mmdd))
        dates = [ds for ds, _ in sources._list_day_dirs(base)]
        assert dates == ["26.20/0515", "26.25/0618"], dates
        assert sources._in_range("26.25/0618", "26.22", "26.30") is True
        assert sources._in_range("26.20/0515", "26.22", "26.30") is False
        assert sources._in_range("26.25/0618", None, None) is True
    print("test_dir_walk_and_range PASS")


def _make_finished_tree(root):
    """Create root/RUNS_FINISHED/26.25/0618/<seq>/<exp>/<act>/ with an .hlo + act.yml."""
    act_dir = os.path.join(
        root,
        RunDir.FINISHED.value,
        "26.25",
        "0618",
        "141523__SDC_seq__lab1",
        "260618.141524__SDC_exp_CV",
        "1__0__sim__cv",
    )
    os.makedirs(act_dir)
    _write_hlo(os.path.join(act_dir, "cv_data.hlo"))
    with open(os.path.join(act_dir, "260618.141525-act.yml"), "w") as f:
        yaml.safe_dump(
            {
                "technique_name": "CV",
                "run_type": "data",
                "samples_out": [{"global_label": "solid__lab1_1"}],
            },
            f,
        )


def test_runs_finished_index():
    with tempfile.TemporaryDirectory() as d:
        _make_finished_tree(d)
        idx = sources.RunsSourceIndex(d, "FINISHED")
        df = idx.index()
        assert list(df.columns) == sources.INDEX_COLUMNS, list(df.columns)
        assert len(df) == 1, df
        r = df.iloc[0]
        assert r["source"] == RunDir.FINISHED
        assert r["sequence"] == "SDC_seq"
        assert r["technique"] == "CV"
        assert r["sample"] == "solid__lab1_1"
        assert r["file_name"] == "cv_data.hlo"
        assert r["file_type"] == "hlo"
        assert r["available"] is True
        _, data = readers.read_dataset(r["locator"], r["file_type"])
        assert data["t_s"] == [0.0, 1.0]
    print("test_runs_finished_index PASS")


def _make_synced_zip(root):
    """Create root/RUNS_SYNCED/26.25/0618/<seq>.zip with act.yml + .hlo members."""
    day = os.path.join(root, RunDir.SYNCED.value, "26.25", "0618")
    os.makedirs(day)
    with tempfile.TemporaryDirectory() as tmp:
        hlo = os.path.join(tmp, "cv_data.hlo")
        _write_hlo(hlo)
        actyml = os.path.join(tmp, "act.yml")
        with open(actyml, "w") as f:
            yaml.safe_dump(
                {
                    "technique_name": "CV",
                    "samples_out": [{"global_label": "solid__lab1_1"}],
                },
                f,
            )
        zpath = os.path.join(day, "141523__SDC_seq__lab1.zip")
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.write(
                actyml, "260618.141524__SDC_exp_CV/1__0__sim__cv/260618.141525-act.yml"
            )
            zf.write(hlo, "260618.141524__SDC_exp_CV/1__0__sim__cv/cv_data.hlo")


def test_runs_synced_index():
    with tempfile.TemporaryDirectory() as d:
        _make_synced_zip(d)
        df = sources.RunsSourceIndex(d, "SYNCED").index()
        assert len(df) == 1, df
        r = df.iloc[0]
        assert r["source"] == RunDir.SYNCED
        assert r["sequence"] == "SDC_seq"
        assert r["technique"] == "CV"
        assert r["sample"] == "solid__lab1_1"
        assert r["file_name"] == "cv_data.hlo"
        assert r["locator"].startswith("zip::")
        _, data = readers.read_dataset(r["locator"], r["file_type"])
        assert data["Ewe_V"] == [0.1, 0.2]
    print("test_runs_synced_index PASS")


def _make_process(root):
    """Create a -prc.yml referencing the .hlo created by _make_finished_tree."""
    prc_dir = os.path.join(
        root,
        "PROCESSES",
        "26.25",
        "0618",
        "141523__SDC_seq__lab1",
        "260618.141524__SDC_exp_CV",
    )
    os.makedirs(prc_dir)
    with open(os.path.join(prc_dir, "0__abc__CV-prc.yml"), "w") as f:
        yaml.safe_dump(
            {
                "technique_name": "CV",
                "run_type": "data",
                "samples_out": [{"global_label": "solid__lab1_1"}],
                "files": [{"file_name": "cv_data.hlo", "file_type": "helao__file"}],
            },
            f,
        )


def test_processes_index_resolves_to_runs():
    with tempfile.TemporaryDirectory() as d:
        _make_finished_tree(d)  # the actual cv_data.hlo
        _make_process(d)  # the -prc.yml that references it
        df = sources.DerivedSourceIndex(d, "PROCESSES").index()
        assert len(df) == 1, df
        r = df.iloc[0]
        assert r["source"] == "PROCESSES"
        assert r["technique"] == "CV"
        assert r["sample"] == "solid__lab1_1"
        assert r["file_name"] == "cv_data.hlo"
        assert r["available"] is True
        _, data = readers.read_dataset(r["locator"], r["file_type"])
        assert data["t_s"] == [0.0, 1.0]


def test_processes_index_missing_file_unavailable():
    with tempfile.TemporaryDirectory() as d:
        _make_process(d)  # prc.yml but NO RUNS_FINISHED data
        df = sources.DerivedSourceIndex(d, "PROCESSES").index()
        assert len(df) == 1
        assert df.iloc[0]["available"] is False
        assert df.iloc[0]["locator"] == ""
    print("test_processes_index PASS")


def _make_analysis(root, with_local_output=True):
    ana_dir = os.path.join(root, "ANALYSES", "26.25", "0618", "150305__icpms__plate1")
    os.makedirs(ana_dir)
    with open(os.path.join(ana_dir, "uuid1234.yml"), "w") as f:
        yaml.safe_dump(
            {
                "analysis_name": "icpms",
                "global_sample_label": "solid__lab1_1",
                "outputs": [
                    {
                        "analysis_output_path": {
                            "bucket": "b",
                            "key": "analysis/uuid1234/conc.json",
                            "region": "r",
                        },
                        "content_type": "application/json",
                        "output_type": "concentration",
                        "output_name": "conc",
                    }
                ],
            },
            f,
        )
    if with_local_output:
        with open(os.path.join(ana_dir, "conc.json"), "w") as f:
            json.dump({"element": ["Ni", "Fe"], "ppm": [12.0, 3.4]}, f)


def test_analyses_index_local():
    with tempfile.TemporaryDirectory() as d:
        _make_analysis(d, with_local_output=True)
        df = sources.DerivedSourceIndex(d, "ANALYSES").index()
        assert len(df) == 1, df
        r = df.iloc[0]
        assert r["source"] == "ANALYSES"
        assert r["sequence"] == "icpms"
        assert r["sample"] == "solid__lab1_1"
        assert r["file_type"] == "json"
        assert r["available"] is True
        _, data = readers.read_dataset(r["locator"], r["file_type"])
        assert data["ppm"] == [12.0, 3.4]


def test_analyses_index_s3_only_unavailable():
    with tempfile.TemporaryDirectory() as d:
        _make_analysis(d, with_local_output=False)
        df = sources.DerivedSourceIndex(d, "ANALYSES").index()
        assert len(df) == 1
        assert df.iloc[0]["available"] is False
        assert df.iloc[0]["locator"] == ""
    print("test_analyses_index PASS")


def test_get_index_dispatch():
    with tempfile.TemporaryDirectory() as d:
        _make_finished_tree(d)
        df = sources.get_index(d, RunDir.FINISHED, None, None)
        assert df.iloc[0]["source"] == RunDir.FINISHED
        empty = sources.get_index(d, "ANALYSES", None, None)
        assert list(empty.columns) == sources.INDEX_COLUMNS
        assert len(empty) == 0
    print("test_get_index_dispatch PASS")


def test_load_selected_end_to_end():
    with tempfile.TemporaryDirectory() as d:
        _make_finished_tree(d)
        _make_process(d)  # adds an unavailable-resolves-to-available process row too
        df = sources.get_index(d, RunDir.FINISHED, None, None)
        datasets, skipped = dbstate.load_selected(df, [0])
        assert len(datasets) == 1 and not skipped, (datasets, skipped)
        ds = datasets[0]
        assert ds.data["t_s"] == [0.0, 1.0]
        assert dbstate.available_columns(datasets) == ["Ewe_V", "t_s"]

        # an unavailable row is skipped, not loaded
        ana = sources.get_index(d, "ANALYSES", None, None)  # empty
        ds2, sk2 = dbstate.load_selected(ana, [])
        assert ds2 == [] and sk2 == []
    print("test_load_selected_end_to_end PASS")


def _ds(label, data, **kw):
    base = dict(
        locator="L",
        source=RunDir.FINISHED,
        sequence="s",
        experiment="e",
        node="n",
        technique="CV",
        sample="smp",
        file_name="f.hlo",
        meta={},
    )
    base.update(kw)
    return dbstate.SelectedDataset(label=label, data=data, **base)


def test_available_columns_union_sorted():
    a = _ds("a", {"t_s": [0, 1], "Ewe_V": [0.1, 0.2]})
    b = _ds("b", {"t_s": [0, 1], "I_A": [1, 2]})
    assert dbstate.available_columns([a, b]) == ["Ewe_V", "I_A", "t_s"]


def test_build_trace_and_downsample():
    a = _ds("a", {"t_s": [0, 1, 2, 3], "Ewe_V": [0.1, 0.2, 0.3, 0.4]})
    tr = dbstate.build_trace(a, "t_s", "Ewe_V")
    assert tr == {"x": [0, 1, 2, 3], "y": [0.1, 0.2, 0.3, 0.4]}
    assert dbstate.build_trace(a, "t_s", "missing") is None
    ds = dbstate.downsample(tr, 2)
    assert len(ds["x"]) <= 2 and ds["x"][0] == 0


def test_summary_row():
    a = _ds("a", {"t_s": [0, 1, 2], "Ewe_V": [0.1, 0.5, 0.3]})
    s = dbstate.summary_row(a, "t_s", "Ewe_V")
    assert s["n_points"] == 3
    assert s["x_min"] == 0 and s["x_max"] == 2
    assert s["y_min"] == 0.1 and s["y_max"] == 0.5
    assert s["source"] == RunDir.FINISHED and s["technique"] == "CV"
    print("test_state PASS")


def test_build_document_smoke():
    from helao.core.servers.data_browser.app import build_document

    with tempfile.TemporaryDirectory() as d:
        _make_finished_tree(d)
        doc = Document()
        vis = _FakeVis(d, doc)
        build_document(vis)
        assert len(doc.roots) >= 1, "build_document added no roots"
    print("test_build_document_smoke PASS")


def test_plot_tab_builds_traces():
    from helao.core.servers.data_browser.app import _UI

    with tempfile.TemporaryDirectory() as d:
        _make_finished_tree(d)
        doc = Document()
        vis = _FakeVis(d, doc)
        ui = _UI(vis, d, 50000)
        ui.index_df = sources.get_index(d, RunDir.FINISHED, None, None)
        ui._refresh_index_table()
        ui.index_source.selected.indices = [0]
        ui._on_add()
        assert len(ui.selected) == 1
        assert set(ui.x_sel.options) == {"t_s", "Ewe_V"}
        ui.x_sel.value, ui.y_sel.value = "t_s", "Ewe_V"
        ui._rebuild_plot()
        assert len(ui.plot.renderers) == 1, ui.plot.renderers
    print("test_plot_tab_builds_traces PASS")


def test_table_tab_summary_and_rows():
    from helao.core.servers.data_browser.app import _UI

    with tempfile.TemporaryDirectory() as d:
        _make_finished_tree(d)
        doc = Document()
        vis = _FakeVis(d, doc)
        ui = _UI(vis, d, 50000)
        ui.index_df = sources.get_index(d, RunDir.FINISHED, None, None)
        ui._refresh_index_table()
        ui.index_source.selected.indices = [0]
        ui._on_add()
        ui.x_sel.value, ui.y_sel.value = "t_s", "Ewe_V"
        ui._rebuild_tables()
        assert ui.summary_source.data["n_points"] == [2], ui.summary_source.data
        ui.summary_source.selected.indices = [0]
        ui._on_summary_select("indices", [], [0])
        assert ui.rows_source.data["t_s"] == [0.0, 1.0], ui.rows_source.data
        assert ui.rows_source.data["Ewe_V"] == [0.1, 0.2]
    print("test_table_tab_summary_and_rows PASS")


def test_plot_replot_and_clear_safe():
    from helao.core.servers.data_browser.app import _UI

    with tempfile.TemporaryDirectory() as d:
        _make_finished_tree(d)
        doc = Document()
        ui = _UI(_FakeVis(d, doc), d, 50000)
        ui.index_df = sources.get_index(d, RunDir.FINISHED, None, None)
        ui._refresh_index_table()
        ui.index_source.selected.indices = [0]
        ui._on_add()
        ui.x_sel.value, ui.y_sel.value = "t_s", "Ewe_V"
        ui._rebuild_plot()
        ui._rebuild_plot()  # replot: exercises legend-clear path twice
        assert len(ui.plot.renderers) == 1
        # select a summary row, then clear -> stale summary index must not raise
        ui.summary_source.selected.indices = [0]
        ui._on_clear()
        ui._on_summary_select("indices", [], [0])
        assert ui.selected == []
    print("test_plot_replot_and_clear_safe PASS")


def test_plot_skips_a_non_numeric_column_and_says_so():
    """A string column must not become a trace, and the skip must be reported.

    HELAO datasets carry strings freely -- an orchestrator host, a status
    message, a sample label sit beside the numeric traces. The Reflex browser
    filtered them (``is_numeric``/``chart_series``, which lived in *its* module
    rather than in the shared layer); the Bokeh browser handed the column
    straight to ``build_trace`` and plotted it. Measured, that does not raise:
    Bokeh accepts a list of strings in a ``ColumnDataSource`` and even renders
    the document, so the operator got a renderer that draws nothing and no
    message saying why. Both UIs now go through ``state.chart_series``.
    """
    from helao.core.servers.data_browser.app import _UI

    with tempfile.TemporaryDirectory() as d:
        vis = _RecordingVis(d, Document())
        ui = _UI(vis, d, 50000)
        ui.selected = [
            _ds(
                "a",
                {
                    "t_s": [0.0, 1.0],
                    "Ewe_V": [0.1, 0.2],
                    "orchestrator": ["127.0.0.1", "127.0.0.1"],
                },
            )
        ]
        ui._refresh_axes()
        ui.x_sel.value, ui.y_sel.value = "t_s", "orchestrator"
        vis.messages.clear()
        ui._rebuild_plot()
        assert ui.plot.renderers == [], ui.plot.renderers
        assert any("not numeric" in m for m in vis.messages), vis.messages
        # ...and the numeric pair from the same dataset still plots.
        ui.y_sel.value = "Ewe_V"
        ui._rebuild_plot()
        assert len(ui.plot.renderers) == 1, ui.plot.renderers
    print("test_plot_skips_a_non_numeric_column_and_says_so PASS")


def test_plot_reports_a_dataset_missing_the_chosen_columns():
    """Overlaying files from unrelated runs is normal; saying nothing is not."""
    from helao.core.servers.data_browser.app import _UI

    with tempfile.TemporaryDirectory() as d:
        vis = _RecordingVis(d, Document())
        ui = _UI(vis, d, 50000)
        ui.selected = [
            _ds("a", {"t_s": [0.0, 1.0], "Ewe_V": [0.1, 0.2]}),
            _ds("b", {"q": [1.0, 2.0], "I": [3.0, 4.0]}),
        ]
        ui._refresh_axes()
        ui.x_sel.value, ui.y_sel.value = "t_s", "Ewe_V"
        vis.messages.clear()
        ui._rebuild_plot()
        assert len(ui.plot.renderers) == 1, ui.plot.renderers
        assert any("b" in m and "t_s/Ewe_V" in m for m in vis.messages), vis.messages
    print("test_plot_reports_a_dataset_missing_the_chosen_columns PASS")


def test_both_browsers_share_one_numeric_guard():
    """The guard lives in the shared layer, not in one UI.

    ``is_numeric``/``chart_series`` were written in ``app_reflex`` -- a UI --
    so the Bokeh browser could not call them. Pin the hoist: the Reflex names
    must *be* the shared-layer objects, not copies that can drift apart.
    """
    from helao.ui.shared.data_browser import app_reflex as dbx

    assert dbx.is_numeric is dbstate.is_numeric
    assert dbx.chart_series is dbstate.chart_series
    print("test_both_browsers_share_one_numeric_guard PASS")


def test_shims_expose_makebokehapp():
    import importlib

    for mod in (
        "helao.deploy.hte.servers.visualizer.data_browser",
        "helao.deploy.test.servers.visualizer.data_browser",
    ):
        m = importlib.import_module(mod)
        assert hasattr(m, "makeBokehApp"), mod
        import inspect

        params = list(inspect.signature(m.makeBokehApp).parameters)
        assert params == ["doc", "confPrefix", "server_key", "helao_repo_root"], (
            mod,
            params,
        )
    print("test_shims_expose_makebokehapp PASS")


def run_all():
    test_read_hlo_file()
    test_read_json_columnar()
    test_read_json_records()
    test_read_parquet()
    test_read_hlo_from_zip()
    test_dir_walk_and_range()
    test_runs_finished_index()
    test_runs_synced_index()
    test_processes_index_resolves_to_runs()
    test_processes_index_missing_file_unavailable()
    test_analyses_index_local()
    test_analyses_index_s3_only_unavailable()
    test_get_index_dispatch()
    test_load_selected_end_to_end()
    test_available_columns_union_sorted()
    test_build_trace_and_downsample()
    test_summary_row()
    test_build_document_smoke()
    test_plot_tab_builds_traces()
    test_table_tab_summary_and_rows()
    test_plot_replot_and_clear_safe()
    test_plot_skips_a_non_numeric_column_and_says_so()
    test_plot_reports_a_dataset_missing_the_chosen_columns()
    test_both_browsers_share_one_numeric_guard()
    test_shims_expose_makebokehapp()
    print("ALL DATA_BROWSER TESTS PASS")


if __name__ == "__main__":
    run_all()
