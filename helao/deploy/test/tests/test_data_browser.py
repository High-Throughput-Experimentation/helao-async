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

from helao.core.servers.data_browser import readers
from helao.core.servers.data_browser import sources
from helao.core.servers.data_browser import state as dbstate


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
        base = os.path.join(d, "RUNS_FINISHED")
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
        root, "RUNS_FINISHED", "26.25", "0618",
        "141523__SDC_seq__lab1", "260618.141524__SDC_exp_CV",
        "1__0__sim__cv",
    )
    os.makedirs(act_dir)
    _write_hlo(os.path.join(act_dir, "cv_data.hlo"))
    with open(os.path.join(act_dir, "260618.141525-act.yml"), "w") as f:
        yaml.safe_dump({
            "technique_name": "CV",
            "run_type": "data",
            "samples_out": [{"global_label": "solid__lab1_1"}],
        }, f)


def test_runs_finished_index():
    with tempfile.TemporaryDirectory() as d:
        _make_finished_tree(d)
        idx = sources.RunsSourceIndex(d, "FINISHED")
        df = idx.index()
        assert list(df.columns) == sources.INDEX_COLUMNS, list(df.columns)
        assert len(df) == 1, df
        r = df.iloc[0]
        assert r["source"] == "RUNS_FINISHED"
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
    day = os.path.join(root, "RUNS_SYNCED", "26.25", "0618")
    os.makedirs(day)
    with tempfile.TemporaryDirectory() as tmp:
        hlo = os.path.join(tmp, "cv_data.hlo")
        _write_hlo(hlo)
        actyml = os.path.join(tmp, "act.yml")
        with open(actyml, "w") as f:
            yaml.safe_dump({"technique_name": "CV",
                            "samples_out": [{"global_label": "solid__lab1_1"}]}, f)
        zpath = os.path.join(day, "141523__SDC_seq__lab1.zip")
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.write(actyml, "260618.141524__SDC_exp_CV/1__0__sim__cv/260618.141525-act.yml")
            zf.write(hlo, "260618.141524__SDC_exp_CV/1__0__sim__cv/cv_data.hlo")


def test_runs_synced_index():
    with tempfile.TemporaryDirectory() as d:
        _make_synced_zip(d)
        df = sources.RunsSourceIndex(d, "SYNCED").index()
        assert len(df) == 1, df
        r = df.iloc[0]
        assert r["source"] == "RUNS_SYNCED"
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
        root, "PROCESSES", "26.25", "0618",
        "141523__SDC_seq__lab1", "260618.141524__SDC_exp_CV",
    )
    os.makedirs(prc_dir)
    with open(os.path.join(prc_dir, "0__abc__CV-prc.yml"), "w") as f:
        yaml.safe_dump({
            "technique_name": "CV",
            "run_type": "data",
            "samples_out": [{"global_label": "solid__lab1_1"}],
            "files": [{"file_name": "cv_data.hlo", "file_type": "helao__file"}],
        }, f)


def test_processes_index_resolves_to_runs():
    with tempfile.TemporaryDirectory() as d:
        _make_finished_tree(d)   # the actual cv_data.hlo
        _make_process(d)         # the -prc.yml that references it
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
        yaml.safe_dump({
            "analysis_name": "icpms",
            "global_sample_label": "solid__lab1_1",
            "outputs": [{
                "analysis_output_path": {"bucket": "b", "key": "analysis/uuid1234/conc.json", "region": "r"},
                "content_type": "application/json",
                "output_type": "concentration",
                "output_name": "conc",
            }],
        }, f)
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
        df = sources.get_index(d, "RUNS_FINISHED", None, None)
        assert df.iloc[0]["source"] == "RUNS_FINISHED"
        empty = sources.get_index(d, "ANALYSES", None, None)
        assert list(empty.columns) == sources.INDEX_COLUMNS
        assert len(empty) == 0
    print("test_get_index_dispatch PASS")


def test_load_selected_end_to_end():
    with tempfile.TemporaryDirectory() as d:
        _make_finished_tree(d)
        _make_process(d)  # adds an unavailable-resolves-to-available process row too
        df = sources.get_index(d, "RUNS_FINISHED", None, None)
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
    base = dict(locator="L", source="RUNS_FINISHED", sequence="s", experiment="e",
                node="n", technique="CV", sample="smp", file_name="f.hlo", meta={})
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
    assert s["source"] == "RUNS_FINISHED" and s["technique"] == "CV"
    print("test_state PASS")


if __name__ == "__main__":
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
