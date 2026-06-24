"""Unit tests for the data_browser source indexers adapter."""
import json
import os
import tempfile
import zipfile

import yaml

from helao.framework.adapters.data_browser import sources, readers


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


def _make_synced_zip(root):
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


def _make_process(root):
    prc_dir = os.path.join(root, "PROCESSES", "26.25", "0618",
                           "141523__SDC_seq__lab1", "260618.141524__SDC_exp_CV")
    os.makedirs(prc_dir)
    with open(os.path.join(prc_dir, "0__abc__CV-prc.yml"), "w") as f:
        yaml.safe_dump({"technique_name": "CV", "run_type": "data",
                        "samples_out": [{"global_label": "solid__lab1_1"}],
                        "files": [{"file_name": "cv_data.hlo", "file_type": "helao__file"}]}, f)


def _make_analysis(root, with_local_output=True):
    ana_dir = os.path.join(root, "ANALYSES", "26.25", "0618", "150305__icpms__plate1")
    os.makedirs(ana_dir)
    with open(os.path.join(ana_dir, "uuid1234.yml"), "w") as f:
        yaml.safe_dump({"analysis_name": "icpms", "global_sample_label": "solid__lab1_1",
                        "outputs": [{"analysis_output_path": {"bucket": "b", "key": "analysis/uuid1234/conc.json", "region": "r"},
                                     "content_type": "application/json",
                                     "output_type": "concentration", "output_name": "conc"}]}, f)
    if with_local_output:
        with open(os.path.join(ana_dir, "conc.json"), "w") as f:
            json.dump({"element": ["Ni", "Fe"], "ppm": [12.0, 3.4]}, f)


def test_dir_walk_and_range():
    with tempfile.TemporaryDirectory() as d:
        base = os.path.join(d, "RUNS_FINISHED")
        for ww, mmdd in [("26.20", "0515"), ("26.25", "0618")]:
            os.makedirs(os.path.join(base, ww, mmdd))
        dates = [ds for ds, _ in sources._list_day_dirs(base)]
        assert dates == ["26.20/0515", "26.25/0618"]
        assert sources._in_range("26.25/0618", "26.22", "26.30") is True
        assert sources._in_range("26.20/0515", "26.22", "26.30") is False
        assert sources._in_range("26.25/0618", None, None) is True


def test_runs_finished_index():
    with tempfile.TemporaryDirectory() as d:
        _make_finished_tree(d)
        df = sources.RunsSourceIndex(d, "FINISHED").index()
        assert list(df.columns) == sources.INDEX_COLUMNS
        assert len(df) == 1
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


def test_runs_synced_index():
    with tempfile.TemporaryDirectory() as d:
        _make_synced_zip(d)
        df = sources.RunsSourceIndex(d, "SYNCED").index()
        assert len(df) == 1
        r = df.iloc[0]
        assert r["source"] == "RUNS_SYNCED"
        assert r["sequence"] == "SDC_seq"
        assert r["locator"].startswith("zip::")
        _, data = readers.read_dataset(r["locator"], r["file_type"])
        assert data["Ewe_V"] == [0.1, 0.2]


def test_processes_index_resolves_to_runs():
    with tempfile.TemporaryDirectory() as d:
        _make_finished_tree(d)
        _make_process(d)
        df = sources.DerivedSourceIndex(d, "PROCESSES").index()
        assert len(df) == 1
        r = df.iloc[0]
        assert r["source"] == "PROCESSES"
        assert r["sample"] == "solid__lab1_1"
        assert r["available"] is True
        _, data = readers.read_dataset(r["locator"], r["file_type"])
        assert data["t_s"] == [0.0, 1.0]


def test_processes_index_missing_file_unavailable():
    with tempfile.TemporaryDirectory() as d:
        _make_process(d)
        df = sources.DerivedSourceIndex(d, "PROCESSES").index()
        assert len(df) == 1
        assert df.iloc[0]["available"] is False
        assert df.iloc[0]["locator"] == ""


def test_analyses_index_local():
    with tempfile.TemporaryDirectory() as d:
        _make_analysis(d, with_local_output=True)
        df = sources.DerivedSourceIndex(d, "ANALYSES").index()
        assert len(df) == 1
        r = df.iloc[0]
        assert r["source"] == "ANALYSES"
        assert r["sequence"] == "icpms"
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


def test_get_index_dispatch():
    with tempfile.TemporaryDirectory() as d:
        _make_finished_tree(d)
        df = sources.get_index(d, "RUNS_FINISHED", None, None)
        assert df.iloc[0]["source"] == "RUNS_FINISHED"
        empty = sources.get_index(d, "ANALYSES", None, None)
        assert list(empty.columns) == sources.INDEX_COLUMNS
        assert len(empty) == 0
